import { useCallback, useEffect, useRef, useState } from "react";
import {
  Archive,
  CameraOff,
  CheckCircle2,
  CircleAlert,
  Copy,
  Database,
  Download,
  FileCheck2,
  HardDrive,
  ListChecks,
  RefreshCw,
  ServerCog,
  ShieldCheck,
  TimerReset,
  WifiOff,
  type LucideIcon,
} from "lucide-react";

import type {
  OwnerExportReadinessReport,
  OwnerHealthReport,
  OwnerMediaCatalog,
  OwnerRetentionReport,
} from "../api";
import { errorMessage, useMelloa } from "../app";
import { Badge, Button, Card, EmptyState, ErrorState, LoadingState, Metric, SectionHeader } from "../components/ui";
import { formatCount, formatInstant, titleCase } from "../lib/format";

type OperationsTab = "health" | "media" | "retention" | "export";

type OperationsSnapshot = {
  readonly health: OwnerHealthReport | null;
  readonly media: OwnerMediaCatalog | null;
  readonly retention: OwnerRetentionReport | null;
  readonly exportReadiness: OwnerExportReadinessReport | null;
};

type ExportCommandKind = "export" | "validation" | "package" | "packageValidation";

type AttentionTone = "positive" | "warning" | "neutral";

type AttentionItem = {
  readonly id: string;
  readonly icon: LucideIcon;
  readonly title: string;
  readonly detail: string;
  readonly tone: AttentionTone;
  readonly tab: OperationsTab;
};

const emptySnapshot: OperationsSnapshot = {
  health: null,
  media: null,
  retention: null,
  exportReadiness: null,
};

export function OperationsPage() {
  const { api } = useMelloa();
  const [tab, setTab] = useState<OperationsTab>("health");
  const [snapshot, setSnapshot] = useState<OperationsSnapshot>(emptySnapshot);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const tabsRef = useRef<HTMLDivElement | null>(null);
  const loadRequestRef = useRef(0);

  const load = useCallback(async () => {
    const requestId = loadRequestRef.current + 1;
    loadRequestRef.current = requestId;
    setLoading(true);
    const [health, media, retention, exportReadiness] = await Promise.allSettled([
      api.healthDetail(),
      api.mediaCatalog(),
      api.retentionReport(),
      api.exportReadiness(),
    ]);
    if (requestId !== loadRequestRef.current) {
      return;
    }
    setSnapshot({
      health: health.status === "fulfilled" ? health.value : null,
      media: media.status === "fulfilled" ? media.value : null,
      retention: retention.status === "fulfilled" ? retention.value : null,
      exportReadiness: exportReadiness.status === "fulfilled" ? exportReadiness.value : null,
    });
    const firstFailure = [health, media, retention, exportReadiness].find((result) => result.status === "rejected");
    setError(firstFailure?.status === "rejected" ? errorMessage(firstFailure.reason) : null);
    setLoading(false);
  }, [api]);

  useEffect(() => {
    void load();
  }, [load]);

  const degradedComponents = snapshot.health?.components.filter((component) => component.state !== "healthy" && component.state !== "disabled").length ?? 0;
  const retainedObjects = snapshot.retention?.inventory.reduce((sum, item) => sum + (item.retained_objects ?? 0), 0) ?? 0;
  const exportRecords = snapshot.exportReadiness?.coverage.reduce(
    (sum, item) => sum + (item.estimated_records ?? 0),
    0,
  ) ?? 0;
  const attentionItems = operationsAttentionItems(snapshot);
  const selectAttentionTab = (nextTab: OperationsTab) => {
    setTab(nextTab);
    window.requestAnimationFrame(() => {
      if (typeof tabsRef.current?.scrollIntoView === "function") {
        tabsRef.current.scrollIntoView({ block: "start" });
      }
    });
  };

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
        <Metric label="Export" value={snapshot.exportReadiness === null ? "Unknown" : "Preview"} detail={`${formatCount(exportRecords)} estimated records`} />
      </section>

      <OperationsAttentionSummary items={attentionItems} onSelectTab={selectAttentionTab} />

      <div className="tab-list" ref={tabsRef} role="tablist" aria-label="Operations views">
        <button aria-selected={tab === "health"} className={tab === "health" ? "active" : ""} onClick={() => setTab("health")} role="tab" type="button"><ServerCog size={16} /> Health</button>
        <button aria-selected={tab === "media"} className={tab === "media" ? "active" : ""} onClick={() => setTab("media")} role="tab" type="button"><HardDrive size={16} /> Media & gaps</button>
        <button aria-selected={tab === "retention"} className={tab === "retention" ? "active" : ""} onClick={() => setTab("retention")} role="tab" type="button"><Archive size={16} /> Retention</button>
        <button aria-selected={tab === "export"} className={tab === "export" ? "active" : ""} onClick={() => setTab("export")} role="tab" type="button"><Download size={16} /> Export</button>
      </div>

      {tab === "health" ? <HealthView report={snapshot.health} /> : null}
      {tab === "media" ? <MediaView report={snapshot.media} /> : null}
      {tab === "retention" ? <RetentionView report={snapshot.retention} /> : null}
      {tab === "export" ? <ExportView report={snapshot.exportReadiness} /> : null}
    </div>
  );
}

function OperationsAttentionSummary({
  items,
  onSelectTab,
}: {
  readonly items: readonly AttentionItem[];
  readonly onSelectTab: (tab: OperationsTab) => void;
}) {
  return (
    <Card aria-label="Owner attention summary" className="operations-attention">
      <div className="card-heading-row">
        <div>
          <h2>Owner attention</h2>
          <p>Current preview boundaries and degraded checks that affect trust in this run.</p>
        </div>
        <Badge tone={items.some((item) => item.tone === "warning") ? "warning" : "positive"}>
          {items.filter((item) => item.tone === "warning").length} action items
        </Badge>
      </div>
      <div className="attention-list">
        {items.map((item) => {
          const Icon = item.icon;
          return (
            <button
              className={`attention-row attention-${item.tone}`}
              key={item.id}
              onClick={() => onSelectTab(item.tab)}
              type="button"
            >
              <span className={`component-state ${item.tone === "positive" ? "healthy" : item.tone === "neutral" ? "disabled" : ""}`}>
                <Icon aria-hidden="true" size={17} />
              </span>
              <span>
                <strong>{item.title}</strong>
                <small>{item.detail}</small>
              </span>
              <Badge tone={item.tone === "positive" ? "positive" : item.tone === "warning" ? "warning" : "neutral"}>
                {titleCase(item.tab)}
              </Badge>
            </button>
          );
        })}
      </div>
    </Card>
  );
}

function operationsAttentionItems(snapshot: OperationsSnapshot): readonly AttentionItem[] {
  const items: AttentionItem[] = [];
  const health = snapshot.health;
  if (health === null) {
    items.push({
      id: "health-unavailable",
      icon: CircleAlert,
      title: "Health report unavailable",
      detail: "The private core did not return component state.",
      tone: "warning",
      tab: "health",
    });
  } else {
    const requiredIssues = health.components.filter((component) => component.required && component.state !== "healthy");
    const optionalIssues = health.components.filter((component) => !component.required && component.state !== "healthy" && component.state !== "disabled");
    if (requiredIssues.length > 0) {
      items.push({
        id: "required-health",
        icon: CircleAlert,
        title: `${requiredIssues.length} required component${requiredIssues.length === 1 ? " needs" : "s need"} attention`,
        detail: requiredIssues.map((component) => titleCase(component.component_id)).join(", "),
        tone: "warning",
        tab: "health",
      });
    } else if (optionalIssues.length > 0) {
      items.push({
        id: "optional-health",
        icon: CircleAlert,
        title: `${optionalIssues.length} optional component${optionalIssues.length === 1 ? "" : "s"} degraded`,
        detail: optionalIssues.map((component) => titleCase(component.component_id)).join(", "),
        tone: "warning",
        tab: "health",
      });
    } else {
      const requiredHealthy = health.components.filter((component) => component.required).length;
      items.push({
        id: "health-ok",
        icon: CheckCircle2,
        title: "Required runtime checks are healthy",
        detail: `${requiredHealthy} required component${requiredHealthy === 1 ? "" : "s"} reported healthy.`,
        tone: "positive",
        tab: "health",
      });
    }
  }

  const media = snapshot.media;
  if (media === null) {
    items.push({
      id: "media-unavailable",
      icon: CameraOff,
      title: "Capture state unavailable",
      detail: "The media metadata endpoint did not respond.",
      tone: "warning",
      tab: "media",
    });
  } else if (!media.capture_enabled) {
    items.push({
      id: "media-disabled",
      icon: CameraOff,
      title: "Camera capture is disabled",
      detail: "The current MVP should not be treated as ambient observation.",
      tone: "neutral",
      tab: "media",
    });
  }

  const retention = snapshot.retention;
  if (retention === null) {
    items.push({
      id: "retention-unavailable",
      icon: TimerReset,
      title: "Retention report unavailable",
      detail: "Owner-visible deletion and backup-expiry state could not be read.",
      tone: "warning",
      tab: "retention",
    });
  } else if (retention.backup_expiry.state !== "configured") {
    items.push({
      id: "backup-not-configured",
      icon: TimerReset,
      title: "Backup is not configured",
      detail: titleCase(retention.backup_expiry.status_reason),
      tone: "warning",
      tab: "retention",
    });
  }

  const exportReadiness = snapshot.exportReadiness;
  if (exportReadiness === null) {
    items.push({
      id: "export-unavailable",
      icon: Download,
      title: "Export readiness unavailable",
      detail: "The owner export coverage endpoint did not respond.",
      tone: "warning",
      tab: "export",
    });
  } else {
    const included = exportReadiness.coverage.filter((item) => item.included).length;
    const excluded = exportReadiness.coverage.length - included;
    if (excluded > 0 || !exportReadiness.encrypted) {
      items.push({
        id: "export-preview",
        icon: ListChecks,
        title: "Export remains a preview",
        detail: `${included} groups included, ${excluded} explicit gaps, ${exportReadiness.encrypted ? "encrypted" : "plaintext"} inner bundle.`,
        tone: "warning",
        tab: "export",
      });
    }
  }

  return items;
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
  const auditPolicy = report.policies.find((policy) => policy.policy_id === "retention.audit-ledger");
  const auditInventory = report.inventory.find((item) => item.policy_id === "retention.audit-ledger");
  return (
    <div className="operations-stack">
      <Card className="backup-disclosure">
        <span className="summary-icon"><Database size={18} /></span>
        <div><h2>Backup expiry</h2><p>{report.backup_expiry.status_reason}</p></div>
        <Badge tone={report.backup_expiry.state === "configured" ? "positive" : "warning"}>{titleCase(report.backup_expiry.state)}</Badge>
      </Card>
      {auditPolicy === undefined && auditInventory === undefined ? null : (
        <Card className="operations-panel">
          <div className="card-heading-row">
            <div>
              <h2>Content-free audit ledger</h2>
              <p>{auditPolicy?.summary ?? "Security and action evidence is counted without exposing audit payloads."}</p>
            </div>
            <Badge tone={auditInventory?.coverage === "complete" ? "positive" : "warning"}>{titleCase(auditInventory?.coverage ?? "unknown")}</Badge>
          </div>
          <dl className="detail-list">
            <div><dt>Audit records</dt><dd>{formatInventoryObjects(auditInventory?.retained_objects)}</dd></div>
            <div><dt>Retained bytes</dt><dd>{formatInventoryBytes(auditInventory?.retained_bytes)}</dd></div>
            <div><dt>Oldest retained</dt><dd>{formatInstant(auditInventory?.oldest_retained_at)}</dd></div>
            <div><dt>Deletion control</dt><dd>{titleCase(auditPolicy?.deletion_control ?? "unknown")}</dd></div>
          </dl>
          <p className="retention-reason"><ShieldCheck size={14} /> Security events are exposed here only as aggregate counts; credentials, cookies, tokens, prompts, and raw model output are not shown.</p>
        </Card>
      )}
      <section className="retention-grid" aria-label="Retention policies">
        {report.policies.map((policy) => {
          const inventory = report.inventory.find((item) => item.policy_id === policy.policy_id);
          return (
            <Card className="retention-card" key={policy.policy_id}>
              <div className="retention-card-header"><div><p className="eyebrow">{titleCase(policy.data_category)}</p><h2>{policy.summary}</h2></div><Badge tone={policy.automatic_expiry ? "positive" : "warning"}>{titleCase(policy.mode)}</Badge></div>
              <dl className="detail-list">
                <div><dt>Coverage</dt><dd>{titleCase(inventory?.coverage ?? "unknown")}</dd></div>
                <div><dt>Retained</dt><dd>{formatInventoryObjects(inventory?.retained_objects)}</dd></div>
                <div><dt>Retained bytes</dt><dd>{formatInventoryBytes(inventory?.retained_bytes)}</dd></div>
                <div><dt>Pending deletion</dt><dd>{formatInventoryCount(inventory?.pending_deletions)}</dd></div>
                <div><dt>Deletion receipts</dt><dd>{formatInventoryCount(inventory?.deletion_receipts)}</dd></div>
                <div><dt>External copies</dt><dd>{titleCase(policy.external_copy_state)}</dd></div>
                <div><dt>Owner deletion</dt><dd>{titleCase(policy.deletion_control)}</dd></div>
                <div><dt>Oldest retained</dt><dd>{formatInstant(inventory?.oldest_retained_at)}</dd></div>
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

function ExportView({ report }: { readonly report: OwnerExportReadinessReport | null }) {
  const { api, canMutate, notify } = useMelloa();
  const [copyState, setCopyState] = useState<{
    readonly command: ExportCommandKind;
    readonly status: "copied" | "failed";
  } | null>(null);
  const [downloading, setDownloading] = useState(false);
  if (report === null) {
    return <Card><EmptyState icon={Download} title="Export report unavailable" description="The private core did not return owner export readiness." /></Card>;
  }
  const includedCoverage = report.coverage.filter((item) => item.included);
  const excludedCoverage = report.coverage.filter((item) => !item.included);
  const implementedValidationChecks = report.validation_checks.filter((item) => item.implemented).length;
  const packageReadiness = report.encrypted_package;
  const packageCommand = packageReadiness.supported ? packageReadiness.package_command ?? null : null;
  const packageValidationCommand = packageReadiness.supported ? packageReadiness.validation_command ?? null : null;
  const packageSupported = packageCommand !== null && packageValidationCommand !== null;
  const copyCommand = async (command: ExportCommandKind, value: string) => {
    try {
      if (navigator.clipboard === undefined) {
        throw new Error("Clipboard API unavailable");
      }
      await navigator.clipboard.writeText(value);
      setCopyState({ command, status: "copied" });
    } catch {
      setCopyState({ command, status: "failed" });
    }
  };
  const downloadCurrentExport = async () => {
    if (!canMutate) {
      notify("Unlock owner changes before downloading the current export.", "error");
      return;
    }
    setDownloading(true);
    try {
      const archive = await api.downloadExportPreview();
      const objectUrl = URL.createObjectURL(archive.blob);
      try {
        const link = document.createElement("a");
        link.href = objectUrl;
        link.download = archive.filename;
        document.body.append(link);
        try {
          link.click();
        } finally {
          link.remove();
        }
      } finally {
        URL.revokeObjectURL(objectUrl);
      }
      notify("Validated unencrypted export downloaded.", "success");
    } catch (caught) {
      notify(errorMessage(caught), "error");
    } finally {
      setDownloading(false);
    }
  };
  return (
    <div className="operations-stack">
      <Card className="operations-panel export-summary-panel">
        <div className="card-heading-row">
          <div>
            <h2>Canonical owner export</h2>
            <p>{report.format_id}</p>
          </div>
          <Badge tone={report.encrypted ? "positive" : "warning"}>{report.encrypted ? "Encrypted" : "Unencrypted preview"}</Badge>
        </div>
        <div className="export-capability-grid">
          <div><span>Included groups</span><strong>{includedCoverage.length} of {report.coverage.length}</strong></div>
          <div><span>Validation checks</span><strong>{implementedValidationChecks} of {report.validation_checks.length}</strong></div>
          <div><span>Known gaps</span><strong>{excludedCoverage.length}</strong></div>
          <div><span>Inner bundle</span><strong>{report.encrypted ? "Encrypted" : "Plaintext"}</strong></div>
          <div><span>Package encryption</span><strong>{packageSupported ? packageReadiness.cipher : "Unavailable"}</strong></div>
        </div>
        <div className="export-command-grid" aria-label="Live export download">
          <div>
            <div className="export-command-header">
              <span>Live runtime bundle</span>
              <Button
                disabled={!canMutate}
                loading={downloading}
                onClick={() => void downloadCurrentExport()}
                size="sm"
                tone="primary"
                type="button"
              >
                <Download size={14} /> Download current ZIP
              </Button>
            </div>
            <small>Validated before download. The ZIP is not encrypted and excludes blobs and SQL snapshots.</small>
          </div>
        </div>
        {packageSupported ? (
          <div className="export-command-grid" aria-label="Encrypted package commands">
            <div>
              <div className="export-command-header">
                <span>Encrypted package</span>
                <Badge tone="positive">{packageReadiness.package_format_id}</Badge>
              </div>
              <small>{packageReadiness.cipher} with {packageReadiness.kdf}; passphrase file mode {packageReadiness.required_file_mode}</small>
            </div>
            <CommandBlock
              command={packageCommand}
              copied={copyState?.command === "package" ? copyState.status : null}
              label="Package command"
              onCopy={() => void copyCommand("package", packageCommand)}
            />
            <CommandBlock
              command={packageValidationCommand}
              copied={copyState?.command === "packageValidation" ? copyState.status : null}
              label="Package validation command"
              onCopy={() => void copyCommand("packageValidation", packageValidationCommand)}
            />
          </div>
        ) : null}
        <div className="export-command-grid" aria-label="Export commands">
          <CommandBlock
            command={report.cli_command}
            copied={copyState?.command === "export" ? copyState.status : null}
            label="Export command"
            onCopy={() => void copyCommand("export", report.cli_command)}
          />
          <CommandBlock
            command={report.validation_command}
            copied={copyState?.command === "validation" ? copyState.status : null}
            label="Validation command"
            onCopy={() => void copyCommand("validation", report.validation_command)}
          />
        </div>
      </Card>
      <Card className="operations-panel">
        <div className="card-heading-row"><div><h2>Included artifacts</h2><p>Records that the current preview writes into the bundle.</p></div><Badge>{includedCoverage.length} included</Badge></div>
        <div className="export-coverage-list">
          {includedCoverage.map((item) => (
            <article className="export-coverage-row" key={item.group_id}>
              <span className="component-state healthy">
                <FileCheck2 size={17} />
              </span>
              <div>
                <strong>{titleCase(item.group_id.replace(/^export[.-]/, ""))}</strong>
                <p>{item.summary}</p>
                {item.estimated_records === null || item.estimated_records === undefined ? null : (
                  <span className="export-record-count">{formatEstimatedRecords(item.estimated_records)}</span>
                )}
                {item.artifact_path === null || item.artifact_path === undefined ? null : (
                  <code>{item.artifact_path}</code>
                )}
              </div>
              <Badge tone="positive">Included</Badge>
            </article>
          ))}
        </div>
      </Card>
      <Card className="operations-panel">
        <div className="card-heading-row"><div><h2>Explicit gaps</h2><p>Export capabilities that remain deliberately unavailable in this preview.</p></div><Badge tone="warning">{excludedCoverage.length} gaps</Badge></div>
        <div className="export-coverage-list">
          {excludedCoverage.map((item) => (
            <article className="export-coverage-row" key={item.group_id}>
              <span className="component-state disabled">
                <WifiOff size={17} />
              </span>
              <div>
                <strong>{titleCase(item.group_id.replace(/^export[.-]/, ""))}</strong>
                <p>{item.summary}</p>
              </div>
              <Badge tone="neutral">Excluded</Badge>
            </article>
          ))}
        </div>
      </Card>
      <Card className="operations-panel">
        <div className="card-heading-row">
          <div><h2>Import validation scope</h2><p>Dry-run checks are separated from restore work that still remains pending.</p></div>
          <Badge>{implementedValidationChecks} checks</Badge>
        </div>
        <div className="export-validation-list">
          {report.validation_checks.map((item) => (
            <article className="export-validation-row" key={item.check_id}>
              <span className={`component-state ${item.implemented ? "healthy" : "disabled"}`}>
                {item.implemented ? <FileCheck2 size={17} /> : <WifiOff size={17} />}
              </span>
              <div>
                <strong>{titleCase(item.check_id.replace(/^export[.-]validation[.-]/, ""))}</strong>
                <p>{item.summary}</p>
              </div>
              <Badge tone={item.implemented ? "positive" : "warning"}>{item.implemented ? "Checked" : "Pending"}</Badge>
            </article>
          ))}
        </div>
      </Card>
      <Card className="backup-disclosure">
        <span className="summary-icon"><ShieldCheck size={18} /></span>
        <div><h2>Limitations</h2><p>{[...report.limitations, ...packageReadiness.limitations].map(titleCase).join(" · ")}</p></div>
        <Badge tone="warning">Preview</Badge>
      </Card>
    </div>
  );
}

function CommandBlock({
  command,
  copied,
  label,
  onCopy,
}: {
  readonly command: string;
  readonly copied: "copied" | "failed" | null;
  readonly label: string;
  readonly onCopy: () => void;
}) {
  return (
    <div>
      <div className="export-command-header">
        <span>{label}</span>
        <Button onClick={onCopy} size="sm" tone="ghost" type="button">
          <Copy size={14} /> Copy
        </Button>
      </div>
      <code>{command}</code>
      {copied === null ? null : (
        <p className="command-copy-status" role="status">
          {copied === "copied" ? `${label} copied` : `${label} copy failed`}
        </p>
      )}
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

function formatEstimatedRecords(value: number): string {
  return `${formatCount(value)} estimated ${value === 1 ? "record" : "records"}`;
}

function formatInventoryCount(value: number | null | undefined): string {
  return value === null || value === undefined ? "Not measured" : formatCount(value);
}

function formatInventoryObjects(value: number | null | undefined): string {
  if (value === null || value === undefined) {
    return "Not measured";
  }
  return `${formatCount(value)} ${value === 1 ? "object" : "objects"}`;
}

function formatInventoryBytes(value: number | null | undefined): string {
  return value === null || value === undefined ? "Not measured" : formatBytes(value);
}
