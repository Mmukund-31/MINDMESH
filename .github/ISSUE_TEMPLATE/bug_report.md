---
name: Bug report
about: Something does not work as documented
labels: bug
---

**What happened, and what did you expect?**

**How to reproduce**
If it happened in an agent run, attach the run export: `mindmesh runs export <run id> -o bug.json` (or
**Export JSON** in Studio). Maintainers can import and replay it without your code or model. Check it for
secrets first: tool arguments and results are included.

**Environment**
- MINDMESH version (`pip show mindmesh`):
- Python and OS:
- Database (SQLite / PostgreSQL version):
- Model (e.g. `ollama:qwen3:4b`, `langchain:…` with the provider class):
