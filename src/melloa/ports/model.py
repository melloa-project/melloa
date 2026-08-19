"""Provider-neutral model gateway port."""

from typing import Protocol, runtime_checkable

from melloa.domain.models import (
    ModelGatewayHealth,
    ModelInvocationTarget,
    ModelRequest,
    ModelResult,
    ProcessingLocation,
)


class ModelInvocationError(RuntimeError):
    """A configured model failed after it may have received owner context."""

    def __init__(
        self,
        *,
        provider_id: str,
        model_id: str,
        processing_location: ProcessingLocation,
    ) -> None:
        super().__init__("model invocation failed")
        self.target = ModelInvocationTarget(
            provider_id=provider_id,
            model_id=model_id,
            processing_location=processing_location,
        )
        self.external_disclosure = (
            processing_location is ProcessingLocation.APPROVED_PROVIDER
        )


class ModelGateway(Protocol):
    def invoke(self, request: ModelRequest) -> ModelResult:
        """Execute one bounded model request and return validated untrusted data."""


@runtime_checkable
class HealthCheckingModelGateway(Protocol):
    def health(self) -> ModelGatewayHealth:
        """Return a redacted health observation without owner input."""
