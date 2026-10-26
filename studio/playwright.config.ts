import { defineConfig, devices } from "@playwright/test";

// E2E runs against a real MindMesh API (fresh SQLite DB, demo seeded) and the Vite dev server.
const PY = process.env.MINDMESH_PYTHON ?? (process.platform === "win32" ? "..\\.venv\\Scripts\\python" : "../.venv/bin/python");
const DB = "sqlite:///./e2e-studio.db";

export default defineConfig({
  testDir: "e2e",
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: "http://127.0.0.1:5174",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  // PW_CHANNEL=msedge|chrome uses an installed browser instead of Playwright's bundled Chromium.
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], channel: process.env.PW_CHANNEL } }],
  webServer: [
    {
      command: `${PY} -c "import glob, os; [os.remove(f) for f in glob.glob('e2e-studio.db*')]" && ${PY} -m mindmesh.cli demo seed && ${PY} -m mindmesh.cli serve --port 8765`,
      url: "http://127.0.0.1:8765/healthz",
      reuseExistingServer: false,
      timeout: 120_000,
      env: { MINDMESH_DATABASE_URL: DB, PYTHONIOENCODING: "utf-8", MINDMESH_CORS_ORIGINS: "http://127.0.0.1:5174" },
    },
    {
      command: "npx vite --port 5174 --strictPort --host 127.0.0.1",
      url: "http://127.0.0.1:5174",
      reuseExistingServer: false,
      timeout: 120_000,
      env: { MINDMESH_API_URL: "http://127.0.0.1:8765" },
    },
  ],
});
