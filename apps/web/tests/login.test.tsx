import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import type { SystemStatus } from "../src/api";
import { LoginPage } from "../src/pages/login";

const verifiedStatus: SystemStatus = {
  contract_version: "1.0.0",
  service: "melloa-core",
  version: "0.2.0",
  release_display: "v0.2.0 preview",
  stage: "preview",
  milestone: "M1",
  architecture_baseline: "v0.2",
  generated_at: "2026-08-18T12:00:00Z",
  public_ingress: false,
  external_actions_enabled: false,
  guardian: {
    mode: "no-actions",
    sequence: 4,
    changed_at: "2026-08-18T11:59:00Z",
    receipt_hash: "sha256:guardian-receipt",
    key_id: "guardian.status-v1",
  },
};

describe("LoginPage", () => {
  it("states the private and independent authority boundaries", () => {
    render(<MemoryRouter><LoginPage login={vi.fn()} refreshStatus={vi.fn()} status={null} /></MemoryRouter>);

    expect(screen.getByText("Private by design")).toBeInTheDocument();
    expect(screen.getByText("Guardian remains independent")).toBeInTheDocument();
    expect(screen.getByText("No browser persistence")).toBeInTheDocument();
    expect(screen.getByText("Release unverified")).toHaveAccessibleName(
      "Runtime release: Release unverified",
    );
  });

  it("identifies the verified preview release before authentication", () => {
    render(
      <MemoryRouter>
        <LoginPage login={vi.fn()} refreshStatus={vi.fn()} status={verifiedStatus} />
      </MemoryRouter>,
    );

    expect(screen.getByText("v0.2.0 preview")).toHaveAccessibleName(
      "Runtime release: v0.2.0 preview",
    );
  });

  it("submits the owner credential and clears the field", async () => {
    const login = vi.fn(async () => undefined);
    render(<MemoryRouter><LoginPage login={login} refreshStatus={vi.fn()} status={null} /></MemoryRouter>);
    const input = screen.getByLabelText("Owner credential");
    fireEvent.change(input, { target: { value: "a".repeat(32) } });
    fireEvent.click(screen.getByRole("button", { name: /Open Owner Console/ }));

    await waitFor(() => expect(login).toHaveBeenCalledWith("a".repeat(32)));
    expect(input).toHaveValue("");
  });

  it("retries the signed runtime status check before authentication", async () => {
    const refreshStatus = vi.fn(async () => undefined);
    render(<MemoryRouter><LoginPage login={vi.fn()} refreshStatus={refreshStatus} status={null} /></MemoryRouter>);

    fireEvent.click(screen.getByRole("button", { name: "Retry signed status check" }));

    await waitFor(() => expect(refreshStatus).toHaveBeenCalledOnce());
  });
});
