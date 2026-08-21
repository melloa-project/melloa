"""Codex CLI proposal generation in disposable clean Git worktrees."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Final, Literal
from urllib.parse import urlsplit

from melloa.domain.self_change import PlannedSelfChange, SelfChange, SelfChangeState
from melloa.ports.self_change import SelfChangePlanningError

_ALLOWED_ROOTS: Final = ("apps/web/src/", "src/melloa/", "tests/")
_PROTECTED_PATHS: Final = (
    "src/melloa/adapters/guardian/",
    "src/melloa/adapters/coding/",
    "src/melloa/adapters/postgres/",
    "src/melloa/adapters/telegram.py",
    "src/melloa/application/release_activation.py",
    "src/melloa/application/self_change.py",
    "src/melloa/application/self_change_applying.py",
    "src/melloa/application/self_change_planning.py",
    "src/melloa/apps/cli.py",
    "src/melloa/apps/core.py",
    "src/melloa/apps/owner_telegram.py",
    "src/melloa/apps/runtime.py",
    "src/melloa/domain/auth.py",
    "src/melloa/domain/guardian.py",
    "src/melloa/domain/self_change.py",
    "src/melloa/domain/telegram.py",
    "src/melloa/ports/auth.py",
    "src/melloa/ports/guardian.py",
    "src/melloa/ports/self_change.py",
    "src/melloa/ports/telegram.py",
    "src/melloa/release.py",
)
_AGENT_ENVIRONMENT: Final = frozenset(
    {
        "CODEX_HOME",
        "HOME",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "NO_PROXY",
        "OPENAI_API_KEY",
        "SSL_CERT_DIR",
        "SSL_CERT_FILE",
    }
)
_FORBIDDEN_GIT_CONFIG_PREFIXES: Final = (
    "alias.",
    "credential.",
    "diff.",
    "filter.",
    "gpg.",
    "http.",
    "https.",
    "include.",
    "includeif.",
    "interactive.",
    "merge.",
    "protocol.",
    "url.",
)
_FORBIDDEN_GIT_CONFIG_KEYS: Final = frozenset(
    {
        "commit.gpgsign",
        "core.askpass",
        "core.attributesfile",
        "core.fsmonitor",
        "core.hookspath",
        "core.sshcommand",
        "remote.origin.proxy",
        "remote.origin.pushurl",
        "remote.origin.receivepack",
        "remote.origin.uploadpack",
    }
)
_PUBLIC_GIT_ENVIRONMENT: Final = {
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_TERMINAL_PROMPT": "0",
    "HOME": "/nonexistent",
    "PATH": (
        "/opt/melloa/toolchain/bin:/usr/local/sbin:/usr/local/bin:"
        "/usr/sbin:/usr/bin:/sbin:/bin"
    ),
    "XDG_CONFIG_HOME": "/nonexistent",
}


class CodexCliSourceChangePlanner:
    """Give Codex only explicit request text and a disposable public-source checkout."""

    def __init__(
        self,
        *,
        repository: Path,
        work_root: Path,
        codex_executable: Path,
        git_executable: Path = Path("/usr/bin/git"),
        model: str | None = None,
        local_provider: Literal["ollama", "lmstudio"] | None = None,
        agent_environment: Mapping[str, str] | None = None,
        agent_uid: int | None = None,
        agent_gid: int | None = None,
        timeout_seconds: int = 1_800,
    ) -> None:
        for path, label in (
            (repository, "coding repository"),
            (work_root, "coding work root"),
            (codex_executable, "Codex executable"),
            (git_executable, "Git executable"),
        ):
            if not path.is_absolute():
                raise ValueError(f"{label} path must be absolute")
        if timeout_seconds < 1:
            raise ValueError("Codex planning timeout must be positive")
        if (agent_uid is None) != (agent_gid is None):
            raise ValueError("Codex agent UID and GID must be supplied together")
        if agent_uid is not None and (agent_uid <= 0 or agent_gid is None or agent_gid <= 0):
            raise ValueError("Codex agent UID and GID must be positive non-root IDs")
        if agent_uid is not None and os.geteuid() != 0:
            raise ValueError("a separate Codex agent identity requires a root broker")
        try:
            work_root.resolve().relative_to(repository.resolve())
        except ValueError:
            pass
        else:
            raise ValueError("coding work root must remain outside the source checkout")
        environment = dict(agent_environment or {})
        if not set(environment) <= _AGENT_ENVIRONMENT:
            raise ValueError("Codex environment contains a non-agent credential or setting")
        if any("\x00" in value or len(value) > 8_192 for value in environment.values()):
            raise ValueError("Codex environment contains an invalid value")
        self._repository = repository
        self._work_root = work_root
        self._codex_executable = codex_executable
        self._git_executable = git_executable
        self._model = model
        self._local_provider = local_provider
        self._environment = environment
        self._agent_uid = agent_uid
        self._agent_gid = agent_gid
        self._timeout_seconds = timeout_seconds

    def plan(self, change: SelfChange) -> PlannedSelfChange:
        if change.state is not SelfChangeState.PLANNING:
            raise SelfChangePlanningError("self_change.invalid_planning_claim")
        self._require_runtime_paths()
        if self._agent_uid is not None:
            self._require_public_origin()
        self._run_git(("fetch", "--quiet", "--no-tags", "origin", "main"))
        base_revision = self._run_git(("rev-parse", "refs/remotes/origin/main^{commit}"))
        revision = base_revision.stdout.decode("ascii").strip()
        if len(revision) != 40 or any(
            character not in "0123456789abcdef" for character in revision
        ):
            raise SelfChangePlanningError("self_change.base_revision_invalid")

        workspace = Path(tempfile.mkdtemp(prefix="proposal-", dir=self._work_root))
        checkout = workspace / "source"
        try:
            self._run_git(("worktree", "add", "--quiet", "--detach", str(checkout), revision))
            self._prepare_agent_workspace(workspace)
            self._run_codex(checkout, change.request_text)
            self._run_git(("-C", str(checkout), "add", "--intent-to-add", "--all"))
            changed_paths = self._changed_paths(checkout)
            validate_self_change_paths(checkout, changed_paths)
            self._run_git(("-C", str(checkout), "diff", "--check", "HEAD", "--"))
            binary = self._run_git(
                ("-C", str(checkout), "diff", "--numstat", "HEAD", "--")
            ).stdout
            if any(line.startswith(b"-\t-\t") for line in binary.splitlines()):
                raise SelfChangePlanningError("self_change.binary_change_forbidden")
            patch_result = self._run_git(
                (
                    "-C",
                    str(checkout),
                    "diff",
                    "--binary",
                    "--full-index",
                    "--no-ext-diff",
                    "HEAD",
                    "--",
                )
            )
            try:
                patch = patch_result.stdout.decode("utf-8")
            except UnicodeDecodeError as error:
                raise SelfChangePlanningError(
                    "self_change.non_utf8_change_forbidden"
                ) from error
            if not patch:
                raise SelfChangePlanningError("self_change.empty_proposal")
            if len(patch) > 60_000:
                raise SelfChangePlanningError("self_change.proposal_too_large")
            summary = f"Proposal for owner request: {change.request_text}"
            return PlannedSelfChange(
                base_revision=revision,
                summary=summary[:2_000],
                patch=patch,
            )
        finally:
            subprocess.run(  # noqa: S603
                (
                    str(self._git_executable),
                    "-C",
                    str(self._repository),
                    "worktree",
                    "remove",
                    "--force",
                    str(checkout),
                ),
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=30,
            )
            shutil.rmtree(workspace, ignore_errors=True)

    def _run_codex(self, checkout: Path, request_text: str) -> None:
        prompt = (
            "Prepare one small, production-quality implementation of the explicit owner request "
            "below. Work only in the current repository. Do not access network services, external "
            "data, credentials, deployment state, or private conversation history. Do not commit, "
            "push, or deploy. Do not modify release, authentication, Guardian, Telegram binding, "
            "self-change policy, database, migration, CI, or infrastructure code. Add or update "
            "focused tests when appropriate. Leave the complete proposed change in the "
            "worktree.\n\n"
            "EXPLICIT OWNER REQUEST\n"
            f"{request_text}\n"
            "END EXPLICIT OWNER REQUEST"
        )
        command = [
            str(self._codex_executable),
            "--ask-for-approval",
            "never",
            "exec",
            "--sandbox",
            "workspace-write",
            "--ephemeral",
            "--ignore-user-config",
            "--cd",
            str(checkout),
        ]
        if self._model is not None:
            command.extend(("--model", self._model))
        if self._local_provider is not None:
            command.extend(("--oss", "--local-provider", self._local_provider))
        command.append(prompt)
        environment = {
            "PATH": (
                "/opt/melloa/toolchain/bin:/usr/local/sbin:/usr/local/bin:"
                "/usr/sbin:/usr/bin:/sbin:/bin"
            )
        } | self._environment
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
                user=self._agent_uid,
                group=self._agent_gid,
                extra_groups=() if self._agent_uid is not None else None,
                umask=0o077,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise SelfChangePlanningError("self_change.coding_agent_unavailable") from error
        if completed.returncode != 0:
            raise SelfChangePlanningError("self_change.coding_agent_failed")

    def _prepare_agent_workspace(self, workspace: Path) -> None:
        if self._agent_uid is None or self._agent_gid is None:
            return
        for root, directories, files in os.walk(workspace, followlinks=False):
            root_path = Path(root)
            os.chown(root_path, self._agent_uid, self._agent_gid, follow_symlinks=False)
            for name in (*directories, *files):
                os.chown(
                    root_path / name,
                    self._agent_uid,
                    self._agent_gid,
                    follow_symlinks=False,
                )

    def _changed_paths(self, checkout: Path) -> tuple[str, ...]:
        result = self._run_git(
            ("-C", str(checkout), "diff", "--name-only", "-z", "HEAD", "--")
        )
        try:
            paths = tuple(
                value.decode("utf-8")
                for value in result.stdout.split(b"\0")
                if value
            )
        except UnicodeDecodeError as error:
            raise SelfChangePlanningError("self_change.invalid_changed_path") from error
        if not paths:
            raise SelfChangePlanningError("self_change.empty_proposal")
        return paths

    def _require_runtime_paths(self) -> None:
        if (
            not self._repository.is_dir()
            or self._repository.is_symlink()
            or (self._repository / ".git").is_symlink()
        ):
            raise SelfChangePlanningError("self_change.repository_unavailable")
        if not self._work_root.is_dir() or self._work_root.is_symlink():
            raise SelfChangePlanningError("self_change.work_root_unavailable")
        if not os.access(self._work_root, os.W_OK):
            raise SelfChangePlanningError("self_change.work_root_unavailable")
        for executable in (self._codex_executable, self._git_executable):
            if (
                not executable.is_file()
                or executable.is_symlink()
                or not os.access(executable, os.X_OK)
            ):
                raise SelfChangePlanningError("self_change.coding_command_unavailable")
            metadata = executable.stat(follow_symlinks=False)
            if self._agent_uid is not None and (
                metadata.st_uid != 0 or metadata.st_mode & 0o022
            ):
                raise SelfChangePlanningError("self_change.coding_command_untrusted")

    def _require_public_origin(self) -> None:
        try:
            remote = (
                self._run_git(("remote", "get-url", "origin"))
                .stdout.decode("utf-8")
                .strip()
            )
            parsed = urlsplit(remote)
        except (UnicodeDecodeError, ValueError) as error:
            raise SelfChangePlanningError("self_change.public_source_invalid") from error
        if (
            not remote
            or "\n" in remote
            or parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or not parsed.path.strip("/")
            or parsed.query
            or parsed.fragment
        ):
            raise SelfChangePlanningError("self_change.public_source_invalid")
        try:
            names = (
                self._run_git(("config", "--local", "--name-only", "--list", "-z"))
                .stdout.decode("utf-8")
                .split("\0")
            )
        except UnicodeDecodeError as error:
            raise SelfChangePlanningError("self_change.public_source_invalid") from error
        for raw_name in names:
            name = raw_name.lower()
            if name and (
                name in _FORBIDDEN_GIT_CONFIG_KEYS
                or name.startswith(_FORBIDDEN_GIT_CONFIG_PREFIXES)
            ):
                raise SelfChangePlanningError("self_change.public_source_untrusted")

    def _run_git(self, arguments: Sequence[str]) -> subprocess.CompletedProcess[bytes]:
        try:
            completed = subprocess.run(  # noqa: S603
                (
                    str(self._git_executable),
                    "-c",
                    "credential.helper=",
                    "-c",
                    "core.askPass=",
                    "-c",
                    "core.hooksPath=/dev/null",
                    "-C",
                    str(self._repository),
                    *arguments,
                ),
                env=_PUBLIC_GIT_ENVIRONMENT,
                check=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=120,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise SelfChangePlanningError("self_change.git_read_failed") from error
        if completed.returncode != 0:
            raise SelfChangePlanningError("self_change.git_read_failed")
        return completed


def validate_self_change_paths(checkout: Path, paths: Sequence[str]) -> None:
    for raw_path in paths:
        path = PurePosixPath(raw_path)
        if (
            path.is_absolute()
            or ".." in path.parts
            or "\\" in raw_path
            or not any(raw_path.startswith(root) for root in _ALLOWED_ROOTS)
            or any(
                raw_path == protected.rstrip("/") or raw_path.startswith(protected)
                for protected in _PROTECTED_PATHS
            )
        ):
            raise SelfChangePlanningError("self_change.protected_path_changed")
        filesystem_path = checkout / path
        if filesystem_path.is_symlink():
            raise SelfChangePlanningError("self_change.symlink_change_forbidden")


__all__ = ["CodexCliSourceChangePlanner", "validate_self_change_paths"]
