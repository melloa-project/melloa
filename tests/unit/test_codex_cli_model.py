from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

import melloa.adapters.models.codex_cli as codex_cli_module
from melloa.adapters.fakes.guardian import FakeGuardianStatusReader
from melloa.adapters.models.codex_cli import (
    CodexCliInvocationError,
    CodexCliModelGateway,
    CodexCliRouteConfig,
    load_codex_cli_route_config,
)
from melloa.adapters.models.openai_compatible import OpenAICompatibleRouteConfig
from melloa.apps.mvp import build_mvp_runtime
from melloa.domain.classification import Sensitivity
from melloa.domain.guardian import GuardianMode, GuardianStatusPayload
from melloa.domain.models import (
    ModelRouteHealthState,
    ModelRouteRequest,
    ProcessingLocation,
)
from tests.conftest import record_id


@dataclass(frozen=True)
class FakeCodexRuntime:
    config: CodexCliRouteConfig
    executable: Path
    working_directory: Path
    codex_home: Path
    capture_path: Path


def _config(**overrides: object) -> CodexCliRouteConfig:
    document: dict[str, object] = {
        "route_id": "model.codex.test",
        "display_name": "Codex subscription test",
        "model_id": "gpt-test",
        "executable": "/opt/codex/bin/codex",
        "working_directory": "/var/lib/melloa/codex-work",
        "codex_home": "/var/lib/melloa/codex-home",
    }
    document.update(overrides)
    return CodexCliRouteConfig.model_validate(document)


def _request(**overrides: object) -> ModelRouteRequest:
    document: dict[str, object] = {
        "request_id": record_id("request", 1),
        "task_type": "conversation.owner-reply",
        "required_modalities": ("text",),
        "minimum_quality_profile": "quality.conversation",
        "sensitivity": Sensitivity.PERSONAL,
        "allowed_processing_locations": frozenset(
            {ProcessingLocation.APPROVED_PROVIDER}
        ),
        "latency_deadline_ms": 10_000,
        "max_input_tokens": 4_096,
        "max_output_tokens": 512,
        "cost_ceiling_gbp": 0.0,
        "provider_retention_policy": "retention.no-training",
        "minimum_reliability": 0.0,
        "fallback_route_ids": ("model.codex.test",),
        "output_schema_id": "schema.conversation-response.v1",
        "prompt_version": "test-v1",
        "input": {
            "text": "What should I read next? private-owner-message",
            "memory_citations": [
                {
                    "citation_id": record_id("citation", 1),
                    "assertion_id": record_id("assertion", 1),
                }
            ],
        },
    }
    document.update(overrides)
    return ModelRouteRequest.model_validate(document)


def _fake_runtime(tmp_path: Path, *, mode: str = "success") -> FakeCodexRuntime:
    tmp_path.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp_path.chmod(0o700)
    executable = tmp_path / "fake-codex"
    working_directory = tmp_path / "codex-work"
    codex_home = tmp_path / "codex-home"
    path_anchor = tmp_path / "path-anchor"
    capture_path = tmp_path / "capture.json"
    for directory in (working_directory, codex_home, path_anchor):
        directory.mkdir(mode=0o700)
        directory.chmod(0o700)
    executable.write_text(
        f"""#!{sys.executable}
import json
import os
import sys
import time
from pathlib import Path

MODE = {mode!r}
CAPTURE_PATH = Path({str(capture_path)!r})

def capture(document):
    CAPTURE_PATH.write_text(json.dumps(document, sort_keys=True), encoding="utf-8")

if "--version" in sys.argv:
    capture({{
        "argv": sys.argv[1:],
        "cwd": os.getcwd(),
        "environment": dict(os.environ),
    }})
    if MODE == "health-failure":
        sys.stderr.write("provider-secret-from-health\\n")
        raise SystemExit(23)
    raise SystemExit(0)

prompt = sys.stdin.read()
schema_path = Path(sys.argv[sys.argv.index("--output-schema") + 1])
output_path = Path(sys.argv[sys.argv.index("--output-last-message") + 1])
capture({{
    "argv": sys.argv[1:],
    "cwd": os.getcwd(),
    "environment": dict(os.environ),
    "prompt": prompt,
    "schema": json.loads(schema_path.read_text(encoding="utf-8")),
}})
if MODE == "timeout":
    time.sleep(30)
elif MODE == "nonzero":
    sys.stderr.write("provider-secret-from-stderr\\n")
    raise SystemExit(17)
elif MODE == "missing":
    raise SystemExit(0)
elif MODE == "empty":
    output_path.touch()
elif MODE == "too-large":
    output_path.write_bytes(b"x" * 200_001)
elif MODE == "symlink":
    output_path.symlink_to(schema_path)
elif MODE == "invalid":
    output_path.write_text(
        '{{"text":"Bad shape","citation_ids":[],"leaked":"provider-secret"}}',
        encoding="utf-8",
    )
else:
    output_path.write_text(
        '{{"text":"Try a short essay.","citation_ids":[]}}',
        encoding="utf-8",
    )
""",
        encoding="utf-8",
    )
    executable.chmod(0o700)
    config = _config(
        executable=executable,
        working_directory=path_anchor / ".." / working_directory.name,
        codex_home=path_anchor / ".." / codex_home.name,
    )
    return FakeCodexRuntime(
        config=config,
        executable=executable,
        working_directory=working_directory,
        codex_home=codex_home,
        capture_path=capture_path,
    )


def _gateway(runtime: FakeCodexRuntime, fixed_time: datetime) -> CodexCliModelGateway:
    return CodexCliModelGateway(
        runtime.config,
        clock=lambda: fixed_time,
        id_factory=lambda prefix: record_id(prefix, 2),
    )


def test_route_configuration_is_explicit_external_and_read_only() -> None:
    config = _config()
    route = config.registered_route()

    assert route.processing_location is ProcessingLocation.APPROVED_PROVIDER
    assert route.external_disclosure is True
    assert config.sandbox_mode == "read-only"
    assert config.approval_policy == "never"
    assert config.session_persistence == "ephemeral"
    assert config.ignore_user_config is True
    assert config.ignore_exec_rules is True

    with pytest.raises(ValidationError, match="approved-provider disclosure"):
        _config(processing_location="device")
    with pytest.raises(ValidationError, match=r"provider\.openai-codex-subscription"):
        _config(provider_id="provider.owner-relabelled")
    with pytest.raises(ValidationError, match="String should match pattern"):
        _config(model_id="--dangerously-bypass-approvals-and-sandbox")
    with pytest.raises(ValidationError, match="must be an absolute path"):
        _config(executable="codex")


def test_gateway_uses_stdin_fixed_flags_and_a_minimal_environment(
    tmp_path: Path,
    fixed_time: datetime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _fake_runtime(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "ambient-openai-secret")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "ambient-aws-secret")
    monkeypatch.setenv("SSH_AUTH_SOCK", str(tmp_path / "private-agent.sock"))
    monkeypatch.setenv("UNRELATED_SECRET", "ambient-unrelated-secret")

    result = _gateway(runtime, fixed_time).invoke(_request())
    capture = json.loads(runtime.capture_path.read_text(encoding="utf-8"))
    argv = capture["argv"]
    environment = capture["environment"]
    prompt = json.loads(capture["prompt"])

    assert result.output == {"text": "Try a short essay.", "citation_ids": []}
    assert result.route_id == "model.codex.test"
    assert result.provider_id == "provider.openai-codex-subscription"
    assert result.model_id == "gpt-test"
    assert result.input_tokens == 0
    assert result.output_tokens == 0
    assert result.cost_gbp == 0.0
    assert result.external_disclosure is True
    assert result.started_at == fixed_time
    assert result.completed_at == fixed_time

    assert argv == [
        "--ask-for-approval",
        "never",
        "--sandbox",
        "read-only",
        "--strict-config",
        "exec",
        "--ephemeral",
        "--ignore-user-config",
        "--ignore-rules",
        "--skip-git-repo-check",
        "--model",
        "gpt-test",
        "--cd",
        str(runtime.working_directory),
        "--output-schema",
        argv[argv.index("--output-schema") + 1],
        "--output-last-message",
        argv[argv.index("--output-last-message") + 1],
        "--color",
        "never",
        "-",
    ]
    assert "private-owner-message" not in " ".join(argv)
    assert prompt["owner_message"] == "What should I read next? private-owner-message"
    assert prompt["memory_citations"][0]["citation_id"] == record_id("citation", 1)
    assert "Guardian, policy, memory, credential, or capability authority" in prompt[
        "instructions"
    ]
    assert capture["schema"]["additionalProperties"] is False
    assert set(capture["schema"]["properties"]) == {"text", "citation_ids"}
    assert capture["cwd"] == str(runtime.working_directory)
    assert environment["HOME"] == str(runtime.working_directory)
    assert environment["CODEX_HOME"] == str(runtime.codex_home)
    assert environment["LANG"] == "C.UTF-8"
    assert environment["LC_ALL"] == "C.UTF-8"
    assert environment["NO_COLOR"] == "1"
    assert Path(environment["TMPDIR"]).name.startswith("melloa-codex-")
    for variable in (
        "OPENAI_API_KEY",
        "AWS_SECRET_ACCESS_KEY",
        "SSH_AUTH_SOCK",
        "UNRELATED_SECRET",
    ):
        assert variable not in environment


@pytest.mark.parametrize(
    ("mode", "reason_code"),
    (
        ("invalid", "model.cli_agent.output_invalid"),
        ("empty", "model.cli_agent.output_invalid"),
        ("symlink", "model.cli_agent.output_invalid"),
        ("missing", "model.cli_agent.output_missing"),
        ("too-large", "model.cli_agent.output_too_large"),
        ("nonzero", "model.cli_agent.failed"),
    ),
)
def test_gateway_redacts_process_and_output_failures(
    tmp_path: Path,
    fixed_time: datetime,
    mode: str,
    reason_code: str,
) -> None:
    runtime = _fake_runtime(tmp_path, mode=mode)

    with pytest.raises(CodexCliInvocationError) as raised:
        _gateway(runtime, fixed_time).invoke(_request())

    assert raised.value.reason_code == reason_code
    assert str(raised.value) == reason_code
    assert "provider-secret" not in str(raised.value)
    assert str(runtime.working_directory) not in str(raised.value)


def test_gateway_terminates_timed_out_process(
    tmp_path: Path,
    fixed_time: datetime,
) -> None:
    runtime = _fake_runtime(tmp_path, mode="timeout")

    with pytest.raises(CodexCliInvocationError) as raised:
        _gateway(runtime, fixed_time).invoke(_request(latency_deadline_ms=25))

    assert raised.value.reason_code == "model.cli_agent.timeout"


@pytest.mark.parametrize(
    ("unsafe_target", "reason_code"),
    (
        ("missing-executable", "model.cli_agent.executable_unsafe"),
        ("writable-executable", "model.cli_agent.executable_unsafe"),
        ("writable-executable-directory", "model.cli_agent.executable_unsafe"),
        ("working-directory", "model.cli_agent.working_directory_unsafe"),
        ("codex-home", "model.cli_agent.codex_home_unsafe"),
    ),
)
def test_gateway_rejects_unsafe_runtime_paths(
    tmp_path: Path,
    fixed_time: datetime,
    unsafe_target: str,
    reason_code: str,
) -> None:
    runtime = _fake_runtime(tmp_path)
    if unsafe_target == "missing-executable":
        runtime.executable.unlink()
    elif unsafe_target == "writable-executable":
        runtime.executable.chmod(0o722)
    elif unsafe_target == "writable-executable-directory":
        tmp_path.chmod(0o722)
    elif unsafe_target == "working-directory":
        runtime.working_directory.chmod(0o755)
    else:
        runtime.codex_home.chmod(0o755)

    with pytest.raises(CodexCliInvocationError) as raised:
        _gateway(runtime, fixed_time).invoke(_request())

    assert raised.value.reason_code == reason_code
    assert str(tmp_path) not in str(raised.value)


def test_health_is_redacted_and_tracks_the_last_invocation_failure(
    tmp_path: Path,
    fixed_time: datetime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _fake_runtime(tmp_path, mode="invalid")
    gateway = _gateway(runtime, fixed_time)
    monkeypatch.setenv("OPENAI_API_KEY", "ambient-openai-secret")

    healthy = gateway.health()
    assert healthy.state is ModelRouteHealthState.HEALTHY
    assert healthy.reason_code == "model.cli_agent.executable_ready"

    with pytest.raises(CodexCliInvocationError):
        gateway.invoke(_request())
    degraded = gateway.health()
    capture = json.loads(runtime.capture_path.read_text(encoding="utf-8"))

    assert degraded.state is ModelRouteHealthState.DEGRADED
    assert degraded.reason_code == "model.cli_agent.output_invalid"
    assert capture["argv"] == ["--version"]
    assert capture["cwd"] == str(runtime.working_directory)
    assert capture["environment"]["CODEX_HOME"] == str(runtime.codex_home)
    assert "OPENAI_API_KEY" not in capture["environment"]

    failed_runtime = _fake_runtime(tmp_path / "failed", mode="health-failure")
    unavailable = _gateway(failed_runtime, fixed_time).health()
    assert unavailable.state is ModelRouteHealthState.UNAVAILABLE
    assert unavailable.reason_code == "model.cli_agent.unavailable"


def test_gateway_rejects_invalid_and_oversized_requests_before_execution(
    tmp_path: Path,
    fixed_time: datetime,
) -> None:
    runtime = _fake_runtime(tmp_path)
    gateway = _gateway(runtime, fixed_time)

    with pytest.raises(CodexCliInvocationError) as invalid:
        gateway.invoke(_request(task_type="conversation.unsupported"))
    assert invalid.value.reason_code == "model.cli_agent.request_invalid"
    assert not runtime.capture_path.exists()

    with pytest.raises(CodexCliInvocationError) as empty:
        gateway.invoke(_request(input={"text": "", "memory_citations": []}))
    assert empty.value.reason_code == "model.cli_agent.request_invalid"
    assert not runtime.capture_path.exists()

    with pytest.raises(CodexCliInvocationError) as oversized:
        gateway.invoke(
            _request(
                input={
                    "text": "valid text",
                    "memory_citations": [{"oversized": "x" * 300_000}],
                },
            )
        )
    assert oversized.value.reason_code == "model.cli_agent.request_too_large"
    assert not runtime.capture_path.exists()

    with pytest.raises(CodexCliInvocationError) as unserializable:
        gateway.invoke(
            _request(
                input={"text": "valid text", "memory_citations": [object()]},
            )
        )
    assert unserializable.value.reason_code == "model.cli_agent.request_invalid"
    assert not runtime.capture_path.exists()


def test_gateway_redacts_temporary_directory_failures(
    tmp_path: Path,
    fixed_time: datetime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _fake_runtime(tmp_path)

    def fail_temporary_directory(*_args: object, **_kwargs: object) -> None:
        raise OSError("private-temporary-path")

    monkeypatch.setattr(
        codex_cli_module,
        "TemporaryDirectory",
        fail_temporary_directory,
    )
    with pytest.raises(CodexCliInvocationError) as raised:
        _gateway(runtime, fixed_time).invoke(_request())

    assert raised.value.reason_code == "model.cli_agent.failed"
    assert "private-temporary-path" not in str(raised.value)


def test_route_config_loader_rejects_non_regular_and_oversized_files(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="path must be absolute"):
        load_codex_cli_route_config(Path("relative-codex-route.json"))

    directory = tmp_path / "route"
    directory.mkdir()
    with pytest.raises(ValueError, match="regular file"):
        load_codex_cli_route_config(directory)

    oversized = tmp_path / "oversized.json"
    oversized.write_bytes(b"x" * 65_537)
    with pytest.raises(ValueError, match="too large"):
        load_codex_cli_route_config(oversized)

    writable = tmp_path / "writable.json"
    writable.write_text(_config().model_dump_json(), encoding="utf-8")
    writable.chmod(0o620)
    with pytest.raises(ValueError, match="non-writable regular file"):
        load_codex_cli_route_config(writable)

    symlink_target = tmp_path / "symlink-target.json"
    symlink_target.write_text(_config().model_dump_json(), encoding="utf-8")
    symlink_path = tmp_path / "symlink-route.json"
    symlink_path.symlink_to(symlink_target)
    with pytest.raises(ValueError, match="could not be read safely"):
        load_codex_cli_route_config(symlink_path)

    unsafe_directory = tmp_path / "unsafe"
    unsafe_directory.mkdir(mode=0o700)
    unsafe_config = unsafe_directory / "route.json"
    unsafe_config.write_text(_config().model_dump_json(), encoding="utf-8")
    unsafe_directory.chmod(0o722)
    with pytest.raises(ValueError, match="non-writable regular file"):
        load_codex_cli_route_config(unsafe_config)

    config_file = tmp_path / "route.json"
    config_file.write_text(_config().model_dump_json(), encoding="utf-8")
    loaded = load_codex_cli_route_config(config_file)
    assert loaded.route_id == "model.codex.test"

    repository_example_path = (
        Path(__file__).parents[2] / "config/routes/codex-cli.example.json"
    )
    private_example = tmp_path / "codex-cli.example.json"
    private_example.write_bytes(repository_example_path.read_bytes())
    private_example.chmod(0o600)
    repository_example = load_codex_cli_route_config(private_example)
    assert repository_example.route_id == "model.codex.subscription"
    assert repository_example.processing_location is ProcessingLocation.APPROVED_PROVIDER


def test_mvp_conversation_uses_cli_agent_route_with_inspectable_disclosure(
    tmp_path: Path,
    fixed_time: datetime,
) -> None:
    fake_runtime = _fake_runtime(tmp_path)
    guardian = FakeGuardianStatusReader.from_payload(
        GuardianStatusPayload(
            instance_id="home-guardian",
            mode=GuardianMode.NORMAL,
            sequence=1,
            changed_at=fixed_time,
            reason_code="guardian.codex-cli-smoke",
        ),
        receipt_hash="sha256:" + "1" * 64,
    )
    owner_credential = "owner-bootstrap-credential-for-codex-cli-smoke"
    mvp_runtime = build_mvp_runtime(
        guardian,
        owner_credential,
        cli_agent_route_configs=(fake_runtime.config,),
        clock=lambda: fixed_time,
    )

    assert mvp_runtime.model_route_ids == (
        "model.codex.test",
        "model.fake.deterministic",
    )
    with TestClient(mvp_runtime.app, base_url="https://testserver") as client:
        login = client.post(
            "/api/v1/auth/session",
            json={"credential": owner_credential},
        )
        assert login.status_code == 200
        csrf = login.json()["csrf_token"]
        headers = {"X-Melloa-CSRF": csrf}

        routes = client.get("/api/v1/providers/routes")
        assert routes.status_code == 200
        codex_status = next(
            route
            for route in routes.json()["routes"]
            if route["route_id"] == "model.codex.test"
        )
        assert codex_status["route_kind"] == "cli_agent"
        assert codex_status["processing_location"] == "approved_provider"
        assert codex_status["external_disclosure"] is True
        assert codex_status["health"]["state"] == "healthy"

        thread = client.post(
            "/api/v1/conversations",
            headers=headers,
            json={
                "title": "Codex CLI smoke",
                "sensitivity": "personal",
                "retention_policy": "retention.owner-conversation",
            },
        )
        assert thread.status_code == 201
        thread_id = thread.json()["thread_id"]
        reply = client.post(
            f"/api/v1/conversations/{thread_id}/messages",
            headers=headers,
            json={
                "text": "Suggest a short essay.",
                "idempotency_key": "codex-cli-smoke:message:1",
            },
        )
        assert reply.status_code == 200
        assert reply.json()["output_message"]["parts"][0]["text"] == (
            "Try a short essay."
        )

        turn_id = reply.json()["turn"]["turn_id"]
        inspection = client.get(
            f"/api/v1/conversations/{thread_id}/turns/{turn_id}"
        )
        assert inspection.status_code == 200
        model_result = inspection.json()["model_result"]
        assert model_result["route_id"] == "model.codex.test"
        assert model_result["external_disclosure"] is True
        assert model_result["attempts"][0]["processing_location"] == (
            "approved_provider"
        )
        assert inspection.json()["retrieval_manifest"]["external_disclosure"] is True


def test_mvp_runtime_rejects_duplicate_ids_across_cli_agent_routes(
    tmp_path: Path,
    fixed_time: datetime,
) -> None:
    fake_runtime = _fake_runtime(tmp_path)
    guardian = FakeGuardianStatusReader.from_payload(
        GuardianStatusPayload(
            instance_id="home-guardian",
            mode=GuardianMode.NORMAL,
            sequence=1,
            changed_at=fixed_time,
            reason_code="guardian.codex-cli-duplicate-test",
        ),
        receipt_hash="sha256:" + "2" * 64,
    )

    with pytest.raises(ValueError, match="route IDs must be unique"):
        build_mvp_runtime(
            guardian,
            "owner-bootstrap-credential-for-codex-cli-duplicate-test",
            cli_agent_route_configs=(fake_runtime.config, fake_runtime.config),
            clock=lambda: fixed_time,
        )


def test_mvp_route_order_prefers_local_then_subscription_then_direct_provider(
    tmp_path: Path,
    fixed_time: datetime,
) -> None:
    fake_runtime = _fake_runtime(tmp_path)
    local_route = OpenAICompatibleRouteConfig(
        route_id="model.local.device",
        display_name="Local device route",
        provider_id="provider.local-test",
        model_id="local-test",
        base_url="http://127.0.0.1:11434/v1",
    )
    direct_provider_route = OpenAICompatibleRouteConfig(
        route_id="model.direct.provider",
        display_name="Direct provider route",
        provider_id="provider.direct-test",
        model_id="direct-test",
        base_url="https://provider.example.test/v1",
        processing_location=ProcessingLocation.APPROVED_PROVIDER,
    )
    guardian = FakeGuardianStatusReader.from_payload(
        GuardianStatusPayload(
            instance_id="home-guardian",
            mode=GuardianMode.NORMAL,
            sequence=1,
            changed_at=fixed_time,
            reason_code="guardian.codex-cli-order-test",
        ),
        receipt_hash="sha256:" + "3" * 64,
    )

    runtime = build_mvp_runtime(
        guardian,
        "owner-bootstrap-credential-for-codex-cli-order-test",
        route_configs=(direct_provider_route, local_route),
        cli_agent_route_configs=(fake_runtime.config,),
        clock=lambda: fixed_time,
    )

    assert runtime.model_route_ids == (
        "model.local.device",
        "model.codex.test",
        "model.direct.provider",
        "model.fake.deterministic",
    )
