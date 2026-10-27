import { readFileSync } from "node:fs";
import { expect, test } from "@playwright/test";

/** Developer tooling: API-key management and JSON exports of runs and benchmark results. */
test("create, use and revoke an API key from Settings", async ({ page, request }) => {
  await page.goto("/settings");
  await expect(page.getByTestId("keys-table")).toContainText("bootstrap");

  await page.getByTestId("key-name").fill("e2e-ci");
  await page.getByTestId("key-role").selectOption("read");
  await page.getByTestId("create-key").click();
  const key = (await page.getByTestId("new-key").locator("code").textContent())!.trim();
  await expect(page.getByTestId("keys-table")).toContainText("e2e-ci");

  // The new key works against the API, read-only.
  const api = "http://127.0.0.1:8765/api/v1";
  expect((await request.get(`${api}/runs`, { headers: { "X-API-Key": key } })).status()).toBe(200);
  expect((await request.post(`${api}/memories/expire`, { headers: { "X-API-Key": key } })).status()).toBe(403);

  page.once("dialog", (d) => d.accept());
  await page.getByRole("button", { name: "Revoke e2e-ci" }).click();
  await expect(page.getByTestId("keys-table")).not.toContainText("e2e-ci");
  expect((await request.get(`${api}/runs`, { headers: { "X-API-Key": key } })).status()).toBe(401);
});

test("export a run and the benchmark results as JSON", async ({ page }) => {
  await page.goto("/runs");
  await page.getByTestId("run-row").filter({ hasText: "A-7731" }).first().click();
  const [runFile] = await Promise.all([page.waitForEvent("download"), page.getByTestId("export-run").click()]);
  const run = JSON.parse(readFileSync((await runFile.path())!, "utf8"));
  expect(run.format).toBe("mindmesh.run/v1");
  expect(run.summary.answer).toContain("DENIED");
  expect(run.events.length).toBeGreaterThan(5);

  await page.goto("/replay?tab=benchmarks");
  await page.getByTestId("run-benchmark").click();
  await expect(page.getByTestId("benchmark-table")).toBeVisible({ timeout: 60_000 });
  const [evalFile] = await Promise.all([page.waitForEvent("download"), page.getByTestId("export-evals").click()]);
  const evals = JSON.parse(readFileSync((await evalFile.path())!, "utf8"));
  expect(evals.format).toBe("mindmesh.eval/v1");
  expect(evals.evals.map((e: { variant: string }) => e.variant).sort()).toEqual(
    ["baseline", "mindmesh", "mindmesh-misconfigured"],
  );

  const [report] = await Promise.all([page.waitForEvent("download"), page.getByTestId("export-report").click()]);
  expect(report.suggestedFilename()).toBe("refund-report.md");
  expect(readFileSync((await report.path())!, "utf8")).toContain("# Benchmark: `refund`");
});
