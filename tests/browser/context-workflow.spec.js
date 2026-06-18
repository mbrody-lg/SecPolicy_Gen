const fs = require("node:fs");
const path = require("node:path");
const { expect, test } = require("@playwright/test");

const fixturePath = process.env.CONTEXT_BROWSER_FIXTURE_PATH
  || "/repo/migration/context-browser-smoke.json";
const manifest = JSON.parse(fs.readFileSync(path.resolve(fixturePath), "utf8"));

async function openContext(page, state) {
  const url = manifest.contexts[state];
  if (!url) {
    throw new Error(`Missing browser fixture context for state: ${state}`);
  }
  await page.goto(url);
  await expect(page.locator("[data-workplace-navigation]")).toBeVisible();
}

async function openTab(page, tabName) {
  await page.locator(`[data-workflow-tab-trigger="${tabName}"]`).first().click();
  const panel = page.locator(`[data-workflow-tab-panel="${tabName}"]`);
  await expect(panel).toBeVisible();
  return panel;
}

test.describe("Context Agent workflow release gate", () => {
  test("shows task-discovered questions in Intake and Context Building", async ({ page }) => {
    await openContext(page, "task_needs_context");

    const intake = await openTab(page, "intake");
    await expect(intake.getByText("Context Agent has 1 pending question")).toBeVisible();
    await expect(intake.getByText("Confirm the regulated operating country.")).toBeVisible();

    const contextBuilding = await openTab(page, "context-building");
    await expect(contextBuilding.getByText("Needs more information")).toBeVisible();
    await expect(contextBuilding.getByText("Required to complete context-plan task: Company profile.")).toBeVisible();
    await expect(contextBuilding.getByRole("button", { name: "Update context" })).toBeVisible();
  });

  test("shows execution evidence and final-context synthesis controls", async ({ page }) => {
    await openContext(page, "executed");

    const execution = await openTab(page, "execution");
    await expect(execution.getByText("Completed tasks: 1")).toBeVisible();
    await expect(execution.getByText("Patient records are the primary asset.")).toBeVisible();

    const finalContext = await openTab(page, "final-context");
    await expect(finalContext.getByRole("heading", { name: "Final context" })).toBeVisible();
    await expect(finalContext.getByText("Patient records are the primary asset.")).toBeVisible();
    await expect(finalContext.getByRole("button", { name: "Synthesize final context" })).toBeVisible();
  });

  test("gates policy generation until Final Context is ready", async ({ page }) => {
    await openContext(page, "final_needs_improvement");

    const blockedPolicy = await openTab(page, "policy-generation");
    await expect(blockedPolicy.getByText("Synthesize the final context before generating a policy.")).toBeVisible();
    await expect(blockedPolicy.locator("[data-generate-policy-button]")).toBeDisabled();

    await openContext(page, "ready");
    const readyPolicy = await openTab(page, "policy-generation");
    await expect(readyPolicy.locator("[data-generate-policy-button]")).toBeEnabled();
  });
});
