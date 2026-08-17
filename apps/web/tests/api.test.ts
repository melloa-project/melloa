import { describe, expect, it } from "vitest";

import { MelloaApi, type AuthenticatedOwner } from "../src/api";

const principal: AuthenticatedOwner = {
  owner_id: "owner_00000000000000000000000000000001",
  session_id: "session_00000000000000000000000000000001",
  authentication_method: "auth.synthetic-opaque-token",
  authenticated_at: "2026-08-16T12:00:00Z",
  reauthenticated_until: "2026-08-16T12:05:00Z",
  expires_at: "2026-08-16T12:30:00Z",
};

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("MelloaApi", () => {
  it("invokes fetch-compatible functions without an object receiver", async () => {
    let receiver: unknown = "not-called";
    const fetcher = function (this: unknown): Promise<Response> {
      receiver = this;
      return Promise.resolve(jsonResponse({ service: "melloa-core" }));
    };

    await new MelloaApi(fetcher).systemStatus();
    expect(receiver).toBeUndefined();
  });

  it("keeps mutation proof in memory and sends same-origin credentials", async () => {
    const calls: Array<{ readonly input: string; readonly init?: RequestInit }> = [];
    const api = new MelloaApi(async (input, init) => {
      calls.push({ input: String(input), init });
      if (String(input) === "/api/v1/auth/session") {
        return jsonResponse({ principal, csrf_token: "csrf-proof" });
      }
      return jsonResponse({ thread_id: "thread_01" }, 201);
    });

    expect(api.hasMutationProof).toBe(false);
    await expect(api.login("owner-credential")).resolves.toEqual(principal);
    expect(api.hasMutationProof).toBe(true);
    await api.createThread({
      title: "Private thread",
      sensitivity: "personal",
      retention_policy: "retention.owner-conversation",
    });

    expect(calls[0]?.init?.credentials).toBe("same-origin");
    expect(calls[0]?.init?.cache).toBe("no-store");
    expect(new Headers(calls[1]?.init?.headers).get("X-Melloa-CSRF")).toBe("csrf-proof");
    expect(calls[1]?.init?.body).toContain("Private thread");
  });

  it("lists active sessions and signs out others with mutation proof", async () => {
    const calls: Array<{ readonly input: string; readonly init?: RequestInit }> = [];
    const api = new MelloaApi(async (input, init) => {
      calls.push({ input: String(input), init });
      if (String(input) === "/api/v1/auth/session") {
        return jsonResponse({ principal, csrf_token: "csrf-proof" });
      }
      if (String(input) === "/api/v1/auth/sessions") {
        return jsonResponse({ current_session_id: principal.session_id, sessions: [principal] });
      }
      return jsonResponse({ revoked_count: 2 });
    });

    await api.login("owner-credential");
    await expect(api.activeSessions()).resolves.toEqual({
      current_session_id: principal.session_id,
      sessions: [principal],
    });
    await expect(api.revokeOtherSessions()).resolves.toEqual({ revoked_count: 2 });

    expect(calls[1]?.input).toBe("/api/v1/auth/sessions");
    expect(calls[1]?.init?.method).toBe("GET");
    expect(calls[2]?.input).toBe("/api/v1/auth/sessions/others");
    expect(calls[2]?.init?.method).toBe("DELETE");
    expect(new Headers(calls[2]?.init?.headers).get("X-Melloa-CSRF")).toBe("csrf-proof");
  });

  it("downloads a CSRF-bound owner export archive with a safe filename", async () => {
    const calls: Array<{ readonly input: string; readonly init?: RequestInit }> = [];
    const api = new MelloaApi(async (input, init) => {
      calls.push({ input: String(input), init });
      if (String(input) === "/api/v1/auth/session") {
        return jsonResponse({ principal, csrf_token: "csrf-proof" });
      }
      return new Response(new Uint8Array([80, 75, 3, 4]), {
        headers: {
          "Content-Type": "application/zip",
          "Content-Disposition": "attachment; filename=\"melloa-owner-export-export_01.zip\"",
        },
      });
    });

    await api.login("owner-credential");
    const archive = await api.downloadExportPreview();

    expect(archive.filename).toBe("melloa-owner-export-export_01.zip");
    expect(Array.from(new Uint8Array(await archive.blob.arrayBuffer()))).toEqual([80, 75, 3, 4]);
    expect(calls[1]?.input).toBe("/api/v1/exports/preview");
    expect(calls[1]?.init?.method).toBe("POST");
    const headers = new Headers(calls[1]?.init?.headers);
    expect(headers.get("Accept")).toBe("application/zip");
    expect(headers.get("X-Melloa-CSRF")).toBe("csrf-proof");
  });

  it("rejects a successful non-archive export response", async () => {
    let requests = 0;
    const api = new MelloaApi(async () => {
      requests += 1;
      return requests === 1
        ? jsonResponse({ principal, csrf_token: "csrf-proof" })
        : jsonResponse({ unexpected: true });
    });

    await api.login("owner-credential");
    await expect(api.downloadExportPreview()).rejects.toMatchObject({
      code: "invalid_export_response",
      status: 502,
    });
  });

  it("rejects mutations before making a request when proof is absent", async () => {
    let called = false;
    const api = new MelloaApi(async () => {
      called = true;
      return jsonResponse({});
    });

    await expect(api.postMessage("thread_01", "hello", "browser:1")).rejects.toMatchObject({
      status: 403,
      code: "recent_authentication_required",
    });
    await expect(api.deleteMemoryContent("assertion_01")).rejects.toMatchObject({
      status: 403,
      code: "recent_authentication_required",
    });
    await expect(api.revokeOtherSessions()).rejects.toMatchObject({
      status: 403,
      code: "recent_authentication_required",
    });
    await expect(api.downloadExportPreview()).rejects.toMatchObject({
      status: 403,
      code: "recent_authentication_required",
    });
    expect(called).toBe(false);
  });

  it("surfaces structured errors and clears stale proof on authentication failure", async () => {
    let requests = 0;
    const api = new MelloaApi(async () => {
      requests += 1;
      return requests === 1
        ? jsonResponse({ principal, csrf_token: "csrf-proof" })
        : jsonResponse({ code: "owner_authentication_failed", message: "Owner authentication failed." }, 401);
    });

    await api.login("owner-credential");
    await expect(api.currentSession()).rejects.toMatchObject({
      code: "owner_authentication_failed",
      status: 401,
    });
    expect(api.hasMutationProof).toBe(false);
  });

  it("uses explicit inspection routes and encoded activity windows", async () => {
    const requested: string[] = [];
    const api = new MelloaApi(async (input) => {
      requested.push(String(input));
      return jsonResponse({ entries: [], routes: [], components: [], sources: [], items: [] });
    });

    await api.modelRoutes();
    await api.healthDetail();
    await api.mediaCatalog();
    await api.retentionReport();
    await api.exportReadiness();
    await api.modelActivity(new Date("2026-08-10T00:00:00Z"), new Date("2026-08-17T00:00:00Z"));

    expect(requested.slice(0, 5)).toEqual([
      "/api/v1/providers/routes",
      "/api/v1/inspection/health",
      "/api/v1/inspection/media",
      "/api/v1/retention",
      "/api/v1/inspection/export",
    ]);
    expect(requested[5]).toContain("from=2026-08-10T00%3A00%3A00.000Z");
    expect(requested[5]).toContain("to=2026-08-17T00%3A00%3A00.000Z");
  });

  it("deletes assertion content through a CSRF-bound memory route", async () => {
    const calls: Array<{ readonly input: string; readonly init?: RequestInit }> = [];
    const api = new MelloaApi(async (input, init) => {
      calls.push({ input: String(input), init });
      if (String(input) === "/api/v1/auth/session") {
        return jsonResponse({ principal, csrf_token: "csrf-proof" });
      }
      return jsonResponse({ created: true });
    });

    await api.login("owner-credential");
    await api.deleteMemoryContent("assertion/needs encoding");

    expect(calls[1]?.input).toBe("/api/v1/memory/assertion%2Fneeds%20encoding/content");
    expect(calls[1]?.init?.method).toBe("DELETE");
    expect(new Headers(calls[1]?.init?.headers).get("X-Melloa-CSRF")).toBe("csrf-proof");
  });
});
