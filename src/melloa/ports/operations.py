"""Ports for redacted operational health and media metadata inspection."""

from typing import Protocol

from melloa.domain.base import RecordId
from melloa.domain.operations import ComponentHealth, MediaItemMetadata, MediaSourceStatus


class OperationsInspectionReader(Protocol):
    def component_health(self) -> tuple[ComponentHealth, ...]:
        """Return non-sensitive component status records."""

    def media_sources(self, owner_id: RecordId) -> tuple[MediaSourceStatus, ...]:
        """Return owner-visible source status without capture credentials or addresses."""

    def media_items(self, owner_id: RecordId) -> tuple[MediaItemMetadata, ...]:
        """Return owner-scoped retained metadata without blob paths or content URLs."""
