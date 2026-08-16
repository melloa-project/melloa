import { useCallback, useEffect, useState } from "react";
import {
  Bot,
  CheckCircle2,
  CircleAlert,
  Clock3,
  Coins,
  Cpu,
  HardDrive,
  KeyRound,
  Network,
  RefreshCw,
  ShieldCheck,
  SquareTerminal,
  WifiOff,
} from "lucide-react";

import type { ModelRouteStatus, OwnerModelRouteReport } from "../api";
import { errorMessage, useMelloa } from "../app";
import { Badge, Button, Card, EmptyState, ErrorState, LoadingState, SectionHeader } from "../components/ui";
import { formatDurationMs, formatGbp, formatInstant, titleCase } from "../lib/format";

export function ProvidersPage() {
  const { api } = useMelloa();
  const [report, setReport] = useState<OwnerModelRouteReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setReport(await api.modelRoutes());
      setError(null);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setLoading(false);
    }
  }, [api]);

  useEffect(() => {
    void load();
  }, [load]);

  const activeRoutes = report?.routes.filter((route) => route.health.state === "healthy").length ?? 0;
  const externalRoutes = report?.routes.filter((route) => route.external_disclosure).length ?? 0;

  return (
    <div className="standard-page providers-page">
      <SectionHeader
        eyebrow="Provider-neutral gateway"
        title="Providers"
        description="Inspect the configured routes Melli may use. Selection remains capability- and policy-bounded."
        action={<Button onClick={() => void load()} size="sm"><RefreshCw size={15} /> Refresh health</Button>}
      />

      {loading && report === null ? <LoadingState label="Checking configured routes" /> : null}
      {error === null ? null : <ErrorState message={error} action={<Button onClick={() => void load()}>Try again</Button>} />}

      {report === null ? null : (
        <>
          <section className="provider-summary" aria-label="Provider route summary">
            <div><span className="summary-icon positive"><CheckCircle2 size={18} /></span><strong>{activeRoutes}</strong><small>healthy routes</small></div>
            <div><span className="summary-icon"><Cpu size={18} /></span><strong>{report.routes.length}</strong><small>configured routes</small></div>
            <div><span className={`summary-icon ${externalRoutes > 0 ? "warning" : "positive"}`}><Network size={18} /></span><strong>{externalRoutes}</strong><small>external routes</small></div>
            <div className="provider-summary-note"><ShieldCheck size={17} /><span><strong>Routing does not grant authority</strong><small>Models propose. Deterministic controls authorize.</small></span></div>
          </section>

          {report.routes.length === 0 ? (
            <Card>
              <EmptyState icon={Bot} title="No routes configured" description="Add a private local route configuration, then restart the current MVP runtime." />
            </Card>
          ) : (
            <section className="provider-grid" aria-label="Configured model routes">
              {report.routes.map((route) => <ProviderCard key={route.route_id} route={route} />)}
            </section>
          )}

          <Card className="provider-guidance">
            <div className="guidance-icon"><HardDrive size={19} /></div>
            <div>
              <h2>Affordable routes first</h2>
              <p>Prefer local OpenAI-compatible servers. Subscription-backed Codex CLI is optional, experimental, externally disclosed, and uses the same non-authoritative route contract.</p>
            </div>
            <div className="provider-guidance-paths">
              <code>config/routes/ollama-qwen.example.json</code>
              <code>config/routes/codex-cli.example.json</code>
            </div>
          </Card>
          <p className="page-footnote">Route health checked {formatInstant(report.generated_at)} · contract {report.contract_version}</p>
        </>
      )}
    </div>
  );
}

function ProviderCard({ route }: { readonly route: ModelRouteStatus }) {
  const synthetic = route.route_kind === "synthetic";
  const cliAgent = route.route_kind === "cli_agent";
  const codexCli = cliAgent && route.provider_id === "provider.openai-codex-subscription";
  const routeKindLabel = codexCli
    ? "Experimental Codex CLI"
    : cliAgent
      ? "Experimental CLI agent"
      : synthetic
        ? "Synthetic fixture"
        : titleCase(route.route_kind);
  const healthTone = route.health.state === "healthy" ? "positive" : route.health.state === "degraded" ? "warning" : "danger";
  const HealthIcon = route.health.state === "healthy" ? CheckCircle2 : route.health.state === "degraded" ? CircleAlert : WifiOff;
  const RouteIcon = cliAgent ? SquareTerminal : Bot;
  return (
    <Card className={`provider-card ${synthetic ? "synthetic" : ""} ${cliAgent ? "cli-agent" : ""}`}>
      <div className="provider-card-header">
        <span className={`provider-mark ${synthetic ? "synthetic" : ""} ${cliAgent ? "cli-agent" : ""}`}><RouteIcon size={20} /></span>
        <div><h2>{route.display_name}</h2><p>{route.model_id}</p></div>
        <Badge tone={healthTone}><HealthIcon size={13} /> {titleCase(route.health.state)}</Badge>
      </div>
      <div className="provider-labels">
        <Badge tone={synthetic ? "violet" : cliAgent ? "warning" : "info"}>{routeKindLabel}</Badge>
        <Badge tone={route.external_disclosure ? "warning" : "positive"}>{route.external_disclosure ? "External disclosure" : "No external disclosure"}</Badge>
      </div>
      {synthetic ? <p className="synthetic-callout">Deterministic test response only. This is not a real intelligence route.</p> : null}
      {cliAgent ? (
        <div className="cli-agent-callout">
          <div className="cli-agent-callout-heading">
            <ShieldCheck size={16} />
            <span><strong>Candidate response only</strong><small>When selected in Guardian normal, owner text and selected citations go to the approved provider.</small></span>
          </div>
          <ul aria-label="CLI agent boundaries">
            <li><KeyRound size={13} /> Read-only sandbox</li>
            <li>Ephemeral session</li>
            <li>Approval policy: never</li>
            <li>Guardian normal required</li>
            <li>No Melloa authority</li>
          </ul>
          <p>Health checks validate the executable only; the sandbox is not host isolation. Per-call token usage and subscription cost are not reported.</p>
        </div>
      ) : null}
      <dl className="provider-details">
        <div><dt>Provider</dt><dd>{route.provider_id}</dd></div>
        <div><dt>Route ID</dt><dd>{route.route_id}</dd></div>
        <div><dt>Processing</dt><dd>{titleCase(route.processing_location)}</dd></div>
        <div><dt>Privacy scope</dt><dd>{formatRouteList(route.allowed_sensitivities)}</dd></div>
        <div><dt>Retention policy</dt><dd>{formatRouteList(route.provider_retention_policies)}</dd></div>
        <div><dt>Modalities</dt><dd>{formatRouteList(route.supported_modalities)}</dd></div>
        <div><dt>Quality</dt><dd>{formatRouteList(route.quality_profiles)}</dd></div>
        <div><dt>Token ceiling</dt><dd>{route.max_input_tokens.toLocaleString()} in · {route.max_output_tokens.toLocaleString()} out</dd></div>
        <div><dt>Reliability</dt><dd>{Math.round(route.reliability * 100)}%</dd></div>
        <div><dt>Timeout</dt><dd><Clock3 size={14} /> {formatDurationMs(route.timeout_ms)}</dd></div>
        <div><dt>Cost ceiling</dt><dd><Coins size={14} /> {cliAgent ? "Subscription · unreported" : formatGbp(route.estimated_max_cost_gbp)}</dd></div>
        <div><dt>Probe</dt><dd>{route.health.latency_ms === null || route.health.latency_ms === undefined ? "Not measured" : formatDurationMs(route.health.latency_ms)}</dd></div>
      </dl>
      <div className={`provider-health-note ${route.health.state}`}>
        <HealthIcon size={15} /><span>{titleCase(route.health.reason_code)}</span>
      </div>
    </Card>
  );
}

function formatRouteList(values: readonly string[]): string {
  return values.map(titleCase).join(" · ");
}
