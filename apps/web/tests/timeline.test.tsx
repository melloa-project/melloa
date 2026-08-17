import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { OwnerTimelineReport } from "../src/api";
import { TimelinePage } from "../src/pages/timeline";

const mocks = vi.hoisted(() => ({ ownerTimeline: vi.fn() }));

vi.mock("../src/app", () => {
  const context = { api: { ownerTimeline: mocks.ownerTimeline } };
  return {
    errorMessage: (error: unknown) => error instanceof Error ? error.message : "Unexpected error",
    useMelloa: () => context,
  };
});

const report: OwnerTimelineReport = {
  contract_version: "1.1.0",
  owner_id: "owner_00000000000000000000000000000001",
  window_start: "2026-08-10T12:00:00Z",
  window_end: "2026-08-17T12:00:00Z",
  generated_at: "2026-08-17T12:00:00Z",
  total_events: 4,
  matching_events: 9,
  truncated: true,
  coverage: [
    "timeline.coverage.canonical-conversation",
    "timeline.coverage.model-activity",
    "timeline.coverage.outbound-delivery",
    "timeline.coverage.reply-processing",
  ],
  limitations: [
    "timeline.limit.current-mvp-canonical-records",
    "timeline.limit.newest-events-only",
    "timeline.limit.no-message-or-model-text",
    "timeline.limit.no-process-local-auth-events",
  ],
  entries: [
    {
      event_id: "timeline_00000000000000000000000000000004",
      kind: "timeline.model-route.completed",
      occurred_at: "2026-08-17T11:04:03Z",
      source: "timeline.source.model-activity",
      summary: "Model route completed with external disclosure evidence.",
      thread_id: "thread_000000000000000000000000000001",
      turn_id: "turn_000000000000000000000000000001",
      status: "model.disclosure.external",
      references: [
        "request_000000000000000000000000000001",
        "assertion_000000000000000000000000000001",
      ],
      metadata: {
        route_id: "model.codex.subscription",
        provider_id: "provider.openai-codex-subscription",
        model_id: "gpt-5.3-codex",
        input_tokens: 1_024,
        output_tokens: 256,
        cost_gbp: 0,
        external_disclosure: true,
        disclosed_memory_count: 1,
      },
    },
    {
      event_id: "timeline_00000000000000000000000000000003",
      kind: "timeline.outbound-delivery.completed",
      occurred_at: "2026-08-17T11:03:00Z",
      source: "timeline.source.outbound-delivery",
      summary: "Outbound delivery completed under exact authorization.",
      thread_id: "thread_000000000000000000000000000001",
      message_id: "message_000000000000000000000000000002",
      work_id: "deliverywork_000000000000000000000000000001",
      status: "delivery.work.completed",
      references: ["attempt_000000000000000000000000000001"],
      metadata: {
        client_adapter: "client.telegram.synthetic",
        attempt_count: 1,
        max_attempts: 3,
        resumption_count: 0,
      },
    },
    {
      event_id: "timeline_00000000000000000000000000000002",
      kind: "timeline.reply-processing.ready",
      occurred_at: "2026-08-17T11:02:00Z",
      source: "timeline.source.reply-processing",
      summary: "Reply processing is queued or waiting.",
      thread_id: "thread_000000000000000000000000000001",
      message_id: "message_000000000000000000000000000001",
      work_id: "work_000000000000000000000000000001",
      status: "conversation.processing.ready",
      references: [],
      metadata: { attempt_count: 0, max_attempts: 3, resumption_count: 0 },
    },
    {
      event_id: "timeline_00000000000000000000000000000001",
      kind: "timeline.conversation.message-created",
      occurred_at: "2026-08-17T11:01:00Z",
      source: "timeline.source.owner-message",
      summary: "Owner message accepted into canonical conversation.",
      thread_id: "thread_000000000000000000000000000001",
      message_id: "message_000000000000000000000000000001",
      status: "conversation.delivery.delivered",
      sensitivity: "personal",
      references: [],
      metadata: {
        source_client: "client.owner-console",
        part_count: 1,
        citation_count: 0,
        contains_text: true,
        contains_attachment_reference: false,
      },
    },
  ],
};

describe("TimelinePage", () => {
  beforeEach(() => {
    mocks.ownerTimeline.mockReset();
    mocks.ownerTimeline.mockResolvedValue(report);
  });

  it("renders a redacted owner timeline and filters by event group", async () => {
    render(
      <MemoryRouter initialEntries={["/timeline"]}>
        <Routes>
          <Route path="/timeline" element={<TimelinePage />} />
          <Route path="/conversation/:threadId" element={<ConversationLocation />} />
          <Route path="/memory" element={<MemoryLocation />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByText("Model route completed with external disclosure evidence.")).toBeInTheDocument();
    expect(screen.getByText("Outbound delivery completed under exact authorization.")).toBeInTheDocument();
    expect(screen.getByText("Owner message accepted into canonical conversation.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "All 4" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("4 newest shown")).toBeInTheDocument();
    expect(screen.getByText("4 newest of 9")).toBeInTheDocument();
    expect(screen.queryByText("Synthetic prompt")).not.toBeInTheDocument();
    expect(screen.getByText("Current Mvp Canonical Records")).toBeInTheDocument();
    expect(screen.getByText("Newest Events Only")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Model 1" }));

    expect(screen.getByText("model.codex.subscription")).toBeInTheDocument();
    expect(screen.getByText("provider.openai-codex-subscription")).toBeInTheDocument();
    expect(screen.queryByText("Outbound delivery completed under exact authorization.")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", {
      name: `Open conversation ${report.entries[0]?.thread_id}`,
    }));
    expect(screen.getByText(`conversation-search=?turn=${report.entries[0]?.turn_id}`)).toBeInTheDocument();
  });

  it("opens referenced memory assertions from timeline evidence", async () => {
    render(
      <MemoryRouter initialEntries={["/timeline"]}>
        <Routes>
          <Route path="/timeline" element={<TimelinePage />} />
          <Route path="/memory" element={<MemoryLocation />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByText("Model route completed with external disclosure evidence.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Model 1" }));
    fireEvent.click(screen.getByRole("button", { name: "assertion…000001" }));

    expect(screen.getByText(`memory-search=?assertion=${report.entries[0]?.references[1]}`)).toBeInTheDocument();
  });

  it("reloads timeline when the selected window changes", async () => {
    render(
      <MemoryRouter>
        <TimelinePage />
      </MemoryRouter>,
    );

    await waitFor(() => expect(mocks.ownerTimeline).toHaveBeenCalledTimes(1));
    fireEvent.change(screen.getByLabelText("Timeline window"), { target: { value: "24h" } });

    await waitFor(() => expect(mocks.ownerTimeline).toHaveBeenCalledTimes(2));
    const [start, end, limit] = mocks.ownerTimeline.mock.calls[1] as [Date, Date, number];
    expect((end.getTime() - start.getTime()) / (60 * 60 * 1_000)).toBe(24);
    expect(limit).toBe(150);
  });
});

function ConversationLocation() {
  const location = useLocation();
  return <div>{`conversation-search=${location.search}`}</div>;
}

function MemoryLocation() {
  const location = useLocation();
  return <div>{`memory-search=${location.search}`}</div>;
}
