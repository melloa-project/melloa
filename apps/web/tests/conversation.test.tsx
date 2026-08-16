import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  ConversationMessage,
  ConversationProcessingStatus,
  ConversationReply,
  ConversationThread,
  ConversationTurn,
  ConversationTurnInspection,
} from "../src/api";
import { ConversationPage } from "../src/pages/conversation";

const mocks = vi.hoisted(() => ({
  listThreads: vi.fn(),
  listMessages: vi.fn(),
  listTurns: vi.fn(),
  listProcessing: vi.fn(),
  inspectTurn: vi.fn(),
  postMessage: vi.fn(),
  notify: vi.fn(),
}));

vi.mock("../src/app", () => {
  const context = {
    api: {
      listThreads: mocks.listThreads,
      listMessages: mocks.listMessages,
      listTurns: mocks.listTurns,
      listProcessing: mocks.listProcessing,
      inspectTurn: mocks.inspectTurn,
      postMessage: mocks.postMessage,
    },
    principal: { owner_id: "owner_01" },
    canMutate: true,
    notify: mocks.notify,
  };
  return {
    errorMessage: (error: unknown) => error instanceof Error ? error.message : "Unexpected error",
    useMelloa: () => context,
  };
});

const thread: ConversationThread = {
  thread_id: "thread_01",
  owner_id: "owner_01",
  intelligence_id: "melli_01",
  title: "Today with Melli",
  status: "active",
  sensitivity: "personal",
  retention_policy: "retention.owner-conversation",
  created_at: "2026-08-16T12:00:00Z",
  updated_at: "2026-08-16T12:00:02Z",
};

const ownerMessage: ConversationMessage = {
  message_id: "message_owner_01",
  thread_id: thread.thread_id,
  author_principal_id: "owner_01",
  source_client: "owner-console",
  parts: [{ kind: "text", text: "What should I focus on?" }],
  citation_ids: [],
  delivery_state: "accepted",
  sensitivity: "personal",
  created_at: "2026-08-16T12:00:00Z",
  observed_at: "2026-08-16T12:00:00Z",
};

const outputMessage: ConversationMessage = {
  ...ownerMessage,
  message_id: "message_melli_01",
  author_principal_id: "melli_01",
  parts: [{ kind: "text", text: "A grounded response." }],
  citation_ids: ["citation_01"],
  created_at: "2026-08-16T12:00:02Z",
  observed_at: "2026-08-16T12:00:02Z",
};

const turn: ConversationTurn = {
  turn_id: "turn_01",
  thread_id: thread.thread_id,
  triggering_message_ids: [ownerMessage.message_id],
  evidence_ids: ["citation_01"],
  model_run_ids: ["result_01"],
  policy_decision_ids: [],
  proposed_action_ids: [],
  executed_action_ids: [],
  output_message_ids: [outputMessage.message_id],
  decision_record: {
    summary: "Responded without proposing an external action.",
    prompt_version: "conversation-v1",
    runtime_version: "melloa-core/test",
    uncertainty: "low",
  },
  started_at: "2026-08-16T12:00:01Z",
  completed_at: "2026-08-16T12:00:02Z",
};

const processing: ConversationProcessingStatus = {
  work_id: "work_01",
  thread_id: thread.thread_id,
  message_id: ownerMessage.message_id,
  state: "completed",
  attempt_count: 1,
  max_attempts: 3,
  available_at: "2026-08-16T12:00:00Z",
  completed_at: "2026-08-16T12:00:02Z",
  attempts: [],
  resumptions: [],
};

const inspection: ConversationTurnInspection = {
  turn,
  retrieval_manifest: {
    citations: [{ citation_id: "citation_01", assertion_id: "assertion_01", epistemic_status: "owner_confirmed" }],
  },
  model_result: {
    route_id: "model.local.qwen",
    provider_id: "provider.ollama",
    model_id: "qwen3:8b",
    started_at: "2026-08-16T12:00:01Z",
    completed_at: "2026-08-16T12:00:02Z",
    external_disclosure: false,
    input_tokens: 24,
    output_tokens: 12,
    cost_gbp: 0,
    attempts: [{ route_id: "model.local.qwen", outcome: "succeeded", processing_location: "device" }],
  },
  output_message: outputMessage,
};

describe("ConversationPage", () => {
  beforeEach(() => {
    for (const mock of Object.values(mocks)) {
      mock.mockReset();
    }
    mocks.listThreads.mockResolvedValue([thread]);
    mocks.listMessages.mockResolvedValue([ownerMessage, outputMessage]);
    mocks.listTurns.mockResolvedValue([turn]);
    mocks.listProcessing.mockResolvedValue([processing]);
    mocks.inspectTurn.mockResolvedValue(inspection);
    const reply: ConversationReply = { inbound_message: ownerMessage, output_message: outputMessage, turn, processing, duplicate: false };
    mocks.postMessage.mockResolvedValue(reply);
  });

  it("supports send and exposes route, cost, disclosure, and provenance", async () => {
    render(
      <MemoryRouter initialEntries={[`/conversation/${thread.thread_id}`]}>
        <Routes><Route path="/conversation/:threadId" element={<ConversationPage />} /></Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByRole("heading", { name: thread.title })).toBeInTheDocument();
    const response = await screen.findByText("A grounded response.");
    const inspectButton = response.closest("button");
    expect(inspectButton).not.toBeNull();
    fireEvent.click(inspectButton as HTMLButtonElement);

    expect(await screen.findByText("qwen3:8b")).toBeInTheDocument();
    expect(screen.getByText("No external disclosure")).toBeInTheDocument();
    expect(screen.getByText("assertion_01")).toBeInTheDocument();
    expect(screen.getByText("£0.00")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Message Melli"), { target: { value: "Plan the next step." } });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    await waitFor(() => expect(mocks.postMessage).toHaveBeenCalledWith(
      thread.thread_id,
      "Plan the next step.",
      expect.any(String),
    ));
  });

  it("labels Codex CLI token and subscription cost metadata as unreported", async () => {
    mocks.inspectTurn.mockResolvedValue({
      ...inspection,
      model_result: {
        ...inspection.model_result,
        route_id: "model.codex.subscription",
        provider_id: "provider.openai-codex-subscription",
        model_id: "codex-subscription-model",
        external_disclosure: true,
        input_tokens: 0,
        output_tokens: 0,
        cost_gbp: 0,
        attempts: [{ route_id: "model.codex.subscription", outcome: "succeeded", processing_location: "approved_provider" }],
      },
    });
    render(
      <MemoryRouter initialEntries={[`/conversation/${thread.thread_id}`]}>
        <Routes><Route path="/conversation/:threadId" element={<ConversationPage />} /></Routes>
      </MemoryRouter>,
    );

    const response = await screen.findByText("A grounded response.");
    fireEvent.click(response.closest("button") as HTMLButtonElement);

    expect(await screen.findByText("codex-subscription-model")).toBeInTheDocument();
    expect(screen.getAllByText("Unreported")).toHaveLength(2);
    expect(screen.getByText(/Subscription fees are not represented as per-call cost/i)).toBeInTheDocument();
  });
});
