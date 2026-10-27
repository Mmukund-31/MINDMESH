# Deployment (Render + Vercel)

The hosted MindMesh runs entirely in the cloud: the API on Render (Docker), PostgreSQL 16 + pgvector on Render,
and Studio on Vercel. Nothing depends on a developer laptop.

| Component | URL | Hosting |
|---|---|---|
| Public demo (read-only) | https://mindmesh-studio.vercel.app | Vercel production deployment |
| Developer Studio (protected) | https://mindmesh-studio-dev.vercel.app | Vercel preview deployment, behind Vercel login |
| API | https://mindmesh-api-wa1c.onrender.com (`/healthz`, `/api/v1`) | Render web service `mindmesh-api`, Docker, Singapore |
| Database | private network only | Render PostgreSQL `mindmesh-db`, free plan |

## Environments and access

- **Public demo.** The production Studio build bakes in `VITE_DEFAULT_API_KEY`, a `read` key bound to the
  separate `demo` project. Visitors can browse runs, traces, memories, policies and workflows, use previews and
  simulations, and open live streams. Every change returns `403 read-only API key`. Studio shows a banner and
  disables the guided experiment's run buttons.
- **Developer environment.** The preview deployment has no default key, and Vercel Deployment Protection
  requires a Vercel login on the team to open it. In Studio, go to **Settings** and enter the admin key
  (`MINDMESH_API_KEY`). It has full access to the private `default` project. The demo project is not visible
  with this key, and the developer project is not visible with the public key.

Secrets live only in Render's environment and in the operator's local `~/.mindmesh-deploy.env`
(`MINDMESH_ADMIN_KEY`, `MINDMESH_SECRET_KEY`, `MINDMESH_PUBLIC_KEY`, `RENDER_API_KEY`). They are never in git.

## API configuration (Render environment)

| Variable | Value |
|---|---|
| `MINDMESH_ENV` | `production` (refuses to start with unsafe settings) |
| `MINDMESH_DATABASE_URL` | the database's internal connection string |
| `MINDMESH_API_KEY`, `MINDMESH_SECRET_KEY` | 32+ character secrets |
| `MINDMESH_PUBLIC_KEY` | read-only demo key, with `MINDMESH_SEED_PUBLIC=true` |
| `MINDMESH_CORS_ORIGINS` | `https://mindmesh-studio.vercel.app,https://mindmesh-studio-dev.vercel.app` |
| `MINDMESH_RATE_LIMIT`, `MINDMESH_RATE_LIMIT_WRITES` | `300`, `60` per client IP per minute |
| `FORWARDED_ALLOW_IPS` | Render's private ranges plus Cloudflare's published ranges (see `render.yaml`) |
| `PORT` | `8000` |

Render sits behind Cloudflare. Trusting only those proxies makes uvicorn take the client from the rightmost
untrusted `X-Forwarded-For` entry, which Cloudflare appends. A forged `X-Forwarded-For` therefore cannot evade
the rate limit. This was verified by sending forged headers and checking the access log.

Migrations run on startup under a PostgreSQL advisory lock. The `demo` project is seeded once, on first boot,
and is not reseeded on restarts.

## Deploying changes

- **API:** pushing to `main` redeploys automatically (`autoDeploy`). Environment changes need a manual deploy
  (Render dashboard → Manual Deploy, or `POST /v1/services/{id}/deploys`).
- **Public Studio:** `cd studio && vercel deploy --prod`. The build reads `VITE_API_URL` and
  `VITE_DEFAULT_API_KEY` from the Vercel project's production environment.
- **Developer Studio:** `cd studio && vercel deploy`, then
  `vercel alias set <preview-url> mindmesh-studio-dev.vercel.app`. The preview environment sets only
  `VITE_API_URL`.

`render.yaml` describes the same API and database as a Render Blueprint, for recreating the stack.

## Verifying a deployment

```bash
MINDMESH_URL=https://mindmesh-api-wa1c.onrender.com \
MINDMESH_STUDIO_ORIGIN=https://mindmesh-studio.vercel.app \
MINDMESH_PUBLIC_KEY=... MINDMESH_ADMIN_KEY=... \
python scripts/verify_deployment.py --rate-limit
```

The script runs 26 checks:

- HTTPS and the HTTP→HTTPS redirect
- health and database
- docs disabled
- 401s
- roles and project isolation
- read-only refusal
- CORS
- the guided experiment run end to end, with its server-sent event stream and trace
- 404, 422 and 413 errors
- the write rate limit

## Rotating keys

- **Admin key:** change `MINDMESH_API_KEY` on Render and redeploy. The previous value is revoked at startup.
- **Public key:** change `MINDMESH_PUBLIC_KEY` on Render, update `VITE_DEFAULT_API_KEY` in Vercel production,
  and redeploy both.
- **Other keys:** create extra keys with `mindmesh keys create --project <name> [--role read]` (run it against the
  database URL). Revoke them with `mindmesh keys revoke`, or manage keys in Studio (Settings).

## Free-tier limits

- **Cold starts.** The API sleeps after 15 idle minutes. The first request then takes about 50 seconds while
  the instance starts.
- **Shared instance hours.** Free instance hours (750/month) are shared with the workspace's other free services.
- **Database expiry.** The free database **expires on 2026-11-26** (30 days after creation). Before then,
  upgrade it to a paid plan, or create a new database and point `MINDMESH_DATABASE_URL` at it. The demo
  reseeds itself; developer data would need a `pg_dump` / `pg_restore`.
- **Scripted models.** Agents use deterministic scripted models; no hosted LLM is configured
  (`MINDMESH_MODEL` unset).
