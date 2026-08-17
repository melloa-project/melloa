import { type FormEvent, useCallback, useEffect, useState } from "react";
import {
  CheckCircle2,
  Clock3,
  KeyRound,
  Link2,
  LockKeyhole,
  MessageCircle,
  RefreshCw,
  ShieldCheck,
  Smartphone,
  Unlink,
  UserRound,
} from "lucide-react";

import type {
  OwnerSessionInventory,
  TelegramChannelStatus,
  TelegramOwnerPairing,
  TelegramPairingCandidate,
} from "../api";
import { errorMessage, useMelloa } from "../app";
import { Badge, Button, Card, EmptyState, ErrorState, LoadingState, Modal, SectionHeader } from "../components/ui";
import { formatInstant, formatRelative, redactNumericIdentifier, shortId, titleCase } from "../lib/format";

type TelegramState = {
  readonly status: TelegramChannelStatus;
  readonly pairing: TelegramOwnerPairing | null;
  readonly candidates: readonly TelegramPairingCandidate[];
};

export function SettingsPage() {
  const { api, principal, status, canMutate, notify } = useMelloa();
  const [sessions, setSessions] = useState<OwnerSessionInventory | null>(null);
  const [sessionsLoading, setSessionsLoading] = useState(true);
  const [sessionsError, setSessionsError] = useState<string | null>(null);
  const [revokeSessionsOpen, setRevokeSessionsOpen] = useState(false);
  const [revokingSessions, setRevokingSessions] = useState(false);
  const [telegram, setTelegram] = useState<TelegramState | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedCandidate, setSelectedCandidate] = useState<TelegramPairingCandidate | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [revokeOpen, setRevokeOpen] = useState(false);
  const [revoking, setRevoking] = useState(false);

  const loadSessions = useCallback(async () => {
    setSessionsLoading(true);
    try {
      setSessions(await api.activeSessions());
      setSessionsError(null);
    } catch (caught) {
      setSessions(null);
      setSessionsError(errorMessage(caught));
    } finally {
      setSessionsLoading(false);
    }
  }, [api]);

  const loadTelegram = useCallback(async () => {
    setLoading(true);
    try {
      const [status, pairing, candidates] = await Promise.all([
        api.inspectTelegramStatus(),
        api.inspectTelegramPairing(),
        api.listTelegramPairingCandidates(),
      ]);
      setTelegram({ status, pairing, candidates });
      setError(null);
    } catch (caught) {
      setTelegram(null);
      setError(errorMessage(caught));
    } finally {
      setLoading(false);
    }
  }, [api]);

  useEffect(() => {
    void loadSessions();
    void loadTelegram();
  }, [loadSessions, loadTelegram]);

  async function revokeOtherSessions() {
    setRevokingSessions(true);
    try {
      const result = await api.revokeOtherSessions();
      setRevokeSessionsOpen(false);
      await loadSessions();
      const noun = result.revoked_count === 1 ? "session" : "sessions";
      notify(`${result.revoked_count} other ${noun} signed out.`, "success");
    } catch (caught) {
      notify(errorMessage(caught), "error");
    } finally {
      setRevokingSessions(false);
    }
  }

  async function confirmPairing(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (selectedCandidate === null) {
      return;
    }
    const input = event.currentTarget.elements.namedItem("confirmation-code");
    if (!(input instanceof HTMLInputElement)) {
      return;
    }
    const code = input.value;
    input.value = "";
    setConfirming(true);
    try {
      await api.confirmTelegramPairing(selectedCandidate.candidate_id, code);
      setSelectedCandidate(null);
      await loadTelegram();
      notify("Telegram owner pairing confirmed.", "success");
    } catch (caught) {
      notify(errorMessage(caught), "error");
    } finally {
      setConfirming(false);
    }
  }

  async function revokePairing() {
    if (telegram?.pairing === null || telegram?.pairing === undefined) {
      return;
    }
    setRevoking(true);
    try {
      await api.revokeTelegramPairing(telegram.pairing.pairing_id);
      setRevokeOpen(false);
      await loadTelegram();
      notify("Telegram owner pairing revoked.", "success");
    } catch (caught) {
      notify(errorMessage(caught), "error");
    } finally {
      setRevoking(false);
    }
  }

  const pollingState = telegram?.status.polling?.state ?? "unavailable";
  const realTransport = telegram?.status.capabilities?.network === true;
  const channelTone = pollingState === "healthy" ? "positive" : pollingState === "disabled" ? "neutral" : "warning";
  const otherSessions = sessions?.sessions.filter(
    (session) => session.session_id !== sessions.current_session_id,
  ) ?? [];

  return (
    <div className="standard-page settings-page">
      <SectionHeader
        eyebrow="Private configuration"
        title="Settings"
        description="Review owner access, Guardian status, and explicitly paired secondary channels."
      />

      <div className="settings-grid">
        <Card className="settings-card">
          <div className="settings-card-heading"><span className="settings-icon"><UserRound size={19} /></span><div><h2>Owner session</h2><p>Short-lived application authentication</p></div><Badge tone={canMutate ? "positive" : "warning"}>{canMutate ? "Changes unlocked" : "Read only"}</Badge></div>
          <dl className="settings-details">
            <div><dt>Owner</dt><dd>{shortId(principal.owner_id)}</dd></div>
            <div><dt>Method</dt><dd>{titleCase(principal.authentication_method)}</dd></div>
            <div><dt>Authenticated</dt><dd>{formatInstant(principal.authenticated_at)}</dd></div>
            <div><dt>Session expires</dt><dd>{formatRelative(principal.expires_at)}</dd></div>
            <div><dt>Recent auth</dt><dd>{formatRelative(principal.reauthenticated_until)}</dd></div>
          </dl>
          {sessionsLoading && sessions === null ? <LoadingState label="Reading active sessions" /> : null}
          {sessionsError === null ? null : <ErrorState title="Session inventory unavailable" message={sessionsError} />}
          {sessions === null ? null : (
            <>
              <dl className="channel-status-grid" aria-label="Active owner sessions">
                {sessions.sessions.map((session) => {
                  const current = session.session_id === sessions.current_session_id;
                  return (
                    <div key={session.session_id}>
                      <dt>{current ? "This browser" : `Other browser · ${shortId(session.session_id)}`}</dt>
                      <dd>{titleCase(session.authentication_method)} · signed in {formatInstant(session.authenticated_at)} · expires {formatRelative(session.expires_at)}</dd>
                    </div>
                  );
                })}
              </dl>
              <div className="memory-actions">
                <Button loading={sessionsLoading} onClick={() => void loadSessions()} size="sm"><RefreshCw size={15} /> Refresh sessions</Button>
                <Button
                  disabled={!canMutate || sessionsLoading || otherSessions.length === 0}
                  onClick={() => setRevokeSessionsOpen(true)}
                  size="sm"
                  tone="danger"
                >
                  <Unlink size={15} /> Sign out other sessions
                </Button>
              </div>
            </>
          )}
          <p className="settings-note"><KeyRound size={15} /> Credentials and mutation proof are not written to browser storage.</p>
        </Card>

        <Card className="settings-card">
          <div className="settings-card-heading"><span className="settings-icon guardian"><ShieldCheck size={19} /></span><div><h2>Guardian boundary</h2><p>Independently controlled authority</p></div><Badge tone={status === null ? "warning" : "positive"}>{status === null ? "Unverified" : titleCase(status.guardian.mode)}</Badge></div>
          <dl className="settings-details">
            <div><dt>Signed sequence</dt><dd>{status?.guardian.sequence ?? "Unavailable"}</dd></div>
            <div><dt>Key ID</dt><dd>{status?.guardian.key_id ?? "Unavailable"}</dd></div>
            <div><dt>Changed</dt><dd>{formatInstant(status?.guardian.changed_at)}</dd></div>
            <div><dt>External actions</dt><dd>{status?.external_actions_enabled === true ? "Enabled" : "Bounded"}</dd></div>
            <div><dt>Public ingress</dt><dd>{status?.public_ingress === false ? "None" : "Unverified"}</dd></div>
          </dl>
          <p className="settings-note"><LockKeyhole size={15} /> This console cannot change Guardian mode or absorb its authority.</p>
        </Card>
      </div>

      <Card className="telegram-card">
        <div className="card-heading-row">
          <div className="channel-heading"><span className="telegram-mark"><MessageCircle size={19} /></span><div><h2>Telegram</h2><p>Optional, replaceable secondary conversation adapter</p></div></div>
          <div className="channel-heading-actions"><Badge tone={channelTone}>{realTransport ? "Bot API" : "Synthetic fixture"} · {titleCase(pollingState)}</Badge><Button onClick={() => void loadTelegram()} size="sm"><RefreshCw size={15} /> Refresh</Button></div>
        </div>

        {loading && telegram === null ? <LoadingState label="Reading Telegram pairing" /> : null}
        {error === null ? null : <ErrorState title="Telegram is not configured" message={error} />}

        {telegram === null ? null : (
          <dl className="channel-status-grid">
            <div><dt>Transport</dt><dd>{realTransport ? "Real Telegram Bot API" : "Synthetic, no network"}</dd></div>
            <div><dt>Polling</dt><dd>{titleCase(telegram.status.polling?.reason_code ?? "not configured")}</dd></div>
            <div><dt>Replies</dt><dd>{telegram.status.replies === null ? "Not enabled" : `${telegram.status.replies.deliveries_submitted} sent · ${telegram.status.replies.pending_replies} pending`}</dd></div>
            <div><dt>Delivery</dt><dd>{titleCase(telegram.status.delivery?.status ?? "not configured")}</dd></div>
            <div><dt>Channel state</dt><dd>{telegram.status.state_persistence === "postgresql" ? "PostgreSQL restart-safe" : "Process-only preview"}</dd></div>
            <div><dt>Attachments</dt><dd>Rejected before fetch</dd></div>
            <div><dt>Retry safety</dt><dd>{telegram.status.capabilities?.ambiguous_send_retries === false ? "Ambiguous sends do not retry" : "Synthetic only"}</dd></div>
          </dl>
        )}

        {telegram?.pairing === null ? (
          <div className="telegram-unpaired">
            <EmptyState
              icon={Smartphone}
              title="No owner account paired"
              description="Start the Telegram adapter, send /start to the configured bot in a private chat, then confirm the candidate here using the short-lived code returned by the bot."
            />
            {telegram.candidates.length === 0 ? (
              <div className="candidate-empty"><Clock3 size={16} /><span>No unexpired pairing candidates are waiting.</span></div>
            ) : (
              <div className="candidate-list">
                {telegram.candidates.map((candidate) => (
                  <article className="candidate-row" key={candidate.candidate_id}>
                    <span className="candidate-icon"><Smartphone size={17} /></span>
                    <div><strong>Telegram user {redactNumericIdentifier(candidate.telegram_user_id)}</strong><span>Chat {redactNumericIdentifier(candidate.telegram_chat_id)} · expires {formatRelative(candidate.expires_at)}</span></div>
                    <Button disabled={!canMutate} onClick={() => setSelectedCandidate(candidate)} tone="primary"><Link2 size={15} /> Confirm</Button>
                  </article>
                ))}
              </div>
            )}
          </div>
        ) : null}

        {telegram?.pairing !== null && telegram?.pairing !== undefined ? (
          <div className="paired-channel">
            <span className="paired-channel-icon"><CheckCircle2 size={21} /></span>
            <div className="paired-channel-copy"><Badge tone="positive">Paired</Badge><h3>Telegram user {redactNumericIdentifier(telegram.pairing.telegram_user_id)}</h3><p>Chat {redactNumericIdentifier(telegram.pairing.telegram_chat_id)} · confirmed {formatInstant(telegram.pairing.confirmed_at)}</p></div>
            <dl className="paired-channel-meta"><div><dt>Pairing</dt><dd>{shortId(telegram.pairing.pairing_id)}</dd></div><div><dt>Confirmed by</dt><dd>{shortId(telegram.pairing.confirmed_by_owner_id)}</dd></div></dl>
            <Button disabled={!canMutate} onClick={() => setRevokeOpen(true)} tone="danger"><Unlink size={15} /> Revoke pairing</Button>
          </div>
        ) : null}

        <div className="channel-boundary"><ShieldCheck size={16} /><span><strong>Channel-neutral by design</strong><small>Telegram messages become canonical conversation records; Telegram does not own Melli, memory, or policy authority.</small></span></div>
      </Card>

      <Modal
        description="This browser stays signed in. Every other active session for the current owner credential is revoked together with content-free audit evidence."
        onClose={() => setRevokeSessionsOpen(false)}
        open={revokeSessionsOpen}
        title={`Sign out ${otherSessions.length} other ${otherSessions.length === 1 ? "session" : "sessions"}?`}
      >
        <div className="destructive-confirmation danger"><LockKeyhole size={19} /><p>Other browsers lose access immediately. This action requires recent owner authentication and cannot reveal or recover their opaque tokens.</p></div>
        <div className="modal-actions"><Button onClick={() => setRevokeSessionsOpen(false)}>Cancel</Button><Button loading={revokingSessions} onClick={() => void revokeOtherSessions()} tone="danger">Sign out other sessions</Button></div>
      </Modal>

      <Modal
        description="Enter the short-lived code shown through the Telegram pairing challenge."
        onClose={() => setSelectedCandidate(null)}
        open={selectedCandidate !== null}
        title="Confirm Telegram owner"
      >
        <form className="stack-form" onSubmit={(event) => void confirmPairing(event)}>
          <div className="pairing-target"><Smartphone size={18} /><span><strong>User {selectedCandidate === null ? "Unknown" : redactNumericIdentifier(selectedCandidate.telegram_user_id)}</strong><small>Chat {selectedCandidate === null ? "Unknown" : redactNumericIdentifier(selectedCandidate.telegram_chat_id)}</small></span></div>
          <label className="field-label" htmlFor="confirmation-code">Confirmation code</label>
          <input autoCapitalize="none" autoComplete="one-time-code" autoFocus className="text-input code-input" id="confirmation-code" inputMode="text" maxLength={128} minLength={20} name="confirmation-code" pattern="[A-Za-z0-9_-]{20,128}" required spellCheck={false} />
          <div className="modal-actions"><Button onClick={() => setSelectedCandidate(null)} type="button">Cancel</Button><Button loading={confirming} tone="primary" type="submit">Confirm pairing</Button></div>
        </form>
      </Modal>

      <Modal
        description="Inbound messages from this Telegram account will stop being accepted after revocation."
        onClose={() => setRevokeOpen(false)}
        open={revokeOpen}
        title="Revoke Telegram pairing?"
      >
        <div className="destructive-confirmation danger"><Unlink size={19} /><p>This preserves the audit record but removes the active owner-channel binding.</p></div>
        <div className="modal-actions"><Button onClick={() => setRevokeOpen(false)}>Cancel</Button><Button loading={revoking} onClick={() => void revokePairing()} tone="danger">Revoke pairing</Button></div>
      </Modal>
    </div>
  );
}
