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

try {
  await page.goto(baseUrl, { waitUntil: "networkidle" });
  await page.getByRole("heading", { name: /Your conversation with Melli/ }).waitFor();
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

  await page.getByLabel("Message Melli").fill("Give me a concise local readiness check.");
  await page.getByRole("button", { name: "Send message" }).click();
  const response = page.getByText(/^Synthetic local reply\./);
  await response.waitFor({ timeout: 20_000 });
  await response.click();
  await page.getByRole("heading", { name: "Turn details" }).waitFor();
  await page.getByText("deterministic-fixture-v1", { exact: true }).waitFor();
  await page.screenshot({
    path: `${outputDirectory}/conversation-desktop.png`,
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

  await page.getByRole("tab", { name: "Retention" }).click();
  await page.getByText("Backup expiry", { exact: true }).waitFor();
  await page.getByText("0 objects", { exact: true }).first().waitFor();
  await page.screenshot({
    path: `${outputDirectory}/operations-retention-desktop.png`,
    fullPage: true,
  });

  await page.setViewportSize({ width: 390, height: 844 });
  await scrollPageShell(0);
  await page.screenshot({
    path: `${outputDirectory}/operations-retention-mobile.png`,
  });

  await page.getByRole("tab", { name: "Export" }).click();
  await page.getByText("melloa.canonical-owner-export", { exact: true }).waitFor();
  await scrollPageShell(0);
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

  await page.getByRole("link", { name: "Providers" }).click();
  await page.getByRole("heading", { name: "Providers" }).waitFor();
  await page.screenshot({
    path: `${outputDirectory}/providers-mobile.png`,
  });
  await page.locator(".page-shell").evaluate((element) => {
    element.scrollTop = element.scrollHeight;
  });
  const providerGuidanceBox = await page.locator(".provider-guidance").boundingBox();
  const mobileNavBox = await page.locator(".mobile-nav").boundingBox();
  if (
    providerGuidanceBox === null ||
    mobileNavBox === null ||
    providerGuidanceBox.y + providerGuidanceBox.height > mobileNavBox.y - 8
  ) {
    throw new Error("Provider mobile content does not clear the bottom navigation");
  }
  await scrollPageShell(0);

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
