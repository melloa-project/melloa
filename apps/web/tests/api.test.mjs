import assert from "node:assert/strict";
import test from "node:test";

import { ApiError, MelloaApi } from "../.test-dist/api.js";

const principal = {
  owner_id: "owner_00000000000000000000000000000001",
  session_id: "session_00000000000000000000000000000001",
  authentication_method: "auth.synthetic-opaque-token",
  authenticated_at: "2026-08-16T12:00:00Z",
  reauthenticated_until: "2026-08-16T12:05:00Z",
  expires_at: "2026-08-16T12:30:00Z",
};

function jsonResponse(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

test("client keeps the CSRF proof in memory and sends same-origin credentials", async () => {
  const calls = [];
  const api = new MelloaApi(async (input, init) => {
    calls.push({ input: String(input), init });
    if (String(input) === "/api/v1/auth/session") {
      return jsonResponse({ principal, csrf_token: "csrf-proof" });
    }
    return jsonResponse({ thread_id: "thread_00000000000000000000000000000001" }, 201);
  });

  assert.equal(api.hasMutationProof, false);
  assert.deepEqual(await api.login("synthetic-owner-credential"), principal);
  assert.equal(api.hasMutationProof, true);
  await api.createThread({
    title: "Private thread",
    sensitivity: "personal",
    retention_policy: "retention.owner-conversation",
  });

  assert.equal(calls[0].init.credentials, "same-origin");
  assert.equal(calls[0].init.cache, "no-store");
  assert.equal(calls[1].init.headers.get("X-Melloa-CSRF"), "csrf-proof");
  assert.equal(calls[1].init.credentials, "same-origin");
  assert.match(calls[1].init.body, /Private thread/);
});

test("mutations require a fresh in-memory proof before fetch", async () => {
  let called = false;
  const api = new MelloaApi(async () => {
    called = true;
    return jsonResponse({});
  });

  await assert.rejects(
    api.postMessage("thread_00000000000000000000000000000001", "hello", "browser:1"),
    (error) =>
      error instanceof ApiError &&
      error.status === 403 &&
      error.code === "recent_authentication_required",
  );
  assert.equal(called, false);
});

test("client surfaces structured API errors and clears stale mutation proof", async () => {
  let requests = 0;
  const api = new MelloaApi(async () => {
    requests += 1;
    if (requests === 1) {
      return jsonResponse({ principal, csrf_token: "csrf-proof" });
    }
    return jsonResponse(
      { code: "owner_authentication_failed", message: "Owner authentication failed." },
      401,
    );
  });
  await api.login("synthetic-owner-credential");
  await assert.rejects(
    api.currentSession(),
    (error) => error instanceof ApiError && error.code === "owner_authentication_failed",
  );
  assert.equal(api.hasMutationProof, false);
});

test("model activity uses encoded half-open window parameters", async () => {
  let requested = "";
  const api = new MelloaApi(async (input) => {
    requested = String(input);
    return jsonResponse({ entries: [] });
  });
  await api.modelActivity(
    new Date("2026-08-10T00:00:00Z"),
    new Date("2026-08-17T00:00:00Z"),
  );
  assert.match(requested, /^\/api\/v1\/inspection\/model-activity\?/);
  assert.match(requested, /from=2026-08-10T00%3A00%3A00.000Z/);
  assert.match(requested, /to=2026-08-17T00%3A00%3A00.000Z/);
});

test("health, media, and retention inspection use authenticated same-origin routes", async () => {
  const requested = [];
  const api = new MelloaApi(async (input) => {
    requested.push(String(input));
    return jsonResponse({ components: [], sources: [], items: [] });
  });
  await api.healthDetail();
  await api.mediaCatalog();
  await api.retentionReport();
  assert.deepEqual(requested, [
    "/api/v1/inspection/health",
    "/api/v1/inspection/media",
    "/api/v1/retention",
  ]);
});

test("conversation processing inspection and resume stay same-origin and CSRF-bound", async () => {
  const calls = [];
  const api = new MelloaApi(async (input, init) => {
    calls.push({ input: String(input), init });
    if (String(input) === "/api/v1/auth/session") {
      return jsonResponse({ principal, csrf_token: "csrf-proof" });
    }
    return jsonResponse({ attempts: [], resumptions: [] });
  });
  const threadId = "thread_00000000000000000000000000000001";
  const messageId = "message_00000000000000000000000000000001";
  await api.login("synthetic-owner-credential");
  await api.listProcessing(threadId);
  await api.inspectProcessing(threadId, messageId);
  await api.resumeMessage(threadId, messageId);

  assert.equal(calls[1].input, `/api/v1/conversations/${threadId}/processing`);
  assert.equal(
    calls[2].input,
    `/api/v1/conversations/${threadId}/messages/${messageId}/processing`,
  );
  assert.equal(calls[3].input, `/api/v1/conversations/${threadId}/messages/${messageId}/resume`);
  assert.equal(calls[3].init.method, "POST");
  assert.equal(calls[3].init.headers.get("X-Melloa-CSRF"), "csrf-proof");
});

test("delivery inspection, enqueue, and resume stay thread-scoped and CSRF-bound", async () => {
  const calls = [];
  const api = new MelloaApi(async (input, init) => {
    calls.push({ input: String(input), init });
    if (String(input) === "/api/v1/auth/session") {
      return jsonResponse({ principal, csrf_token: "csrf-proof" });
    }
    return jsonResponse([]);
  });
  const threadId = "thread_00000000000000000000000000000001";
  const messageId = "message_00000000000000000000000000000001";
  const workId = "deliverywork_00000000000000000000000000000001";
  await api.login("synthetic-owner-credential");
  await api.listDeliveries(threadId);
  await api.inspectDelivery(threadId, workId);
  await api.enqueueDelivery(threadId, {
    message_id: messageId,
    client_adapter: "client.fake",
    destination_ref: "synthetic:owner",
    idempotency_key: "owner-console-delivery:1",
  });
  await api.resumeDelivery(threadId, workId);

  const base = `/api/v1/conversations/${threadId}/deliveries`;
  assert.equal(calls[1].input, base);
  assert.equal(calls[2].input, `${base}/${workId}`);
  assert.equal(calls[3].input, base);
  assert.equal(calls[3].init.method, "POST");
  assert.equal(calls[3].init.headers.get("X-Melloa-CSRF"), "csrf-proof");
  assert.deepEqual(JSON.parse(calls[3].init.body), {
    message_id: messageId,
    client_adapter: "client.fake",
    destination_ref: "synthetic:owner",
    idempotency_key: "owner-console-delivery:1",
  });
  assert.equal(calls[4].input, `${base}/${workId}/resume`);
  assert.equal(calls[4].init.method, "POST");
  assert.equal(calls[4].init.headers.get("X-Melloa-CSRF"), "csrf-proof");
});

test("Telegram pairing reads stay private and mutations are encoded and CSRF-bound", async () => {
  const calls = [];
  const api = new MelloaApi(async (input, init) => {
    calls.push({ input: String(input), init });
    if (String(input) === "/api/v1/auth/session") {
      return jsonResponse({ principal, csrf_token: "csrf-proof" });
    }
    return jsonResponse([]);
  });
  const candidateId = "tgcandidate_00000000000000000000000000000001";
  const pairingId = "tgpairing_00000000000000000000000000000001";
  await api.login("synthetic-owner-credential");
  await api.listTelegramPairingCandidates();
  await api.inspectTelegramPairing();
  await api.confirmTelegramPairing(candidateId, "synthetic-confirmation-code");
  await api.revokeTelegramPairing(pairingId);

  const base = "/api/v1/integrations/telegram/pairing";
  assert.equal(calls[1].input, `${base}/candidates`);
  assert.equal(calls[2].input, base);
  assert.equal(calls[3].input, `${base}/candidates/${candidateId}/confirm`);
  assert.equal(calls[3].init.method, "POST");
  assert.equal(calls[3].init.headers.get("X-Melloa-CSRF"), "csrf-proof");
  assert.deepEqual(JSON.parse(calls[3].init.body), {
    confirmation_code: "synthetic-confirmation-code",
  });
  assert.equal(calls[4].input, `${base}/${pairingId}/revoke`);
  assert.equal(calls[4].init.method, "POST");
  assert.equal(calls[4].init.headers.get("X-Melloa-CSRF"), "csrf-proof");
});
