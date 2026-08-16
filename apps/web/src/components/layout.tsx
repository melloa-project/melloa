import { type FormEvent, useState } from "react";
import {
  Activity,
  Bot,
  Brain,
  ChevronRight,
  CircleUserRound,
  DatabaseZap,
  LockKeyhole,
  LogOut,
  MessageCircleMore,
  Network,
  Settings,
  ShieldCheck,
  SlidersHorizontal,
  X,
} from "lucide-react";
import { NavLink, Outlet, useLocation } from "react-router-dom";

import { errorMessage, useMelloa } from "../app";
import { formatRelative, shortId, titleCase } from "../lib/format";
import { Badge, Button, IconButton, Modal } from "./ui";

const navigation = [
  { to: "/conversation", label: "Conversation", icon: MessageCircleMore },
  { to: "/activity", label: "Activity", icon: Activity },
  { to: "/memory", label: "Memory", icon: Brain },
  { to: "/providers", label: "Providers", icon: Bot },
  { to: "/operations", label: "Operations", icon: DatabaseZap },
  { to: "/settings", label: "Settings", icon: Settings },
] as const;

export function AppLayout() {
  const {
    principal,
    status,
    canMutate,
    login,
    logout,
    notices,
    dismissNotice,
    notify,
  } = useMelloa();
  const location = useLocation();
  const [reauthOpen, setReauthOpen] = useState(false);
  const [reauthenticating, setReauthenticating] = useState(false);
  const page = navigation.find((item) => location.pathname.startsWith(item.to));

  async function reauthenticate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const input = form.elements.namedItem("credential");
    if (!(input instanceof HTMLInputElement)) {
      return;
    }
    const credential = input.value;
    input.value = "";
    setReauthenticating(true);
    try {
      await login(credential);
      setReauthOpen(false);
      notify("Changes unlocked with recent owner authentication.", "success");
    } catch (error) {
      notify(errorMessage(error), "error");
    } finally {
      setReauthenticating(false);
    }
  }

  return (
    <div className="app-frame">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true"><Network size={19} /></span>
          <div><strong>Melloa</strong><span>Owner Console</span></div>
        </div>

        <nav className="sidebar-nav" aria-label="Primary navigation">
          {navigation.map(({ to, label, icon: Icon }) => (
            <NavLink
              className={({ isActive }) => `nav-link ${isActive ? "active" : ""}`}
              key={to}
              to={to}
            >
              <Icon aria-hidden="true" size={18} />
              <span>{label}</span>
              <ChevronRight aria-hidden="true" className="nav-chevron" size={15} />
            </NavLink>
          ))}
        </nav>

        <div className="sidebar-boundary">
          <div className="boundary-icon"><ShieldCheck aria-hidden="true" size={17} /></div>
          <div>
            <strong>Guardian is separate</strong>
            <span>Status is read-only here. Control stays on the owner path.</span>
          </div>
        </div>

        <button className="owner-chip" type="button" onClick={() => setReauthOpen(true)}>
          <CircleUserRound aria-hidden="true" size={20} />
          <span><strong>Owner</strong><small>{shortId(principal.owner_id)}</small></span>
          <Badge tone={canMutate ? "positive" : "warning"}>
            {canMutate ? "Unlocked" : "Read only"}
          </Badge>
        </button>
      </aside>

      <div className="main-column">
        <header className="authority-bar">
          <div className="mobile-brand">
            <span className="brand-mark" aria-hidden="true"><Network size={17} /></span>
            <strong>Melloa</strong>
          </div>
          <div className="authority-title">
            <span>{page?.label ?? "Owner Console"}</span>
            <small>Private first-party surface</small>
          </div>
          <div className="authority-status">
            <span className="status-item">
              <span className={`status-dot status-${status === null ? "unknown" : "healthy"}`} />
              Private only
            </span>
            <span className="status-item">
              <ShieldCheck aria-hidden="true" size={15} />
              Guardian {status === null ? "unverified" : titleCase(status.guardian.mode)}
            </span>
            <Badge tone={status?.external_actions_enabled === true ? "warning" : "positive"}>
              {status?.external_actions_enabled === true ? "Actions enabled" : "Actions bounded"}
            </Badge>
            {!canMutate ? (
              <Button onClick={() => setReauthOpen(true)} size="sm" tone="primary">
                <LockKeyhole aria-hidden="true" size={15} /> Unlock changes
              </Button>
            ) : null}
          </div>
        </header>

        <main className="page-shell"><Outlet /></main>
      </div>

      <nav className="mobile-nav" aria-label="Mobile navigation">
        {navigation.map(({ to, label, icon: Icon }) => (
          <NavLink
            className={({ isActive }) => `mobile-nav-link ${isActive ? "active" : ""}`}
            key={to}
            to={to}
          >
            <Icon aria-hidden="true" size={19} />
            <span>{label}</span>
          </NavLink>
        ))}
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
        description="The credential is submitted to the same-origin private core and cleared immediately."
        onClose={() => setReauthOpen(false)}
        open={reauthOpen}
        title="Unlock owner changes"
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
              Unlock changes
            </Button>
          </div>
        </form>
        <button className="signout-link" type="button" onClick={() => void logout()}>
          <LogOut aria-hidden="true" size={15} /> Sign out instead
        </button>
      </Modal>

      <div className="sr-only" aria-live="polite">
        Session expires {formatRelative(principal.expires_at)}.
      </div>
    </div>
  );
}
