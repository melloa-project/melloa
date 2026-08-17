import { describe, expect, it } from "vitest";

import { canUseMutationProof, isLatestRequest } from "../src/app";
import type { AuthenticatedOwner } from "../src/api";

const principal: AuthenticatedOwner = {
  owner_id: "owner_00000000000000000000000000000001",
  session_id: "session_00000000000000000000000000000001",
  authentication_method: "auth.synthetic-opaque-token",
  authenticated_at: "2026-08-16T12:00:00Z",
  reauthenticated_until: "2026-08-16T12:05:00Z",
  expires_at: "2026-08-16T12:30:00Z",
};

describe("canUseMutationProof", () => {
  it("requires an in-memory mutation proof", () => {
    expect(canUseMutationProof(principal, false, Date.parse("2026-08-16T12:01:00Z"))).toBe(false);
  });

  it("expires when recent owner authentication lapses", () => {
    expect(canUseMutationProof(principal, true, Date.parse("2026-08-16T12:04:59Z"))).toBe(true);
    expect(canUseMutationProof(principal, true, Date.parse("2026-08-16T12:05:00Z"))).toBe(false);
  });

  it("fails closed on an invalid reauthentication timestamp", () => {
    expect(canUseMutationProof(
      { ...principal, reauthenticated_until: "not-a-timestamp" },
      true,
      Date.parse("2026-08-16T12:01:00Z"),
    )).toBe(false);
  });
});

describe("isLatestRequest", () => {
  it("accepts only the newest app-level refresh request", () => {
    expect(isLatestRequest(3, 3)).toBe(true);
    expect(isLatestRequest(2, 3)).toBe(false);
  });
});
