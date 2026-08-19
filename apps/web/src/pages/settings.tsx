import { useCallback, useEffect, useState } from "react";
import {
  ArrowLeft,
  Database,
  Download,
  KeyRound,
  LockKeyhole,
  LogOut,
  MonitorSmartphone,
  RefreshCw,
  ShieldCheck,
  TriangleAlert,
  UserRoundX,
} from "lucide-react";
import { Link } from "react-router-dom";

import type { OwnerExportReadinessReport, OwnerSessionInventory } from "../api";
import { errorMessage, useMelloa } from "../app";
import { useOwnerUnlock } from "../components/layout";
import { Badge, Button, ErrorState, LoadingState } from "../components/ui";
import { formatInstant, formatRelative, titleCase } from "../lib/format";

export function SettingsPage() {
  const {
    api,
    principal,
    status,
    canWrite,
    canUseSensitiveControls,
    logout,
    notify,
  } = useMelloa();
  const openUnlock = useOwnerUnlock();
  const [sessions, setSessions] = useState<OwnerSessionInventory | null>(null);
  const [exportReadiness, setExportReadiness] = useState<OwnerExportReadinessReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);
  const [revoking, setRevoking] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    const [sessionResult, exportResult] = await Promise.allSettled([
      api.activeSessions(),
      api.exportReadiness(),
    ]);
    setSessions(sessionResult.status === "fulfilled" ? sessionResult.value : null);
    setExportReadiness(exportResult.status === "fulfilled" ? exportResult.value : null);
    const failure = sessionResult.status === "rejected"
      ? sessionResult.reason
      : exportResult.status === "rejected"
        ? exportResult.reason
        : null;
    setError(failure === null ? null : errorMessage(failure));
    setLoading(false);
  }, [api]);

  useEffect(() => {
    void load();
  }, [load]);

  async function downloadExport() {
    if (!canWrite || !canUseSensitiveControls) {
      openUnlock("Export contains your private history, so Melloa asks for fresh owner confirmation.");
      return;
    }
    setExporting(true);
    try {
      const archive = await api.downloadExportPreview();
      const url = URL.createObjectURL(archive.blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = archive.filename;
      anchor.click();
      URL.revokeObjectURL(url);
      notify("Your export is ready in Downloads.", "success");
    } catch (caught) {
      notify(errorMessage(caught), "error");
    } finally {
      setExporting(false);
    }
  }

  async function signOutOtherSessions() {
    if (!canWrite || !canUseSensitiveControls) {
      openUnlock("Confirm it’s you before signing out other browsers.");
      return;
    }
    setRevoking(true);
    try {
      const result = await api.revokeOtherSessions();
      await load();
      notify(
        result.revoked_count === 0
          ? "No other browsers were signed in."
          : `${result.revoked_count} other ${result.revoked_count === 1 ? "browser" : "browsers"} signed out.`,
        "success",
      );
    } catch (caught) {
      notify(errorMessage(caught), "error");
    } finally {
      setRevoking(false);
    }
  }

  const otherSessions = sessions?.sessions.filter(
    (session) => session.session_id !== sessions.current_session_id,
  ) ?? [];
  const includedGroups = exportReadiness?.coverage.filter((item) => item.included).length ?? 0;
  const totalGroups = exportReadiness?.coverage.length ?? 0;

  return (
    <div className="safety-page">
      <header className="safety-heading">
        <Link className="back-link" to="/conversation"><ArrowLeft size={16} /> Back to Melli</Link>
        <div>
          <p className="eyebrow">Owner control</p>
          <h1>Data &amp; safety</h1>
          <p>The few controls that should remain outside ordinary conversation.</p>
        </div>
        <Button aria-label="Refresh data and safety" loading={loading} onClick={() => void load()} size="icon" tone="ghost">
          <RefreshCw size={17} />
        </Button>
      </header>

      {loading && sessions === null && exportReadiness === null ? <LoadingState label="Reading owner controls" /> : null}
      {error === null ? null : <ErrorState message={error} title="Some owner controls are unavailable" />}

      <div className="safety-content">
        <div className="safety-surface">
          <section className="safety-section data-section">
          <div className="safety-card-heading">
            <span className="safety-icon"><Database size={19} /></span>
            <div><h2>Your data</h2><p>Take a copy of the history Melloa currently holds.</p></div>
          </div>
          <div className="plain-status">
            <span><strong>{includedGroups}</strong> of {totalGroups || "?"} current data groups included</span>
            <Badge tone={exportReadiness?.encrypted === true ? "positive" : "warning"}>
              {exportReadiness?.encrypted === true ? "Encrypted" : "Not encrypted"}
            </Badge>
          </div>
          {exportReadiness?.encrypted === false ? (
            <p className="safety-warning"><TriangleAlert size={16} /> The current browser download is a preview ZIP and is not encrypted. Keep it private.</p>
          ) : null}
          <Button loading={exporting} onClick={() => void downloadExport()} tone="primary">
            <Download size={16} /> Download my data
          </Button>
          <p className="fine-print">Melloa validates the archive before download. This is a portability copy, not a replacement for encrypted backups.</p>
          </section>

          <section className="safety-section sessions-section">
          <div className="safety-card-heading">
            <span className="safety-icon"><MonitorSmartphone size={19} /></span>
            <div><h2>Signed-in browsers</h2><p>Review where this owner session is active.</p></div>
          </div>
          <div className="session-list">
            {(sessions?.sessions ?? [principal]).map((session) => {
              const current = session.session_id === (sessions?.current_session_id ?? principal.session_id);
              return (
                <div className="session-row" key={session.session_id}>
                  <span className="session-dot" />
                  <div>
                    <strong>{current ? "This browser" : "Another browser"}</strong>
                    <small>Signed in {formatInstant(session.authenticated_at)} · expires {formatRelative(session.expires_at)}</small>
                  </div>
                  {current ? <Badge tone="positive">Current</Badge> : null}
                </div>
              );
            })}
          </div>
          <Button
            disabled={otherSessions.length === 0}
            loading={revoking}
            onClick={() => void signOutOtherSessions()}
            tone="danger"
          >
            <UserRoundX size={16} /> Sign out other browsers
          </Button>
          <Button onClick={() => void logout()} tone="ghost"><LogOut size={16} /> Sign out here</Button>
          </section>
        </div>

        <div className="safety-trust-grid">
          <section className="safety-trust protection-section">
          <div className="safety-card-heading">
            <span className="safety-icon"><ShieldCheck size={19} /></span>
            <div><h2>Independent protection</h2><p>Guardian stays outside Melli’s control.</p></div>
          </div>
          {status === null ? (
            <p className="safety-warning"><TriangleAlert size={16} /> Protection status could not be verified. External actions remain unsafe to trust.</p>
          ) : (
            <dl className="plain-details">
              <div><dt>Guardian</dt><dd>{titleCase(status.guardian.mode)}</dd></div>
              <div><dt>Public access</dt><dd>{status.public_ingress === false ? "Disabled" : "Not verified"}</dd></div>
              <div><dt>External actions</dt><dd>{status.external_actions_enabled ? "Policy constrained" : "Paused"}</dd></div>
            </dl>
          )}
          <p className="fine-print"><LockKeyhole size={14} /> This interface can read protection status, but cannot change Guardian or obtain its keys.</p>
          </section>

          <section className="safety-trust access-section">
          <div className="safety-card-heading">
            <span className="safety-icon"><KeyRound size={19} /></span>
            <div><h2>Sensitive changes</h2><p>Fresh confirmation is reserved for consequential controls.</p></div>
          </div>
          <p>Ordinary conversation remains available after the five-minute confirmation window. Exporting private history and signing out other browsers ask again.</p>
          <Badge tone={canUseSensitiveControls ? "positive" : "neutral"}>
            {canUseSensitiveControls ? "Recently confirmed" : "Confirm when needed"}
          </Badge>
          </section>
        </div>
      </div>
    </div>
  );
}
