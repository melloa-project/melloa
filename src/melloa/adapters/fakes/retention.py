"""Process-local owner-scoped retention policy and inventory inspection."""

from __future__ import annotations

from melloa.domain.base import RecordId
from melloa.domain.retention import (
    BackupExpiryDisclosure,
    RetentionInventoryStatus,
    RetentionPolicyStatus,
)


class InMemoryRetentionReader:
    def __init__(
        self,
        owner_id: RecordId,
        *,
        policies: tuple[RetentionPolicyStatus, ...],
        inventory: tuple[RetentionInventoryStatus, ...],
        backup_expiry: BackupExpiryDisclosure,
    ) -> None:
        policy_ids = tuple(policy.policy_id for policy in policies)
        inventory_ids = tuple(item.policy_id for item in inventory)
        if not policies or len(set(policy_ids)) != len(policy_ids):
            raise ValueError("synthetic retention policies must be non-empty and unique")
        if set(inventory_ids) != set(policy_ids) or len(inventory_ids) != len(policy_ids):
            raise ValueError("synthetic retention inventory must cover every policy once")
        self._owner_id = owner_id
        self._policies = tuple(sorted(policies, key=lambda policy: policy.policy_id))
        self._inventory = tuple(sorted(inventory, key=lambda item: item.policy_id))
        self._backup_expiry = backup_expiry

    def policies(self, owner_id: RecordId) -> tuple[RetentionPolicyStatus, ...]:
        return self._policies if owner_id == self._owner_id else ()

    def inventory(self, owner_id: RecordId) -> tuple[RetentionInventoryStatus, ...]:
        return self._inventory if owner_id == self._owner_id else ()

    def backup_expiry(self, owner_id: RecordId) -> BackupExpiryDisclosure | None:
        return self._backup_expiry if owner_id == self._owner_id else None
