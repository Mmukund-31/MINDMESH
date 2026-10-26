"""Deterministic policy evaluation, enforced in code (never delegated to the LLM).

Evaluation order for a proposed tool call:

1. The tool must be in the agent's tool allowlist (otherwise: deny).
2. Enabled rules are scanned by ascending ``priority``; the first rule whose
   ``tools`` / ``roles`` / ``agents`` globs and *all* ``conditions`` match decides.
   A rule with ``max_calls_per_run`` only matches once that many calls were made.
3. If nothing matches, ``default_effect`` applies (``allow`` unless configured otherwise).
"""

from __future__ import annotations

import posixpath
import re
from fnmatch import fnmatchcase
from typing import Any

from ..core.types import Condition, PolicyDecision, PolicyEffect, PolicyRule, PolicyRuleIn

_MISSING = object()


def _get(args: dict[str, Any], path: str) -> Any:
    cur: Any = args
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return _MISSING
    return cur


def _norm_path(p: str) -> str:
    p = p.replace("\\", "/")
    return posixpath.normpath("/" + p.lstrip("/"))


def _under(path: str, prefix: str) -> bool:
    path, prefix = _norm_path(path), _norm_path(prefix)
    return path == prefix or path.startswith(prefix.rstrip("/") + "/")


def condition_matches(c: Condition, args: dict[str, Any]) -> bool:
    v = _get(args, c.arg)
    if c.op == "exists":
        return (v is not _MISSING) == bool(c.value if c.value is not None else True)
    if v is _MISSING:
        return False
    try:
        match c.op:
            case "eq":
                return v == c.value
            case "ne":
                return v != c.value
            case "lt":
                return v < c.value
            case "lte":
                return v <= c.value
            case "gt":
                return v > c.value
            case "gte":
                return v >= c.value
            case "in":
                return v in c.value
            case "not_in":
                return v not in c.value
            case "regex":
                return isinstance(v, str) and re.search(str(c.value), v) is not None
            case "path_prefix":
                return isinstance(v, str) and _under(v, str(c.value))
            case "not_path_prefix":
                return isinstance(v, str) and not _under(v, str(c.value))
    except TypeError:
        return False  # incomparable types never match
    return False


def _glob_any(value: str, patterns: list[str]) -> bool:
    return any(fnmatchcase(value, p) for p in (patterns or ["*"]))


class PolicyEngine:
    def __init__(
        self,
        rules: list[PolicyRule | PolicyRuleIn],
        *,
        default_effect: PolicyEffect = PolicyEffect.ALLOW,
    ):
        self.rules = sorted([r for r in rules if r.enabled], key=lambda r: r.priority)
        self.default_effect = default_effect

    def evaluate(
        self,
        tool: str,
        args: dict[str, Any],
        *,
        agent: str,
        role: str,
        allowed_tools: list[str] | None = None,
        calls_so_far: dict[str, int] | None = None,
    ) -> PolicyDecision:
        if allowed_tools is not None and not _glob_any(tool, allowed_tools):
            return PolicyDecision(
                effect=PolicyEffect.DENY, reason=f"tool '{tool}' is not in agent '{agent}' allowlist"
            )
        calls = (calls_so_far or {}).get(tool, 0)
        for r in self.rules:
            if not (_glob_any(tool, r.tools) and _glob_any(role, r.roles) and _glob_any(agent, r.agents)):
                continue
            if r.max_calls_per_run is not None and calls < r.max_calls_per_run:
                continue
            if not all(condition_matches(c, args) for c in r.conditions):
                continue
            reason = r.description or f"matched rule '{r.name}'"
            if r.max_calls_per_run is not None:
                reason = f"rate limit: '{tool}' already called {calls}x (max {r.max_calls_per_run})"
            return PolicyDecision(
                effect=r.effect, rule_id=getattr(r, "id", None), rule_name=r.name, reason=reason
            )
        return PolicyDecision(effect=self.default_effect, reason=f"no rule matched; default {self.default_effect.value}")
