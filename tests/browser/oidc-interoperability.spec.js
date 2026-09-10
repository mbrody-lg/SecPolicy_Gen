const { expect, test } = require("@playwright/test");

test("authenticates through the local provider and resolves application access", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveURL(/identity\.test:8(?:080|443)/);

  await page.getByLabel("Username or email").fill("developer");
  await page.getByLabel("Password", { exact: true }).fill("fake-local-developer-password");
  await page.getByRole("button", { name: "Sign In" }).click();

  await expect(page).toHaveURL(/context-agent\.test\/$/);
  await expect(page.getByText("Generated contexts")).toBeVisible();
  await page.getByText("SecPolicyGen Local Organization", { exact: true }).first().click();
  await expect(page.getByText("11111111-1111-1111-1111-111111111111")).toBeVisible();
});
