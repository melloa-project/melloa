"""Provider-neutral model gateway port."""

from typing import Protocol, runtime_checkable

from melloa.domain.models import ModelGatewayHealth, ModelRequest, ModelResult


class ModelInvocationError(RuntimeError):
    """A configured model failed after it may have received owner context."""

    def __init__(self, *, external_disclosure: bool) -> None:
        super().__init__("model invocation failed")
        self.external_disclosure = external_disclosure


class ModelGateway(Protocol):
    def invoke(self, request: ModelRequest) -> ModelResult:
        """Execute one bounded model request and return validated untrusted data."""


@runtime_checkable
class HealthCheckingModelGateway(Protocol):
    def health(self) -> ModelGatewayHealth:
        """Return a redacted health observation without owner input."""
