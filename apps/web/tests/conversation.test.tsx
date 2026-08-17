import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  ConversationMessage,
  ConversationProcessingStatus,
  ConversationReply,
  ConversationThread,
  ConversationTurn,
  ConversationTurnInspection,
  DeliveryWorkStatus,
} from "../src/api";
import { ConversationPage } from "../src/pages/conversation";

const mocks = vi.hoisted(() => ({
  listThreads: vi.fn(),
  listMessages: vi.fn(),
  listTurns: vi.fn(),
  listProcessing: vi.fn(),
  listDeliveries: vi.fn(),
  inspectTurn: vi.fn(),
  postMessage: vi.fn(),
  resumeMessage: vi.fn(),
  resumeDelivery: vi.fn(),
  notify: vi.fn(),
  canMutate: true,
}));

vi.mock("../src/app", () => {
  const context = {
    api: {
      listThreads: mocks.listThreads,
      listMessages: mocks.listMessages,
      listTurns: mocks.listTurns,
      listProcessing: mocks.listProcessing,
      listDeliveries: mocks.listDeliveries,
      inspectTurn: mocks.inspectTurn,
      postMessage: mocks.postMessage,
      resumeMessage: mocks.resumeMessage,
      resumeDelivery: mocks.resumeDelivery,
    },
    principal: { owner_id: "owner_01" },
    get canMutate() {
      return mocks.canMutate;
    },
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

const otherThread: ConversationThread = {
  ...thread,
  thread_id: "thread_02",
  title: "Follow-up thread",
  created_at: "2026-08-16T12:30:00Z",
  updated_at: "2026-08-16T12:30:02Z",
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

const otherOutputMessage: ConversationMessage = {
  ...outputMessage,
  message_id: "message_melli_02",
  thread_id: otherThread.thread_id,
  parts: [{ kind: "text", text: "Second thread reply." }],
  citation_ids: [],
  created_at: "2026-08-16T12:30:02Z",
  observed_at: "2026-08-16T12:30:02Z",
};

const turn: ConversationTurn = {
  turn_id: "turn_01",
  thread_id: thread.thread_id,
  triggering_message_ids: [ownerMessage.message_id],
  evidence_ids: ["citation_01"],
  model_run_ids: ["result_01"],
  policy_decision_ids: ["decision_01"],
  proposed_action_ids: ["proposal_01"],
  executed_action_ids: ["action_01"],
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

const deadProcessing: ConversationProcessingStatus = {
  ...processing,
  state: "dead",
  attempt_count: 3,
  completed_at: null,
  last_error_code: "model.route.exhausted",
  attempts: [
    {
      attempt_id: "attempt_dead_01",
      work_id: processing.work_id,
      message_id: ownerMessage.message_id,
      attempt: 3,
      outcome: "dead",
      error_code: "model.route.exhausted",
      started_at: "2026-08-16T12:00:01Z",
      completed_at: "2026-08-16T12:00:02Z",
      model_route_attempts: [],
      disclosed_memory_ids: [],
      external_disclosure: false,
    },
  ],
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

const completedDelivery: DeliveryWorkStatus = {
  work_id: "work_delivery_01",
  thread_id: thread.thread_id,
  message_id: outputMessage.message_id,
  requested_by: "melli_01",
  client_adapter: "client.telegram.synthetic",
  destination_ref: "telegram:pairing:pairing_000000000000000000000001",
  action_hash: "sha256:" + "a".repeat(64),
  current_policy_decision_id: "decision_0000000000000000000000000001",
  state: "completed",
  attempt_count: 1,
  max_attempts: 3,
  available_at: "2026-08-16T12:00:02Z",
  completed_at: "2026-08-16T12:00:03Z",
  attempts: [
    {
      attempt_id: "deliveryattempt_000000000000000000000001",
      work_id: "work_delivery_01",
      message_id: outputMessage.message_id,
      attempt: 1,
      authorization_request_id: "authorization_000000000000000000000001",
      policy_decision_id: "decision_0000000000000000000000000001",
      action_hash: "sha256:" + "a".repeat(64),
      outcome: "succeeded",
      started_at: "2026-08-16T12:00:02Z",
      completed_at: "2026-08-16T12:00:03Z",
      adapter_receipt: {
        delivery_id: "delivery_000000000000000000000000000001",
        message_id: outputMessage.message_id,
        client_adapter: "client.telegram.synthetic",
        destination_ref: "telegram:pairing:pairing_000000000000000000000001",
        attempt: 1,
        state: "delivered",
        attempted_at: "2026-08-16T12:00:03Z",
      },
      execution_receipt: {
        action_id: "action_000000000000000000000000000001",
        decision_id: "decision_0000000000000000000000000001",
        action_hash: "sha256:" + "a".repeat(64),
        capability_id: "client.telegram.synthetic",
        operation: "messages.send",
        delivery_id: "delivery_000000000000000000000000000001",
        executed_at: "2026-08-16T12:00:03Z",
      },
    },
  ],
  resumptions: [],
};

const deadDelivery: DeliveryWorkStatus = {
  ...completedDelivery,
  work_id: "work_delivery_dead_01",
  state: "dead",
  attempt_count: 3,
  completed_at: null,
  last_error_code: "telegram.delivery.outcome_unknown",
  attempts: [
    {
      attempt_id: "deliveryattempt_000000000000000000000002",
      work_id: "work_delivery_dead_01",
      message_id: outputMessage.message_id,
      attempt: 3,
      authorization_request_id: "authorization_000000000000000000000001",
      policy_decision_id: "decision_0000000000000000000000000001",
      action_hash: "sha256:" + "a".repeat(64),
      outcome: "dead",
      error_code: "telegram.delivery.outcome_unknown",
      started_at: "2026-08-16T12:00:02Z",
      completed_at: "2026-08-16T12:00:03Z",
      adapter_receipt: null,
      execution_receipt: null,
    },
  ],
};

describe("ConversationPage", () => {
  beforeEach(() => {
    for (const mock of [
      mocks.listThreads,
      mocks.listMessages,
      mocks.listTurns,
      mocks.listProcessing,
      mocks.listDeliveries,
      mocks.inspectTurn,
      mocks.postMessage,
      mocks.resumeMessage,
      mocks.resumeDelivery,
      mocks.notify,
    ]) {
      mock.mockReset();
    }
    mocks.canMutate = true;
    mocks.listThreads.mockResolvedValue([thread]);
    mocks.listMessages.mockResolvedValue([ownerMessage, outputMessage]);
    mocks.listTurns.mockResolvedValue([turn]);
    mocks.listProcessing.mockResolvedValue([processing]);
    mocks.listDeliveries.mockResolvedValue([]);
    mocks.inspectTurn.mockResolvedValue(inspection);
    const reply: ConversationReply = { inbound_message: ownerMessage, output_message: outputMessage, turn, processing, duplicate: false };
    mocks.postMessage.mockResolvedValue(reply);
    mocks.resumeMessage.mockResolvedValue({ ...deadProcessing, state: "queued", attempt_count: 3 });
    mocks.resumeDelivery.mockResolvedValue({ ...deadDelivery, state: "queued", attempt_count: 3 });
  });

  it("supports send and exposes route, cost, disclosure, and provenance", async () => {
    render(
      <MemoryRouter initialEntries={[`/conversation/${thread.thread_id}`]}>
        <Routes>
          <Route path="/conversation/:threadId" element={<ConversationPage />} />
          <Route path="/memory" element={<MemoryLocation />} />
        </Routes>
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
    expect(screen.getByText("Turn ledger")).toBeInTheDocument();
    expect(screen.getByText("Triggering messages")).toBeInTheDocument();
    expect(screen.getByText(ownerMessage.message_id)).toBeInTheDocument();
    expect(screen.getByText("Policy decisions")).toBeInTheDocument();
    expect(screen.getByText("decision_01")).toBeInTheDocument();
    expect(screen.getByText("Proposed actions")).toBeInTheDocument();
    expect(screen.getByText("proposal_01")).toBeInTheDocument();
    expect(screen.getByText("Executed actions")).toBeInTheDocument();
    expect(screen.getByText("action_01")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Message Melli"), { target: { value: "Plan the next step." } });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    await waitFor(() => expect(mocks.postMessage).toHaveBeenCalledWith(
      thread.thread_id,
      "Plan the next step.",
      expect.any(String),
    ));

    fireEvent.click(screen.getByRole("button", { name: "Inspect memory assertion assertion_01" }));
    expect(screen.getByText("memory-search=?assertion=assertion_01")).toBeInTheDocument();
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

  it("offers privacy-safe starter prompts without auto-sending", async () => {
    mocks.listMessages.mockResolvedValue([]);
    mocks.listTurns.mockResolvedValue([]);
    mocks.listProcessing.mockResolvedValue([]);
    mocks.listDeliveries.mockResolvedValue([]);
    render(
      <MemoryRouter initialEntries={[`/conversation/${thread.thread_id}`]}>
        <Routes><Route path="/conversation/:threadId" element={<ConversationPage />} /></Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByRole("heading", { name: "Start with what matters now" })).toBeInTheDocument();
    const starters = screen.getByLabelText("Starter prompts");
    fireEvent.click(within(starters).getByRole("button", { name: /Use memory evidence/i }));

    expect(screen.getByLabelText("Message Melli")).toHaveValue(
      "What can you answer from the current seed memory, and what evidence will you cite?",
    );
    expect(mocks.postMessage).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    await waitFor(() => expect(mocks.postMessage).toHaveBeenCalledWith(
      thread.thread_id,
      "What can you answer from the current seed memory, and what evidence will you cite?",
      expect.any(String),
    ));
  });

  it("keeps composer drafts and retry keys scoped to the selected thread", async () => {
    mocks.listThreads.mockResolvedValue([thread, otherThread]);
    render(
      <MemoryRouter initialEntries={[`/conversation/${thread.thread_id}`]}>
        <Routes><Route path="/conversation/:threadId" element={<ConversationPage />} /></Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByRole("heading", { name: thread.title })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Message Melli"), { target: { value: "First thread draft." } });

    fireEvent.click(screen.getByRole("button", { name: /Follow-up thread/i }));
    expect(await screen.findByRole("heading", { name: otherThread.title })).toBeInTheDocument();
    expect(screen.getByLabelText("Message Melli")).toHaveValue("");

    fireEvent.change(screen.getByLabelText("Message Melli"), { target: { value: "Second thread draft." } });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    await waitFor(() => expect(mocks.postMessage).toHaveBeenCalledWith(
      otherThread.thread_id,
      "Second thread draft.",
      expect.any(String),
    ));

    fireEvent.click(screen.getByRole("button", { name: /Today with Melli/i }));
    expect(await screen.findByRole("heading", { name: thread.title })).toBeInTheDocument();
    expect(screen.getByLabelText("Message Melli")).toHaveValue("First thread draft.");

    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    await waitFor(() => expect(mocks.postMessage).toHaveBeenLastCalledWith(
      thread.thread_id,
      "First thread draft.",
      expect.any(String),
    ));
  });

  it("keeps the latest selected conversation when an older thread load resolves last", async () => {
    const staleMessages = deferred<readonly ConversationMessage[]>();
    mocks.listThreads.mockResolvedValue([thread, otherThread]);
    mocks.listMessages.mockImplementation((selectedId: string) => (
      selectedId === thread.thread_id
        ? staleMessages.promise
        : Promise.resolve([otherOutputMessage])
    ));
    mocks.listTurns.mockResolvedValue([]);
    mocks.listProcessing.mockResolvedValue([]);
    mocks.listDeliveries.mockResolvedValue([]);

    render(
      <MemoryRouter initialEntries={[`/conversation/${thread.thread_id}`]}>
        <Routes><Route path="/conversation/:threadId" element={<ConversationPage />} /></Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByRole("heading", { name: thread.title })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Follow-up thread/i }));

    expect(await screen.findByRole("heading", { name: otherThread.title })).toBeInTheDocument();
    expect(await screen.findByText("Second thread reply.")).toBeInTheDocument();

    await act(async () => {
      staleMessages.resolve([ownerMessage, outputMessage]);
      await staleMessages.promise;
    });

    await waitFor(() => {
      expect(screen.queryByText("A grounded response.")).not.toBeInTheDocument();
    });
    expect(screen.getByText("Second thread reply.")).toBeInTheDocument();
  });

  it("opens the exact turn inspector from a route query", async () => {
    render(
      <MemoryRouter initialEntries={[`/conversation/${thread.thread_id}?turn=${turn.turn_id}`]}>
        <Routes><Route path="/conversation/:threadId" element={<ConversationPage />} /></Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByRole("heading", { name: "Turn details" })).toBeInTheDocument();
    expect(await screen.findByText("qwen3:8b")).toBeInTheDocument();
    expect(mocks.inspectTurn).toHaveBeenCalledWith(thread.thread_id, turn.turn_id);
  });

  it("shows outbound delivery authority and resumes dead delivery work", async () => {
    mocks.listDeliveries.mockResolvedValue([completedDelivery, deadDelivery]);
    render(
      <MemoryRouter initialEntries={[`/conversation/${thread.thread_id}`]}>
        <Routes><Route path="/conversation/:threadId" element={<ConversationPage />} /></Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByText("Delivered · inspect")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Delivered · inspect"));

    expect(await screen.findByRole("heading", { name: "Delivery" })).toBeInTheDocument();
    expect(screen.getByText("client.telegram.synthetic")).toBeInTheDocument();
    expect(screen.getByText("telegram:pairing:pairing_000000000000000000000001")).toBeInTheDocument();
    expect(screen.getByText(/adapter delivery_.*execution action_/i)).toBeInTheDocument();

    fireEvent.click(screen.getByText("Delivery failed · inspect"));
    expect(await screen.findByText("Telegram Delivery Outcome Unknown")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Resume delivery with bounded retries/i }));

    await waitFor(() => expect(mocks.resumeDelivery).toHaveBeenCalledWith(thread.thread_id, deadDelivery.work_id));
    expect(mocks.notify).toHaveBeenCalledWith("A new bounded delivery retry budget was added.", "success");
  });

  it("disables dead reply and delivery resume controls without mutation proof", async () => {
    mocks.canMutate = false;
    mocks.listProcessing.mockResolvedValue([deadProcessing]);
    mocks.listDeliveries.mockResolvedValue([deadDelivery]);
    render(
      <MemoryRouter initialEntries={[`/conversation/${thread.thread_id}`]}>
        <Routes><Route path="/conversation/:threadId" element={<ConversationPage />} /></Routes>
      </MemoryRouter>,
    );

    const replyResume = await screen.findByRole("button", { name: "Reply failed · resume" });
    expect(replyResume).toBeDisabled();
    fireEvent.click(replyResume);
    expect(mocks.resumeMessage).not.toHaveBeenCalled();

    fireEvent.click(screen.getByText("What should I focus on?"));
    expect(await screen.findByRole("heading", { name: "Processing" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Resume with bounded retries/i })).toBeDisabled();

    fireEvent.click(screen.getByText("Delivery failed · inspect"));
    expect(await screen.findByRole("heading", { name: "Delivery" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Resume delivery with bounded retries/i })).toBeDisabled();
    expect(mocks.resumeDelivery).not.toHaveBeenCalled();
  });
});

function MemoryLocation() {
  const location = useLocation();
  return <div>{`memory-search=${location.search}`}</div>;
}

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
