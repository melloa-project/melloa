import { useCallback, useEffect, useState } from "react";
import {
  Archive,
  ArrowUpRight,
  Bot,
  Boxes,
  Clock3,
  Eye,
  FileText,
  GitBranch,
  MessageSquare,
  RefreshCw,
  Send,
  ShieldCheck,
} from "lucide-react";
import { useNavigate } from "react-router-dom";

import type { OwnerTimelineEvent, OwnerTimelineReport } from "../api";
import { errorMessage, useMelloa } from "../app";
import { Badge, Button, Card, EmptyState, ErrorState, LoadingState, Metric, SectionHeader } from "../components/ui";
import { formatCount, formatGbp, formatInstant, shortId, titleCase } from "../lib/format";

type WindowOption = "24h" | "7d" | "30d";
type TimelineFilter = "all" | "conversation" | "processing" | "delivery" | "model" | "audit";

const windows: ReadonlyArray<{ readonly value: WindowOption; readonly label: string; readonly hours: number }> = [
  { value: "24h", label: "24 hours", hours: 24 },
  { value: "7d", label: "7 days", hours: 24 * 7 },
  { value: "30d", label: "30 days", hours: 24 * 30 },
];

const filters: ReadonlyArray<{ readonly value: TimelineFilter; readonly label: string }> = [
  { value: "all", label: "All" },
  { value: "conversation", label: "Conversation" },
  { value: "processing", label: "Processing" },
  { value: "delivery", label: "Delivery" },
  { value: "model", label: "Model" },
  { value: "audit", label: "Audit" },
];

export function TimelinePage() {
  const { api } = useMelloa();
  const navigate = useNavigate();
  const [windowOption, setWindowOption] = useState<WindowOption>("7d");
  const [filter, setFilter] = useState<TimelineFilter>("all");
  const [report, setReport] = useState<OwnerTimelineReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    const selected = windows.find((option) => option.value === windowOption) ?? windows[1];
    setLoading(true);
    try {
      const end = new Date();
      const start = new Date(end.getTime() - (selected?.hours ?? 24 * 7) * 60 * 60 * 1_000);
      setReport(await api.ownerTimeline(start, end, 150));
      setError(null);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setLoading(false);
    }
  }, [api, windowOption]);

  useEffect(() => {
    void load();
  }, [load]);

  const entries = report?.entries ?? [];
  const visibleEntries = entries.filter((entry) => filter === "all" || eventGroup(entry) === filter);
  const modelEvents = entries.filter((entry) => eventGroup(entry) === "model");
  const externalEvents = modelEvents.filter((entry) => entry.status === "model.disclosure.external");
  const deliveryEvents = entries.filter((entry) => eventGroup(entry) === "delivery");

  return (
    <div className="standard-page timeline-page">
      <SectionHeader
        eyebrow="Owner timeline"
        title="Timeline"
        description="Chronological canonical records from the current MVP, without message text, prompts, model output, credentials, or tokens."
        action={(
          <div className="header-actions">
            <label className="select-field">
              <span className="sr-only">Timeline window</span>
              <select value={windowOption} onChange={(event) => setWindowOption(event.target.value as WindowOption)}>
                {windows.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
              </select>
            </label>
            <Button loading={loading} onClick={() => void load()} size="sm"><RefreshCw size={15} /> Refresh</Button>
          </div>
        )}
      />

      {loading && report === null ? <LoadingState label="Reading owner timeline" /> : null}
      {error === null ? null : <ErrorState message={error} action={<Button onClick={() => void load()}>Try again</Button>} />}

      {report === null ? null : (
        <>
          <section className="metric-grid" aria-label="Timeline summary">
            <Metric
              label="Timeline items"
              value={formatCount(report.matching_events)}
              detail={report.truncated ? `${report.total_events} newest shown` : `${report.total_events} shown`}
            />
            <Metric label="Model records" value={formatCount(modelEvents.length)} detail={`${externalEvents.length} external`} />
            <Metric label="Delivery records" value={formatCount(deliveryEvents.length)} detail="Exact-authority work only" />
            <Metric label="Window" value={windows.find((item) => item.value === windowOption)?.label ?? "7 days"} detail={`Updated ${formatInstant(report.generated_at)}`} />
          </section>

          <Card className="data-card timeline-card">
            <div className="card-heading-row">
              <div>
                <h2>Canonical timeline</h2>
                <p>Newest records first, scoped to current owner-visible stores.</p>
              </div>
              <div className="header-actions">
                {report.truncated ? <Badge tone="warning">{report.total_events} newest of {report.matching_events}</Badge> : null}
                <Badge tone={externalEvents.length > 0 ? "warning" : "positive"}>
                  {externalEvents.length > 0 ? <Eye size={13} /> : <ShieldCheck size={13} />}
                  {externalEvents.length > 0 ? `${externalEvents.length} external model` : "No external model"}
                </Badge>
              </div>
            </div>

            <TimelineFilterBar
              active={filter}
              countForFilter={(value) => countForFilter(entries, value)}
              onChange={setFilter}
            />

            {entries.length === 0 ? (
              <EmptyState
                icon={Clock3}
                title="No timeline records in this window"
                description="Conversation and processing records will appear here after canonical activity is accepted."
                action={<Button onClick={() => navigate("/conversation")} tone="primary">Open conversation</Button>}
              />
            ) : visibleEntries.length === 0 ? (
              <EmptyState
                icon={Boxes}
                title={`No ${filter} records in this window`}
                description="Choose another filter or widen the timeline window."
              />
            ) : (
              <div className="timeline-list">
                {visibleEntries.map((entry) => (
                  <TimelineRow entry={entry} key={entry.event_id} navigate={navigate} />
                ))}
              </div>
            )}
          </Card>

          <div className="timeline-disclosure-panel">
            <CoverageList title="Coverage" values={report.coverage} />
            <CoverageList title="Limits" values={report.limitations} />
          </div>
        </>
      )}
    </div>
  );
}

function TimelineFilterBar({
  active,
  countForFilter,
  onChange,
}: {
  readonly active: TimelineFilter;
  readonly countForFilter: (filter: TimelineFilter) => number;
  readonly onChange: (filter: TimelineFilter) => void;
}) {
  return (
    <div className="timeline-toolbar">
      <div className="segmented-control" role="toolbar" aria-label="Timeline filters">
        {filters.map((filter) => (
          <Button
            aria-pressed={active === filter.value}
            className={`segmented-option ${active === filter.value ? "active" : ""}`}
            key={filter.value}
            onClick={() => onChange(filter.value)}
            size="sm"
            tone={active === filter.value ? "primary" : "ghost"}
            type="button"
          >
            {filter.label} {countForFilter(filter.value)}
          </Button>
        ))}
      </div>
    </div>
  );
}

function TimelineRow({
  entry,
  navigate,
}: {
  readonly entry: OwnerTimelineEvent;
  readonly navigate: (path: string) => void;
}) {
  const group = eventGroup(entry);
  const Icon = iconForEvent(entry);
  const routeId = readString(entry.metadata, "route_id");
  const providerId = readString(entry.metadata, "provider_id");
  const inputTokens = readNumber(entry.metadata, "input_tokens");
  const outputTokens = readNumber(entry.metadata, "output_tokens");
  const costGbp = readNumber(entry.metadata, "cost_gbp");
  const externalDisclosure = readBoolean(entry.metadata, "external_disclosure");
  const adapter = readString(entry.metadata, "client_adapter");
  const exportId = readString(entry.metadata, "export_id");
  const sourceEventId = readString(entry.metadata, "source_event_id");
  const fileCount = readNumber(entry.metadata, "file_count");
  const exportedRecordCount = readNumber(entry.metadata, "exported_record_count");
  const encrypted = readBoolean(entry.metadata, "encrypted");

  return (
    <article className={`timeline-row timeline-row-${group}`}>
      <div className="timeline-marker"><Icon aria-hidden="true" size={18} /></div>
      <div className="timeline-main">
        <div className="timeline-row-title">
          <strong>{entry.summary}</strong>
          <Badge tone={toneForEvent(entry)}>{titleCase(entry.status ?? entry.kind)}</Badge>
        </div>
        <div className="timeline-row-meta">
          <span>{formatInstant(entry.occurred_at)}</span>
          <span>{titleCase(entry.source.replace(/^timeline[.-]source[.-]/, ""))}</span>
          {entry.sensitivity === null || entry.sensitivity === undefined ? null : <span>{titleCase(entry.sensitivity)}</span>}
          <span>{shortId(entry.event_id)}</span>
        </div>
        <div className="timeline-facts">
          {routeId === null ? null : <span><Bot size={13} /> {routeId}</span>}
          {providerId === null ? null : <span><GitBranch size={13} /> {providerId}</span>}
          {inputTokens === null || outputTokens === null ? null : (
            <span>{(inputTokens + outputTokens).toLocaleString()} tokens</span>
          )}
          {costGbp === null ? null : <span>{formatGbp(costGbp)}</span>}
          {externalDisclosure === null ? null : (
            <span>{externalDisclosure ? "External disclosure" : "Local/private route"}</span>
          )}
          {adapter === null ? null : <span><Send size={13} /> {adapter}</span>}
          {exportId === null ? null : <span><Archive size={13} /> {shortId(exportId)}</span>}
          {sourceEventId === null ? null : <span><FileText size={13} /> Event {shortId(sourceEventId)}</span>}
          {fileCount === null ? null : <span>{fileCount.toLocaleString()} files</span>}
          {exportedRecordCount === null ? null : <span>{exportedRecordCount.toLocaleString()} records</span>}
          {encrypted === null ? null : (
            <span>{encrypted ? "Encrypted package" : "Plaintext preview"}</span>
          )}
        </div>
      </div>
      <div className="timeline-actions">
        {entry.thread_id === null || entry.thread_id === undefined ? null : (
          <Button
            aria-label={`Open conversation ${entry.thread_id}`}
            onClick={() => navigate(conversationPath(entry))}
            size="icon"
            tone="ghost"
          >
            <ArrowUpRight size={17} />
          </Button>
        )}
      </div>
      <ReferenceList references={entry.references} navigate={navigate} />
    </article>
  );
}

function ReferenceList({
  references,
  navigate,
}: {
  readonly references: readonly string[];
  readonly navigate: (path: string) => void;
}) {
  if (references.length === 0) {
    return null;
  }
  const visibleReferences = references.slice(0, 8);
  return (
    <div className="timeline-references" aria-label="Canonical references">
      {visibleReferences.map((reference) => (
        <button
          className="timeline-reference-chip"
          key={reference}
          onClick={() => {
            if (reference.startsWith("assertion_")) {
              navigate(`/memory?assertion=${encodeURIComponent(reference)}`);
            }
          }}
          type="button"
        >
          {shortId(reference)}
        </button>
      ))}
      {references.length > visibleReferences.length ? (
        <span className="timeline-reference-overflow">+{references.length - visibleReferences.length}</span>
      ) : null}
    </div>
  );
}

function CoverageList({ title, values }: { readonly title: string; readonly values: readonly string[] }) {
  return (
    <section className="timeline-disclosure-list" aria-label={`Timeline ${title.toLowerCase()}`}>
      <h2>{title}</h2>
      <div>
        {values.map((value) => <Badge key={value} tone="info">{titleCase(value.replace(/^timeline[.-](coverage|limit)[.-]/, ""))}</Badge>)}
      </div>
    </section>
  );
}

function eventGroup(entry: OwnerTimelineEvent): TimelineFilter {
  if (entry.kind.startsWith("timeline.reply-processing.")) {
    return "processing";
  }
  if (entry.kind.startsWith("timeline.outbound-delivery.")) {
    return "delivery";
  }
  if (entry.kind.startsWith("timeline.model-route.")) {
    return "model";
  }
  if (entry.kind.startsWith("timeline.audit.")) {
    return "audit";
  }
  return "conversation";
}

function countForFilter(entries: readonly OwnerTimelineEvent[], filter: TimelineFilter): number {
  if (filter === "all") {
    return entries.length;
  }
  return entries.filter((entry) => eventGroup(entry) === filter).length;
}

function iconForEvent(entry: OwnerTimelineEvent) {
  const group = eventGroup(entry);
  if (group === "model") {
    return Bot;
  }
  if (group === "processing") {
    return GitBranch;
  }
  if (group === "delivery") {
    return Send;
  }
  if (group === "audit") {
    return ShieldCheck;
  }
  if (entry.kind === "timeline.conversation.thread-created") {
    return FileText;
  }
  return MessageSquare;
}

function toneForEvent(entry: OwnerTimelineEvent): "neutral" | "positive" | "warning" | "danger" | "info" | "violet" {
  if (entry.status?.includes("external") === true) {
    return "warning";
  }
  if (entry.status?.includes("dead") === true || entry.status?.includes("failed") === true) {
    return "danger";
  }
  if (entry.status?.includes("completed") === true || entry.status?.includes("delivered") === true) {
    return "positive";
  }
  if (eventGroup(entry) === "model") {
    return "violet";
  }
  if (eventGroup(entry) === "audit") {
    return "neutral";
  }
  return "info";
}

function conversationPath(entry: OwnerTimelineEvent): string {
  if (entry.thread_id === null || entry.thread_id === undefined) {
    return "/conversation";
  }
  const query = entry.turn_id === null || entry.turn_id === undefined
    ? ""
    : `?turn=${encodeURIComponent(entry.turn_id)}`;
  return `/conversation/${encodeURIComponent(entry.thread_id)}${query}`;
}

function readString(value: Record<string, unknown>, key: string): string | null {
  const item = value[key];
  return typeof item === "string" && item.length > 0 ? item : null;
}

function readNumber(value: Record<string, unknown>, key: string): number | null {
  const item = value[key];
  return typeof item === "number" && Number.isFinite(item) ? item : null;
}

function readBoolean(value: Record<string, unknown>, key: string): boolean | null {
  const item = value[key];
  return typeof item === "boolean" ? item : null;
}
