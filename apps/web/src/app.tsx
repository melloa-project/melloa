import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import {
  ApiError,
  MelloaApi,
  type AuthenticatedOwner,
  type SystemStatus,
} from "./api";
import { AppLayout } from "./components/layout";
import { LoadingState } from "./components/ui";
import { ConversationPage } from "./pages/conversation";
import { LoginPage } from "./pages/login";
import { SettingsPage } from "./pages/settings";

type Notice = {
  readonly id: number;
  readonly tone: "info" | "success" | "error";
  readonly message: string;
};

type MelloaContextValue = {
  readonly api: MelloaApi;
  readonly principal: AuthenticatedOwner;
  readonly status: SystemStatus | null;
  readonly canWrite: boolean;
  readonly canUseSensitiveControls: boolean;
  readonly notices: readonly Notice[];
  readonly login: (credential: string) => Promise<void>;
  readonly logout: () => Promise<void>;
  readonly refreshStatus: () => Promise<void>;
  readonly notify: (message: string, tone?: Notice["tone"]) => void;
  readonly dismissNotice: (id: number) => void;
};

const MelloaContext = createContext<MelloaContextValue | null>(null);
const api = new MelloaApi();

export function useMelloa(): MelloaContextValue {
  const value = useContext(MelloaContext);
  if (value === null) {
    throw new Error("useMelloa must be used inside the Melloa application");
  }
  return value;
}

export function App() {
  const [principal, setPrincipal] = useState<AuthenticatedOwner | null>(null);
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [booting, setBooting] = useState(true);
  const [notices, setNotices] = useState<readonly Notice[]>([]);
  const [nowMs, setNowMs] = useState(() => Date.now());
  const statusRefreshRequestRef = useRef(0);

  const notify = useCallback((message: string, tone: Notice["tone"] = "info") => {
    const id = Date.now() + Math.floor(Math.random() * 1_000);
    setNotices((current) => [...current, { id, tone, message }].slice(-3));
    window.setTimeout(() => {
      setNotices((current) => current.filter((notice) => notice.id !== id));
    }, 5_000);
  }, []);

  const dismissNotice = useCallback((id: number) => {
    setNotices((current) => current.filter((notice) => notice.id !== id));
  }, []);

  const refreshStatus = useCallback(async () => {
    const requestId = statusRefreshRequestRef.current + 1;
    statusRefreshRequestRef.current = requestId;
    try {
      const nextStatus = await api.systemStatus();
      if (!isLatestRequest(requestId, statusRefreshRequestRef.current)) {
        return;
      }
      setStatus(nextStatus);
    } catch (error) {
      if (!isLatestRequest(requestId, statusRefreshRequestRef.current)) {
        return;
      }
      setStatus(null);
      if (!(error instanceof ApiError && error.status === 503)) {
        notify(errorMessage(error), "error");
      }
    }
  }, [notify]);

  useEffect(() => {
    let active = true;
    void Promise.allSettled([api.systemStatus(), api.currentSession()]).then((results) => {
      if (!active) {
        return;
      }
      const [statusResult, sessionResult] = results;
      if (statusResult?.status === "fulfilled") {
        setStatus(statusResult.value);
      }
      if (sessionResult?.status === "fulfilled") {
        setPrincipal(sessionResult.value);
      }
      setBooting(false);
    });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (principal === null) {
      return;
    }
    const timer = window.setInterval(() => void refreshStatus(), 60_000);
    return () => window.clearInterval(timer);
  }, [principal, refreshStatus]);

  useEffect(() => {
    if (principal === null) {
      return;
    }
    setNowMs(Date.now());
    const timer = window.setInterval(() => setNowMs(Date.now()), 30_000);
    return () => window.clearInterval(timer);
  }, [principal]);

  const login = useCallback(async (credential: string) => {
    const nextPrincipal = await api.login(credential);
    setPrincipal(nextPrincipal);
    await refreshStatus();
  }, [refreshStatus]);

  const logout = useCallback(async () => {
    try {
      await api.logout();
    } finally {
      setPrincipal(null);
      notify("Signed out of the private Owner Console.");
    }
  }, [notify]);

  const context = useMemo<MelloaContextValue | null>(() => {
    if (principal === null) {
      return null;
    }
    return {
      api,
      principal,
      status,
      canWrite: api.hasMutationProof,
      canUseSensitiveControls: canUseMutationProof(principal, api.hasMutationProof, nowMs),
      notices,
      login,
      logout,
      refreshStatus,
      notify,
      dismissNotice,
    };
  }, [dismissNotice, login, logout, notices, notify, nowMs, principal, refreshStatus, status]);

  if (booting) {
    return <div className="boot-screen"><LoadingState label="Opening the private console" /></div>;
  }

  if (principal === null || context === null) {
    return (
      <BrowserRouter>
        <Routes>
          <Route path="*" element={<LoginPage login={login} refreshStatus={refreshStatus} status={status} />} />
        </Routes>
      </BrowserRouter>
    );
  }

  return (
    <MelloaContext.Provider value={context}>
      <BrowserRouter>
        <Routes>
          <Route element={<AppLayout />}>
            <Route path="/conversation/:threadId?" element={<ConversationPage />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="*" element={<Navigate replace to="/conversation" />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </MelloaContext.Provider>
  );
}

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    return error.message;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return "The private core returned an unexpected error.";
}

export function PageBoundary({ children }: { readonly children: ReactNode }) {
  return <>{children}</>;
}

export function isLatestRequest(requestId: number, latestRequestId: number): boolean {
  return requestId === latestRequestId;
}

export function canUseMutationProof(
  principal: AuthenticatedOwner,
  hasMutationProof: boolean,
  nowMs: number,
): boolean {
  if (!hasMutationProof) {
    return false;
  }
  const reauthenticatedUntil = Date.parse(principal.reauthenticated_until);
  return Number.isFinite(reauthenticatedUntil) && reauthenticatedUntil > nowMs;
}
