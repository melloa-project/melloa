"""Provider-neutral model gateway port."""

from typing import Protocol, runtime_checkable

from melloa.domain.models import ModelGatewayHealth, ModelResult, ModelRouteRequest


class ModelGateway(Protocol):
    def invoke(self, request: ModelRouteRequest) -> ModelResult:
        """Execute one bounded route request and return validated untrusted data."""


@runtime_checkable
class HealthCheckingModelGateway(Protocol):
    def health(self) -> ModelGatewayHealth:
        """Return a redacted route-health observation without model input."""
