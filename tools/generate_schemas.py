#!/usr/bin/env python3
"""Generate committed JSON Schema contracts from strict Pydantic domain models."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from melloa.domain.audit import AuditRecord
from melloa.domain.auth import AuthenticatedOwner
from melloa.domain.conversation import (
    ConversationMessage,
    ConversationProcessingAttempt,
    ConversationProcessingResumption,
    ConversationProcessingStatus,
    ConversationReplyWork,
    ConversationThread,
    ConversationTurn,
    ConversationTurnInspection,
    DeliveryAttempt,
)
from melloa.domain.delivery import (
    AuthorizedClientDelivery,
    DeliveryExecutionReceipt,
    DeliveryWorkAttempt,
    DeliveryWorkResumption,
    DeliveryWorkStatus,
    OutboundDeliveryWork,
)
from melloa.domain.events import EventEnvelope
from melloa.domain.guardian import GuardianStatusPayload, SignedGuardianStatus
from melloa.domain.identity import OwnerIdentity, PersistentIntelligenceIdentity
from melloa.domain.inspection import OwnerModelActivityReport
from melloa.domain.memory import (
    Assertion,
    AssertionCorrectionResult,
    AssertionStateChange,
    AssertionStateProjection,
    AssertionStateTransitionResult,
    MemoryInspection,
    ProvenanceEdge,
)
from melloa.domain.models import (
    ConversationModelOutput,
    ModelResult,
    ModelRouteRequest,
    RegisteredModelRoute,
)
from melloa.domain.operations import OwnerHealthReport, OwnerMediaCatalog
from melloa.domain.policy import AuthorizationRequest, PolicyDecision
from melloa.domain.retrieval import MemoryCitation, RetrievalManifest
from melloa.domain.telegram import (
    TelegramAttachmentReceipt,
    TelegramInboundUpdate,
    TelegramIngestionReceipt,
    TelegramOwnerPairing,
    TelegramPairingCandidate,
    TelegramPollRequest,
    TelegramPollState,
)

ROOT = Path(__file__).resolve().parents[1]
REGISTRY: dict[str, tuple[str, type[BaseModel]]] = {
    "actions/authorization-request-v1.json": ("authorization-request", AuthorizationRequest),
    "actions/policy-decision-v1.json": ("policy-decision", PolicyDecision),
    "auth/authenticated-owner-v1.json": ("authenticated-owner", AuthenticatedOwner),
    "audit/audit-record-v1.json": ("audit-record", AuditRecord),
    "conversation/delivery-attempt-v1.json": ("delivery-attempt", DeliveryAttempt),
    "conversation/authorized-delivery-v1.json": (
        "authorized-client-delivery",
        AuthorizedClientDelivery,
    ),
    "conversation/delivery-execution-receipt-v1.json": (
        "delivery-execution-receipt",
        DeliveryExecutionReceipt,
    ),
    "conversation/delivery-work-attempt-v1.json": (
        "delivery-work-attempt",
        DeliveryWorkAttempt,
    ),
    "conversation/delivery-work-resumption-v1.json": (
        "delivery-work-resumption",
        DeliveryWorkResumption,
    ),
    "conversation/delivery-work-status-v1.json": (
        "delivery-work-status",
        DeliveryWorkStatus,
    ),
    "conversation/message-v1.json": ("conversation-message", ConversationMessage),
    "conversation/outbound-delivery-work-v1.json": (
        "outbound-delivery-work",
        OutboundDeliveryWork,
    ),
    "conversation/processing-attempt-v1.json": (
        "conversation-processing-attempt",
        ConversationProcessingAttempt,
    ),
    "conversation/processing-resumption-v1.json": (
        "conversation-processing-resumption",
        ConversationProcessingResumption,
    ),
    "conversation/processing-status-v1.json": (
        "conversation-processing-status",
        ConversationProcessingStatus,
    ),
    "conversation/reply-work-v1.json": ("conversation-reply-work", ConversationReplyWork),
    "conversation/thread-v1.json": ("conversation-thread", ConversationThread),
    "conversation/turn-v1.json": ("conversation-turn", ConversationTurn),
    "conversation/turn-inspection-v1.json": (
        "conversation-turn-inspection",
        ConversationTurnInspection,
    ),
    "events/event-envelope-v1.json": ("event-envelope", EventEnvelope),
    "guardian/signed-status-v1.json": ("guardian-signed-status", SignedGuardianStatus),
    "guardian/status-payload-v1.json": ("guardian-status-payload", GuardianStatusPayload),
    "identity/owner-v1.json": ("owner-identity", OwnerIdentity),
    "identity/persistent-intelligence-v1.json": (
        "persistent-intelligence",
        PersistentIntelligenceIdentity,
    ),
    "inspection/owner-model-activity-v1.json": (
        "owner-model-activity",
        OwnerModelActivityReport,
    ),
    "inspection/owner-health-v1.json": ("owner-health", OwnerHealthReport),
    "inspection/owner-media-catalog-v1.json": (
        "owner-media-catalog",
        OwnerMediaCatalog,
    ),
    "memory/assertion-v1.json": ("assertion", Assertion),
    "memory/assertion-correction-result-v1.json": (
        "assertion-correction-result",
        AssertionCorrectionResult,
    ),
    "memory/assertion-state-change-v1.json": (
        "assertion-state-change",
        AssertionStateChange,
    ),
    "memory/assertion-state-v1.json": ("assertion-state", AssertionStateProjection),
    "memory/assertion-state-transition-result-v1.json": (
        "assertion-state-transition-result",
        AssertionStateTransitionResult,
    ),
    "memory/inspection-v1.json": ("memory-inspection", MemoryInspection),
    "memory/provenance-edge-v1.json": ("provenance-edge", ProvenanceEdge),
    "models/route-request-v1.json": ("model-route-request", ModelRouteRequest),
    "models/result-v1.json": ("model-result", ModelResult),
    "models/registered-route-v1.json": ("registered-model-route", RegisteredModelRoute),
    "retrieval/citation-v1.json": ("memory-citation", MemoryCitation),
    "retrieval/manifest-v1.json": ("retrieval-manifest", RetrievalManifest),
    "telegram/attachment-receipt-v1.json": (
        "telegram-attachment-receipt",
        TelegramAttachmentReceipt,
    ),
    "telegram/inbound-update-v1.json": (
        "telegram-inbound-update",
        TelegramInboundUpdate,
    ),
    "telegram/ingestion-receipt-v1.json": (
        "telegram-ingestion-receipt",
        TelegramIngestionReceipt,
    ),
    "telegram/owner-pairing-v1.json": (
        "telegram-owner-pairing",
        TelegramOwnerPairing,
    ),
    "telegram/pairing-candidate-v1.json": (
        "telegram-pairing-candidate",
        TelegramPairingCandidate,
    ),
    "telegram/poll-request-v1.json": ("telegram-poll-request", TelegramPollRequest),
    "telegram/poll-state-v1.json": ("telegram-poll-state", TelegramPollState),
    "models/conversation-output-v1.json": (
        "conversation-model-output",
        ConversationModelOutput,
    ),
}


def schema_document(name: str, model: type[BaseModel]) -> dict[str, Any]:
    schema = model.model_json_schema(mode="serialization")
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = f"https://schemas.melloa.dev/v1/{name}.json"
    return schema


def encoded_schema(name: str, model: type[BaseModel]) -> str:
    return json.dumps(schema_document(name, model), indent=2, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    mismatches: list[str] = []

    for relative_path, (name, model) in REGISTRY.items():
        path = ROOT / "schemas" / relative_path
        expected = encoded_schema(name, model)
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != expected:
                mismatches.append(relative_path)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(expected, encoding="utf-8")

    if mismatches:
        print("Generated schemas are stale:")
        for mismatch in mismatches:
            print(f"- {mismatch}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
