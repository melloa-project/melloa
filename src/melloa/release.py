"""Canonical active release identity shared by runtime surfaces."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal, TypedDict

PackageVersion = Literal["0.2.0"]
ReleaseDisplay = Literal["v0.2.0 preview"]
ReleaseStage = Literal["preview"]


class PublicReleaseMetadata(TypedDict):
    version: PackageVersion
    display: ReleaseDisplay
    stage: ReleaseStage


@dataclass(frozen=True, slots=True)
class ReleaseIdentity:
    package_version: PackageVersion
    release_display: ReleaseDisplay
    stage: ReleaseStage

    @property
    def runtime_identifier(self) -> str:
        return f"melloa-core/{self.package_version}-{self.stage}"

    def public_metadata(self) -> PublicReleaseMetadata:
        return {
            "version": self.package_version,
            "display": self.release_display,
            "stage": self.stage,
        }


CURRENT_RELEASE: Final = ReleaseIdentity(
    package_version="0.2.0",
    release_display="v0.2.0 preview",
    stage="preview",
)

__all__ = [
    "CURRENT_RELEASE",
    "PackageVersion",
    "PublicReleaseMetadata",
    "ReleaseDisplay",
    "ReleaseIdentity",
    "ReleaseStage",
]
