from datetime import timedelta

import pytest

from mindmesh.core import clock
from mindmesh.core.types import ContextConfig, ExclusionReason, MemoryCreate, MemoryUpdate, Provenance


async def test_subject_versioning_supersedes_within_scope(mm):
    a = await mm.memory.add(MemoryCreate(content="Deploys happen on Tuesdays.", subject_key="deploy_day"))
    b = await mm.memory.add(MemoryCreate(content="Deploys happen on Thursdays.", subject_key="deploy_day"))
    assert b.lineage_id == a.lineage_id and b.version == 2 and b.supersedes_id == a.id
    assert (await mm.memory.get(a.id)).status == "superseded"
    assert [m.version for m in await mm.memory.versions(b.id)] == [1, 2]


async def test_identical_write_is_idempotent(mm):
    a = await mm.memory.add(MemoryCreate(content="Office is in Lisbon.", subject_key="office"))
    b = await mm.memory.add(MemoryCreate(content="office is in  lisbon.", subject_key="office"))
    assert a.id == b.id


async def test_edit_creates_version_and_scope_move_supersedes_target_scope(mm):
    old = await mm.memory.add(MemoryCreate(content="Window is 14 days.", subject_key="window"))
    priv = await mm.memory.add(MemoryCreate(content="Window is 30 days.", subject_key="window", scope="agent:billing"))
    assert (await mm.memory.get(old.id)).status == "active"  # different scopes: both active -> conflict
    assert len(await mm.memory.conflicts()) == 1
    moved = await mm.memory.update(priv.id, MemoryUpdate(scope="project", reason="applies to everyone"))
    assert moved.version == 2 and moved.scope == "project"
    assert (await mm.memory.get(priv.id)).status == "superseded"
    assert (await mm.memory.get(old.id)).status == "superseded"
    assert await mm.memory.conflicts() == []


async def test_cannot_edit_inactive_memory(mm):
    m = await mm.memory.add(MemoryCreate(content="x fact", subject_key="x"))
    await mm.memory.retract(m.id, "wrong")
    with pytest.raises(ValueError):
        await mm.memory.update(m.id, MemoryUpdate(content="y"))


async def test_retract_and_expire(mm):
    m = await mm.memory.add(MemoryCreate(content="Temporary promo code SPRING", expires_at=clock.now() + timedelta(days=1)))
    r = await mm.memory.retract(m.id, "leaked", by="sec")
    assert r.status == "retracted" and "leaked" in r.status_reason
    m2 = await mm.memory.add(MemoryCreate(content="Old promo WINTER", expires_at=clock.now() + timedelta(seconds=1)))
    clock.freeze(clock.now() + timedelta(days=2))
    assert await mm.memory.expire_due() == 1
    assert (await mm.memory.get(m2.id)).status == "expired"


async def test_hybrid_search_ranks_relevant_first(mm):
    await mm.memory.add(MemoryCreate(content="The refund window for premium customers is 30 days."))
    await mm.memory.add(MemoryCreate(content="Our office plants are watered on Fridays."))
    hits = await mm.memory.search("how many days is the refund window", k=2)
    assert "refund" in hits[0].memory.content
    assert hits[0].relevance > hits[1].relevance


async def test_receipt_explains_every_exclusion(mm):
    now = clock.now()
    await mm.memory.add(MemoryCreate(content="Refund policy: 14 day refund window.", subject_key="refund"))
    await mm.memory.add(MemoryCreate(content="Refund policy: 30 day refund window.", subject_key="refund"))  # supersedes
    await mm.memory.add(MemoryCreate(content="Refund policy for billing: 45 day refund window.", subject_key="refund",
                                     scope="agent:billing"))
    r = await mm.memory.add(MemoryCreate(content="Refund exceptions require manager sign-off for refunds."))
    await mm.memory.retract(r.id, "outdated")
    await mm.memory.add(MemoryCreate(content="Refund vouchers expire.", expires_at=now + timedelta(seconds=5)))
    clock.freeze(now + timedelta(minutes=1))
    rc = await mm.context.assemble(query="refund window policy", config=ContextConfig(), scopes=["project"])
    reasons = {(i.subject_key, i.reason) for i in rc.excluded}
    assert ("refund", ExclusionReason.SUPERSEDED) in reasons
    assert ("refund", ExclusionReason.SCOPE_MISMATCH) in reasons
    assert any(i.reason == ExclusionReason.RETRACTED for i in rc.excluded)
    assert any(i.reason == ExclusionReason.EXPIRED for i in rc.excluded)
    assert [i.content for i in rc.included if i.subject_key == "refund"] == ["Refund policy: 30 day refund window."]


async def test_conflict_resolution_prefers_trust(mm):
    await mm.memory.add(MemoryCreate(content="Server region is eu-west-1.", subject_key="region", trust=0.9))
    await mm.memory.add(MemoryCreate(content="Server region is us-east-1.", subject_key="region", scope="agent:ops",
                                     trust=0.4))
    rc = await mm.context.assemble(query="which server region", config=ContextConfig(),
                                   scopes=["project", "agent:ops"])
    inc = [i.content for i in rc.included if i.subject_key == "region"]
    assert inc == ["Server region is eu-west-1."]
    assert any(i.reason == ExclusionReason.CONFLICT_LOST for i in rc.excluded)


async def test_budget_is_respected_and_reported(mm):
    for i in range(10):
        await mm.memory.add(MemoryCreate(content=f"Deployment fact number {i}: deployment uses blue green strategy."))
    cfg = ContextConfig(budget_tokens=80, min_relevance=0.0)
    rc = await mm.context.assemble(query="deployment strategy", config=cfg, scopes=["project"])
    assert rc.used_tokens <= 80
    assert any(i.reason == ExclusionReason.BUDGET for i in rc.excluded)


async def test_naive_strategy_ignores_status_and_scope(mm):
    m = await mm.memory.add(MemoryCreate(content="Refund window is 14 days.", subject_key="w"))
    await mm.memory.add(MemoryCreate(content="Refund window is 30 days.", subject_key="w"))
    rc = await mm.context.assemble(query="refund window", config=ContextConfig(strategy="naive"), scopes=["project"])
    assert rc.included[0].item_id == m.id  # stale, superseded memory first: the failure mode MindMesh fixes


async def test_retrievals_are_recorded(mm):
    m = await mm.memory.add(MemoryCreate(content="Escalate legal threats to a supervisor.",
                                         provenance=Provenance(source_type="import", source_ref="kb.md")))
    await mm.context.assemble(query="legal threat escalation", config=ContextConfig(), scopes=["project"], run_id="run_x")
    hist = await mm.memory.retrievals(m.id)
    assert hist and hist[0]["run_id"] == "run_x" and hist[0]["included"]
    assert (await mm.memory.get(m.id)).retrieval_count == 1
