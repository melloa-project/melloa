from __future__ import annotations

import json

import httpx
import pytest
from pydantic import ValidationError

from melloa.adapters.models.openai_compatible import (
    OpenAIAPIStyle,
    OpenAICompatibleModelConfig,
    OpenAICompatibleModelGateway,
    load_openai_compatible_model_config,
)
from melloa.domain.classification import Sensitivity
from melloa.domain.models import (
    ModelHealthState,
    ModelRequest,
    ProcessingLocation,
)
from melloa.ports.model import ModelInvocationError
from tests.conftest import record_id


def _config(**overrides) -> OpenAICompatibleModelConfig:
    document = {
        "display_name": "Local test model",
        "provider_id": "provider.local-test",
        "model_id": "qwen-test",
        "base_url": "http://127.0.0.1:11434/v1",
        "processing_location": "device",
    }
    document.update(overrides)
    return OpenAICompatibleModelConfig.model_validate(document)


def _request() -> ModelRequest:
    return ModelRequest(
        request_id=record_id("request", 1),
        sensitivity=Sensitivity.PERSONAL,
        allowed_processing_locations=frozenset({ProcessingLocation.DEVICE}),
        latency_deadline_ms=10_000,
        max_input_tokens=4_096,
        max_output_tokens=512,
        cost_ceiling_gbp=1.0,
        prompt_version="test-v1",
        input={
            "text": "What should I read next?",
            "recent_conversation": [
                {
                    "message_id": record_id("message", 1),
                    "role": "owner",
                    "text": "I enjoyed the previous essay.",
                },
                {
                    "message_id": record_id("message", 2),
                    "role": "melli",
                    "text": "The shorter one suited you.",
                },
            ],
            "memory_citations": [
                {
                    "citation_id": record_id("citation", 1),
                    "assertion_id": record_id("assertion", 1),
                }
            ],
        },
    )


def test_local_model_config_requires_loopback_for_device_and_private_for_lan() -> None:
    with pytest.raises(ValidationError, match="on-device models must use a loopback"):
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
def test_private_model_rejects_unspecified_multicast_and_link_local_endpoints(
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
def test_private_model_accepts_rfc1918_ula_and_tailscale_endpoints(
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
    assert config.processing_location is ProcessingLocation.APPROVED_PROVIDER


def test_gateway_rejects_disallowed_location_sensitivity_and_cost_before_calling() -> None:
    def unexpected_call(_request: httpx.Request) -> httpx.Response:
        pytest.fail("a rejected model request must not reach the configured endpoint")

    transport = httpx.MockTransport(unexpected_call)
    location_gateway = OpenAICompatibleModelGateway(
        _config(
            base_url="http://192.168.1.10:8000/v1",
            processing_location="private_network",
        ),
        transport=transport,
    )
    with pytest.raises(ValueError, match="location is not allowed"):
        location_gateway.invoke(_request())

    sensitivity_gateway = OpenAICompatibleModelGateway(
        _config(allowed_sensitivities=["public"]),
        transport=transport,
    )
    with pytest.raises(ValueError, match="not approved for this message sensitivity"):
        sensitivity_gateway.invoke(_request())

    cost_gateway = OpenAICompatibleModelGateway(
        _config(estimated_max_cost_gbp=2.0),
        transport=transport,
    )
    with pytest.raises(ValueError, match="configured model cost exceeds"):
        cost_gateway.invoke(_request())


def test_failed_approved_provider_call_reports_possible_disclosure(fixed_time) -> None:
    def unavailable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("provider unavailable", request=request)

    gateway = OpenAICompatibleModelGateway(
        _config(
            base_url="https://api.example.test/v1",
            processing_location="approved_provider",
        ),
        clock=lambda: fixed_time,
        transport=httpx.MockTransport(unavailable),
    )
    approved_request = _request().model_copy(
        update={
            "allowed_processing_locations": frozenset(
                {ProcessingLocation.APPROVED_PROVIDER}
            )
        }
    )

    with pytest.raises(ModelInvocationError) as failure:
        gateway.invoke(approved_request)

    assert failure.value.external_disclosure is True
    assert failure.value.target.provider_id == "provider.local-test"
    assert failure.value.target.model_id == "qwen-test"
    assert (
        failure.value.target.processing_location
        is ProcessingLocation.APPROVED_PROVIDER
    )


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
    assert body["store"] is False
    assert body["response_format"] == {"type": "json_object"}
    prompt = json.loads(body["messages"][1]["content"])
    assert prompt["owner_message"] == "What should I read next?"
    assert prompt["recent_conversation"] == [
        {
            "message_id": record_id("message", 1),
            "role": "owner",
            "text": "I enjoyed the previous essay.",
        },
        {
            "message_id": record_id("message", 2),
            "role": "melli",
            "text": "The shorter one suited you.",
        },
    ]
    assert result.output == {"text": "Try a short essay.", "citation_ids": []}
    assert result.input_tokens == 120
    assert result.output_tokens == 18
    assert result.cost_gbp == pytest.approx(0.000156)
    assert result.external_disclosure is False


def test_gateway_invokes_bounded_responses_api_and_accounts_usage(fixed_time) -> None:
    observed: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed["url"] = str(request.url)
        observed["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "output": [
                    {"type": "reasoning", "summary": []},
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [
                            {
                                "type": "output_text",
                                "text": (
                                    '{"text":"Try a considered essay.",'
                                    '"citation_ids":[]}'
                                ),
                            }
                        ],
                    },
                ],
                "usage": {"input_tokens": 140, "output_tokens": 22},
            },
        )

    config = _config(
        api_style="responses",
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

    assert config.api_style is OpenAIAPIStyle.RESPONSES
    assert observed["url"] == "http://127.0.0.1:11434/v1/responses"
    body = observed["body"]
    assert isinstance(body, dict)
    assert body["model"] == "qwen-test"
    assert body["store"] is False
    assert body["max_output_tokens"] == 512
    assert "instructions" in body
    assert "temperature" not in body
    assert body["text"] == {
        "format": {
            "type": "json_schema",
            "name": "melli_conversation_response",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "citation_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": ["text", "citation_ids"],
                "additionalProperties": False,
            },
        }
    }
    prompt = json.loads(body["input"])
    assert prompt["owner_message"] == "What should I read next?"
    assert result.output == {
        "text": "Try a considered essay.",
        "citation_ids": [],
    }
    assert result.input_tokens == 140
    assert result.output_tokens == 22
    assert result.cost_gbp == pytest.approx(0.000184)


@pytest.mark.parametrize(
    "document",
    (
        {},
        {"output": []},
        {"output": [{"type": "reasoning"}]},
        {
            "output": [
                {"type": "message", "content": []},
                {"type": "message", "content": []},
            ]
        },
        {"output": [{"type": "message", "content": []}]},
        {
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "refusal", "refusal": "No"}],
                }
            ]
        },
    ),
)
def test_responses_gateway_rejects_missing_or_ambiguous_text(document, fixed_time) -> None:
    gateway = OpenAICompatibleModelGateway(
        _config(api_style="responses"),
        clock=lambda: fixed_time,
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(200, json=document)
        ),
    )

    with pytest.raises(ModelInvocationError):
        gateway.invoke(_request())


def test_gateway_health_requires_exact_configured_model_and_redacts_failures(
    tmp_path, fixed_time
) -> None:
    token_file = tmp_path / "model-token"
    token_file.write_text("private-test-token", encoding="utf-8")
    token_file.chmod(0o600)
    seen_authorization = ""

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal seen_authorization
        seen_authorization = request.headers.get("Authorization", "")
        return httpx.Response(200, json={"data": [{"id": "qwen-test"}]})

    gateway = OpenAICompatibleModelGateway(
        _config(authorization_token_file=token_file),
        clock=lambda: fixed_time,
        transport=httpx.MockTransport(handler),
    )
    health = gateway.health()
    assert health.state is ModelHealthState.HEALTHY
    assert health.reason_code == "model.endpoint_ready"
    assert seen_authorization == "Bearer private-test-token"

    token_file.chmod(0o644)
    unavailable = gateway.health()
    assert unavailable.state is ModelHealthState.UNAVAILABLE
    assert unavailable.reason_code == "model.endpoint_unavailable"


@pytest.mark.parametrize(
    "document",
    (
        {},
        {"data": []},
        {"data": "qwen-test"},
        {"data": [{}]},
        {"data": [{"id": 7}]},
        {"data": [{"id": ""}]},
    ),
)
def test_gateway_health_rejects_absent_empty_or_malformed_models_data(document, fixed_time) -> None:
    gateway = OpenAICompatibleModelGateway(
        _config(),
        clock=lambda: fixed_time,
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=document)),
    )

    health = gateway.health()

    assert health.state is ModelHealthState.UNAVAILABLE
    assert health.reason_code == "model.models_response_invalid"


@pytest.mark.parametrize(
    ("available_ids", "expected_state", "expected_reason"),
    (
        (
            ["qwen-test-v2", "QWEN-TEST"],
            ModelHealthState.UNAVAILABLE,
            "model.configured_model_unavailable",
        ),
        (
            ["other-model", "qwen-test"],
            ModelHealthState.HEALTHY,
            "model.endpoint_ready",
        ),
    ),
)
def test_gateway_health_uses_an_exact_model_id_match(
    available_ids, expected_state, expected_reason, fixed_time
) -> None:
    gateway = OpenAICompatibleModelGateway(
        _config(),
        clock=lambda: fixed_time,
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                json={"data": [{"id": model_id} for model_id in available_ids]},
            )
        ),
    )

    health = gateway.health()

    assert health.state is expected_state
    assert health.reason_code == expected_reason


def test_gateway_health_rejects_moving_alias_for_pinned_instruct_model(fixed_time) -> None:
    gateway = OpenAICompatibleModelGateway(
        _config(model_id="qwen3:4b-instruct-2507-q4_K_M"),
        clock=lambda: fixed_time,
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                json={"data": [{"id": "qwen3:4b"}]},
            )
        ),
    )

    health = gateway.health()

    assert health.state is ModelHealthState.UNAVAILABLE
    assert health.reason_code == "model.configured_model_unavailable"


def test_model_config_loader_rejects_non_regular_files_and_accepts_example(tmp_path) -> None:
    directory = tmp_path / "model"
    directory.mkdir()
    with pytest.raises(ValueError, match="regular file"):
        load_openai_compatible_model_config(directory)

    config_file = tmp_path / "model.json"
    config_file.write_text(_config().model_dump_json(), encoding="utf-8")
    loaded = load_openai_compatible_model_config(config_file)
    assert loaded.model_id == "qwen-test"
