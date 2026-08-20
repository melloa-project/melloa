from __future__ import annotations

import pytest

from melloa.adapters.fakes.model import FakeModelGateway
from melloa.adapters.models.routed import RoutedModelGateway
from melloa.domain.classification import Sensitivity
from melloa.domain.models import (
    ModelHealthState,
    ModelRequest,
    ModelRoute,
    ProcessingLocation,
)
from melloa.ports.model import ModelInvocationError
from tests.conftest import record_id


def _request(route: ModelRoute) -> ModelRequest:
    return ModelRequest(
        request_id=record_id("request", 1),
        route=route,
        sensitivity=Sensitivity.PERSONAL,
        allowed_processing_locations=frozenset({ProcessingLocation.DEVICE}),
        latency_deadline_ms=10_000,
        max_input_tokens=4_096,
        max_output_tokens=512,
        cost_ceiling_gbp=1.0,
        prompt_version="test-v1",
        input={},
    )


def test_routes_only_to_the_explicit_target_and_preserves_provenance(fixed_time) -> None:
    capable = FakeModelGateway(
        {"text": "capable", "citation_ids": []},
        clock=lambda: fixed_time,
        model_id="capable-test",
    )
    economy = FakeModelGateway(
        {"text": "economy", "citation_ids": []},
        clock=lambda: fixed_time,
        model_id="economy-test",
    )
    gateway = RoutedModelGateway(
        capable=capable,
        economy=economy,
        clock=lambda: fixed_time,
    )

    capable_result = gateway.invoke(_request(ModelRoute.CAPABLE))
    economy_result = gateway.invoke(_request(ModelRoute.ECONOMY))

    assert [request.route for request in capable.requests] == [ModelRoute.CAPABLE]
    assert [request.route for request in economy.requests] == [ModelRoute.ECONOMY]
    assert capable_result.route is ModelRoute.CAPABLE
    assert capable_result.model_id == "capable-test"
    assert economy_result.route is ModelRoute.ECONOMY
    assert economy_result.model_id == "economy-test"


def test_route_health_requires_both_explicit_targets(fixed_time) -> None:
    capable = FakeModelGateway({}, clock=lambda: fixed_time)
    economy = FakeModelGateway({}, clock=lambda: fixed_time)
    gateway = RoutedModelGateway(
        capable=capable,
        economy=economy,
        clock=lambda: fixed_time,
    )

    health = gateway.health()

    assert health.state is ModelHealthState.HEALTHY
    assert health.reason_code == "model.routes_ready"
    assert health.checked_at == fixed_time


def test_capable_failure_never_falls_back_to_economy(fixed_time) -> None:
    def unavailable(_request: ModelRequest):
        raise TimeoutError("synthetic capable outage")

    capable = FakeModelGateway(unavailable, clock=lambda: fixed_time)
    economy = FakeModelGateway(
        {"text": "economy", "citation_ids": []},
        clock=lambda: fixed_time,
    )
    gateway = RoutedModelGateway(
        capable=capable,
        economy=economy,
        clock=lambda: fixed_time,
    )

    with pytest.raises(TimeoutError, match="capable outage"):
        gateway.invoke(_request(ModelRoute.CAPABLE))

    assert [request.route for request in capable.requests] == [ModelRoute.CAPABLE]
    assert economy.requests == []


def test_route_rejects_conflicting_failure_provenance(fixed_time) -> None:
    def conflicting(_request: ModelRequest):
        raise ModelInvocationError(
            provider_id="provider.conflicting",
            model_id="conflicting-v1",
            processing_location=ProcessingLocation.DEVICE,
            route=ModelRoute.ECONOMY,
        )

    gateway = RoutedModelGateway(
        capable=FakeModelGateway(conflicting, clock=lambda: fixed_time),
        economy=FakeModelGateway({}, clock=lambda: fixed_time),
        clock=lambda: fixed_time,
    )

    with pytest.raises(ValueError, match="conflicting provenance"):
        gateway.invoke(_request(ModelRoute.CAPABLE))


def test_routes_must_not_alias_one_gateway() -> None:
    gateway = FakeModelGateway({})

    with pytest.raises(
        ValueError,
        match="capable and economy routes must use distinct gateways",
    ):
        RoutedModelGateway(capable=gateway, economy=gateway)
