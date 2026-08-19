import { describe, expect, it } from "vitest";

import type { ConversationMessage, ConversationTurnInspection } from "../src/api";
import { messageBody, turnMetadata } from "../src/lib/format";

describe("owner-readable formatting", () => {
  it("keeps hostile message text literal", () => {
    const message: ConversationMessage = {
      message_id: "message_01",
      thread_id: "thread_01",
      author_principal_id: "owner_01",
      source_client: "owner-console",
      parts: [{ kind: "text", text: '<img src=x onerror="globalThis.compromised=true">' }],
      citation_ids: [],
      sensitivity: "personal",
      created_at: "2026-08-16T12:00:00Z",
      observed_at: "2026-08-16T12:00:00Z",
    };
    expect(messageBody(message)).toBe('<img src=x onerror="globalThis.compromised=true">');
    expect(globalThis).not.toHaveProperty("compromised");
  });

  it("projects the few model facts useful in answer context", () => {
    const inspection = {
      model_result: {
        provider_id: "provider.ollama",
        model_id: "qwen3:8b",
        processing_location: "device",
        started_at: "2026-08-16T12:00:00.000Z",
        completed_at: "2026-08-16T12:00:01.250Z",
        external_disclosure: false,
        input_tokens: 42,
        output_tokens: 18,
        cost_gbp: 0,
      },
    } as unknown as ConversationTurnInspection;

    expect(turnMetadata(inspection)).toMatchObject({
      modelId: "qwen3:8b",
      location: "device",
      externalDisclosure: false,
      latencyMs: 1250,
    });
  });
});
