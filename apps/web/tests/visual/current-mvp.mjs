import { mkdir, readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

import { chromium } from "@playwright/test";

const baseUrl = process.env.MELLOA_WEB_URL ?? "http://127.0.0.1:8787";
const credentialPath = process.env.MELLOA_OWNER_CREDENTIAL_FILE;
if (credentialPath === undefined || credentialPath.length === 0) {
  throw new Error("MELLOA_OWNER_CREDENTIAL_FILE is required");
}
const credential = (await readFile(credentialPath, "utf8")).trim();
if (credential.length < 32) {
  throw new Error("owner credential file is invalid");
}

const defaultOutput = fileURLToPath(
  new URL("../../../../docs/assets/current-mvp/", import.meta.url),
);
const outputDirectory = process.env.MELLOA_SCREENSHOT_DIR ?? defaultOutput;
await mkdir(outputDirectory, { recursive: true });

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({
  viewport: { width: 1440, height: 960 },
  colorScheme: "light",
  reducedMotion: "reduce",
});
const page = await context.newPage();

async function scrollPageShell(top) {
  await page.locator(".page-shell").evaluate((element, nextTop) => {
    element.scrollTop = nextTop;
  }, top);
}

async function assertPageClearsMobileNavigation(subjectSelector, label) {
  await page.locator(".page-shell").evaluate((element) => {
    element.scrollTop = element.scrollHeight;
  });
  const subjectBox = await page.locator(subjectSelector).last().boundingBox();
  const mobileNavBox = await page.locator(".mobile-nav").boundingBox();
  if (
    subjectBox === null ||
    mobileNavBox === null ||
    subjectBox.y + subjectBox.height > mobileNavBox.y - 8
  ) {
    throw new Error(`${label} mobile content does not clear the bottom navigation`);
  }
  await scrollPageShell(0);
}

async function scrollIntoPageView(subjectSelector, block = "start") {
  await page.locator(subjectSelector).first().evaluate((element, scrollBlock) => {
    element.scrollIntoView({ block: scrollBlock });
  }, block);
}

try {
  await page.goto(baseUrl, { waitUntil: "networkidle" });
  await page.getByRole("heading", { name: /Your conversation with Melli/ }).waitFor();
  await page.getByRole("button", { name: "Retry signed status check" }).waitFor();
  await page.screenshot({
    path: `${outputDirectory}/login-desktop.png`,
    fullPage: true,
  });

  await page.getByLabel("Owner credential").fill(credential);
  await page.getByRole("button", { name: /Open Owner Console/ }).click();
  await page.getByText("Conversations", { exact: true }).waitFor();

  await page.getByRole("button", { name: "New conversation" }).click();
  await page.getByLabel("Title").fill("Local MVP readiness");
  await page.getByRole("button", { name: "Create conversation" }).click();
  await page.getByRole("heading", { name: "Local MVP readiness" }).waitFor();
  await page.getByRole("heading", { name: "Start with what matters now" }).waitFor();
  await page.getByText("Use memory evidence", { exact: true }).waitFor();
  await page.getByText("Conversation created.", { exact: true }).waitFor({
    state: "hidden",
    timeout: 7_000,
  });
  await page.screenshot({
    path: `${outputDirectory}/conversation-starters-desktop.png`,
    fullPage: true,
  });

  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({
    path: `${outputDirectory}/conversation-starters-mobile.png`,
  });
  await page.setViewportSize({ width: 1440, height: 960 });

  await page.getByLabel("Message Melli").fill("Give me a concise local readiness check.");
  await page.getByRole("button", { name: "Send message" }).click();
  const response = page.getByText(/^Synthetic local reply\./);
  await response.waitFor({ timeout: 20_000 });
  await response.click();
  await page.getByRole("heading", { name: "Turn details" }).waitFor();
  await page.getByText("deterministic-fixture-v1", { exact: true }).first().waitFor();
  await page.screenshot({
    path: `${outputDirectory}/conversation-desktop.png`,
    fullPage: true,
  });

  await page.getByRole("link", { name: "Activity" }).click();
  await page.getByRole("heading", { name: "Activity" }).waitFor();
  await page.getByRole("heading", { name: "Run ledger" }).waitFor();
  await page.getByText("deterministic-fixture-v1", { exact: true }).first().waitFor();
  await page.getByRole("button", { name: /^Local \d+$/ }).waitFor();
  await page.getByText("No external disclosure", { exact: true }).waitFor();
  await page.screenshot({
    path: `${outputDirectory}/activity-desktop.png`,
    fullPage: true,
  });

  await page.getByRole("link", { name: "Memory" }).click();
  await page.getByRole("heading", { name: "Memory", exact: true }).waitFor();
  await page.getByLabel("Assertion ID").fill("assertion_00000000000000000000000000000001");
  await page.getByRole("button", { name: "Inspect memory" }).click();
  await page.getByText("assertion_00000000000000000000000000000001", { exact: true }).waitFor();
  await page.getByRole("heading", { name: "Provenance" }).waitFor();
  await page.getByRole("heading", { name: "State history" }).waitFor();
  await page.screenshot({
    path: `${outputDirectory}/memory-desktop.png`,
    fullPage: true,
  });

  await page.getByRole("link", { name: "Providers" }).click();
  await page.getByRole("heading", { name: "Providers" }).waitFor();
  await page.getByRole("heading", { name: "Deterministic synthetic fixture", exact: true }).waitFor();
  await page.screenshot({
    path: `${outputDirectory}/providers-desktop.png`,
    fullPage: true,
  });

  await page.getByRole("link", { name: "Operations" }).click();
  await page.getByRole("heading", { name: "Operations" }).waitFor();
  await page.getByRole("tab", { name: "Export" }).click();
  await page.getByText("melloa.canonical-owner-export", { exact: true }).waitFor();
  await page.getByText("Unencrypted preview", { exact: true }).waitFor();
  await page.getByText("melloa.encrypted-owner-export-package", { exact: true }).waitFor();
  const [ownerExport] = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("button", { name: "Download current ZIP" }).click(),
  ]);
  if (!/^melloa-owner-export-export_[a-z0-9]+\.zip$/.test(ownerExport.suggestedFilename())) {
    throw new Error("Owner export download did not use the bounded attachment filename");
  }
  const ownerExportPath = await ownerExport.path();
  if (ownerExportPath === null) {
    throw new Error("Owner export download did not produce a local archive");
  }
  const ownerExportBytes = await readFile(ownerExportPath);
  if (
    ownerExportBytes.length < 4
    || ownerExportBytes[0] !== 0x50
    || ownerExportBytes[1] !== 0x4b
    || ownerExportBytes[2] !== 0x03
    || ownerExportBytes[3] !== 0x04
  ) {
    throw new Error("Owner export download is not a ZIP archive");
  }
  await page.getByText("Validated unencrypted export downloaded.", { exact: true }).waitFor();
  await page.screenshot({
    path: `${outputDirectory}/operations-export-desktop.png`,
    fullPage: true,
  });
  await page.getByText("Validated unencrypted export downloaded.", { exact: true }).waitFor({
    state: "hidden",
    timeout: 7_000,
  });

  await page.getByRole("link", { name: "Timeline" }).click();
  await page.getByRole("heading", { name: "Timeline", exact: true }).waitFor();
  await page.getByRole("heading", { name: "Canonical timeline" }).waitFor();
  await page.getByRole("button", { name: /^Audit \d+$/ }).click();
  await page.getByText("Owner export preview generated and audited.", { exact: true }).first().waitFor();
  await page.getByText("Plaintext preview", { exact: true }).first().waitFor();
  await page.screenshot({
    path: `${outputDirectory}/timeline-audit-desktop.png`,
    fullPage: true,
  });

  await page.getByRole("button", { name: /^All \d+$/ }).click();
  await page.getByText("Structured reply turn recorded with decision evidence.", { exact: true }).first().waitFor();
  await page.screenshot({
    path: `${outputDirectory}/timeline-desktop.png`,
    fullPage: true,
  });

  await page.setViewportSize({ width: 390, height: 844 });
  await scrollIntoPageView(".timeline-card");
  await page.screenshot({
    path: `${outputDirectory}/timeline-mobile.png`,
  });
  await assertPageClearsMobileNavigation(".timeline-disclosure-panel", "Timeline");

  await page.getByRole("button", { name: /^Audit \d+$/ }).click();
  await page.getByText("Owner export preview generated and audited.", { exact: true }).first().waitFor();
  await scrollIntoPageView(".timeline-card");
  await page.screenshot({
    path: `${outputDirectory}/timeline-audit-mobile.png`,
  });
  await assertPageClearsMobileNavigation(".timeline-disclosure-panel", "Timeline audit");

  await page.getByRole("link", { name: "Operations" }).click();
  await page.getByRole("heading", { name: "Operations" }).waitFor();
  await page.getByRole("tab", { name: "Retention" }).click();
  await page.getByText("Backup expiry", { exact: true }).waitFor();
  await page.getByText("0 objects", { exact: true }).first().waitFor();
  await page.setViewportSize({ width: 1440, height: 960 });
  await scrollPageShell(0);
  await page.screenshot({
    path: `${outputDirectory}/operations-retention-desktop.png`,
    fullPage: true,
  });

  await page.setViewportSize({ width: 390, height: 844 });
  await scrollIntoPageView(".backup-disclosure");
  await page.screenshot({
    path: `${outputDirectory}/operations-retention-mobile.png`,
  });

  await page.getByRole("tab", { name: "Export" }).click();
  await page.getByText("melloa.canonical-owner-export", { exact: true }).waitFor();
  await scrollIntoPageView(".export-summary-panel");
  await page.screenshot({
    path: `${outputDirectory}/operations-export-mobile.png`,
  });
  await page.getByText("Validated unencrypted export downloaded.", { exact: true }).waitFor({
    state: "hidden",
    timeout: 7_000,
  });
  const exportDownloadButton = page.getByRole("button", { name: "Download current ZIP" });
  await exportDownloadButton.evaluate((element) => element.scrollIntoView({ block: "center" }));
  await page.screenshot({
    path: `${outputDirectory}/operations-export-download-mobile.png`,
  });

  await page.getByRole("link", { name: "Activity" }).click();
  await page.getByRole("heading", { name: "Activity" }).waitFor();
  await page.getByText("deterministic-fixture-v1", { exact: true }).first().waitFor();
  await page.screenshot({
    path: `${outputDirectory}/activity-mobile.png`,
  });
  await assertPageClearsMobileNavigation(".activity-row", "Activity");

  await page.getByRole("link", { name: "Memory" }).click();
  await page.getByRole("heading", { name: "Memory", exact: true }).waitFor();
  await page.getByLabel("Assertion ID").fill("assertion_00000000000000000000000000000001");
  await page.getByRole("button", { name: "Inspect memory" }).click();
  await page.getByText("assertion_00000000000000000000000000000001", { exact: true }).waitFor();
  await page.screenshot({
    path: `${outputDirectory}/memory-mobile.png`,
  });
  await assertPageClearsMobileNavigation(".memory-history-column", "Memory");

  await page.getByRole("link", { name: "Providers" }).click();
  await page.getByRole("heading", { name: "Providers" }).waitFor();
  await page.screenshot({
    path: `${outputDirectory}/providers-mobile.png`,
  });
  await assertPageClearsMobileNavigation(".provider-guidance", "Provider");

  await page.getByRole("link", { name: "Settings" }).click();
  await page.getByRole("heading", { name: "Settings" }).waitFor();
  await page.getByText("Synthetic, no network", { exact: true }).waitFor();
  const telegramCard = page.locator(".telegram-card");
  await telegramCard.evaluate((element) => element.scrollIntoView({ block: "start" }));
  await page.screenshot({
    path: `${outputDirectory}/settings-mobile.png`,
  });

  await page.setViewportSize({ width: 1440, height: 1100 });
  await scrollPageShell(0);
  await page.screenshot({
    path: `${outputDirectory}/settings-desktop.png`,
    fullPage: true,
  });
} finally {
  await context.close();
  await browser.close();
}

console.log(`MVP screenshots written to ${outputDirectory}`);
