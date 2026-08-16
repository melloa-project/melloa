"""Owner-scoped retention policy and inventory inspection."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from melloa.domain.auth import AuthenticatedOwner
from melloa.domain.base import RecordId, utc_now
from melloa.domain.retention import OwnerRetentionReport
from melloa.ports.retention import OwnerRetentionReader


class RetentionOwnershipError(PermissionError):
    """The authenticated principal does not own the retention report."""


class RetentionInspectionUnavailableError(RuntimeError):
    """Retention inspection is configured without a complete report boundary."""


class OwnerRetentionService:
    def __init__(
        self,
        *,
        owner_id: RecordId,
        reader: OwnerRetentionReader,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._owner_id = owner_id
        self._reader = reader
        self._clock = clock

    def report(self, principal: AuthenticatedOwner) -> OwnerRetentionReport:
        if principal.owner_id != self._owner_id:
            raise RetentionOwnershipError(
                "authenticated principal does not own this retention report"
            )
        policies = tuple(
            sorted(
                self._reader.policies(self._owner_id),
                key=lambda policy: policy.policy_id,
            )
        )
        inventory = tuple(
            sorted(
                self._reader.inventory(self._owner_id),
                key=lambda item: item.policy_id,
            )
        )
        backup_expiry = self._reader.backup_expiry(self._owner_id)
        if not policies or not inventory or backup_expiry is None:
            raise RetentionInspectionUnavailableError(
                "retention report source is incomplete"
            )
        return OwnerRetentionReport(
            owner_id=self._owner_id,
            generated_at=self._clock(),
            policies=policies,
            inventory=inventory,
            backup_expiry=backup_expiry,
        )
