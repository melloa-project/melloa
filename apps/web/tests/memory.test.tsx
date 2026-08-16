import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { MemoryInspection } from "../src/api";
import { MemoryPage } from "../src/pages/memory";

const mocks = vi.hoisted(() => ({
  inspectMemory: vi.fn(),
  correctMemory: vi.fn(),
  disputeMemory: vi.fn(),
  retractMemory: vi.fn(),
  deleteMemoryContent: vi.fn(),
  notify: vi.fn(),
  canMutate: true,
}));

vi.mock("../src/app", () => ({
  errorMessage: (error: unknown) => error instanceof Error ? error.message : "Unexpected error",
  useMelloa: () => ({
    api: {
      inspectMemory: mocks.inspectMemory,
      correctMemory: mocks.correctMemory,
      disputeMemory: mocks.disputeMemory,
      retractMemory: mocks.retractMemory,
      deleteMemoryContent: mocks.deleteMemoryContent,
    },
    canMutate: mocks.canMutate,
    notify: mocks.notify,
  }),
}));

const retainedInspection: MemoryInspection = {
  content_state: "retained",
  assertion: {
    assertion_id: "assertion_00000000000000000000000000000001",
    subject_id: "owner_00000000000000000000000000000001",
    predicate: "owner.preference.synthetic-activity",
    value: { activity: "reading", fixture: true },
    epistemic_status: "owner_confirmed",
    source_authority: "owner_authored",
    sensitivity: "personal",
    observed_at: "2026-08-16T12:00:00Z",
  },
  deletion_tombstone: null,
  backup_expiry: null,
  current_state: {
    assertion_id: "assertion_00000000000000000000000000000001",
    current_status: "confirmed",
    version: 1,
  },
  provenance_edges: [],
  state_changes: [
    {
      change_id: "state_change_00000000000000000000000000000001",
      reason: "assertion.initialized",
      new_status: "confirmed",
      version: 1,
    },
  ],
};

const deletedInspection: MemoryInspection = {
  ...retainedInspection,
  content_state: "deleted",
  assertion: {
    ...retainedInspection.assertion,
    value: undefined,
  },
  deletion_tombstone: {
    tombstone_id: "deletion_00000000000000000000000000000001",
    assertion_id: retainedInspection.assertion.assertion_id,
    owner_id: "owner_00000000000000000000000000000001",
    deleted_by_record_id: "owner_00000000000000000000000000000001",
    content_hash: "sha256:" + "1".repeat(64),
    size_bytes: 72,
    retention_policy: "retention.owner-memory",
    retained_at: "2026-08-16T12:00:00Z",
    deleted_at: "2026-08-16T12:05:00Z",
    reason_code: "memory.assertion-content-owner-deleted",
    rebuild_work_id: "work_00000000000000000000000000000001",
  },
  backup_expiry: {
    state: "unknown",
    status_reason: "retention.backup.expiry_unknown",
  },
};

describe("MemoryPage", () => {
  beforeEach(() => {
    mocks.inspectMemory.mockReset();
    mocks.correctMemory.mockReset();
    mocks.disputeMemory.mockReset();
    mocks.retractMemory.mockReset();
    mocks.deleteMemoryContent.mockReset();
    mocks.notify.mockReset();
    mocks.canMutate = true;
    mocks.inspectMemory.mockResolvedValue(retainedInspection);
    mocks.deleteMemoryContent.mockResolvedValue({ created: true });
  });

  it("deletes retained assertion content and renders tombstone evidence", async () => {
    mocks.inspectMemory
      .mockResolvedValueOnce(retainedInspection)
      .mockResolvedValueOnce(deletedInspection);

    render(
      <MemoryRouter initialEntries={[`/memory?assertion=${retainedInspection.assertion.assertion_id}`]}>
        <MemoryPage />
      </MemoryRouter>,
    );

    expect(await screen.findByText("reading")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Delete content" }));
    expect(screen.getByRole("heading", { name: "Delete memory content" })).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("button", { name: "Delete content" }).at(-1) as HTMLButtonElement);

    await waitFor(() => expect(mocks.deleteMemoryContent).toHaveBeenCalledWith(
      retainedInspection.assertion.assertion_id,
    ));
    expect(await screen.findByText(/Assertion content was deleted by owner request/i)).toBeInTheDocument();
    expect(screen.getByText("Backup expiry")).toBeInTheDocument();
    expect(screen.getByText("Unknown")).toBeInTheDocument();
    expect(screen.getByText("Assertion Initialized")).toBeInTheDocument();
    expect(screen.getAllByText("v1").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByRole("button", { name: "Correct" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Dispute" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Delete content" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Retract" })).toBeDisabled();
    expect(mocks.notify).toHaveBeenCalledWith("Memory content deleted.", "success");
  });

  it("disables mutation controls without a live mutation proof", async () => {
    mocks.canMutate = false;
    render(
      <MemoryRouter initialEntries={[`/memory?assertion=${retainedInspection.assertion.assertion_id}`]}>
        <MemoryPage />
      </MemoryRouter>,
    );

    expect(await screen.findByText("reading")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Correct" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Delete content" })).toBeDisabled();
  });
});
