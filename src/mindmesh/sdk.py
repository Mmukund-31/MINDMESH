"""The MindMesh SDK entry point.

Example::

    mm = MindMesh("sqlite:///mindmesh.db", project="demo")
    await mm.init()

    @mm.tool(side_effect=True)
    async def send_email(to: str, body: str) -> str: ...

    mm.agent(AgentSpec(name="mailer", tools=["send_email"], model="ollama:qwen3:8b"))
    run = await mm.run("mailer", "Tell bob the build is green")
"""

from __future__ import annotations

import asyncio
import contextlib
import os
from collections.abc import Callable
from typing import Any

from .context.engine import ContextEngine
from .core.errors import NotFound
from .core.events import EventLog
from .core.state import TERMINAL_RUN, RunStatus
from .core.types import (
    AgentSpec,
    Approval,
    ContextItem,
    MemoryCreate,
    PolicyEffect,
    PolicyRule,
    PolicyRuleIn,
    Run,
    RunOverrides,
)
from .embeddings import Embedder, resolve_embedder
from .memory.store import MemoryStore
from .models.base import ModelProvider
from .models.registry import resolve_model
from .policy.engine import PolicyEngine
from .policy.redact import Redactor, default_redactor
from .policy.rules import load_rules
from .policy.tools import ToolRegistry, ToolSpec
from .policy.tools import tool as tool_decorator
from .runtime.agent import AgentRunner, RunOptions, RunState
from .storage.db import Database
from .storage.repositories import Repos


class _Shared:
    """State shared between project-scoped views of the same MindMesh instance."""

    def __init__(self) -> None:
        self.tools = ToolRegistry()
        self.agents: dict[str, AgentSpec] = {}
        self.active: dict[str, tuple[asyncio.Task, AgentRunner]] = {}
        self.providers: dict[str, ModelProvider] = {}
        self.model_override: str | None = None


class MindMesh:
    def __init__(
        self,
        database_url: str | None = None,
        *,
        project: str = "default",
        embedder: Embedder | str | None = None,
        default_policy_effect: PolicyEffect = PolicyEffect.ALLOW,
        redactor: Redactor | None = None,
        db: Database | None = None,
        _shared: _Shared | None = None,
        _project_id: str | None = None,
    ):
        self.db = db or Database(database_url or os.environ.get("MINDMESH_DATABASE_URL", "sqlite:///mindmesh.db"))
        self.project_name = project
        emb = embedder or os.environ.get("MINDMESH_EMBEDDER", "hashing:384")
        self.embedder: Embedder = resolve_embedder(emb) if isinstance(emb, str) else emb
        self.default_policy_effect = default_policy_effect
        self.redactor = redactor or default_redactor
        self._shared = _shared or _Shared()
        self.project_id: str = _project_id or ""
        self._policy_cache = PolicyEngine([], default_effect=default_policy_effect)
        if self.project_id:
            self._bind(self.project_id)

    # ------------------------------------------------------------------ lifecycle

    async def init(self, *, create_schema: bool = True) -> MindMesh:
        """Connect and bind the project. ``create_schema`` applies pending migrations; without it the
        schema must already be at the latest revision."""
        if create_schema:
            await self.db.migrate()
        else:
            await self.db.require_current_schema()
        if not self.project_id:
            self._bind(await self.db.ensure_project(self.project_name))
        return self

    def _bind(self, project_id: str) -> None:
        self.project_id = project_id
        self.repos = Repos(self.db, project_id)
        self.memory = MemoryStore(self.repos, self.embedder)
        self.context = ContextEngine(self.memory)

    def scoped(self, project_id: str) -> MindMesh:
        """A view of this instance bound to another project (tools/agents are shared)."""
        return MindMesh(
            db=self.db,
            embedder=self.embedder,
            default_policy_effect=self.default_policy_effect,
            redactor=self.redactor,
            _shared=self._shared,
            _project_id=project_id,
        )

    async def close(self) -> None:
        for task, _ in list(self._shared.active.values()):
            task.cancel()
        await self.db.dispose()

    # ------------------------------------------------------------------ registration

    @property
    def tools(self) -> ToolRegistry:
        return self._shared.tools

    @property
    def agents(self) -> dict[str, AgentSpec]:
        return self._shared.agents

    def tool(self, name: str | None = None, **kw: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """Decorator: define and register a tool in one go."""

        def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
            tool_decorator(name, **kw)(fn)
            self.tools.register(fn)
            return fn

        return deco

    def register_tool(self, fn: Callable[..., Any], **overrides: Any) -> ToolSpec:
        return self.tools.register(fn, **overrides)

    def agent(self, spec: AgentSpec | None = None, **kw: Any) -> AgentSpec:
        spec = spec or AgentSpec(**kw)
        missing = [t for t in spec.tools if "*" not in t and t not in self.tools]
        if missing:
            raise ValueError(f"agent {spec.name!r} references unregistered tools: {missing}")
        self.agents[spec.name] = spec
        return spec

    def register_provider_instance(self, spec: str, provider: ModelProvider) -> None:
        """Pin a provider instance for a model spec string (e.g. a custom client)."""
        self._shared.providers[spec] = provider

    def set_model_override(self, spec: str | None) -> None:
        """Force every agent onto one model (e.g. run the demo against Ollama)."""
        self._shared.model_override = spec

    def resolve_model(self, spec: str) -> ModelProvider:
        return self._shared.providers.get(spec) or resolve_model(spec)

    # ------------------------------------------------------------------ memory / policy helpers

    async def remember(self, content: str, **kw: Any):
        return await self.memory.add(MemoryCreate(content=content, **kw))

    async def add_policy(self, rule: PolicyRuleIn | dict[str, Any]) -> PolicyRule:
        return await self.repos.policies.create(rule if isinstance(rule, PolicyRuleIn) else PolicyRuleIn(**rule))

    async def load_policies(self, yaml_text: str, *, replace: bool = True) -> list[PolicyRule]:
        rules = load_rules(yaml_text)
        if replace:
            return await self.repos.policies.replace_all(rules)
        return [await self.repos.policies.create(r) for r in rules]

    async def refresh_policies(self) -> PolicyEngine:
        self._policy_cache = PolicyEngine(
            await self.repos.policies.list(enabled_only=True), default_effect=self.default_policy_effect
        )
        return self._policy_cache

    # ------------------------------------------------------------------ runs

    def effective_spec(self, agent: str | AgentSpec, overrides: RunOverrides | None = None) -> AgentSpec:
        spec = agent if isinstance(agent, AgentSpec) else self.agents.get(agent)
        if spec is None:
            raise NotFound(f"agent {agent!r} is not registered")
        upd: dict[str, Any] = {}
        if self._shared.model_override:
            upd["model"] = self._shared.model_override
        if overrides:
            if overrides.model:
                upd["model"] = overrides.model
            if overrides.memory_scopes is not None:
                upd["memory_scopes"] = overrides.memory_scopes
            if overrides.enforce_policies is not None:
                upd["enforce_policies"] = overrides.enforce_policies
            if overrides.context:
                upd["context"] = spec.context.model_copy(update=overrides.context)
            if overrides.limits:
                upd["limits"] = spec.limits.model_copy(update=overrides.limits)
        spec = spec.model_copy(update=upd)
        return AgentSpec.model_validate(spec.model_dump())  # re-validate merged config

    async def create_run(
        self,
        agent: str | AgentSpec,
        task: str,
        input: dict[str, Any] | None = None,
        *,
        overrides: RunOverrides | None = None,
        label: str | None = None,
        kind: str = "live",
        parent_run_id: str | None = None,
        workflow_run_id: str | None = None,
    ) -> tuple[Run, AgentSpec]:
        spec = self.effective_spec(agent, overrides)
        run = await self.repos.runs.create(
            agent_name=spec.name,
            task=task,
            input=input or {},
            status=RunStatus.PENDING.value,
            label=label,
            kind=kind,
            parent_run_id=parent_run_id,
            workflow_run_id=workflow_run_id,
            config={
                "agent_spec": spec.model_dump(mode="json"),
                "overrides": overrides.model_dump(mode="json", exclude_none=True) if overrides else None,
            },
        )
        return run, spec

    async def run(
        self,
        agent: str | AgentSpec,
        task: str,
        input: dict[str, Any] | None = None,
        *,
        overrides: RunOverrides | None = None,
        label: str | None = None,
        kind: str = "live",
        parent_run_id: str | None = None,
        workflow_run_id: str | None = None,
        evidence: list[ContextItem] | None = None,
        provider: ModelProvider | None = None,
        replay_outcomes: dict[int, dict[str, Any]] | None = None,
        wait: bool = True,
    ) -> Run:
        """Create and execute a run. With ``wait=False`` it runs in the background."""
        run, spec = await self.create_run(
            agent, task, input, overrides=overrides, label=label, kind=kind,
            parent_run_id=parent_run_id, workflow_run_id=workflow_run_id,
        )
        await self.refresh_policies()
        runner = AgentRunner(
            self, spec, run,
            RunOptions(provider=provider, replay_outcomes=replay_outcomes, evidence=evidence or []),
        )
        return await self._launch(run.id, runner.start(), runner, wait)

    async def resume(self, run_id: str, *, wait: bool = True) -> Run:
        run = await self.repos.runs.get(run_id)
        if run_id in self._shared.active and not self._shared.active[run_id][0].done():
            raise ValueError(f"run {run_id} is already executing")
        if RunStatus(run.status) in TERMINAL_RUN:
            raise ValueError(f"cannot resume a {run.status} run")
        if run.status == RunStatus.WAITING_APPROVAL.value:
            pending = await self.repos.approvals.list(status="pending", run_id=run_id)
            if pending:
                raise ValueError(f"run {run_id} is waiting for approval {pending[0].id}")
        spec = AgentSpec.model_validate(run.config["agent_spec"])
        if self._shared.model_override:
            spec = spec.model_copy(update={"model": self._shared.model_override})
        await self.refresh_policies()
        runner = AgentRunner(self, spec, run)
        return await self._launch(run_id, runner.resume(), runner, wait)

    async def _launch(self, run_id: str, coro, runner: AgentRunner, wait: bool) -> Run:
        task = asyncio.create_task(coro)
        self._shared.active[run_id] = (task, runner)
        task.add_done_callback(lambda _t: self._shared.active.pop(run_id, None))
        if wait:
            return await task
        await asyncio.sleep(0)
        return await self.repos.runs.get(run_id)

    async def wait(self, run_id: str, timeout: float = 60.0) -> Run:
        entry = self._shared.active.get(run_id)
        if entry:
            await asyncio.wait_for(asyncio.shield(entry[0]), timeout)
        return await self.repos.runs.get(run_id)

    async def cancel(self, run_id: str, reason: str = "cancelled by user") -> Run:
        run = await self.repos.runs.get(run_id)
        if RunStatus(run.status) in TERMINAL_RUN:
            return run
        await self.repos.runs.update(run_id, cancel_requested=True)
        entry = self._shared.active.get(run_id)
        if entry:
            entry[1].cancel_event.set()
            try:
                await asyncio.wait_for(asyncio.shield(entry[0]), 10)
            except TimeoutError:
                entry[0].cancel()  # the runner records CANCELLED before the task ends
                with contextlib.suppress(asyncio.CancelledError):
                    await entry[0]
            return await self.repos.runs.get(run_id)
        # Not executing in this process: paused/pending runs can be finalized directly.
        if RunStatus(run.status) in (RunStatus.PENDING, RunStatus.WAITING_APPROVAL):
            runner = AgentRunner(self, AgentSpec.model_validate(run.config["agent_spec"]), run)
            runner.events = await EventLog.resume(self.repos.events, run_id, redactor=self.redactor)
            ckpt = await self.repos.runs.latest_checkpoint(run_id)
            await runner._terminate(
                RunStatus.CANCELLED, RunState.from_dict(ckpt["state"]) if ckpt else RunState(), error=reason
            )
            for a in await self.repos.approvals.list(status="pending", run_id=run_id):
                await self.repos.approvals.resolve(a.id, False, "system", "run cancelled")
        return await self.repos.runs.get(run_id)

    async def resolve_approval(
        self, approval_id: str, approve: bool, *, resolver: str = "user", note: str | None = None,
        resume: bool = True, wait: bool = True,
    ) -> tuple[Approval, Run | None]:
        appr = await self.repos.approvals.resolve(approval_id, approve, resolver, note)
        run = None
        if resume:
            current = await self.repos.runs.get(appr.run_id)
            if current.status == RunStatus.WAITING_APPROVAL.value:
                run = await self.resume(appr.run_id, wait=wait)
        return appr, run

    # ------------------------------------------------------------------ replay / workflows / eval

    async def replay(self, run_id: str, *, wait: bool = True) -> Run:
        from .replay.replayer import safe_replay

        return await safe_replay(self, run_id, wait=wait)

    async def rerun(self, run_id: str, overrides: RunOverrides | None = None, *, wait: bool = True) -> Run:
        from .replay.replayer import rerun

        return await rerun(self, run_id, overrides, wait=wait)

    async def compare(self, run_a: str, run_b: str) -> dict[str, Any]:
        from .replay.diff import compare_runs

        return await compare_runs(self, run_a, run_b)

    async def run_workflow(self, spec, *, wait: bool = True):
        from .orchestration.scheduler import WorkflowScheduler

        return await WorkflowScheduler(self).start(spec, wait=wait)
