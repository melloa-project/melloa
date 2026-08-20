from __future__ import annotations

import pytest

from melloa.adapters.fakes.guardian import FakeGuardianStatusReader
from melloa.adapters.models.openai_compatible import OpenAICompatibleModelConfig
from melloa.adapters.telegram import TelegramOwnerConfig
from melloa.apps.runtime import build_runtime
from melloa.domain.classification import Sensitivity
from melloa.domain.guardian import GuardianMode, GuardianStatusPayload


def _guardian(fixed_time):
    return FakeGuardianStatusReader.from_payload(
        GuardianStatusPayload(
            instance_id="runtime-test-guardian",
            mode=GuardianMode.NORMAL,
            sequence=1,
            changed_at=fixed_time,
            reason_code="guardian.test",
        ),
        receipt_hash="sha256:" + "1" * 64,
    )


def _model_config() -> OpenAICompatibleModelConfig:
    return OpenAICompatibleModelConfig(
        display_name="Local test model",
        provider_id="provider.runtime-test",
        model_id="runtime-test-v1",
        base_url="http://127.0.0.1:11434/v1",
        allowed_sensitivities=frozenset(Sensitivity),
    )


def test_telegram_runtime_requires_secret_pair_model_and_postgres(fixed_time) -> None:
    telegram = TelegramOwnerConfig(owner_user_id=1234, owner_chat_id=5678)
    token = "123456789:abcdefghijklmnopqrstuvwxyz_ABCD123456"

    with pytest.raises(ValueError, match="supplied together"):
        build_runtime(
            _guardian(fixed_time),
            "runtime-owner-credential-value-0001",
            _model_config(),
            telegram_config=telegram,
        )
    with pytest.raises(ValueError, match="PostgreSQL"):
        build_runtime(
            _guardian(fixed_time),
            "runtime-owner-credential-value-0001",
            _model_config(),
            telegram_config=telegram,
            telegram_bot_token=token,
        )
    with pytest.raises(ValueError, match="conversation model"):
        build_runtime(
            _guardian(fixed_time),
            "runtime-owner-credential-value-0001",
            database_connection=object(),  # type: ignore[arg-type]
            telegram_config=telegram,
            telegram_bot_token=token,
        )
