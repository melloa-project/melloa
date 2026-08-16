import { describe, expect, it } from "vitest";

import type { ConversationMessage, ConversationTurnInspection } from "../src/api";
import { messageBody, redactNumericIdentifier, safeJson, turnMetadata } from "../src/lib/format";

describe("owner-readable formatting", () => {
  it("keeps hostile message text literal", () => {
    const message: ConversationMessage = {
      message_id: "message_01",
      thread_id: "thread_01",
      author_principal_id: "owner_01",
      source_client: "owner-console",
      parts: [{ kind: "text", text: '<img src=x onerror="globalThis.compromised=true">' }],
      citation_ids: [],
      delivery_state: "accepted",
      sensitivity: "personal",
      created_at: "2026-08-16T12:00:00Z",
      observed_at: "2026-08-16T12:00:00Z",
    };
    expect(messageBody(message)).toBe('<img src=x onerror="globalThis.compromised=true">');
    expect(globalThis).not.toHaveProperty("compromised");
  });

  it("projects provider-neutral turn metadata", () => {
    const inspection = {
      model_result: {
        route_id: "model.local.qwen",
        provider_id: "provider.ollama",
        model_id: "qwen3:8b",
        started_at: "2026-08-16T12:00:00.000Z",
        completed_at: "2026-08-16T12:00:01.250Z",
        external_disclosure: false,
        input_tokens: 42,
        output_tokens: 18,
        cost_gbp: 0,
        attempts: [{ processing_location: "device", outcome: "succeeded" }],
      },
    } as unknown as ConversationTurnInspection;

    expect(turnMetadata(inspection)).toMatchObject({
      routeId: "model.local.qwen",
      providerId: "provider.ollama",
      modelId: "qwen3:8b",
      location: "device",
      externalDisclosure: false,
      inputTokens: 42,
      outputTokens: 18,
      latencyMs: 1250,
    });
  });

  it("pretty prints inspectable records without interpreting them", () => {
    expect(safeJson({ value: "<script>literal</script>" })).toContain("<script>literal</script>");
  });

  it("reveals only a fixed suffix for Telegram identifiers", () => {
    expect(redactNumericIdentifier(123456789)).toBe("••••6789");
    expect(redactNumericIdentifier(-987654321)).toBe("••••4321");
    expect(redactNumericIdentifier(Number.NaN)).toBe("Invalid identifier");
  });
});
