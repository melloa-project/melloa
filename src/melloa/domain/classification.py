"""Shared epistemic, sensitivity, and trust classifications."""

from collections.abc import Iterable
from enum import StrEnum


class EpistemicStatus(StrEnum):
    OBSERVATION = "observation"
    INTERPRETATION = "interpretation"
    BELIEF = "belief"
    OWNER_CONFIRMED = "owner_confirmed"
    CORRECTION = "correction"


class Sensitivity(StrEnum):
    PUBLIC = "public"
    INTERNAL = "internal"
    PERSONAL = "personal"
    SENSITIVE = "sensitive"
    HIGHLY_SENSITIVE = "highly_sensitive"
    DEVICE_ONLY = "device_only"


_SENSITIVITY_ORDER = (
    Sensitivity.PUBLIC,
    Sensitivity.INTERNAL,
    Sensitivity.PERSONAL,
    Sensitivity.SENSITIVE,
    Sensitivity.HIGHLY_SENSITIVE,
    Sensitivity.DEVICE_ONLY,
)
_SENSITIVITY_RANK = {
    sensitivity: rank for rank, sensitivity in enumerate(_SENSITIVITY_ORDER)
}


def sensitivity_scope(maximum: Sensitivity) -> frozenset[Sensitivity]:
    """Return every class no more restrictive than the declared maximum."""

    return frozenset(_SENSITIVITY_ORDER[: _SENSITIVITY_RANK[maximum] + 1])


def most_restrictive_sensitivity(
    sensitivities: Iterable[Sensitivity],
) -> Sensitivity:
    """Conservatively classify derived data using its strictest input."""

    values = tuple(sensitivities)
    if not values:
        raise ValueError("at least one sensitivity is required")
    return max(values, key=_SENSITIVITY_RANK.__getitem__)


class TrustLabel(StrEnum):
    OWNER_AUTHORED = "owner_authored"
    TRUSTED_SYSTEM = "trusted_system"
    TRUSTED_CAPABILITY_METADATA = "trusted_capability_metadata"
    UNTRUSTED_EXTERNAL = "untrusted_external"
    UNTRUSTED_SENSOR_DERIVED = "untrusted_sensor_derived"
    MODEL_GENERATED = "model_generated"
    GENERATED_CODE = "generated_code"
    SIGNED_SYSTEM_ARTIFACT = "signed_system_artifact"
