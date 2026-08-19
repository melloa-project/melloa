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

async function assertVisibleElementsInsideViewport(label) {
  const result = await page.evaluate(() => {
    const viewportWidth = document.documentElement.clientWidth;
    const viewportHeight = document.documentElement.clientHeight;
    const offenders = [];
    for (const element of document.querySelectorAll("*")) {
      const style = window.getComputedStyle(element);
      if (
        style.display === "none"
        || style.visibility === "hidden"
        || Number.parseFloat(style.opacity) === 0
      ) {
        continue;
      }
      const rect = element.getBoundingClientRect();
      if (rect.width === 0 || rect.height === 0 || rect.bottom <= 0 || rect.top >= viewportHeight) {
        continue;
      }
      if (rect.left >= -0.5 && rect.right <= viewportWidth + 0.5) {
        continue;
      }
      const htmlElement = element instanceof HTMLElement ? element : null;
      offenders.push({
        element: [
          element.tagName.toLowerCase(),
          htmlElement?.id === "" || htmlElement?.id === undefined ? "" : `#${htmlElement.id}`,
          typeof htmlElement?.className === "string" && htmlElement.className.length > 0
            ? `.${htmlElement.className.trim().split(/\s+/).slice(0, 3).join(".")}`
            : "",
        ].join(""),
        left: Math.round(rect.left * 10) / 10,
        right: Math.round(rect.right * 10) / 10,
        text: element.textContent?.trim().replace(/\s+/g, " ").slice(0, 80) ?? "",
      });
      if (offenders.length === 12) {
        break;
      }
    }
    return {
      documentOverflow: document.documentElement.scrollWidth > viewportWidth,
      offenders,
      viewportWidth,
    };
  });
  if (result.documentOverflow || result.offenders.length > 0) {
    throw new Error(`${label} exceeds its ${result.viewportWidth}px viewport: ${JSON.stringify(result)}`);
  }
}

async function assertSettingsCanScroll(label) {
  const settings = page.locator(".safety-page");
  const result = await settings.evaluate((element) => {
    const initial = element.scrollTop;
    const scrollable = element.scrollHeight > element.clientHeight;
    element.scrollTop = element.scrollHeight;
    return {
      clientHeight: element.clientHeight,
      initial,
      scrollable,
      scrollHeight: element.scrollHeight,
      scrolled: element.scrollTop > initial,
    };
  });
  if (!result.scrollable || !result.scrolled) {
    throw new Error(`${label} settings are not vertically scrollable: ${JSON.stringify(result)}`);
  }
}

async function assertClosedDrawerCannotReceiveFocus(label) {
  const result = await page.locator(".thread-panel").evaluate((panel) => {
    const control = panel.querySelector("button, a, input, textarea, select");
    if (!(control instanceof HTMLElement)) {
      throw new Error("conversation drawer has no focusable control");
    }
    control.focus();
    return {
      focused: document.activeElement === control,
      pointerEvents: getComputedStyle(panel).pointerEvents,
      visibility: getComputedStyle(panel).visibility,
    };
  });
  if (result.focused || result.visibility !== "hidden" || result.pointerEvents !== "none") {
    throw new Error(`${label} closed drawer remains interactive: ${JSON.stringify(result)}`);
  }
}

async function openConversationDrawer(screenshotName) {
  await page.getByRole("button", { name: "Open conversations" }).click();
  await page.locator(".thread-panel").waitFor({ state: "visible" });
  await page.screenshot({ path: `${outputDirectory}/${screenshotName}` });
}

async function closeConversationDrawerWithEscape(label) {
  await page.keyboard.press("Escape");
  await page.locator(".thread-panel").waitFor({ state: "hidden" });
  await assertClosedDrawerCannotReceiveFocus(label);
}

async function inspectConversationAt(width, height, suffix) {
  await page.setViewportSize({ width, height });
  await page.getByRole("heading", { name: "New conversation" }).waitFor();
  await assertClosedDrawerCannotReceiveFocus(`${suffix} conversation`);
  await assertVisibleElementsInsideViewport(`${suffix} conversation`);
  await page.screenshot({ path: `${outputDirectory}/conversation-${suffix}.png` });
  await openConversationDrawer(`conversations-${suffix}.png`);
  await assertVisibleElementsInsideViewport(`${suffix} open conversation drawer`);
  await closeConversationDrawerWithEscape(`${suffix} conversation`);
}

async function inspectSettingsAt(width, height, suffix) {
  await page.setViewportSize({ width, height });
  await page.getByRole("link", { name: "Safety", exact: true }).click();
  await page.getByRole("heading", { name: "Data & safety" }).waitFor();
  await assertVisibleElementsInsideViewport(`${suffix} settings`);
  await assertSettingsCanScroll(suffix);
  await page.screenshot({ path: `${outputDirectory}/data-safety-${suffix}.png` });
  await page.locator(".safety-page").evaluate((element) => { element.scrollTop = 0; });
  await page.getByRole("link", { name: "Melli", exact: true }).click();
  await page.getByRole("heading", { name: "New conversation" }).waitFor();
}

try {
  await page.goto(baseUrl, { waitUntil: "networkidle" });
  await page.getByRole("heading", { name: "Pick up where you left off." }).waitFor();
  await page.getByText("Private access verified", { exact: true }).waitFor();
  await assertVisibleElementsInsideViewport("desktop login");
  await page.screenshot({ path: `${outputDirectory}/login-desktop.png`, fullPage: true });

  await page.setViewportSize({ width: 390, height: 844 });
  const credentialInput = page.getByLabel("Owner credential");
  if (await credentialInput.evaluate((element) => document.activeElement === element)) {
    throw new Error("mobile login unexpectedly autofocuses the credential field");
  }
  await assertVisibleElementsInsideViewport("390px login");
  await page.screenshot({ path: `${outputDirectory}/login-390px.png`, fullPage: true });

  await credentialInput.fill(credential);
  await page.getByRole("button", { name: /Continue to Melli/ }).click();
  await page.getByRole("link", { name: "Open Melli" }).waitFor();
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.getByRole("button", { name: "Start a new conversation" }).click();
  await page.getByRole("heading", { name: "New conversation" }).waitFor();
  await page.getByRole("heading", { name: "Melli isn’t connected yet" }).waitFor();
  await page.getByText("A private model connection needs attention", { exact: false }).waitFor();
  await assertVisibleElementsInsideViewport("desktop conversation");
  await page.screenshot({ path: `${outputDirectory}/conversation-desktop.png` });

  await page.getByRole("link", { name: "Data and safety" }).click();
  await page.getByRole("heading", { name: "Data & safety" }).waitFor();
  await page.getByRole("heading", { name: "Your data" }).waitFor();
  await page.getByRole("heading", { name: "Independent protection" }).waitFor();
  await assertVisibleElementsInsideViewport("desktop settings");
  await page.screenshot({ path: `${outputDirectory}/data-safety-desktop.png` });
  await page.getByRole("link", { name: "Back to Melli" }).click();

  await inspectConversationAt(390, 844, "390px");
  await inspectSettingsAt(390, 844, "390px");
  await inspectConversationAt(320, 700, "320px");
  await inspectSettingsAt(320, 700, "320px");
} finally {
  await browser.close();
}
