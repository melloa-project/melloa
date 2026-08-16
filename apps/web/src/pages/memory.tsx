import { type FormEvent, useCallback, useEffect, useState } from "react";
import {
  AlertTriangle,
  Brain,
  CheckCircle2,
  GitBranch,
  History,
  PencilLine,
  Search,
  ShieldCheck,
  Trash2,
} from "lucide-react";
import { useSearchParams } from "react-router-dom";

import type { MemoryInspection } from "../api";
import { errorMessage, useMelloa } from "../app";
import { Badge, Button, Card, EmptyState, ErrorState, LoadingState, Modal, SectionHeader } from "../components/ui";
import { formatInstant, readString, safeJson, shortId, titleCase } from "../lib/format";

type MemoryAction = "correct" | "dispute" | "retract";

export function MemoryPage() {
  const { api, canMutate, notify } = useMelloa();
  const [searchParams, setSearchParams] = useSearchParams();
  const [query, setQuery] = useState(searchParams.get("assertion") ?? "");
  const [inspection, setInspection] = useState<MemoryInspection | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [action, setAction] = useState<MemoryAction | null>(null);
  const [mutating, setMutating] = useState(false);

  const inspect = useCallback(async (assertionId: string) => {
    const normalized = assertionId.trim();
    if (normalized.length === 0) {
      return;
    }
    setLoading(true);
    try {
      setInspection(await api.inspectMemory(normalized));
      setSearchParams({ assertion: normalized }, { replace: true });
      setError(null);
    } catch (caught) {
      setInspection(null);
      setError(errorMessage(caught));
    } finally {
      setLoading(false);
    }
  }, [api, setSearchParams]);

  useEffect(() => {
    const assertionId = searchParams.get("assertion");
    if (assertionId !== null && assertionId.length > 0) {
      setQuery(assertionId);
      void inspect(assertionId);
    }
  }, []);

  function submitSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void inspect(query);
  }

  async function submitAction(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (action === null || inspection === null) {
      return;
    }
    setMutating(true);
    try {
      const assertionId = inspection.assertion.assertion_id;
      const version = inspection.current_state.version;
      if (action === "correct") {
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
      notify(`Memory ${action === "correct" ? "corrected" : action === "dispute" ? "disputed" : "retracted"}.`, "success");
    } catch (caught) {
      notify(errorMessage(caught), "error");
    } finally {
      setMutating(false);
    }
  }

  const status = inspection?.current_state.current_status ?? "unknown";
  const assertionValue = inspection?.assertion.value;

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
            <div className="memory-id-row"><code>{inspection.assertion.assertion_id}</code><span>v{inspection.current_state.version}</span></div>
            <div className="memory-value">
              {assertionValue === undefined ? <p>No structured value recorded.</p> : Object.entries(assertionValue).map(([key, value]) => (
                <div key={key}><span>{titleCase(key)}</span><strong>{typeof value === "string" ? value : safeJson(value)}</strong></div>
              ))}
            </div>
            <dl className="detail-list memory-metadata">
              <div><dt>Epistemic status</dt><dd>{titleCase(readString(inspection.assertion, "epistemic_status"))}</dd></div>
              <div><dt>Source authority</dt><dd>{titleCase(readString(inspection.assertion, "source_authority"))}</dd></div>
              <div><dt>Sensitivity</dt><dd>{titleCase(readString(inspection.assertion, "sensitivity"))}</dd></div>
              <div><dt>Observed</dt><dd>{formatInstant(readString(inspection.assertion, "observed_at"))}</dd></div>
            </dl>
            <div className="memory-actions">
              <Button disabled={!canMutate} onClick={() => setAction("correct")}><PencilLine size={15} /> Correct</Button>
              <Button disabled={!canMutate} onClick={() => setAction("dispute")}><AlertTriangle size={15} /> Dispute</Button>
              <Button disabled={!canMutate} onClick={() => setAction("retract")} tone="danger"><Trash2 size={15} /> Retract</Button>
            </div>
          </Card>

          <div className="memory-history-column">
            <Card className="memory-lineage-card">
              <div className="subsection-heading"><GitBranch size={17} /><div><h2>Provenance</h2><p>{inspection.provenance_edges.length} recorded edges</p></div></div>
              {inspection.provenance_edges.length === 0 ? <p className="muted-copy">No upstream provenance edges are recorded.</p> : inspection.provenance_edges.map((edge, index) => (
                <details className="record-details" key={`${readString(edge, "edge_id")}-${index}`}>
                  <summary><span>{titleCase(readString(edge, "relationship"))}</span><code>{shortId(readString(edge, "edge_id"))}</code></summary>
                  <pre>{safeJson(edge)}</pre>
                </details>
              ))}
            </Card>
            <Card className="memory-lineage-card">
              <div className="subsection-heading"><History size={17} /><div><h2>State history</h2><p>Append-only owner corrections</p></div></div>
              {inspection.state_changes.length === 0 ? (
                <div className="history-empty"><CheckCircle2 size={17} /><span>No correction-state changes recorded.</span></div>
              ) : inspection.state_changes.map((change, index) => (
                <details className="record-details" key={`${readString(change, "change_id")}-${index}`}>
                  <summary><span>{titleCase(readString(change, "change_type"))}</span><code>v{readString(change, "version")}</code></summary>
                  <pre>{safeJson(change)}</pre>
                </details>
              ))}
            </Card>
          </div>
        </div>
      )}

      <Modal
        description={action === "correct" ? "A correction appends a new version; it does not rewrite history." : "This appends an owner-authored state change to the assertion history."}
        onClose={() => setAction(null)}
        open={action !== null && inspection !== null}
        title={action === "correct" ? "Correct memory" : action === "dispute" ? "Dispute memory" : "Retract memory"}
      >
        <form className="stack-form" onSubmit={(event) => void submitAction(event)}>
          {action === "correct" ? (
            <>
              <label className="field-label" htmlFor="memory-correction">Corrected JSON object</label>
              <textarea className="json-editor" defaultValue={safeJson(assertionValue ?? {})} id="memory-correction" name="value" required rows={9} spellCheck={false} />
            </>
          ) : (
            <div className={`destructive-confirmation ${action === "retract" ? "danger" : "warning"}`}>
              <AlertTriangle size={19} />
              <p>{action === "dispute" ? "Mark this assertion as contested while preserving its lineage?" : "Mark this assertion as retracted while preserving its correction history?"}</p>
            </div>
          )}
          <div className="modal-actions">
            <Button onClick={() => setAction(null)} type="button">Cancel</Button>
            <Button loading={mutating} tone={action === "retract" ? "danger" : "primary"} type="submit">Confirm {action}</Button>
          </div>
        </form>
      </Modal>
    </div>
  );
}
