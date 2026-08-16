"""Deterministic model routing with hard privacy, retention, cost, and quality filters."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from melloa.domain.base import canonical_json_bytes, utc_now
from melloa.domain.models import (
    ModelAttemptOutcome,
    ModelResult,
    ModelRouteAttempt,
    ModelRouteRequest,
    RegisteredModelRoute,
)
from melloa.ports.model import ModelGateway


class ModelRoutingError(RuntimeError):
    def __init__(self, reason_code: str, attempts: tuple[ModelRouteAttempt, ...]) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code
        self.attempts = attempts


@dataclass(frozen=True)
class ModelRouteBinding:
    route: RegisteredModelRoute
    backend: ModelGateway


class DeterministicModelRouter:
    def __init__(
        self,
        bindings: tuple[ModelRouteBinding, ...],
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        if not bindings:
            raise ValueError("at least one model route is required")
        route_ids = tuple(binding.route.route_id for binding in bindings)
        if len(set(route_ids)) != len(route_ids):
            raise ValueError("model route IDs must be unique")
        self._bindings = bindings
        self._clock = clock

    def invoke(self, request: ModelRouteRequest) -> ModelResult:
        attempts: list[ModelRouteAttempt] = []
        for binding in self._eligible_bindings(request):
            route = binding.route
            started_at = self._clock()
            try:
                result = binding.backend.invoke(request)
                self._validate_backend_result(request, route, result)
            except Exception:
                attempts.append(
                    self._attempt(
                        route,
                        ModelAttemptOutcome.FAILED,
                        started_at,
                        error_code="model.route_failed",
                    )
                )
                continue
            attempts.append(
                self._attempt(route, ModelAttemptOutcome.SUCCEEDED, started_at)
            )
            document = result.model_dump(mode="json")
            document["attempts"] = [attempt.model_dump(mode="json") for attempt in attempts]
            document["external_disclosure"] = any(
                attempt.external_disclosure for attempt in attempts
            )
            return ModelResult.model_validate_json(canonical_json_bytes(document))
        reason = "model.all_eligible_routes_failed" if attempts else "model.no_eligible_route"
        raise ModelRoutingError(reason, tuple(attempts))

    def _eligible_bindings(
        self,
        request: ModelRouteRequest,
    ) -> tuple[ModelRouteBinding, ...]:
        preference = {
            route_id: index for index, route_id in enumerate(request.fallback_route_ids)
        }
        eligible = tuple(
            binding
            for binding in self._bindings
            if self._eligible(request, binding.route)
            and (not preference or binding.route.route_id in preference)
        )
        return tuple(
            sorted(
                eligible,
                key=lambda binding: (
                    preference.get(binding.route.route_id, binding.route.priority),
                    binding.route.priority,
                    binding.route.route_id,
                ),
            )
        )

    @staticmethod
    def _eligible(request: ModelRouteRequest, route: RegisteredModelRoute) -> bool:
        return (
            set(request.required_modalities) <= route.supported_modalities
            and request.minimum_quality_profile in route.quality_profiles
            and request.sensitivity in route.allowed_sensitivities
            and route.processing_location in request.allowed_processing_locations
            and request.provider_retention_policy in route.provider_retention_policies
            and request.max_input_tokens <= route.max_input_tokens
            and request.max_output_tokens <= route.max_output_tokens
            and route.estimated_max_cost_gbp <= request.cost_ceiling_gbp
            and route.reliability >= request.minimum_reliability
        )

    @staticmethod
    def _validate_backend_result(
        request: ModelRouteRequest,
        route: RegisteredModelRoute,
        result: ModelResult,
    ) -> None:
        if result.request_id != request.request_id:
            raise ValueError("model backend returned a result for another request")
        if (result.route_id, result.provider_id, result.model_id) != (
            route.route_id,
            route.provider_id,
            route.model_id,
        ):
            raise ValueError("model backend result does not match its registered route")
        if result.attempts:
            raise ValueError("model backend cannot author router attempt records")
        if result.cost_gbp > request.cost_ceiling_gbp:
            raise ValueError("model backend exceeded the request cost ceiling")
        if result.input_tokens > request.max_input_tokens:
            raise ValueError("model backend exceeded the input-token ceiling")
        if result.output_tokens > request.max_output_tokens:
            raise ValueError("model backend exceeded the output-token ceiling")
        elapsed_ms = (result.completed_at - result.started_at).total_seconds() * 1000
        if elapsed_ms > request.latency_deadline_ms:
            raise ValueError("model backend exceeded the latency deadline")
        if result.external_disclosure != route.external_disclosure:
            raise ValueError("model backend disclosure does not match its registered route")

    def _attempt(
        self,
        route: RegisteredModelRoute,
        outcome: ModelAttemptOutcome,
        started_at: datetime,
        *,
        error_code: str | None = None,
    ) -> ModelRouteAttempt:
        return ModelRouteAttempt(
            route_id=route.route_id,
            provider_id=route.provider_id,
            model_id=route.model_id,
            processing_location=route.processing_location,
            outcome=outcome,
            started_at=started_at,
            completed_at=max(self._clock(), started_at),
            external_disclosure=route.external_disclosure,
            error_code=error_code,
        )
