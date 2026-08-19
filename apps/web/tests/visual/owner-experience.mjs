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
  new URL("../../../../dist/melloa-screenshots/", import.meta.url),
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

async function assertNoHorizontalOverflow() {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
  if (overflow) {
    throw new Error("owner experience has horizontal overflow");
  }
}

try {
  await page.goto(baseUrl, { waitUntil: "networkidle" });
  await page.getByRole("heading", { name: "Pick up where you left off." }).waitFor();
  await page.getByText("Private access verified", { exact: true }).waitFor();
  await page.screenshot({ path: `${outputDirectory}/login-desktop.png`, fullPage: true });

  await page.getByLabel("Owner credential").fill(credential);
  await page.getByRole("button", { name: /Continue to Melli/ }).click();
  await page.getByRole("link", { name: "Open Melli" }).waitFor();
  await page.getByRole("button", { name: "Start a new conversation" }).click();
  await page.getByRole("heading", { name: "New conversation" }).waitFor();
  await page.getByRole("heading", { name: "Melli needs a capable model" }).waitFor();
  await page.getByText("The old fixed tour has been removed", { exact: false }).waitFor();
  await assertNoHorizontalOverflow();
  await page.screenshot({ path: `${outputDirectory}/conversation-desktop.png`, fullPage: true });

  await page.getByRole("link", { name: "Data and safety" }).click();
  await page.getByRole("heading", { name: "Data & safety" }).waitFor();
  await page.getByRole("heading", { name: "Your data" }).waitFor();
  await page.getByRole("heading", { name: "Independent protection" }).waitFor();
  await assertNoHorizontalOverflow();
  await page.screenshot({ path: `${outputDirectory}/data-safety-desktop.png`, fullPage: true });

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goBack();
  await page.getByRole("heading", { name: "New conversation" }).waitFor();
  await assertNoHorizontalOverflow();
  await page.screenshot({ path: `${outputDirectory}/conversation-mobile.png` });

  await page.getByRole("button", { name: "Open conversations" }).click();
  const conversationScrim = page.locator(".thread-panel-scrim");
  await conversationScrim.waitFor();
  await page.screenshot({ path: `${outputDirectory}/conversations-mobile.png` });
  await conversationScrim.click({ position: { x: 360, y: 200 } });

  await page.getByRole("link", { name: "Safety", exact: true }).click();
  await page.getByRole("heading", { name: "Data & safety" }).waitFor();
  await assertNoHorizontalOverflow();
  await page.screenshot({ path: `${outputDirectory}/data-safety-mobile.png` });
} finally {
  await browser.close();
}
