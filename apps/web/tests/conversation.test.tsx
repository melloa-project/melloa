import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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

const readyRoutes = {
  routes: [{
    route_kind: "openai_compatible",
    health: { state: "healthy" },
  }],
};

function message(id: string, author: string, text: string) {
  return {
    message_id: id,
    thread_id: thread.thread_id,
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
    mocks.postMessage.mockResolvedValue({
      processing: { state: "completed" },
      output_message: message("message_2", "melli_1", "A useful answer"),
    });
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

    expect(await screen.findByRole("heading", { name: "Melli needs a capable model" })).toBeVisible();
    expect(screen.getByText(/old fixed tour has been removed/i)).toBeVisible();
    expect(screen.getByLabelText("Message Melli")).toBeDisabled();
    expect(screen.queryByRole("button", { name: /Fill a no-network/i })).not.toBeInTheDocument();
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
