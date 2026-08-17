import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { OwnerModelRouteReport } from "../src/api";
import { ProvidersPage } from "../src/pages/providers";

const mocks = vi.hoisted(() => ({
  modelRoutes: vi.fn(),
  notify: vi.fn(),
}));

vi.mock("../src/app", () => {
  const context = {
    api: { modelRoutes: mocks.modelRoutes },
    notify: mocks.notify,
  };
  return {
    errorMessage: (error: unknown) => error instanceof Error ? error.message : "Unexpected error",
    useMelloa: () => context,
  };
});

const report: OwnerModelRouteReport = {
  contract_version: "1.0.0",
  owner_id: "owner_01",
  generated_at: "2026-08-16T12:00:00Z",
  routes: [
    {
      route_id: "model.local.qwen",
      display_name: "Local Qwen through Ollama",
      route_kind: "openai_compatible",
      provider_id: "provider.ollama",
      model_id: "qwen3:8b",
      processing_location: "device",
      external_disclosure: false,
      supported_modalities: ["text"],
      quality_profiles: ["quality.conversation"],
      allowed_sensitivities: ["public", "internal", "personal"],
      provider_retention_policies: ["retention.no-training"],
      max_input_tokens: 8192,
      max_output_tokens: 2048,
      reliability: 0.99,
      timeout_ms: 45_000,
      estimated_max_cost_gbp: 0,
      health: { state: "healthy", checked_at: "2026-08-16T12:00:00Z", latency_ms: 18, reason_code: "probe.succeeded" },
    },
    {
      route_id: "model.codex.subscription",
      display_name: "Codex subscription route",
      route_kind: "cli_agent",
      provider_id: "provider.openai-codex-subscription",
      model_id: "gpt-5.3-codex",
      processing_location: "approved_provider",
      external_disclosure: true,
      supported_modalities: ["text"],
      quality_profiles: ["quality.conversation"],
      allowed_sensitivities: ["public", "internal", "personal"],
      provider_retention_policies: ["retention.no-training"],
      max_input_tokens: 16384,
      max_output_tokens: 2048,
      reliability: 0.85,
      timeout_ms: 120_000,
      estimated_max_cost_gbp: 0,
      health: { state: "healthy", checked_at: "2026-08-16T12:00:00Z", latency_ms: 24, reason_code: "model.cli_agent.executable_ready" },
    },
    {
      route_id: "model.fake.deterministic",
      display_name: "Deterministic synthetic fixture",
      route_kind: "synthetic",
      provider_id: "provider.synthetic",
      model_id: "deterministic-fixture-v1",
      processing_location: "device",
      external_disclosure: false,
      supported_modalities: ["text"],
      quality_profiles: ["quality.conversation", "quality.conversation-synthetic"],
      allowed_sensitivities: ["public", "internal", "personal", "sensitive", "highly_sensitive", "device_only"],
      provider_retention_policies: ["retention.no-training"],
      max_input_tokens: 4096,
      max_output_tokens: 1024,
      reliability: 1,
      timeout_ms: 1_000,
      estimated_max_cost_gbp: 0,
      health: { state: "healthy", checked_at: "2026-08-16T12:00:00Z", latency_ms: 0, reason_code: "synthetic.ready" },
    },
  ],
};

describe("ProvidersPage", () => {
  beforeEach(() => {
    mocks.modelRoutes.mockReset();
    mocks.notify.mockReset();
    mocks.modelRoutes.mockResolvedValue(report);
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: {
        writeText: vi.fn().mockResolvedValue(undefined),
      },
    });
  });

  it("shows real route metadata and visibly labels synthetic fallback", async () => {
    render(
      <MemoryRouter>
        <ProvidersPage />
      </MemoryRouter>,
    );

    expect(await screen.findAllByText("Local Qwen through Ollama")).not.toHaveLength(0);
    expect(screen.getByText("qwen3:8b")).toBeInTheDocument();
    expect(screen.getAllByText("No external disclosure")).not.toHaveLength(0);
    expect(screen.getAllByText("Synthetic fixture")).not.toHaveLength(0);
    expect(screen.getByText(/not a real intelligence route/i)).toBeInTheDocument();
    expect(screen.getByText("Experimental Codex CLI")).toBeInTheDocument();
    expect(screen.getAllByText("External disclosure")).not.toHaveLength(0);
    expect(screen.getByText("Candidate response only")).toBeInTheDocument();
    expect(screen.getByText("Read-only sandbox")).toBeInTheDocument();
    expect(screen.getByText("Ephemeral session")).toBeInTheDocument();
    expect(screen.getByText("Approval policy: never")).toBeInTheDocument();
    expect(screen.getByText("Guardian normal required")).toBeInTheDocument();
    expect(screen.getByText("No Melloa authority")).toBeInTheDocument();
    expect(screen.getByText("Subscription · unreported")).toBeInTheDocument();
    expect(screen.getAllByText("Retention No Training")).not.toHaveLength(0);
    expect(screen.getAllByText("Public · Internal · Personal")).not.toHaveLength(0);
    expect(screen.getByText("8,192 in · 2,048 out")).toBeInTheDocument();
    expect(screen.getByText("99%")).toBeInTheDocument();

    const eligibility = within(screen.getByLabelText("Route privacy eligibility"));
    expect(eligibility.getByText("Device-only work")).toBeInTheDocument();
    expect(eligibility.getByText("Personal no-disclosure")).toBeInTheDocument();
    expect(eligibility.getByText("External disclosure")).toBeInTheDocument();
    expect(eligibility.getAllByText("1 healthy route")).toHaveLength(2);
    expect(eligibility.getAllByText("No owner-usable route")).toHaveLength(2);
    expect(eligibility.queryByText("No healthy route")).not.toBeInTheDocument();
    expect(eligibility.getByText("Local Qwen through Ollama")).toBeInTheDocument();
    expect(eligibility.getByText("Codex subscription route")).toBeInTheDocument();
    expect(eligibility.queryByText("Deterministic synthetic fixture")).not.toBeInTheDocument();
  });

  it("highlights a provider route from a route query", async () => {
    render(
      <MemoryRouter initialEntries={["/providers?route=model.codex.subscription"]}>
        <ProvidersPage />
      </MemoryRouter>,
    );

    const selectedBadge = await screen.findByText("Selected route");
    const selectedCard = selectedBadge.closest(".provider-card");
    expect(selectedCard).toBeInstanceOf(HTMLElement);
    expect(selectedCard).toHaveAttribute("aria-current", "true");
    expect(within(selectedCard as HTMLElement).getByText("model.codex.subscription")).toBeInTheDocument();
  });

  it("copies exact provider route ids from route cards", async () => {
    render(
      <MemoryRouter>
        <ProvidersPage />
      </MemoryRouter>,
    );

    await screen.findAllByText("Local Qwen through Ollama");

    fireEvent.click(screen.getByRole("button", { name: "Copy route ID model.codex.subscription" }));

    await waitFor(() => expect(navigator.clipboard.writeText).toHaveBeenCalledWith("model.codex.subscription"));
    expect(mocks.notify).toHaveBeenCalledWith("Route ID copied.", "success");
  });

  it("reports when provider route id copy is unavailable", async () => {
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: undefined,
    });

    render(
      <MemoryRouter>
        <ProvidersPage />
      </MemoryRouter>,
    );

    await screen.findAllByText("Local Qwen through Ollama");

    fireEvent.click(screen.getByRole("button", { name: "Copy route ID model.local.qwen" }));

    await waitFor(() => expect(mocks.notify).toHaveBeenCalledWith("Route ID copy failed.", "error"));
  });

  it("keeps the latest provider refresh when an older request resolves last", async () => {
    const stale = deferred<OwnerModelRouteReport>();
    const latest = deferred<OwnerModelRouteReport>();
    const localRoute = report.routes[0];
    const codexRoute = report.routes[1];
    if (localRoute === undefined || codexRoute === undefined) {
      throw new Error("Provider refresh race test requires local and Codex routes.");
    }
    mocks.modelRoutes.mockReset();
    mocks.modelRoutes.mockReturnValueOnce(stale.promise).mockReturnValueOnce(latest.promise);

    render(
      <MemoryRouter>
        <ProvidersPage />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole("button", { name: /refresh health/i }));

    await act(async () => {
      latest.resolve({
        ...report,
        routes: [codexRoute],
      });
      await latest.promise;
    });

    expect(await screen.findAllByText("Codex subscription route")).not.toHaveLength(0);

    await act(async () => {
      stale.resolve({
        ...report,
        routes: [localRoute],
      });
      await stale.promise;
    });

    await waitFor(() => {
      expect(screen.queryByText("Local Qwen through Ollama")).not.toBeInTheDocument();
    });
    expect(screen.getAllByText("Codex subscription route")).not.toHaveLength(0);
  });
});

type Deferred<T> = {
  readonly promise: Promise<T>;
  readonly reject: (reason?: unknown) => void;
  readonly resolve: (value: T) => void;
};

function deferred<T>(): Deferred<T> {
  let reject!: (reason?: unknown) => void;
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((promiseResolve, promiseReject) => {
    resolve = promiseResolve;
    reject = promiseReject;
  });
  return { promise, reject, resolve };
}
