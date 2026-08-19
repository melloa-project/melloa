import {
  createContext,
  type FormEvent,
  useContext,
  useMemo,
  useState,
} from "react";
import {
  LockKeyhole,
  MessageCircleMore,
  Settings,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  X,
} from "lucide-react";
import { NavLink, Outlet } from "react-router-dom";

import { errorMessage, useMelloa } from "../app";
import { Button, IconButton, Modal } from "./ui";

type UnlockOwner = (reason?: string) => void;

const OwnerUnlockContext = createContext<UnlockOwner | null>(null);

export function useOwnerUnlock(): UnlockOwner {
  const value = useContext(OwnerUnlockContext);
  if (value === null) {
    throw new Error("useOwnerUnlock must be used inside the Melloa layout");
  }
  return value;
}

export function AppLayout() {
  const {
    status,
    canWrite,
    login,
    notices,
    dismissNotice,
    notify,
  } = useMelloa();
  const [reauthOpen, setReauthOpen] = useState(false);
  const [reauthenticating, setReauthenticating] = useState(false);
  const [reauthReason, setReauthReason] = useState(
    "Re-enter your local owner credential to continue.",
  );

  const openUnlock = useMemo<UnlockOwner>(() => (reason) => {
    setReauthReason(reason ?? "Re-enter your local owner credential to continue.");
    setReauthOpen(true);
  }, []);

  const protectionUnavailable = status === null || status.public_ingress !== false;

  async function reauthenticate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const input = event.currentTarget.elements.namedItem("credential");
    if (!(input instanceof HTMLInputElement)) {
      return;
    }
    const credential = input.value;
    input.value = "";
    setReauthenticating(true);
    try {
      await login(credential);
      setReauthOpen(false);
      notify("Owner access confirmed.", "success");
    } catch (error) {
      notify(errorMessage(error), "error");
    } finally {
      setReauthenticating(false);
    }
  }

  return (
    <OwnerUnlockContext.Provider value={openUnlock}>
      <div className="app-shell">
        <header className="topbar">
          <NavLink aria-label="Open Melli" className="melli-brand" to="/conversation">
            <span className="melli-mark" aria-hidden="true"><Sparkles size={18} /></span>
            <span><strong>Melli</strong><small>Private with Melloa</small></span>
          </NavLink>

          <div className="topbar-actions">
            {protectionUnavailable ? (
              <span className="protection-warning" role="status">
                <ShieldAlert aria-hidden="true" size={16} /> Protection status unavailable
              </span>
            ) : (
              <span className="protection-ok" title="Private access verified">
                <ShieldCheck aria-hidden="true" size={16} />
                <span className="sr-only">Private access verified</span>
              </span>
            )}
            {!canWrite ? (
              <Button
                onClick={() => openUnlock("Confirm owner access to write in this private session.")}
                size="sm"
                tone="primary"
              >
                <LockKeyhole aria-hidden="true" size={15} /> Unlock
              </Button>
            ) : null}
            <NavLink aria-label="Data and safety" className="topbar-link" to="/settings">
              <Settings aria-hidden="true" size={18} />
              <span>Data &amp; safety</span>
            </NavLink>
          </div>
        </header>

        <main className="app-main"><Outlet /></main>

        <nav className="mobile-primary" aria-label="Primary navigation">
          <NavLink to="/conversation"><MessageCircleMore aria-hidden="true" size={19} /><span>Melli</span></NavLink>
          <NavLink to="/settings"><Settings aria-hidden="true" size={19} /><span>Safety</span></NavLink>
        </nav>

        <div className="toast-stack" aria-live="polite">
          {notices.map((notice) => (
            <div className={`toast toast-${notice.tone}`} key={notice.id} role="status">
              <span>{notice.message}</span>
              <IconButton
                icon={X}
                label="Dismiss notification"
                onClick={() => dismissNotice(notice.id)}
                tone="ghost"
              />
            </div>
          ))}
        </div>

        <Modal
          description={reauthReason}
          onClose={() => setReauthOpen(false)}
          open={reauthOpen}
          title="Confirm it’s you"
        >
          <form className="stack-form" onSubmit={(event) => void reauthenticate(event)}>
            <label className="field-label" htmlFor="reauth-credential">Owner credential</label>
            <input
              autoComplete="current-password"
              autoFocus
              className="text-input"
              id="reauth-credential"
              minLength={32}
              name="credential"
              required
              type="password"
            />
            <div className="modal-actions">
              <Button onClick={() => setReauthOpen(false)} type="button">Cancel</Button>
              <Button loading={reauthenticating} tone="primary" type="submit">
                Continue
              </Button>
            </div>
          </form>
        </Modal>
      </div>
    </OwnerUnlockContext.Provider>
  );
}
