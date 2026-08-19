import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SettingsPage } from "../src/pages/settings";

const mocks = vi.hoisted(() => ({
  context: {} as Record<string, unknown>,
  unlock: vi.fn(),
  activeSessions: vi.fn(),
  exportReadiness: vi.fn(),
  downloadExportPreview: vi.fn(),
  revokeOtherSessions: vi.fn(),
  logout: vi.fn(),
  notify: vi.fn(),
}));

vi.mock("../src/app", () => ({
  errorMessage: (error: unknown) => error instanceof Error ? error.message : "Unexpected error",
  useMelloa: () => mocks.context,
}));

vi.mock("../src/components/layout", () => ({
  useOwnerUnlock: () => mocks.unlock,
}));

const principal = {
  owner_id: "owner_1",
  session_id: "session_current",
  authentication_method: "local",
  authenticated_at: "2026-08-19T12:00:00Z",
  reauthenticated_until: "2026-08-19T12:05:00Z",
  expires_at: "2026-08-19T13:00:00Z",
};

const otherSession = {
  ...principal,
  session_id: "session_other",
  authenticated_at: "2026-08-19T11:00:00Z",
};

describe("SettingsPage", () => {
  beforeEach(() => {
    for (const mock of Object.values(mocks)) {
      if (typeof mock === "function" && "mockReset" in mock) {
        (mock as ReturnType<typeof vi.fn>).mockReset();
      }
    }
    mocks.activeSessions.mockResolvedValue({
      current_session_id: principal.session_id,
      sessions: [principal, otherSession],
    });
    mocks.exportReadiness.mockResolvedValue({
      encrypted: false,
      coverage: [
        { group: "conversation-history", label: "Active conversations", included: true },
        { group: "answer-provenance", label: "Answer provenance", included: true },
        { group: "memory-history", label: "Memory history", included: true },
        {
          group: "conversation-deletion-receipts",
          label: "Conversation deletion receipts",
          included: false,
        },
        {
          group: "account-and-security-history",
          label: "Account and browser history",
          included: false,
        },
        {
          group: "system-events-and-audit-history",
          label: "System event and audit history",
          included: false,
        },
      ],
      validation_checks: [],
      limitations: [
        "The browser archive is not encrypted.",
        "Backups remain separate from this copy.",
      ],
    });
    mocks.revokeOtherSessions.mockResolvedValue({ revoked_count: 1 });
    mocks.context = {
      api: {
        activeSessions: mocks.activeSessions,
        exportReadiness: mocks.exportReadiness,
        downloadExportPreview: mocks.downloadExportPreview,
        revokeOtherSessions: mocks.revokeOtherSessions,
      },
      principal,
      status: {
        access_scope: "loopback",
        public_ingress: false,
        external_actions_enabled: false,
        guardian: { mode: "offline" },
      },
      canWrite: true,
      canUseSensitiveControls: true,
      logout: mocks.logout,
      notify: mocks.notify,
    };
  });

  it("keeps data ownership and independent protection without runtime administration", async () => {
    render(<MemoryRouter><SettingsPage /></MemoryRouter>);

    expect(await screen.findByRole("heading", { name: "Data & safety" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "Your data" })).toBeVisible();
    expect(screen.getByText("3")).toBeVisible();
    expect(screen.getByText("Not encrypted")).toBeVisible();
    fireEvent.click(screen.getByText("What this copy includes"));
    expect(screen.getByText("Active conversations · Answer provenance · Memory history")).toBeVisible();
    expect(screen.getByText(/Conversation deletion receipts/)).toBeVisible();
    expect(screen.getByText("Backups remain separate from this copy.")).toBeVisible();
    expect(screen.getByRole("heading", { name: "Independent protection" })).toBeVisible();
    expect(screen.getByText("Offline")).toBeVisible();
    expect(screen.queryByText(/Telegram/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/provider/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/session_current/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/signed sequence/i)).not.toBeInTheDocument();
  });

  it("reserves fresh confirmation for exporting private history", async () => {
    mocks.context = { ...mocks.context, canUseSensitiveControls: false };
    render(<MemoryRouter><SettingsPage /></MemoryRouter>);

    fireEvent.click(await screen.findByRole("button", { name: /Download portability copy/ }));
    expect(mocks.unlock).toHaveBeenCalledWith(expect.stringMatching(/private history/i));
    expect(mocks.downloadExportPreview).not.toHaveBeenCalled();
    expect(screen.getByText(/Ordinary conversation remains available/i)).toBeVisible();
  });

  it("can sign out other browsers without exposing their internal IDs", async () => {
    render(<MemoryRouter><SettingsPage /></MemoryRouter>);

    fireEvent.click(await screen.findByRole("button", { name: "Sign out other browsers" }));
    await waitFor(() => expect(mocks.revokeOtherSessions).toHaveBeenCalledOnce());
    expect(mocks.notify).toHaveBeenCalledWith("1 other browser signed out.", "success");
    expect(screen.queryByText("session_other")).not.toBeInTheDocument();
  });
});
