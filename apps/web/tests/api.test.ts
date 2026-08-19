import { describe, expect, it, vi } from "vitest";

import { MelloaApi, type AuthenticatedOwner } from "../src/api";

const principal: AuthenticatedOwner = {
  owner_id: "owner_1",
  session_id: "session_1",
  authentication_method: "local",
  authenticated_at: "2026-08-19T12:00:00Z",
  reauthenticated_until: "2026-08-19T12:05:00Z",
  expires_at: "2026-08-19T13:00:00Z",
};

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("MelloaApi", () => {
  it("keeps writing proof in memory and sends same-origin credentials", async () => {
    const calls: Array<{ readonly input: string; readonly init?: RequestInit }> = [];
    const api = new MelloaApi(async (input, init) => {
      calls.push({ input: String(input), init });
      if (String(input) === "/api/v1/auth/session") {
        return jsonResponse({ principal, csrf_token: "csrf-proof" });
      }
      return jsonResponse({ thread_id: "thread_1" }, 201);
    });

    expect(api.hasMutationProof).toBe(false);
    await api.login("owner-credential");
    await api.createThread({
      title: "Private conversation",
      sensitivity: "personal",
      retention_policy: "retention.owner-conversation",
    });

    expect(api.hasMutationProof).toBe(true);
    expect(calls[0]?.init?.credentials).toBe("same-origin");
    expect(calls[0]?.init?.cache).toBe("no-store");
    expect(new Headers(calls[1]?.init?.headers).get("X-Melloa-CSRF")).toBe("csrf-proof");
  });

  it("rejects writes locally when browser proof is absent", async () => {
    let called = false;
    const api = new MelloaApi(async () => {
      called = true;
      return jsonResponse({});
    });

    await expect(api.postMessage("thread_1", "hello", "browser:1")).rejects.toMatchObject({
      status: 403,
      code: "owner_access_required",
    });
    expect(called).toBe(false);
  });

  it("does not erase ordinary writing proof when only fresh confirmation expired", async () => {
    let requests = 0;
    const api = new MelloaApi(async () => {
      requests += 1;
      return requests === 1
        ? jsonResponse({ principal, csrf_token: "csrf-proof" })
        : jsonResponse({
          code: "recent_authentication_required",
          message: "Fresh owner confirmation is required.",
        }, 403);
    });

    await api.login("owner-credential");
    await expect(api.revokeOtherSessions()).rejects.toMatchObject({
      code: "recent_authentication_required",
    });
    expect(api.hasMutationProof).toBe(true);
  });

  it("clears stale proof on authentication or CSRF failure", async () => {
    let requests = 0;
    const api = new MelloaApi(async () => {
      requests += 1;
      return requests === 1
        ? jsonResponse({ principal, csrf_token: "csrf-proof" })
        : jsonResponse({ code: "csrf_validation_failed", message: "Invalid browser proof." }, 403);
    });

    const proofChanged = vi.fn();
    const unsubscribe = api.subscribeMutationProof(proofChanged);
    await api.login("owner-credential");
    await expect(api.postMessage("thread_1", "hello", "browser:1")).rejects.toMatchObject({
      code: "csrf_validation_failed",
    });
    expect(api.hasMutationProof).toBe(false);
    expect(proofChanged).toHaveBeenCalledTimes(2);
    unsubscribe();
  });

  it("uses the small owner-facing route set", async () => {
    const requested: string[] = [];
    const api = new MelloaApi(async (input) => {
      requested.push(String(input));
      return jsonResponse({ routes: [], coverage: [], sessions: [] });
    });

    await api.modelRoutes();
    await api.exportReadiness();
    await api.listThreads();

    expect(requested).toEqual([
      "/api/v1/model/status",
      "/api/v1/data-export",
      "/api/v1/conversations",
    ]);
  });

  it("downloads a CSRF-bound owner export with a bounded filename", async () => {
    let requests = 0;
    const api = new MelloaApi(async () => {
      requests += 1;
      if (requests === 1) {
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
  });

  it("rejects a successful response that is not an export archive", async () => {
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
});
