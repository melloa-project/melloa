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
  Pencil,
  Plus,
  RefreshCw,
  Send,
  ShieldCheck,
  Sparkles,
  Trash2,
  UserRound,
} from "lucide-react";
import { useNavigate, useParams } from "react-router-dom";

import type {
  ConversationMessage,
  ConversationProcessingStatus,
  ConversationReply,
  ConversationThread,
  ConversationTranscript,
  ConversationTurn,
  ConversationTurnInspection,
} from "../api";
import { errorMessage, useMelloa } from "../app";
import { useOwnerUnlock } from "../components/layout";
import { Badge, Button, ErrorState, LoadingState, Modal } from "../components/ui";
import {
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

type ConversationView = ConversationTranscript & {
  readonly initialized: boolean;
  readonly loading: boolean;
  readonly error: string | null;
};

type FailedSend = {
  readonly text: string;
  readonly idempotencyKey: string;
  readonly message: string;
};

type OptimisticSend = {
  readonly message: ConversationMessage;
  readonly knownMessageIds: readonly string[];
};

type CorrectionDraft = {
  readonly message: ConversationMessage;
  readonly text: string;
  readonly idempotencyKey: string;
  readonly error: string | null;
};

const newConversationKey = "new-conversation";

export function ConversationPage() {
  const { api, principal, canWrite, canUseSensitiveControls, notify } = useMelloa();
  const openUnlock = useOwnerUnlock();
  const navigate = useNavigate();
  const { threadId } = useParams();
  const composerRef = useRef<HTMLTextAreaElement | null>(null);
  const composerFormRef = useRef<HTMLFormElement | null>(null);
  const conversationScrollRef = useRef<HTMLDivElement | null>(null);
  const threadPanelRef = useRef<HTMLElement | null>(null);
  const threadPanelToggleRef = useRef<HTMLButtonElement | null>(null);
  const shouldFollowConversationRef = useRef(true);
  const currentThreadIdRef = useRef<string | undefined>(threadId);
  const threadRequestRef = useRef(0);
  const conversationRequestRefs = useRef(new Map<string, number>());
  const conversationInFlightRefs = useRef(new Map<string, number>());
  const createRequestRef = useRef(0);
  const inspectionRequestRef = useRef(0);
  const deletedThreadIdsRef = useRef(new Set<string>());
  const [threads, setThreads] = useState<readonly ConversationThread[]>([]);
  const [threadsLoading, setThreadsLoading] = useState(true);
  const [threadError, setThreadError] = useState<string | null>(null);
  const [conversationViews, setConversationViews] = useState<Readonly<Record<string, ConversationView>>>({});
  const [optimisticSends, setOptimisticSends] = useState<Readonly<Record<string, OptimisticSend>>>({});
  const [drafts, setDrafts] = useState<Readonly<Record<string, string>>>({});
  const [sendFailures, setSendFailures] = useState<Readonly<Record<string, FailedSend>>>({});
  const [sendingThreadIds, setSendingThreadIds] = useState<ReadonlySet<string>>(() => new Set());
  const [resumingMessageIds, setResumingMessageIds] = useState<ReadonlySet<string>>(() => new Set());
  const [creating, setCreating] = useState(false);
  const [modelAvailability, setModelAvailability] = useState<ModelAvailability>("checking");
  const [threadPanelOpen, setThreadPanelOpen] = useState(false);
  const [inspection, setInspection] = useState<ConversationTurnInspection | null>(null);
  const [inspectionLoading, setInspectionLoading] = useState(false);
  const [correction, setCorrection] = useState<CorrectionDraft | null>(null);
  const [correcting, setCorrecting] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);

  currentThreadIdRef.current = threadId;
  const viewKey = threadId ?? newConversationKey;
  const selectedThread = threads.find((thread) => thread.thread_id === threadId) ?? null;
  const conversationView = threadId === undefined ? undefined : conversationViews[threadId];
  const transcriptIsCurrent = threadId === undefined || conversationView?.initialized === true;
  const visibleMessages = conversationView?.messages ?? [];
  const visibleTurns = conversationView?.turns ?? [];
  const visibleProcessing = conversationView?.processing ?? [];
  const optimisticSend = threadId === undefined ? undefined : optimisticSends[threadId];
  const optimisticRecorded = optimisticSend === undefined
    ? false
    : visibleMessages.some((message) => (
      !optimisticSend.knownMessageIds.includes(message.message_id)
      && message.author_principal_id === principal.owner_id
      && messageBody(message) === messageBody(optimisticSend.message)
    ));
  const displayedMessages = optimisticSend !== undefined && !optimisticRecorded
    ? [...visibleMessages, optimisticSend.message]
    : visibleMessages;
  const supersededMessageIds = new Set(
    displayedMessages.flatMap((message) => (
      message.corrects_message_id == null ? [] : [message.corrects_message_id]
    )),
  );
  const activeDisplayedMessages = displayedMessages.filter((message) => (
    !supersededMessageIds.has(message.message_id)
    && (
      message.reply_to_message_id == null
      || !supersededMessageIds.has(message.reply_to_message_id)
    )
  ));
  const turnByOutputMessage = useMemo(
    () => new Map(visibleTurns.flatMap((turn) => turn.output_message_ids.map((id) => [id, turn] as const))),
    [visibleTurns],
  );
  const processingByMessage = useMemo(
    () => new Map(visibleProcessing.map((status) => [status.message_id, status] as const)),
    [visibleProcessing],
  );
  const hasPendingWork = visibleProcessing.some((status) => !terminalProcessingStates.has(status.state));
  const conversationLoading = threadId !== undefined && (conversationView?.loading ?? true);
  const conversationError = conversationView?.error ?? null;
  const draft = drafts[viewKey] ?? "";
  const sendFailure = sendFailures[viewKey];
  const sending = threadId !== undefined && sendingThreadIds.has(threadId);

  const updateConversation = useCallback((
    selectedId: string,
    update: (current: ConversationView) => ConversationView,
  ) => {
    setConversationViews((current) => ({
      ...current,
      [selectedId]: update(current[selectedId] ?? emptyConversationView()),
    }));
  }, []);

  const setDraft = useCallback((key: string, value: string) => {
    setDrafts((current) => ({ ...current, [key]: value }));
  }, []);

  const invalidateConversationRequest = useCallback((selectedId: string) => {
    conversationRequestRefs.current.set(
      selectedId,
      (conversationRequestRefs.current.get(selectedId) ?? 0) + 1,
    );
    conversationInFlightRefs.current.delete(selectedId);
  }, []);

  const loadThreads = useCallback(async () => {
    const requestId = threadRequestRef.current + 1;
    threadRequestRef.current = requestId;
    try {
      const next = await api.listThreads();
      if (requestId !== threadRequestRef.current) {
        return next;
      }
      setThreads(next);
      setThreadError(null);
      return next;
    } catch (caught) {
      if (requestId === threadRequestRef.current) {
        setThreadError(errorMessage(caught));
      }
      return [] as const;
    } finally {
      if (requestId === threadRequestRef.current) {
        setThreadsLoading(false);
      }
    }
  }, [api]);

  const checkModel = useCallback(async () => {
    setModelAvailability("checking");
    try {
      const availability = await api.conversationAvailability();
      setModelAvailability(availability.available ? "ready" : "unavailable");
    } catch {
      setModelAvailability("unavailable");
    }
  }, [api]);

  const loadConversation = useCallback(async (
    selectedId: string,
    quiet = false,
  ): Promise<ConversationTranscript | null> => {
    if (quiet && conversationInFlightRefs.current.has(selectedId)) {
      return null;
    }
    const requestId = (conversationRequestRefs.current.get(selectedId) ?? 0) + 1;
    conversationRequestRefs.current.set(selectedId, requestId);
    conversationInFlightRefs.current.set(selectedId, requestId);
    if (!quiet) {
      updateConversation(selectedId, (current) => ({
        ...current,
        loading: true,
        error: null,
      }));
      shouldFollowConversationRef.current = true;
    }
    try {
      const transcript = await api.transcript(selectedId);
      if (requestId !== conversationRequestRefs.current.get(selectedId)) {
        return null;
      }
      updateConversation(selectedId, () => ({
        ...transcript,
        initialized: true,
        loading: false,
        error: null,
      }));
      return transcript;
    } catch (caught) {
      if (requestId !== conversationRequestRefs.current.get(selectedId)) {
        return null;
      }
      updateConversation(selectedId, (current) => ({
        ...current,
        initialized: true,
        loading: false,
        error: errorMessage(caught),
      }));
      return null;
    } finally {
      if (requestId === conversationInFlightRefs.current.get(selectedId)) {
        conversationInFlightRefs.current.delete(selectedId);
      }
    }
  }, [api, updateConversation]);

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
      return;
    }
    void loadConversation(threadId);
  }, [loadConversation, threadId]);

  useEffect(() => {
    if (threadId === undefined || !hasPendingWork) {
      return;
    }
    let cancelled = false;
    let timer = window.setTimeout(async function poll() {
      await loadConversation(threadId, true);
      if (!cancelled) {
        timer = window.setTimeout(poll, 1_500);
      }
    }, 1_500);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
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
  }, [activeDisplayedMessages, sending, visibleProcessing]);

  useEffect(() => {
    if (!threadPanelOpen) {
      return;
    }
    const panel = threadPanelRef.current;
    const toggle = threadPanelToggleRef.current;
    const mobile = typeof window.matchMedia !== "function"
      || window.matchMedia("(max-width: 860px)").matches;
    if (panel === null || !mobile) {
      return;
    }
    const focusable = () => [...panel.querySelectorAll<HTMLElement>(
      "a[href], button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex='-1'])",
    )].filter((element) => !element.hidden && element.getAttribute("aria-hidden") !== "true");
    (focusable()[0] ?? panel).focus();
    const manageDrawerFocus = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        setThreadPanelOpen(false);
        return;
      }
      if (event.key !== "Tab") {
        return;
      }
      const controls = focusable();
      const first = controls[0];
      const last = controls.at(-1);
      if (first === undefined || last === undefined) {
        event.preventDefault();
        panel.focus();
      } else if (event.shiftKey && (document.activeElement === first || !panel.contains(document.activeElement))) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", manageDrawerFocus);
    return () => {
      document.removeEventListener("keydown", manageDrawerFocus);
      if (toggle?.isConnected === true) {
        toggle.focus();
      }
    };
  }, [threadPanelOpen]);

  useEffect(() => {
    inspectionRequestRef.current += 1;
    setInspection(null);
    setInspectionLoading(false);
    setCorrection(null);
    setCorrecting(false);
    setDeleteOpen(false);
  }, [threadId]);

  async function createConversation(title = "New conversation", originKey = viewKey) {
    if (!canWrite) {
      openUnlock("Confirm owner access once to start writing. Ordinary conversation will stay unlocked for this browser session.");
      return null;
    }
    const requestId = createRequestRef.current + 1;
    createRequestRef.current = requestId;
    setCreating(true);
    try {
      const created = await api.createThread({
        title,
        sensitivity: "personal",
      });
      await loadThreads();
      if (
        requestId === createRequestRef.current
        && (currentThreadIdRef.current ?? newConversationKey) === originKey
      ) {
        navigate(`/conversation/${created.thread_id}`);
        setThreadPanelOpen(false);
        window.setTimeout(() => composerRef.current?.focus(), 0);
      }
      return created;
    } catch (caught) {
      notify(errorMessage(caught), "error");
      return null;
    } finally {
      if (requestId === createRequestRef.current) {
        setCreating(false);
      }
    }
  }

  async function sendMessage(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const text = draft.trim();
    const sourceKey = viewKey;
    if (text.length === 0 || sending || creating || modelAvailability !== "ready") {
      return;
    }
    if (!canWrite) {
      openUnlock("Confirm owner access once to keep talking with Melli in this browser session.");
      return;
    }

    const previousFailure = sendFailures[sourceKey];
    const idempotencyKey = previousFailure?.text === text
      ? previousFailure.idempotencyKey
      : crypto.randomUUID();
    setSendFailures((current) => withoutKey(current, sourceKey));
    let activeThreadId = threadId;
    try {
      if (activeThreadId === undefined) {
        const created = await createConversation(titleFromMessage(text), sourceKey);
        activeThreadId = created?.thread_id;
      }
      if (activeThreadId === undefined) {
        setSendFailures((current) => ({
          ...current,
          [sourceKey]: {
            text,
            idempotencyKey,
            message: "Your message was not sent. It is still in the composer.",
          },
        }));
        return;
      }
      const targetThreadId = activeThreadId;
      setSendingThreadIds((current) => new Set(current).add(targetThreadId));
      setDraft(sourceKey, "");
      setDraft(targetThreadId, "");
      shouldFollowConversationRef.current = true;
      setOptimisticSends((current) => ({
        ...current,
        [targetThreadId]: {
          message: optimisticOwnerMessage(targetThreadId, principal.owner_id, text, idempotencyKey),
          knownMessageIds: (conversationViews[targetThreadId]?.messages ?? []).map((message) => message.message_id),
        },
      }));
      const reply = await api.postMessage(targetThreadId, text, idempotencyKey);
      if (deletedThreadIdsRef.current.has(targetThreadId)) {
        return;
      }
      invalidateConversationRequest(targetThreadId);
      applyConversationReply(targetThreadId, reply, updateConversation);
      setOptimisticSends((current) => withoutKey(current, targetThreadId));
      await loadThreads();
      if (reply.processing.state === "dead") {
        notify("Melli could not answer. You can try this message again.", "error");
      }
    } catch (caught) {
      const failureKey = activeThreadId ?? sourceKey;
      if (activeThreadId !== undefined) {
        const failedThreadId = activeThreadId;
        setOptimisticSends((current) => withoutKey(current, failedThreadId));
      }
      setDraft(failureKey, text);
      setSendFailures((current) => ({
        ...current,
        [failureKey]: { text, idempotencyKey, message: errorMessage(caught) },
      }));
      if (activeThreadId !== undefined && currentThreadIdRef.current !== activeThreadId) {
        notify("A message was not sent. Return to that conversation to try again.", "error");
      }
    } finally {
      if (activeThreadId !== undefined) {
        const finishedThreadId = activeThreadId;
        setSendingThreadIds((current) => withoutSetValue(current, finishedThreadId));
      }
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
    const sourceThreadId = threadId;
    const recoveryKey = `${sourceThreadId}:${status.message_id}`;
    setResumingMessageIds((current) => new Set(current).add(recoveryKey));
    try {
      const reply = await api.resumeMessage(sourceThreadId, status.message_id);
      if (deletedThreadIdsRef.current.has(sourceThreadId)) {
        return;
      }
      invalidateConversationRequest(sourceThreadId);
      applyConversationReply(sourceThreadId, reply, updateConversation);
    } catch (caught) {
      notify(errorMessage(caught), "error");
    } finally {
      setResumingMessageIds((current) => withoutSetValue(current, recoveryKey));
    }
  }

  async function explainTurn(turn: ConversationTurn) {
    if (threadId === undefined) {
      return;
    }
    const requestId = inspectionRequestRef.current + 1;
    inspectionRequestRef.current = requestId;
    const sourceThreadId = threadId;
    setInspection(null);
    setInspectionLoading(true);
    try {
      const next = await api.inspectTurn(sourceThreadId, turn.turn_id);
      if (
        requestId === inspectionRequestRef.current
        && currentThreadIdRef.current === sourceThreadId
      ) {
        setInspection(next);
      }
    } catch (caught) {
      if (requestId === inspectionRequestRef.current) {
        notify(errorMessage(caught), "error");
      }
    } finally {
      if (requestId === inspectionRequestRef.current) {
        setInspectionLoading(false);
      }
    }
  }

  function closeInspection() {
    inspectionRequestRef.current += 1;
    setInspection(null);
    setInspectionLoading(false);
  }

  function beginCorrection(message: ConversationMessage) {
    if (!canWrite) {
      openUnlock("Confirm owner access to correct this message.");
      return;
    }
    setCorrection({
      message,
      text: messageBody(message),
      idempotencyKey: crypto.randomUUID(),
      error: null,
    });
  }

  async function submitCorrection(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (correction === null || threadId === undefined || correcting) {
      return;
    }
    const text = correction.text.trim();
    if (text.length === 0 || text === messageBody(correction.message).trim()) {
      return;
    }
    const sourceThreadId = threadId;
    const targetMessageId = correction.message.message_id;
    const idempotencyKey = correction.idempotencyKey;
    setCorrecting(true);
    setCorrection((current) => current === null ? null : { ...current, error: null });
    try {
      const reply = await api.correctMessage(
        sourceThreadId,
        targetMessageId,
        text,
        idempotencyKey,
      );
      if (deletedThreadIdsRef.current.has(sourceThreadId)) {
        return;
      }
      invalidateConversationRequest(sourceThreadId);
      applyConversationReply(sourceThreadId, reply, updateConversation);
      setCorrection(null);
      await loadThreads();
      notify("Message corrected.", "success");
    } catch (caught) {
      setCorrection((current) => (
        current === null || current.message.message_id !== targetMessageId
          ? current
          : { ...current, error: errorMessage(caught) }
      ));
    } finally {
      setCorrecting(false);
    }
  }

  function requestConversationDeletion() {
    if (selectedThread === null) {
      return;
    }
    if (!canWrite || !canUseSensitiveControls) {
      openUnlock("Confirm it’s you before permanently deleting this conversation.");
      return;
    }
    setDeleteOpen(true);
  }

  async function deleteConversation() {
    if (selectedThread === null) {
      return;
    }
    const deletedThread = selectedThread;
    setDeleting(true);
    try {
      await api.deleteThread(deletedThread.thread_id);
      deletedThreadIdsRef.current.add(deletedThread.thread_id);
      invalidateConversationRequest(deletedThread.thread_id);
      inspectionRequestRef.current += 1;
      currentThreadIdRef.current = undefined;
      setThreads((current) => current.filter(
        (thread) => thread.thread_id !== deletedThread.thread_id,
      ));
      setConversationViews((current) => withoutKey(current, deletedThread.thread_id));
      setOptimisticSends((current) => withoutKey(current, deletedThread.thread_id));
      setDrafts((current) => withoutKey(current, deletedThread.thread_id));
      setSendFailures((current) => withoutKey(current, deletedThread.thread_id));
      setSendingThreadIds((current) => withoutSetValue(current, deletedThread.thread_id));
      setDeleteOpen(false);
      setThreadPanelOpen(false);
      navigate("/conversation", { replace: true });
      await loadThreads();
      notify(
        "Conversation deleted from active data. Backup expiry is not verified.",
        "success",
      );
    } catch (caught) {
      notify(errorMessage(caught), "error");
    } finally {
      setDeleting(false);
    }
  }

  const unavailable = modelAvailability === "unavailable";

  return (
    <div className={`conversation-workspace ${threadPanelOpen ? "threads-open" : ""}`}>
      <aside
        aria-label="Conversations"
        aria-modal={threadPanelOpen ? "true" : undefined}
        className="thread-panel"
        id="conversation-drawer"
        ref={threadPanelRef}
        role={threadPanelOpen ? "dialog" : undefined}
        tabIndex={-1}
      >
        <div className="thread-panel-heading">
          <span>Conversations</span>
          <div className="thread-panel-actions">
            <Button
              aria-label="Close conversations"
              className="thread-panel-close"
              onClick={() => setThreadPanelOpen(false)}
              size="icon"
              tone="ghost"
            >
              <PanelLeftClose aria-hidden="true" size={18} />
            </Button>
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
        </div>
        <div className="thread-list">
          {threadsLoading ? <LoadingState label="Opening conversations" /> : null}
          {threadError === null ? null : (
            <div className="thread-error" role="alert">
              <span>{threadError}</span>
              <Button onClick={() => void loadThreads()} size="sm" tone="ghost">Try again</Button>
            </div>
          )}
          {threads.map((thread) => (
            <button
              aria-current={thread.thread_id === threadId ? "true" : undefined}
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

      <section className="conversation-stage" inert={threadPanelOpen ? true : undefined}>
        <header className="conversation-heading">
          <Button
            aria-controls="conversation-drawer"
            aria-expanded={threadPanelOpen}
            aria-label={threadPanelOpen ? "Conversation menu open" : "Open conversations"}
            className="thread-panel-toggle"
            onClick={() => setThreadPanelOpen((open) => !open)}
            ref={threadPanelToggleRef}
            size="icon"
            tone="ghost"
          >
            {threadPanelOpen ? <PanelLeftClose size={19} /> : <PanelLeftOpen size={19} />}
          </Button>
          <div>
            <h1>{selectedThread?.title ?? "Talk with Melli"}</h1>
            <p>{hasPendingWork || sending ? "Melli is thinking…" : "Private owner conversation"}</p>
          </div>
          {hasPendingWork || sending ? <Badge tone="info"><Clock3 className="spin-slow" size={13} /> Thinking</Badge> : null}
          {selectedThread === null ? null : (
            <Button
              aria-label="Delete conversation"
              onClick={requestConversationDeletion}
              size="icon"
              title="Delete conversation"
              tone="ghost"
            >
              <Trash2 aria-hidden="true" size={17} />
            </Button>
          )}
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
          {conversationError === null ? null : (
            <ErrorState
              action={threadId === undefined ? undefined : (
                <Button onClick={() => void loadConversation(threadId)}><RefreshCw size={15} /> Try again</Button>
              )}
              message={conversationError}
              title={visibleMessages.length === 0
                ? "This conversation could not be opened"
                : "This conversation could not be refreshed"}
            />
          )}

          {!conversationLoading && transcriptIsCurrent && conversationError === null && activeDisplayedMessages.length === 0 ? (
            <ConversationWelcome
              availability={modelAvailability}
              onRetryModel={() => void checkModel()}
              onSelectPrompt={(prompt) => {
                setDraft(viewKey, prompt);
                composerRef.current?.focus();
              }}
            />
          ) : null}

          <div
            aria-busy={sending || hasPendingWork}
            aria-live="polite"
            aria-relevant="additions text"
            className="message-list"
            role="log"
          >
            {activeDisplayedMessages.map((message) => {
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
                      {message.corrects_message_id == null ? null : (
                        <span className="correction-badge">Corrected</span>
                      )}
                      {!ownerMessage || message.message_id.startsWith("optimistic-") ? null : (
                        <button
                          aria-label="Correct message"
                          className="message-correct"
                          onClick={() => beginCorrection(message)}
                          type="button"
                        >
                          <Pencil aria-hidden="true" size={12} /> Correct
                        </button>
                      )}
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
                        <Button
                          loading={resumingMessageIds.has(`${message.thread_id}:${status.message_id}`)}
                          onClick={() => void resumeMessage(status)}
                          size="sm"
                          tone="ghost"
                        >
                          Try again
                        </Button>
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
          {sendFailure === undefined ? null : (
            <div className="composer-error" role="alert">
              <CircleAlert aria-hidden="true" size={16} />
              <div><strong>Message not sent</strong><span>{sendFailure.message} Your text is still here.</span></div>
              <Button onClick={() => composerFormRef.current?.requestSubmit()} size="sm" type="button">Try again</Button>
              <Button
                aria-label="Dismiss send error"
                onClick={() => setSendFailures((current) => withoutKey(current, viewKey))}
                size="icon"
                tone="ghost"
                type="button"
              >
                ×
              </Button>
            </div>
          )}
          <form className="composer" onSubmit={(event) => void sendMessage(event)} ref={composerFormRef}>
            <textarea
              aria-label="Message Melli"
              disabled={modelAvailability !== "ready" || sending}
              maxLength={100_000}
              onChange={(event) => {
                const nextDraft = event.target.value;
                setDraft(viewKey, nextDraft);
                if (sendFailure !== undefined && nextDraft.trim() !== sendFailure.text) {
                  setSendFailures((current) => withoutKey(current, viewKey));
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
              disabled={draft.trim().length === 0 || modelAvailability !== "ready" || creating}
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
        <button
          aria-label="Dismiss conversation drawer"
          className="thread-panel-scrim"
          onClick={() => setThreadPanelOpen(false)}
          tabIndex={-1}
          type="button"
        />
      ) : null}

      <Modal
        description="The context and privacy facts that materially shaped this answer."
        onClose={closeInspection}
        open={inspection !== null || inspectionLoading}
        title="Why this answer?"
      >
        {inspectionLoading ? <LoadingState label="Reading answer context" /> : null}
        {inspection === null ? null : <AnswerExplanation inspection={inspection} />}
      </Modal>

      <Modal
        description="Melli will answer the corrected wording instead of treating it as a new topic."
        onClose={() => {
          if (!correcting) {
            setCorrection(null);
          }
        }}
        open={correction !== null}
        title="Correct your message"
      >
        {correction === null ? null : (
          <form className="stack-form" onSubmit={(event) => void submitCorrection(event)}>
            <label className="field-label" htmlFor="message-correction">Corrected message</label>
            <textarea
              autoFocus
              className="correction-input"
              disabled={correcting}
              id="message-correction"
              maxLength={100_000}
              onChange={(event) => setCorrection((current) => (
                current === null
                  ? null
                  : { ...current, text: event.target.value, error: null }
              ))}
              rows={5}
              value={correction.text}
            />
            <p className="correction-limit">
              The earlier wording remains in correction history for provenance. Deleting the
              conversation removes both versions from active data.
            </p>
            {correction.error === null ? null : (
              <p className="correction-error" role="alert">{correction.error}</p>
            )}
            <div className="modal-actions">
              <Button disabled={correcting} onClick={() => setCorrection(null)} tone="ghost" type="button">
                Cancel
              </Button>
              <Button
                disabled={
                  correction.text.trim().length === 0
                  || correction.text.trim() === messageBody(correction.message).trim()
                }
                loading={correcting}
                tone="primary"
                type="submit"
              >
                Save correction
              </Button>
            </div>
          </form>
        )}
      </Modal>

      <Modal
        description="This removes the conversation from Melloa’s active data and cannot be undone."
        onClose={() => {
          if (!deleting) {
            setDeleteOpen(false);
          }
        }}
        open={deleteOpen}
        title="Delete this conversation?"
      >
        <div className="stack-form">
          <p>Messages, answers, and model output in this conversation will be removed now.</p>
          <p className="deletion-limit">
            Encrypted backups may retain an older copy until their separately configured expiry.
            This Melloa instance cannot verify that schedule.
          </p>
          <div className="modal-actions">
            <Button disabled={deleting} onClick={() => setDeleteOpen(false)} tone="ghost">
              Keep conversation
            </Button>
            <Button loading={deleting} onClick={() => void deleteConversation()} tone="danger">
              <Trash2 aria-hidden="true" size={16} /> Delete conversation
            </Button>
          </div>
        </div>
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
  const usedMemoryCount = inspection.turn.evidence_ids.length;
  const summary = readString(inspection.turn.decision_record, "summary");
  const local = !metadata.externalDisclosure;
  return (
    <div className="answer-explanation">
      <section>
        <span className="explanation-icon"><BookOpenCheck size={18} /></span>
        <div>
          <h3>Context</h3>
          <p>{usedMemoryCount === 0
            ? "No saved memories were used for this answer."
            : `Melli used ${usedMemoryCount} saved ${usedMemoryCount === 1 ? "memory" : "memories"}.`}</p>
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

function emptyConversationView(): ConversationView {
  return {
    messages: [],
    turns: [],
    processing: [],
    initialized: false,
    loading: false,
    error: null,
  };
}

function applyConversationReply(
  threadId: string,
  reply: ConversationReply,
  updateConversation: (
    selectedId: string,
    update: (current: ConversationView) => ConversationView,
  ) => void,
) {
  updateConversation(threadId, (current) => ({
    messages: mergeById(
      current.messages,
      [reply.inbound_message, reply.output_message].filter(
        (message): message is ConversationMessage => message != null,
      ),
      (message) => message.message_id,
    ),
    turns: mergeById(
      current.turns,
      reply.turn == null ? [] : [reply.turn],
      (turn) => turn.turn_id,
    ),
    processing: mergeById(
      current.processing,
      [reply.processing],
      (status) => status.message_id,
    ),
    initialized: true,
    loading: false,
    error: null,
  }));
}

function withoutKey<T>(
  current: Readonly<Record<string, T>>,
  key: string,
): Readonly<Record<string, T>> {
  const next = { ...current };
  delete next[key];
  return next;
}

function withoutSetValue<T>(current: ReadonlySet<T>, value: T): ReadonlySet<T> {
  const next = new Set(current);
  next.delete(value);
  return next;
}
