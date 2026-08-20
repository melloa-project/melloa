from __future__ import annotations

from pathlib import Path

import pytest

from melloa.adapters.coding.server_release import (
    ExternalSandboxSelfChangeVerifier,
    ServerReleaseDeployment,
)
from melloa.ports.self_change import SelfChangeReleaseError


def test_external_verifier_accepts_only_successful_protected_command(tmp_path: Path) -> None:
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    verifier_command = tmp_path / "verify"
    verifier_command.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    verifier_command.chmod(0o700)
    verifier = ExternalSandboxSelfChangeVerifier(
        verifier_command,
        require_root_owner=False,
    )

    verifier.verify(checkout)

    verifier_command.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    with pytest.raises(SelfChangeReleaseError) as raised:
        verifier.verify(checkout)
    assert raised.value.reason_code == "self_change.verification_failed"


def test_server_release_adapter_passes_only_exact_paths_and_revision(tmp_path: Path) -> None:
    checkout = tmp_path / "checkout"
    tools = checkout / "tools"
    tools.mkdir(parents=True)
    script = tools / "server_release.sh"
    script.write_text(
        "#!/bin/sh\nset -eu\nprintf '%s\\n' \"$*\" >> release-arguments\n",
        encoding="utf-8",
    )
    script.chmod(0o700)
    environment_file = tmp_path / "server.env"
    environment_file.write_text("SAFE=paths-only\n", encoding="utf-8")
    environment_file.chmod(0o600)
    state_dir = tmp_path / "release-state"
    state_dir.mkdir()
    deployment = ServerReleaseDeployment(
        environment_file=environment_file,
        release_state_dir=state_dir,
        timeout_seconds=10,
    )
    revision = "a" * 40

    deployment.deploy(checkout, revision)
    deployment.rollback(checkout)

    assert (checkout / "release-arguments").read_text(encoding="utf-8").splitlines() == [
        f"deploy --env-file {environment_file} --state-dir {state_dir} --revision {revision}",
        f"rollback --env-file {environment_file} --state-dir {state_dir}",
    ]
