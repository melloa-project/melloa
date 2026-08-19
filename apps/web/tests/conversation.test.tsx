import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ConversationPage } from "../src/pages/conversation";

const mocks = vi.hoisted(() => ({
  context: {} as Record<string, unknown>,
  unlock: vi.fn(),
  listThreads: vi.fn(),
  createThread: vi.fn(),
  transcript: vi.fn(),
  modelRoutes: vi.fn(),
  postMessage: vi.fn(),
  resumeMessage: vi.fn(),
  inspectTurn: vi.fn(),
  notify: vi.fn(),
}));

vi.mock("../src/app", () => ({
  errorMessage: (error: unknown) => error instanceof Error ? error.message : "Unexpected error",
  useMelloa: () => mocks.context,
}));

vi.mock("../src/components/layout", () => ({
  useOwnerUnlock: () => mocks.unlock,
}));

const owner = {
  owner_id: "owner_1",
  session_id: "session_1",
  authentication_method: "local",
  authenticated_at: "2026-08-19T12:00:00Z",
  reauthenticated_until: "2026-08-19T12:05:00Z",
  expires_at: "2026-08-19T13:00:00Z",
};

const thread = {
  thread_id: "thread_1",
  owner_id: owner.owner_id,
  intelligence_id: "melli_1",
  title: "A meaningful decision",
  status: "active",
  sensitivity: "personal",
  retention_policy: "retention.owner-conversation",
  created_at: "2026-08-19T12:00:00Z",
  updated_at: "2026-08-19T12:00:00Z",
};

const secondThread = {
  ...thread,
  thread_id: "thread_2",
  title: "A family visit",
  created_at: "2026-08-19T12:05:00Z",
  updated_at: "2026-08-19T12:05:00Z",
};

const readyRoutes = {
  routes: [{
    route_kind: "openai_compatible",
    health: { state: "healthy" },
  }],
};

function message(id: string, author: string, text: string, threadId = thread.thread_id) {
  return {
    message_id: id,
    thread_id: threadId,
    author_principal_id: author,
    source_client: "owner-console",
    parts: [{ kind: "text", text }],
    citation_ids: [],
    delivery_state: "recorded",
    sensitivity: "personal",
    created_at: "2026-08-19T12:00:00Z",
    observed_at: "2026-08-19T12:00:00Z",
  };
}

function replyFor(text: string) {
  const inboundMessage = message("message_owner", owner.owner_id, text);
  return {
    inbound_message: inboundMessage,
    output_message: message("message_melli", "melli_1", "A useful answer"),
    turn: null,
    processing: { message_id: inboundMessage.message_id, state: "completed", attempts: [] },
    duplicate: false,
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, reject, resolve };
}

function renderConversation(path = "/conversation/thread_1") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/conversation/:threadId?" element={<ConversationPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("ConversationPage", () => {
  beforeEach(() => {
    [
      mocks.unlock,
      mocks.listThreads,
      mocks.createThread,
      mocks.transcript,
      mocks.modelRoutes,
      mocks.postMessage,
      mocks.resumeMessage,
      mocks.inspectTurn,
      mocks.notify,
    ].forEach((mock) => mock.mockReset());

    mocks.listThreads.mockResolvedValue([thread]);
    mocks.transcript.mockResolvedValue({ messages: [], turns: [], processing: [] });
    mocks.modelRoutes.mockResolvedValue(readyRoutes);
    mocks.createThread.mockResolvedValue(thread);
    mocks.postMessage.mockResolvedValue(replyFor("What should I consider?"));
    mocks.context = {
      api: {
        listThreads: mocks.listThreads,
        createThread: mocks.createThread,
        transcript: mocks.transcript,
        modelRoutes: mocks.modelRoutes,
        postMessage: mocks.postMessage,
        resumeMessage: mocks.resumeMessage,
        inspectTurn: mocks.inspectTurn,
      },
      principal: owner,
      canWrite: true,
      canUseSensitiveControls: false,
      notify: mocks.notify,
    };
  });

  it("opens ready for a real job without teaching the fixture or runtime", async () => {
    renderConversation();

    expect(await screen.findByRole("heading", { name: "What would be useful to think through?" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Help me think through a decision I’m facing." }));
    expect(screen.getByLabelText("Message Melli")).toHaveValue("Help me think through a decision I’m facing.");
    expect(mocks.postMessage).not.toHaveBeenCalled();
    expect(screen.queryByText(/no-network tour/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/eligible model required/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/route attempts/i)).not.toBeInTheDocument();
  });

  it("keeps ordinary conversation writable after recent confirmation expires", async () => {
    renderConversation();
    const composer = await screen.findByLabelText("Message Melli");
    fireEvent.change(composer, { target: { value: "What should I consider?" } });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));

    await waitFor(() => expect(mocks.postMessage).toHaveBeenCalledWith(
      thread.thread_id,
      "What should I consider?",
      expect.any(String),
    ));
    expect(mocks.unlock).not.toHaveBeenCalled();
  });

  it("asks for owner access when the browser lost its writing proof", async () => {
    mocks.context = { ...mocks.context, canWrite: false };
    renderConversation();
    fireEvent.change(await screen.findByLabelText("Message Melli"), {
      target: { value: "Continue our conversation" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));

    expect(mocks.unlock).toHaveBeenCalledWith(expect.stringMatching(/keep talking/i));
    expect(mocks.postMessage).not.toHaveBeenCalled();
  });

  it("removes the fixed response from the owner path when no capable model exists", async () => {
    mocks.modelRoutes.mockResolvedValue({
      routes: [{ route_kind: "synthetic", health: { state: "healthy" } }],
    });
    renderConversation();

    expect(await screen.findByRole("heading", { name: "Melli isn’t connected yet" })).toBeVisible();
    expect(screen.getByText(/private model connection needs attention/i)).toBeVisible();
    expect(screen.getByLabelText("Message Melli")).toBeDisabled();
    expect(screen.queryByRole("button", { name: /Fill a no-network/i })).not.toBeInTheDocument();
  });

  it("shows the owner message immediately while Melli is answering", async () => {
    const pending = deferred<ReturnType<typeof replyFor>>();
    mocks.postMessage.mockReturnValue(pending.promise);
    renderConversation();

    const composer = await screen.findByLabelText("Message Melli");
    fireEvent.change(composer, { target: { value: "My sister is visiting next week." } });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));

    expect(await screen.findByText("My sister is visiting next week.")).toBeVisible();
    expect(screen.getByText("Melli is thinking")).toBeVisible();
    expect(composer).toHaveValue("");

    await act(async () => pending.resolve(replyFor("My sister is visiting next week.")));
  });

  it("keeps a failed message recoverable and reuses its idempotency key", async () => {
    mocks.postMessage
      .mockRejectedValueOnce(new Error("The private model did not respond."))
      .mockResolvedValueOnce(replyFor("Please try this once."));
    renderConversation();

    const composer = await screen.findByLabelText("Message Melli");
    fireEvent.change(composer, { target: { value: "Please try this once." } });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Message not sent");
    expect(screen.getByRole("alert")).toHaveTextContent("The private model did not respond.");
    expect(composer).toHaveValue("Please try this once.");
    const firstKey = mocks.postMessage.mock.calls[0]?.[2];

    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(mocks.postMessage).toHaveBeenCalledTimes(2));
    expect(mocks.postMessage.mock.calls[1]?.[2]).toBe(firstKey);
    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
  });

  it("does not send Enter while an input method is composing", async () => {
    renderConversation();
    const composer = await screen.findByLabelText("Message Melli");
    fireEvent.change(composer, { target: { value: "まだ入力中" } });

    fireEvent.keyDown(composer, { code: "Enter", isComposing: true, key: "Enter" });
    expect(mocks.postMessage).not.toHaveBeenCalled();
    expect(composer).toHaveValue("まだ入力中");

    fireEvent.keyDown(composer, { code: "Enter", isComposing: false, key: "Enter" });
    await waitFor(() => expect(mocks.postMessage).toHaveBeenCalledOnce());
  });

  it("ignores a stale transcript after the owner switches conversations", async () => {
    const firstTranscript = deferred<{
      messages: ReturnType<typeof message>[];
      turns: never[];
      processing: never[];
    }>();
    const secondTranscript = deferred<{
      messages: ReturnType<typeof message>[];
      turns: never[];
      processing: never[];
    }>();
    mocks.listThreads.mockResolvedValue([thread, secondThread]);
    mocks.transcript.mockImplementation((selectedId: string) => (
      selectedId === thread.thread_id ? firstTranscript.promise : secondTranscript.promise
    ));
    renderConversation();

    await waitFor(() => expect(mocks.transcript).toHaveBeenCalledWith(thread.thread_id));
    fireEvent.click(await screen.findByRole("button", { name: /A family visit/ }));
    await waitFor(() => expect(mocks.transcript).toHaveBeenCalledWith(secondThread.thread_id));

    await act(async () => secondTranscript.resolve({
      messages: [message("message_second", owner.owner_id, "Plan a museum day.", secondThread.thread_id)],
      turns: [],
      processing: [],
    }));
    expect(await screen.findByText("Plan a museum day.")).toBeVisible();
    expect(screen.getByRole("heading", { name: secondThread.title })).toBeVisible();

    await act(async () => firstTranscript.resolve({
      messages: [message("message_first", owner.owner_id, "Stale first-thread content")],
      turns: [],
      processing: [],
    }));
    expect(screen.queryByText("Stale first-thread content")).not.toBeInTheDocument();
    expect(screen.getByText("Plan a museum day.")).toBeVisible();
  });

  it("creates and titles the first conversation from the owner’s first message", async () => {
    mocks.listThreads.mockResolvedValue([]);
    const created = { ...thread, title: "Help me choose between two roles" };
    mocks.createThread.mockResolvedValue(created);
    renderConversation("/conversation");

    fireEvent.change(await screen.findByLabelText("Message Melli"), {
      target: { value: "Help me choose between two roles" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));

    await waitFor(() => expect(mocks.createThread).toHaveBeenCalledWith({
      title: "Help me choose between two roles",
      sensitivity: "personal",
      retention_policy: "retention.owner-conversation",
    }));
    expect(mocks.postMessage).toHaveBeenCalledWith(
      created.thread_id,
      "Help me choose between two roles",
      expect.any(String),
    );
  });

  it("explains only useful context and privacy by default", async () => {
    const ownerMessage = message("message_1", owner.owner_id, "Use what you know about me");
    const melliMessage = message("message_2", "melli_1", "Here is what I would prioritize.");
    const turn = {
      turn_id: "turn_secret_internal_id",
      thread_id: thread.thread_id,
      triggering_message_ids: [ownerMessage.message_id],
      evidence_ids: [],
      model_run_ids: ["result_secret_internal_id"],
      policy_decision_ids: [],
      proposed_action_ids: [],
      executed_action_ids: [],
      output_message_ids: [melliMessage.message_id],
      decision_record: { summary: "Used relevant owner context and no external tools." },
      started_at: "2026-08-19T12:00:00Z",
      completed_at: "2026-08-19T12:00:01Z",
    };
    mocks.transcript.mockResolvedValue({
      messages: [ownerMessage, melliMessage],
      turns: [turn],
      processing: [{
        message_id: ownerMessage.message_id,
        state: "completed",
        attempts: [{
          model_result_summary: {
            route_id: "model.local",
            provider_id: "provider.local",
          },
        }],
      }],
    });
    mocks.inspectTurn.mockResolvedValue({
      turn,
      output_message: melliMessage,
      retrieval_manifest: { citations: [{ assertion_id: "assertion_secret", citation_id: "citation_secret" }] },
      model_result: {
        route_id: "model.local",
        provider_id: "provider.local",
        model_id: "capable-local-model",
        external_disclosure: false,
        started_at: "2026-08-19T12:00:00Z",
        completed_at: "2026-08-19T12:00:01Z",
        attempts: [{ processing_location: "device" }],
      },
    });
    renderConversation();

    fireEvent.click(await screen.findByRole("button", { name: "Why this answer?" }));
    expect(await screen.findByText("Melli used 1 saved memory.")).toBeVisible();
    expect(screen.getByText("Processed on this device without external disclosure.")).toBeVisible();
    expect(screen.queryByText("turn_secret_internal_id")).not.toBeInTheDocument();
    expect(screen.queryByText("assertion_secret")).not.toBeInTheDocument();
    expect(screen.queryByText(/turn ledger/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/route attempts/i)).not.toBeInTheDocument();
  });
});
