"""Ports for owner-visible retention policy and inventory inspection."""

from typing import Protocol

from melloa.domain.base import RecordId
from melloa.domain.retention import (
    BackupExpiryDisclosure,
    RetentionInventoryStatus,
    RetentionPolicyStatus,
)


class OwnerRetentionReader(Protocol):
    def policies(self, owner_id: RecordId) -> tuple[RetentionPolicyStatus, ...]:
        """Return the configured retention policies visible to one owner."""

    def inventory(self, owner_id: RecordId) -> tuple[RetentionInventoryStatus, ...]:
        """Return redacted coverage and aggregate inventory for one owner."""

    def backup_expiry(self, owner_id: RecordId) -> BackupExpiryDisclosure | None:
        """Return the honest backup deletion horizon, or no foreign-owner record."""
