"""Render evaluation reports as JSON + Markdown."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

METRIC_ROWS = [
    ("success_rate", "Task success rate", "pct"),
    ("evidence_recall", "Required-evidence recall", "pct"),
    ("context_precision", "Context precision", "pct"),
    ("context_efficiency", "Context efficiency (relevant tokens)", "pct"),
    ("unsafe_actions_executed", "Unsafe actions executed", "int"),
    ("unsafe_actions_blocked", "Unsafe actions blocked", "int"),
    ("tool_error_rate", "Tool error rate", "pct"),
    ("recovery_rate", "Recovery after injected faults", "pct"),
    ("approvals_requested", "Human approvals requested", "int"),
    ("avg_steps", "Avg steps", "num"),
    ("avg_tokens", "Avg tokens", "num"),
]


def fmt(v: Any, kind: str) -> str:
    if v is None:
        return "–"
    if kind == "pct":
        return f"{v * 100:.0f}%"
    if kind == "int":
        return str(int(v))
    return f"{v:.1f}"


def to_markdown(report: dict[str, Any]) -> str:
    names = list(report["variants"])
    lines = [
        f"# Benchmark: `{report['suite']}`",
        "",
        report.get("description", "").strip(),
        "",
        f"Model: `{report['model']}` · seed {report['seed']}",
        "",
        "| Metric | " + " | ".join(f"`{n}`" for n in names) + " |",
        "|---|" + "---|" * len(names),
    ]
    for key, label, kind in METRIC_ROWS:
        lines.append(f"| {label} | " + " | ".join(fmt(report["variants"][n]["metrics"].get(key), kind) for n in names) + " |")
    lines += ["", "## Per-task outcomes", "", "| Task | " + " | ".join(names) + " |", "|---|" + "---|" * len(names)]
    tasks = [r["task_id"] for r in report["variants"][names[0]]["results"]]
    for i, t in enumerate(tasks):
        cells = []
        for n in names:
            r = report["variants"][n]["results"][i]
            cells.append(("✅ " if r["success"] else "❌ ") + (r["answer"][:60] or r.get("error") or r["status"]))
        lines.append(f"| `{t}` | " + " | ".join(cells) + " |")
    lines += ["", "## Variants", ""] + [f"- **{n}**: {report['variants'][n]['description']}" for n in names]
    return "\n".join(lines) + "\n"


def write_report(report: dict[str, Any], results_dir: Path) -> dict[str, str]:
    results_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    base = results_dir / f"{report['suite']}-{stamp}"
    jp, mp = base.with_suffix(".json"), base.with_suffix(".md")
    jp.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    mp.write_text(to_markdown(report), encoding="utf-8")
    (results_dir / f"{report['suite']}-latest.md").write_text(to_markdown(report), encoding="utf-8")
    return {"json": str(jp), "markdown": str(mp)}
