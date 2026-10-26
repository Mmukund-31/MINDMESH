import { expect, test } from "@playwright/test";

/**
 * The signature demonstration, end to end through the UI:
 * failing run -> diagnose with the context receipt -> fix memory -> rerun -> compare -> benchmark.
 */
test("diagnose a wrong refund decision, fix memory, rerun and compare", async ({ page }) => {
  // 1. Overview flags the run a human marked incorrect.
  await page.goto("/");
  await expect(page.getByTestId("project-name")).toHaveText("default");
  await expect(page.getByText("flagged incorrect").first()).toBeVisible();

  // 2. Execution Studio: open the failing premium-refund run.
  await page.getByRole("link", { name: "Execution Studio" }).click();
  await page.getByTestId("run-row").filter({ hasText: "A-7731" }).first().click();
  await expect(page.getByTestId("run-answer")).toContainText("DENIED");
  await expect(page.getByTestId("trace-graph")).toBeVisible();

  // The context receipt explains the cause: the updated policy was excluded (scope_mismatch).
  await page.getByTestId("tab-context").click();
  const excluded = page.getByTestId("receipt-excluded").filter({ hasText: "scope_mismatch" }).first();
  await expect(excluded).toContainText("premium customers within 30 days");
  const runUrl = page.url();

  // 3. Fix it in Memory Explorer: promote the billing-scoped policy to project scope.
  await excluded.getByRole("link").click();
  await expect(page.getByRole("dialog")).toContainText("agent:billing");
  await page.getByTestId("edit-memory").click();
  await page.getByTestId("scope-input").fill("project");
  await page.getByTestId("save-memory").click();
  await expect(page.getByRole("dialog")).toContainText("v2");
  await page.keyboard.press("Escape");

  // 4. Rerun the original task with the corrected memory.
  await page.goto(runUrl);
  await page.getByTestId("rerun").click();
  await expect(page.getByTestId("run-answer")).toContainText("APPROVED", { timeout: 20_000 });

  // 5. Replay Lab comparison shows where behaviour diverged and why.
  await page.getByRole("link", { name: "Compare with parent" }).click();
  await expect(page.getByTestId("answer-A")).toContainText("DENIED");
  await expect(page.getByTestId("answer-B")).toContainText("APPROVED");
  await expect(page.getByTestId("divergence")).toContainText("diverged at step");
  await expect(page.getByTestId("context-added").first()).toContainText("premium customers within 30 days");

  // 6. Benchmark: baseline vs misconfigured vs fixed.
  await page.getByTestId("run-benchmark").click();
  const table = page.getByTestId("benchmark-table");
  await expect(table).toBeVisible({ timeout: 45_000 });
  await expect(table).toContainText("mindmesh");
  await expect(table.getByRole("row", { name: /Task success/ })).toContainText("100%");
});

test("approve a paused refund from the Control Room", async ({ page }) => {
  await page.goto("/control");
  const card = page.getByTestId("approval-card").first();
  await expect(card).toContainText("refund.issue");
  await card.getByTestId("approve-card").click();
  await expect(page.getByText("Decision history")).toBeVisible();
  await page.getByRole("tab", { name: /Blocked actions/ }).click();
  await expect(page.getByTestId("blocked-row").filter({ hasText: "block-large-refunds" }).first()).toBeVisible();
});

test("orchestration lab renders the research workflow DAG", async ({ page }) => {
  await page.goto("/orchestration");
  await expect(page.getByTestId("workflow-graph")).toBeVisible();
  await expect(page.getByTestId("wf-task-verify")).toContainText("succeeded");
  await expect(page.getByText(/rejected write/)).toBeVisible();
});
