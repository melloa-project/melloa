from __future__ import annotations

import shutil
import subprocess
from datetime import timedelta
from pathlib import Path
from unittest.mock import Mock

import pytest

from melloa.adapters.coding.git_release import GitSelfChangeReleaseExecutor
from melloa.application.self_change_applying import SelfChangeApplyingWorker
from melloa.domain.self_change import (
    SelfChange,
    SelfChangeState,
    self_change_proposal_digest,
    self_change_request_digest,
)
from melloa.ports.self_change import SelfChangeReleaseError
from tests.conftest import record_id


class _Verifier:
    def __init__(self, *, mutate: bool = False) -> None:
        self.checkouts: list[Path] = []
        self.mutate = mutate

    def verify(self, checkout: Path) -> None:
        self.checkouts.append(checkout)
        if self.mutate:
            (checkout / "src/melloa/example.py").write_text("VALUE = 3\n", encoding="utf-8")


class _Deployment:
    def __init__(self) -> None:
        self.deployed: list[tuple[Path, str]] = []
        self.rollbacks: list[Path] = []

    def deploy(self, checkout: Path, revision: str) -> None:
        self.deployed.append((checkout, revision))

    def rollback(self, checkout: Path) -> None:
        self.rollbacks.append(checkout)


def _applying_change(fixed_time, *, patch: str | None = None) -> SelfChange:
    request = "Implement the exact approved owner behavior."
    proposal_patch = patch or (
        "diff --git a/src/melloa/example.py b/src/melloa/example.py\n"
        "--- a/src/melloa/example.py\n"
        "+++ b/src/melloa/example.py\n"
        "@@ -1 +1 @@\n"
        "-VALUE = 1\n"
        "+VALUE = 2\n"
    )
    summary = "Implement the approved behavior."
    digest = self_change_proposal_digest(
        base_revision="a" * 40,
        summary=summary,
        patch=proposal_patch,
    )
    return SelfChange(
        change_id=record_id("change", 2),
        owner_id=record_id("owner", 1),
        request_text=request,
        request_digest=self_change_request_digest(request),
        requested_update_id=10,
        state=SelfChangeState.APPLYING,
        base_revision="a" * 40,
        proposal_summary=summary,
        proposal_patch=proposal_patch,
        proposal_digest=digest,
        approval_update_id=11,
        approved_digest=digest,
        attempt_count=1,
        available_at=fixed_time,
        lease_owner=record_id("worker", 1),
        lease_expires_at=fixed_time + timedelta(hours=2),
        requested_at=fixed_time,
        updated_at=fixed_time,
        approved_at=fixed_time,
    )


def test_applying_worker_retains_candidate_before_release(fixed_time) -> None:
    claim = _applying_change(fixed_time)
    candidate = "b" * 40
    retained = claim.model_copy(update={"candidate_revision": candidate})
    store = Mock()
    store.claim_next_applying.return_value = claim
    store.record_candidate.return_value = retained
    store.record_deployed.return_value = retained.model_copy(
        update={
            "state": SelfChangeState.DEPLOYED,
            "lease_owner": None,
            "lease_expires_at": None,
            "deployed_at": fixed_time,
        }
    )
    executor = Mock()
    executor.prepare_candidate.return_value = candidate
    worker = SelfChangeApplyingWorker(
        store=store,
        executor=executor,
        clock=lambda: fixed_time,
        id_factory=lambda prefix: record_id(prefix, 9),
    )

    result = worker.process_next()

    assert result is not None
    store.record_candidate.assert_called_once_with(
        claim,
        candidate_revision=candidate,
        now=fixed_time,
    )
    executor.release_candidate.assert_called_once_with(retained)
    store.record_deployed.assert_called_once_with(
        retained,
        candidate_revision=candidate,
        now=fixed_time,
    )


def test_applying_worker_records_bounded_release_failure(fixed_time) -> None:
    claim = _applying_change(fixed_time)
    store = Mock()
    store.claim_next_applying.return_value = claim
    store.record_applying_failure.return_value = claim
    executor = Mock()
    executor.prepare_candidate.side_effect = SelfChangeReleaseError(
        "self_change.base_revision_changed"
    )
    worker = SelfChangeApplyingWorker(
        store=store,
        executor=executor,
        clock=lambda: fixed_time,
        id_factory=lambda prefix: record_id(prefix, 9),
    )

    worker.process_next()

    store.record_applying_failure.assert_called_once_with(
        claim,
        error_code="self_change.base_revision_changed",
        retry_at=fixed_time + timedelta(minutes=10),
        now=fixed_time,
    )


def test_git_release_commits_exact_patch_then_deploys_and_pushes(
    tmp_path: Path,
    fixed_time,
) -> None:
    repository, remote, git = _repository(tmp_path)
    patch = _approved_patch(repository, git)
    state_root = tmp_path / "release-work"
    state_root.mkdir()
    verifier = _Verifier()
    deployment = _Deployment()
    executor = GitSelfChangeReleaseExecutor(
        repository=repository,
        state_root=state_root,
        git_executable=git,
        verifier=verifier,
        deployment=deployment,
    )
    change = _change_for_repository(fixed_time, repository, git, patch)

    candidate = executor.prepare_candidate(change)
    retained = change.model_copy(update={"candidate_revision": candidate})
    executor.release_candidate(retained)

    assert len(verifier.checkouts) == 1
    assert deployment.deployed == [(state_root / change.change_id, candidate)]
    assert deployment.rollbacks == []
    assert _git(git, remote, "rev-parse", "refs/heads/main") == candidate
    assert _git(
        git,
        remote,
        "rev-parse",
        f"refs/heads/melloa-candidates/{change.change_id}",
    ) == candidate
    assert executor.prepare_candidate(retained) == candidate


def test_git_release_rejects_verifier_mutation(
    tmp_path: Path,
    fixed_time,
) -> None:
    repository, _remote, git = _repository(tmp_path)
    patch = _approved_patch(repository, git)
    state_root = tmp_path / "release-work"
    state_root.mkdir()
    executor = GitSelfChangeReleaseExecutor(
        repository=repository,
        state_root=state_root,
        git_executable=git,
        verifier=_Verifier(mutate=True),
        deployment=_Deployment(),
    )

    with pytest.raises(SelfChangeReleaseError) as raised:
        executor.prepare_candidate(_change_for_repository(fixed_time, repository, git, patch))

    assert raised.value.reason_code == "self_change.approved_patch_changed"


def test_git_release_rolls_back_if_main_moves_after_candidate_deploy(
    tmp_path: Path,
    fixed_time,
) -> None:
    repository, remote, git = _repository(tmp_path)
    patch = _approved_patch(repository, git)
    state_root = tmp_path / "release-work"
    state_root.mkdir()
    deployment = _Deployment()
    executor = GitSelfChangeReleaseExecutor(
        repository=repository,
        state_root=state_root,
        git_executable=git,
        verifier=_Verifier(),
        deployment=deployment,
    )
    change = _change_for_repository(fixed_time, repository, git, patch)
    candidate = executor.prepare_candidate(change)
    retained = change.model_copy(update={"candidate_revision": candidate})
    (repository / "src/melloa/other.py").write_text("OTHER = 1\n", encoding="utf-8")
    _run((str(git), "-C", str(repository), "add", "src/melloa/other.py"))
    _commit(git, repository, "Concurrent")
    _run((str(git), "-C", str(repository), "push", "origin", "main"))

    with pytest.raises(SelfChangeReleaseError) as raised:
        executor.release_candidate(retained)

    assert raised.value.reason_code == "self_change.main_changed_before_publication"
    assert deployment.deployed == [(state_root / change.change_id, candidate)]
    assert deployment.rollbacks == [state_root / change.change_id]
    assert _git(git, remote, "rev-parse", "refs/heads/main") != candidate


def test_git_release_rejects_checkout_that_differs_from_retained_candidate(
    tmp_path: Path,
    fixed_time,
) -> None:
    repository, _remote, git = _repository(tmp_path)
    patch = _approved_patch(repository, git)
    state_root = tmp_path / "release-work"
    state_root.mkdir()
    executor = GitSelfChangeReleaseExecutor(
        repository=repository,
        state_root=state_root,
        git_executable=git,
        verifier=_Verifier(),
        deployment=_Deployment(),
    )
    change = _change_for_repository(fixed_time, repository, git, patch)
    candidate = executor.prepare_candidate(change)
    retained = change.model_copy(update={"candidate_revision": candidate})
    checkout = state_root / change.change_id
    _run(
        (
            str(git),
            "-C",
            str(checkout),
            "-c",
            "user.name=Melloa Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "--amend",
            "--no-edit",
            "--allow-empty",
            "--date=2001-01-01T00:00:00Z",
        )
    )

    with pytest.raises(SelfChangeReleaseError) as raised:
        executor.prepare_candidate(retained)

    assert raised.value.reason_code == "self_change.candidate_checkout_changed"


def _change_for_repository(
    fixed_time,
    repository: Path,
    git: Path,
    patch: str,
) -> SelfChange:
    change = _applying_change(fixed_time, patch=patch)
    base_revision = _git(git, repository, "rev-parse", "HEAD")
    digest = self_change_proposal_digest(
        base_revision=base_revision,
        summary=change.proposal_summary or "",
        patch=patch,
    )
    return change.model_copy(
        update={
            "base_revision": base_revision,
            "proposal_digest": digest,
            "approved_digest": digest,
        }
    )


def _approved_patch(repository: Path, git: Path) -> str:
    path = repository / "src/melloa/example.py"
    path.write_text("VALUE = 2\n", encoding="utf-8")
    patch = _run(
        (
            str(git),
            "-C",
            str(repository),
            "diff",
            "--binary",
            "--full-index",
            "--no-ext-diff",
            "HEAD",
            "--",
        )
    ).stdout.decode("utf-8")
    path.write_text("VALUE = 1\n", encoding="utf-8")
    return patch


def _repository(tmp_path: Path) -> tuple[Path, Path, Path]:
    git_path = shutil.which("git")
    assert git_path is not None
    git = Path(git_path).resolve()
    remote = tmp_path / "remote.git"
    repository = tmp_path / "repository"
    _run((str(git), "init", "--bare", "--initial-branch=main", str(remote)))
    _run((str(git), "init", "--initial-branch=main", str(repository)))
    (repository / "src/melloa").mkdir(parents=True)
    (repository / "src/melloa/example.py").write_text("VALUE = 1\n", encoding="utf-8")
    _run((str(git), "-C", str(repository), "add", "."))
    _commit(git, repository, "Initial")
    _run((str(git), "-C", str(repository), "remote", "add", "origin", str(remote)))
    _run((str(git), "-C", str(repository), "push", "-u", "origin", "main"))
    return repository, remote, git


def _commit(git: Path, repository: Path, message: str) -> None:
    _run(
        (
            str(git),
            "-C",
            str(repository),
            "-c",
            "user.name=Melloa Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-m",
            message,
        )
    )


def _git(git: Path, repository: Path, *arguments: str) -> str:
    return _run((str(git), "-C", str(repository), *arguments)).stdout.decode().strip()


def _run(command: tuple[str, ...]) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(  # noqa: S603
        command,
        check=True,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=10,
    )
