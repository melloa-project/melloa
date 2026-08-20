"""Exact-patch Git publication around a separately sandboxed verifier and release tool."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from collections.abc import Sequence
from pathlib import Path

from melloa.adapters.coding.codex_cli import validate_self_change_paths
from melloa.domain.self_change import (
    GitRevision,
    SelfChange,
    SelfChangeState,
    self_change_proposal_digest,
)
from melloa.ports.self_change import (
    SelfChangeCandidateVerifier,
    SelfChangeDeployment,
    SelfChangePlanningError,
    SelfChangeReleaseError,
)


class GitSelfChangeReleaseExecutor:
    """Commit and publish only the stored owner-approved diff."""

    def __init__(
        self,
        *,
        repository: Path,
        state_root: Path,
        git_executable: Path,
        verifier: SelfChangeCandidateVerifier,
        deployment: SelfChangeDeployment,
        git_timeout_seconds: int = 300,
    ) -> None:
        for path, label in (
            (repository, "release repository"),
            (state_root, "self-change state root"),
            (git_executable, "Git executable"),
        ):
            if not path.is_absolute():
                raise ValueError(f"{label} path must be absolute")
        if git_timeout_seconds < 1:
            raise ValueError("self-change Git timeout must be positive")
        try:
            state_root.resolve().relative_to(repository.resolve())
        except ValueError:
            pass
        else:
            raise ValueError("self-change state must remain outside the source checkout")
        self._repository = repository
        self._state_root = state_root
        self._git_executable = git_executable
        self._verifier = verifier
        self._deployment = deployment
        self._git_timeout_seconds = git_timeout_seconds

    def prepare_candidate(self, change: SelfChange) -> GitRevision:
        self._validate_approved_change(change)
        self._require_runtime_paths()
        self._fetch_main()
        checkout = self._checkout_path(change)
        if checkout.exists():
            self._require_checkout(checkout)
            head = self._revision(checkout, "HEAD")
            if change.candidate_revision is None:
                if head == change.base_revision:
                    self._remove_checkout(checkout)
                else:
                    self._verify_candidate(change, checkout, head)
                    return head
            else:
                self._verify_candidate(change, checkout, change.candidate_revision)
                return change.candidate_revision
        if change.candidate_revision is not None:
            self._ensure_candidate_object(change)
            self._add_checkout(checkout, change.candidate_revision)
            self._verify_candidate(change, checkout, change.candidate_revision)
            return change.candidate_revision

        remote_main = self._remote_main()
        if remote_main != change.base_revision:
            raise SelfChangeReleaseError("self_change.base_revision_changed")
        self._add_checkout(checkout, change.base_revision)
        try:
            self._apply_exact_patch(change, checkout)
            self._verifier.verify(checkout)
            self._verify_uncommitted_patch(change, checkout)
            self._run_git(
                (
                    "-C",
                    str(checkout),
                    "-c",
                    "core.hooksPath=/dev/null",
                    "-c",
                    "commit.gpgsign=false",
                    "-c",
                    "user.name=Melloa Self-Change",
                    "-c",
                    "user.email=self-change@melloa.invalid",
                    "commit",
                    "--quiet",
                    "-m",
                    f"Apply owner-approved change {change.change_id}",
                    "-m",
                    f"Melloa-Proposal-Digest: {change.proposal_digest}",
                )
            )
            candidate = self._revision(checkout, "HEAD")
            self._verify_candidate(change, checkout, candidate)
            return candidate
        except SelfChangeReleaseError:
            raise
        except Exception as error:
            raise SelfChangeReleaseError("self_change.candidate_preparation_failed") from error

    def release_candidate(self, change: SelfChange) -> None:
        self._validate_approved_change(change)
        if change.candidate_revision is None:
            raise SelfChangeReleaseError("self_change.candidate_missing")
        self._require_runtime_paths()
        checkout = self._checkout_path(change)
        self._require_checkout(checkout)
        self._verify_candidate(change, checkout, change.candidate_revision)
        candidate_ref = self._candidate_ref(change)
        remote_candidate = self._remote_ref(candidate_ref)
        if remote_candidate is None:
            self._push(f"{change.candidate_revision}:{candidate_ref}")
        elif remote_candidate != change.candidate_revision:
            raise SelfChangeReleaseError("self_change.candidate_ref_conflict")

        self._deployment.deploy(checkout, change.candidate_revision)
        self._fetch_main()
        remote_main = self._remote_main()
        if remote_main == change.candidate_revision:
            return
        if remote_main != change.base_revision:
            self._rollback_after_publication_failure(checkout)
            raise SelfChangeReleaseError("self_change.main_changed_before_publication")
        try:
            self._push(f"{change.candidate_revision}:refs/heads/main")
        except SelfChangeReleaseError:
            self._rollback_after_publication_failure(checkout)
            raise
        if self._remote_main() != change.candidate_revision:
            self._rollback_after_publication_failure(checkout)
            raise SelfChangeReleaseError("self_change.main_publication_unverified")

    def _apply_exact_patch(self, change: SelfChange, checkout: Path) -> None:
        if change.proposal_patch is None:
            raise SelfChangeReleaseError("self_change.proposal_missing")
        self._run_git(
            (
                "-C",
                str(checkout),
                "apply",
                "--index",
                "--whitespace=error",
                "-",
            ),
            input_bytes=change.proposal_patch.encode("utf-8"),
        )
        self._verify_uncommitted_patch(change, checkout)

    def _verify_uncommitted_patch(self, change: SelfChange, checkout: Path) -> None:
        paths = self._changed_paths(checkout, "HEAD")
        self._validate_changed_paths(checkout, paths)
        patch = self._run_git(
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
        ).stdout
        if change.proposal_patch is None or patch != change.proposal_patch.encode("utf-8"):
            raise SelfChangeReleaseError("self_change.approved_patch_changed")
        untracked = self._run_git(
            (
                "-C",
                str(checkout),
                "ls-files",
                "--others",
                "--exclude-standard",
                "-z",
            )
        ).stdout
        if untracked:
            raise SelfChangeReleaseError("self_change.unapproved_file_created")

    def _verify_candidate(
        self,
        change: SelfChange,
        checkout: Path,
        candidate_revision: GitRevision,
    ) -> None:
        if self._revision(checkout, "HEAD") != candidate_revision:
            raise SelfChangeReleaseError("self_change.candidate_checkout_changed")
        if self._revision(checkout, f"{candidate_revision}^") != change.base_revision:
            raise SelfChangeReleaseError("self_change.candidate_parent_changed")
        paths = self._changed_paths(
            checkout,
            change.base_revision or "",
            candidate_revision,
        )
        self._validate_changed_paths(checkout, paths)
        patch = self._run_git(
            (
                "-C",
                str(checkout),
                "diff",
                "--binary",
                "--full-index",
                "--no-ext-diff",
                change.base_revision or "",
                candidate_revision,
                "--",
            )
        ).stdout
        if change.proposal_patch is None or patch != change.proposal_patch.encode("utf-8"):
            raise SelfChangeReleaseError("self_change.candidate_diff_changed")
        message = self._run_git(
            ("-C", str(checkout), "show", "-s", "--format=%B", candidate_revision)
        ).stdout.decode("utf-8", errors="replace")
        if f"Melloa-Proposal-Digest: {change.proposal_digest}" not in message.splitlines():
            raise SelfChangeReleaseError("self_change.candidate_approval_missing")
        if self._run_git(("-C", str(checkout), "status", "--porcelain")).stdout:
            raise SelfChangeReleaseError("self_change.candidate_checkout_dirty")

    @staticmethod
    def _validate_approved_change(change: SelfChange) -> None:
        if change.state is not SelfChangeState.APPLYING:
            raise SelfChangeReleaseError("self_change.invalid_application_claim")
        if (
            change.base_revision is None
            or change.proposal_summary is None
            or change.proposal_patch is None
            or change.proposal_digest is None
            or change.approved_digest != change.proposal_digest
            or change.proposal_digest
            != self_change_proposal_digest(
                base_revision=change.base_revision,
                summary=change.proposal_summary,
                patch=change.proposal_patch,
            )
        ):
            raise SelfChangeReleaseError("self_change.approval_evidence_invalid")

    def _ensure_candidate_object(self, change: SelfChange) -> None:
        if change.candidate_revision is None:
            return
        exists = self._run_git(
            ("cat-file", "-e", f"{change.candidate_revision}^{{commit}}"),
            check=False,
        )
        if exists.returncode == 0:
            return
        candidate_ref = self._candidate_ref(change)
        self._run_git(("fetch", "--quiet", "--no-tags", "origin", candidate_ref))
        if self._revision(self._repository, "FETCH_HEAD") != change.candidate_revision:
            raise SelfChangeReleaseError("self_change.candidate_commit_unavailable")

    @staticmethod
    def _validate_changed_paths(checkout: Path, paths: Sequence[str]) -> None:
        try:
            validate_self_change_paths(checkout, paths)
        except SelfChangePlanningError as error:
            raise SelfChangeReleaseError(error.reason_code) from error

    def _changed_paths(self, checkout: Path, *revisions: str) -> tuple[str, ...]:
        raw = self._run_git(
            ("-C", str(checkout), "diff", "--name-only", "-z", *revisions, "--")
        ).stdout
        try:
            return tuple(value.decode("utf-8") for value in raw.split(b"\0") if value)
        except UnicodeDecodeError as error:
            raise SelfChangeReleaseError("self_change.invalid_changed_path") from error

    def _fetch_main(self) -> None:
        self._run_git(("fetch", "--quiet", "--no-tags", "origin", "main"))

    def _remote_main(self) -> str:
        revision = self._remote_ref("refs/heads/main")
        if revision is None:
            raise SelfChangeReleaseError("self_change.remote_main_unavailable")
        return revision

    def _remote_ref(self, reference: str) -> str | None:
        result = self._run_git(("ls-remote", "--refs", "origin", reference))
        output = result.stdout.decode("ascii").strip()
        if not output:
            return None
        lines = output.splitlines()
        if len(lines) != 1:
            raise SelfChangeReleaseError("self_change.remote_ref_ambiguous")
        revision, returned_ref = lines[0].split("\t", maxsplit=1)
        if returned_ref != reference or len(revision) != 40:
            raise SelfChangeReleaseError("self_change.remote_ref_invalid")
        return revision

    def _push(self, refspec: str) -> None:
        result = self._run_git(
            (
                "-c",
                "core.hooksPath=/dev/null",
                "push",
                "--porcelain",
                "origin",
                refspec,
            ),
            check=False,
        )
        if result.returncode != 0:
            raise SelfChangeReleaseError("self_change.git_push_failed")

    def _rollback_after_publication_failure(self, checkout: Path) -> None:
        try:
            self._deployment.rollback(checkout)
        except Exception as error:
            raise SelfChangeReleaseError("self_change.publication_rollback_failed") from error

    def _add_checkout(self, checkout: Path, revision: str) -> None:
        self._run_git(("worktree", "add", "--quiet", "--detach", str(checkout), revision))

    def _remove_checkout(self, checkout: Path) -> None:
        self._run_git(("worktree", "remove", "--force", str(checkout)))
        shutil.rmtree(checkout, ignore_errors=True)

    def _require_checkout(self, checkout: Path) -> None:
        if not checkout.is_dir() or checkout.is_symlink():
            raise SelfChangeReleaseError("self_change.candidate_checkout_unavailable")

    def _revision(self, checkout: Path, revision: str) -> str:
        value = self._run_git(("-C", str(checkout), "rev-parse", f"{revision}^{{commit}}"))
        parsed = value.stdout.decode("ascii").strip()
        if len(parsed) != 40 or any(character not in "0123456789abcdef" for character in parsed):
            raise SelfChangeReleaseError("self_change.git_revision_invalid")
        return parsed

    def _checkout_path(self, change: SelfChange) -> Path:
        return self._state_root / change.change_id

    @staticmethod
    def _candidate_ref(change: SelfChange) -> str:
        return f"refs/heads/melloa-candidates/{change.change_id}"

    def _require_runtime_paths(self) -> None:
        try:
            git_metadata = self._git_executable.stat(follow_symlinks=False)
        except OSError as error:
            raise SelfChangeReleaseError("self_change.release_workspace_unavailable") from error
        if (
            not self._repository.is_dir()
            or self._repository.is_symlink()
            or (self._repository / ".git").is_symlink()
            or not self._state_root.is_dir()
            or self._state_root.is_symlink()
            or not os.access(self._state_root, os.W_OK)
            or not stat.S_ISREG(git_metadata.st_mode)
            or git_metadata.st_uid != 0
            or git_metadata.st_mode & 0o022
            or not os.access(self._git_executable, os.X_OK)
        ):
            raise SelfChangeReleaseError("self_change.release_workspace_unavailable")

    def _run_git(
        self,
        arguments: Sequence[str],
        *,
        input_bytes: bytes | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[bytes]:
        try:
            result = subprocess.run(  # noqa: S603
                (str(self._git_executable), "-C", str(self._repository), *arguments),
                input=input_bytes or b"",
                env=os.environ | {"GIT_TERMINAL_PROMPT": "0"},
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=self._git_timeout_seconds,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise SelfChangeReleaseError("self_change.git_operation_failed") from error
        if check and result.returncode != 0:
            raise SelfChangeReleaseError("self_change.git_operation_failed")
        return result


__all__ = ["GitSelfChangeReleaseExecutor"]
