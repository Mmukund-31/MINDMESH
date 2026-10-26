"""Load and dump policy rules as YAML (policy-as-code)."""

from __future__ import annotations

from typing import Any

import yaml

from ..core.types import PolicyRule, PolicyRuleIn


def load_rules(text: str) -> list[PolicyRuleIn]:
    data = yaml.safe_load(text) or {}
    items = data.get("rules", data) if isinstance(data, dict) else data
    if not isinstance(items, list):
        raise ValueError("policy YAML must be a list of rules or a mapping with a 'rules' list")
    return [PolicyRuleIn.model_validate(i) for i in items]


def dump_rules(rules: list[PolicyRule | PolicyRuleIn]) -> str:
    out: list[dict[str, Any]] = []
    for r in rules:
        d = PolicyRuleIn.model_validate(r.model_dump(include=set(PolicyRuleIn.model_fields))).model_dump(mode="json")
        out.append({k: v for k, v in d.items() if v not in (None, [], "") or k in ("effect", "name")})
    return yaml.safe_dump({"rules": out}, sort_keys=False)
