"""Process-local owner-scoped retention policy and inventory inspection."""

from __future__ import annotations

from melloa.domain.base import RecordId
from melloa.domain.retention import (
    BackupExpiryDisclosure,
    RetentionInventoryCoverage,
    RetentionInventoryStatus,
    RetentionPolicyStatus,
)
from melloa.ports.conversation import ConversationStore
from melloa.ports.memory import MemoryRepository
from melloa.ports.retention import OwnerRetentionReader


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


class MemoryBackedRetentionReader:
    def __init__(
        self,
        base_reader: OwnerRetentionReader,
        memory_repository: MemoryRepository,
        *,
        memory_policy_id: str = "retention.owner-memory",
    ) -> None:
        self._base_reader = base_reader
        self._memory_repository = memory_repository
        self._memory_policy_id = memory_policy_id

    def policies(self, owner_id: RecordId) -> tuple[RetentionPolicyStatus, ...]:
        return self._base_reader.policies(owner_id)

    def inventory(self, owner_id: RecordId) -> tuple[RetentionInventoryStatus, ...]:
        inventory = self._base_reader.inventory(owner_id)
        if not inventory:
            return inventory
        memory_inventory = self._memory_repository.assertion_content_retention_inventory(
            owner_id
        )
        memory_item = RetentionInventoryStatus(
            policy_id=self._memory_policy_id,
            coverage=RetentionInventoryCoverage.COMPLETE,
            retained_objects=memory_inventory.retained_objects,
            retained_bytes=memory_inventory.retained_bytes,
            overdue_objects=0,
            pending_deletions=0,
            deletion_receipts=memory_inventory.deletion_receipts,
            oldest_retained_at=memory_inventory.oldest_retained_at,
            status_reason="retention.inventory.canonical_memory",
        )
        return tuple(
            memory_item if item.policy_id == self._memory_policy_id else item
            for item in inventory
        )

    def backup_expiry(self, owner_id: RecordId) -> BackupExpiryDisclosure | None:
        return self._base_reader.backup_expiry(owner_id)


class ConversationBackedRetentionReader:
    def __init__(
        self,
        base_reader: OwnerRetentionReader,
        conversation_store: ConversationStore,
        *,
        conversation_policy_id: str = "retention.owner-conversation",
    ) -> None:
        self._base_reader = base_reader
        self._conversation_store = conversation_store
        self._conversation_policy_id = conversation_policy_id

    def policies(self, owner_id: RecordId) -> tuple[RetentionPolicyStatus, ...]:
        return self._base_reader.policies(owner_id)

    def inventory(self, owner_id: RecordId) -> tuple[RetentionInventoryStatus, ...]:
        inventory = self._base_reader.inventory(owner_id)
        if not inventory:
            return inventory
        conversation_inventory = self._conversation_store.retention_inventory(owner_id)
        conversation_item = RetentionInventoryStatus(
            policy_id=self._conversation_policy_id,
            coverage=RetentionInventoryCoverage.COMPLETE,
            retained_objects=conversation_inventory.retained_objects,
            retained_bytes=conversation_inventory.retained_bytes,
            overdue_objects=0,
            pending_deletions=0,
            deletion_receipts=0,
            oldest_retained_at=conversation_inventory.oldest_retained_at,
            status_reason="retention.inventory.canonical_conversation",
        )
        return tuple(
            conversation_item if item.policy_id == self._conversation_policy_id else item
            for item in inventory
        )

    def backup_expiry(self, owner_id: RecordId) -> BackupExpiryDisclosure | None:
        return self._base_reader.backup_expiry(owner_id)
