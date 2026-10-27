"""Explain a policy change before it is applied.

Diffs the current rules against a proposed rule set, then re-evaluates the tool calls agents actually proposed
(recorded ``policy.decision`` events) under both, so a reviewer sees which past decisions would flip and which
rule would be responsible. Per-run call counts are rebuilt from the log in order, so rate-limit rules are
evaluated against the same history they saw at run time.
"""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING, Any

from ..core.events import EventType
from ..core.types import AgentSpec, PolicyDecision, PolicyEffect, PolicyRuleIn
from .engine import PolicyEngine

if TYPE_CHECKING:
    from ..sdk import MindMesh

MAX_DECISIONS = 500
MAX_CHANGES = 50
ENFORCEMENT_OFF = "policy enforcement disabled for this agent"


def _comparable(r: PolicyRuleIn) -> dict[str, Any]:
    return PolicyRuleIn.model_validate(r.model_dump(include=set(PolicyRuleIn.model_fields))).model_dump(mode="json")


def _rule_diff(current: list[PolicyRuleIn], proposed: list[PolicyRuleIn]) -> list[dict[str, Any]]:
    cur, new = {r.name: _comparable(r) for r in current}, {r.name: _comparable(r) for r in proposed}
    out: list[dict[str, Any]] = []
    for name in [*cur, *(n for n in new if n not in cur)]:
        a, b = cur.get(name), new.get(name)
        if a is None:
            out.append({"rule": name, "change": "added", "after": b})
        elif b is None:
            out.append({"rule": name, "change": "removed", "before": a})
        elif a != b:
            fields = [k for k in a if a[k] != b[k]]
            out.append({"rule": name, "change": "modified", "fields": fields,
                        "before": {k: a[k] for k in fields}, "after": {k: b[k] for k in fields}})
    return out


def _brief(d: PolicyDecision) -> dict[str, Any]:
    return {"effect": d.effect.value, "rule_name": d.rule_name, "reason": d.reason}


async def policy_change_impact(mm: MindMesh, proposed: list[PolicyRuleIn]) -> dict[str, Any]:
    current = await mm.repos.policies.list()
    engines = {
        "before": PolicyEngine(current, default_effect=mm.default_policy_effect),
        "after": PolicyEngine(proposed, default_effect=mm.default_policy_effect),
    }
    events = await mm.repos.events.by_type([EventType.POLICY_DECISION], limit=MAX_DECISIONS)
    by_run: dict[str, list] = defaultdict(list)
    for e in events:
        by_run[e.run_id].append(e)

    evaluated = unchanged = 0
    changes: list[dict[str, Any]] = []
    tally: dict[str, int] = defaultdict(int)
    for run_id, evs in by_run.items():
        run = await mm.repos.runs.get(run_id)
        if run.kind == "replay":
            continue  # replays reuse the original run's decisions
        spec = AgentSpec.model_validate(run.config["agent_spec"])
        calls: dict[str, int] = {}
        for e in sorted(evs, key=lambda x: x.seq):
            p = e.payload
            tool, args = p.get("tool"), p.get("args") or {}
            recorded_allowed = p.get("effect") == PolicyEffect.ALLOW.value
            if p.get("reason") == ENFORCEMENT_OFF or str(p.get("rule_name") or "").startswith(("guard.", "budget.")):
                # not decided by policy rules: enforcement was off, or a runtime guard/budget stopped the call
                calls[tool] = calls.get(tool, 0) + recorded_allowed
                continue
            kw = {"agent": spec.name, "role": spec.role, "allowed_tools": spec.tools, "calls_so_far": dict(calls)}
            before, after = (engines[k].evaluate(tool, args, **kw) for k in ("before", "after"))
            calls[tool] = calls.get(tool, 0) + recorded_allowed
            evaluated += 1
            if before.effect == after.effect:
                unchanged += 1
                continue
            tally[f"{before.effect.value}->{after.effect.value}"] += 1
            if len(changes) < MAX_CHANGES:
                changes.append({"run_id": run_id, "agent": spec.name, "kind": run.kind, "step": e.step, "tool": tool,
                                "args": args, "before": _brief(before), "after": _brief(after)})

    return {
        "rules": _rule_diff(current, proposed),
        "evaluated": evaluated,
        "unchanged": unchanged,
        "changed": sum(tally.values()),
        "transitions": dict(tally),
        "changes": changes,
        "note": "Past tool calls re-evaluated against both rule sets. Calls the agent never proposed are not "
                "covered, and agent behaviour after a different decision is not simulated.",
    }
