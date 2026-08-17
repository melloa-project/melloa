import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { OperationsPage } from "../src/pages/operations";

const mocks = vi.hoisted(() => ({
  healthDetail: vi.fn(),
  mediaCatalog: vi.fn(),
  retentionReport: vi.fn(),
  exportReadiness: vi.fn(),
  downloadExportPreview: vi.fn(),
  notify: vi.fn(),
  createObjectUrl: vi.fn(),
  revokeObjectUrl: vi.fn(),
  anchorClick: vi.fn(),
}));

vi.mock("../src/app", () => ({
  errorMessage: (error: unknown) => error instanceof Error ? error.message : "Unexpected error",
  useMelloa: () => ({
    api: {
      healthDetail: mocks.healthDetail,
      mediaCatalog: mocks.mediaCatalog,
      retentionReport: mocks.retentionReport,
      exportReadiness: mocks.exportReadiness,
      downloadExportPreview: mocks.downloadExportPreview,
    },
    canMutate: true,
    notify: mocks.notify,
  }),
}));

describe("OperationsPage retention view", () => {
  beforeEach(() => {
    for (const mock of Object.values(mocks)) {
      mock.mockReset();
    }
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: {
        writeText: vi.fn().mockResolvedValue(undefined),
      },
    });
    Object.defineProperty(URL, "createObjectURL", {
      configurable: true,
      value: mocks.createObjectUrl,
    });
    Object.defineProperty(URL, "revokeObjectURL", {
      configurable: true,
      value: mocks.revokeObjectUrl,
    });
    Object.defineProperty(HTMLAnchorElement.prototype, "click", {
      configurable: true,
      value: mocks.anchorClick,
    });
    mocks.createObjectUrl.mockReturnValue("blob:melloa-owner-export");
    mocks.downloadExportPreview.mockResolvedValue({
      blob: new Blob(["validated archive"], { type: "application/zip" }),
      filename: "melloa-owner-export-export_01.zip",
    });
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
          coverage: "complete",
          retained_objects: 3,
          retained_bytes: 2048,
          overdue_objects: 0,
          pending_deletions: 0,
          deletion_receipts: 0,
          oldest_retained_at: "2026-08-16T11:50:00Z",
          status_reason: "retention.inventory.audit_event_store",
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
      encrypted_package: {
        supported: true,
        package_format_id: "melloa.encrypted-owner-export-package",
        package_format_version: "1.0.0",
        package_command: "melloa export-encrypt --bundle-dir <export-dir> --passphrase-file <passphrase-file> --output-file <export-dir>.melloaenc",
        validation_command: "melloa export-decrypt-validate --package-file <export-dir>.melloaenc --passphrase-file <passphrase-file>",
        passphrase_file_required: true,
        required_file_mode: "0600",
        cipher: "aes-256-gcm",
        kdf: "scrypt",
        limitations: [
          "export.package-not-backup-proof",
          "export.package-not-signed",
          "export.package-wraps-preview-bundle",
        ],
      },
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
          group_id: "export.delivery-records",
          included: true,
          estimated_records: 1,
          artifact_path: "conversations/deliveries.jsonl",
          summary: "Redacted outbound delivery work status.",
          status_reason: "export.coverage.delivery-jsonl",
        },
        {
          group_id: "export.model-activity",
          included: true,
          estimated_records: 1,
          artifact_path: "inspection/model-activity.jsonl",
          summary: "Redacted model activity report.",
          status_reason: "export.coverage.model-activity",
        },
        {
          group_id: "export.retention-report",
          included: true,
          estimated_records: 1,
          artifact_path: "inspection/retention.jsonl",
          summary: "Owner-visible retention policy and aggregate inventory disclosure.",
          status_reason: "export.coverage.retention-report",
        },
        {
          group_id: "export.blobs",
          included: false,
          artifact_path: null,
          summary: "Attachment, media, and object-store blobs are not exported.",
          status_reason: "export.coverage.blobs-not-included",
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
    expect(within(retention).getByText("3 objects")).toBeInTheDocument();
    expect(within(retention).getByText("2.0 KiB")).toBeInTheDocument();
    expect(within(retention).getAllByText("Not available")).toHaveLength(2);
    expect(within(retention).getAllByText("Deletion receipts")).toHaveLength(2);
    expect(within(retention).getByText("Owner Request")).toBeInTheDocument();
    expect(within(retention).getAllByText("Oldest retained")).toHaveLength(2);
    expect(screen.getByText("Content-free audit ledger")).toBeInTheDocument();
    expect(screen.getByText("Audit records")).toBeInTheDocument();
    expect(screen.getByText("Security events are exposed here only as aggregate counts; credentials, cookies, tokens, prompts, and raw model output are not shown.")).toBeInTheDocument();
  });

  it("renders export coverage and validation commands without claiming backup coverage", async () => {
    render(<OperationsPage />);

    fireEvent.click(await screen.findByRole("tab", { name: /Export/i }));

    const commands = screen.getByLabelText("Export commands");
    expect(within(commands).getByText("melloa export-mvp --output-dir <export-dir>")).toBeInTheDocument();
    expect(within(commands).getByText("melloa import-validate --bundle-dir <export-dir>")).toBeInTheDocument();
    const copyButtons = within(commands).getAllByRole("button", { name: "Copy" });
    expect(copyButtons).toHaveLength(2);
    expect(screen.getByText("Unencrypted preview")).toBeInTheDocument();
    expect(screen.getByText("Included groups")).toBeInTheDocument();
    expect(screen.getByText("4 of 6")).toBeInTheDocument();
    expect(screen.getByText("Validation checks")).toBeInTheDocument();
    expect(screen.getByText("1 of 2")).toBeInTheDocument();
    expect(screen.getByText("Known gaps")).toBeInTheDocument();
    expect(screen.getByText("Inner bundle")).toBeInTheDocument();
    expect(screen.getByText("Plaintext")).toBeInTheDocument();
    expect(screen.getByText("Package encryption")).toBeInTheDocument();
    expect(screen.getByText("aes-256-gcm")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Download current ZIP" })).toBeEnabled();
    expect(screen.getByText("Validated before download. The ZIP is not encrypted and excludes blobs and SQL snapshots.")).toBeInTheDocument();
    const packageCommands = screen.getByLabelText("Encrypted package commands");
    expect(within(packageCommands).getByText("melloa.encrypted-owner-export-package")).toBeInTheDocument();
    expect(within(packageCommands).getByText("aes-256-gcm with scrypt; passphrase file mode 0600")).toBeInTheDocument();
    expect(within(packageCommands).getByText("melloa export-encrypt --bundle-dir <export-dir> --passphrase-file <passphrase-file> --output-file <export-dir>.melloaenc")).toBeInTheDocument();
    expect(within(packageCommands).getByText("melloa export-decrypt-validate --package-file <export-dir>.melloaenc --passphrase-file <passphrase-file>")).toBeInTheDocument();
    expect(screen.getByText("Included artifacts")).toBeInTheDocument();
    expect(screen.getByText("Explicit gaps")).toBeInTheDocument();
    expect(screen.getByText("conversations/*.jsonl")).toBeInTheDocument();
    expect(screen.getByText("conversations/deliveries.jsonl")).toBeInTheDocument();
    expect(screen.getByText("inspection/model-activity.jsonl")).toBeInTheDocument();
    expect(screen.getByText("inspection/retention.jsonl")).toBeInTheDocument();
    const conversationCoverage = screen
      .getByText("conversations/*.jsonl")
      .closest(".export-coverage-row");
    expect(conversationCoverage).toBeInstanceOf(HTMLElement);
    expect(within(conversationCoverage as HTMLElement).getByText("7 estimated records")).toBeInTheDocument();
    const retentionCoverage = screen
      .getByText("inspection/retention.jsonl")
      .closest(".export-coverage-row");
    expect(retentionCoverage).toBeInstanceOf(HTMLElement);
    expect(within(retentionCoverage as HTMLElement).getByText("1 estimated record")).toBeInTheDocument();
    expect(screen.getByText("Import validation scope")).toBeInTheDocument();
    expect(screen.getByText("Every bundled file is verified against checksums.sha256 before records are trusted.")).toBeInTheDocument();
    expect(screen.getByText("Validation is a dry run and does not import into a database or execute migrations.")).toBeInTheDocument();
    expect(screen.getByText("Checked")).toBeInTheDocument();
    expect(screen.getByText("Pending")).toBeInTheDocument();
    expect(screen.getByText("Logical SQL snapshots remain pending.")).toBeInTheDocument();
    expect(screen.getByText("Attachment, media, and object-store blobs are not exported.")).toBeInTheDocument();
    expect(screen.getAllByText("Excluded")).toHaveLength(2);
    expect(screen.getByText(/Export Package Not Signed/i)).toBeInTheDocument();
  });

  it("copies export commands from the Operations view", async () => {
    render(<OperationsPage />);

    fireEvent.click(await screen.findByRole("tab", { name: /Export/i }));
    const commands = screen.getByLabelText("Export commands");
    const [copyExport, copyValidation] = within(commands).getAllByRole("button", { name: "Copy" });
    const packageCommands = screen.getByLabelText("Encrypted package commands");
    const [copyPackage, copyPackageValidation] = within(packageCommands).getAllByRole("button", { name: "Copy" });

    fireEvent.click(copyExport!);
    await screen.findByText("Export command copied");
    expect(navigator.clipboard.writeText).toHaveBeenLastCalledWith(
      "melloa export-mvp --output-dir <export-dir>",
    );

    fireEvent.click(copyValidation!);
    await screen.findByText("Validation command copied");
    expect(navigator.clipboard.writeText).toHaveBeenLastCalledWith(
      "melloa import-validate --bundle-dir <export-dir>",
    );

    fireEvent.click(copyPackage!);
    await screen.findByText("Package command copied");
    expect(navigator.clipboard.writeText).toHaveBeenLastCalledWith(
      "melloa export-encrypt --bundle-dir <export-dir> --passphrase-file <passphrase-file> --output-file <export-dir>.melloaenc",
    );

    fireEvent.click(copyPackageValidation!);
    await screen.findByText("Package validation command copied");
    expect(navigator.clipboard.writeText).toHaveBeenLastCalledWith(
      "melloa export-decrypt-validate --package-file <export-dir>.melloaenc --passphrase-file <passphrase-file>",
    );
  });

  it("downloads the validated live export and releases its object URL", async () => {
    render(<OperationsPage />);

    fireEvent.click(await screen.findByRole("tab", { name: /Export/i }));
    fireEvent.click(screen.getByRole("button", { name: "Download current ZIP" }));

    await waitFor(() => expect(mocks.downloadExportPreview).toHaveBeenCalledOnce());
    expect(mocks.createObjectUrl).toHaveBeenCalledOnce();
    expect(mocks.anchorClick).toHaveBeenCalledOnce();
    expect(mocks.revokeObjectUrl).toHaveBeenCalledWith("blob:melloa-owner-export");
    expect(mocks.notify).toHaveBeenCalledWith(
      "Validated unencrypted export downloaded.",
      "success",
    );
  });
});
