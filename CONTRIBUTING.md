# Contributing to MINDMESH

1. `python -m venv .venv && pip install -e ".[server,postgres,dev]"` and `cd studio && npm install`.
   Copy `.env.example` to `.env` for Docker Compose settings (e.g. `POSTGRES_PORT=5433` when 5432 is taken).
2. Make your change, with tests:
   - Python: `pytest` (unit, integration, security); `ruff check .`
   - PostgreSQL: `docker compose up -d postgres` then
     `MINDMESH_TEST_DATABASE_URL=postgresql://mindmesh:mindmesh@127.0.0.1:5432/mindmesh pytest -m postgres`
     (dedicated tests), or the same variable with `pytest -m "not ollama"` to run the entire suite on
     PostgreSQL. Each test starts from an empty schema, so point it at a scratch database.
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

## Windows notes

- Use `127.0.0.1`, not `localhost`, in database URLs: `localhost` resolves to IPv6 `::1` first, which Docker
  Desktop accepts without answering, so each new connection waits for the 10 s connect timeout.
- The CLI, server and tests select a `SelectorEventLoop` on Windows automatically (psycopg's async driver
  cannot use the default `ProactorEventLoop`). In your own scripts use `mindmesh.core.aio.run(main())`
  instead of `asyncio.run(main())` when talking to PostgreSQL.
- With **Smart App Control** on, Windows blocks unsigned native files: the venv's `.exe` launchers and
  SQLAlchemy's compiled extensions. Run tools as modules (`python -m mindmesh.cli …`, `python -m pytest`,
  `python -m ruff`) and install SQLAlchemy without its extensions (same behaviour, pure Python):
  `set DISABLE_SQLALCHEMY_CEXT=1 && python -m pip install --force-reinstall --no-deps --no-binary sqlalchemy sqlalchemy`
- Playwright: `set PW_CHANNEL=msedge && npx playwright test` uses the installed Edge.
