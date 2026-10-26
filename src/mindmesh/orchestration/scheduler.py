"""Multi-agent workflow execution over a task DAG.

* Tasks become READY when all dependencies SUCCEEDED; dependents of a failed task are
  SKIPPED unless that task declares ``on_failure: continue``.
* Up to ``max_concurrency`` tasks run at once; each task execution is a normal,
  fully traced agent run (``workflow_run_id`` links them).
* Failed task runs are retried up to ``max_attempts``.
* Outputs are posted to a shared, persisted **evidence board** and handed off to
  dependents (their context receives upstream evidence; a ``handoff`` event is logged).
* A **verifier** task (``verifies: <key>``) answering ``REJECT: <reason>`` re-opens the
  verified task with the feedback, then re-verifies — bounded by ``max_attempts``.

Workflow-level events are logged on the workflow id, so the Orchestration Lab can
render a timeline of readiness, handoffs, retries and verdicts.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from ..core import clock
from ..core.events import EventLog
from ..core.state import TERMINAL_TASK, TaskStatus, transition
from ..core.types import ContextItem, ScoreBreakdown, WorkflowSpec, WorkflowTask

if TYPE_CHECKING:
    from ..sdk import MindMesh


class WorkflowScheduler:
    def __init__(self, mm: MindMesh):
        self.mm = mm
        self.repo = mm.repos.workflows

    async def start(self, spec: WorkflowSpec | dict[str, Any], *, wait: bool = True) -> str:
        spec = spec if isinstance(spec, WorkflowSpec) else WorkflowSpec.model_validate(spec)
        self._validate(spec)
        wid = await self.repo.create_run(spec.name, spec.goal, spec.model_dump(mode="json"), status="running")
        for t in spec.tasks:
            await self.repo.add_task(
                wid, key=t.key, agent=t.agent, task=t.task, depends_on=t.depends_on,
                status=TaskStatus.PENDING.value, max_attempts=t.max_attempts,
            )
        task = asyncio.create_task(self._drive(wid, spec))
        if wait:
            await task
        else:
            _BACKGROUND.add(task)
            task.add_done_callback(_BACKGROUND.discard)
        return wid

    def _validate(self, spec: WorkflowSpec) -> None:
        keys = [t.key for t in spec.tasks]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate task keys")
        for t in spec.tasks:
            for d in t.depends_on:
                if d not in keys:
                    raise ValueError(f"task {t.key!r} depends on unknown task {d!r}")
            if t.verifies and t.verifies not in t.depends_on:
                raise ValueError(f"verifier {t.key!r} must depend on {t.verifies!r}")
            if t.agent not in self.mm.agents:
                raise ValueError(f"task {t.key!r} uses unregistered agent {t.agent!r}")
        # cycle check (Kahn)
        indeg = {t.key: len(t.depends_on) for t in spec.tasks}
        children: dict[str, list[str]] = {k: [] for k in keys}
        for t in spec.tasks:
            for d in t.depends_on:
                children[d].append(t.key)
        queue = [k for k, v in indeg.items() if v == 0]
        seen = 0
        while queue:
            k = queue.pop()
            seen += 1
            for c in children[k]:
                indeg[c] -= 1
                if indeg[c] == 0:
                    queue.append(c)
        if seen != len(keys):
            raise ValueError("workflow has a dependency cycle")

    async def _set(self, t: WorkflowTask, dst: TaskStatus, log: EventLog, **fields: Any) -> WorkflowTask:
        transition(TaskStatus(t.status), dst)
        updated = await self.repo.update_task(t.id, status=dst.value, **fields)
        await log.emit(
            "task.state_changed", {"task": t.key, "from": t.status, "to": dst.value, **_brief(fields)}
        )
        return updated

    async def _drive(self, wid: str, spec: WorkflowSpec) -> None:
        log = EventLog(self.mm.repos.events, wid, redactor=self.mm.redactor)
        await log.emit("workflow.started", {"name": spec.name, "goal": spec.goal, "tasks": len(spec.tasks)},
                       span_id=log.root_span)
        specs = {t.key: t for t in spec.tasks}
        running: dict[str, asyncio.Task] = {}
        feedback: dict[str, str] = {}
        try:
            while True:
                tasks = {t.key: t for t in await self.repo.tasks(wid)}
                # promote / skip
                for t in tasks.values():
                    if t.status != TaskStatus.PENDING.value:
                        continue
                    deps = [tasks[d] for d in t.depends_on]
                    if all(d.status == TaskStatus.SUCCEEDED.value for d in deps):
                        tasks[t.key] = await self._set(t, TaskStatus.READY, log)
                    elif any(
                        d.status in (TaskStatus.FAILED.value, TaskStatus.SKIPPED.value)
                        and specs[d.key].on_failure == "fail"
                        for d in deps
                    ):
                        tasks[t.key] = await self._set(t, TaskStatus.SKIPPED, log, error="upstream failed")
                    elif all(d.status in {s.value for s in TERMINAL_TASK} for d in deps):
                        tasks[t.key] = await self._set(t, TaskStatus.READY, log)
                # launch
                for t in tasks.values():
                    if t.status == TaskStatus.READY.value and t.key not in running and len(running) < spec.max_concurrency:
                        t = await self._set(t, TaskStatus.RUNNING, log, attempts=t.attempts + 1, started_at=clock.now())
                        running[t.key] = asyncio.create_task(self._execute(wid, t, tasks, log, feedback.get(t.key)))
                if not running:
                    break
                done, _ = await asyncio.wait(running.values(), return_when=asyncio.FIRST_COMPLETED)
                for key in [k for k, f in running.items() if f in done]:
                    fut = running.pop(key)
                    await self._complete(wid, key, fut, specs, log, feedback)
        except asyncio.CancelledError:
            for f in running.values():
                f.cancel()
            raise
        final = await self.repo.tasks(wid)
        ok = all(
            t.status == TaskStatus.SUCCEEDED.value
            or (t.status in (TaskStatus.FAILED.value, TaskStatus.SKIPPED.value) and specs[t.key].on_failure == "continue")
            for t in final
        )
        status = "succeeded" if ok else "failed"
        await self.repo.update_run(wid, status=status, ended_at=clock.now())
        await log.emit("workflow.finished", {"status": status}, span_id=log.root_span)

    async def _execute(self, wid: str, t: WorkflowTask, tasks: dict[str, WorkflowTask], log: EventLog,
                       feedback: str | None):
        board = await self.repo.evidence(wid)
        evidence = [
            ContextItem(
                item_id=e.id, kind="evidence", content=e.content, tokens=0,
                source=f"{e.created_by} ({e.task_key})", score=ScoreBreakdown(total=0.0),
            )
            for e in board
        ]
        upstream = {d: (tasks[d].output or {}).get("answer") for d in t.depends_on}
        for d in t.depends_on:
            await log.emit("handoff", {"from": d, "to": t.key, "evidence_ids": [e.id for e in board if e.task_key == d]})
        wf = await self.repo.get_run(wid)
        task_input: dict[str, Any] = {"workflow_goal": wf.goal, "upstream": upstream, "attempt": t.attempts}
        if feedback:
            task_input["verifier_feedback"] = feedback
        return await self.mm.run(
            t.agent, t.task, task_input, workflow_run_id=wid, evidence=evidence,
            label=f"{wf.name}/{t.key}#{t.attempts}",
        )

    async def _complete(self, wid, key, fut: asyncio.Task, specs, log: EventLog, feedback: dict[str, str]) -> None:
        tasks = {t.key: t for t in await self.repo.tasks(wid)}
        t = tasks[key]
        try:
            run = fut.result()
            err = None if run.status == "succeeded" else (run.error or run.status)
        except Exception as e:  # noqa: BLE001
            run, err = None, f"{type(e).__name__}: {e}"
        run_id = run.id if run else None
        if err is not None:
            if t.attempts < t.max_attempts:
                await log.emit("task.retry", {"task": key, "attempt": t.attempts, "error": err})
                await self._set(t, TaskStatus.READY, log, run_id=run_id, error=err)
            else:
                await self._set(t, TaskStatus.FAILED, log, run_id=run_id, error=err, ended_at=clock.now())
            return
        answer = (run.result or {}).get("answer", "")
        target = specs[key].verifies
        if target and answer.strip().upper().startswith("REJECT"):
            reason = answer.split(":", 1)[1].strip() if ":" in answer else answer
            tgt = tasks[target]
            await log.emit("verifier.rejected", {"verifier": key, "task": target, "reason": reason})
            if tgt.attempts < tgt.max_attempts and t.attempts < t.max_attempts:
                feedback[target] = reason
                await self._set(tgt, TaskStatus.READY, log, error=f"rejected by {key}: {reason}")
                await self._set(t, TaskStatus.PENDING, log, run_id=run_id)
            else:
                await self._set(t, TaskStatus.FAILED, log, run_id=run_id, ended_at=clock.now(),
                                error=f"rejected {target} and retries are exhausted: {reason}")
            return
        if target:
            await log.emit("verifier.approved", {"verifier": key, "task": target})
        await self.repo.add_evidence(
            wid, answer, source=f"task:{key}", created_by=t.agent, run_id=run_id, task_key=key
        )
        await self._set(t, TaskStatus.SUCCEEDED, log, run_id=run_id, output={"answer": answer, "run_id": run_id},
                        error=None, ended_at=clock.now())


_BACKGROUND: set[asyncio.Task] = set()


def _brief(fields: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in fields.items() if k in ("attempts", "error", "run_id")}
