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

export function formatDurationMs(value: number): string {
  if (value < 1_000) {
    return `${Math.max(0, Math.round(value))} ms`;
  }
  return `${(value / 1_000).toFixed(value < 10_000 ? 1 : 0)} s`;
}

export function titleCase(value: string): string {
  return value
    .replaceAll(/[._-]+/g, " ")
    .replaceAll(/\b\w/g, (character) => character.toUpperCase());
}

export function messageBody(message: ConversationMessage): string {
  return message.parts.map((part) => part.text).join("\n");
}

export type TurnMetadata = {
  readonly modelId: string;
  readonly location: string;
  readonly externalDisclosure: boolean;
  readonly latencyMs: number;
};

export function turnMetadata(inspection: ConversationTurnInspection): TurnMetadata {
  const result = inspection.model_result;
  const startedAt = readString(result, "started_at");
  const completedAt = readString(result, "completed_at");
  const latencyMs = Math.max(
    0,
    new Date(completedAt).getTime() - new Date(startedAt).getTime(),
  );
  return {
    modelId: readString(result, "model_id"),
    location: readString(result, "processing_location"),
    externalDisclosure: result.external_disclosure === true,
    latencyMs: Number.isNaN(latencyMs) ? 0 : latencyMs,
  };
}

export function readString(value: JsonObject, key: string): string {
  return typeof value[key] === "string" ? value[key] : "unknown";
}
