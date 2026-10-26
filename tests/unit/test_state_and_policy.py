import pytest

from mindmesh.core.errors import InvalidTransition
from mindmesh.core.state import ApprovalStatus, RunStatus, TaskStatus, can_transition, transition
from mindmesh.core.types import Condition, PolicyEffect, PolicyRuleIn
from mindmesh.policy.engine import PolicyEngine, condition_matches
from mindmesh.policy.redact import MASK, Redactor
from mindmesh.policy.rules import dump_rules, load_rules


def test_run_state_machine_allows_documented_path():
    s = RunStatus.PENDING
    for nxt in (RunStatus.RUNNING, RunStatus.WAITING_APPROVAL, RunStatus.RUNNING, RunStatus.SUCCEEDED):
        s = transition(s, nxt)
    assert s == RunStatus.SUCCEEDED


@pytest.mark.parametrize(
    "src,dst",
    [
        (RunStatus.SUCCEEDED, RunStatus.RUNNING),
        (RunStatus.CANCELLED, RunStatus.RUNNING),
        (RunStatus.PENDING, RunStatus.SUCCEEDED),
        (RunStatus.FAILED, RunStatus.WAITING_APPROVAL),
    ],
)
def test_illegal_run_transitions_raise(src, dst):
    with pytest.raises(InvalidTransition):
        transition(src, dst)


def test_task_and_approval_transitions():
    assert can_transition(TaskStatus.SUCCEEDED, TaskStatus.READY)  # verifier re-open
    assert not can_transition(TaskStatus.FAILED, TaskStatus.READY)
    assert transition(ApprovalStatus.PENDING, ApprovalStatus.APPROVED) == ApprovalStatus.APPROVED
    with pytest.raises(InvalidTransition):
        transition(ApprovalStatus.APPROVED, ApprovalStatus.REJECTED)


def rule(name, effect, **kw):
    return PolicyRuleIn(name=name, effect=effect, **kw)


def test_policy_first_match_by_priority():
    eng = PolicyEngine(
        [
            rule("approve-big", PolicyEffect.REQUIRE_APPROVAL, tools=["pay.*"],
                 conditions=[Condition(arg="amount", op="gt", value=100)], priority=20),
            rule("deny-huge", PolicyEffect.DENY, tools=["pay.*"],
                 conditions=[Condition(arg="amount", op="gt", value=1000)], priority=10),
        ]
    )
    ev = lambda amt: eng.evaluate("pay.send", {"amount": amt}, agent="a", role="r").effect  # noqa: E731
    assert ev(50) == PolicyEffect.ALLOW
    assert ev(500) == PolicyEffect.REQUIRE_APPROVAL
    assert ev(5000) == PolicyEffect.DENY


def test_allowlist_is_enforced_before_rules():
    eng = PolicyEngine([rule("allow-all", PolicyEffect.ALLOW)])
    d = eng.evaluate("shell.exec", {}, agent="a", role="r", allowed_tools=["docs.*"])
    assert d.effect == PolicyEffect.DENY and "allowlist" in d.reason


def test_rate_limit_rule_matches_only_after_limit():
    eng = PolicyEngine([rule("once", PolicyEffect.DENY, tools=["x"], max_calls_per_run=1)])
    assert eng.evaluate("x", {}, agent="a", role="r", calls_so_far={}).effect == PolicyEffect.ALLOW
    d = eng.evaluate("x", {}, agent="a", role="r", calls_so_far={"x": 1})
    assert d.effect == PolicyEffect.DENY and "rate limit" in d.reason


def test_role_and_agent_globs_and_default_effect():
    eng = PolicyEngine([rule("ops-only", PolicyEffect.ALLOW, tools=["deploy"], roles=["ops"])],
                       default_effect=PolicyEffect.DENY)
    assert eng.evaluate("deploy", {}, agent="a", role="ops").effect == PolicyEffect.ALLOW
    assert eng.evaluate("deploy", {}, agent="a", role="support").effect == PolicyEffect.DENY


@pytest.mark.parametrize(
    "path,expected",
    [("/data/reports/q3.csv", True), ("/data/../etc/passwd", False), ("data/reports/../../etc", False),
     ("/data-evil/x", False), ("\\data\\x", True)],
)
def test_path_prefix_normalises_traversal(path, expected):
    assert condition_matches(Condition(arg="path", op="path_prefix", value="/data"), {"path": path}) is expected


def test_conditions_handle_missing_and_incomparable_values():
    c = Condition(arg="amount", op="gt", value=10)
    assert not condition_matches(c, {})
    assert not condition_matches(c, {"amount": "lots"})
    assert condition_matches(Condition(arg="a.b", op="eq", value=1), {"a": {"b": 1}})
    assert condition_matches(Condition(arg="x", op="exists", value=False), {})


def test_policy_yaml_roundtrip():
    rules = load_rules("""
rules:
  - name: no-big
    effect: deny
    tools: [refund.issue]
    conditions: [{arg: amount, op: gt, value: 500}]
""")
    assert rules[0].conditions[0].value == 500
    again = load_rules(dump_rules(rules))
    assert again[0].model_dump() == rules[0].model_dump()


def test_redactor_masks_keys_and_patterns():
    r = Redactor()
    out = r({
        "password": "hunter2",
        "note": "use key sk-abcdefghijklmnopqrstuvwx and Bearer abcdefghijklmnop12",
        "nested": [{"api_key": "x1"}, "card 4111 1111 1111 1111"],
        "count": 3,
    })
    assert out["password"] == MASK
    assert "sk-" not in out["note"] and "abcdefghijklmnop12" not in out["note"]
    assert out["nested"][0]["api_key"] == MASK
    assert "4111" not in out["nested"][1]
    assert out["count"] == 3
