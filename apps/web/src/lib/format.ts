import type {
  ConversationMessage,
  ConversationTurnInspection,
  JsonObject,
} from "../api";

export function formatInstant(value: string | null | undefined): string {
  if (value === null || value === undefined || value.length === 0) {
    return "Not available";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "Invalid time";
  }
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

export function formatRelative(value: string): string {
  const timestamp = new Date(value).getTime();
  if (Number.isNaN(timestamp)) {
    return "unknown";
  }
  const seconds = Math.round((timestamp - Date.now()) / 1_000);
  const absolute = Math.abs(seconds);
  const formatter = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });
  if (absolute < 60) {
    return formatter.format(seconds, "second");
  }
  const minutes = Math.round(seconds / 60);
  if (Math.abs(minutes) < 60) {
    return formatter.format(minutes, "minute");
  }
  const hours = Math.round(minutes / 60);
  if (Math.abs(hours) < 24) {
    return formatter.format(hours, "hour");
  }
  return formatter.format(Math.round(hours / 24), "day");
}

export function formatGbp(value: number): string {
  if (value === 0) {
    return "£0.00";
  }
  if (value < 0.01) {
    return `<£0.01`;
  }
  return new Intl.NumberFormat(undefined, {
    style: "currency",
    currency: "GBP",
  }).format(value);
}

export function formatCount(value: number): string {
  return new Intl.NumberFormat().format(value);
}

export function formatDurationMs(value: number): string {
  if (value < 1_000) {
    return `${Math.max(0, Math.round(value))} ms`;
  }
  return `${(value / 1_000).toFixed(value < 10_000 ? 1 : 0)} s`;
}

export function shortId(value: string): string {
  if (value.length <= 18) {
    return value;
  }
  return `${value.slice(0, 9)}…${value.slice(-6)}`;
}

export function redactNumericIdentifier(value: number): string {
  if (!Number.isSafeInteger(value)) {
    return "Invalid identifier";
  }
  const suffix = Math.abs(value).toString().slice(-4).padStart(4, "•");
  return `••••${suffix}`;
}

export function titleCase(value: string): string {
  return value
    .replaceAll(/[._-]+/g, " ")
    .replaceAll(/\b\w/g, (character) => character.toUpperCase());
}

export function messageBody(message: ConversationMessage): string {
  const text = message.parts
    .filter((part) => part.kind === "text" && typeof part.text === "string")
    .map((part) => part.text ?? "")
    .join("\n");
  const attachments = message.parts.filter((part) => part.kind === "attachment").length;
  if (text.length > 0 && attachments > 0) {
    return `${text}\n\n${attachments} quarantined attachment${attachments === 1 ? "" : "s"}`;
  }
  if (text.length > 0) {
    return text;
  }
  if (attachments > 0) {
    return `${attachments} quarantined attachment${attachments === 1 ? "" : "s"}`;
  }
  return "Empty canonical message";
}

export type TurnMetadata = {
  readonly routeId: string;
  readonly providerId: string;
  readonly modelId: string;
  readonly location: string;
  readonly externalDisclosure: boolean;
  readonly inputTokens: number;
  readonly outputTokens: number;
  readonly costGbp: number;
  readonly latencyMs: number;
  readonly attempts: readonly JsonObject[];
};

export function turnMetadata(inspection: ConversationTurnInspection): TurnMetadata {
  const result = inspection.model_result;
  const attempts = asObjectArray(result.attempts);
  const finalAttempt = attempts.at(-1);
  const startedAt = readString(result, "started_at");
  const completedAt = readString(result, "completed_at");
  const latencyMs = Math.max(
    0,
    new Date(completedAt).getTime() - new Date(startedAt).getTime(),
  );
  return {
    routeId: readString(result, "route_id"),
    providerId: readString(result, "provider_id"),
    modelId: readString(result, "model_id"),
    location: finalAttempt === undefined
      ? "unknown"
      : readString(finalAttempt, "processing_location"),
    externalDisclosure: result.external_disclosure === true,
    inputTokens: readNumber(result, "input_tokens"),
    outputTokens: readNumber(result, "output_tokens"),
    costGbp: readNumber(result, "cost_gbp"),
    latencyMs: Number.isNaN(latencyMs) ? 0 : latencyMs,
    attempts,
  };
}

export function asObject(value: unknown): JsonObject | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? value as JsonObject
    : null;
}

export function asObjectArray(value: unknown): readonly JsonObject[] {
  return Array.isArray(value)
    ? value.map(asObject).filter((item): item is JsonObject => item !== null)
    : [];
}

export function readString(value: JsonObject, key: string): string {
  return typeof value[key] === "string" ? value[key] : "unknown";
}

export function readNumber(value: JsonObject, key: string): number {
  return typeof value[key] === "number" ? value[key] : 0;
}

export function safeJson(value: unknown): string {
  return JSON.stringify(value, null, 2);
}
