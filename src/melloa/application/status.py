"""Owner-visible release and Guardian status assembled through read-only ports."""

from __future__ import annotations

from typing import Literal

from melloa.domain.base import AwareDatetime, ContractModel, Sha256Digest, utc_now
from melloa.domain.guardian import GuardianMode
from melloa.ports.guardian import GuardianStatusReader
from melloa.release import (
    CURRENT_RELEASE,
    PackageVersion,
    ReleaseDisplay,
    ReleaseStage,
)


class GuardianSummary(ContractModel):
    mode: GuardianMode
    sequence: int
    changed_at: AwareDatetime
    receipt_hash: Sha256Digest
    key_id: str


class SystemStatus(ContractModel):
    contract_version: Literal["1.0.0"] = "1.0.0"
    service: Literal["melloa-core"] = "melloa-core"
    version: PackageVersion = CURRENT_RELEASE.package_version
    release_display: ReleaseDisplay = CURRENT_RELEASE.release_display
    stage: ReleaseStage = CURRENT_RELEASE.stage
    generated_at: AwareDatetime
    guardian: GuardianSummary
    access_scope: Literal["loopback", "private-network", "unverified"]
    public_ingress: bool | None
    external_actions_enabled: bool


def read_system_status(
    reader: GuardianStatusReader,
    *,
    access_scope: Literal["loopback", "private-network", "unverified"] = "unverified",
) -> SystemStatus:
    status = reader.read_status()
    return SystemStatus(
        generated_at=utc_now(),
        access_scope=access_scope,
        public_ingress=False if access_scope == "loopback" else None,
        guardian=GuardianSummary(
            mode=status.payload.mode,
            sequence=status.payload.sequence,
            changed_at=status.payload.changed_at,
            receipt_hash=status.receipt_hash,
            key_id=status.key_id,
        ),
        external_actions_enabled=status.payload.mode is GuardianMode.NORMAL,
    )
