export type JsonObject = Record<string, unknown>;

export type AuthenticatedOwner = {
  readonly owner_id: string;
  readonly session_id: string;
  readonly authentication_method: string;
  readonly authenticated_at: string;
  readonly reauthenticated_until: string;
  readonly expires_at: string;
};

export type ConversationThread = {
  readonly thread_id: string;
  readonly owner_id: string;
  readonly intelligence_id: string;
  readonly title: string;
  readonly status: string;
  readonly sensitivity: string;
  readonly retention_policy: string;
  readonly created_at: string;
  readonly updated_at: string;
};

export type MessagePart = {
  readonly kind: string;
  readonly text?: string | null;
  readonly attachment_id?: string | null;
  readonly media_type?: string | null;
  readonly content_hash?: string | null;
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
  readonly delivery_state: string;
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
  readonly policy_decision_ids: readonly string[];
  readonly proposed_action_ids: readonly string[];
  readonly executed_action_ids: readonly string[];
  readonly output_message_ids: readonly string[];
  readonly decision_record: JsonObject;
  readonly started_at: string;
  readonly completed_at?: string | null;
};

export type ConversationProcessingAttempt = {
  readonly attempt_id: string;
  readonly work_id: string;
  readonly message_id: string;
  readonly attempt: number;
  readonly request_id?: string | null;
  readonly outcome: string;
  readonly error_code?: string | null;
  readonly started_at: string;
  readonly completed_at: string;
  readonly retry_at?: string | null;
  readonly retrieval_manifest_id?: string | null;
  readonly model_result_summary?: JsonObject | null;
  readonly model_route_attempts: readonly JsonObject[];
  readonly disclosed_memory_ids: readonly string[];
  readonly external_disclosure: boolean;
};

export type ConversationProcessingResumption = {
  readonly resumption_id: string;
  readonly work_id: string;
  readonly message_id: string;
  readonly requested_by: string;
  readonly requested_at: string;
  readonly prior_attempts: number;
  readonly added_attempts: number;
};

export type ConversationProcessingStatus = {
  readonly work_id: string;
  readonly thread_id: string;
  readonly message_id: string;
  readonly state: string;
  readonly attempt_count: number;
  readonly max_attempts: number;
  readonly available_at: string;
  readonly lease_expires_at?: string | null;
  readonly last_error_code?: string | null;
  readonly completed_at?: string | null;
  readonly attempts: readonly ConversationProcessingAttempt[];
  readonly resumptions: readonly ConversationProcessingResumption[];
};

export type ConversationReply = {
  readonly inbound_message: ConversationMessage;
  readonly output_message?: ConversationMessage | null;
  readonly turn?: ConversationTurn | null;
  readonly processing: ConversationProcessingStatus;
  readonly duplicate: boolean;
};

export type DeliveryWorkAttempt = {
  readonly attempt_id: string;
  readonly work_id: string;
  readonly message_id: string;
  readonly attempt: number;
  readonly authorization_request_id: string;
  readonly policy_decision_id: string;
  readonly action_hash: string;
  readonly outcome: string;
  readonly error_code?: string | null;
  readonly started_at: string;
  readonly completed_at: string;
  readonly retry_at?: string | null;
  readonly adapter_receipt?: JsonObject | null;
  readonly execution_receipt?: JsonObject | null;
};

export type DeliveryWorkResumption = {
  readonly resumption_id: string;
  readonly work_id: string;
  readonly message_id: string;
  readonly requested_by: string;
  readonly requested_at: string;
  readonly prior_attempts: number;
  readonly added_attempts: number;
  readonly authorization_request: JsonObject;
  readonly policy_decision: JsonObject;
};

export type DeliveryWorkStatus = {
  readonly work_id: string;
  readonly thread_id: string;
  readonly message_id: string;
  readonly requested_by: string;
  readonly client_adapter: string;
  readonly destination_ref: string;
  readonly action_hash: string;
  readonly current_policy_decision_id: string;
  readonly state: string;
  readonly attempt_count: number;
  readonly max_attempts: number;
  readonly available_at: string;
  readonly lease_expires_at?: string | null;
  readonly last_error_code?: string | null;
  readonly completed_at?: string | null;
  readonly attempts: readonly DeliveryWorkAttempt[];
  readonly resumptions: readonly DeliveryWorkResumption[];
};

export type DeliverySubmission = {
  readonly delivery: DeliveryWorkStatus;
  readonly created: boolean;
};

export type TelegramPairingCandidate = {
  readonly candidate_id: string;
  readonly update_id: number;
  readonly telegram_user_id: number;
  readonly telegram_chat_id: number;
  readonly observed_at: string;
  readonly expires_at: string;
};

export type TelegramOwnerPairing = {
  readonly contract_version: "1.0.0";
  readonly pairing_id: string;
  readonly candidate_id: string;
  readonly owner_id: string;
  readonly telegram_user_id: number;
  readonly telegram_chat_id: number;
  readonly confirmed_by_owner_id: string;
  readonly confirmed_at: string;
  readonly revoked_at: string | null;
};

export type TelegramChannelStatus = {
  readonly configured: boolean;
  readonly adapter_id: string;
  readonly state_persistence: "postgresql" | "process-only-preview";
  readonly polling: {
    readonly state: string;
    readonly reason_code: string;
    readonly next_offset: number;
    readonly poll_revision: number;
    readonly updates_handled: number;
    readonly last_error_code?: string | null;
    readonly source: {
      readonly status: string;
      readonly transport: string;
      readonly network: boolean;
      readonly last_success_at?: string | null;
      readonly last_error_code?: string | null;
    };
  } | null;
  readonly replies: {
    readonly state: string;
    readonly reason_code: string;
    readonly pending_replies: number;
    readonly deliveries_submitted: number;
    readonly recovery_after_update_id?: number | null;
    readonly last_error_code?: string | null;
  } | null;
  readonly delivery: {
    readonly status: string;
    readonly transport: string;
    readonly network: boolean;
    readonly last_success_at?: string | null;
    readonly last_error_code?: string | null;
  } | null;
  readonly capabilities: {
    readonly transport: string;
    readonly network: boolean;
    readonly text: boolean;
    readonly attachments: boolean;
    readonly max_text_length: number;
    readonly ambiguous_send_retries: boolean;
  } | null;
  readonly limitations: readonly string[];
};

export type ConversationTurnInspection = {
  readonly turn: ConversationTurn;
  readonly retrieval_manifest: JsonObject;
  readonly model_result: JsonObject;
  readonly output_message: ConversationMessage;
};

export type MemoryInspection = {
  readonly assertion: JsonObject & { readonly assertion_id: string; readonly value: JsonObject };
  readonly current_state: JsonObject & {
    readonly current_status: string;
    readonly version: number;
  };
  readonly provenance_edges: readonly JsonObject[];
  readonly state_changes: readonly JsonObject[];
};

export type ModelActivityReport = {
  readonly owner_id: string;
  readonly window_start: string;
  readonly window_end: string;
  readonly generated_at: string;
  readonly total_runs: number;
  readonly external_disclosure_runs: number;
  readonly total_input_tokens: number;
  readonly total_output_tokens: number;
  readonly total_cost_gbp: number;
  readonly external_cost_gbp: number;
  readonly entries: readonly ModelActivityEntry[];
};

export type ModelActivityEntry = {
  readonly turn_id: string;
  readonly thread_id: string;
  readonly result_id: string;
  readonly request_id: string;
  readonly route_id: string;
  readonly provider_id: string;
  readonly model_id: string;
  readonly input_tokens: number;
  readonly output_tokens: number;
  readonly cost_gbp: number;
  readonly started_at: string;
  readonly completed_at: string;
  readonly external_disclosure: boolean;
  readonly disclosure?: JsonObject | null;
};

export type ModelGatewayHealth = {
  readonly state: "healthy" | "degraded" | "unavailable" | "unknown";
  readonly checked_at: string;
  readonly latency_ms?: number | null;
  readonly reason_code: string;
};

export type ModelRouteStatus = {
  readonly route_id: string;
  readonly display_name: string;
  readonly route_kind: "synthetic" | "openai_compatible" | "cli_agent" | "acp_agent";
  readonly provider_id: string;
  readonly model_id: string;
  readonly processing_location: "device" | "private_network" | "approved_provider";
  readonly external_disclosure: boolean;
  readonly timeout_ms: number;
  readonly estimated_max_cost_gbp: number;
  readonly health: ModelGatewayHealth;
};

export type OwnerModelRouteReport = {
  readonly contract_version: "1.0.0";
  readonly owner_id: string;
  readonly generated_at: string;
  readonly routes: readonly ModelRouteStatus[];
};

export type SystemStatus = {
  readonly service: string;
  readonly milestone: string;
  readonly generated_at: string;
  readonly public_ingress: false;
  readonly external_actions_enabled: boolean;
  readonly guardian: {
    readonly mode: string;
    readonly sequence: number;
    readonly changed_at: string;
    readonly receipt_hash: string;
    readonly key_id: string;
  };
};

export type ComponentHealth = {
  readonly component_id: string;
  readonly category: string;
  readonly state: string;
  readonly required: boolean;
  readonly observed_at: string;
  readonly summary: string;
  readonly version?: string | null;
};

export type OwnerHealthReport = {
  readonly owner_id: string;
  readonly generated_at: string;
  readonly overall_state: string;
  readonly components: readonly ComponentHealth[];
};

export type MissingMediaInterval = {
  readonly started_at: string;
  readonly ended_at: string;
  readonly reason_code: string;
};

export type MediaSourceStatus = {
  readonly capability_id: string;
  readonly installed: boolean;
  readonly capture_enabled: boolean;
  readonly health_state: string;
  readonly observed_at: string;
  readonly status_reason: string;
  readonly last_capture_at?: string | null;
  readonly missing_intervals: readonly MissingMediaInterval[];
};

export type MediaItemMetadata = {
  readonly media_id: string;
  readonly owner_id: string;
  readonly source_capability_id: string;
  readonly event_id: string;
  readonly media_type: string;
  readonly content_hash: string;
  readonly sensitivity: string;
  readonly captured_from: string;
  readonly captured_to: string;
  readonly interpretation_confidence?: number | null;
  readonly retention_policy: string;
  readonly retained_at: string;
  readonly expires_at: string;
  readonly size_bytes: number;
  readonly retention_state: string;
  readonly disclosure_record_ids: readonly string[];
};

export type OwnerMediaCatalog = {
  readonly owner_id: string;
  readonly generated_at: string;
  readonly capture_enabled: boolean;
  readonly content_endpoint_available: false;
  readonly sources: readonly MediaSourceStatus[];
  readonly items: readonly MediaItemMetadata[];
};

export type RetentionDurationBounds = {
  readonly minimum_seconds: number;
  readonly default_seconds: number;
  readonly maximum_seconds: number;
};

export type RetentionPolicyStatus = {
  readonly policy_id: string;
  readonly data_category: string;
  readonly summary: string;
  readonly mode: string;
  readonly duration_bounds?: RetentionDurationBounds | null;
  readonly automatic_expiry: boolean;
  readonly deletion_control: string;
  readonly owner_deletion_scopes: readonly string[];
  readonly tombstone_retained: boolean;
  readonly derived_rebuild_required: boolean;
  readonly external_copy_state: string;
  readonly status_reason: string;
};

export type RetentionInventoryStatus = {
  readonly policy_id: string;
  readonly coverage: string;
  readonly retained_objects?: number | null;
  readonly retained_bytes?: number | null;
  readonly overdue_objects?: number | null;
  readonly pending_deletions?: number | null;
  readonly deletion_receipts?: number | null;
  readonly oldest_retained_at?: string | null;
  readonly next_expiry_at?: string | null;
  readonly status_reason: string;
};

export type BackupExpiryDisclosure = {
  readonly state: string;
  readonly status_reason: string;
  readonly maximum_retention_seconds?: number | null;
  readonly latest_snapshot_at?: string | null;
};

export type OwnerRetentionReport = {
  readonly contract_version: "1.0.0";
  readonly owner_id: string;
  readonly generated_at: string;
  readonly policies: readonly RetentionPolicyStatus[];
  readonly inventory: readonly RetentionInventoryStatus[];
  readonly backup_expiry: BackupExpiryDisclosure;
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
};

export class MelloaApi {
  readonly #fetch: FetchLike;
  #csrfToken: string | null = null;

  constructor(fetcher: FetchLike = (input, init) => fetch(input, init)) {
    this.#fetch = fetcher;
  }

  get hasMutationProof(): boolean {
    return this.#csrfToken !== null;
  }

  async login(credential: string): Promise<AuthenticatedOwner> {
    const issued = await this.#request<{
      readonly principal: AuthenticatedOwner;
      readonly csrf_token: string;
    }>("/api/v1/auth/session", {
      method: "POST",
      body: { credential },
    });
    this.#csrfToken = issued.csrf_token;
    return issued.principal;
  }

  async currentSession(): Promise<AuthenticatedOwner> {
    return this.#request<AuthenticatedOwner>("/api/v1/auth/session");
  }

  async logout(): Promise<void> {
    try {
      await this.#request<void>("/api/v1/auth/session", {
        method: "DELETE",
        csrf: true,
      });
    } finally {
      this.#csrfToken = null;
    }
  }

  async systemStatus(): Promise<SystemStatus> {
    return this.#request<SystemStatus>("/api/v1/system/status");
  }

  async healthDetail(): Promise<OwnerHealthReport> {
    return this.#request<OwnerHealthReport>("/api/v1/inspection/health");
  }

  async mediaCatalog(): Promise<OwnerMediaCatalog> {
    return this.#request<OwnerMediaCatalog>("/api/v1/inspection/media");
  }

  async retentionReport(): Promise<OwnerRetentionReport> {
    return this.#request<OwnerRetentionReport>("/api/v1/retention");
  }

  async modelRoutes(): Promise<OwnerModelRouteReport> {
    return this.#request<OwnerModelRouteReport>("/api/v1/providers/routes");
  }

  async listThreads(): Promise<readonly ConversationThread[]> {
    return this.#request<readonly ConversationThread[]>("/api/v1/conversations");
  }

  async createThread(input: {
    readonly title: string;
    readonly sensitivity: string;
    readonly retention_policy: string;
  }): Promise<ConversationThread> {
    return this.#request<ConversationThread>("/api/v1/conversations", {
      method: "POST",
      body: input,
      csrf: true,
    });
  }

  async listMessages(threadId: string): Promise<readonly ConversationMessage[]> {
    return this.#request<readonly ConversationMessage[]>(
      `/api/v1/conversations/${encodeURIComponent(threadId)}/messages`,
    );
  }

  async listTurns(threadId: string): Promise<readonly ConversationTurn[]> {
    return this.#request<readonly ConversationTurn[]>(
      `/api/v1/conversations/${encodeURIComponent(threadId)}/turns`,
    );
  }

  async listProcessing(threadId: string): Promise<readonly ConversationProcessingStatus[]> {
    return this.#request<readonly ConversationProcessingStatus[]>(
      `/api/v1/conversations/${encodeURIComponent(threadId)}/processing`,
    );
  }

  async inspectProcessing(
    threadId: string,
    messageId: string,
  ): Promise<ConversationProcessingStatus> {
    return this.#request<ConversationProcessingStatus>(
      `/api/v1/conversations/${encodeURIComponent(threadId)}/messages/${encodeURIComponent(messageId)}/processing`,
    );
  }

  async inspectTurn(threadId: string, turnId: string): Promise<ConversationTurnInspection> {
    return this.#request<ConversationTurnInspection>(
      `/api/v1/conversations/${encodeURIComponent(threadId)}/turns/${encodeURIComponent(turnId)}`,
    );
  }

  async postMessage(
    threadId: string,
    text: string,
    idempotencyKey: string,
  ): Promise<ConversationReply> {
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
      {
        method: "POST",
        csrf: true,
      },
    );
  }

  async listDeliveries(threadId: string): Promise<readonly DeliveryWorkStatus[]> {
    return this.#request<readonly DeliveryWorkStatus[]>(
      `/api/v1/conversations/${encodeURIComponent(threadId)}/deliveries`,
    );
  }

  async inspectDelivery(threadId: string, workId: string): Promise<DeliveryWorkStatus> {
    return this.#request<DeliveryWorkStatus>(
      `/api/v1/conversations/${encodeURIComponent(threadId)}/deliveries/${encodeURIComponent(workId)}`,
    );
  }

  async enqueueDelivery(
    threadId: string,
    input: {
      readonly message_id: string;
      readonly client_adapter: string;
      readonly destination_ref: string;
      readonly idempotency_key: string;
    },
  ): Promise<DeliverySubmission> {
    return this.#request<DeliverySubmission>(
      `/api/v1/conversations/${encodeURIComponent(threadId)}/deliveries`,
      {
        method: "POST",
        body: input,
        csrf: true,
      },
    );
  }

  async resumeDelivery(threadId: string, workId: string): Promise<DeliveryWorkStatus> {
    return this.#request<DeliveryWorkStatus>(
      `/api/v1/conversations/${encodeURIComponent(threadId)}/deliveries/${encodeURIComponent(workId)}/resume`,
      {
        method: "POST",
        csrf: true,
      },
    );
  }

  async listTelegramPairingCandidates(): Promise<readonly TelegramPairingCandidate[]> {
    return this.#request<readonly TelegramPairingCandidate[]>(
      "/api/v1/integrations/telegram/pairing/candidates",
    );
  }

  async inspectTelegramStatus(): Promise<TelegramChannelStatus> {
    return this.#request<TelegramChannelStatus>(
      "/api/v1/integrations/telegram/status",
    );
  }

  async inspectTelegramPairing(): Promise<TelegramOwnerPairing | null> {
    return this.#request<TelegramOwnerPairing | null>(
      "/api/v1/integrations/telegram/pairing",
    );
  }

  async confirmTelegramPairing(
    candidateId: string,
    confirmationCode: string,
  ): Promise<TelegramOwnerPairing> {
    return this.#request<TelegramOwnerPairing>(
      `/api/v1/integrations/telegram/pairing/candidates/${encodeURIComponent(candidateId)}/confirm`,
      {
        method: "POST",
        body: { confirmation_code: confirmationCode },
        csrf: true,
      },
    );
  }

  async revokeTelegramPairing(pairingId: string): Promise<TelegramOwnerPairing> {
    return this.#request<TelegramOwnerPairing>(
      `/api/v1/integrations/telegram/pairing/${encodeURIComponent(pairingId)}/revoke`,
      {
        method: "POST",
        csrf: true,
      },
    );
  }

  async inspectMemory(assertionId: string): Promise<MemoryInspection> {
    return this.#request<MemoryInspection>(
      `/api/v1/memory/${encodeURIComponent(assertionId)}`,
    );
  }

  async correctMemory(
    assertionId: string,
    value: JsonObject,
    expectedVersion: number,
  ): Promise<JsonObject> {
    return this.#request<JsonObject>(
      `/api/v1/memory/${encodeURIComponent(assertionId)}/corrections`,
      {
        method: "POST",
        body: { value, expected_version: expectedVersion },
        csrf: true,
      },
    );
  }

  async disputeMemory(assertionId: string, expectedVersion: number): Promise<JsonObject> {
    return this.#changeMemoryState(assertionId, "disputes", expectedVersion);
  }

  async retractMemory(assertionId: string, expectedVersion: number): Promise<JsonObject> {
    return this.#changeMemoryState(assertionId, "retractions", expectedVersion);
  }

  async modelActivity(windowStart?: Date, windowEnd?: Date): Promise<ModelActivityReport> {
    const query = new URLSearchParams();
    if (windowStart !== undefined) {
      query.set("from", windowStart.toISOString());
    }
    if (windowEnd !== undefined) {
      query.set("to", windowEnd.toISOString());
    }
    const suffix = query.size === 0 ? "" : `?${query.toString()}`;
    return this.#request<ModelActivityReport>(`/api/v1/inspection/model-activity${suffix}`);
  }

  async #changeMemoryState(
    assertionId: string,
    operation: "disputes" | "retractions",
    expectedVersion: number,
  ): Promise<JsonObject> {
    return this.#request<JsonObject>(
      `/api/v1/memory/${encodeURIComponent(assertionId)}/${operation}`,
      {
        method: "POST",
        body: { expected_version: expectedVersion },
        csrf: true,
      },
    );
  }

  async #request<T>(path: string, options: RequestOptions = {}): Promise<T> {
    const headers = new Headers({ Accept: "application/json" });
    if (options.body !== undefined) {
      headers.set("Content-Type", "application/json");
    }
    if (options.csrf === true) {
      if (this.#csrfToken === null) {
        throw new ApiError(
          403,
          "recent_authentication_required",
          "Sign in again before changing private state.",
        );
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
    const contentType = response.headers.get("content-type") ?? "";
    const payload: unknown = contentType.includes("application/json")
      ? await response.json()
      : null;
    if (!response.ok) {
      if (response.status === 401) {
        this.#csrfToken = null;
      }
      const error = isObject(payload) ? payload : {};
      const code = typeof error.code === "string" ? error.code : `http_${response.status}`;
      const detail = typeof error.detail === "string" ? error.detail : undefined;
      const message = typeof error.message === "string" ? error.message : detail;
      throw new ApiError(response.status, code, message ?? "Melloa API request failed.");
    }
    return payload as T;
  }
}

function isObject(value: unknown): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
