"""Isolated coding-agent adapters for reviewable source proposals."""

from melloa.adapters.coding.codex_cli import CodexCliSourceChangePlanner
from melloa.adapters.coding.git_release import GitSelfChangeReleaseExecutor
from melloa.adapters.coding.server_release import (
    ExternalSandboxSelfChangeVerifier,
    ServerReleaseDeployment,
)

__all__ = [
    "CodexCliSourceChangePlanner",
    "ExternalSandboxSelfChangeVerifier",
    "GitSelfChangeReleaseExecutor",
    "ServerReleaseDeployment",
]
