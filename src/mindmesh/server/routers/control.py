"""Control Room: policies, approvals, blocked actions, tool + agent registry."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field

from ...core.events import EventType
from ...core.types import Approval, ApprovalResolve, PolicyDecision, PolicyRule, PolicyRuleIn
from ...policy.rules import dump_rules
from ...sdk import MindMesh
from ..deps import project_mm

router = APIRouter(tags=["control"])


class PolicyYaml(BaseModel):
    model_config = ConfigDict(extra="forbid")
    yaml: str = Field(max_length=200_000)


class Simulate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    agent: str


@router.get("/policies", response_model=list[PolicyRule])
async def list_policies(mm: MindMesh = Depends(project_mm)):
    return await mm.repos.policies.list()


@router.post("/policies", response_model=PolicyRule, status_code=201)
async def create_policy(body: PolicyRuleIn, mm: MindMesh = Depends(project_mm)):
    return await mm.repos.policies.create(body)


@router.get("/policies/yaml")
async def get_policies_yaml(mm: MindMesh = Depends(project_mm)):
    return {"yaml": dump_rules(await mm.repos.policies.list())}


@router.put("/policies/yaml", response_model=list[PolicyRule])
async def put_policies_yaml(body: PolicyYaml, mm: MindMesh = Depends(project_mm)):
    return await mm.load_policies(body.yaml, replace=True)


@router.post("/policies/simulate", response_model=PolicyDecision)
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
async def update_policy(policy_id: str, body: PolicyRuleIn, mm: MindMesh = Depends(project_mm)):
    return await mm.repos.policies.update(policy_id, body)


@router.delete("/policies/{policy_id}", status_code=204)
async def delete_policy(policy_id: str, mm: MindMesh = Depends(project_mm)):
    await mm.repos.policies.delete(policy_id)


@router.get("/approvals", response_model=list[Approval])
async def list_approvals(status: str | None = None, run_id: str | None = None, mm: MindMesh = Depends(project_mm)):
    return await mm.repos.approvals.list(status=status, run_id=run_id)


@router.post("/approvals/{approval_id}/resolve", response_model=Approval)
async def resolve_approval(approval_id: str, body: ApprovalResolve, mm: MindMesh = Depends(project_mm)):
    appr, _ = await mm.resolve_approval(approval_id, body.approve, resolver=body.resolver, note=body.note, wait=False)
    return appr


@router.get("/blocked-actions")
async def blocked_actions(limit: int = Query(200, le=1000), mm: MindMesh = Depends(project_mm)):
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
