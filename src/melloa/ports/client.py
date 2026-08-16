"""Channel-neutral client adapter port."""

from typing import Protocol

from melloa.domain.base import JsonObject
from melloa.domain.conversation import ConversationMessage, DeliveryAttempt
from melloa.domain.delivery import AuthorizedClientDelivery


class ClientDeliveryError(RuntimeError):
    """A client adapter failed without exposing raw provider details."""

    def __init__(self, reason_code: str, *, retryable: bool) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code
        self.retryable = retryable


class TransientClientDeliveryError(ClientDeliveryError):
    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code, retryable=True)


class PermanentClientDeliveryError(ClientDeliveryError):
    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code, retryable=False)


class ClientAdapter(Protocol):
    def receive(self) -> tuple[ConversationMessage, ...]:
        """Return normalized inbound messages durably accepted by the adapter."""

    def send(self, delivery: AuthorizedClientDelivery) -> DeliveryAttempt:
        """Send only an exact message-bound action allowed by deterministic policy."""

    def capabilities(self) -> JsonObject:
        """Describe transport limits and security properties."""

    def health(self) -> JsonObject:
        """Return non-sensitive adapter health."""
