from __future__ import annotations

from datetime import timedelta

import pytest
from pydantic import ValidationError

from melloa.adapters.fakes.model import FakeModelGateway
from melloa.application.routing import (
    DeterministicModelRouter,
    ModelRouteBinding,
    ModelRoutingError,
)
from melloa.domain.classification import Sensitivity
from melloa.domain.models import (
    ModelAttemptOutcome,
    ModelResult,
    ModelRouteAttempt,
    ModelRouteRequest,
    ProcessingLocation,
    RegisteredModelRoute,
)
from tests.conftest import record_id


class FailingModelGateway:
    def __init__(self) -> None:
        self.requests = []

    def invoke(self, request):
        self.requests.append(request)
        raise TimeoutError("synthetic provider timeout")


class MutatingModelGateway:
    def __init__(self, backend, updates) -> None:
        self._backend = backend
        self._updates = updates

    def invoke(self, route_request):
        return self._backend.invoke(route_request).model_copy(update=self._updates)


def route(
    *,
    route_id: str,
    location: ProcessingLocation,
    priority: int,
    external_disclosure: bool,
    cost: float = 0.0,
) -> RegisteredModelRoute:
    return RegisteredModelRoute(
        route_id=route_id,
        provider_id=f"provider.{route_id.rsplit('.', 1)[-1]}",
        model_id=f"{route_id}-v1",
        processing_location=location,
        supported_modalities=frozenset({"text"}),
        quality_profiles=frozenset({"quality.conversation"}),
        allowed_sensitivities=frozenset(Sensitivity),
        provider_retention_policies=frozenset({"retention.no-training"}),
        max_input_tokens=8_192,
        max_output_tokens=2_048,
        estimated_max_cost_gbp=cost,
        reliability=0.99,
        priority=priority,
        external_disclosure=external_disclosure,
    )


def request(*, sensitivity=Sensitivity.PERSONAL, locations=None, cost=1.0):
    return ModelRouteRequest(
        request_id=record_id("request", 1),
        task_type="conversation.owner-reply",
        required_modalities=("text",),
        minimum_quality_profile="quality.conversation",
        sensitivity=sensitivity,
        allowed_processing_locations=(
            frozenset(ProcessingLocation) if locations is None else frozenset(locations)
        ),
        latency_deadline_ms=10_000,
        max_input_tokens=1_024,
        max_output_tokens=256,
        cost_ceiling_gbp=cost,
        provider_retention_policy="retention.no-training",
        minimum_reliability=0.9,
        fallback_route_ids=("model.hosted", "model.local"),
        output_schema_id="schema.conversation-response.v1",
        prompt_version="test-v1",
        input={"text": "synthetic"},
    )


def test_router_falls_back_without_hiding_failed_route_disclosure(fixed_time) -> None:
    hosted = route(
        route_id="model.hosted",
        location=ProcessingLocation.APPROVED_PROVIDER,
        priority=0,
        external_disclosure=True,
        cost=0.2,
    )
    local = route(
        route_id="model.local",
        location=ProcessingLocation.DEVICE,
        priority=1,
        external_disclosure=False,
    )
    failing = FailingModelGateway()
    local_backend = FakeModelGateway(
        {"text": "local fallback"},
        clock=lambda: fixed_time,
        route_id=local.route_id,
        provider_id=local.provider_id,
        model_id=local.model_id,
    )
    router = DeterministicModelRouter(
        (
            ModelRouteBinding(hosted, failing),
            ModelRouteBinding(local, local_backend),
        ),
        clock=lambda: fixed_time,
    )

    result = router.invoke(request())

    assert result.output == {"text": "local fallback"}
    assert result.external_disclosure is True
    assert tuple(attempt.outcome for attempt in result.attempts) == (
        ModelAttemptOutcome.FAILED,
        ModelAttemptOutcome.SUCCEEDED,
    )
    assert result.attempts[0].route_id == "model.hosted"
    assert result.attempts[1].route_id == "model.local"


def test_router_filters_privacy_and_cost_as_hard_constraints(fixed_time) -> None:
    hosted = route(
        route_id="model.hosted",
        location=ProcessingLocation.APPROVED_PROVIDER,
        priority=0,
        external_disclosure=True,
        cost=0.5,
    )
    local = route(
        route_id="model.local",
        location=ProcessingLocation.DEVICE,
        priority=1,
        external_disclosure=False,
    )
    hosted_backend = FailingModelGateway()
    local_backend = FakeModelGateway(
        {"text": "device only"},
        clock=lambda: fixed_time,
        route_id=local.route_id,
        provider_id=local.provider_id,
        model_id=local.model_id,
    )
    router = DeterministicModelRouter(
        (
            ModelRouteBinding(hosted, hosted_backend),
            ModelRouteBinding(local, local_backend),
        ),
        clock=lambda: fixed_time,
    )

    result = router.invoke(
        request(
            sensitivity=Sensitivity.DEVICE_ONLY,
            locations={ProcessingLocation.DEVICE},
            cost=0.0,
        )
    )

    assert result.route_id == "model.local"
    assert result.external_disclosure is False
    assert hosted_backend.requests == []


def test_router_fails_when_no_route_is_eligible(fixed_time) -> None:
    local = route(
        route_id="model.local",
        location=ProcessingLocation.DEVICE,
        priority=0,
        external_disclosure=False,
    )
    router = DeterministicModelRouter(
        (
            ModelRouteBinding(
                local,
                FakeModelGateway(
                    {"text": "unused"},
                    clock=lambda: fixed_time,
                    route_id=local.route_id,
                    provider_id=local.provider_id,
                    model_id=local.model_id,
                ),
            ),
        ),
        clock=lambda: fixed_time,
    )

    with pytest.raises(ModelRoutingError) as captured:
        router.invoke(request(locations={ProcessingLocation.APPROVED_PROVIDER}))
    assert captured.value.reason_code == "model.no_eligible_route"
    assert captured.value.attempts == ()


def test_router_rejects_backend_route_identity_mismatch(fixed_time) -> None:
    local = route(
        route_id="model.local",
        location=ProcessingLocation.DEVICE,
        priority=0,
        external_disclosure=False,
    )
    router = DeterministicModelRouter(
        (
            ModelRouteBinding(
                local,
                FakeModelGateway({"text": "wrong identity"}, clock=lambda: fixed_time),
            ),
        ),
        clock=lambda: fixed_time,
    )

    with pytest.raises(ModelRoutingError) as captured:
        router.invoke(request(locations={ProcessingLocation.DEVICE}))
    assert captured.value.reason_code == "model.all_eligible_routes_failed"
    assert captured.value.attempts[0].error_code == "model.route_failed"


def test_route_request_rejects_duplicate_fallbacks() -> None:
    document = request().model_dump()
    document["fallback_route_ids"] = ("model.local", "model.local")
    with pytest.raises(ValueError, match="fallback route IDs"):
        ModelRouteRequest.model_validate(document)


def test_route_registry_rejects_inconsistent_location_disclosure() -> None:
    local_document = route(
        route_id="model.local",
        location=ProcessingLocation.DEVICE,
        priority=0,
        external_disclosure=False,
    ).model_dump()
    local_document["external_disclosure"] = True
    with pytest.raises(ValidationError, match="device routes"):
        RegisteredModelRoute.model_validate(local_document)

    hosted_document = route(
        route_id="model.hosted",
        location=ProcessingLocation.APPROVED_PROVIDER,
        priority=0,
        external_disclosure=True,
    ).model_dump()
    hosted_document["external_disclosure"] = False
    with pytest.raises(ValidationError, match="approved-provider routes"):
        RegisteredModelRoute.model_validate(hosted_document)


def test_route_attempt_and_result_trace_invariants(fixed_time) -> None:
    successful = ModelRouteAttempt(
        route_id="model.local",
        provider_id="provider.local",
        model_id="local-v1",
        processing_location=ProcessingLocation.DEVICE,
        outcome=ModelAttemptOutcome.SUCCEEDED,
        started_at=fixed_time,
        completed_at=fixed_time,
        external_disclosure=False,
    )
    attempt_document = successful.model_dump()
    attempt_document["completed_at"] = fixed_time - timedelta(seconds=1)
    with pytest.raises(ValidationError, match="cannot complete before"):
        ModelRouteAttempt.model_validate(attempt_document)
    attempt_document = successful.model_dump()
    attempt_document["error_code"] = "model.unexpected"
    with pytest.raises(ValidationError, match="successful model attempt"):
        ModelRouteAttempt.model_validate(attempt_document)
    attempt_document = successful.model_dump()
    attempt_document["outcome"] = ModelAttemptOutcome.FAILED
    with pytest.raises(ValidationError, match="failed model attempt"):
        ModelRouteAttempt.model_validate(attempt_document)

    result = ModelResult(
        result_id=record_id("model_result", 1),
        request_id=record_id("request", 1),
        route_id="model.local",
        provider_id="provider.local",
        model_id="local-v1",
        output={"text": "synthetic"},
        input_tokens=1,
        output_tokens=1,
        cost_gbp=0.0,
        started_at=fixed_time,
        completed_at=fixed_time,
        external_disclosure=False,
        attempts=(successful,),
    )
    result_document = result.model_dump()
    result_document["completed_at"] = fixed_time - timedelta(seconds=1)
    with pytest.raises(ValidationError, match="cannot complete before"):
        ModelResult.model_validate(result_document)

    failed = successful.model_copy(
        update={
            "outcome": ModelAttemptOutcome.FAILED,
            "error_code": "model.route_failed",
        }
    )
    result_document = result.model_dump()
    result_document["attempts"] = (successful, failed)
    with pytest.raises(ValidationError, match="exactly one final"):
        ModelResult.model_validate(result_document)
    result_document = result.model_dump()
    result_document["model_id"] = "different-v1"
    with pytest.raises(ValidationError, match="does not match"):
        ModelResult.model_validate(result_document)
    result_document = result.model_dump()
    result_document["external_disclosure"] = True
    with pytest.raises(ValidationError, match="disclosure"):
        ModelResult.model_validate(result_document)


def test_router_requires_nonempty_unique_registry(fixed_time) -> None:
    with pytest.raises(ValueError, match="at least one"):
        DeterministicModelRouter((), clock=lambda: fixed_time)
    local = route(
        route_id="model.local",
        location=ProcessingLocation.DEVICE,
        priority=0,
        external_disclosure=False,
    )
    backend = FakeModelGateway(
        {"text": "synthetic"},
        clock=lambda: fixed_time,
        route_id=local.route_id,
        provider_id=local.provider_id,
        model_id=local.model_id,
    )
    with pytest.raises(ValueError, match="unique"):
        DeterministicModelRouter(
            (ModelRouteBinding(local, backend), ModelRouteBinding(local, backend)),
            clock=lambda: fixed_time,
        )


@pytest.mark.parametrize(
    "updates",
    [
        {"request_id": record_id("request", 2)},
        {"cost_gbp": 2.0},
        {"input_tokens": 2_000},
        {"output_tokens": 300},
        {"external_disclosure": True},
    ],
)
def test_router_rejects_backend_results_outside_request_contract(fixed_time, updates) -> None:
    local = route(
        route_id="model.local",
        location=ProcessingLocation.DEVICE,
        priority=0,
        external_disclosure=False,
    )
    backend = FakeModelGateway(
        {"text": "synthetic"},
        clock=lambda: fixed_time,
        route_id=local.route_id,
        provider_id=local.provider_id,
        model_id=local.model_id,
    )
    router = DeterministicModelRouter(
        (ModelRouteBinding(local, MutatingModelGateway(backend, updates)),),
        clock=lambda: fixed_time,
    )
    route_request = request(locations={ProcessingLocation.DEVICE})
    route_request = route_request.model_copy(update={"fallback_route_ids": ("model.local",)})

    with pytest.raises(ModelRoutingError) as captured:
        router.invoke(route_request)
    assert captured.value.reason_code == "model.all_eligible_routes_failed"


def test_router_rejects_backend_latency_violation(fixed_time) -> None:
    local = route(
        route_id="model.local",
        location=ProcessingLocation.DEVICE,
        priority=0,
        external_disclosure=False,
    )
    backend = FakeModelGateway(
        {"text": "synthetic"},
        clock=lambda: fixed_time,
        route_id=local.route_id,
        provider_id=local.provider_id,
        model_id=local.model_id,
    )
    router = DeterministicModelRouter(
        (
            ModelRouteBinding(
                local,
                MutatingModelGateway(
                    backend,
                    {"completed_at": fixed_time + timedelta(seconds=11)},
                ),
            ),
        ),
        clock=lambda: fixed_time,
    )
    route_request = request(locations={ProcessingLocation.DEVICE})
    route_request = route_request.model_copy(update={"fallback_route_ids": ("model.local",)})

    with pytest.raises(ModelRoutingError):
        router.invoke(route_request)
