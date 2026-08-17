import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ModelActivityEntry, ModelActivityReport } from "../src/api";
import { ActivityPage } from "../src/pages/activity";

const mocks = vi.hoisted(() => ({ modelActivity: vi.fn() }));

vi.mock("../src/app", () => {
  const context = { api: { modelActivity: mocks.modelActivity } };
  return {
    errorMessage: (error: unknown) => error instanceof Error ? error.message : "Unexpected error",
    useMelloa: () => context,
  };
});

const localEntry: ModelActivityEntry = {
  turn_id: "turn_local_000000000000000000000000000001",
  thread_id: "thread_local_01",
  result_id: "result_local_000000000000000000000001",
  request_id: "request_local_000000000000000000000001",
  route_id: "model.local.qwen",
  provider_id: "provider.ollama",
  model_id: "qwen3:8b",
  input_tokens: 320,
  output_tokens: 120,
  cost_gbp: 0,
  started_at: "2026-08-16T12:00:00Z",
  completed_at: "2026-08-16T12:00:01Z",
  external_disclosure: false,
};

const externalEntry: ModelActivityEntry = {
  turn_id: "turn_external_00000000000000000000000001",
  thread_id: "thread_external_01",
  result_id: "result_external_000000000000000000000001",
  request_id: "request_external_000000000000000000000001",
  route_id: "model.codex.subscription",
  provider_id: "provider.openai-codex-subscription",
  model_id: "gpt-5.3-codex",
  input_tokens: 1_024,
  output_tokens: 256,
  cost_gbp: 0,
  started_at: "2026-08-16T12:04:00Z",
  completed_at: "2026-08-16T12:04:03Z",
  external_disclosure: true,
  disclosure: {
    retrieval_manifest_id: "retrieval_manifest_000000000000000000000001",
    purpose: "conversation.reply",
    triggering_message_ids: ["message_000000000000000000000000000001"],
    memory_references: [
      {
        citation_id: "citation_000000000000000000000000000001",
        assertion_id: "assertion_000000000000000000000000000001",
        sensitivity: "personal",
      },
      {
        citation_id: "citation_000000000000000000000000000002",
        assertion_id: "assertion_000000000000000000000000000002",
        sensitivity: "internal",
      },
    ],
    external_attempts: [
      {
        route_id: "model.codex.subscription",
        provider_id: "provider.openai-codex-subscription",
        model_id: "gpt-5.3-codex",
        processing_location: "approved_provider",
        outcome: "succeeded",
        started_at: "2026-08-16T12:04:00Z",
        completed_at: "2026-08-16T12:04:03Z",
        external_disclosure: true,
      },
    ],
  },
};

const report: ModelActivityReport = {
  owner_id: "owner_01",
  window_start: "2026-08-09T12:00:00Z",
  window_end: "2026-08-16T12:00:00Z",
  generated_at: "2026-08-16T12:05:00Z",
  total_runs: 2,
  external_disclosure_runs: 1,
  total_input_tokens: 1_344,
  total_output_tokens: 376,
  total_cost_gbp: 0,
  external_cost_gbp: 0,
  entries: [localEntry, externalEntry],
};

describe("ActivityPage", () => {
  beforeEach(() => {
    mocks.modelActivity.mockReset();
    mocks.modelActivity.mockResolvedValue(report);
  });

  it("filters the run ledger by disclosure state", async () => {
    render(
      <MemoryRouter initialEntries={["/activity"]}>
        <Routes>
          <Route path="/activity" element={<ActivityPage />} />
          <Route path="/memory" element={<MemoryLocation />} />
          <Route path="/conversation/:threadId" element={<ConversationLocation />} />
          <Route path="/providers" element={<ProviderLocation />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByText("qwen3:8b")).toBeInTheDocument();
    expect(screen.getByText("gpt-5.3-codex")).toBeInTheDocument();
    expect(screen.getByText("Req request_l…000001 · Result result_lo…000001")).toBeInTheDocument();
    expect(screen.getByText("Req request_e…000001 · Result result_ex…000001")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "All 2" })).toHaveAttribute("aria-pressed", "true");

    fireEvent.click(screen.getByRole("button", { name: "External 1" }));

    expect(screen.queryByText("qwen3:8b")).not.toBeInTheDocument();
    expect(screen.getByText("gpt-5.3-codex")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "External 1" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("Manifest retrieval…000001")).toBeInTheDocument();
    expect(screen.getByText("Conversation Reply")).toBeInTheDocument();
    expect(screen.getByText("Model Codex Subscription · Succeeded")).toBeInTheDocument();
    expect(screen.getByText("assertion…000001")).toBeInTheDocument();
    expect(screen.getByText("assertion…000002")).toBeInTheDocument();
    expect(screen.getByText("Personal · citation_…000001")).toBeInTheDocument();
    expect(screen.getByText("Internal · citation_…000002")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: `Open turn inspection for ${externalEntry.model_id}` }));
    expect(screen.getByText(`conversation-search=?turn=${externalEntry.turn_id}`)).toBeInTheDocument();
  });

  it("opens the exact provider route contract from a model run", async () => {
    render(
      <MemoryRouter initialEntries={["/activity"]}>
        <Routes>
          <Route path="/activity" element={<ActivityPage />} />
          <Route path="/providers" element={<ProviderLocation />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByText("qwen3:8b")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: `Open route contract for ${externalEntry.route_id}` }));

    expect(screen.getByText(`providers-search=?route=${encodeURIComponent(externalEntry.route_id)}`)).toBeInTheDocument();
  });

  it("opens disclosed memories from external activity evidence", async () => {
    render(
      <MemoryRouter initialEntries={["/activity"]}>
        <Routes>
          <Route path="/activity" element={<ActivityPage />} />
          <Route path="/memory" element={<MemoryLocation />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByText("qwen3:8b")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "External 1" }));
    fireEvent.click(screen.getByRole("button", {
      name: `Inspect disclosed memory ${externalEntry.disclosure?.memory_references[0]?.assertion_id}`,
    }));

    expect(screen.getByText(`memory-search=?assertion=${externalEntry.disclosure?.memory_references[0]?.assertion_id}`)).toBeInTheDocument();
  });

  it("filters back to local runs after viewing external disclosure evidence", async () => {
    render(
      <MemoryRouter>
        <ActivityPage />
      </MemoryRouter>,
    );

    expect(await screen.findByText("qwen3:8b")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "External 1" }));
    expect(screen.getByText("assertion…000001")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Local 1" }));

    expect(screen.getByText("qwen3:8b")).toBeInTheDocument();
    expect(screen.queryByText("gpt-5.3-codex")).not.toBeInTheDocument();
    expect(screen.queryByText("assertion…000001")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Local 1" })).toHaveAttribute("aria-pressed", "true");
  });

  it("reloads activity when the selected window changes", async () => {
    render(
      <MemoryRouter>
        <ActivityPage />
      </MemoryRouter>,
    );

    await waitFor(() => expect(mocks.modelActivity).toHaveBeenCalledTimes(1));
    fireEvent.change(screen.getByLabelText("Activity window"), { target: { value: "24h" } });

    await waitFor(() => expect(mocks.modelActivity).toHaveBeenCalledTimes(2));
    const [start, end] = mocks.modelActivity.mock.calls[1] as [Date, Date];
    expect((end.getTime() - start.getTime()) / (60 * 60 * 1_000)).toBe(24);
  });

  it("keeps the latest activity refresh when an older request resolves last", async () => {
    const stale = deferred<ModelActivityReport>();
    const latest = deferred<ModelActivityReport>();
    mocks.modelActivity.mockReset();
    mocks.modelActivity.mockReturnValueOnce(stale.promise).mockReturnValueOnce(latest.promise);

    render(
      <MemoryRouter>
        <ActivityPage />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole("button", { name: /refresh/i }));

    await act(async () => {
      latest.resolve({
        ...report,
        total_runs: 1,
        external_disclosure_runs: 1,
        total_input_tokens: externalEntry.input_tokens,
        total_output_tokens: externalEntry.output_tokens,
        entries: [externalEntry],
      });
      await latest.promise;
    });

    expect(await screen.findByText("gpt-5.3-codex")).toBeInTheDocument();

    await act(async () => {
      stale.resolve({
        ...report,
        total_runs: 1,
        external_disclosure_runs: 0,
        total_input_tokens: localEntry.input_tokens,
        total_output_tokens: localEntry.output_tokens,
        entries: [localEntry],
      });
      await stale.promise;
    });

    await waitFor(() => {
      expect(screen.queryByText("qwen3:8b")).not.toBeInTheDocument();
    });
    expect(screen.getByText("gpt-5.3-codex")).toBeInTheDocument();
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

function MemoryLocation() {
  const location = useLocation();
  return <div>{`memory-search=${location.search}`}</div>;
}

function ConversationLocation() {
  const location = useLocation();
  return <div>{`conversation-search=${location.search}`}</div>;
}

function ProviderLocation() {
  const location = useLocation();
  return <div>{`providers-search=${location.search}`}</div>;
}
