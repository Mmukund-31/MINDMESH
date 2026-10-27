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
  // Outcome first, then the connected trace; the findings name the cause before any digging.
  await expect(page.getByTestId("trace-timeline")).toBeVisible();
  await expect(page.getByTestId("findings")).toContainText("Context excluded 1 memory");

  // The context receipt explains the cause: the updated policy was excluded (scope_mismatch).
  await page.getByTestId("tab-context").click();
  const excluded = page.getByTestId("receipt-excluded").filter({ hasText: "scope_mismatch" }).first();
  await expect(excluded).toContainText("premium customers within 30 days");
  const runUrl = page.url();

  // 3. Fix it in Memory Explorer: promote the billing-scoped policy to project scope.
  await excluded.getByRole("link").click();
  await expect(page.getByTestId("memory-detail")).toContainText("agent:billing");
  await expect(page.getByTestId("memory-visibility")).toBeVisible();
  await page.getByTestId("edit-memory").click();
  await page.getByTestId("scope-input").fill("project");
  await page.getByTestId("save-memory").click();
  await expect(page.getByTestId("memory-detail")).toContainText("v2");

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
  await page.getByRole("tab", { name: /Benchmarks/ }).click();
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
  // Every decision is in the audit trail, attributed to the key that made it.
  await page.getByRole("tab", { name: /Audit trail/ }).click();
  await expect(page.getByTestId("audit-row").first()).toContainText("approval.approved");
  // The permission matrix resolves rules per agent and tool: large refunds need approval or are denied.
  await page.getByRole("tab", { name: /Tool permissions/ }).click();
  await expect(page.getByTestId("perm-support-refund.issue")).toContainText("deny if amount gt 500");
});

test("orchestration lab renders the research workflow DAG", async ({ page }) => {
  await page.goto("/orchestration");
  await expect(page.getByTestId("workflow-graph")).toBeVisible();
  await expect(page.getByTestId("wf-task-verify")).toContainText("succeeded");
  await expect(page.getByTestId("task-inspector")).toContainText("verify rejected write");
});

/**
 * The first-run experience, using only what a newcomer sees: run -> understand the failure -> preview and
 * apply the fix -> before/after -> stress tests -> scorecard. Runs last in this file because "Run experiment"
 * re-seeds the scenario's memories, which the tests above navigate to.
 */
test("guided experiment: fail, diagnose, fix, compare, stress-test and measure", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByTestId("server-mode")).toContainText("Demo mode");
  await page.getByTestId("experiment-banner").click();

  // 1. Run: the trace streams, and the decision is flagged as wrong.
  await page.getByTestId("run-experiment").click();
  const original = page.getByTestId("live-run-experiment:original");
  // Starting resets and reseeds the scenario first: allow it the same time as the run itself.
  await expect(original.getByTestId("mode-demo")).toBeVisible({ timeout: 20_000 });
  await expect(original.getByTestId("feed-line").first()).toBeVisible();
  await expect(page.getByTestId("failure-verdict")).toBeVisible({ timeout: 20_000 });
  await expect(original.getByTestId("live-answer")).toContainText("DENIED");

  // 2. Diagnose: the receipt shows the current policy was out of the agent's scope.
  await expect(page.getByTestId("diagnosis-missed")).toContainText("premium customers within 30 days");
  await expect(page.getByTestId("root-cause")).toContainText("agent:billing");

  // 3. Fix: preview first (nothing written), then apply.
  await expect(page.getByTestId("apply-fix")).toBeDisabled();
  await page.getByTestId("preview-fix").click();
  const impact = page.getByTestId("memory-impact");
  await expect(impact).toContainText("gains access");
  await expect(impact.getByTestId("impact-included").first()).toContainText("premium customers within 30 days");
  await page.getByTestId("apply-fix").click();
  await expect(page.getByTestId("fix-applied")).toBeVisible();

  // 4. Rerun and compare before / after; a safe replay reproduces the original.
  await page.getByTestId("rerun-original").click();
  const ba = page.getByTestId("before-after");
  await expect(ba).toBeVisible({ timeout: 20_000 });
  await expect(ba.getByTestId("outcome-a")).toContainText("DENIED");
  await expect(ba.getByTestId("outcome-b")).toContainText("APPROVED");
  await expect(ba.getByTestId("context-added").first()).toContainText("premium customers within 30 days");
  await page.getByTestId("safe-replay").click();
  await expect(page.getByTestId("live-run-replay").getByTestId("mode-replay")).toBeVisible({ timeout: 20_000 });
  await expect(page.getByTestId("replay-verdict")).toContainText("reproduced the original decision exactly", { timeout: 20_000 });

  // 5. Stress tests: the injection is blocked by policy (not by the model), and retries ride out the outage.
  await page.getByTestId("run-injection").click();
  await expect(page.getByTestId("injection-verdict")).toBeVisible({ timeout: 20_000 });
  await expect(page.getByTestId("live-run-experiment:injection").getByTestId("event-feed")).toContainText(
    "Policy blocked refund.issue",
  );
  await page.getByTestId("preview-policy").click();
  await expect(page.getByTestId("policy-flip").first()).toContainText("amount=4999");
  await page.getByTestId("run-faults").click();
  await expect(page.getByTestId("faults-verdict")).toBeVisible({ timeout: 20_000 });
  await expect(page.getByTestId("live-run-experiment:faults").getByTestId("event-feed")).toContainText("injected fault");
  await expect(page.getByTestId("live-run-experiment:faults:unprotected").getByTestId("live-answer")).toContainText("ESCALATED");

  // 6. Measure: the scorecard and the plain-language improvement.
  await page.getByTestId("run-scorecard").click();
  // Earlier tests may have stored refund results already: wait for this measurement, not a previous one.
  await expect(page.getByTestId("run-scorecard")).toContainText("Measure again", { timeout: 60_000 });
  const score = page.getByTestId("scorecard");
  await expect(score).toBeVisible({ timeout: 60_000 });
  await expect(page.getByTestId("score-success_rate")).toContainText("100% (7/7)");
  await expect(page.getByTestId("improvement")).toContainText("took correct decisions from 4/7 (57%) to 7/7 (100%)");
  await expect(page.getByTestId("experiment-summary")).toBeVisible();
});
