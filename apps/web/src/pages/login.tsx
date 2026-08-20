import { type FormEvent, useState } from "react";
import {
  ArrowRight,
  Eye,
  EyeOff,
  KeyRound,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  TriangleAlert,
} from "lucide-react";
import { useNavigate } from "react-router-dom";

import type { SystemStatus } from "../api";
import { errorMessage } from "../app";
import { Button, Card } from "../components/ui";

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
    const input = event.currentTarget.elements.namedItem("credential");
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

  const privateAccessVerified = status?.public_ingress === false;

  return (
    <main className="login-page">
      <section className="login-story" aria-labelledby="login-title">
        <div className="login-brand">
          <span className="melli-mark"><Sparkles aria-hidden="true" size={20} /></span>
          <span><strong>Melli</strong><small>Private with Melloa</small></span>
        </div>
        <div className="login-promise">
          <p className="eyebrow">A relationship that can continue</p>
          <h1 id="login-title">Pick up where you left off.</h1>
          <p>Melli is built to understand your history, goals, and changing context—not make you administer an AI runtime.</p>
        </div>
        <p className="login-reset-note">First server setup pairs Telegram during install. Use this web entrypoint only when the launcher or service prints an owner credential.</p>
      </section>

      <section className="login-access">
        <Card className="login-card">
          <div className="login-card-heading">
            <span className="login-lock"><KeyRound aria-hidden="true" size={19} /></span>
            <div><h2>Continue privately</h2><p>Use the owner credential printed by the launcher or installed service.</p></div>
          </div>
          <form className="stack-form" onSubmit={(event) => void submit(event)}>
            <label className="field-label" htmlFor="owner-credential">Owner credential</label>
            <div className="password-field">
              <input
                autoComplete="current-password"
                className="text-input"
                id="owner-credential"
                minLength={32}
                name="credential"
                required
                type={showCredential ? "text" : "password"}
              />
              <button
                aria-label={showCredential ? "Hide credential" : "Show credential"}
                onClick={() => setShowCredential((visible) => !visible)}
                type="button"
              >
                {showCredential ? <EyeOff aria-hidden="true" size={18} /> : <Eye aria-hidden="true" size={18} />}
              </button>
            </div>
            {error === null ? null : <p className="form-error" role="alert">{error}</p>}
            <Button loading={submitting} tone="primary" type="submit">
              Continue to Melli <ArrowRight aria-hidden="true" size={16} />
            </Button>
          </form>
          <div className={`login-protection ${privateAccessVerified ? "verified" : "unverified"}`}>
            {privateAccessVerified ? <ShieldCheck size={17} /> : <TriangleAlert size={17} />}
            <div>
              <strong>{privateAccessVerified ? "Private access verified" : "Protection status unavailable"}</strong>
              <small>{privateAccessVerified ? "No public application ingress" : "Check the local core before continuing"}</small>
            </div>
            <Button
              aria-label="Retry protection status"
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
        <p className="login-help">Server setup: <code>docs/server-deployment.md</code>. Local preview: <code>docs/getting-started.md</code>.</p>
      </section>
    </main>
  );
}
