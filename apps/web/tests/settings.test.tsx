import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { OwnerSessionInventory, TelegramChannelStatus } from "../src/api";
import { SettingsPage } from "../src/pages/settings";

type ApiMock = {
  readonly activeSessions: ReturnType<typeof vi.fn>;
  readonly revokeOtherSessions: ReturnType<typeof vi.fn>;
  readonly inspectTelegramPairing: ReturnType<typeof vi.fn>;
  readonly inspectTelegramStatus: ReturnType<typeof vi.fn>;
  readonly listTelegramPairingCandidates: ReturnType<typeof vi.fn>;
  readonly confirmTelegramPairing: ReturnType<typeof vi.fn>;
  readonly revokeTelegramPairing: ReturnType<typeof vi.fn>;
};

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
  apiOverride: null as ApiMock | null,
}));

vi.mock("../src/app", () => {
  const stableApi = {
    activeSessions: mocks.activeSessions,
    revokeOtherSessions: mocks.revokeOtherSessions,
    inspectTelegramPairing: mocks.inspectTelegramPairing,
    inspectTelegramStatus: mocks.inspectTelegramStatus,
    listTelegramPairingCandidates: mocks.listTelegramPairingCandidates,
    confirmTelegramPairing: mocks.confirmTelegramPairing,
    revokeTelegramPairing: mocks.revokeTelegramPairing,
  };
  const context = {
    api: stableApi,
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
    notify: mocks.notify,
  };
  return {
    errorMessage: (error: unknown) => error instanceof Error ? error.message : "Unexpected error",
    useMelloa: () => ({
      ...context,
      api: mocks.apiOverride ?? stableApi,
      canMutate: mocks.canMutate,
    }),
  };
});

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
    mocks.apiOverride = null;
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
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: {
        writeText: vi.fn().mockResolvedValue(undefined),
      },
    });
  });

  it("shows real channel health and accepts the secure pairing-code shape", async () => {
    render(<SettingsPage />);

    expect(await screen.findByText(/Bot API · Healthy/i)).toBeInTheDocument();
    expect(screen.getByText("Real Telegram Bot API")).toBeInTheDocument();
    expect(screen.getByText("Rejected before fetch")).toBeInTheDocument();
    expect(screen.getByText("PostgreSQL restart-safe")).toBeInTheDocument();
    expect(screen.getByText("Ambiguous sends do not retry")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Copy Telegram adapter ID client.telegram.bot-api" }));
    await waitFor(() => expect(navigator.clipboard.writeText).toHaveBeenCalledWith("client.telegram.bot-api"));
    expect(mocks.notify).toHaveBeenCalledWith("Telegram adapter ID copied.", "success");
    fireEvent.click(screen.getByRole("button", { name: "Copy Telegram candidate ID tgcandidate_01" }));
    await waitFor(() => expect(navigator.clipboard.writeText).toHaveBeenCalledWith("tgcandidate_01"));
    expect(mocks.notify).toHaveBeenCalledWith("Telegram candidate ID copied.", "success");

    fireEvent.click(screen.getByRole("button", { name: /Confirm/i }));
    const input = screen.getByLabelText("Confirmation code");
    expect(input).toHaveAttribute("minlength", "20");
    expect(input).toHaveAttribute("maxlength", "128");
    expect(input).toHaveAttribute("pattern", "[A-Za-z0-9_-]{20,128}");
  });

  it("does not show real Bot API pairing instructions for the synthetic fixture", async () => {
    mocks.inspectTelegramStatus.mockResolvedValue(telegramStatus("disabled", false));
    mocks.listTelegramPairingCandidates.mockResolvedValue([]);

    render(<SettingsPage />);

    expect(await screen.findByText(/Synthetic fixture · Disabled/i)).toBeInTheDocument();
    expect(screen.getByText("Bot API pairing inactive")).toBeInTheDocument();
    expect(screen.getByText("Synthetic no-network mode cannot receive /start updates.")).toBeInTheDocument();
    expect(screen.getByText("Enable Bot API before pairing.")).toBeInTheDocument();
    expect(screen.queryByText(/send \/start to the configured bot/i)).not.toBeInTheDocument();
  });

  it("reports when Telegram authority id copy is unavailable", async () => {
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: undefined,
    });

    render(<SettingsPage />);

    expect(await screen.findByText(/Bot API · Healthy/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Copy Telegram adapter ID client.telegram.bot-api" }));

    await waitFor(() => expect(mocks.notify).toHaveBeenCalledWith("Telegram adapter ID copy failed.", "error"));
  });

  it("copies exact owner session and Guardian authority ids", async () => {
    render(<SettingsPage />);

    expect(await screen.findByText(/Bot API · Healthy/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Copy Owner ID owner_01" }));
    await waitFor(() => expect(navigator.clipboard.writeText).toHaveBeenCalledWith("owner_01"));
    expect(mocks.notify).toHaveBeenCalledWith("Owner ID copied.", "success");

    fireEvent.click(screen.getByRole("button", { name: "Copy Session ID session_01" }));
    await waitFor(() => expect(navigator.clipboard.writeText).toHaveBeenCalledWith("session_01"));
    expect(mocks.notify).toHaveBeenCalledWith("Session ID copied.", "success");

    fireEvent.click(screen.getByRole("button", { name: "Copy Current session ID session_01" }));
    await waitFor(() => expect(navigator.clipboard.writeText).toHaveBeenCalledWith("session_01"));
    expect(mocks.notify).toHaveBeenCalledWith("Current session ID copied.", "success");

    fireEvent.click(screen.getByRole("button", { name: "Copy Other session ID session_02" }));
    await waitFor(() => expect(navigator.clipboard.writeText).toHaveBeenCalledWith("session_02"));
    expect(mocks.notify).toHaveBeenCalledWith("Other session ID copied.", "success");

    fireEvent.click(screen.getByRole("button", { name: "Copy Guardian key ID guardian.status-v1" }));
    await waitFor(() => expect(navigator.clipboard.writeText).toHaveBeenCalledWith("guardian.status-v1"));
    expect(mocks.notify).toHaveBeenCalledWith("Guardian key ID copied.", "success");
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
    fireEvent.click(screen.getByRole("button", { name: "Copy Telegram pairing ID tgpairing_01" }));
    await waitFor(() => expect(navigator.clipboard.writeText).toHaveBeenCalledWith("tgpairing_01"));
    fireEvent.click(screen.getByRole("button", { name: "Copy Telegram candidate ID tgcandidate_01" }));
    await waitFor(() => expect(navigator.clipboard.writeText).toHaveBeenCalledWith("tgcandidate_01"));
    fireEvent.click(screen.getByRole("button", { name: "Copy Telegram owner ID owner_01" }));
    await waitFor(() => expect(navigator.clipboard.writeText).toHaveBeenCalledWith("owner_01"));
    expect(mocks.notify).toHaveBeenCalledWith("Telegram owner ID copied.", "success");
    fireEvent.click(screen.getByRole("button", { name: "Copy Telegram confirmed-by owner ID owner_01" }));
    await waitFor(() => expect(navigator.clipboard.writeText).toHaveBeenCalledWith("owner_01"));
    expect(mocks.notify).toHaveBeenCalledWith("Telegram confirmed-by owner ID copied.", "success");
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

  it("keeps the latest session refresh when an older request resolves last", async () => {
    const stale = deferred<OwnerSessionInventory>();
    mocks.activeSessions.mockReset();
    mocks.activeSessions
      .mockResolvedValueOnce(sessionInventory(["session_02"]))
      .mockReturnValueOnce(stale.promise);

    const rendered = render(<SettingsPage />);

    expect(await screen.findByText("This browser")).toBeInTheDocument();
    expect(screen.getByText(/^Other browser · /i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Refresh sessions" }));
    mocks.apiOverride = settingsApi(vi.fn().mockResolvedValue(sessionInventory([])));
    rendered.rerender(<SettingsPage />);

    await waitFor(() => expect(screen.queryByText(/^Other browser · /i)).not.toBeInTheDocument());

    await act(async () => {
      stale.resolve(sessionInventory(["session_stale_000000000000000000000001"]));
      await stale.promise;
    });

    await waitFor(() => {
      expect(screen.queryByText(/^Other browser · /i)).not.toBeInTheDocument();
    });
    expect(screen.queryByText(/session_st…000001/i)).not.toBeInTheDocument();
  });

  it("keeps the latest Telegram inspection refresh when an older request resolves last", async () => {
    const staleStatus = deferred<TelegramChannelStatus>();
    mocks.inspectTelegramStatus.mockReset();
    mocks.inspectTelegramPairing.mockReset();
    mocks.listTelegramPairingCandidates.mockReset();
    mocks.inspectTelegramStatus
      .mockResolvedValueOnce(telegramStatus("healthy", true))
      .mockReturnValueOnce(staleStatus.promise)
      .mockResolvedValueOnce(telegramStatus("disabled", false));
    mocks.inspectTelegramPairing.mockResolvedValue(null);
    mocks.listTelegramPairingCandidates.mockResolvedValue([]);

    render(<SettingsPage />);

    expect(await screen.findByText(/Bot API · Healthy/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));

    expect(await screen.findByText(/Synthetic fixture · Disabled/i)).toBeInTheDocument();

    await act(async () => {
      staleStatus.resolve(telegramStatus("healthy", true));
      await staleStatus.promise;
    });

    expect(screen.getByText(/Synthetic fixture · Disabled/i)).toBeInTheDocument();
    expect(screen.queryByText(/Bot API · Healthy/i)).not.toBeInTheDocument();
  });
});

type Deferred<T> = {
  readonly promise: Promise<T>;
  readonly reject: (reason?: unknown) => void;
  readonly resolve: (value: T) => void;
};

function deferred<T>(): Deferred<T> {
  let reject!: (reason?: unknown) => void;
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((promiseResolve, promiseReject) => {
    resolve = promiseResolve;
    reject = promiseReject;
  });
  return { promise, reject, resolve };
}

function sessionInventory(otherSessionIds: readonly string[]): OwnerSessionInventory {
  return {
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
      ...otherSessionIds.map((sessionId, index) => ({
        owner_id: "owner_01",
        session_id: sessionId,
        authentication_method: "auth.local",
        authenticated_at: `2026-08-16T12:0${index + 1}:00Z`,
        reauthenticated_until: `2026-08-16T12:0${index + 6}:00Z`,
        expires_at: `2026-08-16T12:3${index + 1}:00Z`,
      })),
    ],
  };
}

function settingsApi(activeSessions: ReturnType<typeof vi.fn>): ApiMock {
  return {
    activeSessions,
    revokeOtherSessions: mocks.revokeOtherSessions,
    inspectTelegramPairing: mocks.inspectTelegramPairing,
    inspectTelegramStatus: mocks.inspectTelegramStatus,
    listTelegramPairingCandidates: mocks.listTelegramPairingCandidates,
    confirmTelegramPairing: mocks.confirmTelegramPairing,
    revokeTelegramPairing: mocks.revokeTelegramPairing,
  };
}

function telegramStatus(pollingState: "healthy" | "disabled", network: boolean): TelegramChannelStatus {
  return {
    configured: true,
    adapter_id: network ? "client.telegram.bot-api" : "client.telegram.synthetic",
    state_persistence: network ? "postgresql" : "process-only-preview",
    polling: {
      state: pollingState,
      reason_code: pollingState === "healthy" ? "telegram.worker.ready" : "telegram.worker.disabled",
      next_offset: network ? 12 : 0,
      poll_revision: network ? 2 : 0,
      updates_handled: network ? 2 : 0,
      source: {
        status: pollingState,
        transport: network ? "telegram-bot-api" : "synthetic",
        network,
      },
    },
    replies: null,
    delivery: {
      status: pollingState,
      transport: network ? "telegram-bot-api" : "synthetic",
      network,
    },
    capabilities: {
      transport: network ? "telegram-bot-api" : "synthetic",
      network,
      text: true,
      attachments: false,
      max_text_length: 4096,
      ambiguous_send_retries: false,
    },
    limitations: ["attachments rejected before fetch"],
  };
}
