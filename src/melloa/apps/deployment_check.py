"""Read-only pre-activation checks for the real owner integrations."""

from __future__ import annotations

import asyncio
import os
import stat
from pathlib import Path
from typing import Any

from melloa.adapters.guardian.file import FileGuardianStatusReader
from melloa.adapters.models.openai_compatible import (
    OpenAICompatibleModelConfig,
    OpenAICompatibleModelGateway,
    load_openai_compatible_model_config,
)
from melloa.adapters.models.routed import ModelRouteConfigs
from melloa.adapters.telegram import (
    TelegramBotClient,
    TelegramBotIdentity,
    TelegramChat,
    TelegramOwnerConfig,
)
from melloa.domain.classification import Sensitivity
from melloa.domain.models import ModelGatewayHealth, ModelHealthState

_MODEL_CREDENTIAL_ROOT = Path("/run/melloa/model-credentials")
_MAX_PRIVATE_FILE_BYTES = 65_536


class DeploymentCheckError(RuntimeError):
    """A redacted, owner-actionable activation prerequisite failure."""


def _read_private_text(
    path: Path,
    *,
    label: str,
    minimum: int = 1,
    maximum: int = _MAX_PRIVATE_FILE_BYTES,
) -> str:
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    except OSError as error:
        raise DeploymentCheckError(f"{label} is unavailable") from error
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or metadata.st_mode & 0o077
            or not metadata.st_mode & stat.S_IRUSR
            or not minimum <= metadata.st_size <= maximum
        ):
            raise DeploymentCheckError(f"{label} is not a private owner-readable file")
        document = os.read(descriptor, maximum + 1)
    finally:
        os.close(descriptor)
    try:
        value = document.decode("utf-8").strip()
    except UnicodeDecodeError as error:
        raise DeploymentCheckError(f"{label} is not UTF-8 text") from error
    if not minimum <= len(value) <= maximum:
        raise DeploymentCheckError(f"{label} has an invalid length")
    return value


def _require_model_credential(config: OpenAICompatibleModelConfig, *, route: str) -> None:
    path = config.authorization_token_file
    if path is None:
        return
    if not path.is_absolute() or path == _MODEL_CREDENTIAL_ROOT:
        raise DeploymentCheckError(f"{route} model credential path is outside its private mount")
    try:
        relative = path.relative_to(_MODEL_CREDENTIAL_ROOT)
    except ValueError as error:
        raise DeploymentCheckError(
            f"{route} model credential path is outside its private mount"
        ) from error
    if len(relative.parts) != 1 or relative.parts[0] in {".", ".."}:
        raise DeploymentCheckError(f"{route} model credential path is outside its private mount")
    _read_private_text(path, label=f"{route} model credential", maximum=4_096)


def _load_route(path: Path, *, route: str) -> OpenAICompatibleModelConfig:
    _read_private_text(path, label=f"{route} model config")
    try:
        config = load_openai_compatible_model_config(path)
    except (OSError, ValueError) as error:
        raise DeploymentCheckError(f"{route} model config is invalid") from error
    if Sensitivity.PERSONAL not in config.allowed_sensitivities:
        raise DeploymentCheckError(f"{route} model is not approved for personal conversation")
    _require_model_credential(config, route=route)
    return config


async def _live_checks(
    routes: ModelRouteConfigs,
    telegram: TelegramBotClient,
    owner: TelegramOwnerConfig,
) -> tuple[ModelGatewayHealth, ModelGatewayHealth, TelegramBotIdentity, TelegramChat]:
    capable_health, economy_health, identity, chat = await asyncio.gather(
        asyncio.to_thread(OpenAICompatibleModelGateway(routes.capable).health),
        asyncio.to_thread(OpenAICompatibleModelGateway(routes.economy).health),
        telegram.verify_long_polling(),
        telegram.verify_private_chat(owner.owner_chat_id),
    )
    return capable_health, economy_health, identity, chat


def check_deployment_integrations(
    *,
    guardian_status: Path,
    guardian_public_key: Path,
    capable_model_config: Path,
    economy_model_config: Path,
    telegram_owner_config: Path,
    telegram_bot_token_file: Path,
) -> dict[str, Any]:
    try:
        verified_guardian = FileGuardianStatusReader(
            guardian_status,
            guardian_public_key,
        ).read_status()
    except Exception as error:
        raise DeploymentCheckError("Guardian public handoff could not be verified") from error

    capable = _load_route(capable_model_config, route="capable")
    economy = _load_route(economy_model_config, route="economy")
    try:
        routes = ModelRouteConfigs(capable=capable, economy=economy)
    except ValueError as error:
        raise DeploymentCheckError("capable and economy model routes are not distinct") from error

    try:
        owner = TelegramOwnerConfig.model_validate_json(
            _read_private_text(
                telegram_owner_config,
                label="Telegram owner config",
            ),
            strict=True,
        )
    except ValueError as error:
        raise DeploymentCheckError("Telegram owner config is invalid") from error
    if owner.owner_user_id != owner.owner_chat_id:
        raise DeploymentCheckError("private Telegram owner and chat IDs must match")
    token = _read_private_text(
        telegram_bot_token_file,
        label="Telegram bot token",
        minimum=37,
        maximum=149,
    )
    try:
        telegram = TelegramBotClient(token)
        capable_health, economy_health, identity, _chat = asyncio.run(
            _live_checks(routes, telegram, owner)
        )
    except Exception as error:
        reason = getattr(error, "reason_code", "telegram.integration_unavailable")
        raise DeploymentCheckError(f"Telegram integration failed: {reason}") from error

    for route, health in (
        ("capable", capable_health),
        ("economy", economy_health),
    ):
        if health.state is not ModelHealthState.HEALTHY:
            raise DeploymentCheckError(f"{route} model is unavailable: {health.reason_code}")

    return {
        "activation_prerequisites": "passed",
        "guardian": {
            "mode": verified_guardian.payload.mode.value,
            "receipt": verified_guardian.receipt_hash,
        },
        "models": {
            "capable": {
                "model_id": capable.model_id,
                "provider_id": capable.provider_id,
                "state": capable_health.state.value,
            },
            "economy": {
                "model_id": economy.model_id,
                "provider_id": economy.provider_id,
                "state": economy_health.state.value,
            },
        },
        "telegram": {
            "bot_id": identity.id,
            "bot_username": identity.username,
            "private_chat": "verified",
        },
    }


__all__ = ["DeploymentCheckError", "check_deployment_integrations"]
