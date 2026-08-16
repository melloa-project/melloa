"""Authenticated owner-principal contracts without identity-vendor coupling."""

from __future__ import annotations

from typing import Literal

from pydantic import model_validator

from melloa.domain.base import AwareDatetime, ContractModel, QualifiedName, RecordId


class AuthenticatedOwner(ContractModel):
    contract_version: Literal["1.0.0"] = "1.0.0"
    owner_id: RecordId
    session_id: RecordId
    authentication_method: QualifiedName
    authenticated_at: AwareDatetime
    reauthenticated_until: AwareDatetime
    expires_at: AwareDatetime

    @model_validator(mode="after")
    def validate_intervals(self) -> AuthenticatedOwner:
        if self.reauthenticated_until <= self.authenticated_at:
            raise ValueError("recent-authentication window must end after authentication")
        if self.expires_at <= self.authenticated_at:
            raise ValueError("owner session must expire after authentication")
        if self.reauthenticated_until > self.expires_at:
            raise ValueError("recent-authentication window cannot outlive the session")
        return self
