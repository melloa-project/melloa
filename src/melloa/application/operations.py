"""Authenticated owner inspection of redacted health and media metadata."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from melloa.application.inspection import InspectionOwnershipError
from melloa.domain.auth import AuthenticatedOwner
from melloa.domain.base import RecordId, utc_now
from melloa.domain.operations import (
    OwnerHealthReport,
    OwnerMediaCatalog,
    aggregate_health_state,
)
from melloa.ports.operations import OperationsInspectionReader


class OwnerOperationsService:
    def __init__(
        self,
        *,
        owner_id: RecordId,
        reader: OperationsInspectionReader,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._owner_id = owner_id
        self._reader = reader
        self._clock = clock

    def health(self, principal: AuthenticatedOwner) -> OwnerHealthReport:
        self._require_owner(principal)
        components = tuple(
            sorted(
                self._reader.component_health(),
                key=lambda component: (component.category.value, component.component_id),
            )
        )
        return OwnerHealthReport(
            owner_id=self._owner_id,
            generated_at=self._clock(),
            overall_state=aggregate_health_state(components),
            components=components,
        )

    def media(self, principal: AuthenticatedOwner) -> OwnerMediaCatalog:
        self._require_owner(principal)
        sources = tuple(
            sorted(
                self._reader.media_sources(self._owner_id),
                key=lambda source: source.capability_id,
            )
        )
        items = tuple(
            sorted(
                self._reader.media_items(self._owner_id),
                key=lambda item: (item.captured_from, item.media_id),
            )
        )
        return OwnerMediaCatalog(
            owner_id=self._owner_id,
            generated_at=self._clock(),
            capture_enabled=any(source.capture_enabled for source in sources),
            sources=sources,
            items=items,
        )

    def _require_owner(self, principal: AuthenticatedOwner) -> None:
        if principal.owner_id != self._owner_id:
            raise InspectionOwnershipError(
                "authenticated principal does not own this runtime"
            )
