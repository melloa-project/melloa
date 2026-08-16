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
          policy_id: "retention.audit-ledger",
          data_category: "data.audit-ledger",
          summary: "Security and action evidence is append-oriented and deletion-restricted.",
          mode: "append-only",
          automatic_expiry: false,
          deletion_control: "restricted",
          owner_deletion_scopes: [],
          tombstone_retained: true,
          derived_rebuild_required: false,
          external_copy_state: "none",
          status_reason: "retention.audit.restricted",
        },
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
          policy_id: "retention.audit-ledger",
          coverage: "unavailable",
          status_reason: "retention.inventory.audit_not_assembled",
        },
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
          estimated_records: 7,
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
      validation_checks: [
        {
          check_id: "export.validation.checksums",
          implemented: true,
          summary: "Every bundled file is verified against checksums.sha256 before records are trusted.",
          status_reason: "export.validation.checksum-verification",
        },
        {
          check_id: "export.validation.restore-execution",
          implemented: false,
          summary: "Validation is a dry run and does not import into a database or execute migrations.",
          status_reason: "export.validation.restore-execution-pending",
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
    expect(within(retention).getAllByText("Retained bytes")).toHaveLength(2);
    expect(within(retention).getByText("12.0 KiB")).toBeInTheDocument();
    expect(within(retention).getByText("Unavailable")).toBeInTheDocument();
    expect(within(retention).getAllByText("Not measured")).toHaveLength(4);
    expect(within(retention).getAllByText("Deletion receipts")).toHaveLength(2);
    expect(within(retention).getByText("Owner Request")).toBeInTheDocument();
    expect(within(retention).getAllByText("Oldest retained")).toHaveLength(2);
  });

  it("renders export coverage and validation commands without claiming backup coverage", async () => {
    render(<OperationsPage />);

    fireEvent.click(await screen.findByRole("tab", { name: /Export/i }));

    const commands = screen.getByLabelText("Export commands");
    expect(within(commands).getByText("melloa export-mvp --output-dir <export-dir>")).toBeInTheDocument();
    expect(within(commands).getByText("melloa import-validate --bundle-dir <export-dir>")).toBeInTheDocument();
    expect(screen.getByText("Unencrypted preview")).toBeInTheDocument();
    expect(screen.getByText("conversations/*.jsonl")).toBeInTheDocument();
    const conversationCoverage = screen
      .getByText("conversations/*.jsonl")
      .closest(".export-coverage-row");
    expect(conversationCoverage).toBeInstanceOf(HTMLElement);
    expect(within(conversationCoverage as HTMLElement).getByText("7 estimated records")).toBeInTheDocument();
    expect(screen.getByText("Import validation scope")).toBeInTheDocument();
    expect(screen.getByText("Every bundled file is verified against checksums.sha256 before records are trusted.")).toBeInTheDocument();
    expect(screen.getByText("Validation is a dry run and does not import into a database or execute migrations.")).toBeInTheDocument();
    expect(screen.getByText("Checked")).toBeInTheDocument();
    expect(screen.getByText("Pending")).toBeInTheDocument();
    expect(screen.getByText("Logical SQL snapshots remain pending.")).toBeInTheDocument();
    expect(screen.getByText("Excluded")).toBeInTheDocument();
  });
});
