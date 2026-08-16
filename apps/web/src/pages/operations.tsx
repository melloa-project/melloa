import { useCallback, useEffect, useState } from "react";
import {
  Archive,
  CameraOff,
  CheckCircle2,
  CircleAlert,
  Database,
  HardDrive,
  RefreshCw,
  ServerCog,
  ShieldCheck,
  TimerReset,
  WifiOff,
} from "lucide-react";

import type { OwnerHealthReport, OwnerMediaCatalog, OwnerRetentionReport } from "../api";
import { errorMessage, useMelloa } from "../app";
import { Badge, Button, Card, EmptyState, ErrorState, LoadingState, Metric, SectionHeader } from "../components/ui";
import { formatCount, formatInstant, titleCase } from "../lib/format";

type OperationsTab = "health" | "media" | "retention";

type OperationsSnapshot = {
  readonly health: OwnerHealthReport | null;
  readonly media: OwnerMediaCatalog | null;
  readonly retention: OwnerRetentionReport | null;
};

const emptySnapshot: OperationsSnapshot = { health: null, media: null, retention: null };

export function OperationsPage() {
  const { api } = useMelloa();
  const [tab, setTab] = useState<OperationsTab>("health");
  const [snapshot, setSnapshot] = useState<OperationsSnapshot>(emptySnapshot);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    const [health, media, retention] = await Promise.allSettled([
      api.healthDetail(),
      api.mediaCatalog(),
      api.retentionReport(),
    ]);
    setSnapshot({
      health: health.status === "fulfilled" ? health.value : null,
      media: media.status === "fulfilled" ? media.value : null,
      retention: retention.status === "fulfilled" ? retention.value : null,
    });
    const firstFailure = [health, media, retention].find((result) => result.status === "rejected");
    setError(firstFailure?.status === "rejected" ? errorMessage(firstFailure.reason) : null);
    setLoading(false);
  }, [api]);

  useEffect(() => {
    void load();
  }, [load]);

  const degradedComponents = snapshot.health?.components.filter((component) => component.state !== "healthy" && component.state !== "disabled").length ?? 0;
  const retainedObjects = snapshot.retention?.inventory.reduce((sum, item) => sum + (item.retained_objects ?? 0), 0) ?? 0;

  return (
    <div className="standard-page operations-page">
      <SectionHeader
        eyebrow="Owner operations"
        title="Operations"
        description="Health, capture gaps, retention coverage, and honest process-local limitations."
        action={<Button onClick={() => void load()} size="sm"><RefreshCw size={15} /> Refresh all</Button>}
      />

      {loading && snapshot.health === null ? <LoadingState label="Reading operational state" /> : null}
      {error === null ? null : <ErrorState title="Some operational data is unavailable" message={error} action={<Button onClick={() => void load()}>Try again</Button>} />}

      <section className="metric-grid compact" aria-label="Operations summary">
        <Metric label="Overall health" value={titleCase(snapshot.health?.overall_state ?? "unknown")} detail={`${degradedComponents} degraded components`} />
        <Metric label="Capture" value={snapshot.media?.capture_enabled === true ? "Enabled" : "Disabled"} detail={`${snapshot.media?.items.length ?? 0} metadata records`} />
        <Metric label="Retained objects" value={formatCount(retainedObjects)} detail={`${snapshot.retention?.policies.length ?? 0} explicit policies`} />
        <Metric label="Public ingress" value="None" detail="Private owner surface only" />
      </section>

      <div className="tab-list" role="tablist" aria-label="Operations views">
        <button aria-selected={tab === "health"} className={tab === "health" ? "active" : ""} onClick={() => setTab("health")} role="tab" type="button"><ServerCog size={16} /> Health</button>
        <button aria-selected={tab === "media"} className={tab === "media" ? "active" : ""} onClick={() => setTab("media")} role="tab" type="button"><HardDrive size={16} /> Media & gaps</button>
        <button aria-selected={tab === "retention"} className={tab === "retention" ? "active" : ""} onClick={() => setTab("retention")} role="tab" type="button"><Archive size={16} /> Retention</button>
      </div>

      {tab === "health" ? <HealthView report={snapshot.health} /> : null}
      {tab === "media" ? <MediaView report={snapshot.media} /> : null}
      {tab === "retention" ? <RetentionView report={snapshot.retention} /> : null}
    </div>
  );
}

function HealthView({ report }: { readonly report: OwnerHealthReport | null }) {
  if (report === null) {
    return <Card><EmptyState icon={WifiOff} title="Health report unavailable" description="The private core did not return component-level health." /></Card>;
  }
  return (
    <Card className="operations-panel">
      <div className="card-heading-row">
        <div><h2>Runtime components</h2><p>Required and optional components are shown separately, without hiding degraded state.</p></div>
        <Badge tone={report.overall_state === "healthy" ? "positive" : "warning"}>{titleCase(report.overall_state)}</Badge>
      </div>
      <div className="component-list">
        {report.components.map((component) => {
          const healthy = component.state === "healthy";
          const disabled = component.state === "disabled";
          const Icon = healthy ? CheckCircle2 : disabled ? WifiOff : CircleAlert;
          return (
            <article className="component-row" key={component.component_id}>
              <span className={`component-state ${healthy ? "healthy" : disabled ? "disabled" : "degraded"}`}><Icon size={17} /></span>
              <div><strong>{titleCase(component.component_id)}</strong><p>{component.summary}</p></div>
              <Badge tone={healthy ? "positive" : disabled ? "neutral" : "warning"}>{titleCase(component.state)}</Badge>
              <span className="component-meta">{titleCase(component.category)}{component.version === null || component.version === undefined ? "" : ` · ${component.version}`}</span>
              <Badge tone={component.required ? "info" : "neutral"}>{component.required ? "Required" : "Optional"}</Badge>
            </article>
          );
        })}
      </div>
      <p className="panel-updated">Observed {formatInstant(report.generated_at)}</p>
    </Card>
  );
}

function MediaView({ report }: { readonly report: OwnerMediaCatalog | null }) {
  if (report === null) {
    return <Card><EmptyState icon={CameraOff} title="Media report unavailable" description="No authenticated capture metadata report was returned." /></Card>;
  }
  return (
    <div className="operations-stack">
      <Card className="operations-panel">
        <div className="card-heading-row">
          <div><h2>Capture sources</h2><p>Source health and missing intervals remain visible even when capture is disabled.</p></div>
          <Badge tone={report.capture_enabled ? "positive" : "neutral"}>{report.capture_enabled ? "Capture enabled" : "Capture disabled"}</Badge>
        </div>
        {report.sources.length === 0 ? (
          <EmptyState icon={CameraOff} title="No capture sources configured" description="The current MVP does not capture ambient media." />
        ) : (
          <div className="source-grid">
            {report.sources.map((source) => (
              <article className="source-card" key={source.capability_id}>
                <div><strong>{titleCase(source.capability_id)}</strong><Badge tone={source.health_state === "healthy" ? "positive" : "warning"}>{titleCase(source.health_state)}</Badge></div>
                <p>{source.status_reason}</p>
                <dl className="detail-list">
                  <div><dt>Installed</dt><dd>{source.installed ? "Yes" : "No"}</dd></div>
                  <div><dt>Capture</dt><dd>{source.capture_enabled ? "Enabled" : "Disabled"}</dd></div>
                  <div><dt>Last capture</dt><dd>{formatInstant(source.last_capture_at)}</dd></div>
                  <div><dt>Missing intervals</dt><dd>{source.missing_intervals.length}</dd></div>
                </dl>
              </article>
            ))}
          </div>
        )}
      </Card>
      <Card className="operations-panel">
        <div className="card-heading-row"><div><h2>Retained media metadata</h2><p>Content is never served by this inspection endpoint.</p></div><Badge>{report.items.length} items</Badge></div>
        {report.items.length === 0 ? <EmptyState icon={HardDrive} title="No retained media" description="No media metadata is present in this runtime." /> : (
          <div className="inventory-table">
            {report.items.map((item) => (
              <div className="inventory-row" key={item.media_id}>
                <div><strong>{titleCase(item.media_type)}</strong><code>{item.media_id}</code></div>
                <span>{formatBytes(item.size_bytes)}</span>
                <span>{titleCase(item.retention_state)}</span>
                <span>Expires {formatInstant(item.expires_at)}</span>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}

function RetentionView({ report }: { readonly report: OwnerRetentionReport | null }) {
  if (report === null) {
    return <Card><EmptyState icon={TimerReset} title="Retention report unavailable" description="The private core did not return policy coverage." /></Card>;
  }
  return (
    <div className="operations-stack">
      <Card className="backup-disclosure">
        <span className="summary-icon"><Database size={18} /></span>
        <div><h2>Backup expiry</h2><p>{report.backup_expiry.status_reason}</p></div>
        <Badge tone={report.backup_expiry.state === "configured" ? "positive" : "warning"}>{titleCase(report.backup_expiry.state)}</Badge>
      </Card>
      <section className="retention-grid" aria-label="Retention policies">
        {report.policies.map((policy) => {
          const inventory = report.inventory.find((item) => item.policy_id === policy.policy_id);
          return (
            <Card className="retention-card" key={policy.policy_id}>
              <div className="retention-card-header"><div><p className="eyebrow">{titleCase(policy.data_category)}</p><h2>{policy.summary}</h2></div><Badge tone={policy.automatic_expiry ? "positive" : "warning"}>{titleCase(policy.mode)}</Badge></div>
              <dl className="detail-list">
                <div><dt>Coverage</dt><dd>{titleCase(inventory?.coverage ?? "unknown")}</dd></div>
                <div><dt>Retained</dt><dd>{formatCount(inventory?.retained_objects ?? 0)} objects</dd></div>
                <div><dt>Pending deletion</dt><dd>{formatCount(inventory?.pending_deletions ?? 0)}</dd></div>
                <div><dt>External copies</dt><dd>{titleCase(policy.external_copy_state)}</dd></div>
                <div><dt>Owner deletion</dt><dd>{titleCase(policy.deletion_control)}</dd></div>
                <div><dt>Next expiry</dt><dd>{formatInstant(inventory?.next_expiry_at)}</dd></div>
              </dl>
              <p className="retention-reason"><ShieldCheck size={14} /> {policy.status_reason}</p>
            </Card>
          );
        })}
      </section>
    </div>
  );
}

function formatBytes(value: number): string {
  if (value < 1_024) {
    return `${value} B`;
  }
  if (value < 1_048_576) {
    return `${(value / 1_024).toFixed(1)} KiB`;
  }
  return `${(value / 1_048_576).toFixed(1)} MiB`;
}
