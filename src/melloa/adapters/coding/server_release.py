"""Trusted external verifier and reversible server-release command adapters."""

from __future__ import annotations

import os
import stat
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Final

from melloa.domain.self_change import GitRevision
from melloa.ports.self_change import SelfChangeReleaseError

_RELEASE_ENVIRONMENT: Final = frozenset(
    {
        "DOCKER_CONFIG",
        "HOME",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "MELLOA_POSTGRES_IMAGE",
        "MELLOA_PYTHON_IMAGE",
        "MELLOA_RELEASE_HEALTH_TIMEOUT_SECONDS",
        "MELLOA_RELEASE_POLL_SECONDS",
        "MELLOA_RESTIC_IMAGE",
        "MELLOA_UV_IMAGE",
        "NO_PROXY",
    }
)
_VERIFIER_ENVIRONMENT: Final = frozenset(
    {
        "MELLOA_VERIFIER_NODE_MODULES",
        "MELLOA_VERIFIER_PYTHON_ENV",
    }
)


class ExternalSandboxSelfChangeVerifier:
    """Run a root-owned sandbox wrapper with only the candidate path as input."""

    def __init__(
        self,
        executable: Path,
        *,
        environment: Mapping[str, str] | None = None,
        timeout_seconds: int = 1_800,
        require_root_owner: bool = True,
    ) -> None:
        if not executable.is_absolute():
            raise ValueError("self-change verifier path must be absolute")
        if timeout_seconds < 1:
            raise ValueError("self-change verification timeout must be positive")
        selected_environment = dict(environment or {})
        if not set(selected_environment) <= _VERIFIER_ENVIRONMENT:
            raise ValueError("verifier environment contains an unapproved setting")
        if any(
            "\x00" in value or len(value) > 4_096
            for value in selected_environment.values()
        ):
            raise ValueError("verifier environment contains an invalid value")
        self._executable = executable
        self._environment = selected_environment
        self._timeout_seconds = timeout_seconds
        self._require_root_owner = require_root_owner

    def verify(self, checkout: Path) -> None:
        self._require_executable()
        if not checkout.is_absolute() or not checkout.is_dir() or checkout.is_symlink():
            raise SelfChangeReleaseError("self_change.candidate_checkout_unavailable")
        try:
            completed = subprocess.run(  # noqa: S603
                (str(self._executable), str(checkout)),
                cwd=checkout,
                env={"PATH": "/usr/local/bin:/usr/bin:/bin"} | self._environment,
                check=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=self._timeout_seconds,
                start_new_session=True,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise SelfChangeReleaseError("self_change.verifier_unavailable") from error
        if completed.returncode != 0:
            raise SelfChangeReleaseError("self_change.verification_failed")

    def _require_executable(self) -> None:
        try:
            metadata = self._executable.stat(follow_symlinks=False)
        except OSError as error:
            raise SelfChangeReleaseError("self_change.verifier_unavailable") from error
        if (
            not stat.S_ISREG(metadata.st_mode)
            or not os.access(self._executable, os.X_OK)
            or (self._require_root_owner and metadata.st_uid != 0)
            or metadata.st_mode & 0o022
        ):
            raise SelfChangeReleaseError("self_change.verifier_untrusted")


class ServerReleaseDeployment:
    """Invoke the protected release tool, which owns health checks and rollback."""

    def __init__(
        self,
        *,
        environment_file: Path,
        release_state_dir: Path,
        environment: Mapping[str, str] | None = None,
        timeout_seconds: int = 3_600,
    ) -> None:
        for path, label in (
            (environment_file, "server environment file"),
            (release_state_dir, "release state directory"),
        ):
            if not path.is_absolute():
                raise ValueError(f"{label} path must be absolute")
        if timeout_seconds < 1:
            raise ValueError("self-change deployment timeout must be positive")
        selected_environment = dict(environment or {})
        if not set(selected_environment) <= _RELEASE_ENVIRONMENT:
            raise ValueError("release environment contains an unapproved setting")
        if any(
            "\x00" in value or len(value) > 8_192
            for value in selected_environment.values()
        ):
            raise ValueError("release environment contains an invalid value")
        self._environment_file = environment_file
        self._release_state_dir = release_state_dir
        self._environment = selected_environment
        self._timeout_seconds = timeout_seconds

    def deploy(self, checkout: Path, revision: GitRevision) -> None:
        self._run(checkout, ("deploy", "--revision", revision))

    def rollback(self, checkout: Path) -> None:
        self._run(checkout, ("rollback",))

    def _run(self, checkout: Path, action: tuple[str, ...]) -> None:
        script = checkout / "tools/server_release.sh"
        if (
            not checkout.is_absolute()
            or not checkout.is_dir()
            or checkout.is_symlink()
            or not script.is_file()
            or script.is_symlink()
            or not os.access(script, os.X_OK)
        ):
            raise SelfChangeReleaseError("self_change.release_command_unavailable")
        environment = {"PATH": "/usr/local/bin:/usr/bin:/bin"} | self._environment
        command = (
            str(script),
            action[0],
            "--env-file",
            str(self._environment_file),
            "--state-dir",
            str(self._release_state_dir),
            *action[1:],
        )
        try:
            completed = subprocess.run(  # noqa: S603
                command,
                cwd=checkout,
                env=environment,
                check=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=self._timeout_seconds,
                start_new_session=True,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise SelfChangeReleaseError("self_change.release_command_unavailable") from error
        if completed.returncode != 0:
            reason = (
                "self_change.deployment_failed"
                if action[0] == "deploy"
                else "self_change.rollback_failed"
            )
            raise SelfChangeReleaseError(reason)


__all__ = ["ExternalSandboxSelfChangeVerifier", "ServerReleaseDeployment"]
