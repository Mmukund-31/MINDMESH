"""Adaptive context assembly under a token budget, with an explainable receipt.

Pipeline (``ranked`` strategy)::

    candidates (vector+keyword) -> hard filters (status, expiry, scope, relevance)
        -> conflict resolution (per subject_key) -> weighted scoring
        -> greedy packing under the token budget -> ContextReceipt

The ``naive`` strategy reproduces what most agent stacks do: stuff memories in
insertion order until the window is full, ignoring status, scope and relevance.
It exists so benchmarks can quantify what the ranked pipeline buys you.
"""

from __future__ import annotations

from ..core import clock
from ..core.ids import new_id
from ..core.types import (
    ContextConfig,
    ContextItem,
    ContextReceipt,
    ExclusionReason,
    MemoryStatus,
    ScoreBreakdown,
)
from ..embeddings import tokenize
from ..memory.store import MemoryStore, keyword_score, scope_visible
from ..models.base import estimate_tokens
from ..storage.orm import MemoryRow
from ..storage.vector import cosine

ITEM_OVERHEAD_TOKENS = 4
MAX_LOW_RELEVANCE_REPORTED = 5


def item_tokens(text: str) -> int:
    return estimate_tokens(text) + ITEM_OVERHEAD_TOKENS


class ContextEngine:
    def __init__(self, memory: MemoryStore):
        self.memory = memory

    async def assemble(
        self,
        *,
        query: str,
        config: ContextConfig,
        scopes: list[str],
        run_id: str | None = None,
        step: int = 0,
        pinned: list[ContextItem] | None = None,
        evidence: list[ContextItem] | None = None,
        record: bool = True,
    ) -> ContextReceipt:
        receipt_id = new_id("rcpt")
        pinned = pinned or []
        evidence = evidence or []
        included: list[ContextItem] = []
        excluded: list[ContextItem] = []
        used = 0
        for p in pinned:  # task + instructions are always in context
            p.tokens = p.tokens or item_tokens(p.content)
            used += p.tokens
            included.append(p)

        if config.use_memory:
            [qvec] = await self.memory.embedder.embed([query])
            qtok = set(tokenize(query))
            rows = await self.memory.repo.nearest(qvec, k=config.max_candidates)
            if config.strategy == "naive":
                cands, rejected = self._naive(rows, qtok)
            else:
                cands, rejected = self._filter_and_score(rows, qtok, config, scopes)
            excluded.extend(rejected)
        else:
            cands = []

        for ev in evidence:
            if not ev.score.total:
                rel = keyword_score(set(tokenize(query)), ev.content)
                ev.score = ScoreBreakdown(relevance=rel, trust=0.8, importance=0.7, total=0.6 + 0.4 * rel)
            ev.tokens = ev.tokens or item_tokens(ev.content)
            cands.append(ev)

        if config.strategy != "naive":
            cands.sort(key=lambda c: c.score.total, reverse=True)
        for c in cands:
            if used + c.tokens <= config.budget_tokens:
                used += c.tokens
                c.included, c.reason = True, None
                included.append(c)
            else:
                c.included, c.reason = False, ExclusionReason.BUDGET
                c.detail = f"needs {c.tokens} tokens, {config.budget_tokens - used} left"
                excluded.append(c)

        receipt = ContextReceipt(
            receipt_id=receipt_id,
            run_id=run_id,
            step=step,
            query=query[:2000],
            strategy=config.strategy,
            budget_tokens=config.budget_tokens,
            used_tokens=used,
            included=included,
            excluded=excluded,
            created_at=clock.now(),
        )
        if record:
            await self.memory.repo.record_retrievals(
                run_id,
                receipt_id,
                query,
                [
                    {
                        "memory_id": i.item_id,
                        "score": i.score.total,
                        "included": i.included,
                        "reason": i.reason.value if i.reason else None,
                    }
                    for i in included + excluded
                    if i.kind == "memory"
                ],
            )
        return receipt

    # ------------------------------------------------------------------ strategies

    def _naive(self, rows: list[tuple[MemoryRow, float]], qtok: set[str]):
        items = []
        for row, sim in sorted(rows, key=lambda t: (clock.ensure_aware(t[0].created_at), t[0].id)):
            rel = 0.65 * max(sim, 0) + 0.35 * keyword_score(qtok, f"{row.subject_key or ''} {row.content}")
            items.append(self._item(row, ScoreBreakdown(relevance=rel, total=rel)))
        return items, []

    def _filter_and_score(
        self, rows: list[tuple[MemoryRow, float]], qtok: set[str], cfg: ContextConfig, scopes: list[str]
    ) -> tuple[list[ContextItem], list[ContextItem]]:
        now = clock.now()
        eligible: list[tuple[MemoryRow, ScoreBreakdown]] = []
        rejected: list[ContextItem] = []
        low: list[ContextItem] = []
        for row, sim in rows:
            kw = keyword_score(qtok, f"{row.subject_key or ''} {row.content}")
            rel = 0.65 * max(sim, 0.0) + 0.35 * kw
            age_days = max((now - clock.ensure_aware(row.valid_from)).total_seconds() / 86400, 0.0)
            score = ScoreBreakdown(
                relevance=rel,
                recency=0.5 ** (age_days / cfg.recency_half_life_days),
                importance=row.importance,
                trust=row.trust,
            )
            score.total = (
                cfg.w_relevance * score.relevance
                + cfg.w_recency * score.recency
                + cfg.w_importance * score.importance
                + cfg.w_trust * score.trust
            )
            reason, detail = self._hard_filter(row, rel, cfg, scopes, now)
            if reason is None:
                eligible.append((row, score))
            elif reason == ExclusionReason.LOW_RELEVANCE:
                low.append(self._item(row, score, reason, detail))
            elif rel >= cfg.min_relevance * 0.5:  # only report exclusions that could have mattered
                rejected.append(self._item(row, score, reason, detail))

        # Conflict resolution: one winner per subject_key.
        by_subject: dict[str, list[tuple[MemoryRow, ScoreBreakdown]]] = {}
        keep: list[ContextItem] = []
        for row, score in eligible:
            if row.subject_key:
                by_subject.setdefault(row.subject_key, []).append((row, score))
            else:
                keep.append(self._item(row, score))
        for key, group in by_subject.items():
            group.sort(key=lambda t: (t[0].trust, clock.ensure_aware(t[0].valid_from)), reverse=True)
            winner = group[0][0]
            keep.append(self._item(*group[0]))
            for row, score in group[1:]:
                if row.content.strip().lower() == winner.content.strip().lower():
                    continue  # duplicate of the winner, not a conflict
                rejected.append(
                    self._item(
                        row,
                        score,
                        ExclusionReason.CONFLICT_LOST,
                        f"conflicts with {winner.id} on '{key}' (lower trust or older)",
                    )
                )
        low.sort(key=lambda i: i.score.relevance, reverse=True)
        return keep, rejected + low[:MAX_LOW_RELEVANCE_REPORTED]

    @staticmethod
    def _hard_filter(row: MemoryRow, rel: float, cfg: ContextConfig, scopes: list[str], now):
        if row.status == MemoryStatus.RETRACTED.value:
            return ExclusionReason.RETRACTED, row.status_reason
        if row.status == MemoryStatus.SUPERSEDED.value:
            return ExclusionReason.SUPERSEDED, row.status_reason
        exp = clock.ensure_aware(row.expires_at)
        if row.status == MemoryStatus.EXPIRED.value or (exp is not None and exp <= now):
            return ExclusionReason.EXPIRED, f"expired at {exp.isoformat() if exp else '?'}"
        if not scope_visible(row.scope, scopes):
            return ExclusionReason.SCOPE_MISMATCH, f"scope '{row.scope}' not in {scopes}"
        if rel < cfg.min_relevance:
            return ExclusionReason.LOW_RELEVANCE, f"relevance {rel:.2f} < {cfg.min_relevance:.2f}"
        return None, None

    @staticmethod
    def _item(row: MemoryRow, score: ScoreBreakdown, reason: ExclusionReason | None = None, detail: str | None = None):
        return ContextItem(
            item_id=row.id,
            kind="memory",
            content=row.content,
            tokens=item_tokens(row.content),
            subject_key=row.subject_key,
            scope=row.scope,
            source=f"{row.source_type}:{row.source_ref or row.created_by} (v{row.version}, {row.status})",
            score=score,
            included=reason is None,
            reason=reason,
            detail=detail,
        )


__all__ = ["ContextEngine", "cosine", "item_tokens"]
