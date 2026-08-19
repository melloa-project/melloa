import {
  type FormEvent,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  BookOpenCheck,
  CircleAlert,
  Clock3,
  LockKeyhole,
  MessageCircleMore,
  PanelLeftClose,
  PanelLeftOpen,
  Plus,
  RefreshCw,
  Send,
  ShieldCheck,
  Sparkles,
  UserRound,
} from "lucide-react";
import { useNavigate, useParams } from "react-router-dom";

import type {
  ConversationMessage,
  ConversationProcessingStatus,
  ConversationThread,
  ConversationTurn,
  ConversationTurnInspection,
} from "../api";
import { errorMessage, useMelloa } from "../app";
import { useOwnerUnlock } from "../components/layout";
import { Badge, Button, ErrorState, LoadingState, Modal } from "../components/ui";
import {
  asObjectArray,
  formatDurationMs,
  formatInstant,
  messageBody,
  readString,
  titleCase,
  turnMetadata,
} from "../lib/format";

const terminalProcessingStates = new Set(["completed", "dead", "cancelled"]);

const starterPrompts = [
  "Help me think through a decision I’m facing.",
  "I want to make progress on something important.",
  "Help me untangle what has been on my mind.",
] as const;

type ModelAvailability = "checking" | "ready" | "unavailable";

export function ConversationPage() {
  const { api, principal, canWrite, notify } = useMelloa();
  const openUnlock = useOwnerUnlock();
  const navigate = useNavigate();
  const { threadId } = useParams();
  const composerRef = useRef<HTMLTextAreaElement | null>(null);
  const composerFormRef = useRef<HTMLFormElement | null>(null);
  const conversationScrollRef = useRef<HTMLDivElement | null>(null);
  const shouldFollowConversationRef = useRef(true);
  const conversationRequestRef = useRef(0);
  const [threads, setThreads] = useState<readonly ConversationThread[]>([]);
  const [threadsLoading, setThreadsLoading] = useState(true);
  const [messages, setMessages] = useState<readonly ConversationMessage[]>([]);
  const [turns, setTurns] = useState<readonly ConversationTurn[]>([]);
  const [processing, setProcessing] = useState<readonly ConversationProcessingStatus[]>([]);
  const [transcriptThreadId, setTranscriptThreadId] = useState<string | null>(null);
  const [optimisticMessage, setOptimisticMessage] = useState<ConversationMessage | null>(null);
  const [conversationLoading, setConversationLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [sendFailure, setSendFailure] = useState<string | null>(null);
  const [retrySend, setRetrySend] = useState<{
    readonly text: string;
    readonly idempotencyKey: string;
  } | null>(null);
  const [sending, setSending] = useState(false);
  const [creating, setCreating] = useState(false);
  const [modelAvailability, setModelAvailability] = useState<ModelAvailability>("checking");
  const [threadPanelOpen, setThreadPanelOpen] = useState(false);
  const [inspection, setInspection] = useState<ConversationTurnInspection | null>(null);
  const [inspectionLoading, setInspectionLoading] = useState(false);

  const selectedThread = threads.find((thread) => thread.thread_id === threadId) ?? null;
  const transcriptIsCurrent = transcriptThreadId === (threadId ?? null);
  const visibleMessages = transcriptIsCurrent ? messages : [];
  const visibleTurns = transcriptIsCurrent ? turns : [];
  const visibleProcessing = transcriptIsCurrent ? processing : [];
  const displayedMessages = optimisticMessage !== null && optimisticMessage.thread_id === threadId
    ? [...visibleMessages, optimisticMessage]
    : visibleMessages;
  const turnByOutputMessage = useMemo(
    () => new Map(visibleTurns.flatMap((turn) => turn.output_message_ids.map((id) => [id, turn] as const))),
    [visibleTurns],
  );
  const processingByMessage = useMemo(
    () => new Map(visibleProcessing.map((status) => [status.message_id, status] as const)),
    [visibleProcessing],
  );
  const hasPendingWork = visibleProcessing.some((status) => !terminalProcessingStates.has(status.state));

  const loadThreads = useCallback(async () => {
    try {
      const next = await api.listThreads();
      setThreads(next);
      setError(null);
      return next;
    } catch (caught) {
      setError(errorMessage(caught));
      return [] as const;
    } finally {
      setThreadsLoading(false);
    }
  }, [api]);

  const checkModel = useCallback(async () => {
    setModelAvailability("checking");
    try {
      const report = await api.modelRoutes();
      const ready = report.routes.some((route) => (
        route.route_kind !== "synthetic"
        && (route.health.state === "healthy" || route.health.state === "degraded")
      ));
      setModelAvailability(ready ? "ready" : "unavailable");
    } catch {
      setModelAvailability("unavailable");
    }
  }, [api]);

  const loadConversation = useCallback(async (selectedId: string, quiet = false) => {
    const requestId = conversationRequestRef.current + 1;
    conversationRequestRef.current = requestId;
    if (!quiet) {
      setConversationLoading(true);
      setMessages([]);
      setTurns([]);
      setProcessing([]);
      setTranscriptThreadId(null);
      shouldFollowConversationRef.current = true;
    }
    try {
      const transcript = await api.transcript(selectedId);
      if (requestId !== conversationRequestRef.current) {
        return;
      }
      setMessages(transcript.messages);
      setTurns(transcript.turns);
      setProcessing(transcript.processing);
      setTranscriptThreadId(selectedId);
      setError(null);
    } catch (caught) {
      if (requestId !== conversationRequestRef.current) {
        return;
      }
      if (!quiet) {
        setMessages([]);
        setTurns([]);
        setProcessing([]);
        setTranscriptThreadId(selectedId);
        setError(errorMessage(caught));
      }
    } finally {
      if (requestId === conversationRequestRef.current) {
        setConversationLoading(false);
      }
    }
  }, [api]);

  useEffect(() => {
    void Promise.all([loadThreads(), checkModel()]);
  }, [checkModel, loadThreads]);

  useEffect(() => {
    if (threadsLoading || threadId !== undefined || threads.length === 0) {
      return;
    }
    navigate(`/conversation/${threads[0]?.thread_id}`, { replace: true });
  }, [navigate, threadId, threads, threadsLoading]);

  useEffect(() => {
    if (threadId === undefined) {
      conversationRequestRef.current += 1;
      setMessages([]);
      setTurns([]);
      setProcessing([]);
      setTranscriptThreadId(null);
      return;
    }
    void loadConversation(threadId);
  }, [loadConversation, threadId]);

  useEffect(() => {
    if (threadId === undefined || !hasPendingWork) {
      return;
    }
    const timer = window.setInterval(() => void loadConversation(threadId, true), 1_500);
    return () => window.clearInterval(timer);
  }, [hasPendingWork, loadConversation, threadId]);

  useLayoutEffect(() => {
    const textarea = composerRef.current;
    if (textarea === null) {
      return;
    }
    textarea.style.height = "auto";
    const height = Math.min(Math.max(textarea.scrollHeight, 43), 180);
    textarea.style.height = `${height}px`;
    textarea.style.overflowY = textarea.scrollHeight > 180 ? "auto" : "hidden";
  }, [draft]);

  useLayoutEffect(() => {
    const container = conversationScrollRef.current;
    if (container === null || (!shouldFollowConversationRef.current && !sending)) {
      return;
    }
    container.scrollTop = container.scrollHeight;
  }, [displayedMessages, sending, visibleProcessing]);

  useEffect(() => {
    if (!threadPanelOpen) {
      return;
    }
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setThreadPanelOpen(false);
      }
    };
    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [threadPanelOpen]);

  async function createConversation(title = "New conversation") {
    if (!canWrite) {
      openUnlock("Confirm owner access once to start writing. Ordinary conversation will stay unlocked for this browser session.");
      return null;
    }
    setCreating(true);
    try {
      const created = await api.createThread({
        title,
        sensitivity: "personal",
        retention_policy: "retention.owner-conversation",
      });
      await loadThreads();
      navigate(`/conversation/${created.thread_id}`);
      setThreadPanelOpen(false);
      window.setTimeout(() => composerRef.current?.focus(), 0);
      return created;
    } catch (caught) {
      notify(errorMessage(caught), "error");
      return null;
    } finally {
      setCreating(false);
    }
  }

  async function sendMessage(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const text = draft.trim();
    if (text.length === 0 || sending || modelAvailability !== "ready") {
      return;
    }
    if (!canWrite) {
      openUnlock("Confirm owner access once to keep talking with Melli in this browser session.");
      return;
    }

    setSending(true);
    setSendFailure(null);
    const idempotencyKey = retrySend?.text === text
      ? retrySend.idempotencyKey
      : crypto.randomUUID();
    setRetrySend(null);
    try {
      const activeThread = threadId === undefined
        ? await createConversation(titleFromMessage(text))
        : selectedThread;
      if (activeThread === null) {
        setRetrySend({ text, idempotencyKey });
        setSendFailure("Your message was not sent. It is still in the composer.");
        return;
      }
      setDraft("");
      shouldFollowConversationRef.current = true;
      setOptimisticMessage(optimisticOwnerMessage(
        activeThread.thread_id,
        principal.owner_id,
        text,
        idempotencyKey,
      ));
      const reply = await api.postMessage(activeThread.thread_id, text, idempotencyKey);
      setMessages((current) => mergeById(
        transcriptThreadId === activeThread.thread_id ? current : [],
        [reply.inbound_message, reply.output_message].filter(
          (message): message is ConversationMessage => message != null,
        ),
        (message) => message.message_id,
      ));
      setTurns((current) => mergeById(
        transcriptThreadId === activeThread.thread_id ? current : [],
        reply.turn == null ? [] : [reply.turn],
        (turn) => turn.turn_id,
      ));
      setProcessing((current) => mergeById(
        transcriptThreadId === activeThread.thread_id ? current : [],
        [reply.processing],
        (status) => status.message_id,
      ));
      setTranscriptThreadId(activeThread.thread_id);
      setOptimisticMessage(null);
      await Promise.all([loadThreads(), loadConversation(activeThread.thread_id, true)]);
      if (reply.processing.state === "dead") {
        notify("Melli could not answer. You can try this message again.", "error");
      }
    } catch (caught) {
      setOptimisticMessage(null);
      setDraft(text);
      setRetrySend({ text, idempotencyKey });
      setSendFailure(errorMessage(caught));
    } finally {
      setSending(false);
    }
  }

  async function resumeMessage(status: ConversationProcessingStatus) {
    if (threadId === undefined) {
      return;
    }
    if (!canWrite) {
      openUnlock("Confirm owner access to retry this message.");
      return;
    }
    try {
      await api.resumeMessage(threadId, status.message_id);
      await loadConversation(threadId, true);
    } catch (caught) {
      notify(errorMessage(caught), "error");
    }
  }

  async function explainTurn(turn: ConversationTurn) {
    if (threadId === undefined) {
      return;
    }
    setInspection(null);
    setInspectionLoading(true);
    try {
      setInspection(await api.inspectTurn(threadId, turn.turn_id));
    } catch (caught) {
      notify(errorMessage(caught), "error");
    } finally {
      setInspectionLoading(false);
    }
  }

  const unavailable = modelAvailability === "unavailable";

  return (
    <div className={`conversation-workspace ${threadPanelOpen ? "threads-open" : ""}`}>
      <aside className="thread-panel" aria-label="Conversations">
        <div className="thread-panel-heading">
          <span>Conversations</span>
          <Button
            aria-label="Start a new conversation"
            loading={creating}
            onClick={() => void createConversation()}
            size="icon"
            tone="ghost"
          >
            <Plus aria-hidden="true" size={18} />
          </Button>
        </div>
        <div className="thread-list">
          {threadsLoading ? <LoadingState label="Opening conversations" /> : null}
          {threads.map((thread) => (
            <button
              className={thread.thread_id === threadId ? "thread-button active" : "thread-button"}
              key={thread.thread_id}
              onClick={() => {
                navigate(`/conversation/${thread.thread_id}`);
                setThreadPanelOpen(false);
              }}
              type="button"
            >
              <MessageCircleMore aria-hidden="true" size={17} />
              <span><strong>{thread.title}</strong><small>{formatInstant(thread.updated_at)}</small></span>
            </button>
          ))}
          {!threadsLoading && threads.length === 0 ? (
            <p className="thread-empty">Your conversations will stay together here.</p>
          ) : null}
        </div>
        <p className="thread-privacy"><ShieldCheck aria-hidden="true" size={14} /> Private owner history</p>
      </aside>

      <section className="conversation-stage">
        <header className="conversation-heading">
          <Button
            aria-label={threadPanelOpen ? "Close conversations" : "Open conversations"}
            className="thread-panel-toggle"
            onClick={() => setThreadPanelOpen((open) => !open)}
            size="icon"
            tone="ghost"
          >
            {threadPanelOpen ? <PanelLeftClose size={19} /> : <PanelLeftOpen size={19} />}
          </Button>
          <div>
            <h1>{selectedThread?.title ?? "Talk with Melli"}</h1>
            <p>{hasPendingWork ? "Melli is thinking…" : "A private conversation that can continue over time"}</p>
          </div>
          {hasPendingWork ? <Badge tone="info"><Clock3 className="spin-slow" size={13} /> Thinking</Badge> : null}
        </header>

        <div
          className="conversation-scroll"
          onScroll={(event) => {
            const element = event.currentTarget;
            shouldFollowConversationRef.current = (
              element.scrollHeight - element.scrollTop - element.clientHeight < 120
            );
          }}
          ref={conversationScrollRef}
        >
          {conversationLoading || !transcriptIsCurrent ? <LoadingState label="Opening this conversation" /> : null}
          {error === null ? null : (
            <ErrorState
              action={threadId === undefined ? undefined : (
                <Button onClick={() => void loadConversation(threadId)}><RefreshCw size={15} /> Try again</Button>
              )}
              message={error}
              title="This conversation could not be opened"
            />
          )}

          {!conversationLoading && transcriptIsCurrent && error === null && displayedMessages.length === 0 ? (
            <ConversationWelcome
              availability={modelAvailability}
              onRetryModel={() => void checkModel()}
              onSelectPrompt={(prompt) => {
                setDraft(prompt);
                composerRef.current?.focus();
              }}
            />
          ) : null}

          <div className="message-list">
            {displayedMessages.map((message) => {
              const ownerMessage = message.author_principal_id === principal.owner_id;
              const turn = turnByOutputMessage.get(message.message_id);
              const status = ownerMessage ? processingByMessage.get(message.message_id) : undefined;
              return (
                <article className={`chat-message ${ownerMessage ? "owner-message" : "melli-message"}`} key={message.message_id}>
                  <span className="message-avatar" aria-hidden="true">
                    {ownerMessage ? <UserRound size={17} /> : <Sparkles size={17} />}
                  </span>
                  <div className="message-bubble">
                    <div className="message-meta">
                      <strong>{ownerMessage ? "You" : "Melli"}</strong>
                      <time dateTime={message.created_at}>{formatInstant(message.created_at)}</time>
                    </div>
                    <p>{messageBody(message)}</p>
                    {!ownerMessage && turn !== undefined ? (
                      <button className="why-button" onClick={() => void explainTurn(turn)} type="button">
                        Why this answer?
                      </button>
                    ) : null}
                    {status?.state === "dead" ? (
                      <div className="message-recovery" role="status">
                        <CircleAlert size={15} />
                        <span>Melli could not answer this time.</span>
                        <Button onClick={() => void resumeMessage(status)} size="sm" tone="ghost">Try again</Button>
                      </div>
                    ) : null}
                  </div>
                </article>
              );
            })}
            {sending ? (
              <article className="chat-message melli-message thinking-message" role="status">
                <span className="message-avatar" aria-hidden="true"><Sparkles size={17} /></span>
                <div className="message-bubble"><span /><span /><span /><em>Melli is thinking</em></div>
              </article>
            ) : null}
          </div>
        </div>

        <div className="composer-wrap">
          {unavailable ? (
            <p className="composer-unavailable"><LockKeyhole size={14} /> Connect a capable model before sending a message.</p>
          ) : null}
          {sendFailure === null ? null : (
            <div className="composer-error" role="alert">
              <CircleAlert aria-hidden="true" size={16} />
              <div><strong>Message not sent</strong><span>{sendFailure} Your text is still here.</span></div>
              <Button onClick={() => composerFormRef.current?.requestSubmit()} size="sm" type="button">Try again</Button>
              <Button aria-label="Dismiss send error" onClick={() => setSendFailure(null)} size="icon" tone="ghost" type="button">×</Button>
            </div>
          )}
          <form className="composer" onSubmit={(event) => void sendMessage(event)} ref={composerFormRef}>
            <textarea
              aria-label="Message Melli"
              disabled={modelAvailability !== "ready"}
              maxLength={100_000}
              onChange={(event) => {
                const nextDraft = event.target.value;
                setDraft(nextDraft);
                if (retrySend !== null && nextDraft.trim() !== retrySend.text) {
                  setRetrySend(null);
                  setSendFailure(null);
                }
              }}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
                  event.preventDefault();
                  event.currentTarget.form?.requestSubmit();
                }
              }}
              placeholder={modelAvailability === "ready" ? "Message Melli…" : "Melli is not connected yet"}
              ref={composerRef}
              rows={1}
              value={draft}
            />
            <Button
              disabled={draft.trim().length === 0 || modelAvailability !== "ready"}
              loading={sending}
              size="icon"
              tone="primary"
              type="submit"
            >
              <Send aria-hidden="true" size={17} /><span className="sr-only">Send message</span>
            </Button>
          </form>
          <p className="composer-hint">Enter to send · Shift + Enter for a new line</p>
        </div>
      </section>

      {threadPanelOpen ? (
        <button aria-label="Close conversations" className="thread-panel-scrim" onClick={() => setThreadPanelOpen(false)} type="button" />
      ) : null}

      <Modal
        description="The context and privacy facts that materially shaped this answer."
        onClose={() => {
          setInspection(null);
          setInspectionLoading(false);
        }}
        open={inspection !== null || inspectionLoading}
        title="Why this answer?"
      >
        {inspectionLoading ? <LoadingState label="Reading answer context" /> : null}
        {inspection === null ? null : <AnswerExplanation inspection={inspection} />}
      </Modal>
    </div>
  );
}

function ConversationWelcome({
  availability,
  onRetryModel,
  onSelectPrompt,
}: {
  readonly availability: ModelAvailability;
  readonly onRetryModel: () => void;
  readonly onSelectPrompt: (prompt: string) => void;
}) {
  if (availability === "checking") {
    return <div className="conversation-welcome"><LoadingState label="Connecting Melli" /></div>;
  }
  if (availability === "unavailable") {
    return (
      <div className="conversation-welcome unavailable-welcome">
        <span className="welcome-mark"><Sparkles size={24} /></span>
        <h2>Melli isn’t connected yet</h2>
        <p>A private model connection needs attention before Melli can answer. Once it is ready, check again here.</p>
        <Button onClick={onRetryModel}><RefreshCw size={15} /> Check again</Button>
      </div>
    );
  }
  return (
    <div className="conversation-welcome">
      <span className="welcome-mark"><Sparkles size={24} /></span>
      <h2>What would be useful to think through?</h2>
      <p>Start naturally. Melli should do the work of understanding the context.</p>
      <div className="starter-list">
        {starterPrompts.map((prompt) => (
          <button key={prompt} onClick={() => onSelectPrompt(prompt)} type="button">{prompt}</button>
        ))}
      </div>
    </div>
  );
}

function AnswerExplanation({ inspection }: { readonly inspection: ConversationTurnInspection }) {
  const metadata = turnMetadata(inspection);
  const citations = asObjectArray(inspection.retrieval_manifest.citations);
  const summary = readString(inspection.turn.decision_record, "summary");
  const local = !metadata.externalDisclosure;
  return (
    <div className="answer-explanation">
      <section>
        <span className="explanation-icon"><BookOpenCheck size={18} /></span>
        <div>
          <h3>Context</h3>
          <p>{citations.length === 0
            ? "No saved memories were used for this answer."
            : `Melli used ${citations.length} saved ${citations.length === 1 ? "memory" : "memories"}.`}</p>
        </div>
      </section>
      <section>
        <span className="explanation-icon"><ShieldCheck size={18} /></span>
        <div>
          <h3>Privacy</h3>
          <p>{local
            ? `Processed ${plainLocation(metadata.location)} without external disclosure.`
            : "Context was disclosed to an approved external model for this answer."}</p>
        </div>
      </section>
      {summary === "unknown" ? null : (
        <section>
          <span className="explanation-icon"><MessageCircleMore size={18} /></span>
          <div><h3>Reason</h3><p>{summary}</p></div>
        </section>
      )}
      <details className="technical-details">
        <summary>Technical details</summary>
        <dl>
          <div><dt>Model</dt><dd>{metadata.modelId}</dd></div>
          <div><dt>Location</dt><dd>{titleCase(metadata.location)}</dd></div>
          <div><dt>Response time</dt><dd>{formatDurationMs(metadata.latencyMs)}</dd></div>
        </dl>
      </details>
    </div>
  );
}

function titleFromMessage(message: string): string {
  const firstLine = message.split("\n", 1)[0]?.trim() ?? "";
  if (firstLine.length <= 52) {
    return firstLine.length > 0 ? firstLine : "New conversation";
  }
  return `${firstLine.slice(0, 49).trimEnd()}…`;
}

function plainLocation(value: string): string {
  if (value === "device") {
    return "on this device";
  }
  if (value === "private_network") {
    return "on the private network";
  }
  return "within the configured private boundary";
}

function optimisticOwnerMessage(
  threadId: string,
  ownerId: string,
  text: string,
  idempotencyKey: string,
): ConversationMessage {
  const now = new Date().toISOString();
  return {
    message_id: `optimistic-${idempotencyKey}`,
    thread_id: threadId,
    author_principal_id: ownerId,
    source_client: "owner-console",
    parts: [{ kind: "text", text }],
    citation_ids: [],
    delivery_state: "recorded",
    sensitivity: "personal",
    created_at: now,
    observed_at: now,
  };
}

function mergeById<T>(
  current: readonly T[],
  additions: readonly T[],
  identify: (item: T) => string,
): readonly T[] {
  const merged = new Map(current.map((item) => [identify(item), item]));
  for (const item of additions) {
    merged.set(identify(item), item);
  }
  return [...merged.values()];
}
