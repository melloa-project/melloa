import type {
  AuthenticatedOwner,
  ConversationMessage,
  DeliveryWorkStatus,
  JsonObject,
} from "./api.js";

export type AreaId = "conversation" | "timeline" | "memory" | "runs" | "media" | "operations";

export type ConsoleArea = {
  readonly id: AreaId;
  readonly label: string;
};

export const areas: readonly ConsoleArea[] = [
  { id: "conversation", label: "Conversation" },
  { id: "timeline", label: "Timeline" },
  { id: "memory", label: "Memory" },
  { id: "runs", label: "Runs & Decisions" },
  { id: "media", label: "Media" },
  { id: "operations", label: "Operations" },
];

export type TextTarget = {
  textContent: string | null;
};

export function writeText(target: TextTarget, value: string | number | null | undefined): void {
  target.textContent = value === null || value === undefined ? "" : String(value);
}

export function formatInstant(value: string | null | undefined): string {
  if (value === null || value === undefined || value === "") {
    return "—";
  }
  const instant = new Date(value);
  if (Number.isNaN(instant.valueOf())) {
    return "Invalid timestamp";
  }
  return instant.toISOString().replace("T", " ").replace(".000Z", " UTC");
}

export function formatCount(value: number): string {
  return new Intl.NumberFormat("en-GB", { maximumFractionDigits: 0 }).format(value);
}

export function formatGbp(value: number): string {
  return new Intl.NumberFormat("en-GB", {
    style: "currency",
    currency: "GBP",
    minimumFractionDigits: 2,
    maximumFractionDigits: 6,
  }).format(value);
}

export function formatJson(value: unknown): string {
  return JSON.stringify(value, null, 2) ?? "null";
}

export function messageBody(message: ConversationMessage): string {
  return message.parts
    .map((part) => {
      if (part.kind === "text" && part.text !== null && part.text !== undefined) {
        return part.text;
      }
      if (part.kind === "attachment") {
        return `[Attachment: ${part.media_type ?? "unknown type"} · ${part.attachment_id ?? "unknown ID"}]`;
      }
      return `[${part.kind}]`;
    })
    .join("\n");
}

export type DeliveryRecoverySummary = {
  readonly label: string;
  readonly detail: string;
  readonly tone: "completed" | "ready" | "running" | "dead" | "cancelled";
  readonly canResume: boolean;
};

export function deliveryRecoverySummary(delivery: DeliveryWorkStatus): DeliveryRecoverySummary {
  const attemptBudget = `${formatCount(delivery.attempt_count)}/${formatCount(delivery.max_attempts)}`;
  const recoveryCount = delivery.resumptions.length;
  const recoveryDetail =
    recoveryCount === 0
      ? "No owner resumptions recorded."
      : `${formatCount(recoveryCount)} owner resumption${recoveryCount === 1 ? "" : "s"} recorded.`;
  if (delivery.state === "completed") {
    return {
      label: "Completed",
      detail: `Delivery completed after ${attemptBudget} attempts. ${recoveryDetail}`,
      tone: "completed",
      canResume: false,
    };
  }
  if (delivery.state === "dead") {
    return {
      label: "Owner action required",
      detail: `Automatic attempts are exhausted (${attemptBudget}). Last redacted error: ${delivery.last_error_code ?? "none recorded"}. ${recoveryDetail}`,
      tone: "dead",
      canResume: true,
    };
  }
  if (delivery.state === "running") {
    return {
      label: "Attempt in progress",
      detail: `Attempt budget ${attemptBudget}; lease expires ${formatInstant(delivery.lease_expires_at)}. ${recoveryDetail}`,
      tone: "running",
      canResume: false,
    };
  }
  if (delivery.state === "cancelled") {
    return {
      label: "Cancelled",
      detail: `Delivery is cancelled after ${attemptBudget} attempts. ${recoveryDetail}`,
      tone: "cancelled",
      canResume: false,
    };
  }
  return {
    label: delivery.attempt_count === 0 ? "Queued" : "Retry scheduled",
    detail: `Attempt budget ${attemptBudget}; next eligible ${formatInstant(delivery.available_at)}. ${recoveryDetail}`,
    tone: "ready",
    canResume: false,
  };
}

export function parseJsonObject(source: string): JsonObject {
  const value: unknown = JSON.parse(source);
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error("Correction value must be a JSON object.");
  }
  return value as JsonObject;
}

export function hasRecentAuthentication(
  principal: AuthenticatedOwner | null,
  now: number = Date.now(),
): boolean {
  if (principal === null) {
    return false;
  }
  const deadline = Date.parse(principal.reauthenticated_until);
  return Number.isFinite(deadline) && deadline > now;
}

export function mutationCapabilities(
  principal: AuthenticatedOwner | null,
  hasCsrfProof: boolean,
  now: number = Date.now(),
): { readonly standard: boolean; readonly sensitive: boolean } {
  const standard = principal !== null && hasCsrfProof;
  return {
    standard,
    sensitive: standard && hasRecentAuthentication(principal, now),
  };
}

export function defaultActivityWindow(now: Date = new Date()): { readonly from: string; readonly to: string } {
  const end = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate() + 1));
  const start = new Date(end);
  start.setUTCDate(start.getUTCDate() - 7);
  return {
    from: start.toISOString().slice(0, 10),
    to: end.toISOString().slice(0, 10),
  };
}

export function parseActivityWindow(from: string, to: string): {
  readonly start: Date;
  readonly end: Date;
} {
  const start = new Date(`${from}T00:00:00.000Z`);
  const end = new Date(`${to}T00:00:00.000Z`);
  if (from === "" || to === "" || Number.isNaN(start.valueOf()) || Number.isNaN(end.valueOf())) {
    throw new Error("Choose valid UTC dates for the activity window.");
  }
  if (end <= start) {
    throw new Error("The exclusive end date must be after the start date.");
  }
  return { start, end };
}

export function shortId(value: string): string {
  if (value.length <= 20) {
    return value;
  }
  return `${value.slice(0, 12)}…${value.slice(-6)}`;
}
