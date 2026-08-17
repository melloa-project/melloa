import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  OwnerExportReadinessReport,
  OwnerHealthReport,
  OwnerMediaCatalog,
  OwnerRetentionReport,
} from "../src/api";
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
  canMutate: true,
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
    canMutate: mocks.canMutate,
    notify: mocks.notify,
  }),
}));

describe("OperationsPage retention view", () => {
  beforeEach(() => {
    for (const mock of [
      mocks.healthDetail,
      mocks.mediaCatalog,
      mocks.retentionReport,
      mocks.exportReadiness,
      mocks.downloadExportPreview,
      mocks.notify,
      mocks.createObjectUrl,
      mocks.revokeObjectUrl,
      mocks.anchorClick,
    ]) {
      mock.mockReset();
    }
    mocks.canMutate = true;
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
      components: [
        {
          component_id: "application.melloa-core",
          category: "application",
          state: "healthy",
          required: true,
          observed_at: "2026-08-16T12:00:00Z",
          summary: "Private Melloa core is serving authenticated owner requests.",
          version: "0.1.0",
        },
      ],
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
    fireEvent.click(within(retention).getByRole("button", { name: "Copy retention policy ID retention.owner-memory" }));
    await waitFor(() => expect(navigator.clipboard.writeText).toHaveBeenCalledWith("retention.owner-memory"));
    expect(mocks.notify).toHaveBeenCalledWith("Retention policy ID copied.", "success");
    expect(screen.getByText("Content-free audit ledger")).toBeInTheDocument();
    expect(screen.getByText("Audit records")).toBeInTheDocument();
    expect(screen.getByText("Security events are exposed here only as aggregate counts; credentials, cookies, tokens, prompts, and raw model output are not shown.")).toBeInTheDocument();
  });

  it("summarizes owner attention across loaded Operations reports", async () => {
    render(<OperationsPage />);

    const attention = await screen.findByLabelText("Owner attention summary");
    expect(within(attention).getByText("Required runtime checks are healthy")).toBeInTheDocument();
    expect(within(attention).getByText("1 required component reported healthy.")).toBeInTheDocument();
    expect(within(attention).getByText("Camera capture is disabled")).toBeInTheDocument();
    expect(within(attention).getByText("The current MVP should not be treated as ambient observation.")).toBeInTheDocument();
    expect(within(attention).getByText("Backup is not configured")).toBeInTheDocument();
    expect(within(attention).getByText("Retention Backup Not Configured")).toBeInTheDocument();
    expect(within(attention).getByText("Export remains a preview")).toBeInTheDocument();
    expect(within(attention).getByText("4 groups included, 2 explicit gaps, plaintext inner bundle.")).toBeInTheDocument();

    fireEvent.click(within(attention).getByRole("button", { name: /Backup is not configured/i }));

    expect(await screen.findByText("Backup expiry")).toBeInTheDocument();
  });

  it("surfaces required component failures before optional Operations detail", async () => {
    mocks.healthDetail.mockResolvedValueOnce({
      generated_at: "2026-08-16T12:00:00Z",
      overall_state: "unavailable",
      components: [
        {
          component_id: "application.melloa-core",
          category: "application",
          state: "unavailable",
          required: true,
          observed_at: "2026-08-16T12:00:00Z",
          summary: "Private Melloa core is unavailable.",
        },
        {
          component_id: "backup.not-configured",
          category: "backup",
          state: "disabled",
          required: false,
          observed_at: "2026-08-16T12:00:00Z",
          summary: "Backup remains disabled in this preview.",
        },
      ],
    });

    render(<OperationsPage />);

    const attention = await screen.findByLabelText("Owner attention summary");
    expect(within(attention).getByText("1 required component needs attention")).toBeInTheDocument();
    expect(within(attention).getByText("Application Melloa Core")).toBeInTheDocument();
    expect(within(attention).queryByText("Backup Not Configured")).not.toBeInTheDocument();
  });

  it("keeps the latest Operations refresh when an older request resolves last", async () => {
    const staleHealth = deferred<OwnerHealthReport>();
    mocks.healthDetail.mockReset();
    mocks.mediaCatalog.mockReset();
    mocks.retentionReport.mockReset();
    mocks.exportReadiness.mockReset();
    mocks.healthDetail
      .mockReturnValueOnce(staleHealth.promise)
      .mockResolvedValue(latestHealthReport());
    mocks.mediaCatalog
      .mockRejectedValueOnce(new Error("stale media unavailable"))
      .mockResolvedValue(latestMediaReport());
    mocks.retentionReport
      .mockRejectedValueOnce(new Error("stale retention unavailable"))
      .mockResolvedValue(latestRetentionReport());
    mocks.exportReadiness
      .mockRejectedValueOnce(new Error("stale export unavailable"))
      .mockResolvedValue(latestExportReport());

    render(<OperationsPage />);

    fireEvent.click(screen.getByRole("button", { name: /refresh all/i }));
    expect(mocks.healthDetail.mock.calls.length).toBeGreaterThan(1);

    const attention = await screen.findByLabelText("Owner attention summary");
    expect(within(attention).getByText("Required runtime checks are healthy")).toBeInTheDocument();
    expect(within(attention).getByText("1 required component reported healthy.")).toBeInTheDocument();
    expect(within(attention).getByText("0 action items")).toBeInTheDocument();
    expect(screen.getByText("Fresh private core health.")).toBeInTheDocument();

    staleHealth.resolve(staleHealthReport());
    await staleHealth.promise;
    await Promise.resolve();
    await Promise.resolve();

    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByText("Fresh private core health.")).toBeInTheDocument();
    expect(within(attention).getByText("Required runtime checks are healthy")).toBeInTheDocument();
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

  it("does not start a live export download when recent owner authentication lapses", async () => {
    const rendered = render(<OperationsPage />);

    fireEvent.click(await screen.findByRole("tab", { name: /Export/i }));
    expect(screen.getByRole("button", { name: "Download current ZIP" })).toBeEnabled();

    mocks.canMutate = false;
    rendered.rerender(<OperationsPage />);

    const downloadButton = screen.getByRole("button", { name: "Download current ZIP" });
    expect(downloadButton).toBeDisabled();
    fireEvent.click(downloadButton);

    expect(mocks.downloadExportPreview).not.toHaveBeenCalled();
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

function staleHealthReport(): OwnerHealthReport {
  return {
    owner_id: "owner_01",
    generated_at: "2026-08-16T12:00:00Z",
    overall_state: "unavailable",
    components: [
      {
        component_id: "application.melloa-core",
        category: "application",
        state: "unavailable",
        required: true,
        observed_at: "2026-08-16T12:00:00Z",
        summary: "Stale private core outage.",
      },
    ],
  };
}

function latestHealthReport(): OwnerHealthReport {
  return {
    owner_id: "owner_01",
    generated_at: "2026-08-16T12:01:00Z",
    overall_state: "healthy",
    components: [
      {
        component_id: "application.melloa-core",
        category: "application",
        state: "healthy",
        required: true,
        observed_at: "2026-08-16T12:01:00Z",
        summary: "Fresh private core health.",
        version: "0.1.0",
      },
    ],
  };
}

function latestMediaReport(): OwnerMediaCatalog {
  return {
    owner_id: "owner_01",
    generated_at: "2026-08-16T12:01:00Z",
    capture_enabled: false,
    content_endpoint_available: false,
    sources: [],
    items: [],
  };
}

function latestRetentionReport(): OwnerRetentionReport {
  return {
    contract_version: "1.0.0",
    owner_id: "owner_01",
    generated_at: "2026-08-16T12:01:00Z",
    backup_expiry: {
      state: "configured",
      status_reason: "retention.backup.configured",
    },
    policies: [],
    inventory: [],
  };
}

function latestExportReport(): OwnerExportReadinessReport {
  return {
    contract_version: "1.0.0",
    owner_id: "owner_01",
    generated_at: "2026-08-16T12:01:00Z",
    format_id: "melloa.canonical-owner-export",
    cli_command: "melloa export-mvp --output-dir <export-dir>",
    validation_command: "melloa import-validate --bundle-dir <export-dir>",
    encrypted: true,
    includes_sql_snapshot: false,
    includes_blobs: false,
    encrypted_package: {
      supported: false,
      package_format_id: "melloa.encrypted-owner-export-package",
      package_format_version: "1.0.0",
      passphrase_file_required: true,
      limitations: [],
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
    ],
    validation_checks: [
      {
        check_id: "export.validation.checksums",
        implemented: true,
        summary: "Checksums are verified.",
        status_reason: "export.validation.checksum-verification",
      },
    ],
    limitations: [],
  };
}
