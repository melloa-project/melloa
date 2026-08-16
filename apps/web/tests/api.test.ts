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
    await api.modelActivity(new Date("2026-08-10T00:00:00Z"), new Date("2026-08-17T00:00:00Z"));

    expect(requested.slice(0, 4)).toEqual([
      "/api/v1/providers/routes",
      "/api/v1/inspection/health",
      "/api/v1/inspection/media",
      "/api/v1/retention",
    ]);
    expect(requested[4]).toContain("from=2026-08-10T00%3A00%3A00.000Z");
    expect(requested[4]).toContain("to=2026-08-17T00%3A00%3A00.000Z");
  });
});
