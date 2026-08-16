import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("shell exposes every mandatory inspection area", async () => {
  const source = await readFile(new URL("../src/view.ts", import.meta.url), "utf8");
  for (const area of ["Conversation", "Timeline", "Memory", "Runs & Decisions", "Media", "Operations"]) {
    assert.match(source, new RegExp(`label: "${area.replace("&", "\\&")}"`));
  }
});

test("shell states private and Guardian boundaries", async () => {
  const source = await readFile(new URL("../src/main.ts", import.meta.url), "utf8");
  assert.match(source, /Private network only/);
  assert.match(source, /Guardian read-only contract/);
  assert.match(source, /External actions disabled/);
  assert.match(source, /cannot mutate Guardian authority/);
});

test("shell wires every currently implemented owner workflow", async () => {
  const source = await readFile(new URL("../src/main.ts", import.meta.url), "utf8");
  for (const operation of [
    "api.login",
    "api.logout",
    "api.createThread",
    "api.postMessage",
    "api.listProcessing",
    "api.resumeMessage",
    "api.listDeliveries",
    "api.enqueueDelivery",
    "api.resumeDelivery",
    "api.listTelegramPairingCandidates",
    "api.inspectTelegramPairing",
    "api.confirmTelegramPairing",
    "api.revokeTelegramPairing",
    "api.inspectTurn",
    "api.inspectMemory",
    "api.correctMemory",
    "api.disputeMemory",
    "api.retractMemory",
    "api.modelActivity",
    "api.healthDetail",
    "api.mediaCatalog",
    "api.retentionReport",
  ]) {
    assert.match(source, new RegExp(operation.replace(".", "\\.")));
  }
});

test("retention inspection stays honest and does not invent deletion controls", async () => {
  const source = await readFile(new URL("../src/main.ts", import.meta.url), "utf8");
  assert.match(source, /Retention and deletion/);
  assert.match(source, /never treats correction, retraction, backup expiry, or restart as erasure/);
  assert.match(source, /id="retention-policy-list"/);
  assert.doesNotMatch(source, /id="retention-delete/);
});

test("API and owner values are written as text rather than interpreted markup", async () => {
  const source = await readFile(new URL("../src/main.ts", import.meta.url), "utf8");
  assert.equal(source.match(/\.innerHTML\s*=/g)?.length, 1);
  assert.match(source, /app\.innerHTML = shell/);
  assert.match(source, /writeText\(body, messageBody\(message\)\)/);
  assert.match(source, /writeText\(output, formatJson\(value\)\)/);
});

test("static server binds only to loopback", async () => {
  const server = await readFile(new URL("../server.mjs", import.meta.url), "utf8");
  assert.match(server, /const host = "127\.0\.0\.1"/);
  assert.doesNotMatch(server, /0\.0\.0\.0/);
  assert.match(server, /MELLOA_CORE_URL/);
  assert.match(server, /url\.pathname\.startsWith\("\/api\/"\)/);
});

test("browser client never persists session or CSRF secrets", async () => {
  const client = await readFile(new URL("../src/api.ts", import.meta.url), "utf8");
  const shell = await readFile(new URL("../src/main.ts", import.meta.url), "utf8");
  assert.doesNotMatch(`${client}\n${shell}`, /localStorage|sessionStorage|document\.cookie/);
  assert.match(client, /credentials: "same-origin"/);
  assert.match(client, /X-Melloa-CSRF/);
  assert.match(shell, /refs\.credential\.value = ""/);
});

test("Telegram pairing stays secondary, redacted, transient, and explicitly confirmed", async () => {
  const source = await readFile(new URL("../src/main.ts", import.meta.url), "utf8");
  const consoleState = source.match(/type ConsoleState = \{[\s\S]*?\n\};/)?.[0] ?? "";
  assert.match(source, /Optional secondary owner channel/);
  assert.match(source, /Telegram never owns identity or canonical history/);
  assert.match(source, /redactTelegramIdentifier/);
  assert.match(source, /input\.type = "password"/);
  assert.match(source, /input\.autocomplete = "off"/);
  assert.match(source, /const confirmationCode = input\.value;\n\s+input\.value = ""/);
  assert.doesNotMatch(consoleState, /confirmationCode|challenge/i);
  assert.match(source, /window\.confirm\([\s\S]*?Confirm/);
  assert.match(source, /await api\.confirmTelegramPairing[\s\S]*?await loadTelegramPairing\(\)/);
  assert.match(source, /await api\.revokeTelegramPairing[\s\S]*?await loadTelegramPairing\(\)/);
});
