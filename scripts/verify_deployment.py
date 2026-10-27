"""Verify a deployed MindMesh API end to end, from outside (any machine, no local database).

    MINDMESH_URL=https://mindmesh-api.onrender.com \
    MINDMESH_STUDIO_ORIGIN=https://mindmesh-studio.vercel.app \
    MINDMESH_PUBLIC_KEY=... MINDMESH_ADMIN_KEY=... \
    python scripts/verify_deployment.py [--rate-limit]

Checks HTTPS, health and database, key roles and project isolation, read-only enforcement, CORS, the full guided
experiment flow with the admin key (run -> trace -> live stream), error handling, and optionally rate limiting
(``--rate-limit`` spends this client's write budget for a minute). Exits non-zero on the first failed check.
"""

from __future__ import annotations

import argparse
import os
import sys
import time

import httpx

PASSED: list[str] = []


def check(name: str, ok: bool, detail: object = "") -> None:
    if not ok:
        print(f"FAIL  {name}  {detail}")
        sys.exit(1)
    PASSED.append(name)
    print(f"ok    {name}" + (f"  ({detail})" if detail else ""))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rate-limit", action="store_true", help="also exhaust and verify the write rate limit")
    parser.add_argument("--local", action="store_true", help="rehearsal against a local http:// server: skip HTTPS checks")
    args = parser.parse_args()
    base = os.environ["MINDMESH_URL"].rstrip("/")
    origin = os.environ.get("MINDMESH_STUDIO_ORIGIN")
    public, admin = os.environ["MINDMESH_PUBLIC_KEY"], os.environ["MINDMESH_ADMIN_KEY"]
    v = f"{base}/api/v1"
    pub, adm = {"X-API-Key": public}, {"X-API-Key": admin}
    c = httpx.Client(timeout=httpx.Timeout(90.0, connect=90.0))  # free instances cold-start in ~1 min

    # transport and health
    if not args.local:
        check("served over HTTPS", base.startswith("https://"), base)
        plain = c.get("http://" + base.split("://", 1)[1] + "/healthz", follow_redirects=False)
        check("plain HTTP is redirected to HTTPS", plain.status_code in (301, 302, 307, 308)
              and plain.headers.get("location", "").startswith("https://"), plain.status_code)
    h = c.get(f"{base}/healthz")
    check("health: API up, PostgreSQL reachable", h.status_code == 200 and h.json().get("database") == "postgresql",
          h.text)
    check("API docs disabled in production", c.get(f"{base}/docs").status_code == 404)
    check("security headers", c.get(f"{base}/healthz").headers.get("x-content-type-options") == "nosniff")

    # keys, roles and isolation
    check("missing key -> 401", c.get(f"{v}/runs").status_code == 401)
    check("wrong key -> 401", c.get(f"{v}/runs", headers={"X-API-Key": "mm_wrong_0000000000000000"}).status_code == 401)
    me_pub, me_adm = c.get(f"{v}/me", headers=pub).json(), c.get(f"{v}/me", headers=adm).json()
    check("public key: read-only demo project", me_pub.get("role") == "read", me_pub)
    check("admin key: separate project, full access", me_adm.get("role") == "admin"
          and me_adm["project_id"] != me_pub["project_id"], me_adm.get("project_name"))
    demo_runs = c.get(f"{v}/runs", headers=pub, params={"limit": 500}).json()
    check("demo project is seeded", len(demo_runs) >= 5, f"{len(demo_runs)} runs")
    w = c.post(f"{v}/runs", headers=pub, json={"agent": "support", "task": "x"})
    check("public key cannot write", w.status_code == 403 and "read-only" in w.json()["detail"], w.status_code)
    other = c.get(f"{v}/runs/{demo_runs[0]['id']}", headers=adm)
    check("projects are isolated (demo run invisible to the admin project)", other.status_code == 404)

    # CORS
    if origin:
        pre = c.options(f"{v}/runs", headers={"Origin": origin, "Access-Control-Request-Method": "GET",
                                               "Access-Control-Request-Headers": "x-api-key"})
        check("CORS allows the Studio origin", pre.headers.get("access-control-allow-origin") == origin)
        bad = c.options(f"{v}/runs", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"})
        check("CORS rejects other origins", "access-control-allow-origin" not in bad.headers, bad.status_code)

    # full flow (admin): run the guided experiment, read its trace, stream its events
    check("experiment reset", c.post(f"{v}/experiments/refund/reset", headers=adm).status_code == 200)
    run = c.post(f"{v}/experiments/refund/runs", headers=adm, json={"scenario": "original"})
    check("experiment run started", run.status_code == 201, run.text[:200])
    run_id = run.json()["id"]
    token = c.post(f"{v}/runs/{run_id}/stream-token", headers=adm).json()["token"]
    events = []
    with c.stream("GET", f"{v}/runs/{run_id}/stream", params={"token": token}) as s:
        check("stream opens as server-sent events", s.status_code == 200
              and s.headers["content-type"].startswith("text/event-stream"), s.headers.get("content-type"))
        for line in s.iter_lines():
            if line.startswith("event:"):
                events.append(line)
            if "run.finished" in line or "run.failed" in line or len(events) > 400:
                break
    check("stream delivered events through the proxy", len(events) > 3, f"{len(events)} events")
    deadline = time.monotonic() + 60
    while (r := c.get(f"{v}/runs/{run_id}", headers=adm).json())["status"] not in ("succeeded", "failed"):
        check("run finishes within 60 s", time.monotonic() < deadline, r["status"])
        time.sleep(1)
    check("run finished", r["status"] == "succeeded", (r.get("result") or {}).get("answer", "")[:60])
    trace = c.get(f"{v}/runs/{run_id}/trace", headers=adm)
    check("trace recorded", trace.status_code == 200 and trace.json(), trace.status_code)
    pub_token = c.post(f"{v}/runs/{demo_runs[0]['id']}/stream-token", headers=pub)
    check("public key can open live streams", pub_token.status_code == 200)

    # error handling
    check("unknown run -> 404", c.get(f"{v}/runs/run_nope", headers=adm).status_code == 404)
    bad_json = c.post(f"{v}/runs", headers={**adm, "Content-Type": "application/json"}, content=b"{bad")
    check("malformed JSON -> 422", bad_json.status_code == 422)
    big = c.post(f"{v}/runs", headers={**adm, "Content-Type": "application/json"}, content=b"a" * 1_100_000)
    check("oversized body -> 413", big.status_code == 413)

    if args.rate_limit:
        codes = [c.post(f"{v}/context/preview", headers=adm, json={"query": "refund"}).status_code for _ in range(70)]
        limited = [x for x in codes if x == 429]
        check("write rate limit enforced", limited and codes[0] == 200, f"{codes.count(200)} ok, {len(limited)} x 429")
        r429 = c.post(f"{v}/context/preview", headers=adm, json={"query": "refund"})
        check("429 carries Retry-After", r429.status_code != 429 or "retry-after" in r429.headers)

    print(f"\nall {len(PASSED)} checks passed against {base}")


if __name__ == "__main__":
    main()
