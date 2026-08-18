"""Usable process-local MVP assembly with configured provider-neutral routes."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from melloa.adapters.models.codex_cli import CodexCliModelGateway, CodexCliRouteConfig
from melloa.adapters.models.openai_compatible import (
    OpenAICompatibleModelGateway,
    OpenAICompatibleRouteConfig,
)
from melloa.adapters.telegram import (
    TelegramBotApiClientAdapter,
    TelegramBotApiConfig,
    TelegramBotApiPairingChallengePublisher,
    TelegramBotApiPairingCodeIssuer,
    TelegramBotApiUpdateSource,
    normalized_telegram_api_origin,
)
from melloa.application.conversation import ConversationRoutePolicy
from melloa.application.routing import ModelRouteBinding
from melloa.apps.synthetic import (
    DurableRuntimeStores,
    SyntheticRuntime,
    build_synthetic_runtime,
)
from melloa.domain.base import new_record_id, utc_now
from melloa.domain.models import ModelRouteKind, ProcessingLocation
from melloa.ports.guardian import GuardianStatusReader
from melloa.release import CURRENT_RELEASE


def build_mvp_runtime(
    guardian_reader: GuardianStatusReader,
    bootstrap_token: str,
    route_configs: tuple[OpenAICompatibleRouteConfig, ...] = (),
    telegram_config: TelegramBotApiConfig | None = None,
    *,
    cli_agent_route_configs: tuple[CodexCliRouteConfig, ...] = (),
    durable_stores: DurableRuntimeStores | None = None,
    clock: Callable[[], datetime] = utc_now,
    id_factory: Callable[[str], str] = new_record_id,
    telegram_worker_interval: float = 1.0,
) -> SyntheticRuntime:
    supplied_route_ids = (
        *(config.route_id for config in route_configs),
        *(config.route_id for config in cli_agent_route_configs),
    )
    if len(set(supplied_route_ids)) != len(supplied_route_ids):
        raise ValueError("configured model route IDs must be unique")
    local_http_configs = tuple(
        config
        for config in route_configs
        if config.processing_location is not ProcessingLocation.APPROVED_PROVIDER
    )
    approved_provider_http_configs = tuple(
        config
        for config in route_configs
        if config.processing_location is ProcessingLocation.APPROVED_PROVIDER
    )
    ordered_http_configs = (*local_http_configs, *approved_provider_http_configs)
    configured_route_ids = (
        *(config.route_id for config in local_http_configs),
        *(config.route_id for config in cli_agent_route_configs),
        *(config.route_id for config in approved_provider_http_configs),
    )
    openai_compatible_bindings = tuple(
        ModelRouteBinding(
            route=config.registered_route(),
            backend=OpenAICompatibleModelGateway(
                config,
                clock=clock,
                id_factory=id_factory,
            ),
            display_name=config.display_name,
            route_kind=ModelRouteKind.OPENAI_COMPATIBLE,
            timeout_ms=config.timeout_ms,
        )
        for config in ordered_http_configs
    )
    cli_agent_bindings = tuple(
        ModelRouteBinding(
            route=config.registered_route(),
            backend=CodexCliModelGateway(
                config,
                clock=clock,
                id_factory=id_factory,
            ),
            display_name=config.display_name,
            route_kind=ModelRouteKind.CLI_AGENT,
            timeout_ms=config.timeout_ms,
        )
        for config in cli_agent_route_configs
    )
    local_http_binding_count = len(local_http_configs)
    bindings = (
        *openai_compatible_bindings[:local_http_binding_count],
        *cli_agent_bindings,
        *openai_compatible_bindings[local_http_binding_count:],
    )
    configured_timeouts = (
        *(config.timeout_ms for config in route_configs),
        *(config.timeout_ms for config in cli_agent_route_configs),
    )
    configured_cost_ceilings = (
        *(config.estimated_max_cost_gbp for config in route_configs),
        *(config.estimated_max_cost_gbp for config in cli_agent_route_configs),
    )
    route_policy = ConversationRoutePolicy(
        minimum_quality_profile="quality.conversation",
        latency_deadline_ms=max(
            configured_timeouts,
            default=30_000,
        ),
        max_input_tokens=4_096,
        max_output_tokens=1_024,
        cost_ceiling_gbp=max(
            configured_cost_ceilings,
            default=0.0,
        ),
        provider_retention_policy="retention.no-training",
        minimum_reliability=0.0,
        fallback_route_ids=(*configured_route_ids, "model.fake.deterministic"),
        prompt_version="mvp-conversation-v1",
    )
    telegram_source = (
        None
        if telegram_config is None
        else TelegramBotApiUpdateSource(telegram_config, clock=clock)
    )
    telegram_challenge_publisher = (
        None
        if telegram_config is None
        else TelegramBotApiPairingChallengePublisher(telegram_config, clock=clock)
    )
    return build_synthetic_runtime(
        guardian_reader,
        bootstrap_token,
        clock=clock,
        id_factory=id_factory,
        configured_model_bindings=bindings,
        conversation_route_policy=route_policy,
        runtime_version=CURRENT_RELEASE.runtime_identifier,
        telegram_worker_interval=telegram_worker_interval,
        telegram_adapter_id=(
            "client.telegram.synthetic"
            if telegram_config is None
            else telegram_config.adapter_id
        ),
        telegram_source=telegram_source,
        telegram_challenge_publisher=telegram_challenge_publisher,
        telegram_code_issuer=(
            None if telegram_config is None else TelegramBotApiPairingCodeIssuer(telegram_config)
        ),
        telegram_delivery_adapter_factory=(
            None
            if telegram_config is None
            else lambda pairing_service: TelegramBotApiClientAdapter(
                telegram_config,
                pairing_service.pairing_for_delivery,
                clock=clock,
                id_factory=id_factory,
            )
        ),
        telegram_external_destination=(
            "synthetic:owner"
            if telegram_config is None
            else normalized_telegram_api_origin(telegram_config)
        ),
        telegram_poll_timeout_seconds=1 if telegram_config is None else 30,
        telegram_thread_title="Telegram owner conversation",
        durable_stores=durable_stores,
    )
