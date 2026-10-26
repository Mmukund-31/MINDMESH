"""Multi-agent research team: planner -> 2 researchers -> writer -> verifier.

Demonstrates task dependencies, parallel execution, evidence hand-offs, a flaky
tool recovered by bounded retries, and a verifier rejecting a draft (missing
citations) which re-opens the writer task with feedback.
"""

from __future__ import annotations

import re
from typing import Any

from ..core.errors import TransientToolError
from ..core.types import AgentSpec, ContextConfig, Limits, WorkflowSpec, WorkflowTaskSpec
from ..embeddings import tokenize
from ..models.base import GenerationRequest
from ..models.scripted import brain
from ..policy.tools import tool

CORPUS = {
    "doc-hnsw": "HNSW indexes in pgvector give the best recall/latency trade-off for approximate search; "
    "build time and memory use are higher than IVFFlat, and they can be built on an empty table.",
    "doc-ivf": "IVFFlat indexes in pgvector build faster and use less memory than HNSW but need data "
    "present before building (lists are trained) and recall depends on the probes setting.",
    "doc-scale": "For about one million 768-dimensional embeddings, HNSW (m=16, ef_construction=64) keeps "
    "p95 query latency under 10 ms on a single node with 8 GB RAM.",
    "doc-ops": "Operationally, IVFFlat indexes should be rebuilt after large data changes; HNSW supports "
    "incremental inserts without a rebuild.",
    "doc-ollama": "Ollama serves open-weight models such as Qwen3 locally over an HTTP API on port 11434.",
    "doc-cost": "Self-hosted vector search on PostgreSQL avoids per-query fees of managed vector databases.",
}

_state = {"search_failures": 1}


@tool("docs.search", description="Search the internal engineering knowledge base. Returns the top documents.")
async def docs_search(query: str, k: int = 3) -> list[dict[str, Any]]:
    if _state["search_failures"] > 0:
        _state["search_failures"] -= 1
        raise TransientToolError("search index warming up (503)")
    q = set(tokenize(query))
    scored = sorted(
        ((len(q & set(tokenize(t))), d, t) for d, t in CORPUS.items()), key=lambda x: (-x[0], x[1])
    )
    return [{"id": d, "text": t} for s, d, t in scored[: max(1, min(k, 5))] if s > 0]


def _final(answer: str, thought: str = "", evidence: list[str] | None = None) -> dict[str, Any]:
    return {"type": "final_answer", "thought": thought, "answer": answer, "evidence": evidence or []}


@brain("planner")
def planner_brain(req: GenerationRequest) -> dict[str, Any]:
    goal = req.task_input.get("workflow_goal", req.task)
    return _final(
        "PLAN: (1) gather evidence on HNSW in pgvector; (2) gather evidence on IVFFlat; "
        f"(3) write a cited recommendation answering: {goal}",
        "Split into independent research questions so they can run in parallel.",
    )


@brain("researcher")
def researcher_brain(req: GenerationRequest) -> dict[str, Any]:
    done = [h for h in req.history if h["action"].get("tool") == "docs.search" and h["outcome"]["status"] == "ok"]
    if not done:
        topic = "HNSW" if "HNSW" in req.task else "IVFFlat"
        return {"type": "tool_call", "thought": f"Search for {topic} evidence.", "tool": "docs.search",
                "args": {"query": f"pgvector {topic} index recall latency memory build", "k": 3}}
    docs = done[-1]["outcome"]["result"]
    findings = "; ".join(f"[{d['id']}] {d['text']}" for d in docs)
    return _final(f"FINDINGS: {findings}", "Summarise retrieved documents with their ids.", [d["id"] for d in docs])


@brain("writer")
def writer_brain(req: GenerationRequest) -> dict[str, Any]:
    cites = sorted(set(re.findall(r"\[(doc-[\w-]+)\]", " ".join(c.content for c in req.context))))
    feedback = req.task_input.get("verifier_feedback")
    body = (
        "Recommendation: use an HNSW index for ~1M embeddings - it offers the best recall/latency and supports "
        "incremental inserts; choose IVFFlat only when build time and memory are the binding constraints."
    )
    if feedback and cites:
        body += " Sources: " + ", ".join(f"[{c}]" for c in cites[:4]) + "."
        return _final(f"BRIEF: {body}", f"Addressed verifier feedback: {feedback}", cites[:4])
    return _final(f"BRIEF: {body}", "First draft.")


@brain("verifier")
def verifier_brain(req: GenerationRequest) -> dict[str, Any]:
    draft = " ".join(str(v) for v in (req.task_input.get("upstream") or {}).values())
    cites = re.findall(r"\[doc-[\w-]+\]", draft)
    if len(cites) < 2:
        return _final("REJECT: the brief must cite at least two sources from the evidence board.",
                      f"Found {len(cites)} citations.")
    return _final(f"APPROVE: brief is supported by {len(cites)} cited sources.", "Citations present.")


def _spec(name: str, role: str, brain_name: str, tools: list[str], prompt: str) -> AgentSpec:
    return AgentSpec(
        name=name, role=role, system_prompt=prompt, tools=tools, model=f"scripted:{brain_name}",
        memory_scopes=["project"], context=ContextConfig(budget_tokens=1500, use_memory=False),
        limits=Limits(max_steps=6, max_retries=2),
    )


def install(mm, world: Any = None) -> None:
    if "docs.search" not in mm.tools:
        mm.register_tool(docs_search)
    mm.agent(_spec("planner", "planner", "planner", [], "You decompose goals into research questions."))
    mm.agent(_spec("researcher", "researcher", "researcher", ["docs.search"],
                   "You research one question using docs.search and report findings with document ids."))
    mm.agent(_spec("writer", "executor", "writer", [], "You write concise, cited briefs from the evidence board."))
    mm.agent(_spec("verifier", "verifier", "verifier", [],
                   "You verify drafts. Answer 'APPROVE: ...' or 'REJECT: <reason>'."))


def reset_faults() -> None:
    _state["search_failures"] = 1


TEMPLATE = WorkflowSpec(
    name="research-brief",
    goal="Should we use a pgvector HNSW or IVFFlat index for ~1M embeddings?",
    max_concurrency=2,
    tasks=[
        WorkflowTaskSpec(key="plan", agent="planner", task="Plan the research for the goal."),
        WorkflowTaskSpec(key="research_hnsw", agent="researcher", task="Research HNSW indexes in pgvector.",
                         depends_on=["plan"]),
        WorkflowTaskSpec(key="research_ivf", agent="researcher", task="Research IVFFlat indexes in pgvector.",
                         depends_on=["plan"]),
        WorkflowTaskSpec(key="write", agent="writer", task="Write the recommendation brief.",
                         depends_on=["research_hnsw", "research_ivf"], max_attempts=3),
        WorkflowTaskSpec(key="verify", agent="verifier", task="Verify the brief is supported by cited evidence.",
                         depends_on=["write"], verifies="write", max_attempts=3),
    ],
)
