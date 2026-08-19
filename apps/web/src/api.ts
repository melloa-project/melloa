export type JsonObject = Record<string, unknown>;

export type AuthenticatedOwner = {
  readonly owner_id: string;
  readonly session_id: string;
  readonly authentication_method: string;
  readonly authenticated_at: string;
  readonly reauthenticated_until: string;
  readonly expires_at: string;
};

export type OwnerSessionInventory = {
  readonly current_session_id: string;
  readonly sessions: readonly AuthenticatedOwner[];
};

export type OwnerSessionRevocationResult = {
  readonly revoked_count: number;
};

export type ConversationThread = {
  readonly thread_id: string;
  readonly owner_id: string;
  readonly intelligence_id: string;
  readonly title: string;
  readonly status: string;
  readonly sensitivity: string;
  readonly created_at: string;
  readonly updated_at: string;
};

export type ConversationDeletionReceipt = {
  readonly deletion_id: string;
  readonly thread_id: string;
  readonly owner_id: string;
  readonly deleted_at: string;
  readonly active_data_deleted: true;
  readonly backup_expiry_state: "unknown";
};

export type MessagePart = {
  readonly kind: string;
  readonly text: string;
};

export type ConversationMessage = {
  readonly message_id: string;
  readonly thread_id: string;
  readonly author_principal_id: string;
  readonly source_client: string;
  readonly parts: readonly MessagePart[];
  readonly reply_to_message_id?: string | null;
  readonly corrects_message_id?: string | null;
  readonly citation_ids: readonly string[];
  readonly sensitivity: string;
  readonly created_at: string;
  readonly observed_at: string;
};

export type ConversationTurn = {
  readonly turn_id: string;
  readonly thread_id: string;
  readonly triggering_message_ids: readonly string[];
  readonly retrieval_manifest_id?: string | null;
  readonly evidence_ids: readonly string[];
  readonly model_run_ids: readonly string[];
  readonly output_message_ids: readonly string[];
  readonly decision_record: JsonObject;
  readonly started_at: string;
  readonly completed_at?: string | null;
};

export type ConversationProcessingAttempt = {
  readonly model_result_summary?: JsonObject | null;
};

export type ConversationProcessingStatus = {
  readonly message_id: string;
  readonly state: string;
  readonly attempts: readonly ConversationProcessingAttempt[];
};

export type ConversationTranscript = {
  readonly messages: readonly ConversationMessage[];
  readonly turns: readonly ConversationTurn[];
  readonly processing: readonly ConversationProcessingStatus[];
};

export type ConversationReply = {
  readonly inbound_message: ConversationMessage;
  readonly output_message?: ConversationMessage | null;
  readonly turn?: ConversationTurn | null;
  readonly processing: ConversationProcessingStatus;
  readonly duplicate: boolean;
};

export type ConversationTurnInspection = {
  readonly turn: ConversationTurn;
  readonly retrieval_manifest: JsonObject;
  readonly model_result: JsonObject;
  readonly output_message: ConversationMessage;
};

export type ConversationAvailability = {
  readonly available: boolean;
};

export type SystemStatus = {
  readonly contract_version: "1.0.0";
  readonly service: "melloa-core";
  readonly version: string;
  readonly release_display: string;
  readonly stage: string;
  readonly generated_at: string;
  readonly access_scope: "loopback" | "private-network" | "unverified";
  readonly public_ingress: boolean | null;
  readonly external_actions_enabled: boolean;
  readonly guardian: {
    readonly mode: string;
    readonly sequence: number;
    readonly changed_at: string;
    readonly receipt_hash: string;
    readonly key_id: string;
  };
};

export type ExportCoverageItem = {
  readonly included: boolean;
};

export type OwnerExportReadinessReport = {
  readonly encrypted: boolean;
  readonly coverage: readonly ExportCoverageItem[];
  readonly validation_checks: readonly JsonObject[];
  readonly limitations: readonly string[];
};

export type OwnerExportArchive = {
  readonly blob: Blob;
  readonly filename: string;
};

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

type FetchLike = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;

type RequestOptions = {
  readonly method?: string;
  readonly body?: JsonObject;
  readonly csrf?: boolean;
  readonly accept?: string;
};

export class MelloaApi {
  readonly #fetch: FetchLike;
  #csrfToken: string | null = null;
  readonly #mutationProofListeners = new Set<() => void>();

  constructor(fetcher: FetchLike = (input, init) => fetch(input, init)) {
    this.#fetch = fetcher;
  }

  get hasMutationProof(): boolean {
    return this.#csrfToken !== null;
  }

  subscribeMutationProof(listener: () => void): () => void {
    this.#mutationProofListeners.add(listener);
    return () => this.#mutationProofListeners.delete(listener);
  }

  async login(credential: string): Promise<AuthenticatedOwner> {
    const issued = await this.#request<{
      readonly principal: AuthenticatedOwner;
      readonly csrf_token: string;
    }>("/api/v1/auth/session", {
      method: "POST",
      body: { credential },
    });
    this.#setCsrfToken(issued.csrf_token);
    return issued.principal;
  }

  async currentSession(): Promise<AuthenticatedOwner> {
    return this.#request<AuthenticatedOwner>("/api/v1/auth/session");
  }

  async activeSessions(): Promise<OwnerSessionInventory> {
    return this.#request<OwnerSessionInventory>("/api/v1/auth/sessions");
  }

  async revokeOtherSessions(): Promise<OwnerSessionRevocationResult> {
    return this.#request<OwnerSessionRevocationResult>("/api/v1/auth/sessions/others", {
      method: "DELETE",
      csrf: true,
    });
  }

  async logout(): Promise<void> {
    try {
      await this.#request<void>("/api/v1/auth/session", { method: "DELETE", csrf: true });
    } finally {
      this.#setCsrfToken(null);
    }
  }

  async systemStatus(): Promise<SystemStatus> {
    return this.#request<SystemStatus>("/api/v1/system/status");
  }

  async exportReadiness(): Promise<OwnerExportReadinessReport> {
    return this.#request<OwnerExportReadinessReport>("/api/v1/data-export");
  }

  async downloadExportPreview(): Promise<OwnerExportArchive> {
    const response = await this.#response("/api/v1/data-export/archive", {
      method: "POST",
      csrf: true,
      accept: "application/zip",
    });
    const contentType = response.headers.get("content-type") ?? "";
    if (!contentType.includes("application/zip")) {
      throw new ApiError(502, "invalid_export_response", "The private core returned an invalid export archive.");
    }
    return {
      blob: await response.blob(),
      filename: exportArchiveFilename(response.headers.get("content-disposition")),
    };
  }

  async conversationAvailability(): Promise<ConversationAvailability> {
    return this.#request<ConversationAvailability>("/api/v1/conversations/availability");
  }

  async listThreads(): Promise<readonly ConversationThread[]> {
    return this.#request<readonly ConversationThread[]>("/api/v1/conversations");
  }

  async createThread(input: {
    readonly title: string;
    readonly sensitivity: string;
  }): Promise<ConversationThread> {
    return this.#request<ConversationThread>("/api/v1/conversations", {
      method: "POST",
      body: input,
      csrf: true,
    });
  }

  async deleteThread(threadId: string): Promise<ConversationDeletionReceipt> {
    return this.#request<ConversationDeletionReceipt>(
      `/api/v1/conversations/${encodeURIComponent(threadId)}`,
      { method: "DELETE", csrf: true },
    );
  }

  async transcript(threadId: string): Promise<ConversationTranscript> {
    return this.#request<ConversationTranscript>(
      `/api/v1/conversations/${encodeURIComponent(threadId)}/transcript`,
    );
  }

  async inspectTurn(threadId: string, turnId: string): Promise<ConversationTurnInspection> {
    return this.#request<ConversationTurnInspection>(
      `/api/v1/conversations/${encodeURIComponent(threadId)}/turns/${encodeURIComponent(turnId)}`,
    );
  }

  async postMessage(threadId: string, text: string, idempotencyKey: string): Promise<ConversationReply> {
    return this.#request<ConversationReply>(
      `/api/v1/conversations/${encodeURIComponent(threadId)}/messages`,
      {
        method: "POST",
        body: { text, idempotency_key: idempotencyKey },
        csrf: true,
      },
    );
  }

  async resumeMessage(threadId: string, messageId: string): Promise<ConversationReply> {
    return this.#request<ConversationReply>(
      `/api/v1/conversations/${encodeURIComponent(threadId)}/messages/${encodeURIComponent(messageId)}/resume`,
      { method: "POST", csrf: true },
    );
  }

  async #request<T>(path: string, options: RequestOptions = {}): Promise<T> {
    const response = await this.#response(path, options);
    const contentType = response.headers.get("content-type") ?? "";
    const payload: unknown = contentType.includes("application/json") ? await response.json() : null;
    return payload as T;
  }

  async #response(path: string, options: RequestOptions = {}): Promise<Response> {
    const headers = new Headers({ Accept: options.accept ?? "application/json" });
    if (options.body !== undefined) {
      headers.set("Content-Type", "application/json");
    }
    if (options.csrf === true) {
      if (this.#csrfToken === null) {
        throw new ApiError(403, "owner_access_required", "Confirm owner access before changing private state.");
      }
      headers.set("X-Melloa-CSRF", this.#csrfToken);
    }
    const fetcher = this.#fetch;
    const response = await fetcher(path, {
      method: options.method ?? "GET",
      headers,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      credentials: "same-origin",
      cache: "no-store",
      redirect: "error",
    });
    if (!response.ok) {
      const contentType = response.headers.get("content-type") ?? "";
      const payload: unknown = contentType.includes("application/json") ? await response.json() : null;
      const error = isObject(payload) ? payload : {};
      const code = typeof error.code === "string" ? error.code : `http_${response.status}`;
      if (response.status === 401 || code === "csrf_validation_failed") {
        this.#setCsrfToken(null);
      }
      const detail = typeof error.detail === "string" ? error.detail : undefined;
      const message = typeof error.message === "string" ? error.message : detail;
      throw new ApiError(response.status, code, message ?? "Melloa API request failed.");
    }
    return response;
  }

  #setCsrfToken(value: string | null): void {
    if (this.#csrfToken === value) {
      return;
    }
    this.#csrfToken = value;
    for (const listener of this.#mutationProofListeners) {
      listener();
    }
  }
}

function isObject(value: unknown): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function exportArchiveFilename(contentDisposition: string | null): string {
  const filename = contentDisposition?.match(/filename="([A-Za-z0-9._-]+)"/i)?.[1];
  return filename ?? "melloa-owner-export.zip";
}
