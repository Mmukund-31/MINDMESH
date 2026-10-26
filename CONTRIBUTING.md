# Contributing to MINDMESH

1. `python -m venv .venv && pip install -e ".[server,dev]"` and `cd studio && npm install`
2. Make your change, with tests:
   - Python: `pytest` (unit, integration, security); `ruff check .`
   - PostgreSQL: `docker compose up -d postgres` then
     `MINDMESH_TEST_DATABASE_URL=postgresql://mindmesh:mindmesh@localhost:5432/mindmesh pytest -m postgres`
   - Schema changes: edit `storage/orm.py`, then `alembic revision --autogenerate -m "…"`; review the script
     (the migration tests fail if migrations and ORM drift apart)
   - Studio: `npm run typecheck && npm test`; end-to-end: `npx playwright test`
3. Keep the core invariants:
   - every status change goes through `core.state.transition()`
   - tools execute only via `runtime.executor.ToolExecutor`
   - repositories are project-scoped; never add an unscoped query
   - events are append-only and redacted
4. New benchmark tasks go in `src/mindmesh/eval/suites/`; keep them deterministic with scripted brains.

Open a pull request describing the behaviour change and how you verified it.
