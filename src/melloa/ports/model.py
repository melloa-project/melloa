"""Provider-neutral model gateway port."""

from typing import Protocol

from melloa.domain.models import ModelResult, ModelRouteRequest


class ModelGateway(Protocol):
    def invoke(self, request: ModelRouteRequest) -> ModelResult:
        """Execute one bounded route request and return validated untrusted data."""
