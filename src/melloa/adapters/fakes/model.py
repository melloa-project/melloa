"""Deterministic model adapter with no credentials or external disclosure."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from melloa.domain.base import JsonObject, new_record_id, utc_now
from melloa.domain.models import (
    ModelGatewayHealth,
    ModelResult,
    ModelRouteHealthState,
    ModelRouteRequest,
    ProcessingLocation,
)


class FakeModelGateway:
    def __init__(
        self,
        response: JsonObject | Callable[[ModelRouteRequest], JsonObject],
        *,
        clock: Callable[[], datetime] = utc_now,
        id_factory: Callable[[str], str] = new_record_id,
        route_id: str = "model.fake.deterministic",
        provider_id: str = "provider.synthetic",
        model_id: str = "deterministic-fixture-v1",
        external_disclosure: bool = False,
    ) -> None:
        self._response = response
        self._clock = clock
        self._id_factory = id_factory
        self._route_id = route_id
        self._provider_id = provider_id
        self._model_id = model_id
        self._external_disclosure = external_disclosure
        self.requests: list[ModelRouteRequest] = []

    def invoke(self, request: ModelRouteRequest) -> ModelResult:
        if ProcessingLocation.DEVICE not in request.allowed_processing_locations:
            raise ValueError("the deterministic fake requires device processing eligibility")
        self.requests.append(request)
        started_at = self._clock()
        output = self._response(request) if callable(self._response) else self._response
        return ModelResult(
            result_id=self._id_factory("model_result"),
            request_id=request.request_id,
            route_id=self._route_id,
            provider_id=self._provider_id,
            model_id=self._model_id,
            output=output,
            input_tokens=0,
            output_tokens=0,
            cost_gbp=0.0,
            started_at=started_at,
            completed_at=self._clock(),
            external_disclosure=self._external_disclosure,
        )

    def health(self) -> ModelGatewayHealth:
        return ModelGatewayHealth(
            state=ModelRouteHealthState.HEALTHY,
            checked_at=self._clock(),
            latency_ms=0,
            reason_code="model.synthetic_ready",
        )
