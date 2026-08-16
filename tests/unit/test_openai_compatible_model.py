from __future__ import annotations

import json

import httpx
import pytest
from pydantic import ValidationError

from melloa.adapters.models.openai_compatible import (
    OpenAICompatibleModelGateway,
    OpenAICompatibleRouteConfig,
    load_openai_compatible_route_config,
)
from melloa.domain.classification import Sensitivity
from melloa.domain.models import (
    ModelRouteHealthState,
    ModelRouteRequest,
    ProcessingLocation,
)
from tests.conftest import record_id


def _config(**overrides) -> OpenAICompatibleRouteConfig:
    document = {
        "route_id": "model.local.test",
        "display_name": "Local test model",
        "provider_id": "provider.local-test",
        "model_id": "qwen-test",
        "base_url": "http://127.0.0.1:11434/v1",
        "processing_location": "device",
    }
    document.update(overrides)
    return OpenAICompatibleRouteConfig.model_validate(document)


def _request() -> ModelRouteRequest:
    return ModelRouteRequest(
        request_id=record_id("request", 1),
        task_type="conversation.owner-reply",
        required_modalities=("text",),
        minimum_quality_profile="quality.conversation",
        sensitivity=Sensitivity.PERSONAL,
        allowed_processing_locations=frozenset({ProcessingLocation.DEVICE}),
        latency_deadline_ms=10_000,
        max_input_tokens=4_096,
        max_output_tokens=512,
        cost_ceiling_gbp=1.0,
        provider_retention_policy="retention.no-training",
        minimum_reliability=0.0,
        fallback_route_ids=("model.local.test",),
        output_schema_id="schema.conversation-response.v1",
        prompt_version="test-v1",
        input={
            "text": "What should I read next?",
            "memory_citations": [
                {
                    "citation_id": record_id("citation", 1),
                    "assertion_id": record_id("assertion", 1),
                }
            ],
        },
    )


def test_local_route_config_requires_loopback_for_device_and_private_for_lan() -> None:
    with pytest.raises(ValidationError, match="device routes must use a loopback"):
        _config(base_url="http://192.168.1.10:8000/v1")
    with pytest.raises(ValidationError, match="private literal IP"):
        _config(
            base_url="http://models.example.test/v1",
            processing_location="private_network",
        )
    private = _config(
        base_url="http://192.168.1.10:8000/v1",
        processing_location="private_network",
    )
    assert private.processing_location is ProcessingLocation.PRIVATE_NETWORK


@pytest.mark.parametrize(
    "base_url",
    (
        "http://0.0.0.0:8000/v1",
        "http://169.254.169.254:8000/v1",
        "http://224.0.0.1:8000/v1",
        "http://[fe80::1]:8000/v1",
    ),
)
def test_private_route_rejects_unspecified_multicast_and_link_local_endpoints(
    base_url: str,
) -> None:
    with pytest.raises(ValidationError, match="private literal IP"):
        _config(base_url=base_url, processing_location="private_network")


@pytest.mark.parametrize(
    "base_url",
    (
        "http://10.2.3.4:8000/v1",
        "http://100.100.1.2:8000/v1",
        "http://172.20.1.2:8000/v1",
        "http://192.168.1.2:8000/v1",
        "http://[fd00::12]:8000/v1",
    ),
)
def test_private_route_accepts_rfc1918_ula_and_tailscale_endpoints(
    base_url: str,
) -> None:
    config = _config(base_url=base_url, processing_location="private_network")
    assert config.processing_location is ProcessingLocation.PRIVATE_NETWORK


def test_approved_provider_requires_https_and_records_disclosure() -> None:
    with pytest.raises(ValidationError, match="require HTTPS"):
        _config(
            base_url="http://api.example.test/v1",
            processing_location="approved_provider",
        )
    config = _config(
        base_url="https://api.example.test/v1",
        processing_location="approved_provider",
    )
    assert config.registered_route().external_disclosure is True


def test_gateway_invokes_bounded_json_completion_and_accounts_usage(fixed_time) -> None:
    observed: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed["url"] = str(request.url)
        observed["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": (
                                "```json\n"
                                '{"text":"Try a short essay.","citation_ids":[]}\n'
                                "```"
                            )
                        }
                    }
                ],
                "usage": {"prompt_tokens": 120, "completion_tokens": 18},
            },
        )

    config = _config(
        input_cost_gbp_per_million_tokens=1.0,
        output_cost_gbp_per_million_tokens=2.0,
    )
    gateway = OpenAICompatibleModelGateway(
        config,
        clock=lambda: fixed_time,
        id_factory=lambda prefix: record_id(prefix, 1),
        transport=httpx.MockTransport(handler),
    )
    result = gateway.invoke(_request())

    assert observed["url"] == "http://127.0.0.1:11434/v1/chat/completions"
    body = observed["body"]
    assert isinstance(body, dict)
    assert body["model"] == "qwen-test"
    assert body["response_format"] == {"type": "json_object"}
    assert result.output == {"text": "Try a short essay.", "citation_ids": []}
    assert result.input_tokens == 120
    assert result.output_tokens == 18
    assert result.cost_gbp == pytest.approx(0.000156)
    assert result.external_disclosure is False


def test_gateway_health_is_redacted_and_token_file_is_owner_only(tmp_path, fixed_time) -> None:
    token_file = tmp_path / "model-token"
    token_file.write_text("private-test-token", encoding="utf-8")
    token_file.chmod(0o600)
    seen_authorization = ""

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal seen_authorization
        seen_authorization = request.headers.get("Authorization", "")
        return httpx.Response(200, json={"data": []})

    gateway = OpenAICompatibleModelGateway(
        _config(authorization_token_file=token_file),
        clock=lambda: fixed_time,
        transport=httpx.MockTransport(handler),
    )
    health = gateway.health()
    assert health.state is ModelRouteHealthState.HEALTHY
    assert health.reason_code == "model.endpoint_ready"
    assert seen_authorization == "Bearer private-test-token"

    token_file.chmod(0o644)
    unavailable = gateway.health()
    assert unavailable.state is ModelRouteHealthState.UNAVAILABLE
    assert unavailable.reason_code == "model.endpoint_unavailable"


def test_route_config_loader_rejects_non_regular_files_and_accepts_example(tmp_path) -> None:
    directory = tmp_path / "route"
    directory.mkdir()
    with pytest.raises(ValueError, match="regular file"):
        load_openai_compatible_route_config(directory)

    config_file = tmp_path / "route.json"
    config_file.write_text(_config().model_dump_json(), encoding="utf-8")
    loaded = load_openai_compatible_route_config(config_file)
    assert loaded.route_id == "model.local.test"
