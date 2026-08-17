import { type FormEvent, useState } from "react";
import {
  ArrowRight,
  Eye,
  EyeOff,
  KeyRound,
  LockKeyhole,
  Network,
  RefreshCw,
  ShieldCheck,
} from "lucide-react";
import { useNavigate } from "react-router-dom";

import type { SystemStatus } from "../api";
import { errorMessage } from "../app";
import { titleCase } from "../lib/format";
import { Badge, Button, Card } from "../components/ui";

export function LoginPage({
  login,
  refreshStatus,
  status,
}: {
  readonly login: (credential: string) => Promise<void>;
  readonly refreshStatus: () => Promise<void>;
  readonly status: SystemStatus | null;
}) {
  const navigate = useNavigate();
  const [showCredential, setShowCredential] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [refreshingStatus, setRefreshingStatus] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const input = form.elements.namedItem("credential");
    if (!(input instanceof HTMLInputElement)) {
      return;
    }
    const credential = input.value;
    input.value = "";
    setSubmitting(true);
    setError(null);
    try {
      await login(credential);
      navigate("/conversation", { replace: true });
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setSubmitting(false);
    }
  }

  async function retryStatus() {
    setRefreshingStatus(true);
    try {
      await refreshStatus();
    } finally {
      setRefreshingStatus(false);
    }
  }

  return (
    <main className="login-page">
      <section className="login-context" aria-labelledby="login-context-title">
        <div className="login-brand">
          <span className="brand-mark"><Network aria-hidden="true" size={19} /></span>
          <div><strong>Melloa</strong><span>Owner Console</span></div>
        </div>
        <div className="login-copy">
          <Badge tone="positive"><ShieldCheck aria-hidden="true" size={14} /> Private by design</Badge>
          <h1 id="login-context-title">Your conversation with Melli, under your control.</h1>
          <p>
            Talk directly, inspect the route behind every response, and keep Guardian authority
            outside the application plane.
          </p>
        </div>
        <div className="login-boundaries">
          <div><LockKeyhole aria-hidden="true" size={17} /><span><strong>Application authentication</strong><small>Private network membership is not enough.</small></span></div>
          <div><ShieldCheck aria-hidden="true" size={17} /><span><strong>Guardian remains independent</strong><small>This console reads signed status only.</small></span></div>
          <div><KeyRound aria-hidden="true" size={17} /><span><strong>No browser persistence</strong><small>Your credential and mutation proof stay out of storage.</small></span></div>
        </div>
      </section>

      <section className="login-form-column">
        <Card className="login-card">
          <div className="login-card-heading">
            <p className="eyebrow">Private owner access</p>
            <h2>Welcome back</h2>
            <p>Use the credential generated for this local runtime.</p>
          </div>
          <form className="stack-form" onSubmit={(event) => void submit(event)}>
            <label className="field-label" htmlFor="owner-credential">Owner credential</label>
            <div className="password-field">
              <input
                autoComplete="current-password"
                autoFocus
                className="text-input"
                id="owner-credential"
                minLength={32}
                name="credential"
                required
                type={showCredential ? "text" : "password"}
              />
              <button
                aria-label={showCredential ? "Hide credential" : "Show credential"}
                onClick={() => setShowCredential((value) => !value)}
                type="button"
              >
                {showCredential ? <EyeOff aria-hidden="true" size={18} /> : <Eye aria-hidden="true" size={18} />}
              </button>
            </div>
            {error === null ? null : <p className="form-error" role="alert">{error}</p>}
            <Button loading={submitting} tone="primary" type="submit">
              Open Owner Console <ArrowRight aria-hidden="true" size={16} />
            </Button>
          </form>
          <div className="login-runtime-state">
            <span className={`status-dot status-${status === null ? "unknown" : "healthy"}`} />
            <div>
              <strong>{status === null ? "Private core not verified" : `Guardian ${titleCase(status.guardian.mode)}`}</strong>
              <small>{status === null ? "Check the backend and signed status paths." : `Sequence ${status.guardian.sequence} · no public ingress`}</small>
            </div>
            <Button
              aria-label="Retry signed status check"
              loading={refreshingStatus}
              onClick={() => void retryStatus()}
              size="icon"
              tone="ghost"
              type="button"
            >
              <RefreshCw aria-hidden="true" size={16} />
            </Button>
          </div>
        </Card>
        <p className="login-help">Fresh setup? Follow <code>docs/run-current-mvp.md</code>.</p>
      </section>
    </main>
  );
}
