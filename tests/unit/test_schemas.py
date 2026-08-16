from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from melloa.domain.events import EventEnvelope


def test_event_schema_is_draft_2020_12_and_validates_contract(event: EventEnvelope) -> None:
    root = Path(__file__).resolve().parents[2]
    schema = json.loads(
        (root / "schemas/events/event-envelope-v1.json").read_text(encoding="utf-8")
    )
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(event.model_dump(mode="json"))


def test_every_committed_schema_is_structurally_valid() -> None:
    root = Path(__file__).resolve().parents[2]
    for path in sorted((root / "schemas").rglob("*.json")):
        schema = json.loads(path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
