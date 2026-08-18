"""Owner-visible release and Guardian status assembled through read-only ports."""

from __future__ import annotations

from typing import Literal

from melloa.domain.base import AwareDatetime, ContractModel, Sha256Digest, utc_now
from melloa.domain.guardian import GuardianMode
from melloa.ports.guardian import GuardianStatusReader
from melloa.release import (
    CURRENT_RELEASE,
    ArchitectureBaseline,
    PackageVersion,
    ReleaseDisplay,
    ReleaseMilestone,
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
    milestone: ReleaseMilestone = CURRENT_RELEASE.milestone
    architecture_baseline: ArchitectureBaseline = CURRENT_RELEASE.architecture_baseline
    generated_at: AwareDatetime
    guardian: GuardianSummary
    public_ingress: Literal[False] = False
    external_actions_enabled: bool


def read_system_status(reader: GuardianStatusReader) -> SystemStatus:
    status = reader.read_status()
    return SystemStatus(
        generated_at=utc_now(),
        guardian=GuardianSummary(
            mode=status.payload.mode,
            sequence=status.payload.sequence,
            changed_at=status.payload.changed_at,
            receipt_hash=status.receipt_hash,
            key_id=status.key_id,
        ),
        external_actions_enabled=status.payload.mode is GuardianMode.NORMAL,
    )
