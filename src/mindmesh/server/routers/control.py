"""Control Room: policies, approvals, blocked actions, tool + agent registry."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from ...core.events import EventType
from ...core.types import Approval, ApprovalResolve, PolicyDecision, PolicyRule, PolicyRuleIn
from ...policy.impact import policy_change_impact
from ...policy.rules import dump_rules, load_rules
from ...sdk import MindMesh
from ..deps import allow_read_only, audit, project_mm

router = APIRouter(tags=["control"])


class PolicyYaml(BaseModel):
    model_config = ConfigDict(extra="forbid")
    yaml: str = Field(max_length=200_000)


class PolicyImpact(BaseModel):
    """A proposed rule set: full YAML (as the editor saves it), or the current rules with some disabled."""

    model_config = ConfigDict(extra="forbid")
    yaml: str | None = Field(default=None, max_length=200_000)
    disable: list[str] | None = None


class Simulate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    agent: str


@router.get("/policies", response_model=list[PolicyRule])
async def list_policies(mm: MindMesh = Depends(project_mm)):
    return await mm.repos.policies.list()


@router.post("/policies", response_model=PolicyRule, status_code=201)
async def create_policy(body: PolicyRuleIn, request: Request, mm: MindMesh = Depends(project_mm)):
    rule = await mm.repos.policies.create(body)
    await audit(request, mm, "policy.created", "policy", rule.id, f"created rule '{rule.name}' ({rule.effect})",
                rule=body.model_dump(mode="json"))
    return rule


@router.get("/policies/yaml")
async def get_policies_yaml(mm: MindMesh = Depends(project_mm)):
    return {"yaml": dump_rules(await mm.repos.policies.list())}


@router.put("/policies/yaml", response_model=list[PolicyRule])
async def put_policies_yaml(body: PolicyYaml, request: Request, mm: MindMesh = Depends(project_mm)):
    fields = set(PolicyRuleIn.model_fields)
    before = {r.name: r.model_dump(mode="json", include=fields) for r in await mm.repos.policies.list()}
    rules = await mm.load_policies(body.yaml, replace=True)
    after = {r.name: r.model_dump(mode="json", include=fields) for r in rules}
    added, removed = sorted(after.keys() - before.keys()), sorted(before.keys() - after.keys())
    changed = sorted(n for n in after.keys() & before.keys() if after[n] != before[n])
    parts = [f"{len(x)} {w}" for x, w in ((added, "added"), (changed, "changed"), (removed, "removed")) if x]
    await audit(request, mm, "policy.replaced", "policy", None,
                f"saved policy YAML: {', '.join(parts) or 'no rule changes'}",
                added=added, changed=changed, removed=removed, yaml=body.yaml)
    return rules


@router.post("/policies/impact")
@allow_read_only
async def policy_impact(body: PolicyImpact, mm: MindMesh = Depends(project_mm)):
    """Explain a policy change before applying it: rule diff, and which recorded tool calls would be decided
    differently (and by which rule). Nothing is written."""
    if (body.yaml is None) == (body.disable is None):
        raise ValueError("send either 'yaml' (a proposed rule set) or 'disable' (rule names)")
    if body.yaml is not None:
        proposed = load_rules(body.yaml)
    else:
        current = await mm.repos.policies.list()
        unknown = set(body.disable or []) - {r.name for r in current}
        if unknown:
            raise ValueError(f"unknown rules: {sorted(unknown)}")
        proposed = [PolicyRuleIn.model_validate(r.model_dump(include=set(PolicyRuleIn.model_fields)))
                    .model_copy(update={"enabled": r.enabled and r.name not in body.disable}) for r in current]
    return await policy_change_impact(mm, proposed)


@router.post("/policies/simulate", response_model=PolicyDecision)
@allow_read_only
async def simulate_policy(body: Simulate, mm: MindMesh = Depends(project_mm)):
    """Evaluate a hypothetical tool call against current rules (arguments validated first)."""
    spec = mm.agents.get(body.agent)
    if spec is None:
        raise ValueError(f"unknown agent {body.agent!r}")
    tool = mm.tools.get(body.tool)
    args = tool.validate(body.args) if tool else body.args
    engine = await mm.refresh_policies()
    return engine.evaluate(body.tool, args, agent=spec.name, role=spec.role, allowed_tools=spec.tools)


@router.put("/policies/{policy_id}", response_model=PolicyRule)
async def update_policy(policy_id: str, body: PolicyRuleIn, request: Request, mm: MindMesh = Depends(project_mm)):
    before = next((r for r in await mm.repos.policies.list() if r.id == policy_id), None)
    rule = await mm.repos.policies.update(policy_id, body)
    old = before.model_dump(mode="json", include=set(PolicyRuleIn.model_fields)) if before else {}
    new = body.model_dump(mode="json")
    changes = {k: {"before": old.get(k), "after": v} for k, v in new.items() if old.get(k) != v}
    if list(changes) == ["enabled"]:
        what = "enabled" if new["enabled"] else "disabled"
    else:
        what = f"updated ({', '.join(changes) or 'no changes'})"
    await audit(request, mm, "policy.updated", "policy", policy_id, f"rule '{rule.name}' {what}", changes=changes)
    return rule


@router.delete("/policies/{policy_id}", status_code=204)
async def delete_policy(policy_id: str, request: Request, mm: MindMesh = Depends(project_mm)):
    before = next((r for r in await mm.repos.policies.list() if r.id == policy_id), None)
    await mm.repos.policies.delete(policy_id)
    await audit(request, mm, "policy.deleted", "policy", policy_id,
                f"deleted rule '{before.name if before else policy_id}'",
                rule=before.model_dump(mode="json") if before else None)


@router.get("/approvals", response_model=list[Approval])
async def list_approvals(status: str | None = None, run_id: str | None = None, mm: MindMesh = Depends(project_mm)):
    return await mm.repos.approvals.list(status=status, run_id=run_id)


@router.post("/approvals/{approval_id}/resolve", response_model=Approval)
async def resolve_approval(approval_id: str, body: ApprovalResolve, request: Request,
                           mm: MindMesh = Depends(project_mm)):
    appr, _ = await mm.resolve_approval(approval_id, body.approve, resolver=body.resolver, note=body.note, wait=False)
    verdict = "approved" if body.approve else "rejected"
    await audit(request, mm, f"approval.{verdict}", "approval", approval_id,
                f"{verdict} {appr.tool} in run {appr.run_id} step {appr.step} (as {body.resolver})",
                run_id=appr.run_id, step=appr.step, tool=appr.tool, args=appr.args, note=body.note,
                resolver=body.resolver)
    return appr


@router.get("/audit")
async def audit_trail(target_type: str | None = None, limit: int = Query(200, ge=1, le=1000),
                      mm: MindMesh = Depends(project_mm)):
    """Changes made through the API, newest first: policies, approvals, memories, keys, experiment resets."""
    return [{"id": r.id, "ts": r.created_at, "actor": r.actor, "action": r.action, "target_type": r.target_type,
             "target_id": r.target_id, "summary": r.summary, "details": r.details}
            for r in await mm.repos.audit.list(target_type=target_type, limit=limit)]


@router.get("/blocked-actions")
async def blocked_actions(limit: int = Query(200, ge=1, le=1000), mm: MindMesh = Depends(project_mm)):
    events = await mm.repos.events.by_type([EventType.POLICY_DECISION, EventType.GUARD_TRIGGERED], limit=limit * 3)
    out = []
    for e in events:
        effect = e.payload.get("effect")
        if e.type == EventType.POLICY_DECISION and effect == "allow":
            continue
        out.append({"event_id": e.id, "run_id": e.run_id, "step": e.step, "ts": e.ts, "type": e.type, **e.payload})
        if len(out) >= limit:
            break
    return out


@router.get("/tools")
async def list_tools(mm: MindMesh = Depends(project_mm)):
    return [t.json_schema() | {"timeout_s": t.timeout_s, "tags": t.tags} for t in mm.tools.specs()]


@router.get("/agents")
async def list_agents(mm: MindMesh = Depends(project_mm)):
    return [a.model_dump(mode="json") for a in mm.agents.values()]
