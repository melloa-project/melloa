import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  ConversationProcessingAttempt,
  ConversationProcessingStatus,
} from "../src/api";
import { ConversationPage } from "../src/pages/conversation";

const mocks = vi.hoisted(() => ({
  context: {} as Record<string, unknown>,
  unlock: vi.fn(),
  listThreads: vi.fn(),
  createThread: vi.fn(),
  deleteThread: vi.fn(),
  transcript: vi.fn(),
  conversationAvailability: vi.fn(),
  postMessage: vi.fn(),
  correctMessage: vi.fn(),
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

const readyAvailability = { available: true };

function message(id: string, author: string, text: string, threadId = thread.thread_id) {
  return {
    message_id: id,
    thread_id: threadId,
    author_principal_id: author,
    source_client: "owner-console",
    parts: [{ kind: "text", text }],
    citation_ids: [],
    sensitivity: "personal",
    created_at: "2026-08-19T12:00:00Z",
    observed_at: "2026-08-19T12:00:00Z",
  };
}

function replyFor(text: string, selectedThreadId = thread.thread_id) {
  const inboundMessage = message("message_owner", owner.owner_id, text, selectedThreadId);
  return {
    inbound_message: inboundMessage,
    output_message: message("message_melli", "melli_1", "A useful answer", selectedThreadId),
    turn: null,
    processing: { message_id: inboundMessage.message_id, state: "completed", attempts: [] },
    duplicate: false,
  };
}

function failedExternalAttempt(
  attempt: number,
  memoryIds: readonly string[],
  target: "failed" | "result" = "failed",
): ConversationProcessingAttempt {
  const modelTarget = {
    provider_id: attempt === 1 ? "provider.acme-cloud" : "provider.second-cloud",
    model_id: attempt === 1 ? "reasoner-v2" : "reasoner-v3",
    processing_location: "approved_provider" as const,
  };
  return {
    attempt_id: `attempt_${attempt}`,
    work_id: "work_external",
    message_id: "message_external",
    attempt,
    request_id: `request_${attempt}`,
    outcome: "retry_scheduled",
    error_code: target === "failed" ? "model.gateway_failed" : "model.invalid_output",
    started_at: `2026-08-19T12:00:0${attempt}Z`,
    completed_at: `2026-08-19T12:00:0${attempt}Z`,
    retry_at: `2026-08-19T12:01:0${attempt}Z`,
    retrieval_manifest_id: `manifest_${attempt}`,
    model_result_summary: target === "result" ? {
      ...modelTarget,
      result_id: `result_${attempt}`,
      request_id: `request_${attempt}`,
      input_tokens: 20,
      output_tokens: 0,
      cost_gbp: 0,
      started_at: `2026-08-19T12:00:0${attempt}Z`,
      completed_at: `2026-08-19T12:00:0${attempt}Z`,
      external_disclosure: true,
    } : null,
    failed_model_target: target === "failed" ? modelTarget : null,
    disclosed_memory_ids: memoryIds,
    external_disclosure: true,
  };
}

function processingStatus(
  messageId: string,
  state: "ready" | "completed",
  attempts: readonly ConversationProcessingAttempt[],
): ConversationProcessingStatus {
  return {
    work_id: "work_external",
    thread_id: thread.thread_id,
    message_id: messageId,
    state,
    attempt_count: attempts.length,
    max_attempts: 5,
    available_at: "2026-08-19T12:01:00Z",
    completed_at: state === "completed" ? "2026-08-19T12:02:00Z" : null,
    attempts,
    resumptions: [],
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
      mocks.deleteThread,
      mocks.transcript,
      mocks.conversationAvailability,
      mocks.postMessage,
      mocks.correctMessage,
      mocks.resumeMessage,
      mocks.inspectTurn,
      mocks.notify,
    ].forEach((mock) => mock.mockReset());

    mocks.listThreads.mockResolvedValue([thread]);
    mocks.transcript.mockResolvedValue({ messages: [], turns: [], processing: [] });
    mocks.conversationAvailability.mockResolvedValue(readyAvailability);
    mocks.createThread.mockResolvedValue(thread);
    mocks.deleteThread.mockResolvedValue({
      deletion_id: "deletion_1",
      thread_id: thread.thread_id,
      owner_id: owner.owner_id,
      deleted_at: "2026-08-19T12:00:00Z",
      active_data_deleted: true,
      backup_expiry_state: "unknown",
    });
    mocks.postMessage.mockResolvedValue(replyFor("What should I consider?"));
    mocks.context = {
      api: {
        listThreads: mocks.listThreads,
        createThread: mocks.createThread,
        deleteThread: mocks.deleteThread,
        transcript: mocks.transcript,
        conversationAvailability: mocks.conversationAvailability,
        postMessage: mocks.postMessage,
        correctMessage: mocks.correctMessage,
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

  it("requires fresh confirmation and explains conversation deletion limits", async () => {
    const firstRender = renderConversation();
    fireEvent.click(await screen.findByRole("button", { name: "Delete conversation" }));

    expect(mocks.unlock).toHaveBeenCalledWith(expect.stringMatching(/permanently deleting/i));
    expect(screen.queryByRole("dialog", { name: "Delete this conversation?" })).not.toBeInTheDocument();
    expect(mocks.deleteThread).not.toHaveBeenCalled();
    firstRender.unmount();

    mocks.context = { ...mocks.context, canUseSensitiveControls: true };
    mocks.listThreads
      .mockResolvedValueOnce([thread])
      .mockResolvedValueOnce([]);
    renderConversation();
    fireEvent.click(await screen.findByRole("button", { name: "Delete conversation" }));

    const dialog = screen.getByRole("dialog", { name: "Delete this conversation?" });
    expect(dialog).toHaveTextContent(/backups may retain an older copy/i);
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete conversation" }));

    await waitFor(() => expect(mocks.deleteThread).toHaveBeenCalledWith(thread.thread_id));
    await waitFor(() => expect(mocks.notify).toHaveBeenCalledWith(
      "Conversation deleted from active data. Backup expiry is not verified.",
      "success",
    ));
  });

  it("corrects owner wording and hides the superseded exchange", async () => {
    const originalOwner = message(
      "message_original_owner",
      owner.owner_id,
      "My sister arrives Tuesday.",
    );
    const originalAnswer = {
      ...message("message_original_melli", "melli_1", "I will plan around Tuesday."),
      reply_to_message_id: originalOwner.message_id,
    };
    const correctedOwner = {
      ...message(
        "message_corrected_owner",
        owner.owner_id,
        "My sister arrives Thursday.",
      ),
      corrects_message_id: originalOwner.message_id,
    };
    const correctedAnswer = {
      ...message("message_corrected_melli", "melli_1", "I will plan around Thursday."),
      reply_to_message_id: correctedOwner.message_id,
    };
    mocks.transcript.mockResolvedValue({
      messages: [originalOwner, originalAnswer],
      turns: [],
      processing: [],
    });
    mocks.correctMessage.mockResolvedValue({
      inbound_message: correctedOwner,
      output_message: correctedAnswer,
      turn: null,
      processing: {
        message_id: correctedOwner.message_id,
        state: "completed",
        attempts: [],
      },
      duplicate: false,
    });
    renderConversation();

    expect(await screen.findByText("My sister arrives Tuesday.")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Correct message" }));
    const dialog = screen.getByRole("dialog", { name: "Correct your message" });
    expect(within(dialog).getByLabelText("Corrected message")).toHaveValue(
      "My sister arrives Tuesday.",
    );
    expect(within(dialog).getByText(/remains in correction history/i)).toBeVisible();
    expect(within(dialog).getByRole("button", { name: "Save correction" })).toBeDisabled();

    fireEvent.change(within(dialog).getByLabelText("Corrected message"), {
      target: { value: "My sister arrives Thursday." },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save correction" }));

    await waitFor(() => expect(mocks.correctMessage).toHaveBeenCalledWith(
      thread.thread_id,
      originalOwner.message_id,
      "My sister arrives Thursday.",
      expect.any(String),
    ));
    expect(await screen.findByText("My sister arrives Thursday.")).toBeVisible();
    expect(screen.getByText("I will plan around Thursday.")).toBeVisible();
    expect(screen.getByText("Corrected")).toBeVisible();
    expect(screen.queryByText("My sister arrives Tuesday.")).not.toBeInTheDocument();
    expect(screen.queryByText("I will plan around Tuesday.")).not.toBeInTheDocument();
    expect(mocks.transcript).toHaveBeenCalledOnce();
    expect(mocks.notify).toHaveBeenCalledWith("Message corrected.", "success");
  });

  it("removes the fixed response from the owner path when no capable model exists", async () => {
    mocks.conversationAvailability.mockResolvedValue({ available: false });
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

  it("warns as soon as a failed external attempt is waiting to retry", async () => {
    const ownerMessage = message("message_external", owner.owner_id, "Use my saved context");
    const failedAttempt = failedExternalAttempt(
      1,
      ["memory_one", "memory_two"],
    );
    mocks.transcript.mockResolvedValue({
      messages: [ownerMessage],
      turns: [],
      processing: [processingStatus(ownerMessage.message_id, "ready", [failedAttempt])],
    });
    renderConversation();

    const warning = await screen.findByRole("alert");
    expect(warning).toHaveTextContent("External model attempt failed");
    expect(warning).toHaveTextContent(
      "Your message and 2 saved memories may have reached Acme Cloud (reasoner-v2).",
    );
    expect(warning).toHaveTextContent("No usable answer was recorded from this attempt.");
    expect(screen.getByText("Melli is thinking…")).toBeVisible();
  });

  it("keeps every failed external disclosure visible after a later answer succeeds", async () => {
    const ownerMessage = message("message_external", owner.owner_id, "Try another model");
    const melliMessage = message("message_external_answer", "melli_1", "Recovered answer");
    const firstFailure = failedExternalAttempt(1, ["memory_one"]);
    const secondFailure = {
      ...failedExternalAttempt(2, [], "result"),
      outcome: "dead" as const,
      retry_at: null,
    };
    const success: ConversationProcessingAttempt = {
      ...failedExternalAttempt(3, []),
      attempt_id: "attempt_3",
      request_id: "request_3",
      outcome: "succeeded",
      error_code: null,
      retry_at: null,
      model_result_summary: {
        provider_id: "provider.recovery-cloud",
        model_id: "reasoner-v4",
        processing_location: "approved_provider",
        result_id: "result_3",
        request_id: "request_3",
        input_tokens: 20,
        output_tokens: 10,
        cost_gbp: 0.01,
        started_at: "2026-08-19T12:02:00Z",
        completed_at: "2026-08-19T12:02:01Z",
        external_disclosure: true,
      },
      failed_model_target: null,
    };
    mocks.transcript.mockResolvedValue({
      messages: [ownerMessage, melliMessage],
      turns: [],
      processing: [processingStatus(
        ownerMessage.message_id,
        "completed",
        [firstFailure, secondFailure, success],
      )],
    });
    renderConversation();

    expect(await screen.findByText("Recovered answer")).toBeVisible();
    const warning = screen.getByRole("alert");
    expect(warning).toHaveTextContent("2 external model attempts failed");
    expect(warning).toHaveTextContent("Attempt 1");
    expect(warning).toHaveTextContent("Attempt 2");
    expect(warning).toHaveTextContent("Acme Cloud (reasoner-v2)");
    expect(warning).toHaveTextContent("Second Cloud (reasoner-v3)");
    expect(warning).toHaveTextContent("No usable answer was recorded from these attempts.");
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

  it("keeps the destination thread stable when a send finishes elsewhere", async () => {
    const pendingSend = deferred<ReturnType<typeof replyFor>>();
    mocks.listThreads.mockResolvedValue([thread, secondThread]);
    mocks.transcript.mockImplementation((selectedId: string) => Promise.resolve({
      messages: selectedId === secondThread.thread_id
        ? [message("message_second", owner.owner_id, "Plan a museum day.", secondThread.thread_id)]
        : [],
      turns: [],
      processing: [],
    }));
    mocks.postMessage.mockReturnValue(pendingSend.promise);
    renderConversation();

    const composer = await screen.findByLabelText("Message Melli");
    fireEvent.change(composer, { target: { value: "A message for the first thread" } });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    await waitFor(() => expect(mocks.postMessage).toHaveBeenCalledOnce());

    fireEvent.click(screen.getByRole("button", { name: /A family visit/ }));
    expect(await screen.findByText("Plan a museum day.")).toBeVisible();
    expect(screen.getByRole("heading", { name: secondThread.title })).toBeVisible();

    await act(async () => pendingSend.resolve(replyFor(
      "A message for the first thread",
      thread.thread_id,
    )));
    expect(screen.getByRole("heading", { name: secondThread.title })).toBeVisible();
    expect(screen.getByText("Plan a museum day.")).toBeVisible();
    expect(screen.queryByText("Opening this conversation")).not.toBeInTheDocument();
    expect(mocks.transcript.mock.calls.filter(([selectedId]) => selectedId === thread.thread_id)).toHaveLength(1);
  });

  it("keeps drafts and failed retries with the thread that owns them", async () => {
    const pendingSend = deferred<ReturnType<typeof replyFor>>();
    mocks.listThreads.mockResolvedValue([thread, secondThread]);
    mocks.transcript.mockResolvedValue({ messages: [], turns: [], processing: [] });
    mocks.postMessage.mockReturnValue(pendingSend.promise);
    renderConversation();

    const firstComposer = await screen.findByLabelText("Message Melli");
    fireEvent.change(firstComposer, { target: { value: "First-thread draft" } });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    await waitFor(() => expect(mocks.postMessage).toHaveBeenCalledOnce());

    fireEvent.click(screen.getByRole("button", { name: /A family visit/ }));
    const secondComposer = await screen.findByLabelText("Message Melli");
    fireEvent.change(secondComposer, { target: { value: "Second-thread draft" } });
    await act(async () => pendingSend.reject(new Error("The private model did not respond.")));

    expect(secondComposer).toHaveValue("Second-thread draft");
    expect(screen.queryByRole("alert", { name: /Message not sent/ })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /A meaningful decision/ }));
    expect(await screen.findByLabelText("Message Melli")).toHaveValue("First-thread draft");
    expect(await screen.findByText("Message not sent")).toBeVisible();
  });

  it("keeps thread-list and transcript failures isolated", async () => {
    const pendingThreads = deferred<typeof thread[]>();
    mocks.listThreads.mockReturnValue(pendingThreads.promise);
    mocks.transcript.mockRejectedValue(new Error("Transcript unavailable"));
    renderConversation();

    expect(await screen.findByRole("heading", { name: "This conversation could not be opened" })).toBeVisible();
    await act(async () => pendingThreads.resolve([thread]));
    expect(screen.getByRole("heading", { name: "This conversation could not be opened" })).toBeVisible();
    expect(screen.getByText("Transcript unavailable")).toBeVisible();
  });

  it("keeps a valid transcript visible when the thread list fails", async () => {
    mocks.listThreads.mockRejectedValue(new Error("Thread list unavailable"));
    mocks.transcript.mockResolvedValue({
      messages: [message("message_valid", owner.owner_id, "Visible transcript")],
      turns: [],
      processing: [],
    });
    renderConversation();

    expect(await screen.findByText("Visible transcript")).toBeVisible();
    expect(screen.getByText("Thread list unavailable")).toBeVisible();
    expect(screen.queryByRole("heading", { name: "This conversation could not be opened" })).not.toBeInTheDocument();
  });

  it("uses the authoritative resume response without a fragile follow-up read", async () => {
    const failedOwnerMessage = message("message_failed", owner.owner_id, "Please recover this");
    mocks.transcript.mockResolvedValue({
      messages: [failedOwnerMessage],
      turns: [],
      processing: [{
        message_id: failedOwnerMessage.message_id,
        state: "dead",
        attempts: [],
      }],
    });
    mocks.resumeMessage.mockResolvedValue({
      inbound_message: failedOwnerMessage,
      output_message: message("message_recovered", "melli_1", "Recovered answer"),
      turn: null,
      processing: {
        message_id: failedOwnerMessage.message_id,
        state: "completed",
        attempts: [],
      },
      duplicate: false,
    });
    renderConversation();

    fireEvent.click(await screen.findByRole("button", { name: "Try again" }));
    expect(await screen.findByText("Recovered answer")).toBeVisible();
    expect(screen.queryByText("Melli could not answer this time.")).not.toBeInTheDocument();
    expect(mocks.transcript).toHaveBeenCalledOnce();
  });

  it("serializes slow transcript polling and resumes after the slow read", async () => {
    const initialTranscript = deferred<{
      messages: ReturnType<typeof message>[];
      turns: never[];
      processing: { message_id: string; state: string; attempts: never[] }[];
    }>();
    const slowPoll = deferred<{
      messages: ReturnType<typeof message>[];
      turns: never[];
      processing: { message_id: string; state: string; attempts: never[] }[];
    }>();
    const ownerMessage = message("message_pending", owner.owner_id, "Still working?");
    const pendingTranscript = {
      messages: [ownerMessage],
      turns: [] as never[],
      processing: [{ message_id: ownerMessage.message_id, state: "accepted", attempts: [] as never[] }],
    };
    mocks.transcript
      .mockReturnValueOnce(initialTranscript.promise)
      .mockReturnValueOnce(slowPoll.promise)
      .mockResolvedValueOnce({ messages: [ownerMessage], turns: [], processing: [] });
    renderConversation();

    await waitFor(() => expect(mocks.transcript).toHaveBeenCalledOnce());
    vi.useFakeTimers();
    try {
      await act(async () => initialTranscript.resolve(pendingTranscript));
      await act(async () => vi.advanceTimersByTimeAsync(1_500));
      expect(mocks.transcript).toHaveBeenCalledTimes(2);

      await act(async () => vi.advanceTimersByTimeAsync(6_000));
      expect(mocks.transcript).toHaveBeenCalledTimes(2);

      await act(async () => slowPoll.resolve(pendingTranscript));
      await act(async () => vi.advanceTimersByTimeAsync(1_499));
      expect(mocks.transcript).toHaveBeenCalledTimes(2);
      await act(async () => vi.advanceTimersByTimeAsync(1));
      expect(mocks.transcript).toHaveBeenCalledTimes(3);
    } finally {
      vi.useRealTimers();
    }
  });

  it("discards late answer inspections after close and navigation", async () => {
    const closedInspection = deferred<Record<string, unknown>>();
    const navigatedInspection = deferred<Record<string, unknown>>();
    const ownerMessage = message("message_inspection_owner", owner.owner_id, "What matters here?");
    const melliMessage = message("message_inspection_melli", "melli_1", "Consider your constraints.");
    const turn = {
      turn_id: "turn_inspection",
      thread_id: thread.thread_id,
      triggering_message_ids: [ownerMessage.message_id],
      evidence_ids: [],
      model_run_ids: ["result_inspection"],
      output_message_ids: [melliMessage.message_id],
      decision_record: { summary: "Late inspection summary" },
      started_at: "2026-08-19T12:00:00Z",
      completed_at: "2026-08-19T12:00:01Z",
    };
    const inspection = {
      turn,
      output_message: melliMessage,
      retrieval_manifest: { citations: [] },
      model_result: {
        provider_id: "provider.local",
        model_id: "capable-local-model",
        processing_location: "device",
        external_disclosure: false,
        started_at: "2026-08-19T12:00:00Z",
        completed_at: "2026-08-19T12:00:01Z",
      },
    };
    mocks.listThreads.mockResolvedValue([thread, secondThread]);
    mocks.transcript.mockImplementation((selectedId: string) => Promise.resolve(
      selectedId === thread.thread_id
        ? { messages: [ownerMessage, melliMessage], turns: [turn], processing: [] }
        : { messages: [], turns: [], processing: [] },
    ));
    mocks.inspectTurn
      .mockReturnValueOnce(closedInspection.promise)
      .mockReturnValueOnce(navigatedInspection.promise);
    renderConversation();

    fireEvent.click(await screen.findByRole("button", { name: "Why this answer?" }));
    fireEvent.click(screen.getByRole("button", { name: "Close dialog" }));
    await act(async () => closedInspection.resolve(inspection));
    expect(screen.queryByRole("dialog", { name: "Why this answer?" })).not.toBeInTheDocument();
    expect(screen.queryByText("Late inspection summary")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Why this answer?" }));
    fireEvent.click(screen.getByRole("button", { name: /A family visit/ }));
    expect(await screen.findByRole("heading", { name: secondThread.title })).toBeVisible();
    await act(async () => navigatedInspection.resolve(inspection));
    expect(screen.queryByRole("dialog", { name: "Why this answer?" })).not.toBeInTheDocument();
    expect(screen.queryByText("Late inspection summary")).not.toBeInTheDocument();
  });

  it("does not let a delayed create steal newer navigation", async () => {
    const pendingCreate = deferred<typeof thread>();
    mocks.listThreads.mockResolvedValue([thread, secondThread]);
    mocks.createThread.mockReturnValue(pendingCreate.promise);
    renderConversation();

    fireEvent.click(await screen.findByRole("button", { name: "Start a new conversation" }));
    await waitFor(() => expect(mocks.createThread).toHaveBeenCalledOnce());
    fireEvent.click(screen.getByRole("button", { name: /A family visit/ }));
    expect(await screen.findByRole("heading", { name: secondThread.title })).toBeVisible();

    await act(async () => pendingCreate.resolve({
      ...thread,
      thread_id: "thread_3",
      title: "New conversation",
    }));
    expect(screen.getByRole("heading", { name: secondThread.title })).toBeVisible();
  });

  it("moves and traps focus in the mobile conversation drawer", async () => {
    renderConversation();
    const toggle = await screen.findByRole("button", { name: "Open conversations" });
    toggle.focus();
    fireEvent.click(toggle);

    const drawer = screen.getByRole("dialog", { name: "Conversations" });
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    const close = screen.getByRole("button", { name: "Close conversations" });
    await waitFor(() => expect(close).toHaveFocus());

    fireEvent.keyDown(document, { key: "Tab", shiftKey: true });
    expect(screen.getByRole("button", { name: /A meaningful decision/ })).toHaveFocus();
    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "Conversations" })).not.toBeInTheDocument(),
    );
    expect(drawer).not.toHaveAttribute("aria-modal");
    expect(toggle).toHaveFocus();
    expect(toggle).toHaveAttribute("aria-expanded", "false");
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
    }));
    expect(mocks.postMessage).toHaveBeenCalledWith(
      created.thread_id,
      "Help me choose between two roles",
      expect.any(String),
    );
  });

  it("explains only useful context and privacy by default", async () => {
    const ownerMessage = message("message_1", owner.owner_id, "Use what you know about me");
    const melliMessage = {
      ...message("message_2", "melli_1", "Here is what I would prioritize."),
      citation_ids: ["citation_secret"],
    };
    const turn = {
      turn_id: "turn_secret_internal_id",
      thread_id: thread.thread_id,
      triggering_message_ids: [ownerMessage.message_id],
      evidence_ids: ["assertion_secret"],
      model_run_ids: ["result_secret_internal_id"],
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
        provider_id: "provider.local",
        model_id: "capable-local-model",
        processing_location: "device",
        external_disclosure: false,
        started_at: "2026-08-19T12:00:00Z",
        completed_at: "2026-08-19T12:00:01Z",
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
