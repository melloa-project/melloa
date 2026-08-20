"""Two explicit model routes with no implicit fallback."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from melloa.domain.base import utc_now
from melloa.domain.models import (
    ModelGatewayHealth,
    ModelHealthState,
    ModelRequest,
    ModelResult,
    ModelRoute,
)
from melloa.ports.model import (
    HealthCheckingModelGateway,
    ModelGateway,
    ModelInvocationError,
)


class RoutedModelGateway:
    def __init__(
        self,
        *,
        capable: ModelGateway,
        economy: ModelGateway,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        if capable is economy:
            raise ValueError("capable and economy routes must use distinct gateways")
        self._gateways = {
            ModelRoute.CAPABLE: capable,
            ModelRoute.ECONOMY: economy,
        }
        self._clock = clock

    def invoke(self, request: ModelRequest) -> ModelResult:
        try:
            result = self._gateways[request.route].invoke(request)
        except ModelInvocationError as error:
            if error.target.route is not request.route:
                raise ValueError("model route returned conflicting provenance") from error
            raise
        if result.request_id != request.request_id or result.route is not request.route:
            raise ValueError("model route returned conflicting provenance")
        return result

    def route_health(self, route: ModelRoute) -> ModelGatewayHealth:
        gateway = self._gateways[route]
        if not isinstance(gateway, HealthCheckingModelGateway):
            return ModelGatewayHealth(
                state=ModelHealthState.UNAVAILABLE,
                checked_at=self._clock(),
                latency_ms=None,
                reason_code="model.health_not_supported",
            )
        return gateway.health()

    def health(self) -> ModelGatewayHealth:
        capable = self.route_health(ModelRoute.CAPABLE)
        economy = self.route_health(ModelRoute.ECONOMY)
        unavailable_route = next(
            (
                route
                for route, health in (
                    (ModelRoute.CAPABLE, capable),
                    (ModelRoute.ECONOMY, economy),
                )
                if health.state is not ModelHealthState.HEALTHY
            ),
            None,
        )
        return ModelGatewayHealth(
            state=(
                ModelHealthState.HEALTHY
                if unavailable_route is None
                else ModelHealthState.UNAVAILABLE
            ),
            checked_at=max(capable.checked_at, economy.checked_at),
            latency_ms=_maximum_latency(capable, economy),
            reason_code=(
                "model.routes_ready"
                if unavailable_route is None
                else f"model.{unavailable_route.value}_route_unavailable"
            ),
        )


def _maximum_latency(*health: ModelGatewayHealth) -> int | None:
    latencies = [item.latency_ms for item in health if item.latency_ms is not None]
    return max(latencies) if latencies else None


__all__ = ["RoutedModelGateway"]
