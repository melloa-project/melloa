import {
  type FormEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  ArrowDown,
  BookOpenCheck,
  Bot,
  ChevronRight,
  CircleAlert,
  Clock3,
  Coins,
  ExternalLink,
  FileSearch,
  Info,
  LoaderCircle,
  MessageCircleMore,
  PanelRightClose,
  Plus,
  RefreshCw,
  RotateCcw,
  Send,
  ShieldCheck,
  Sparkles,
  UserRound,
  WifiOff,
  X,
  Zap,
} from "lucide-react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";

import type {
  ConversationMessage,
  DeliveryWorkStatus,
  ConversationProcessingStatus,
  ConversationThread,
  ConversationTurn,
  ConversationTurnInspection,
} from "../api";
import { errorMessage, useMelloa } from "../app";
import { Badge, Button, EmptyState, ErrorState, LoadingState, Modal } from "../components/ui";
import {
  asObject,
  asObjectArray,
  formatDurationMs,
  formatGbp,
  formatInstant,
  messageBody,
  readString,
  safeJson,
  shortId,
  titleCase,
  turnMetadata,
} from "../lib/format";

const TERMINAL_PROCESSING_STATES = new Set(["completed", "dead", "cancelled"]);

const starterPrompts = [
  {
    label: "Readiness check",
    text: "Give me a concise local readiness check for this Melloa preview.",
  },
  {
    label: "Use memory evidence",
    text: "What can you answer from the current seed memory, and what evidence will you cite?",
  },
  {
    label: "Inspect boundaries",
    text: "Help me inspect what is private, durable, and still preview-only right now.",
  },
] as const;

type ComposerState = {
  readonly draft: string;
  readonly submissionKey: string | null;
};

const EMPTY_COMPOSER_STATE: ComposerState = {
  draft: "",
  submissionKey: null,
};

export function ConversationPage() {
  const { api, principal, canMutate, notify } = useMelloa();
  const navigate = useNavigate();
  const { threadId } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const queryTurnId = searchParams.get("turn");
  const [threads, setThreads] = useState<readonly ConversationThread[]>([]);
  const [messages, setMessages] = useState<readonly ConversationMessage[]>([]);
  const [turns, setTurns] = useState<readonly ConversationTurn[]>([]);
  const [processing, setProcessing] = useState<readonly ConversationProcessingStatus[]>([]);
  const [deliveries, setDeliveries] = useState<readonly DeliveryWorkStatus[]>([]);
  const [loadingThreads, setLoadingThreads] = useState(true);
  const [loadingConversation, setLoadingConversation] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [composerStateByThread, setComposerStateByThread] = useState<Record<string, ComposerState>>({});
  const [sending, setSending] = useState(false);
  const [selectedTurnId, setSelectedTurnId] = useState<string | null>(null);
  const [selectedMessageId, setSelectedMessageId] = useState<string | null>(null);
  const [selectedDeliveryWorkId, setSelectedDeliveryWorkId] = useState<string | null>(null);
  const [inspection, setInspection] = useState<ConversationTurnInspection | null>(null);
  const [inspectionLoading, setInspectionLoading] = useState(false);
  const listEnd = useRef<HTMLDivElement | null>(null);
  const composerRef = useRef<HTMLTextAreaElement | null>(null);

  const selectedThread = threads.find((thread) => thread.thread_id === threadId) ?? null;
  const composerState = threadId === undefined ? EMPTY_COMPOSER_STATE : composerStateByThread[threadId] ?? EMPTY_COMPOSER_STATE;
  const draft = composerState.draft;
  const submissionKey = composerState.submissionKey;
  const processingByMessage = useMemo(
    () => new Map(processing.map((status) => [status.message_id, status])),
    [processing],
  );
  const deliveriesByMessage = useMemo(() => {
    const result = new Map<string, DeliveryWorkStatus[]>();
    for (const delivery of deliveries) {
      const group = result.get(delivery.message_id);
      if (group === undefined) {
        result.set(delivery.message_id, [delivery]);
      } else {
        group.push(delivery);
      }
    }
    return result;
  }, [deliveries]);
  const turnByOutputMessage = useMemo(() => {
    const result = new Map<string, ConversationTurn>();
    for (const turn of turns) {
      for (const messageId of turn.output_message_ids) {
        result.set(messageId, turn);
      }
    }
    return result;
  }, [turns]);
  const selectedProcessing = selectedMessageId === null
    ? null
    : processingByMessage.get(selectedMessageId) ?? null;
  const selectedDelivery = selectedDeliveryWorkId === null
    ? null
    : deliveries.find((delivery) => delivery.work_id === selectedDeliveryWorkId) ?? null;
  const pending = processing.some((status) => !TERMINAL_PROCESSING_STATES.has(status.state))
    || deliveries.some((status) => !TERMINAL_PROCESSING_STATES.has(status.state));

  const loadThreads = useCallback(async () => {
    setLoadingThreads(true);
    try {
      const nextThreads = await api.listThreads();
      setThreads(nextThreads);
      setError(null);
      return nextThreads;
    } catch (caught) {
      setError(errorMessage(caught));
      return [];
    } finally {
      setLoadingThreads(false);
    }
  }, [api]);

  const loadConversation = useCallback(async (selectedId: string, quiet = false) => {
    if (!quiet) {
      setLoadingConversation(true);
    }
    try {
      const [nextMessages, nextTurns, nextProcessing, nextDeliveries] = await Promise.all([
        api.listMessages(selectedId),
        api.listTurns(selectedId),
        api.listProcessing(selectedId),
        api.listDeliveries(selectedId),
      ]);
      setMessages(nextMessages);
      setTurns(nextTurns);
      setProcessing(nextProcessing);
      setDeliveries(nextDeliveries);
      setError(null);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      if (!quiet) {
        setLoadingConversation(false);
      }
    }
  }, [api]);

  useEffect(() => {
    void loadThreads();
  }, [loadThreads]);

  useEffect(() => {
    if (loadingThreads || threads.length === 0) {
      return;
    }
    if (threadId === undefined || !threads.some((thread) => thread.thread_id === threadId)) {
      const first = threads[0];
      if (first !== undefined) {
        navigate(`/conversation/${first.thread_id}`, { replace: true });
      }
      return;
    }
    setSelectedTurnId(null);
    setSelectedMessageId(null);
    setSelectedDeliveryWorkId(null);
    setInspection(null);
    void loadConversation(threadId);
  }, [loadConversation, loadingThreads, navigate, threadId, threads]);

  useEffect(() => {
    if (queryTurnId === null || turns.length === 0) {
      return;
    }
    if (!turns.some((turn) => turn.turn_id === queryTurnId)) {
      return;
    }
    setSelectedTurnId(queryTurnId);
    setSelectedMessageId(null);
    setSelectedDeliveryWorkId(null);
  }, [queryTurnId, turns]);

  useEffect(() => {
    if (!pending || threadId === undefined) {
      return;
    }
    const timer = window.setInterval(() => void loadConversation(threadId, true), 1_500);
    return () => window.clearInterval(timer);
  }, [loadConversation, pending, threadId]);

  useEffect(() => {
    listEnd.current?.scrollIntoView({ behavior: loadingConversation ? "instant" : "smooth" });
  }, [loadingConversation, messages]);

  useEffect(() => {
    if (selectedTurnId === null || threadId === undefined) {
      setInspection(null);
      return;
    }
    let active = true;
    setInspectionLoading(true);
    void api.inspectTurn(threadId, selectedTurnId)
      .then((result) => {
        if (active) {
          setInspection(result);
        }
      })
      .catch((caught) => {
        if (active) {
          notify(errorMessage(caught), "error");
        }
      })
      .finally(() => {
        if (active) {
          setInspectionLoading(false);
        }
      });
    return () => {
      active = false;
    };
  }, [api, notify, selectedTurnId, threadId]);

  function setComposerStateForThread(
    selectedId: string,
    update: (current: ComposerState) => ComposerState,
  ) {
    setComposerStateByThread((current) => ({
      ...current,
      [selectedId]: update(current[selectedId] ?? EMPTY_COMPOSER_STATE),
    }));
  }

  async function createThread(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const titleInput = form.elements.namedItem("title");
    if (!(titleInput instanceof HTMLInputElement)) {
      return;
    }
    if (!canMutate) {
      notify("Unlock owner changes before creating a conversation.", "error");
      return;
    }
    setCreating(true);
    try {
      const thread = await api.createThread({
        title: titleInput.value.trim(),
        sensitivity: "personal",
        retention_policy: "retention.owner-conversation",
      });
      titleInput.value = "";
      setCreateOpen(false);
      await loadThreads();
      navigate(`/conversation/${thread.thread_id}`);
      notify("Conversation created.", "success");
    } catch (caught) {
      notify(errorMessage(caught), "error");
    } finally {
      setCreating(false);
    }
  }

  async function sendMessage(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (threadId === undefined || draft.trim().length === 0) {
      return;
    }
    if (!canMutate) {
      notify("Unlock owner changes before sending a message.", "error");
      return;
    }
    const selectedId = threadId;
    const trimmedDraft = draft.trim();
    const key = submissionKey ?? crypto.randomUUID();
    setComposerStateForThread(selectedId, (current) => ({ ...current, submissionKey: key }));
    setSending(true);
    try {
      const reply = await api.postMessage(selectedId, trimmedDraft, key);
      setComposerStateForThread(selectedId, () => EMPTY_COMPOSER_STATE);
      await loadConversation(selectedId, true);
      if (reply.processing.state === "dead") {
        notify("Melli could not complete this reply. The turn is ready to inspect or resume.", "error");
      } else if (reply.output_message === null || reply.output_message === undefined) {
        notify("Message accepted. Melli is still processing it.");
      }
    } catch (caught) {
      notify(`${errorMessage(caught)} Retrying will reuse the same canonical submission.`, "error");
    } finally {
      setSending(false);
    }
  }

  async function resumeMessage(status: ConversationProcessingStatus) {
    if (threadId === undefined) {
      return;
    }
    if (!canMutate) {
      notify("Unlock owner changes before resuming model work.", "error");
      return;
    }
    try {
      await api.resumeMessage(threadId, status.message_id);
      await loadConversation(threadId, true);
      notify("A new bounded retry budget was added.", "success");
    } catch (caught) {
      notify(errorMessage(caught), "error");
    }
  }

  async function resumeDelivery(status: DeliveryWorkStatus) {
    if (threadId === undefined) {
      return;
    }
    if (!canMutate) {
      notify("Unlock owner changes before resuming delivery work.", "error");
      return;
    }
    try {
      const delivery = await api.resumeDelivery(threadId, status.work_id);
      setSelectedDeliveryWorkId(delivery.work_id);
      await loadConversation(threadId, true);
      notify("A new bounded delivery retry budget was added.", "success");
    } catch (caught) {
      notify(errorMessage(caught), "error");
    }
  }

  function clearTurnQuery() {
    if (queryTurnId === null) {
      return;
    }
    const next = new URLSearchParams(searchParams);
    next.delete("turn");
    setSearchParams(next, { replace: true });
  }

  function closeInspector() {
    clearTurnQuery();
    setSelectedTurnId(null);
    setSelectedMessageId(null);
    setSelectedDeliveryWorkId(null);
  }

  function inspectMessage(message: ConversationMessage) {
    clearTurnQuery();
    const turn = turnByOutputMessage.get(message.message_id);
    if (turn !== undefined) {
      setSelectedTurnId(turn.turn_id);
      setSelectedMessageId(null);
      setSelectedDeliveryWorkId(null);
      return;
    }
    setSelectedTurnId(null);
    setSelectedMessageId(message.message_id);
    setSelectedDeliveryWorkId(null);
  }

  function inspectDelivery(delivery: DeliveryWorkStatus) {
    clearTurnQuery();
    setSelectedTurnId(null);
    setSelectedMessageId(null);
    setSelectedDeliveryWorkId(delivery.work_id);
  }

  function selectStarterPrompt(prompt: string) {
    if (threadId === undefined) {
      return;
    }
    setComposerStateForThread(threadId, () => ({ draft: prompt, submissionKey: null }));
    window.requestAnimationFrame(() => composerRef.current?.focus());
  }

  const inspectorOpen = selectedTurnId !== null || selectedMessageId !== null || selectedDeliveryWorkId !== null;

  return (
    <div className={`conversation-page ${inspectorOpen ? "inspector-open" : ""}`}>
      <aside className="thread-list" aria-label="Conversation threads">
        <div className="thread-list-header">
          <div><span>Conversations</span><small>{threads.length} canonical thread{threads.length === 1 ? "" : "s"}</small></div>
          <Button aria-label="New conversation" onClick={() => setCreateOpen(true)} size="icon" tone="ghost">
            <Plus aria-hidden="true" size={18} />
          </Button>
        </div>
        {loadingThreads ? <LoadingState label="Loading conversations" /> : null}
        {!loadingThreads && threads.length === 0 ? (
          <div className="thread-empty"><MessageCircleMore size={20} /><p>No conversations yet.</p></div>
        ) : null}
        <div className="thread-items">
          {threads.map((thread) => (
            <button
              className={`thread-item ${thread.thread_id === threadId ? "active" : ""}`}
              key={thread.thread_id}
              onClick={() => navigate(`/conversation/${thread.thread_id}`)}
              type="button"
            >
              <span className="thread-avatar"><Sparkles aria-hidden="true" size={16} /></span>
              <span><strong>{thread.title}</strong><small>{titleCase(thread.sensitivity)} · {shortId(thread.thread_id)}</small></span>
              <ChevronRight aria-hidden="true" size={15} />
            </button>
          ))}
        </div>
      </aside>

      <section className="conversation-main" aria-label="Canonical conversation">
        {selectedThread === null ? (
          <EmptyState
            action={<Button disabled={!canMutate} onClick={() => setCreateOpen(true)} tone="primary"><Plus size={16} /> Start a conversation</Button>}
            description="Create a private first-party thread. Messages remain channel-neutral and inspectable."
            icon={MessageCircleMore}
            title="A quiet place to talk with Melli"
          />
        ) : (
          <>
            <header className="conversation-header">
              <div>
                <div className="conversation-title-row">
                  <h1>{selectedThread.title}</h1>
                  <Badge tone="info">{titleCase(selectedThread.sensitivity)}</Badge>
                </div>
                <p>Canonical thread · {shortId(selectedThread.thread_id)}</p>
              </div>
              <div className="conversation-header-actions">
                {pending ? <Badge tone="warning"><LoaderCircle className="spin" size={13} /> Processing</Badge> : <Badge tone="positive"><Zap size={13} /> Ready</Badge>}
                <Button onClick={() => void loadConversation(selectedThread.thread_id)} size="icon" tone="ghost" title="Refresh conversation"><RefreshCw size={17} /></Button>
              </div>
            </header>

            <div className="message-scroll">
              {loadingConversation ? <LoadingState label="Loading canonical messages" /> : null}
              {error === null ? null : <ErrorState message={error} />}
              {!loadingConversation && error === null && messages.length === 0 ? (
                <EmptyState
                  description="Ask a question or share context. Route, cost, disclosure, and evidence will be attached to Melli's reply."
                  icon={Sparkles}
                  title="Start with what matters now"
                />
              ) : null}
              {!loadingConversation && error === null && messages.length === 0 ? (
                <div className="starter-prompt-grid" aria-label="Starter prompts">
                  {starterPrompts.map((prompt) => (
                    <button
                      className="starter-prompt"
                      key={prompt.label}
                      onClick={() => selectStarterPrompt(prompt.text)}
                      type="button"
                    >
                      <Sparkles aria-hidden="true" size={15} />
                      <span><strong>{prompt.label}</strong><small>{prompt.text}</small></span>
                    </button>
                  ))}
                </div>
              ) : null}
              <div className="message-list">
                {messages.map((message) => {
                  const isOwner = message.author_principal_id === principal.owner_id;
                  const status = processingByMessage.get(message.message_id);
                  const turn = turnByOutputMessage.get(message.message_id);
                  const messageDeliveries = deliveriesByMessage.get(message.message_id) ?? [];
                  return (
                    <article className={`message-row ${isOwner ? "owner" : "melli"}`} key={message.message_id}>
                      <div className="message-avatar">
                        {isOwner ? <UserRound aria-hidden="true" size={17} /> : <Sparkles aria-hidden="true" size={17} />}
                      </div>
                      <button className="message-content" onClick={() => inspectMessage(message)} type="button">
                        <div className="message-meta">
                          <strong>{isOwner ? "You" : "Melli"}</strong>
                          <span>{formatInstant(message.created_at)}</span>
                          {!isOwner && message.citation_ids.length > 0 ? <Badge tone="violet"><BookOpenCheck size={12} /> {message.citation_ids.length} cited</Badge> : null}
                        </div>
                        <p>{messageBody(message)}</p>
                        {turn === undefined ? null : (
                          <span className="inspect-hint"><FileSearch size={13} /> Inspect route and provenance</span>
                        )}
                      </button>
                      {status === undefined ? null : (
                        <ProcessingPill canMutate={canMutate} status={status} onResume={() => void resumeMessage(status)} />
                      )}
                      {messageDeliveries.length === 0 ? null : (
                        <div className="delivery-pill-list" aria-label={`Deliveries for message ${message.message_id}`}>
                          {messageDeliveries.map((delivery) => (
                            <DeliveryPill delivery={delivery} key={delivery.work_id} onInspect={() => inspectDelivery(delivery)} />
                          ))}
                        </div>
                      )}
                    </article>
                  );
                })}
                <div ref={listEnd} />
              </div>
            </div>

            <form className="composer" onSubmit={(event) => void sendMessage(event)}>
              <textarea
                aria-label="Message Melli"
                maxLength={100_000}
                onChange={(event) => {
                  const nextDraft = event.target.value;
                  if (threadId !== undefined) {
                    setComposerStateForThread(threadId, () => ({ draft: nextDraft, submissionKey: null }));
                  }
                }}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey) {
                    event.preventDefault();
                    event.currentTarget.form?.requestSubmit();
                  }
                }}
                placeholder="Message Melli…"
                ref={composerRef}
                rows={1}
                value={draft}
              />
              <div className="composer-footer">
                <span><ShieldCheck size={13} /> Private, policy-bounded conversation</span>
                <Button disabled={draft.trim().length === 0 || !canMutate} loading={sending} size="icon" tone="primary" type="submit">
                  <Send aria-hidden="true" size={17} /><span className="sr-only">Send message</span>
                </Button>
              </div>
            </form>
          </>
        )}
      </section>

      <aside className={`inspector ${inspectorOpen ? "visible" : ""}`} aria-label="Turn inspector">
        <div className="inspector-header">
          <div><p className="eyebrow">Inspectable record</p><h2>{selectedDeliveryWorkId !== null ? "Delivery" : selectedTurnId === null ? "Processing" : "Turn details"}</h2></div>
          <Button onClick={closeInspector} size="icon" tone="ghost"><PanelRightClose size={18} /><span className="sr-only">Close inspector</span></Button>
        </div>
        <div className="inspector-body">
          {inspectionLoading ? <LoadingState label="Loading turn evidence" /> : null}
          {!inspectionLoading && inspection !== null ? (
            <TurnInspector
              inspection={inspection}
              onInspectMemory={(assertionId) => navigate(`/memory?assertion=${encodeURIComponent(assertionId)}`)}
            />
          ) : null}
          {!inspectionLoading && selectedProcessing !== null ? (
            <ProcessingInspector canMutate={canMutate} status={selectedProcessing} onResume={() => void resumeMessage(selectedProcessing)} />
          ) : null}
          {!inspectionLoading && selectedDelivery !== null ? (
            <DeliveryInspector canMutate={canMutate} delivery={selectedDelivery} onResume={() => void resumeDelivery(selectedDelivery)} />
          ) : null}
          {!inspectionLoading && inspection === null && selectedProcessing === null && selectedDelivery === null ? (
            <div className="inspector-placeholder"><Info size={20} /><p>Select a message to inspect its durable record.</p></div>
          ) : null}
        </div>
      </aside>

      <Modal
        description="Threads are canonical Melloa records, independent of browser or Telegram sessions."
        onClose={() => setCreateOpen(false)}
        open={createOpen}
        title="New conversation"
      >
        <form className="stack-form" onSubmit={(event) => void createThread(event)}>
          <label className="field-label" htmlFor="conversation-title">Title</label>
          <input autoFocus className="text-input" id="conversation-title" maxLength={256} name="title" placeholder="What are we working through?" required />
          <div className="form-note"><ShieldCheck size={15} /><span>Starts as Personal with the owner-conversation retention policy.</span></div>
          <div className="modal-actions">
            <Button onClick={() => setCreateOpen(false)} type="button">Cancel</Button>
            <Button disabled={!canMutate} loading={creating} tone="primary" type="submit">Create conversation</Button>
          </div>
        </form>
      </Modal>

      {inspectorOpen ? <button aria-label="Close inspector" className="inspector-scrim" onClick={closeInspector} type="button" /> : null}
    </div>
  );
}

function ProcessingPill({
  canMutate,
  status,
  onResume,
}: {
  readonly canMutate: boolean;
  readonly status: ConversationProcessingStatus;
  readonly onResume: () => void;
}) {
  if (status.state === "completed") {
    return null;
  }
  if (status.state === "dead") {
    return (
      <button className="processing-pill failed" disabled={!canMutate} onClick={onResume} type="button">
        <CircleAlert size={13} /> Reply failed · resume
      </button>
    );
  }
  return <span className="processing-pill"><LoaderCircle className="spin" size={13} /> {titleCase(status.state)}</span>;
}

function DeliveryPill({
  delivery,
  onInspect,
}: {
  readonly delivery: DeliveryWorkStatus;
  readonly onInspect: () => void;
}) {
  const completed = delivery.state === "completed";
  const dead = delivery.state === "dead";
  const label = completed ? "Delivered" : dead ? "Delivery failed" : titleCase(delivery.state);
  const Icon = completed ? ShieldCheck : dead ? CircleAlert : LoaderCircle;
  return (
    <button
      className={`delivery-pill ${completed ? "completed" : dead ? "failed" : "pending"}`}
      onClick={onInspect}
      type="button"
    >
      <Icon className={completed || dead ? undefined : "spin"} size={13} />
      {label} · inspect
    </button>
  );
}

type TurnLedgerRow = {
  readonly label: string;
  readonly ids: readonly string[];
};

function turnLedgerRows(turn: ConversationTurn): readonly TurnLedgerRow[] {
  return [
    { label: "Turn", ids: [turn.turn_id] },
    { label: "Triggering messages", ids: turn.triggering_message_ids },
    { label: "Model runs", ids: turn.model_run_ids },
    { label: "Evidence records", ids: turn.evidence_ids },
    { label: "Policy decisions", ids: turn.policy_decision_ids },
    { label: "Proposed actions", ids: turn.proposed_action_ids },
    { label: "Executed actions", ids: turn.executed_action_ids },
    { label: "Output messages", ids: turn.output_message_ids },
  ];
}

export function TurnInspector({
  inspection,
  onInspectMemory,
}: {
  readonly inspection: ConversationTurnInspection;
  readonly onInspectMemory: (assertionId: string) => void;
}) {
  const metadata = turnMetadata(inspection);
  const citations = asObjectArray(inspection.retrieval_manifest.citations);
  const decision = inspection.turn.decision_record;
  const ledgerRows = turnLedgerRows(inspection.turn);
  const ledgerCount = ledgerRows.reduce((total, row) => total + row.ids.length, 0);
  const synthetic = metadata.providerId === "provider.synthetic";
  const codexCli = metadata.providerId === "provider.openai-codex-subscription";
  return (
    <div className="inspector-sections">
      <section className="inspector-hero">
        <div className="route-icon"><Bot size={19} /></div>
        <div><strong>{metadata.modelId}</strong><span>{metadata.providerId}</span></div>
        <Badge tone={synthetic ? "violet" : metadata.externalDisclosure ? "warning" : "positive"}>
          {synthetic ? "Synthetic" : metadata.externalDisclosure ? "External" : "Local"}
        </Badge>
      </section>

      <section className="inspector-section">
        <h3>Route</h3>
        <dl className="detail-list">
          <div><dt>Route</dt><dd>{metadata.routeId}</dd></div>
          <div><dt>Location</dt><dd>{titleCase(metadata.location)}</dd></div>
          <div><dt>Disclosure</dt><dd>{metadata.externalDisclosure ? "Recorded external disclosure" : "No external disclosure"}</dd></div>
          <div><dt>Latency</dt><dd>{formatDurationMs(metadata.latencyMs)}</dd></div>
        </dl>
      </section>

      <section className="inspector-section metric-pair">
        <div><Coins size={15} /><span>Cost</span><strong>{codexCli ? "Unreported" : formatGbp(metadata.costGbp)}</strong></div>
        <div><Zap size={15} /><span>Tokens</span><strong>{codexCli ? "Unreported" : metadata.inputTokens + metadata.outputTokens}</strong></div>
      </section>
      {codexCli ? <p className="usage-metadata-note">Codex CLI does not report per-call token usage here. Subscription fees are not represented as per-call cost.</p> : null}

      <section className="inspector-section">
        <div className="inspector-section-title"><h3>Turn ledger</h3><Badge tone={ledgerCount > 0 ? "violet" : "neutral"}>{ledgerCount} IDs</Badge></div>
        <div className="turn-ledger-list">
          {ledgerRows.map((row) => (
            <div className="turn-ledger-row" key={row.label}>
              <span><strong>{row.label}</strong><small>{row.ids.length} recorded</small></span>
              <div>
                {row.ids.length === 0 ? <em>None recorded</em> : row.ids.map((id) => <code key={id}>{shortId(id)}</code>)}
              </div>
            </div>
          ))}
        </div>
      </section>

      <section className="inspector-section">
        <div className="inspector-section-title"><h3>Evidence</h3><Badge tone={citations.length > 0 ? "violet" : "neutral"}>{citations.length} retrieved</Badge></div>
        {citations.length === 0 ? <p className="muted-copy">No memory citations were supplied for this turn.</p> : (
          <div className="evidence-list">
            {citations.map((citation) => {
              const assertionId = readString(citation, "assertion_id");
              return (
                <button
                  aria-label={`Inspect memory assertion ${assertionId}`}
                  className="evidence-item"
                  key={readString(citation, "citation_id")}
                  onClick={() => onInspectMemory(assertionId)}
                  type="button"
                >
                  <BookOpenCheck size={15} />
                  <span><strong>{shortId(assertionId)}</strong><small>{titleCase(readString(citation, "epistemic_status"))}</small></span>
                  <ExternalLink aria-hidden="true" className="evidence-open-icon" size={13} />
                </button>
              );
            })}
          </div>
        )}
      </section>

      <section className="inspector-section">
        <h3>Decision record</h3>
        <p className="decision-summary">{readString(decision, "summary")}</p>
        <dl className="detail-list">
          <div><dt>Prompt</dt><dd>{readString(decision, "prompt_version")}</dd></div>
          <div><dt>Runtime</dt><dd>{readString(decision, "runtime_version")}</dd></div>
          <div><dt>Uncertainty</dt><dd>{readString(decision, "uncertainty")}</dd></div>
        </dl>
      </section>

      <section className="inspector-section">
        <div className="inspector-section-title"><h3>Route attempts</h3><Badge>{metadata.attempts.length}</Badge></div>
        {metadata.attempts.map((attempt, index) => (
          <div className="attempt-row" key={`${readString(attempt, "route_id")}-${index}`}>
            {readString(attempt, "outcome") === "succeeded" ? <ShieldCheck size={15} /> : <WifiOff size={15} />}
            <span><strong>{readString(attempt, "route_id")}</strong><small>{titleCase(readString(attempt, "outcome"))} · {titleCase(readString(attempt, "processing_location"))}</small></span>
          </div>
        ))}
      </section>
    </div>
  );
}

function DeliveryInspector({
  canMutate,
  delivery,
  onResume,
}: {
  readonly canMutate: boolean;
  readonly delivery: DeliveryWorkStatus;
  readonly onResume: () => void;
}) {
  const completed = delivery.state === "completed";
  const dead = delivery.state === "dead";
  const Icon = completed ? ShieldCheck : dead ? CircleAlert : LoaderCircle;
  return (
    <div className="inspector-sections">
      <section className={`processing-summary ${completed ? "completed" : ""} ${dead ? "failed" : ""}`}>
        <Icon className={completed || dead ? undefined : "spin"} size={20} />
        <div><strong>{titleCase(delivery.state)}</strong><span>{delivery.attempt_count} of {delivery.max_attempts} attempts used</span></div>
      </section>
      <section className="inspector-section">
        <h3>Exact authority</h3>
        <dl className="detail-list">
          <div><dt>Work</dt><dd>{shortId(delivery.work_id)}</dd></div>
          <div><dt>Message</dt><dd>{shortId(delivery.message_id)}</dd></div>
          <div><dt>Adapter</dt><dd>{delivery.client_adapter}</dd></div>
          <div><dt>Destination</dt><dd>{delivery.destination_ref}</dd></div>
          <div><dt>Policy decision</dt><dd>{shortId(delivery.current_policy_decision_id)}</dd></div>
          <div><dt>Action hash</dt><dd>{shortId(delivery.action_hash)}</dd></div>
          <div><dt>Available</dt><dd>{formatInstant(delivery.available_at)}</dd></div>
          <div><dt>Completed</dt><dd>{formatInstant(delivery.completed_at)}</dd></div>
        </dl>
        {dead ? <Button disabled={!canMutate} onClick={onResume} tone="primary"><RotateCcw size={15} /> Resume delivery with bounded retries</Button> : null}
      </section>
      <section className="inspector-section">
        <div className="inspector-section-title"><h3>Attempts</h3><Badge>{delivery.attempts.length}</Badge></div>
        {delivery.attempts.length === 0 ? <p className="muted-copy">No delivery attempt has started yet.</p> : delivery.attempts.map((attempt) => (
          <div className="attempt-row" key={attempt.attempt_id}>
            {attempt.outcome === "succeeded" ? <ShieldCheck size={15} /> : <Clock3 size={15} />}
            <span>
              <strong>Attempt {attempt.attempt} · {titleCase(attempt.outcome)}</strong>
              <small>{attempt.error_code === null || attempt.error_code === undefined ? deliveryAttemptReceiptSummary(attempt.adapter_receipt, attempt.execution_receipt) : titleCase(attempt.error_code)}</small>
            </span>
          </div>
        ))}
      </section>
      <section className="inspector-section">
        <h3>Resumptions</h3>
        {delivery.resumptions.length === 0 ? <p className="muted-copy">No owner resumption has been recorded.</p> : delivery.resumptions.map((resumption) => (
          <div className="attempt-row" key={resumption.resumption_id}>
            <RotateCcw size={15} />
            <span><strong>{shortId(resumption.resumption_id)}</strong><small>{resumption.added_attempts} attempts added · {formatInstant(resumption.requested_at)}</small></span>
          </div>
        ))}
      </section>
      <details className="raw-details"><summary>Raw redacted delivery status</summary><pre>{safeJson(delivery)}</pre></details>
    </div>
  );
}

function deliveryAttemptReceiptSummary(adapterReceipt: unknown, executionReceipt: unknown): string {
  const adapter = asObject(adapterReceipt);
  const execution = asObject(executionReceipt);
  if (adapter === null && execution === null) {
    return "No receipt";
  }
  const adapterId = adapter === null ? "no adapter receipt" : `adapter ${shortId(readString(adapter, "delivery_id"))}`;
  const executionId = execution === null ? "no execution receipt" : `execution ${shortId(readString(execution, "action_id"))}`;
  return `${adapterId} · ${executionId}`;
}

function ProcessingInspector({
  canMutate,
  status,
  onResume,
}: {
  readonly canMutate: boolean;
  readonly status: ConversationProcessingStatus;
  readonly onResume: () => void;
}) {
  return (
    <div className="inspector-sections">
      <section className={`processing-summary ${status.state === "dead" ? "failed" : ""}`}>
        {status.state === "dead" ? <CircleAlert size={20} /> : <LoaderCircle className="spin" size={20} />}
        <div><strong>{titleCase(status.state)}</strong><span>{status.attempt_count} of {status.max_attempts} attempts used</span></div>
      </section>
      <section className="inspector-section">
        <h3>Recovery state</h3>
        <dl className="detail-list">
          <div><dt>Work</dt><dd>{shortId(status.work_id)}</dd></div>
          <div><dt>Last error</dt><dd>{status.last_error_code ?? "None"}</dd></div>
          <div><dt>Available</dt><dd>{formatInstant(status.available_at)}</dd></div>
          <div><dt>Resumptions</dt><dd>{status.resumptions.length}</dd></div>
        </dl>
        {status.state === "dead" ? <Button disabled={!canMutate} onClick={onResume} tone="primary"><RotateCcw size={15} /> Resume with bounded retries</Button> : null}
      </section>
      <section className="inspector-section">
        <h3>Attempts</h3>
        {status.attempts.length === 0 ? <p className="muted-copy">No attempt has started yet.</p> : status.attempts.map((attempt) => (
          <div className="attempt-row" key={attempt.attempt_id}>
            <Clock3 size={15} />
            <span><strong>Attempt {attempt.attempt}</strong><small>{titleCase(attempt.outcome)} · {attempt.error_code ?? "no error"}</small></span>
          </div>
        ))}
      </section>
      <details className="raw-details"><summary>Raw redacted status</summary><pre>{safeJson(status)}</pre></details>
    </div>
  );
}
