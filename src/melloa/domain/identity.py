"""Owner and persistent-intelligence identity contracts."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from melloa.domain.base import AwareDatetime, ContractModel, NonEmptyText, RecordId


class IdentityStatus(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    RETIRED = "retired"


class OwnerIdentity(ContractModel):
    contract_version: Literal["1.0.0"] = "1.0.0"
    owner_id: RecordId
    created_at: AwareDatetime
    status: IdentityStatus = IdentityStatus.ACTIVE


class NameHistoryEntry(ContractModel):
    display_name: str = Field(min_length=1, max_length=128)
    valid_from: AwareDatetime
    valid_to: AwareDatetime | None = None
    chosen_by: RecordId

    @model_validator(mode="after")
    def validate_interval(self) -> NameHistoryEntry:
        if self.valid_to is not None and self.valid_to <= self.valid_from:
            raise ValueError("name validity must end after it starts")
        return self


class PersistentIntelligenceIdentity(ContractModel):
    contract_version: Literal["1.0.0"] = "1.0.0"
    intelligence_id: RecordId
    owner_id: RecordId
    created_at: AwareDatetime
    role: NonEmptyText
    status: IdentityStatus = IdentityStatus.ACTIVE
    naming_history: tuple[NameHistoryEntry, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def require_one_current_name(self) -> PersistentIntelligenceIdentity:
        current_names = [entry for entry in self.naming_history if entry.valid_to is None]
        if len(current_names) != 1:
            raise ValueError("exactly one current display name is required")
        return self
