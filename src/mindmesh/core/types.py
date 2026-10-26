"""Public Pydantic models shared by the SDK, runtime, storage and API."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .state import ApprovalStatus, RunStatus, TaskStatus

# --------------------------------------------------------------------------- memory


class MemoryKind(StrEnum):
    FACT = "fact"
    EPISODE = "episode"
    DECISION = "decision"
    STRATEGY = "strategy"


class MemoryStatus(StrEnum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    RETRACTED = "retracted"
    EXPIRED = "expired"


class Provenance(BaseModel):
    source_type: str = "manual"  # manual | tool | run | import | agent
    source_ref: str | None = None  # url, tool name, document id ...
    created_by: str = "user"  # user id or agent name
    run_id: str | None = None


class MemoryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=20_000)
    kind: MemoryKind = MemoryKind.FACT
    subject_key: str | None = Field(default=None, max_length=200)
    scope: str = Field(default="project", pattern=r"^(project|agent:[\w.-]+|user:[\w.@-]+|run:[\w-]+)$")
    tags: list[str] = Field(default_factory=list)
    provenance: Provenance = Field(default_factory=Provenance)
    trust: float = Field(default=0.7, ge=0.0, le=1.0)
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
    valid_from: datetime | None = None
    expires_at: datetime | None = None


class MemoryUpdate(BaseModel):
    """Editing a memory creates a new version; omitted fields are carried over."""

    model_config = ConfigDict(extra="forbid")

    content: str | None = Field(default=None, min_length=1, max_length=20_000)
    scope: str | None = Field(default=None, pattern=r"^(project|agent:[\w.-]+|user:[\w.@-]+|run:[\w-]+)$")
    tags: list[str] | None = None
    trust: float | None = Field(default=None, ge=0.0, le=1.0)
    importance: float | None = Field(default=None, ge=0.0, le=1.0)
    expires_at: datetime | None = None
    reason: str | None = None
    edited_by: str = "user"


class Memory(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    lineage_id: str
    version: int
    kind: MemoryKind
    subject_key: str | None
    content: str
    scope: str
    tags: list[str]
    source_type: str
    source_ref: str | None
    created_by: str
    run_id: str | None
    trust: float
    importance: float
    valid_from: datetime
    expires_at: datetime | None
    status: MemoryStatus
    status_reason: str | None
    supersedes_id: str | None
    created_at: datetime
    retrieval_count: int = 0


# --------------------------------------------------------------------------- context


class ExclusionReason(StrEnum):
    BUDGET = "budget"
    EXPIRED = "expired"
    RETRACTED = "retracted"
    SUPERSEDED = "superseded"
    SCOPE_MISMATCH = "scope_mismatch"
    LOW_RELEVANCE = "low_relevance"
    CONFLICT_LOST = "conflict_lost"


class ScoreBreakdown(BaseModel):
    relevance: float = 0.0
    recency: float = 0.0
    importance: float = 0.0
    trust: float = 0.0
    total: float = 0.0


class ContextItem(BaseModel):
    item_id: str
    kind: Literal["memory", "evidence", "task", "instruction"]
    content: str
    tokens: int
    subject_key: str | None = None
    scope: str | None = None
    source: str | None = None
    score: ScoreBreakdown = Field(default_factory=ScoreBreakdown)
    included: bool = True
    reason: ExclusionReason | None = None
    detail: str | None = None


class ContextConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    budget_tokens: int = Field(default=1200, ge=64, le=200_000)
    strategy: Literal["ranked", "naive"] = "ranked"
    min_relevance: float = Field(default=0.12, ge=0.0, le=1.0)
    max_candidates: int = Field(default=50, ge=1, le=1000)
    w_relevance: float = 0.55
    w_recency: float = 0.10
    w_importance: float = 0.15
    w_trust: float = 0.20
    recency_half_life_days: float = 30.0
    use_memory: bool = True


class ContextReceipt(BaseModel):
    receipt_id: str
    run_id: str | None
    step: int
    query: str
    strategy: str
    budget_tokens: int
    used_tokens: int
    included: list[ContextItem]
    excluded: list[ContextItem]
    created_at: datetime


# --------------------------------------------------------------------------- models


class Message(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str


class ModelResponse(BaseModel):
    text: str
    model: str
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: float = 0.0


class ToolCallAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["tool_call"] = "tool_call"
    thought: str = ""
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)


class FinalAnswerAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["final_answer"] = "final_answer"
    thought: str = ""
    answer: str
    evidence: list[str] = Field(default_factory=list)


AgentAction = ToolCallAction | FinalAnswerAction


# --------------------------------------------------------------------------- agents


class Limits(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_steps: int = Field(default=12, ge=1, le=200)
    max_tool_calls: int = Field(default=20, ge=0, le=500)
    max_tokens: int = Field(default=60_000, ge=100)
    timeout_s: float = Field(default=300.0, gt=0)
    tool_timeout_s: float = Field(default=20.0, gt=0)
    max_retries: int = Field(default=2, ge=0, le=10)  # per tool call / model call
    backoff_base_s: float = Field(default=0.05, ge=0)
    repeated_failure_limit: int = Field(default=2, ge=1)


class AgentSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=r"^[\w.-]{1,64}$")
    role: str = "agent"
    description: str = ""
    system_prompt: str = "You are a careful, reliable assistant."
    tools: list[str] = Field(default_factory=list)
    model: str = "scripted:echo"
    memory_scopes: list[str] = Field(default_factory=lambda: ["project"])
    context: ContextConfig = Field(default_factory=ContextConfig)
    limits: Limits = Field(default_factory=Limits)
    enforce_policies: bool = True
    remember_outcomes: bool = False  # write an episode memory at the end of each run


class RunOverrides(BaseModel):
    """Config deltas applied when re-running a task (Replay Lab)."""

    model_config = ConfigDict(extra="forbid")

    model: str | None = None
    memory_scopes: list[str] | None = None
    context: dict[str, Any] | None = None
    limits: dict[str, Any] | None = None
    enforce_policies: bool | None = None


class RunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent: str
    task: str = Field(min_length=1, max_length=20_000)
    input: dict[str, Any] = Field(default_factory=dict)
    overrides: RunOverrides | None = None
    label: str | None = None


class RunFeedback(BaseModel):
    """Human verdict on a run's outcome (e.g. a customer complaint flags a wrong decision)."""

    model_config = ConfigDict(extra="forbid")

    verdict: Literal["correct", "incorrect"]
    note: str | None = Field(default=None, max_length=4000)
    by: str = Field(default="user", max_length=120)


class Run(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    agent_name: str
    task: str
    input: dict[str, Any]
    status: RunStatus
    label: str | None
    kind: str
    parent_run_id: str | None
    workflow_run_id: str | None
    config: dict[str, Any]
    result: dict[str, Any] | None
    error: str | None
    cancel_requested: bool = False
    feedback: dict[str, Any] | None = None
    steps: int
    tool_calls: int
    tokens_in: int
    tokens_out: int
    created_at: datetime
    started_at: datetime | None
    ended_at: datetime | None


class Event(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    run_id: str
    seq: int
    type: str
    step: int | None
    span_id: str
    parent_span_id: str | None
    ts: datetime
    duration_ms: float | None
    payload: dict[str, Any]


# --------------------------------------------------------------------------- policies


class PolicyEffect(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_APPROVAL = "require_approval"


class Condition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    arg: str
    op: Literal["eq", "ne", "lt", "lte", "gt", "gte", "in", "not_in", "regex", "path_prefix", "not_path_prefix", "exists"]
    value: Any = None


class PolicyRuleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    description: str = ""
    effect: PolicyEffect
    tools: list[str] = Field(default_factory=lambda: ["*"])
    roles: list[str] = Field(default_factory=lambda: ["*"])
    agents: list[str] = Field(default_factory=lambda: ["*"])
    conditions: list[Condition] = Field(default_factory=list)
    priority: int = 100
    enabled: bool = True
    max_calls_per_run: int | None = Field(default=None, ge=0)


class PolicyRule(PolicyRuleIn):
    model_config = ConfigDict(from_attributes=True, extra="ignore")

    id: str
    project_id: str
    created_at: datetime


class PolicyDecision(BaseModel):
    effect: PolicyEffect
    rule_id: str | None = None
    rule_name: str | None = None
    reason: str


class Approval(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    run_id: str
    step: int
    tool: str
    args: dict[str, Any]
    reason: str
    status: ApprovalStatus
    requested_at: datetime
    resolved_at: datetime | None
    resolver: str | None
    note: str | None


class ApprovalResolve(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approve: bool
    resolver: str = Field(default="user", max_length=120)
    note: str | None = Field(default=None, max_length=2000)


# --------------------------------------------------------------------------- orchestration


class WorkflowTaskSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(pattern=r"^[\w.-]{1,64}$")
    agent: str
    task: str
    depends_on: list[str] = Field(default_factory=list)
    max_attempts: int = Field(default=2, ge=1, le=10)
    on_failure: Literal["fail", "continue"] = "fail"
    verifies: str | None = None  # key of the task this verifier checks


class WorkflowSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    goal: str
    tasks: list[WorkflowTaskSpec]
    max_concurrency: int = Field(default=3, ge=1, le=32)


class WorkflowTask(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    workflow_run_id: str
    key: str
    agent: str
    task: str
    depends_on: list[str]
    status: TaskStatus
    attempts: int
    max_attempts: int
    run_id: str | None
    output: dict[str, Any] | None
    error: str | None
    started_at: datetime | None
    ended_at: datetime | None


class Evidence(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    workflow_run_id: str
    run_id: str | None
    task_key: str | None
    content: str
    source: str | None
    created_by: str
    created_at: datetime
