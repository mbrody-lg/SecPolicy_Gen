const { defineConfig, devices } = require("@playwright/test");

const baseURL = process.env.CONTEXT_BROWSER_BASE_URL || "http://context-agent:5000";
const localCertificateSpki = process.env.LOCAL_OIDC_CERT_SPKI;

module.exports = defineConfig({
  testDir: ".",
  timeout: 30_000,
  expect: {
    timeout: 5_000,
  },
  reporter: [["list"]],
  outputDir: "/tmp/secpolicy-playwright-results",
  use: {
    baseURL,
    launchOptions: localCertificateSpki
      ? { args: [`--ignore-certificate-errors-spki-list=${localCertificateSpki}`] }
      : undefined,
    trace: "retain-on-failure",
  },
  projects: [
    {
      name: "chromium-desktop",
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 1366, height: 900 },
      },
    },
    {
      name: "chromium-mobile",
      use: {
        ...devices["Pixel 7"],
      },
    },
  ],
});
