import { render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import { AppLayout } from "../src/components/layout";

const mocks = vi.hoisted(() => ({
  context: {
    api: {},
    principal: {
      owner_id: "owner_00000000000000000000000000000001",
      session_id: "session_00000000000000000000000000000001",
      authentication_method: "auth.synthetic-opaque-token",
      authenticated_at: "2026-08-16T12:00:00Z",
      reauthenticated_until: "2026-08-16T12:05:00Z",
      expires_at: "2026-08-16T12:30:00Z",
    },
    status: {
      service: "melloa-core",
      guardian: { mode: "normal" },
      external_actions_enabled: false,
    },
    canMutate: true,
    notices: [],
    login: vi.fn(),
    logout: vi.fn(),
    refreshStatus: vi.fn(),
    notify: vi.fn(),
    dismissNotice: vi.fn(),
  },
}));

vi.mock("../src/app", () => ({
  errorMessage: (error: unknown) => error instanceof Error ? error.message : "Unexpected error",
  useMelloa: () => mocks.context,
}));

describe("AppLayout", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-08-16T12:00:00Z"));
    mocks.context.canMutate = true;
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("shows recent owner authentication timing in the persistent owner chip", () => {
    render(
      <MemoryRouter initialEntries={["/conversation"]}>
        <Routes>
          <Route element={<AppLayout />}>
            <Route path="/conversation" element={<div>Conversation body</div>} />
          </Route>
        </Routes>
      </MemoryRouter>,
    );

    const ownerChip = screen.getByRole("button", {
      name: /owner session: changes unlocked; recent authentication in 5 minutes; session expires in 30 minutes/i,
    });
    expect(within(ownerChip).getByText("Recent auth in 5 minutes")).toBeInTheDocument();
    expect(within(ownerChip).getByText("Unlocked")).toBeInTheDocument();
    expect(ownerChip).toHaveAttribute("title", `Owner ${mocks.context.principal.owner_id}`);
    expect(screen.getByText("Recent authentication in 5 minutes. Session expires in 30 minutes.")).toBeInTheDocument();
  });

  it("keeps the owner chip explanatory when the session is read-only", () => {
    mocks.context.canMutate = false;
    vi.setSystemTime(new Date("2026-08-16T12:06:00Z"));

    render(
      <MemoryRouter initialEntries={["/settings"]}>
        <Routes>
          <Route element={<AppLayout />}>
            <Route path="/settings" element={<div>Settings body</div>} />
          </Route>
        </Routes>
      </MemoryRouter>,
    );

    const ownerChip = screen.getByRole("button", {
      name: /owner session: read only; recent authentication 1 minute ago; session expires in 24 minutes/i,
    });
    expect(within(ownerChip).getByText("Recent auth 1 minute ago")).toBeInTheDocument();
    expect(within(ownerChip).getByText("Read only")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /unlock changes/i })).toBeInTheDocument();
  });
});
