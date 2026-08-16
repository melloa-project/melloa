"""Process-local redacted health and media metadata for synthetic acceptance runs."""

from __future__ import annotations

from collections.abc import Callable

from melloa.domain.base import RecordId
from melloa.domain.operations import ComponentHealth, MediaItemMetadata, MediaSourceStatus


class InMemoryOperationsReader:
    def __init__(
        self,
        owner_id: RecordId,
        *,
        components: tuple[ComponentHealth, ...],
        component_readers: tuple[Callable[[], ComponentHealth], ...] = (),
        media_sources: tuple[MediaSourceStatus, ...] = (),
        media_items: tuple[MediaItemMetadata, ...] = (),
    ) -> None:
        if any(item.owner_id != owner_id for item in media_items):
            raise ValueError("synthetic media reader cannot contain another owner's records")
        self._owner_id = owner_id
        self._components = tuple(
            sorted(
                components,
                key=lambda component: (component.category.value, component.component_id),
            )
        )
        self._component_readers = component_readers
        self._media_sources = tuple(
            sorted(media_sources, key=lambda source: source.capability_id)
        )
        self._media_items = tuple(
            sorted(media_items, key=lambda item: (item.captured_from, item.media_id))
        )

    def component_health(self) -> tuple[ComponentHealth, ...]:
        components = self._components + tuple(reader() for reader in self._component_readers)
        component_ids = tuple(component.component_id for component in components)
        if len(set(component_ids)) != len(component_ids):
            raise ValueError("synthetic health component IDs must be unique")
        return tuple(
            sorted(
                components,
                key=lambda component: (component.category.value, component.component_id),
            )
        )

    def media_sources(self, owner_id: RecordId) -> tuple[MediaSourceStatus, ...]:
        return self._media_sources if owner_id == self._owner_id else ()

    def media_items(self, owner_id: RecordId) -> tuple[MediaItemMetadata, ...]:
        return self._media_items if owner_id == self._owner_id else ()
