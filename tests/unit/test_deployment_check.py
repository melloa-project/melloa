from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from melloa.apps import deployment_check
from melloa.domain.models import ModelGatewayHealth, ModelHealthState


def _private(path: Path, value: str) -> Path:
    path.write_text(value, encoding="utf-8")
    path.chmod(0o600)
    return path


def _model_document(*, provider: str, model: str) -> str:
    return json.dumps(
        {
            "display_name": model,
            "provider_id": provider,
            "model_id": model,
            "base_url": f"https://{model}.example/v1",
            "processing_location": "approved_provider",
            "allowed_sensitivities": ["personal"],
        }
    )


def test_live_deployment_check_is_redacted_and_requires_both_routes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fixed_time,
) -> None:
    capable = _private(
        tmp_path / "capable.json",
        _model_document(provider="provider.capable", model="capable-v1"),
    )
    economy = _private(
        tmp_path / "economy.json",
        _model_document(provider="provider.economy", model="economy-v1"),
    )
    owner = _private(
        tmp_path / "owner.json",
        '{"owner_user_id":5678,"owner_chat_id":5678}',
    )
    token_value = "123456789:abcdefghijklmnopqrstuvwxyz_ABCD123456"
    token = _private(tmp_path / "telegram-token", token_value)
    healthy = ModelGatewayHealth(
        state=ModelHealthState.HEALTHY,
        checked_at=fixed_time,
        latency_ms=5,
        reason_code="model.endpoint_ready",
    )

    monkeypatch.setattr(
        deployment_check,
        "FileGuardianStatusReader",
        lambda *_args: SimpleNamespace(
            read_status=lambda: SimpleNamespace(
                payload=SimpleNamespace(mode=SimpleNamespace(value="offline")),
                receipt_hash="sha256:" + "a" * 64,
            )
        ),
    )
    monkeypatch.setattr(
        deployment_check.OpenAICompatibleModelGateway,
        "health",
        lambda _self: healthy,
    )

    class Telegram:
        def __init__(self, supplied_token: str) -> None:
            assert supplied_token == token_value

        async def verify_long_polling(self):
            return SimpleNamespace(id=99, username="melli_bot")

        async def verify_private_chat(self, chat_id: int):
            assert chat_id == 5678
            return SimpleNamespace(id=chat_id, type="private")

    monkeypatch.setattr(deployment_check, "TelegramBotClient", Telegram)

    result = deployment_check.check_deployment_integrations(
        guardian_status=tmp_path / "status.json",
        guardian_public_key=tmp_path / "public.pem",
        capable_model_config=capable,
        economy_model_config=economy,
        telegram_owner_config=owner,
        telegram_bot_token_file=token,
    )

    serialized = json.dumps(result)
    assert result["activation_prerequisites"] == "passed"
    assert result["models"]["capable"]["state"] == "healthy"
    assert result["models"]["economy"]["state"] == "healthy"
    assert result["telegram"] == {
        "bot_id": 99,
        "bot_username": "melli_bot",
        "private_chat": "verified",
    }
    assert token_value not in serialized
    assert "5678" not in serialized


def test_deployment_check_rejects_mismatched_private_owner_and_chat_ids(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capable = _private(
        tmp_path / "capable.json",
        _model_document(provider="provider.capable", model="capable-v1"),
    )
    economy = _private(
        tmp_path / "economy.json",
        _model_document(provider="provider.economy", model="economy-v1"),
    )
    owner = _private(
        tmp_path / "owner.json",
        '{"owner_user_id":1234,"owner_chat_id":5678}',
    )
    token = _private(
        tmp_path / "telegram-token",
        "123456789:abcdefghijklmnopqrstuvwxyz_ABCD123456",
    )
    monkeypatch.setattr(
        deployment_check,
        "FileGuardianStatusReader",
        lambda *_args: SimpleNamespace(read_status=lambda: object()),
    )

    with pytest.raises(
        deployment_check.DeploymentCheckError,
        match="owner and chat IDs must match",
    ):
        deployment_check.check_deployment_integrations(
            guardian_status=tmp_path / "status.json",
            guardian_public_key=tmp_path / "public.pem",
            capable_model_config=capable,
            economy_model_config=economy,
            telegram_owner_config=owner,
            telegram_bot_token_file=token,
        )


def test_model_credentials_cannot_escape_the_dedicated_mount(tmp_path: Path) -> None:
    config_path = _private(
        tmp_path / "capable.json",
        json.dumps(
            {
                "display_name": "capable-v1",
                "provider_id": "provider.capable",
                "model_id": "capable-v1",
                "base_url": "https://capable.example/v1",
                "processing_location": "approved_provider",
                "allowed_sensitivities": ["personal"],
                "authorization_token_file": (
                    "/run/melloa/model-credentials/../private/owner-credential"
                ),
            }
        ),
    )

    with pytest.raises(
        deployment_check.DeploymentCheckError,
        match="outside its private mount",
    ):
        deployment_check._load_route(config_path, route="capable")
