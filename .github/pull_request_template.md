## What changes, and why

## How I verified it
<!-- Commands you ran and what they showed. Runtime changes: also the live suite (pytest -m ollama tests/live). -->

## Checklist
- [ ] Tests added or updated; `pytest -q` and `ruff check .` pass
- [ ] Storage changes: migration added and tested on PostgreSQL
- [ ] Studio changes: `npm run typecheck && npm test`, and `python scripts/build_studio.py` rebuilt the bundle
- [ ] Docs updated for user-facing behaviour
- [ ] Core invariants in CONTRIBUTING.md still hold
