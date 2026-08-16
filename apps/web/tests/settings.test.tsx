import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SettingsPage } from "../src/pages/settings";

const mocks = vi.hoisted(() => ({
  inspectTelegramPairing: vi.fn(),
  inspectTelegramStatus: vi.fn(),
  listTelegramPairingCandidates: vi.fn(),
  confirmTelegramPairing: vi.fn(),
  revokeTelegramPairing: vi.fn(),
  notify: vi.fn(),
}));

vi.mock("../src/app", () => ({
  errorMessage: (error: unknown) => error instanceof Error ? error.message : "Unexpected error",
  useMelloa: () => ({
    api: {
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
    canMutate: true,
    notify: mocks.notify,
  }),
}));

describe("SettingsPage Telegram inspection", () => {
  beforeEach(() => {
    for (const mock of Object.values(mocks)) {
      mock.mockReset();
    }
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
});
