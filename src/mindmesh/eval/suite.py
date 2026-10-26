"""Evaluation suite definitions (YAML)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from ..core.types import Condition, RunOverrides

SUITES_DIR = Path(__file__).parent / "suites"


class Check(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["answer_startswith", "answer_contains", "status", "tool_executed", "tool_not_executed"]
    value: Any = None
    tool: str | None = None
    where: list[Condition] = Field(default_factory=list)


class Forbidden(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool: str
    where: list[Condition] = Field(default_factory=list)
    description: str = ""


class EvalTask(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    description: str = ""
    customer_id: str | None = None
    order_id: str | None = None
    task: str | None = None
    input: dict[str, Any] = Field(default_factory=dict)
    faults: dict[str, int] = Field(default_factory=dict)
    overrides: RunOverrides | None = None
    checks: list[Check]
    required_evidence: list[str] = Field(default_factory=list)
    forbidden: list[Forbidden] = Field(default_factory=list)


class Variant(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str = ""
    memory_state: Literal["broken", "fixed"] = "fixed"
    overrides: RunOverrides | None = None


class Suite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    description: str = ""
    app: str  # module path exposing install(mm, world) / seed(mm, ...) / make_world(faults)
    agent: str
    variants: dict[str, Variant]
    tasks: list[EvalTask]


def load_suite(name_or_path: str) -> Suite:
    p = Path(name_or_path)
    if not p.exists():
        p = SUITES_DIR / f"{name_or_path}.yaml"
    if not p.exists():
        raise FileNotFoundError(f"suite {name_or_path!r} not found (looked in {SUITES_DIR})")
    return Suite.model_validate(yaml.safe_load(p.read_text(encoding="utf-8")))


def list_suites() -> list[str]:
    return sorted(p.stem for p in SUITES_DIR.glob("*.yaml"))
