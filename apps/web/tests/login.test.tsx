import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import type { SystemStatus } from "../src/api";
import { LoginPage } from "../src/pages/login";

const status: SystemStatus = {
  contract_version: "1.0.0",
  service: "melloa-core",
  version: "0.2.0",
  release_display: "v0.2.0 preview",
  stage: "preview",
  generated_at: "2026-08-19T12:00:00Z",
  access_scope: "loopback",
  public_ingress: false,
  external_actions_enabled: false,
  guardian: {
    mode: "offline",
    sequence: 2,
    changed_at: "2026-08-19T12:00:00Z",
    receipt_hash: `sha256:${"1".repeat(64)}`,
    key_id: "guardian-key",
  },
};

describe("LoginPage", () => {
  it("leads with the owner relationship and keeps the reset limitation honest", () => {
    render(
      <MemoryRouter>
        <LoginPage login={vi.fn()} refreshStatus={vi.fn()} status={status} />
      </MemoryRouter>,
    );

    expect(screen.getByRole("heading", { name: "Pick up where you left off." })).toBeVisible();
    expect(screen.getByText(/understand your history, goals, and changing context/i)).toBeVisible();
    expect(screen.getByText(/early owner-experience reset/i)).toBeVisible();
    expect(screen.getByText("Private access verified")).toBeVisible();
    expect(screen.queryByText(/route behind every response/i)).not.toBeInTheDocument();
  });

  it("submits and clears the local owner credential", async () => {
    const login = vi.fn().mockResolvedValue(undefined);
    render(
      <MemoryRouter>
        <LoginPage login={login} refreshStatus={vi.fn()} status={status} />
      </MemoryRouter>,
    );

    const input = screen.getByLabelText("Owner credential");
    fireEvent.change(input, { target: { value: "a".repeat(32) } });
    fireEvent.click(screen.getByRole("button", { name: /Continue to Melli/ }));

    await waitFor(() => expect(login).toHaveBeenCalledWith("a".repeat(32)));
    expect(input).toHaveValue("");
  });

  it("fails visibly when protection cannot be verified and can retry", async () => {
    const refreshStatus = vi.fn().mockResolvedValue(undefined);
    render(
      <MemoryRouter>
        <LoginPage login={vi.fn()} refreshStatus={refreshStatus} status={null} />
      </MemoryRouter>,
    );

    expect(screen.getByText("Protection status unavailable")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Retry protection status" }));
    await waitFor(() => expect(refreshStatus).toHaveBeenCalledOnce());
  });
});
