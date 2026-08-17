import { useCallback, useEffect, useRef, useState } from "react";
import {
  ArrowUpRight,
  Bot,
  Coins,
  Eye,
  FileSearch,
  Fingerprint,
  MessageSquare,
  Network,
  RefreshCw,
  ShieldCheck,
  Timer,
  Zap,
} from "lucide-react";
import { useNavigate } from "react-router-dom";

import type { ModelActivityEntry, ModelActivityReport } from "../api";
import { errorMessage, useMelloa } from "../app";
import { Badge, Button, Card, EmptyState, ErrorState, LoadingState, Metric, SectionHeader } from "../components/ui";
import { formatDurationMs, formatGbp, formatInstant, shortId, titleCase } from "../lib/format";

type WindowOption = "24h" | "7d" | "30d";
type DisclosureFilter = "all" | "external" | "local";

const windows: ReadonlyArray<{ readonly value: WindowOption; readonly label: string; readonly hours: number }> = [
  { value: "24h", label: "24 hours", hours: 24 },
  { value: "7d", label: "7 days", hours: 24 * 7 },
  { value: "30d", label: "30 days", hours: 24 * 30 },
];

const disclosureFilters: ReadonlyArray<{ readonly value: DisclosureFilter; readonly label: string }> = [
  { value: "all", label: "All" },
  { value: "external", label: "External" },
  { value: "local", label: "Private" },
];

export function ActivityPage() {
  const { api } = useMelloa();
  const navigate = useNavigate();
  const [windowOption, setWindowOption] = useState<WindowOption>("7d");
  const [disclosureFilter, setDisclosureFilter] = useState<DisclosureFilter>("all");
  const [report, setReport] = useState<ModelActivityReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const loadRequestRef = useRef(0);

  const load = useCallback(async () => {
    const requestId = loadRequestRef.current + 1;
    loadRequestRef.current = requestId;
    const selectedHours = windowOption === "24h" ? 24 : windowOption === "30d" ? 24 * 30 : 24 * 7;
    setLoading(true);
    try {
      const end = new Date();
      const start = new Date(end.getTime() - selectedHours * 60 * 60 * 1_000);
      const nextReport = await api.modelActivity(start, end);
      if (requestId !== loadRequestRef.current) {
        return;
      }
      setReport(nextReport);
      setError(null);
    } catch (caught) {
      if (requestId !== loadRequestRef.current) {
        return;
      }
      setError(errorMessage(caught));
    } finally {
      if (requestId === loadRequestRef.current) {
        setLoading(false);
      }
    }
  }, [api, windowOption]);

  useEffect(() => {
    void load();
  }, [load]);

  const totalTokens = (report?.total_input_tokens ?? 0) + (report?.total_output_tokens ?? 0);
  const entries = report?.entries ?? [];
  const externalEntries = entries.filter((entry) => entry.external_disclosure);
  const localEntries = entries.filter((entry) => !entry.external_disclosure);
  const visibleEntries = disclosureFilter === "external"
    ? externalEntries
    : disclosureFilter === "local"
      ? localEntries
      : entries;

  const countForFilter = (filter: DisclosureFilter): number => {
    if (filter === "external") {
      return externalEntries.length;
    }
    if (filter === "local") {
      return localEntries.length;
    }
    return entries.length;
  };

  return (
    <div className="standard-page activity-page">
      <SectionHeader
        eyebrow="Model ledger"
        title="Activity"
        description="Every model run, disclosure, token, and recorded cost in one owner-readable view."
        action={(
          <div className="header-actions">
            <label className="select-field">
              <span className="sr-only">Activity window</span>
              <select value={windowOption} onChange={(event) => setWindowOption(event.target.value as WindowOption)}>
                {windows.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
              </select>
            </label>
            <Button onClick={() => void load()} size="sm"><RefreshCw size={15} /> Refresh</Button>
          </div>
        )}
      />

      {loading && report === null ? <LoadingState label="Reading model activity" /> : null}
      {error === null ? null : <ErrorState message={error} action={<Button onClick={() => void load()}>Try again</Button>} />}

      {report === null ? null : (
        <>
          <section className="metric-grid" aria-label="Model activity summary">
            <Metric label="Model runs" value={report.total_runs} detail={`${report.external_disclosure_runs} externally disclosed`} />
            <Metric label="Tokens" value={totalTokens.toLocaleString()} detail={`${report.total_input_tokens.toLocaleString()} in · ${report.total_output_tokens.toLocaleString()} out`} />
            <Metric label="Recorded cost" value={formatGbp(report.total_cost_gbp)} detail={`${formatGbp(report.external_cost_gbp)} external`} />
            <Metric label="Window" value={windows.find((item) => item.value === windowOption)?.label ?? "7 days"} detail={`Updated ${formatInstant(report.generated_at)}`} />
          </section>

          <Card className="data-card">
            <div className="card-heading-row">
              <div><h2>Run ledger</h2><p>Provider-neutral execution records tied back to canonical turns.</p></div>
              <Badge tone={report.external_disclosure_runs > 0 ? "warning" : "positive"}>
                {report.external_disclosure_runs > 0 ? <Eye size={13} /> : <ShieldCheck size={13} />}
                {report.external_disclosure_runs > 0 ? `${report.external_disclosure_runs} external` : "No external disclosure"}
              </Badge>
            </div>

            {report.entries.length === 0 ? (
              <EmptyState
                icon={Zap}
                title="No model runs in this window"
                description="Send Melli a message or choose a wider activity window."
                action={<Button onClick={() => navigate("/conversation")} tone="primary">Open conversation</Button>}
              />
            ) : visibleEntries.length === 0 ? (
              <>
                <ActivityFilter
                  active={disclosureFilter}
                  countForFilter={countForFilter}
                  onChange={setDisclosureFilter}
                />
                <EmptyState
                  icon={disclosureFilter === "external" ? Eye : ShieldCheck}
                  title={emptyFilterTitle(disclosureFilter)}
                  description="Choose a different disclosure filter or widen the activity window."
                />
              </>
            ) : (
              <>
                <ActivityFilter
                  active={disclosureFilter}
                  countForFilter={countForFilter}
                  onChange={setDisclosureFilter}
                />
                <div className="activity-list">
                  {visibleEntries.map((entry) => (
                    <ActivityRow
                      entry={entry}
                      key={entry.result_id}
                      onInspectMemory={(assertionId) => navigate(`/memory?assertion=${encodeURIComponent(assertionId)}`)}
                      onOpenRoute={(routeId) => navigate(`/providers?route=${encodeURIComponent(routeId)}`)}
                      onOpenThread={navigate}
                    />
                  ))}
                </div>
              </>
            )}
          </Card>

          <p className="page-footnote">
            <ShieldCheck size={14} /> Activity is an inspection surface; policy and Guardian authority remain outside this view.
          </p>
        </>
      )}
    </div>
  );
}

function ActivityRow({
  entry,
  onInspectMemory,
  onOpenRoute,
  onOpenThread,
}: {
  readonly entry: ModelActivityEntry;
  readonly onInspectMemory: (assertionId: string) => void;
  readonly onOpenRoute: (routeId: string) => void;
  readonly onOpenThread: (path: string) => void;
}) {
  const started = Date.parse(entry.started_at);
  const completed = Date.parse(entry.completed_at);
  const latency = Number.isFinite(started) && Number.isFinite(completed) ? completed - started : 0;
  const synthetic = isSyntheticActivityEntry(entry);

  return (
    <article className="activity-row">
      <div className="activity-route-icon"><Bot size={18} /></div>
      <div className="activity-identity">
        <strong>{entry.model_id}</strong>
        <span className="activity-route-label">{entry.provider_id} · {entry.route_id}</span>
        <span className="activity-run-identifiers" title={`Request ${entry.request_id}; Result ${entry.result_id}`}>
          Req {shortId(entry.request_id)} · Result {shortId(entry.result_id)}
        </span>
      </div>
      <div className="activity-facts">
        <span><Zap size={14} /> {(entry.input_tokens + entry.output_tokens).toLocaleString()}</span>
        <span><Coins size={14} /> {formatGbp(entry.cost_gbp)}</span>
        <span><Timer size={14} /> {formatDurationMs(latency)}</span>
      </div>
      <Badge tone={entry.external_disclosure ? "warning" : synthetic ? "violet" : "positive"}>
        {entry.external_disclosure ? "External" : synthetic ? "Synthetic fixture" : "Local"}
      </Badge>
      <div className="activity-time">
        <strong>{formatInstant(entry.completed_at)}</strong>
        <span>Turn {shortId(entry.turn_id)}</span>
      </div>
      <div className="activity-actions">
        <Button
          aria-label={`Open route contract for ${entry.route_id}`}
          onClick={() => onOpenRoute(entry.route_id)}
          size="icon"
          tone="ghost"
        >
          <Network size={17} />
        </Button>
        <Button
          aria-label={`Open turn inspection for ${entry.model_id}`}
          onClick={() => onOpenThread(`/conversation/${entry.thread_id}?turn=${encodeURIComponent(entry.turn_id)}`)}
          size="icon"
          tone="ghost"
        >
          <ArrowUpRight size={17} />
        </Button>
      </div>
      <ActivityDisclosure entry={entry} onInspectMemory={onInspectMemory} />
    </article>
  );
}

function isSyntheticActivityEntry(entry: ModelActivityEntry): boolean {
  return entry.provider_id === "provider.synthetic" || entry.route_id.startsWith("model.fake.");
}

function ActivityDisclosure({
  entry,
  onInspectMemory,
}: {
  readonly entry: ModelActivityEntry;
  readonly onInspectMemory: (assertionId: string) => void;
}) {
  const disclosure = entry.disclosure;
  if (disclosure === null || disclosure === undefined) {
    return null;
  }

  return (
    <div className="activity-disclosure" aria-label={`Disclosure evidence for ${entry.model_id}`}>
      <div className="activity-disclosure-fact">
        <FileSearch size={14} />
        <span>Manifest {shortId(disclosure.retrieval_manifest_id)}</span>
      </div>
      <div className="activity-disclosure-fact">
        <MessageSquare size={14} />
        <span>{disclosure.triggering_message_ids.length} trigger{disclosure.triggering_message_ids.length === 1 ? "" : "s"}</span>
      </div>
      <div className="activity-disclosure-fact">
        <Fingerprint size={14} />
        <span>{titleCase(disclosure.purpose)}</span>
      </div>
      <div className="activity-disclosure-attempts">
        {disclosure.external_attempts.map((attempt) => (
          <Badge key={`${attempt.route_id}-${attempt.started_at}`} tone={attempt.outcome === "succeeded" ? "warning" : "danger"}>
            {titleCase(attempt.route_id)} · {titleCase(attempt.outcome)}
          </Badge>
        ))}
      </div>
      {disclosure.memory_references.length === 0 ? (
        <div className="activity-disclosure-empty">No memory IDs were disclosed.</div>
      ) : (
        <div className="activity-memory-list" aria-label="Disclosed memory references">
          {disclosure.memory_references.map((reference) => (
            <button
              aria-label={`Inspect disclosed memory ${reference.assertion_id}`}
              className="activity-memory-chip"
              key={reference.citation_id}
              onClick={() => onInspectMemory(reference.assertion_id)}
              title="Inspect disclosed memory"
              type="button"
            >
              <strong>{shortId(reference.assertion_id)}</strong>
              <small>{titleCase(reference.sensitivity)} · {shortId(reference.citation_id)}</small>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function ActivityFilter({
  active,
  countForFilter,
  onChange,
}: {
  readonly active: DisclosureFilter;
  readonly countForFilter: (filter: DisclosureFilter) => number;
  readonly onChange: (filter: DisclosureFilter) => void;
}) {
  return (
    <div className="activity-toolbar">
      <div className="segmented-control" aria-label="Disclosure filter">
        {disclosureFilters.map((filter) => {
          const selected = active === filter.value;
          return (
            <Button
              key={filter.value}
              aria-pressed={selected}
              className="segmented-option"
              onClick={() => onChange(filter.value)}
              size="sm"
              tone={selected ? "primary" : "secondary"}
            >
              {filter.value === "external" ? <Eye size={14} /> : filter.value === "local" ? <ShieldCheck size={14} /> : <Zap size={14} />}
              {filter.label} {countForFilter(filter.value)}
            </Button>
          );
        })}
      </div>
    </div>
  );
}

function emptyFilterTitle(filter: DisclosureFilter): string {
  if (filter === "external") {
    return "No external runs in this window";
  }
  if (filter === "local") {
    return "No runs without external disclosure in this window";
  }
  return "No model runs in this window";
}
