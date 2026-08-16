import assert from "node:assert/strict";
import test from "node:test";

import {
  defaultActivityWindow,
  deliveryRecoverySummary,
  hasRecentAuthentication,
  messageBody,
  mutationCapabilities,
  parseActivityWindow,
  parseJsonObject,
  writeText,
} from "../.test-dist/view.js";

const principal = {
  owner_id: "owner_00000000000000000000000000000001",
  session_id: "session_00000000000000000000000000000001",
  authentication_method: "auth.synthetic-opaque-token",
  authenticated_at: "2026-08-16T12:00:00Z",
  reauthenticated_until: "2026-08-16T12:05:00Z",
  expires_at: "2026-08-16T12:30:00Z",
};

test("hostile API text is assigned literally to textContent", () => {
  const target = { textContent: null };
  const hostile = '<img src=x onerror="globalThis.compromised=true">';
  writeText(target, hostile);
  assert.equal(target.textContent, hostile);
  assert.equal(globalThis.compromised, undefined);
});

test("message body preserves text without creating markup", () => {
  const message = {
    parts: [
      { kind: "text", text: "<script>not executable</script>" },
      { kind: "attachment", media_type: "image/png", attachment_id: "attachment_1" },
    ],
  };
  assert.equal(
    messageBody(message),
    "<script>not executable</script>\n[Attachment: image/png · attachment_1]",
  );
});

test("correction parser accepts objects and rejects non-object JSON", () => {
  assert.deepEqual(parseJsonObject('{"fact":"corrected"}'), { fact: "corrected" });
  assert.throws(() => parseJsonObject("[1, 2]"), /JSON object/);
  assert.throws(() => parseJsonObject("null"), /JSON object/);
  assert.throws(() => parseJsonObject("not-json"), SyntaxError);
});

test("recent authentication expires at the declared boundary", () => {
  assert.equal(hasRecentAuthentication(principal, Date.parse("2026-08-16T12:04:59Z")), true);
  assert.equal(hasRecentAuthentication(principal, Date.parse("2026-08-16T12:05:00Z")), false);
  assert.equal(hasRecentAuthentication(null), false);
});

test("ordinary CSRF mutations outlive the stricter memory mutation window", () => {
  assert.deepEqual(
    mutationCapabilities(principal, true, Date.parse("2026-08-16T12:10:00Z")),
    { standard: true, sensitive: false },
  );
  assert.deepEqual(
    mutationCapabilities(principal, false, Date.parse("2026-08-16T12:01:00Z")),
    { standard: false, sensitive: false },
  );
});

test("activity windows are deterministic, UTC, and half-open", () => {
  assert.deepEqual(defaultActivityWindow(new Date("2026-08-16T23:59:59Z")), {
    from: "2026-08-10",
    to: "2026-08-17",
  });
  const window = parseActivityWindow("2026-08-10", "2026-08-17");
  assert.equal(window.start.toISOString(), "2026-08-10T00:00:00.000Z");
  assert.equal(window.end.toISOString(), "2026-08-17T00:00:00.000Z");
  assert.throws(() => parseActivityWindow("2026-08-17", "2026-08-17"), /must be after/);
});

test("delivery recovery summaries project only canonical status and redacted errors", () => {
  const base = {
    state: "ready",
    attempt_count: 1,
    max_attempts: 3,
    available_at: "2026-08-16T12:01:00Z",
    lease_expires_at: null,
    completed_at: null,
    last_error_code: "channel.synthetic_unavailable",
    resumptions: [],
  };
  assert.deepEqual(deliveryRecoverySummary(base), {
    label: "Retry scheduled",
    detail:
      "Attempt budget 1/3; next eligible 2026-08-16 12:01:00 UTC. No owner resumptions recorded.",
    tone: "ready",
    canResume: false,
  });

  const dead = deliveryRecoverySummary({ ...base, state: "dead", attempt_count: 3 });
  assert.equal(dead.label, "Owner action required");
  assert.match(dead.detail, /Last redacted error: channel\.synthetic_unavailable/);
  assert.equal(dead.canResume, true);

  const completed = deliveryRecoverySummary({
    ...base,
    state: "completed",
    attempt_count: 4,
    max_attempts: 6,
    completed_at: "2026-08-16T12:03:00Z",
    last_error_code: null,
    resumptions: [{ resumption_id: "deliveryresume_1" }],
  });
  assert.equal(completed.label, "Completed");
  assert.match(completed.detail, /1 owner resumption recorded/);
  assert.equal(completed.canResume, false);
});
