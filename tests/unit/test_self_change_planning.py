from __future__ import annotations

import shutil
import subprocess
from datetime import timedelta
from pathlib import Path
from unittest.mock import Mock

from melloa.adapters.coding.codex_cli import CodexCliSourceChangePlanner
from melloa.application.self_change_planning import SelfChangePlanningWorker
from melloa.domain.self_change import (
    PlannedSelfChange,
    SelfChange,
    SelfChangeState,
    self_change_request_digest,
)
from melloa.ports.self_change import SelfChangePlanningError
from tests.conftest import record_id


def _planning_change(fixed_time) -> SelfChange:
    request = "Add one friendly bounded behavior."
    return SelfChange(
        change_id=record_id("change", 1),
        owner_id=record_id("owner", 1),
        request_text=request,
        request_digest=self_change_request_digest(request),
        requested_update_id=10,
        state=SelfChangeState.PLANNING,
        attempt_count=1,
        available_at=fixed_time,
        lease_owner=record_id("worker", 1),
        lease_expires_at=fixed_time + timedelta(minutes=30),
        requested_at=fixed_time,
        updated_at=fixed_time,
    )


def test_planning_worker_retains_the_exact_agent_proposal(fixed_time) -> None:
    claim = _planning_change(fixed_time)
    proposal = PlannedSelfChange(
        base_revision="a" * 40,
        summary="Add the bounded behavior.",
        patch="diff --git a/src/melloa/example.py b/src/melloa/example.py\n+bounded\n",
    )
    store = Mock()
    store.claim_next_planning.return_value = claim
    store.record_proposal.return_value = claim.model_copy(
        update={
            "state": SelfChangeState.PROPOSAL_READY,
            "base_revision": proposal.base_revision,
            "proposal_summary": proposal.summary,
            "proposal_patch": proposal.patch,
            "proposal_digest": proposal.proposal_digest,
            "attempt_count": 0,
            "lease_owner": None,
            "lease_expires_at": None,
        }
    )
    planner = Mock()
    planner.plan.return_value = proposal
    worker = SelfChangePlanningWorker(
        store=store,
        planner=planner,
        clock=lambda: fixed_time,
        id_factory=lambda prefix: record_id(prefix, 9),
    )

    result = worker.process_next()

    assert result is not None
    planner.plan.assert_called_once_with(claim)
    store.record_proposal.assert_called_once_with(
        claim,
        base_revision=proposal.base_revision,
        summary=proposal.summary,
        patch=proposal.patch,
        now=fixed_time,
    )


def test_planning_worker_records_only_a_bounded_failure_code(fixed_time) -> None:
    claim = _planning_change(fixed_time)
    store = Mock()
    store.claim_next_planning.return_value = claim
    store.record_planning_failure.return_value = claim.model_copy(
        update={
            "state": SelfChangeState.REQUESTED,
            "lease_owner": None,
            "lease_expires_at": None,
        }
    )
    planner = Mock()
    planner.plan.side_effect = SelfChangePlanningError(
        "self_change.coding_agent_unavailable"
    )
    worker = SelfChangePlanningWorker(
        store=store,
        planner=planner,
        clock=lambda: fixed_time,
        id_factory=lambda prefix: record_id(prefix, 9),
        retry_delay=timedelta(minutes=7),
    )

    worker.process_next()

    store.record_planning_failure.assert_called_once_with(
        claim,
        error_code="self_change.coding_agent_unavailable",
        retry_at=fixed_time + timedelta(minutes=7),
        now=fixed_time,
    )


def test_codex_planner_uses_disposable_checkout_and_returns_exact_patch(
    tmp_path: Path,
    fixed_time,
) -> None:
    repository, work_root, git = _repository(tmp_path)
    codex = _fake_codex(
        tmp_path,
        "mkdir -p src/melloa\nprintf 'VALUE = 2\\n' > src/melloa/example.py\n",
    )
    planner = CodexCliSourceChangePlanner(
        repository=repository,
        work_root=work_root,
        codex_executable=codex,
        git_executable=git,
        timeout_seconds=10,
    )

    proposal = planner.plan(_planning_change(fixed_time))

    assert proposal.base_revision == _git(git, repository, "rev-parse", "HEAD").strip()
    assert "VALUE = 2" in proposal.patch
    assert "src/melloa/example.py" in proposal.patch
    assert not (repository / "src/melloa/example.py").exists()
    assert list(work_root.iterdir()) == []


def test_codex_planner_rejects_control_plane_changes(
    tmp_path: Path,
    fixed_time,
) -> None:
    repository, work_root, git = _repository(tmp_path)
    codex = _fake_codex(
        tmp_path,
        "printf '\\n# unsafe\\n' >> src/melloa/apps/runtime.py\n",
    )
    planner = CodexCliSourceChangePlanner(
        repository=repository,
        work_root=work_root,
        codex_executable=codex,
        git_executable=git,
        timeout_seconds=10,
    )

    try:
        planner.plan(_planning_change(fixed_time))
    except SelfChangePlanningError as error:
        assert error.reason_code == "self_change.protected_path_changed"
    else:
        raise AssertionError("protected change was accepted")


def _repository(tmp_path: Path) -> tuple[Path, Path, Path]:
    git_path = shutil.which("git")
    assert git_path is not None
    git = Path(git_path).resolve()
    remote = tmp_path / "remote.git"
    repository = tmp_path / "repository"
    work_root = tmp_path / "work"
    work_root.mkdir()
    _run((str(git), "init", "--bare", "--initial-branch=main", str(remote)))
    _run((str(git), "init", "--initial-branch=main", str(repository)))
    (repository / "src/melloa/apps").mkdir(parents=True)
    (repository / "src/melloa/apps/runtime.py").write_text("VALUE = 1\n", encoding="utf-8")
    _run((str(git), "-C", str(repository), "add", "."))
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
            "Initial",
        )
    )
    _run((str(git), "-C", str(repository), "remote", "add", "origin", str(remote)))
    _run((str(git), "-C", str(repository), "push", "-u", "origin", "main"))
    return repository, work_root, git


def _fake_codex(tmp_path: Path, body: str) -> Path:
    executable = tmp_path / f"fake-codex-{len(tuple(tmp_path.glob('fake-codex-*')))}"
    executable.write_text("#!/bin/sh\nset -eu\n" + body, encoding="utf-8")
    executable.chmod(0o700)
    return executable


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
