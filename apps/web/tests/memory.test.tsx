import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useNavigate } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { MemoryInspection } from "../src/api";
import { MemoryPage, normalizeAssertionLookup } from "../src/pages/memory";

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

const updatedInspection: MemoryInspection = {
  ...retainedInspection,
  assertion: {
    ...retainedInspection.assertion,
    assertion_id: "assertion_00000000000000000000000000000002",
    predicate: "owner.preference.synthetic-exercise",
    value: { activity: "walking", fixture: true },
  },
  current_state: {
    assertion_id: "assertion_00000000000000000000000000000002",
    current_status: "confirmed",
    version: 1,
  },
};

const retainedInspectionWithProvenance: MemoryInspection = {
  ...retainedInspection,
  provenance_edges: [
    {
      edge_id: "edge_00000000000000000000000000000001",
      from_id: updatedInspection.assertion.assertion_id,
      to_id: retainedInspection.assertion.assertion_id,
      relation: "corrects",
      created_at: "2026-08-16T12:01:00Z",
      producer_id: "owner_00000000000000000000000000000001",
    },
  ],
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
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: {
        writeText: vi.fn().mockResolvedValue(undefined),
      },
    });
  });

  it("deletes retained assertion content and renders tombstone evidence", async () => {
    let contentDeleted = false;
    mocks.inspectMemory.mockImplementation(() => Promise.resolve(
      contentDeleted ? deletedInspection : retainedInspection,
    ));
    mocks.deleteMemoryContent.mockImplementation(() => {
      contentDeleted = true;
      return Promise.resolve({ created: true });
    });

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

  it("copies the exact inspected assertion id", async () => {
    render(
      <MemoryRouter initialEntries={[`/memory?assertion=${retainedInspection.assertion.assertion_id}`]}>
        <MemoryPage />
      </MemoryRouter>,
    );

    expect(await screen.findByText("reading")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Copy assertion ID" }));

    await waitFor(() => expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
      retainedInspection.assertion.assertion_id,
    ));
    expect(mocks.notify).toHaveBeenCalledWith("Assertion ID copied.", "success");
  });

  it("reports when assertion id copy is unavailable", async () => {
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: undefined,
    });
    render(
      <MemoryRouter initialEntries={[`/memory?assertion=${retainedInspection.assertion.assertion_id}`]}>
        <MemoryPage />
      </MemoryRouter>,
    );

    expect(await screen.findByText("reading")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Copy assertion ID" }));

    await waitFor(() => expect(mocks.notify).toHaveBeenCalledWith("Assertion ID copy failed.", "error"));
  });

  it("keeps memory modal mutations disabled when recent owner authentication lapses", async () => {
    const rendered = render(
      <MemoryRouter initialEntries={[`/memory?assertion=${retainedInspection.assertion.assertion_id}`]}>
        <MemoryPage />
      </MemoryRouter>,
    );

    expect(await screen.findByText("reading")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Delete content" }));
    expect(screen.getByRole("heading", { name: "Delete memory content" })).toBeInTheDocument();

    mocks.canMutate = false;
    rendered.rerender(
      <MemoryRouter initialEntries={[`/memory?assertion=${retainedInspection.assertion.assertion_id}`]}>
        <MemoryPage />
      </MemoryRouter>,
    );

    const dialog = screen.getByRole("dialog");
    const deleteButton = within(dialog).getByRole("button", { name: "Delete content" });
    expect(deleteButton).toBeDisabled();
    fireEvent.submit(deleteButton.closest("form") as HTMLFormElement);

    expect(mocks.deleteMemoryContent).not.toHaveBeenCalled();
    expect(mocks.notify).toHaveBeenCalledWith(
      "Unlock owner changes before changing memory.",
      "error",
    );
  });

  it("reloads inspection when the assertion query changes on the mounted page", async () => {
    mocks.inspectMemory.mockImplementation((assertionId: string) => Promise.resolve(
      assertionId === updatedInspection.assertion.assertion_id ? updatedInspection : retainedInspection,
    ));

    render(
      <MemoryRouter initialEntries={[`/memory?assertion=${retainedInspection.assertion.assertion_id}`]}>
        <Routes>
          <Route
            path="/memory"
            element={(
              <>
                <MemoryQuerySwitcher assertionId={updatedInspection.assertion.assertion_id} />
                <MemoryPage />
              </>
            )}
          />
        </Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByText("reading")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Open alternate memory" }));

    expect(await screen.findByText("walking")).toBeInTheDocument();
    expect(screen.queryByText("reading")).not.toBeInTheDocument();
    await waitFor(() => expect(mocks.inspectMemory).toHaveBeenCalledWith(
      updatedInspection.assertion.assertion_id,
    ));
  });

  it("normalizes assertion ids pasted from memory links and copied snippets", async () => {
    expect(normalizeAssertionLookup(
      `http://melloa.local/memory?assertion=${retainedInspection.assertion.assertion_id}`,
    )).toBe(retainedInspection.assertion.assertion_id);
    expect(normalizeAssertionLookup(
      `timeline reference ${updatedInspection.assertion.assertion_id} copied from export`,
    )).toBe(updatedInspection.assertion.assertion_id);
  });

  it("loads memory inspections from normalized assertion query references", async () => {
    mocks.inspectMemory.mockImplementation((assertionId: string) => Promise.resolve(
      assertionId === updatedInspection.assertion.assertion_id ? updatedInspection : retainedInspection,
    ));

    render(
      <MemoryRouter initialEntries={[`/memory?assertion=${encodeURIComponent(
        `timeline reference ${updatedInspection.assertion.assertion_id} copied from export`,
      )}`]}>
        <Routes>
          <Route path="/memory" element={<MemoryPage />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByText("walking")).toBeInTheDocument();
    await waitFor(() => expect(mocks.inspectMemory).toHaveBeenLastCalledWith(
      updatedInspection.assertion.assertion_id,
    ));
  });

  it("keeps the latest memory inspection when an older assertion response resolves last", async () => {
    const staleInspection = deferred<MemoryInspection>();
    mocks.inspectMemory.mockImplementation((assertionId: string) => (
      assertionId === retainedInspection.assertion.assertion_id
        ? staleInspection.promise
        : Promise.resolve(updatedInspection)
    ));

    render(
      <MemoryRouter initialEntries={[`/memory?assertion=${retainedInspection.assertion.assertion_id}`]}>
        <Routes>
          <Route
            path="/memory"
            element={(
              <>
                <MemoryQuerySwitcher assertionId={updatedInspection.assertion.assertion_id} />
                <MemoryPage />
              </>
            )}
          />
        </Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByText("Reading memory provenance")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Open alternate memory" }));

    expect(await screen.findByText("walking")).toBeInTheDocument();

    await act(async () => {
      staleInspection.resolve(retainedInspection);
      await staleInspection.promise;
    });

    await waitFor(() => {
      expect(screen.queryByText("reading")).not.toBeInTheDocument();
    });
    expect(screen.getByText("walking")).toBeInTheDocument();
  });

  it("opens related assertion inspections from provenance edges", async () => {
    mocks.inspectMemory.mockImplementation((assertionId: string) => Promise.resolve(
      assertionId === updatedInspection.assertion.assertion_id ? updatedInspection : retainedInspectionWithProvenance,
    ));

    render(
      <MemoryRouter initialEntries={[`/memory?assertion=${retainedInspection.assertion.assertion_id}`]}>
        <MemoryPage />
      </MemoryRouter>,
    );

    expect(await screen.findByText("reading")).toBeInTheDocument();
    const edgeSummary = screen.getAllByText("Corrects")[0] as HTMLElement;
    fireEvent.click(edgeSummary);
    expect(screen.getByText("Current assertion")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", {
      name: "Copy provenance edge ID edge_00000000000000000000000000000001",
    }));
    await waitFor(() => expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
      "edge_00000000000000000000000000000001",
    ));
    expect(mocks.notify).toHaveBeenCalledWith("Provenance edge ID copied.", "success");
    fireEvent.click(screen.getByRole("button", {
      name: `Copy From assertion ID ${updatedInspection.assertion.assertion_id}`,
    }));
    await waitFor(() => expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
      updatedInspection.assertion.assertion_id,
    ));
    fireEvent.click(screen.getByRole("button", {
      name: `Copy To assertion ID ${retainedInspection.assertion.assertion_id}`,
    }));
    await waitFor(() => expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
      retainedInspection.assertion.assertion_id,
    ));

    fireEvent.click(screen.getByRole("button", {
      name: `Inspect related memory assertion ${updatedInspection.assertion.assertion_id}`,
    }));

    expect(await screen.findByText("walking")).toBeInTheDocument();
    expect(screen.queryByText("reading")).not.toBeInTheDocument();
    await waitFor(() => expect(mocks.inspectMemory).toHaveBeenCalledWith(
      updatedInspection.assertion.assertion_id,
    ));
  });
});

function MemoryQuerySwitcher({ assertionId }: { readonly assertionId: string }) {
  const navigate = useNavigate();
  return (
    <button onClick={() => navigate(`/memory?assertion=${assertionId}`)} type="button">
      Open alternate memory
    </button>
  );
}

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
