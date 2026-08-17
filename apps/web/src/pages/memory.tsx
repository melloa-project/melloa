import { type FormEvent, useCallback, useEffect, useRef, useState } from "react";
import {
  AlertTriangle,
  Brain,
  CheckCircle2,
  Copy,
  ExternalLink,
  GitBranch,
  History,
  PencilLine,
  Search,
  ShieldCheck,
  Trash2,
} from "lucide-react";
import { useSearchParams } from "react-router-dom";

import type { JsonObject, MemoryInspection } from "../api";
import { errorMessage, useMelloa } from "../app";
import { Badge, Button, Card, EmptyState, ErrorState, LoadingState, Modal, SectionHeader } from "../components/ui";
import { asObject, formatInstant, readNumber, readString, safeJson, shortId, titleCase } from "../lib/format";

type MemoryAction = "correct" | "dispute" | "retract" | "delete_content";

export function MemoryPage() {
  const { api, canMutate, notify } = useMelloa();
  const [searchParams, setSearchParams] = useSearchParams();
  const assertionQuery = searchParams.get("assertion")?.trim() ?? "";
  const [query, setQuery] = useState(assertionQuery);
  const [inspection, setInspection] = useState<MemoryInspection | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [action, setAction] = useState<MemoryAction | null>(null);
  const [mutating, setMutating] = useState(false);
  const inspectRequestRef = useRef(0);

  const inspect = useCallback(async (assertionId: string) => {
    const normalized = assertionId.trim();
    if (normalized.length === 0) {
      return;
    }
    const requestId = inspectRequestRef.current + 1;
    inspectRequestRef.current = requestId;
    setLoading(true);
    try {
      const nextInspection = await api.inspectMemory(normalized);
      if (requestId !== inspectRequestRef.current) {
        return;
      }
      setInspection(nextInspection);
      setError(null);
    } catch (caught) {
      if (requestId !== inspectRequestRef.current) {
        return;
      }
      setInspection(null);
      setError(errorMessage(caught));
    } finally {
      if (requestId === inspectRequestRef.current) {
        setLoading(false);
      }
    }
  }, [api]);

  useEffect(() => {
    if (assertionQuery.length === 0) {
      inspectRequestRef.current += 1;
      setQuery("");
      setInspection(null);
      setError(null);
      setLoading(false);
      return;
    }
    setQuery(assertionQuery);
    void inspect(assertionQuery);
  }, [assertionQuery, inspect]);

  function submitSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const normalized = query.trim();
    if (normalized.length === 0) {
      return;
    }
    if (normalized === assertionQuery) {
      void inspect(normalized);
      return;
    }
    setSearchParams({ assertion: normalized });
  }

  function inspectRelatedAssertion(assertionId: string) {
    const normalized = assertionId.trim();
    if (normalized.length === 0 || normalized === "unknown") {
      return;
    }
    setSearchParams({ assertion: normalized });
  }

  async function copyAssertionId(assertionId: string) {
    try {
      if (navigator.clipboard === undefined) {
        throw new Error("Clipboard API unavailable");
      }
      await navigator.clipboard.writeText(assertionId);
      notify("Assertion ID copied.", "success");
    } catch {
      notify("Assertion ID copy failed.", "error");
    }
  }

  async function submitAction(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (action === null || inspection === null) {
      return;
    }
    if (!canMutate) {
      notify("Unlock owner changes before changing memory.", "error");
      return;
    }
    setMutating(true);
    try {
      const assertionId = inspection.assertion.assertion_id;
      const version = inspection.current_state.version;
      if (action === "delete_content") {
        await api.deleteMemoryContent(assertionId);
      } else if (action === "correct") {
        const form = event.currentTarget;
        const field = form.elements.namedItem("value");
        if (!(field instanceof HTMLTextAreaElement)) {
          return;
        }
        const parsed: unknown = JSON.parse(field.value);
        if (parsed === null || Array.isArray(parsed) || typeof parsed !== "object") {
          throw new Error("Correction value must be a JSON object.");
        }
        await api.correctMemory(assertionId, parsed as Record<string, unknown>, version);
      } else if (action === "dispute") {
        await api.disputeMemory(assertionId, version);
      } else {
        await api.retractMemory(assertionId, version);
      }
      await inspect(assertionId);
      setAction(null);
      notify(memoryActionPastTense(action), "success");
    } catch (caught) {
      notify(errorMessage(caught), "error");
    } finally {
      setMutating(false);
    }
  }

  const status = inspection?.current_state.current_status ?? "unknown";
  const assertionValue = inspection?.assertion.value;
  const contentDeleted = inspection?.content_state === "deleted";
  const deletionTombstone = asObject(inspection?.deletion_tombstone);
  const backupExpiry = asObject(inspection?.backup_expiry);

  return (
    <div className="standard-page memory-page">
      <SectionHeader
        eyebrow="Owner-correctable memory"
        title="Memory"
        description="Inspect a durable assertion, its provenance, and every correction-state transition."
      />

      <Card className="memory-search-card">
        <form className="memory-search" onSubmit={submitSearch}>
          <Search aria-hidden="true" size={18} />
          <input
            aria-label="Assertion ID"
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Paste an assertion ID"
            spellCheck={false}
            value={query}
          />
          <Button disabled={query.trim().length === 0} loading={loading} tone="primary" type="submit">Inspect memory</Button>
        </form>
        <p><ShieldCheck size={14} /> Memory lookup is owner-authenticated and does not expose a public search surface.</p>
      </Card>

      {loading && inspection === null ? <LoadingState label="Reading memory provenance" /> : null}
      {error === null ? null : <ErrorState title="Memory not available" message={error} />}

      {!loading && error === null && inspection === null ? (
        <Card>
          <EmptyState
            icon={Brain}
            title="Inspect a memory assertion"
            description="Open a cited assertion from a turn or paste its durable identifier here. Broad memory browsing is intentionally not part of this MVP."
          />
        </Card>
      ) : null}

      {inspection === null ? null : (
        <div className="memory-inspection-grid">
          <Card className="memory-record-card">
            <div className="card-heading-row">
              <div><p className="eyebrow">Assertion</p><h2>{readString(inspection.assertion, "predicate")}</h2></div>
              <Badge tone={status === "confirmed" ? "positive" : status === "disputed" ? "warning" : "danger"}>{titleCase(status)}</Badge>
            </div>
            <div className="memory-id-row">
              <code title={inspection.assertion.assertion_id}>{inspection.assertion.assertion_id}</code>
              <span>v{inspection.current_state.version}</span>
              <Button onClick={() => void copyAssertionId(inspection.assertion.assertion_id)} size="sm" tone="ghost" type="button">
                <Copy aria-hidden="true" size={14} /><span className="sr-only">Copy assertion ID</span>
              </Button>
            </div>
            <div className="memory-value">
              {contentDeleted ? (
                <p>Assertion content was deleted by owner request. Metadata, state history, and deletion evidence remain inspectable.</p>
              ) : assertionValue === undefined ? <p>No structured value recorded.</p> : Object.entries(assertionValue).map(([key, value]) => (
                <div key={key}><span>{titleCase(key)}</span><strong>{typeof value === "string" ? value : safeJson(value)}</strong></div>
              ))}
            </div>
            <dl className="detail-list memory-metadata">
              <div><dt>Epistemic status</dt><dd>{titleCase(readString(inspection.assertion, "epistemic_status"))}</dd></div>
              <div><dt>Source authority</dt><dd>{titleCase(readString(inspection.assertion, "source_authority"))}</dd></div>
              <div><dt>Sensitivity</dt><dd>{titleCase(readString(inspection.assertion, "sensitivity"))}</dd></div>
              <div><dt>Observed</dt><dd>{formatInstant(readString(inspection.assertion, "observed_at"))}</dd></div>
            </dl>
            {contentDeleted && deletionTombstone !== null ? (
              <div className="memory-deletion-disclosure">
                <div>
                  <span>Deleted</span>
                  <strong>{formatInstant(readString(deletionTombstone, "deleted_at"))}</strong>
                </div>
                <div>
                  <span>Tombstone</span>
                  <code>{shortId(readString(deletionTombstone, "tombstone_id"))}</code>
                </div>
                <div>
                  <span>Rebuild work</span>
                  <code>{shortId(readString(deletionTombstone, "rebuild_work_id"))}</code>
                </div>
                <div>
                  <span>Backup expiry</span>
                  <strong>{backupExpiry === null ? "Not disclosed" : titleCase(readString(backupExpiry, "state"))}</strong>
                </div>
              </div>
            ) : null}
            <div className="memory-actions">
              <Button disabled={!canMutate || contentDeleted} onClick={() => setAction("correct")}><PencilLine size={15} /> Correct</Button>
              <Button disabled={!canMutate || contentDeleted} onClick={() => setAction("dispute")}><AlertTriangle size={15} /> Dispute</Button>
              <Button disabled={!canMutate || contentDeleted} onClick={() => setAction("delete_content")} tone="danger"><Trash2 size={15} /> Delete content</Button>
              <Button disabled={!canMutate || contentDeleted} onClick={() => setAction("retract")} tone="danger"><Trash2 size={15} /> Retract</Button>
            </div>
          </Card>

          <div className="memory-history-column">
            <Card className="memory-lineage-card">
              <div className="subsection-heading"><GitBranch size={17} /><div><h2>Provenance</h2><p>{inspection.provenance_edges.length} recorded edges</p></div></div>
              {inspection.provenance_edges.length === 0 ? <p className="muted-copy">No upstream provenance edges are recorded.</p> : inspection.provenance_edges.map((edge, index) => (
                <ProvenanceEdgeDetails
                  currentAssertionId={inspection.assertion.assertion_id}
                  edge={edge}
                  index={index}
                  key={`${readString(edge, "edge_id")}-${index}`}
                  onInspectAssertion={inspectRelatedAssertion}
                />
              ))}
            </Card>
            <Card className="memory-lineage-card">
              <div className="subsection-heading"><History size={17} /><div><h2>State history</h2><p>Append-only owner corrections</p></div></div>
              {inspection.state_changes.length === 0 ? (
                <div className="history-empty"><CheckCircle2 size={17} /><span>No correction-state changes recorded.</span></div>
              ) : inspection.state_changes.map((change, index) => (
                <details className="record-details" key={`${readString(change, "change_id")}-${index}`}>
                  <summary><span>{stateChangeLabel(change)}</span><code>v{readNumber(change, "version")}</code></summary>
                  <pre>{safeJson(change)}</pre>
                </details>
              ))}
            </Card>
          </div>
        </div>
      )}

      <Modal
        description={modalDescription(action)}
        onClose={() => setAction(null)}
        open={action !== null && inspection !== null}
        title={modalTitle(action)}
      >
        <form className="stack-form" onSubmit={(event) => void submitAction(event)}>
          {action === "correct" ? (
            <>
              <label className="field-label" htmlFor="memory-correction">Corrected JSON object</label>
              <textarea className="json-editor" defaultValue={safeJson(assertionValue ?? {})} id="memory-correction" name="value" required rows={9} spellCheck={false} />
            </>
          ) : action === "delete_content" ? (
            <div className="destructive-confirmation danger">
              <AlertTriangle size={19} />
              <p>Delete the retained assertion value while preserving metadata, state history, tombstone evidence, and rebuild obligations?</p>
            </div>
          ) : (
            <div className={`destructive-confirmation ${action === "retract" ? "danger" : "warning"}`}>
              <AlertTriangle size={19} />
              <p>{action === "dispute" ? "Mark this assertion as contested while preserving its lineage?" : "Mark this assertion as retracted while preserving its correction history?"}</p>
            </div>
          )}
          <div className="modal-actions">
            <Button onClick={() => setAction(null)} type="button">Cancel</Button>
            <Button disabled={!canMutate} loading={mutating} tone={action === "retract" || action === "delete_content" ? "danger" : "primary"} type="submit">{confirmLabel(action)}</Button>
          </div>
        </form>
      </Modal>
    </div>
  );
}

function modalTitle(action: MemoryAction | null): string {
  if (action === "correct") {
    return "Correct memory";
  }
  if (action === "dispute") {
    return "Dispute memory";
  }
  if (action === "delete_content") {
    return "Delete memory content";
  }
  return "Retract memory";
}

function modalDescription(action: MemoryAction | null): string {
  if (action === "correct") {
    return "A correction appends a new version; it does not rewrite history.";
  }
  if (action === "delete_content") {
    return "Content deletion removes the retained value, not the accountability record.";
  }
  return "This appends an owner-authored state change to the assertion history.";
}

function confirmLabel(action: MemoryAction | null): string {
  if (action === "delete_content") {
    return "Delete content";
  }
  return `Confirm ${action ?? "change"}`;
}

function memoryActionPastTense(action: MemoryAction): string {
  if (action === "correct") {
    return "Memory corrected.";
  }
  if (action === "dispute") {
    return "Memory disputed.";
  }
  if (action === "delete_content") {
    return "Memory content deleted.";
  }
  return "Memory retracted.";
}

function stateChangeLabel(change: JsonObject): string {
  const explicitType = readString(change, "change_type");
  return titleCase(explicitType === "unknown" ? readString(change, "reason") : explicitType);
}

function ProvenanceEdgeDetails({
  currentAssertionId,
  edge,
  index,
  onInspectAssertion,
}: {
  readonly currentAssertionId: string;
  readonly edge: JsonObject;
  readonly index: number;
  readonly onInspectAssertion: (assertionId: string) => void;
}) {
  const edgeId = readString(edge, "edge_id");
  const fromId = readString(edge, "from_id");
  const toId = readString(edge, "to_id");
  const relation = provenanceRelation(edge);
  return (
    <details className="record-details" key={`${edgeId}-${index}`}>
      <summary><span>{titleCase(relation)}</span><code>{shortId(edgeId)}</code></summary>
      <div className="provenance-edge-summary">
        <ProvenanceEndpoint
          currentAssertionId={currentAssertionId}
          label="From"
          onInspectAssertion={onInspectAssertion}
          value={fromId}
        />
        <span className="provenance-relation">{titleCase(relation)}</span>
        <ProvenanceEndpoint
          currentAssertionId={currentAssertionId}
          label="To"
          onInspectAssertion={onInspectAssertion}
          value={toId}
        />
      </div>
      <pre>{safeJson(edge)}</pre>
    </details>
  );
}

function ProvenanceEndpoint({
  currentAssertionId,
  label,
  onInspectAssertion,
  value,
}: {
  readonly currentAssertionId: string;
  readonly label: string;
  readonly onInspectAssertion: (assertionId: string) => void;
  readonly value: string;
}) {
  const current = value === currentAssertionId;
  const navigable = value !== "unknown" && !current;
  return (
    <div className={`provenance-endpoint ${current ? "current" : ""}`}>
      <span>{label}</span>
      {navigable ? (
        <button
          aria-label={`Inspect related memory assertion ${value}`}
          onClick={() => onInspectAssertion(value)}
          type="button"
        >
          <strong>{shortId(value)}</strong>
          <ExternalLink size={13} />
        </button>
      ) : (
        <strong>{current ? "Current assertion" : shortId(value)}</strong>
      )}
    </div>
  );
}

function provenanceRelation(edge: JsonObject): string {
  const relation = readString(edge, "relation");
  return relation === "unknown" ? readString(edge, "relationship") : relation;
}
