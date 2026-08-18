"""Canonical active release identity shared by runtime surfaces."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal, TypedDict

PackageVersion = Literal["0.2.0"]
ReleaseDisplay = Literal["v0.2.0 preview"]
ReleaseStage = Literal["preview"]
ReleaseMilestone = Literal["M1"]
ArchitectureBaseline = Literal["v0.2"]


class PublicReleaseMetadata(TypedDict):
    version: PackageVersion
    display: ReleaseDisplay
    stage: ReleaseStage
    milestone: ReleaseMilestone
    architecture_baseline: ArchitectureBaseline


@dataclass(frozen=True, slots=True)
class ReleaseIdentity:
    package_version: PackageVersion
    release_display: ReleaseDisplay
    stage: ReleaseStage
    milestone: ReleaseMilestone
    architecture_baseline: ArchitectureBaseline

    @property
    def runtime_identifier(self) -> str:
        return f"melloa-core/{self.package_version}-{self.stage}"

    def public_metadata(self) -> PublicReleaseMetadata:
        return {
            "version": self.package_version,
            "display": self.release_display,
            "stage": self.stage,
            "milestone": self.milestone,
            "architecture_baseline": self.architecture_baseline,
        }


CURRENT_RELEASE: Final = ReleaseIdentity(
    package_version="0.2.0",
    release_display="v0.2.0 preview",
    stage="preview",
    milestone="M1",
    architecture_baseline="v0.2",
)

__all__ = [
    "CURRENT_RELEASE",
    "ArchitectureBaseline",
    "PackageVersion",
    "PublicReleaseMetadata",
    "ReleaseDisplay",
    "ReleaseIdentity",
    "ReleaseMilestone",
    "ReleaseStage",
]
