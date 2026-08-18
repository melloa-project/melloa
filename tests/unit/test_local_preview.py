from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import stat
import subprocess
from pathlib import Path
from types import SimpleNamespace
from urllib.error import URLError

import pytest

from melloa.apps import local_preview
from melloa.domain.models import ModelRouteHealthState


def test_preview_state_is_private_and_removed_only_with_marker(tmp_path: Path) -> None:
    root = tmp_path / "preview-state"
    paths, credential = local_preview.create_preview_state(root)

    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    assert stat.S_IMODE(paths.owner_credential.stat().st_mode) == 0o600
    assert paths.owner_credential.read_text(encoding="utf-8").strip() == credential
    assert len(credential) >= 32

    local_preview.remove_preview_state(paths)
    assert not root.exists()

    unmarked = tmp_path / "unmarked"
    unmarked.mkdir()
    with pytest.raises(local_preview.PreviewError, match="unmarked"):
        local_preview.remove_preview_state(local_preview._paths(unmarked))
    assert unmarked.exists()


def test_preview_state_initialization_failure_removes_created_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "preview-state"
    monkeypatch.setattr(
        local_preview,
        "_write_private",
        lambda *_args: (_ for _ in ()).throw(OSError("disk unavailable")),
    )

    with pytest.raises(local_preview.PreviewError, match="could not be initialized"):
        local_preview.create_preview_state(root)

    assert not root.exists()


def test_core_receives_only_guardian_read_paths(tmp_path: Path) -> None:
    paths = local_preview._paths(tmp_path)
    command = local_preview.core_command(paths, 8123)

    assert str(paths.guardian_status) in command
    assert str(paths.guardian_public_key) in command
    assert str(paths.guardian_private_key) not in command
    assert str(paths.guardian_audit) not in command
    assert str(paths.guardian_lock) not in command
    assert "transition" not in command


def test_core_receives_one_model_route_config_without_guardian_mutation_argv(
    tmp_path: Path,
) -> None:
    paths = local_preview._paths(tmp_path)
    route_path = tmp_path / "ollama-route.json"

    command = local_preview.core_command(paths, 8123, route_path)

    assert command[-2:] == ("--model-route-config", str(route_path))
    assert str(paths.guardian_private_key) not in command
    assert "transition" not in command


def test_model_preflight_requires_device_route_and_exact_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    route_path = tmp_path / "route.json"
    route_path.write_text(
        """{
          "route_id": "model.local.ollama-qwen",
          "display_name": "Local Qwen via Ollama",
          "provider_id": "provider.ollama-local",
          "model_id": "qwen3:4b-instruct-2507-q4_K_M",
          "base_url": "http://127.0.0.1:11434/v1",
          "processing_location": "device"
        }""",
        encoding="utf-8",
    )
    resolved, config = local_preview.load_preview_model_route(route_path)
    assert resolved == route_path.resolve()

    class MissingModelGateway:
        def __init__(self, supplied_config) -> None:
            assert supplied_config is config

        def health(self):
            return SimpleNamespace(
                state=ModelRouteHealthState.UNAVAILABLE,
                reason_code="model.configured_model_unavailable",
            )

    monkeypatch.setattr(local_preview, "OpenAICompatibleModelGateway", MissingModelGateway)
    with pytest.raises(local_preview.PreviewError) as failure:
        local_preview.preflight_model_route(config)
    message = str(failure.value)
    assert "ollama serve" in message
    assert "ollama pull qwen3:4b-instruct-2507-q4_K_M" in message
    assert "response" not in message

    private_route = config.model_dump(mode="json")
    private_route["processing_location"] = "private_network"
    route_path.write_text(json.dumps(private_route), encoding="utf-8")
    with pytest.raises(local_preview.PreviewError, match="only a DEVICE"):
        local_preview.load_preview_model_route(route_path)


def test_run_preview_rejects_multiple_routes_and_preflights_before_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = argparse.Namespace(
        guardian_root=tmp_path / "guardian",
        state_dir=tmp_path / "state",
        model_route_config=[tmp_path / "one.json", tmp_path / "two.json"],
        core_port=8000,
        web_port=8787,
        startup_timeout=1.0,
    )
    with pytest.raises(local_preview.PreviewError, match="at most one"):
        local_preview.run_preview(args)

    _, config = local_preview.load_preview_model_route(
        local_preview.ROOT / "config/routes/ollama-qwen.example.json"
    )
    assert config.model_id == "qwen3:4b-instruct-2507-q4_K_M"
    args.model_route_config = [tmp_path / "route.json"]
    monkeypatch.setattr(
        local_preview,
        "load_preview_model_route",
        lambda path: (path, config),
    )
    monkeypatch.setattr(
        local_preview,
        "preflight_model_route",
        lambda _config: (_ for _ in ()).throw(local_preview.PreviewError("not ready")),
    )
    monkeypatch.setattr(
        local_preview,
        "create_preview_state",
        lambda *_args: pytest.fail("state was created before model preflight"),
    )

    with pytest.raises(local_preview.PreviewError, match="not ready"):
        local_preview.run_preview(args)


def test_preview_contracts_distinguish_fixture_and_on_device_model() -> None:
    fixture_contract = local_preview.preview_contract(None)
    assert "no external model calls" in fixture_contract
    assert "guided output is not Melli" in fixture_contract
    assert "Fill a no-network tour message" in local_preview.preview_next_action(None)

    _, config = local_preview.load_preview_model_route(
        local_preview.ROOT / "config/routes/ollama-qwen.example.json"
    )
    model_contract = local_preview.preview_contract(config)
    assert "owner text and selected memory" in model_contract
    assert "on-device Local Qwen via Ollama" in model_contract
    assert "no external disclosure" in model_contract
    assert "labelled synthetic fallback remains" in model_contract
    model_action = local_preview.preview_next_action(config)
    assert "Eligible model required" in model_action
    assert "Fill a no-network tour message" not in model_action


def test_make_preview_rejects_unknown_model_selector() -> None:
    make = shutil.which("make")
    assert make is not None
    result = subprocess.run(  # noqa: S603 - resolved make executable and fixed argv
        (
            make,
            "--no-print-directory",
            "-n",
            "preview",
            "PREVIEW_MODEL=unknown",
        ),
        cwd=local_preview.ROOT,
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode == 2
    assert "Unknown PREVIEW_MODEL 'unknown'" in result.stderr
    assert "ollama" in result.stderr


@pytest.mark.parametrize("version", ("v22.0.0", "v24.1.2"))
def test_node_version_accepts_supported_major(tmp_path: Path, version: str) -> None:
    local_preview.validate_node(
        tmp_path / "node",
        runner=lambda *_args, **_kwargs: SimpleNamespace(stdout=version),  # type: ignore[arg-type,return-value]
    )


def test_node_version_has_corrective_failure(tmp_path: Path) -> None:
    with pytest.raises(local_preview.PreviewError, match="found major version 20"):
        local_preview.validate_node(
            tmp_path / "node",
            runner=lambda *_args, **_kwargs: SimpleNamespace(stdout="v20.9.0"),  # type: ignore[arg-type,return-value]
        )

    with pytest.raises(local_preview.PreviewError, match="could not be verified"):
        local_preview.validate_node(
            tmp_path / "node",
            runner=lambda *_args, **_kwargs: SimpleNamespace(stdout="unknown"),  # type: ignore[arg-type,return-value]
        )


def test_guardian_setup_is_explicit_init_then_offline_transition(tmp_path: Path) -> None:
    paths = local_preview._paths(tmp_path)
    commands = local_preview.guardian_commands(tmp_path / "guardianctl", paths)

    assert [command[1] for command in commands] == ["init", "transition"]
    assert "offline" in commands[1]
    assert "owner.local_preview" in commands[1]
    assert all(str(paths.guardian_private_key) in command for command in commands)


def test_initialize_guardian_reports_bounded_failure(tmp_path: Path) -> None:
    paths = local_preview._paths(tmp_path)

    def fail(*_args, **_kwargs):
        raise subprocess.CalledProcessError(2, "guardianctl", stderr="private detail\nrejected")

    with pytest.raises(local_preview.PreviewError, match="Guardian preview setup failed: rejected"):
        local_preview.initialize_guardian(tmp_path / "guardianctl", paths, runner=fail)


def test_initialize_guardian_verifies_offline_projection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = local_preview._paths(tmp_path)
    commands: list[tuple[str, ...]] = []

    class Reader:
        def __init__(self, status: Path, public_key: Path) -> None:
            assert status == paths.guardian_status
            assert public_key == paths.guardian_public_key

        def read_status(self):
            return SimpleNamespace(payload=SimpleNamespace(mode=SimpleNamespace(value="offline")))

    monkeypatch.setattr(local_preview, "FileGuardianStatusReader", Reader)
    local_preview.initialize_guardian(
        tmp_path / "guardianctl",
        paths,
        runner=lambda command, **_kwargs: commands.append(command),  # type: ignore[arg-type,return-value]
    )

    assert commands == list(local_preview.guardian_commands(tmp_path / "guardianctl", paths))


def test_initialize_guardian_rejects_unverified_or_nonoffline_projection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = local_preview._paths(tmp_path)

    class BrokenReader:
        def __init__(self, *_args) -> None:
            pass

        def read_status(self):
            raise ValueError("invalid signature")

    monkeypatch.setattr(local_preview, "FileGuardianStatusReader", BrokenReader)
    with pytest.raises(local_preview.PreviewError, match="could not be verified"):
        local_preview.initialize_guardian(
            tmp_path / "guardianctl",
            paths,
            runner=lambda *_args, **_kwargs: None,  # type: ignore[arg-type,return-value]
        )

    class NormalReader(BrokenReader):
        def read_status(self):
            return SimpleNamespace(payload=SimpleNamespace(mode=SimpleNamespace(value="normal")))

    monkeypatch.setattr(local_preview, "FileGuardianStatusReader", NormalReader)
    with pytest.raises(local_preview.PreviewError, match="offline mode"):
        local_preview.initialize_guardian(
            tmp_path / "guardianctl",
            paths,
            runner=lambda *_args, **_kwargs: None,  # type: ignore[arg-type,return-value]
        )


def test_wait_for_endpoint_stops_when_child_exits(tmp_path: Path) -> None:
    log_path = tmp_path / "core.log"
    log_path.write_text("configuration rejected\n", encoding="utf-8")

    class ExitedProcess:
        def poll(self) -> int:
            return 2

    managed = local_preview.ManagedProcess(
        name="Melloa core",
        process=ExitedProcess(),  # type: ignore[arg-type]
        log=log_path.open("rb"),
        log_path=log_path,
    )
    try:
        with pytest.raises(local_preview.PreviewError, match="configuration rejected"):
            local_preview.wait_for_endpoint(
                "http://127.0.0.1:8000/health/ready",
                managed,
                timeout_seconds=0.1,
            )
    finally:
        managed.log.close()


def test_wait_for_endpoint_accepts_ready_loopback_response(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log_path = tmp_path / "core.log"
    log_path.write_text("", encoding="utf-8")

    class RunningProcess:
        def poll(self) -> None:
            return None

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

    monkeypatch.setattr(local_preview, "urlopen", lambda *_args, **_kwargs: Response())
    managed = local_preview.ManagedProcess(
        name="Melloa core",
        process=RunningProcess(),  # type: ignore[arg-type]
        log=log_path.open("rb"),
        log_path=log_path,
    )
    try:
        local_preview.wait_for_endpoint(
            "http://127.0.0.1:8000/health/ready",
            managed,
            timeout_seconds=1,
        )
    finally:
        managed.log.close()


def test_wait_for_endpoint_reports_timeout_and_log_tail(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log_path = tmp_path / "web.log"
    log_path.write_text("first\nlast useful line\n", encoding="utf-8")
    moments = iter((0.0, 0.0, 1.0))

    class RunningProcess:
        def poll(self) -> None:
            return None

    monkeypatch.setattr(local_preview.time, "monotonic", lambda: next(moments))
    monkeypatch.setattr(local_preview.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        local_preview,
        "urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(URLError("connection refused")),
    )
    managed = local_preview.ManagedProcess(
        name="Owner Console",
        process=RunningProcess(),  # type: ignore[arg-type]
        log=log_path.open("rb"),
        log_path=log_path,
    )
    try:
        with pytest.raises(local_preview.PreviewError, match="last useful line"):
            local_preview.wait_for_endpoint(
                "http://127.0.0.1:8787",
                managed,
                timeout_seconds=0.5,
            )
    finally:
        managed.log.close()


def test_stop_process_terminates_its_isolated_process_group(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log_path = tmp_path / "child.log"
    signals: list[tuple[int, signal.Signals]] = []

    class RunningProcess:
        pid = 2345

        def __init__(self) -> None:
            self.running = True

        def poll(self) -> int | None:
            return None if self.running else 0

        def wait(self, *, timeout: int) -> int:
            assert timeout == 5
            self.running = False
            return 0

    process = RunningProcess()
    monkeypatch.setattr(
        os,
        "killpg",
        lambda pid, sent_signal: signals.append((pid, sent_signal)),
    )
    managed = local_preview.ManagedProcess(
        name="child",
        process=process,  # type: ignore[arg-type]
        log=log_path.open("wb"),
        log_path=log_path,
    )

    local_preview._stop_process(managed)

    assert signals == [(2345, signal.SIGTERM)]
    assert managed.log.closed


def test_stop_process_force_kills_child_that_ignores_termination(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log_path = tmp_path / "child.log"
    sent_signals: list[signal.Signals] = []

    class StuckProcess:
        pid = 3456

        def poll(self) -> None:
            return None

        def wait(self, *, timeout: int) -> int:
            if len(sent_signals) == 1:
                raise subprocess.TimeoutExpired("child", timeout)
            return 0

    monkeypatch.setattr(
        os,
        "killpg",
        lambda _pid, sent_signal: sent_signals.append(sent_signal),
    )
    managed = local_preview.ManagedProcess(
        name="child",
        process=StuckProcess(),  # type: ignore[arg-type]
        log=log_path.open("wb"),
        log_path=log_path,
    )

    local_preview._stop_process(managed)

    assert sent_signals == [signal.SIGTERM, signal.SIGKILL]


def test_monitor_reports_unexpected_child_exit(tmp_path: Path) -> None:
    log_path = tmp_path / "child.log"
    log_path.write_text("child failed\n", encoding="utf-8")

    class ExitedProcess:
        def poll(self) -> int:
            return 7

    managed = local_preview.ManagedProcess(
        name="Owner Console",
        process=ExitedProcess(),  # type: ignore[arg-type]
        log=log_path.open("rb"),
        log_path=log_path,
    )
    try:
        with pytest.raises(local_preview.PreviewError, match="child failed"):
            local_preview._monitor((managed,))
    finally:
        managed.log.close()


def test_start_process_uses_no_shell_and_closes_log_on_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class Child:
        pass

    def start(command, **kwargs):
        captured.update(command=command, **kwargs)
        return Child()

    monkeypatch.setattr(local_preview.subprocess, "Popen", start)
    managed = local_preview._start_process(
        "child",
        ("/bin/child", "--flag"),
        tmp_path / "child.log",
        environment={"SAFE": "1"},
    )
    assert captured["command"] == ("/bin/child", "--flag")
    assert captured["start_new_session"] is True
    assert "shell" not in captured
    managed.log.close()

    monkeypatch.setattr(
        local_preview.subprocess,
        "Popen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("cannot execute")),
    )
    with pytest.raises(local_preview.PreviewError, match="cannot execute"):
        local_preview._start_process("child", ("/bin/child",), tmp_path / "failed.log")


def test_run_preview_reports_ready_contract_and_cleans_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = tmp_path / "repository"
    (root / "apps/web/dist").mkdir(parents=True)
    (root / "apps/web/dist/index.html").write_text("ready", encoding="utf-8")
    guardian_root = tmp_path / "guardian"
    (guardian_root / "bin").mkdir(parents=True)
    guardian_binary = guardian_root / "bin/guardianctl"
    guardian_binary.write_text("binary", encoding="utf-8")
    guardian_binary.chmod(0o700)
    node = tmp_path / "node"
    node.write_text("binary", encoding="utf-8")

    started: list[tuple[str, tuple[str, ...], dict[str, str] | None]] = []

    class RunningProcess:
        def poll(self) -> int:
            return 0

    def start_process(name, command, log_path, *, environment=None):
        log = log_path.open("xb")
        started.append((name, tuple(command), environment))
        return local_preview.ManagedProcess(
            name=name,
            process=RunningProcess(),  # type: ignore[arg-type]
            log=log,
            log_path=log_path,
        )

    state = tmp_path / "preview-state"
    monkeypatch.setattr(local_preview, "ROOT", root)
    monkeypatch.setattr(local_preview.shutil, "which", lambda _name: str(node))
    monkeypatch.setattr(local_preview, "validate_node", lambda _node: None)
    monkeypatch.setattr(local_preview, "initialize_guardian", lambda *_args: None)
    monkeypatch.setattr(local_preview, "_start_process", start_process)
    monkeypatch.setattr(local_preview, "wait_for_endpoint", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        local_preview,
        "_monitor",
        lambda _processes: (_ for _ in ()).throw(KeyboardInterrupt()),
    )

    result = local_preview.run_preview(
        argparse.Namespace(
            guardian_root=guardian_root,
            state_dir=state,
            model_route_config=[],
            core_port=18000,
            web_port=18787,
            startup_timeout=1.0,
        )
    )

    output = capsys.readouterr().out
    assert result == 0
    assert "Melloa is ready" in output
    assert "guided output is not Melli" in output
    assert "Disposable preview state removed" in output
    assert not state.exists()
    assert [item[0] for item in started] == ["Melloa core", "Owner Console"]
    assert str(state / "guardian-private.pem") not in started[0][1]
    assert started[1][2]["MELLOA_CORE_URL"] == "http://127.0.0.1:18000"


def test_run_preview_has_corrective_prerequisite_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "repository"
    (root / "apps/web/dist").mkdir(parents=True)
    (root / "apps/web/dist/index.html").write_text("ready", encoding="utf-8")
    guardian_root = tmp_path / "guardian"
    (guardian_root / "bin").mkdir(parents=True)
    guardian_binary = guardian_root / "bin/guardianctl"
    guardian_binary.write_text("binary", encoding="utf-8")
    guardian_binary.chmod(0o600)
    args = argparse.Namespace(
        guardian_root=guardian_root,
        state_dir=None,
        model_route_config=[],
        core_port=8000,
        web_port=8787,
        startup_timeout=1.0,
    )
    monkeypatch.setattr(local_preview, "ROOT", root)

    with pytest.raises(local_preview.PreviewError, match="not executable"):
        local_preview.run_preview(args)

    guardian_binary.chmod(0o700)
    monkeypatch.setattr(local_preview.shutil, "which", lambda _name: None)
    with pytest.raises(local_preview.PreviewError, match=r"Node\.js"):
        local_preview.run_preview(args)


def test_required_file_and_port_errors_are_bounded(tmp_path: Path) -> None:
    with pytest.raises(local_preview.PreviewError, match="missing required file"):
        local_preview._required_file(tmp_path / "missing", "missing required file")

    directory = tmp_path / "directory"
    directory.mkdir()
    with pytest.raises(local_preview.PreviewError, match="regular file required"):
        local_preview._required_file(directory, "regular file required")

    with pytest.raises(argparse.ArgumentTypeError, match="integer"):
        local_preview._validate_port("not-a-port")


def test_parser_rejects_invalid_ports() -> None:
    with pytest.raises(SystemExit):
        local_preview.build_parser().parse_args(["--web-port", "0"])


def test_sigterm_shutdown_request_ignores_duplicate_signal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installed: list[tuple[int, object]] = []
    monkeypatch.setattr(
        local_preview.signal,
        "signal",
        lambda signum, handler: installed.append((signum, handler)),
    )

    with pytest.raises(KeyboardInterrupt):
        local_preview._signal_as_interrupt(signal.SIGTERM, None)

    assert installed == [(signal.SIGTERM, signal.SIG_IGN)]
