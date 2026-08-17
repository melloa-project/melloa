import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SettingsPage } from "../src/pages/settings";

const mocks = vi.hoisted(() => ({
  activeSessions: vi.fn(),
  revokeOtherSessions: vi.fn(),
  inspectTelegramPairing: vi.fn(),
  inspectTelegramStatus: vi.fn(),
  listTelegramPairingCandidates: vi.fn(),
  confirmTelegramPairing: vi.fn(),
  revokeTelegramPairing: vi.fn(),
  notify: vi.fn(),
  canMutate: true,
}));

vi.mock("../src/app", () => ({
  errorMessage: (error: unknown) => error instanceof Error ? error.message : "Unexpected error",
  useMelloa: () => ({
    api: {
      activeSessions: mocks.activeSessions,
      revokeOtherSessions: mocks.revokeOtherSessions,
      inspectTelegramPairing: mocks.inspectTelegramPairing,
      inspectTelegramStatus: mocks.inspectTelegramStatus,
      listTelegramPairingCandidates: mocks.listTelegramPairingCandidates,
      confirmTelegramPairing: mocks.confirmTelegramPairing,
      revokeTelegramPairing: mocks.revokeTelegramPairing,
    },
    principal: {
      owner_id: "owner_01",
      session_id: "session_01",
      authentication_method: "auth.local",
      authenticated_at: "2026-08-16T12:00:00Z",
      reauthenticated_until: "2026-08-16T12:05:00Z",
      expires_at: "2026-08-16T12:30:00Z",
    },
    status: {
      guardian: {
        mode: "normal",
        sequence: 3,
        key_id: "guardian.status-v1",
        changed_at: "2026-08-16T12:00:00Z",
      },
      external_actions_enabled: true,
      public_ingress: false,
    },
    canMutate: mocks.canMutate,
    notify: mocks.notify,
  }),
}));

describe("SettingsPage Telegram inspection", () => {
  beforeEach(() => {
    for (const mock of [
      mocks.activeSessions,
      mocks.revokeOtherSessions,
      mocks.inspectTelegramPairing,
      mocks.inspectTelegramStatus,
      mocks.listTelegramPairingCandidates,
      mocks.confirmTelegramPairing,
      mocks.revokeTelegramPairing,
      mocks.notify,
    ]) {
      mock.mockReset();
    }
    mocks.canMutate = true;
    mocks.inspectTelegramStatus.mockResolvedValue({
      configured: true,
      adapter_id: "client.telegram.bot-api",
      state_persistence: "postgresql",
      polling: {
        state: "healthy",
        reason_code: "telegram.worker.ready",
        next_offset: 12,
        poll_revision: 2,
        updates_handled: 2,
        source: { status: "healthy", transport: "telegram-bot-api", network: true },
      },
      replies: {
        state: "healthy",
        reason_code: "telegram.reply.ready",
        pending_replies: 0,
        deliveries_submitted: 1,
      },
      delivery: { status: "healthy", transport: "telegram-bot-api", network: true },
      capabilities: {
        transport: "telegram-bot-api",
        network: true,
        text: true,
        attachments: false,
        max_text_length: 4096,
        ambiguous_send_retries: false,
      },
      limitations: ["attachments rejected before fetch"],
    });
    mocks.inspectTelegramPairing.mockResolvedValue(null);
    mocks.activeSessions.mockResolvedValue({
      current_session_id: "session_01",
      sessions: [
        {
          owner_id: "owner_01",
          session_id: "session_01",
          authentication_method: "auth.local",
          authenticated_at: "2026-08-16T12:00:00Z",
          reauthenticated_until: "2026-08-16T12:05:00Z",
          expires_at: "2026-08-16T12:30:00Z",
        },
        {
          owner_id: "owner_01",
          session_id: "session_02",
          authentication_method: "auth.local",
          authenticated_at: "2026-08-16T12:01:00Z",
          reauthenticated_until: "2026-08-16T12:06:00Z",
          expires_at: "2026-08-16T12:31:00Z",
        },
      ],
    });
    mocks.revokeOtherSessions.mockResolvedValue({ revoked_count: 1 });
    mocks.listTelegramPairingCandidates.mockResolvedValue([
      {
        candidate_id: "tgcandidate_01",
        update_id: 11,
        telegram_user_id: 123456789,
        telegram_chat_id: 123456789,
        observed_at: "2026-08-16T12:00:00Z",
        expires_at: "2026-08-16T12:10:00Z",
      },
    ]);
  });

  it("shows real channel health and accepts the secure pairing-code shape", async () => {
    render(<SettingsPage />);

    expect(await screen.findByText(/Bot API · Healthy/i)).toBeInTheDocument();
    expect(screen.getByText("Real Telegram Bot API")).toBeInTheDocument();
    expect(screen.getByText("Rejected before fetch")).toBeInTheDocument();
    expect(screen.getByText("PostgreSQL restart-safe")).toBeInTheDocument();
    expect(screen.getByText("Ambiguous sends do not retry")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Confirm/i }));
    const input = screen.getByLabelText("Confirmation code");
    expect(input).toHaveAttribute("minlength", "20");
    expect(input).toHaveAttribute("maxlength", "128");
    expect(input).toHaveAttribute("pattern", "[A-Za-z0-9_-]{20,128}");
  });

  it("inspects active sessions and confirms signing out other browsers", async () => {
    let revoked = false;
    mocks.activeSessions.mockImplementation(() => Promise.resolve(
      revoked
        ? {
            current_session_id: "session_01",
            sessions: [
              {
                owner_id: "owner_01",
                session_id: "session_01",
                authentication_method: "auth.local",
                authenticated_at: "2026-08-16T12:00:00Z",
                reauthenticated_until: "2026-08-16T12:05:00Z",
                expires_at: "2026-08-16T12:30:00Z",
              },
            ],
          }
        : {
        current_session_id: "session_01",
        sessions: [
          {
            owner_id: "owner_01",
            session_id: "session_01",
            authentication_method: "auth.local",
            authenticated_at: "2026-08-16T12:00:00Z",
            reauthenticated_until: "2026-08-16T12:05:00Z",
            expires_at: "2026-08-16T12:30:00Z",
          },
          {
            owner_id: "owner_01",
            session_id: "session_02",
            authentication_method: "auth.local",
            authenticated_at: "2026-08-16T12:01:00Z",
            reauthenticated_until: "2026-08-16T12:06:00Z",
            expires_at: "2026-08-16T12:31:00Z",
          },
        ],
      },
    ));
    mocks.revokeOtherSessions.mockImplementation(() => {
      revoked = true;
      return Promise.resolve({ revoked_count: 1 });
    });
    render(<SettingsPage />);

    expect(await screen.findByText("This browser")).toBeInTheDocument();
    expect(screen.getByText(/^Other browser · /i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Sign out other sessions" }));
    expect(screen.getByRole("heading", { name: "Sign out 1 other session?" })).toBeInTheDocument();
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Sign out other sessions" }));

    await waitFor(() => expect(mocks.revokeOtherSessions).toHaveBeenCalledOnce());
    expect(mocks.notify).toHaveBeenCalledWith("1 other session signed out.", "success");
    await waitFor(() => expect(screen.queryByText(/^Other browser · /i)).not.toBeInTheDocument());
  });

  it("disables modal mutations when recent owner authentication lapses", async () => {
    const rendered = render(<SettingsPage />);

    expect(await screen.findByText(/Bot API · Healthy/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Confirm/i }));
    expect(screen.getByRole("heading", { name: "Confirm Telegram owner" })).toBeInTheDocument();

    mocks.canMutate = false;
    rendered.rerender(<SettingsPage />);

    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByRole("button", { name: "Confirm pairing" })).toBeDisabled();
    fireEvent.submit(within(dialog).getByLabelText("Confirmation code").closest("form") as HTMLFormElement);

    expect(mocks.confirmTelegramPairing).not.toHaveBeenCalled();
    expect(mocks.notify).toHaveBeenCalledWith(
      "Unlock owner changes before confirming Telegram pairing.",
      "error",
    );
  });

  it("keeps session revocation disabled when recent owner authentication lapses", async () => {
    const rendered = render(<SettingsPage />);

    expect(await screen.findByText("This browser")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Sign out other sessions" }));
    expect(screen.getByRole("heading", { name: "Sign out 1 other session?" })).toBeInTheDocument();

    mocks.canMutate = false;
    rendered.rerender(<SettingsPage />);

    const dialog = screen.getByRole("dialog");
    const revokeButton = within(dialog).getByRole("button", { name: "Sign out other sessions" });
    expect(revokeButton).toBeDisabled();
    fireEvent.click(revokeButton);

    expect(mocks.revokeOtherSessions).not.toHaveBeenCalled();
  });

  it("keeps Telegram revocation disabled when recent owner authentication lapses", async () => {
    mocks.inspectTelegramPairing.mockResolvedValue({
      contract_version: "1.0.0",
      pairing_id: "tgpairing_01",
      candidate_id: "tgcandidate_01",
      owner_id: "owner_01",
      telegram_user_id: 123456789,
      telegram_chat_id: 123456789,
      confirmed_by_owner_id: "owner_01",
      confirmed_at: "2026-08-16T12:02:00Z",
      revoked_at: null,
    });
    mocks.listTelegramPairingCandidates.mockResolvedValue([]);
    const rendered = render(<SettingsPage />);

    expect(await screen.findByText("Paired")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Revoke pairing" }));
    expect(screen.getByRole("heading", { name: "Revoke Telegram pairing?" })).toBeInTheDocument();

    mocks.canMutate = false;
    rendered.rerender(<SettingsPage />);

    const dialog = screen.getByRole("dialog");
    const revokeButton = within(dialog).getByRole("button", { name: "Revoke pairing" });
    expect(revokeButton).toBeDisabled();
    fireEvent.click(revokeButton);

    expect(mocks.revokeTelegramPairing).not.toHaveBeenCalled();
  });
});
