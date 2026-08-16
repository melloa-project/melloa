"""Provider-neutral model gateway adapters."""

from melloa.adapters.models.codex_cli import (
    CodexCliInvocationError,
    CodexCliModelGateway,
    CodexCliRouteConfig,
    load_codex_cli_route_config,
)
from melloa.adapters.models.openai_compatible import (
    OpenAICompatibleModelGateway,
    OpenAICompatibleRouteConfig,
    load_openai_compatible_route_config,
)

__all__ = [
    "CodexCliInvocationError",
    "CodexCliModelGateway",
    "CodexCliRouteConfig",
    "OpenAICompatibleModelGateway",
    "OpenAICompatibleRouteConfig",
    "load_codex_cli_route_config",
    "load_openai_compatible_route_config",
]
