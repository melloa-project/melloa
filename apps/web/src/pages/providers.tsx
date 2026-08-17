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
  LockKeyhole,
  Network,
  RefreshCw,
  ShieldCheck,
  SquareTerminal,
  WifiOff,
} from "lucide-react";
import { useSearchParams } from "react-router-dom";

import type { ModelRouteStatus, OwnerModelRouteReport } from "../api";
import { errorMessage, useMelloa } from "../app";
import { Badge, Button, Card, EmptyState, ErrorState, LoadingState, SectionHeader } from "../components/ui";
import { formatDurationMs, formatGbp, formatInstant, titleCase } from "../lib/format";

export function ProvidersPage() {
  const { api } = useMelloa();
  const [searchParams] = useSearchParams();
  const [report, setReport] = useState<OwnerModelRouteReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const selectedRouteId = searchParams.get("route");

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

  useEffect(() => {
    if (report === null || selectedRouteId === null) {
      return;
    }
    window.requestAnimationFrame(() => {
      document.getElementById(providerRouteElementId(selectedRouteId))?.scrollIntoView({ block: "center" });
    });
  }, [report, selectedRouteId]);

  const activeRoutes = report?.routes.filter((route) => route.health.state === "healthy").length ?? 0;
  const externalRoutes = report?.routes.filter((route) => route.external_disclosure).length ?? 0;
  const eligibility = report === null ? [] : providerEligibility(report.routes);

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

          <section className="provider-eligibility" aria-label="Route privacy eligibility">
            {eligibility.map((group) => (
              <Card className={`provider-eligibility-card ${group.tone}`} key={group.label}>
                <div className="provider-eligibility-heading">
                  <span className="provider-eligibility-icon"><group.icon size={17} /></span>
                  <div><h2>{group.label}</h2><p>{group.summary}</p></div>
                </div>
                <div className="provider-eligibility-routes">
                  {group.routes.length === 0 ? (
                    <span className="provider-route-chip muted">No healthy route</span>
                  ) : group.routes.map((route) => (
                    <span className="provider-route-chip" key={route.route_id}>{route.display_name}</span>
                  ))}
                </div>
              </Card>
            ))}
          </section>

          {report.routes.length === 0 ? (
            <Card>
              <EmptyState icon={Bot} title="No routes configured" description="Add a private local route configuration, then restart the current MVP runtime." />
            </Card>
          ) : (
            <section className="provider-grid" aria-label="Configured model routes">
              {report.routes.map((route) => (
                <ProviderCard
                  key={route.route_id}
                  route={route}
                  selected={route.route_id === selectedRouteId}
                />
              ))}
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

type ProviderEligibilityGroup = {
  readonly label: string;
  readonly summary: string;
  readonly icon: typeof LockKeyhole;
  readonly tone: "private" | "local" | "external";
  readonly routes: readonly ModelRouteStatus[];
};

function providerEligibility(routes: readonly ModelRouteStatus[]): readonly ProviderEligibilityGroup[] {
  const healthy = routes.filter((route) => route.health.state === "healthy");
  const deviceOnly = healthy.filter((route) => (
    route.processing_location === "device"
    && !route.external_disclosure
    && route.allowed_sensitivities.includes("device_only")
  ));
  const personalNoDisclosure = healthy.filter((route) => (
    !route.external_disclosure
    && route.allowed_sensitivities.includes("personal")
  ));
  const external = healthy.filter((route) => route.external_disclosure);
  return [
    {
      label: "Device-only work",
      summary: routeCountLabel(deviceOnly.length),
      icon: LockKeyhole,
      tone: "private",
      routes: deviceOnly,
    },
    {
      label: "Personal no-disclosure",
      summary: routeCountLabel(personalNoDisclosure.length),
      icon: HardDrive,
      tone: "local",
      routes: personalNoDisclosure,
    },
    {
      label: "External disclosure",
      summary: routeCountLabel(external.length),
      icon: Network,
      tone: "external",
      routes: external,
    },
  ];
}

function routeCountLabel(count: number): string {
  if (count === 0) {
    return "No healthy routes";
  }
  return `${count} healthy ${count === 1 ? "route" : "routes"}`;
}

function ProviderCard({
  route,
  selected,
}: {
  readonly route: ModelRouteStatus;
  readonly selected: boolean;
}) {
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
    <Card
      aria-current={selected ? "true" : undefined}
      className={`provider-card ${synthetic ? "synthetic" : ""} ${cliAgent ? "cli-agent" : ""} ${selected ? "selected" : ""}`}
      id={providerRouteElementId(route.route_id)}
    >
      <div className="provider-card-header">
        <span className={`provider-mark ${synthetic ? "synthetic" : ""} ${cliAgent ? "cli-agent" : ""}`}><RouteIcon size={20} /></span>
        <div><h2>{route.display_name}</h2><p>{route.model_id}</p></div>
        <Badge tone={healthTone}><HealthIcon size={13} /> {titleCase(route.health.state)}</Badge>
      </div>
      <div className="provider-labels">
        {selected ? <Badge tone="violet">Selected route</Badge> : null}
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

function providerRouteElementId(routeId: string): string {
  return `provider-route-${routeId.replace(/[^a-zA-Z0-9_-]/g, "-")}`;
}
