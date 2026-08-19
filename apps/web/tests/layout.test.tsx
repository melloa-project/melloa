import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AppLayout } from "../src/components/layout";

const mocks = vi.hoisted(() => ({
  context: {} as Record<string, unknown>,
  login: vi.fn(),
}));

vi.mock("../src/app", () => ({
  errorMessage: (error: unknown) => error instanceof Error ? error.message : "Unexpected error",
  useMelloa: () => mocks.context,
}));

function status() {
  return {
    access_scope: "loopback",
    public_ingress: false,
    external_actions_enabled: false,
    guardian: { mode: "offline" },
  };
}

function renderLayout() {
  return render(
    <MemoryRouter initialEntries={["/conversation"]}>
      <Routes>
        <Route element={<AppLayout />}>
          <Route path="/conversation" element={<div>Conversation body</div>} />
          <Route path="/settings" element={<div>Safety body</div>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

describe("AppLayout", () => {
  beforeEach(() => {
    mocks.login.mockReset().mockResolvedValue(undefined);
    mocks.context = {
      status: status(),
      canWrite: true,
      login: mocks.login,
      notices: [],
      dismissNotice: vi.fn(),
      notify: vi.fn(),
    };
  });

  it("makes Melli primary and keeps only one secondary owner-control destination", () => {
    renderLayout();

    expect(screen.getByRole("link", { name: "Open Melli" })).toBeVisible();
    expect(screen.getByRole("link", { name: "Data and safety" })).toBeVisible();
    expect(screen.queryByRole("link", { name: "Timeline" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Activity" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Memory" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Providers" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Operations" })).not.toBeInTheDocument();
    expect(screen.queryByText(/Guardian Offline/i)).not.toBeInTheDocument();
  });

  it("asks for owner access only when writing proof is unavailable", async () => {
    mocks.context = { ...mocks.context, canWrite: false };
    renderLayout();

    fireEvent.click(screen.getByRole("button", { name: "Unlock" }));
    expect(screen.getByRole("heading", { name: "Confirm it’s you" })).toBeVisible();
    fireEvent.change(screen.getByLabelText("Owner credential"), {
      target: { value: "b".repeat(32) },
    });
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));

    await waitFor(() => expect(mocks.login).toHaveBeenCalledWith("b".repeat(32)));
  });

  it("surfaces a protection failure without filling the header with healthy internals", () => {
    mocks.context = { ...mocks.context, status: null };
    renderLayout();

    expect(screen.getByText("Protection status unavailable")).toBeVisible();
    expect(screen.queryByText(/signed sequence/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/v0\.2\.0 preview/i)).not.toBeInTheDocument();
  });
});
