from __future__ import annotations

from typing import Any

from sqlalchemy import select

from ...core import clock
from ...core.errors import NotFound
from ...core.ids import new_id
from ...core.state import ApprovalStatus, transition
from ...core.types import Approval, PolicyRule, PolicyRuleIn
from ..orm import ApprovalRow, PolicyRow
from .base import ScopedRepo


class PolicyRepo(ScopedRepo):
    async def create(self, rule: PolicyRuleIn) -> PolicyRule:
        data = rule.model_dump(mode="json")
        row = PolicyRow(id=new_id("pol"), project_id=self.project_id, **data)
        async with self.db.session() as s:
            s.add(row)
        return PolicyRule.model_validate(row)

    async def update(self, policy_id: str, rule: PolicyRuleIn) -> PolicyRule:
        async with self.db.session() as s:
            row = await s.get(PolicyRow, policy_id)
            if row is None or row.project_id != self.project_id:
                raise NotFound(f"policy {policy_id} not found")
            for k, v in rule.model_dump(mode="json").items():
                setattr(row, k, v)
            await s.flush()
            return PolicyRule.model_validate(row)

    async def delete(self, policy_id: str) -> None:
        async with self.db.session() as s:
            row = await s.get(PolicyRow, policy_id)
            if row is None or row.project_id != self.project_id:
                raise NotFound(f"policy {policy_id} not found")
            await s.delete(row)

    async def get(self, policy_id: str) -> PolicyRule:
        async with self.db.session() as s:
            row = await s.get(PolicyRow, policy_id)
            if row is None or row.project_id != self.project_id:
                raise NotFound(f"policy {policy_id} not found")
            return PolicyRule.model_validate(row)

    async def list(self, *, enabled_only: bool = False) -> list[PolicyRule]:
        q = select(PolicyRow).where(PolicyRow.project_id == self.project_id)
        if enabled_only:
            q = q.where(PolicyRow.enabled.is_(True))
        q = q.order_by(PolicyRow.priority, PolicyRow.created_at)
        async with self.db.session() as s:
            return [PolicyRule.model_validate(r) for r in (await s.execute(q)).scalars()]

    async def replace_all(self, rules: list[PolicyRuleIn]) -> list[PolicyRule]:
        async with self.db.session() as s:
            for row in (await s.execute(select(PolicyRow).where(PolicyRow.project_id == self.project_id))).scalars():
                await s.delete(row)
        return [await self.create(r) for r in rules]


class ApprovalRepo(ScopedRepo):
    async def create(self, run_id: str, step: int, tool: str, args: dict[str, Any], reason: str) -> Approval:
        row = ApprovalRow(
            id=new_id("apr"),
            project_id=self.project_id,
            run_id=run_id,
            step=step,
            tool=tool,
            args=args,
            reason=reason,
            status=ApprovalStatus.PENDING.value,
        )
        async with self.db.session() as s:
            s.add(row)
        return Approval.model_validate(row)

    async def get(self, approval_id: str) -> Approval:
        async with self.db.session() as s:
            row = await s.get(ApprovalRow, approval_id)
            if row is None or row.project_id != self.project_id:
                raise NotFound(f"approval {approval_id} not found")
            return Approval.model_validate(row)

    async def resolve(self, approval_id: str, approve: bool, resolver: str, note: str | None) -> Approval:
        async with self.db.session() as s:
            row = await s.get(ApprovalRow, approval_id)
            if row is None or row.project_id != self.project_id:
                raise NotFound(f"approval {approval_id} not found")
            dst = ApprovalStatus.APPROVED if approve else ApprovalStatus.REJECTED
            row.status = transition(ApprovalStatus(row.status), dst).value
            row.resolved_at = clock.now()
            row.resolver = resolver
            row.note = note
            await s.flush()
            return Approval.model_validate(row)

    async def list(self, *, status: str | None = None, run_id: str | None = None, limit: int = 100) -> list[Approval]:
        q = select(ApprovalRow).where(ApprovalRow.project_id == self.project_id)
        if status:
            q = q.where(ApprovalRow.status == status)
        if run_id:
            q = q.where(ApprovalRow.run_id == run_id)
        q = q.order_by(ApprovalRow.requested_at.desc()).limit(limit)
        async with self.db.session() as s:
            return [Approval.model_validate(r) for r in (await s.execute(q)).scalars()]
