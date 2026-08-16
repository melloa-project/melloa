import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { OperationsPage } from "../src/pages/operations";

const mocks = vi.hoisted(() => ({
  healthDetail: vi.fn(),
  mediaCatalog: vi.fn(),
  retentionReport: vi.fn(),
  exportReadiness: vi.fn(),
}));

vi.mock("../src/app", () => ({
  errorMessage: (error: unknown) => error instanceof Error ? error.message : "Unexpected error",
  useMelloa: () => ({
    api: {
      healthDetail: mocks.healthDetail,
      mediaCatalog: mocks.mediaCatalog,
      retentionReport: mocks.retentionReport,
      exportReadiness: mocks.exportReadiness,
    },
  }),
}));

describe("OperationsPage retention view", () => {
  beforeEach(() => {
    for (const mock of Object.values(mocks)) {
      mock.mockReset();
    }
    mocks.healthDetail.mockResolvedValue({
      generated_at: "2026-08-16T12:00:00Z",
      overall_state: "healthy",
      components: [],
    });
    mocks.mediaCatalog.mockResolvedValue({
      generated_at: "2026-08-16T12:00:00Z",
      capture_enabled: false,
      content_endpoint_available: false,
      sources: [],
      items: [],
    });
    mocks.retentionReport.mockResolvedValue({
      contract_version: "1.0.0",
      owner_id: "owner_01",
      generated_at: "2026-08-16T12:00:00Z",
      backup_expiry: {
        state: "not-configured",
        status_reason: "retention.backup.not_configured",
      },
      policies: [
        {
          policy_id: "retention.owner-memory",
          data_category: "data.memory-assertion",
          summary: "Memory values can be deleted by owner request.",
          mode: "owner-lifecycle",
          automatic_expiry: false,
          deletion_control: "owner-request",
          owner_deletion_scopes: ["memory-claim"],
          tombstone_retained: true,
          derived_rebuild_required: true,
          external_copy_state: "provider-controlled",
          status_reason: "retention.owner_memory.content_deletion_available",
        },
      ],
      inventory: [
        {
          policy_id: "retention.owner-memory",
          coverage: "complete",
          retained_objects: 1,
          retained_bytes: 12288,
          overdue_objects: 0,
          pending_deletions: 0,
          deletion_receipts: 2,
          oldest_retained_at: "2026-08-16T11:55:00Z",
          status_reason: "retention.inventory.canonical_memory",
        },
      ],
    });
    mocks.exportReadiness.mockResolvedValue({
      contract_version: "1.0.0",
      owner_id: "owner_01",
      generated_at: "2026-08-16T12:00:00Z",
      format_id: "melloa.canonical-owner-export",
      cli_command: "melloa export-mvp --output-dir <export-dir>",
      validation_command: "melloa import-validate --bundle-dir <export-dir>",
      encrypted: false,
      includes_sql_snapshot: false,
      includes_blobs: false,
      coverage: [
        {
          group_id: "export.conversation-records",
          included: true,
          artifact_path: "conversations/*.jsonl",
          summary: "Canonical conversation records.",
          status_reason: "export.coverage.conversation-jsonl",
        },
        {
          group_id: "export.logical-sql",
          included: false,
          artifact_path: null,
          summary: "Logical SQL snapshots remain pending.",
          status_reason: "export.coverage.sql-snapshot-not-included",
        },
      ],
      limitations: [
        "export.blobs-not-included",
        "export.preview-unencrypted",
        "export.sql-snapshot-not-included",
      ],
    });
  });

  it("renders canonical retention bytes and deletion receipt evidence", async () => {
    render(<OperationsPage />);

    fireEvent.click(await screen.findByRole("tab", { name: /Retention/i }));

    const retention = screen.getByLabelText("Retention policies");
    expect(within(retention).getByText("Retained bytes")).toBeInTheDocument();
    expect(within(retention).getByText("12.0 KiB")).toBeInTheDocument();
    expect(within(retention).getByText("Deletion receipts")).toBeInTheDocument();
    expect(within(retention).getByText("Owner Request")).toBeInTheDocument();
    expect(within(retention).getByText("Oldest retained")).toBeInTheDocument();
  });

  it("renders export coverage and validation commands without claiming backup coverage", async () => {
    render(<OperationsPage />);

    fireEvent.click(await screen.findByRole("tab", { name: /Export/i }));

    const commands = screen.getByLabelText("Export commands");
    expect(within(commands).getByText("melloa export-mvp --output-dir <export-dir>")).toBeInTheDocument();
    expect(within(commands).getByText("melloa import-validate --bundle-dir <export-dir>")).toBeInTheDocument();
    expect(screen.getByText("Unencrypted preview")).toBeInTheDocument();
    expect(screen.getByText("conversations/*.jsonl")).toBeInTheDocument();
    expect(screen.getByText("Logical SQL snapshots remain pending.")).toBeInTheDocument();
    expect(screen.getByText("Excluded")).toBeInTheDocument();
  });
});
