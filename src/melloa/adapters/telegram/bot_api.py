"""Bounded Telegram Bot API adapters with redacted transport failures."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import stat
from collections.abc import Callable
from datetime import UTC, datetime
from ipaddress import IPv4Address, IPv6Address, ip_address, ip_network
from pathlib import Path
from threading import RLock
from time import monotonic
from typing import Annotated
from urllib.parse import urlsplit, urlunsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator

from melloa.domain.base import (
    JsonObject,
    QualifiedName,
    RecordId,
    canonical_json_bytes,
    new_record_id,
    sha256_digest,
    utc_now,
)
from melloa.domain.conversation import (
    ConversationMessage,
    DeliveryAttempt,
    DeliveryState,
    MessageKind,
)
from melloa.domain.delivery import AuthorizedClientDelivery, validate_client_delivery
from melloa.domain.telegram import (
    MAX_TELEGRAM_UPDATE_BYTES,
    TelegramAttachmentKind,
    TelegramAttachmentReference,
    TelegramChatType,
    TelegramInboundMessage,
    TelegramInboundUpdate,
    TelegramOwnerPairing,
    TelegramPollRequest,
    telegram_pairing_id_from_destination,
)
from melloa.ports.client import (
    PermanentClientDeliveryError,
    TransientClientDeliveryError,
)
from melloa.ports.telegram import (
    PermanentTelegramPollingError,
    TelegramPairingChallenge,
    TelegramPairingConflictError,
    TelegramPollConflictError,
    TransientTelegramPollingError,
)

_MAX_API_RESPONSE_BYTES = 2_000_000
_MAX_TOKEN_BYTES = 512
_MAX_TELEGRAM_TEXT_LENGTH = 4_096
_PRIVATE_IPV4_NETWORKS = tuple(
    ip_network(network)
    for network in ("10.0.0.0/8", "100.64.0.0/10", "172.16.0.0/12", "192.168.0.0/16")
)
_PRIVATE_IPV6_NETWORK = ip_network("fc00::/7")
_SUPPORTED_FILE_FIELDS = (
    ("document", TelegramAttachmentKind.DOCUMENT),
    ("audio", TelegramAttachmentKind.AUDIO),
    ("voice", TelegramAttachmentKind.VOICE),
    ("video", TelegramAttachmentKind.VIDEO),
    ("animation", TelegramAttachmentKind.ANIMATION),
    ("sticker", TelegramAttachmentKind.STICKER),
)
_UNSUPPORTED_CONTENT_FIELDS = frozenset(
    {
        "business_connection",
        "contact",
        "dice",
        "game",
        "giveaway",
        "giveaway_created",
        "giveaway_winners",
        "invoice",
        "location",
        "passport_data",
        "poll",
        "proximity_alert_triggered",
        "refunded_payment",
        "successful_payment",
        "venue",
        "video_note",
        "web_app_data",
    }
)


class TelegramBotApiConfig(BaseModel):
    """Owner-supplied, credential-free Telegram transport configuration."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    adapter_id: QualifiedName = "client.telegram.bot-api"
    token_file: Path
    api_base_url: str = Field(default="https://api.telegram.org", min_length=1, max_length=2_048)
    connect_timeout_seconds: Annotated[float, Field(gt=0, le=30)] = 5.0
    response_grace_seconds: Annotated[float, Field(gt=0, le=30)] = 5.0

    @model_validator(mode="after")
    def validate_endpoint(self) -> TelegramBotApiConfig:
        parts = urlsplit(self.api_base_url)
        if parts.scheme not in {"http", "https"} or not parts.hostname:
            raise ValueError("Telegram API base URL must use HTTP or HTTPS with a host")
        if parts.username or parts.password or parts.query or parts.fragment:
            raise ValueError(
                "Telegram API base URL cannot contain credentials, query, or fragment"
            )
        if parts.hostname == "api.telegram.org":
            if parts.scheme != "https" or parts.port is not None or parts.path not in {"", "/"}:
                raise ValueError("the public Telegram Bot API requires its canonical HTTPS origin")
        elif not _is_private_endpoint(parts.hostname):
            raise ValueError(
                "custom Telegram API endpoints require localhost or a private literal IP"
            )
        return self


class EphemeralTelegramPairingCodeIssuer:
    """Derive replay-stable codes from an in-memory high-entropy process secret."""

    def __init__(self, secret: bytes | None = None) -> None:
        material = secrets.token_bytes(32) if secret is None else bytes(secret)
        if len(material) < 32:
            raise ValueError("Telegram pairing issuer secret must contain at least 32 bytes")
        self._secret = material

    def issue(self, candidate_id: RecordId) -> str:
        digest = hmac.digest(self._secret, candidate_id.encode("utf-8"), hashlib.sha256)
        return base64.urlsafe_b64encode(digest[:24]).rstrip(b"=").decode("ascii")


class TelegramBotApiPairingCodeIssuer:
    """Derive restart-stable pairing codes from the configured bot credential."""

    def __init__(self, config: TelegramBotApiConfig) -> None:
        token = _read_bot_token(config.token_file).encode("utf-8")
        self._secret = hmac.digest(
            token,
            b"melloa:telegram-bot-api:pairing-code:v1",
            hashlib.sha256,
        )

    def issue(self, candidate_id: RecordId) -> str:
        digest = hmac.digest(self._secret, candidate_id.encode("utf-8"), hashlib.sha256)
        return base64.urlsafe_b64encode(digest[:24]).rstrip(b"=").decode("ascii")


class _TelegramBotApiError(RuntimeError):
    def __init__(
        self,
        reason_code: QualifiedName,
        *,
        retryable: bool,
        outcome_unknown: bool = False,
    ) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code
        self.retryable = retryable
        self.outcome_unknown = outcome_unknown


class _TelegramBotApiClient:
    def __init__(
        self,
        config: TelegramBotApiConfig,
        *,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.config = config
        self._transport = transport
        self._clock = clock
        self._health_lock = RLock()
        self._requests = 0
        self._last_success_at: datetime | None = None
        self._last_error_code: QualifiedName | None = None
        self._last_latency_ms: int | None = None
        self._read_token()

    def call(
        self,
        method: str,
        payload: JsonObject,
        *,
        response_timeout_seconds: float,
    ) -> object:
        started = monotonic()
        try:
            document = self._request(method, payload, response_timeout_seconds)
            result = self._result(document)
        except _TelegramBotApiError as error:
            self._record(started, error.reason_code)
            raise
        except Exception as error:
            self._record(started, "telegram.api.invalid_response")
            raise _TelegramBotApiError(
                "telegram.api.invalid_response",
                retryable=False,
            ) from error
        self._record(started, None)
        return result

    def health(self) -> JsonObject:
        with self._health_lock:
            return {
                "status": "healthy" if self._last_error_code is None else "degraded",
                "transport": "telegram-bot-api",
                "network": True,
                "credentials": True,
                "requests": self._requests,
                "last_success_at": (
                    None if self._last_success_at is None else self._last_success_at.isoformat()
                ),
                "last_error_code": self._last_error_code,
                "last_latency_ms": self._last_latency_ms,
                "api_origin": normalized_telegram_api_origin(self.config),
            }

    def _request(
        self,
        method: str,
        payload: JsonObject,
        response_timeout_seconds: float,
    ) -> JsonObject:
        token = self._read_token()
        endpoint = f"{self.config.api_base_url.rstrip('/')}/bot{token}/{method}"
        timeout = httpx.Timeout(
            connect=self.config.connect_timeout_seconds,
            read=response_timeout_seconds,
            write=self.config.connect_timeout_seconds,
            pool=self.config.connect_timeout_seconds,
        )
        try:
            with httpx.Client(
                timeout=timeout,
                follow_redirects=False,
                transport=self._transport,
                trust_env=False,
            ) as client:
                with client.stream(
                    "POST",
                    endpoint,
                    headers={"Accept": "application/json"},
                    json=payload,
                ) as response:
                    status_code = response.status_code
                    content = _bounded_response_content(response)
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout):
            raise _TelegramBotApiError(
                "telegram.api.connection_failed",
                retryable=True,
            ) from None
        except (httpx.ReadTimeout, httpx.WriteTimeout, httpx.RemoteProtocolError):
            raise _TelegramBotApiError(
                "telegram.api.outcome_unknown",
                retryable=True,
                outcome_unknown=True,
            ) from None
        except httpx.HTTPError:
            raise _TelegramBotApiError(
                "telegram.api.transport_failed",
                retryable=True,
                outcome_unknown=True,
            ) from None

        document = _decode_document(content)
        if status_code != 200:
            raise _http_error(status_code)
        return document

    @staticmethod
    def _result(document: JsonObject) -> object:
        ok = document.get("ok")
        if ok is True and "result" in document:
            return document["result"]
        if ok is not False:
            raise _TelegramBotApiError(
                "telegram.api.invalid_response",
                retryable=False,
            )
        error_code = document.get("error_code")
        if error_code == 429:
            raise _TelegramBotApiError("telegram.api.rate_limited", retryable=True)
        if error_code in {401, 403}:
            raise _TelegramBotApiError("telegram.api.unauthorized", retryable=False)
        if isinstance(error_code, int) and error_code >= 500:
            raise _TelegramBotApiError(
                "telegram.api.upstream_unavailable",
                retryable=True,
                outcome_unknown=True,
            )
        raise _TelegramBotApiError("telegram.api.request_rejected", retryable=False)

    def _read_token(self) -> str:
        return _read_bot_token(self.config.token_file)

    def _record(self, started: float, error_code: QualifiedName | None) -> None:
        now = self._clock()
        with self._health_lock:
            self._requests += 1
            self._last_latency_ms = max(0, round((monotonic() - started) * 1_000))
            self._last_error_code = error_code
            if error_code is None:
                self._last_success_at = now


def _read_bot_token(path: Path) -> str:
    metadata = path.lstat()
    if not stat.S_ISREG(metadata.st_mode):
        raise ValueError("Telegram bot token path must be a regular file")
    if stat.S_IMODE(metadata.st_mode) != 0o600:
        raise ValueError("Telegram bot token file mode must be exactly 0600")
    if metadata.st_size > _MAX_TOKEN_BYTES:
        raise ValueError("Telegram bot token file is too large")
    token = path.read_text(encoding="utf-8").strip()
    if not 32 <= len(token) <= 256 or ":" not in token:
        raise ValueError("Telegram bot token file does not contain a plausible token")
    return token


class TelegramBotApiUpdateSource:
    """Long-poll and normalize bounded Telegram updates without advancing offsets."""

    def __init__(
        self,
        config: TelegramBotApiConfig,
        *,
        client: _TelegramBotApiClient | None = None,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._config = config
        self._clock = clock
        self._client = client or _TelegramBotApiClient(
            config,
            transport=transport,
            clock=clock,
        )

    def poll(self, request: TelegramPollRequest) -> tuple[TelegramInboundUpdate, ...]:
        if request.adapter_id != self._config.adapter_id:
            raise TelegramPollConflictError("Telegram source adapter identity mismatch")
        try:
            result = self._client.call(
                "getUpdates",
                {
                    "offset": request.offset,
                    "timeout": request.timeout_seconds,
                    "limit": request.limit,
                    "allowed_updates": [kind.value for kind in request.allowed_updates],
                },
                response_timeout_seconds=(
                    request.timeout_seconds + self._config.response_grace_seconds
                ),
            )
            if not isinstance(result, list):
                raise ValueError("Telegram getUpdates result must be an array")
            updates = tuple(self._normalize_update(item) for item in result)
        except _TelegramBotApiError as error:
            if error.retryable:
                raise TransientTelegramPollingError(error.reason_code) from error
            raise PermanentTelegramPollingError(error.reason_code) from error
        except (TypeError, ValueError) as error:
            raise PermanentTelegramPollingError("telegram.update.invalid") from error
        return updates

    def health(self) -> JsonObject:
        return self._client.health()

    def _normalize_update(self, raw_update: object) -> TelegramInboundUpdate:
        if not isinstance(raw_update, dict):
            raise ValueError("Telegram update must be an object")
        raw_size = len(canonical_json_bytes(raw_update))
        if not 1 <= raw_size <= MAX_TELEGRAM_UPDATE_BYTES:
            raise ValueError("Telegram update exceeds its size ceiling")
        update_id = _required_int(raw_update, "update_id", minimum=0)
        raw_message = raw_update.get("message")
        if not isinstance(raw_message, dict):
            raise ValueError("Telegram update is not a new message")
        message = self._normalize_message(raw_message, raw_update)
        received_at = max(self._clock(), message.sent_at)
        return TelegramInboundUpdate(
            update_id=update_id,
            message=message,
            received_at=received_at,
            raw_size_bytes=raw_size,
            source_payload_hash=sha256_digest(canonical_json_bytes(raw_update)),
        )

    @staticmethod
    def _normalize_message(
        raw_message: JsonObject,
        raw_update: JsonObject,
    ) -> TelegramInboundMessage:
        raw_sender = raw_message.get("from")
        raw_chat = raw_message.get("chat")
        if not isinstance(raw_sender, dict) or not isinstance(raw_chat, dict):
            raise ValueError("Telegram message lacks sender or chat identity")
        chat_type_raw = raw_chat.get("type")
        if not isinstance(chat_type_raw, str):
            raise ValueError("Telegram chat type is absent")
        chat_type = TelegramChatType(chat_type_raw)
        sent_at = _telegram_timestamp(_required_int(raw_message, "date", minimum=0))
        text = raw_message.get("text")
        if text is None:
            text = raw_message.get("caption")
        if text is not None and (not isinstance(text, str) or not text):
            raise ValueError("Telegram message text is invalid")
        attachments = _attachment_references(raw_message, raw_update)
        return TelegramInboundMessage(
            telegram_message_id=_required_int(raw_message, "message_id", minimum=1),
            sender_user_id=_required_int(raw_sender, "id", minimum=1),
            chat_id=_required_int(raw_chat, "id"),
            chat_type=chat_type,
            sent_at=sent_at,
            text=text,
            attachments=attachments,
        )


class TelegramBotApiPairingChallengePublisher:
    """Publish one replay-stable pairing code to its initiating private chat."""

    def __init__(
        self,
        config: TelegramBotApiConfig,
        *,
        client: _TelegramBotApiClient | None = None,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._client = client or _TelegramBotApiClient(
            config,
            transport=transport,
            clock=clock,
        )
        self._lock = RLock()
        self._published: dict[RecordId, str] = {}

    def publish(self, challenge: TelegramPairingChallenge) -> None:
        candidate = challenge.candidate
        fingerprint = _challenge_fingerprint(challenge)
        with self._lock:
            existing = self._published.get(candidate.candidate_id)
            if existing is not None:
                if existing != fingerprint:
                    raise TelegramPairingConflictError(
                        "Telegram pairing challenge changed across replay"
                    )
                return
        text = (
            "Melloa pairing request\n\n"
            f"Confirmation code: {challenge.confirmation_code}\n\n"
            "Enter this code in the private Owner Console. If you did not start this "
            "request, ignore it."
        )
        try:
            result = self._client.call(
                "sendMessage",
                {"chat_id": candidate.telegram_chat_id, "text": text},
                response_timeout_seconds=10.0,
            )
            _validate_sent_message(result, expected_chat_id=candidate.telegram_chat_id)
        except _TelegramBotApiError as error:
            raise RuntimeError(error.reason_code) from error
        with self._lock:
            existing = self._published.setdefault(candidate.candidate_id, fingerprint)
            if existing != fingerprint:
                raise TelegramPairingConflictError(
                    "Telegram pairing challenge changed during publication"
                )


class TelegramBotApiClientAdapter:
    """Deliver exact policy-authorized text to one immutable active pairing."""

    def __init__(
        self,
        config: TelegramBotApiConfig,
        pairing_resolver: Callable[[RecordId], TelegramOwnerPairing],
        *,
        client: _TelegramBotApiClient | None = None,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], datetime] = utc_now,
        id_factory: Callable[[str], str] = new_record_id,
    ) -> None:
        self._config = config
        self._pairing_resolver = pairing_resolver
        self._clock = clock
        self._id_factory = id_factory
        self._client = client or _TelegramBotApiClient(
            config,
            transport=transport,
            clock=clock,
        )
        self._lock = RLock()
        self._sent_by_key: dict[str, tuple[str, int]] = {}
        self._attempts: dict[tuple[str, int], tuple[str, DeliveryAttempt]] = {}

    def receive(self) -> tuple[ConversationMessage, ...]:
        return ()

    def send(self, delivery: AuthorizedClientDelivery) -> DeliveryAttempt:
        now = self._clock()
        validate_client_delivery(
            delivery,
            expected_client_adapter=self._config.adapter_id,
            now=now,
        )
        pairing_id = telegram_pairing_id_from_destination(delivery.destination_ref)
        try:
            pairing = self._pairing_resolver(pairing_id)
        except Exception as error:
            raise PermanentClientDeliveryError(
                "telegram.delivery.pairing_unavailable"
            ) from error
        text = _delivery_text(delivery.message)
        fingerprint = sha256_digest(
            canonical_json_bytes(
                {
                    "message": delivery.message.model_dump(mode="json"),
                    "destination_ref": delivery.destination_ref,
                    "action_hash": delivery.authorization_request.action_hash,
                }
            )
        )
        attempt_key = (delivery.idempotency_key, delivery.attempt)
        with self._lock:
            existing_attempt = self._attempts.get(attempt_key)
            if existing_attempt is not None:
                existing_fingerprint, receipt = existing_attempt
                if existing_fingerprint != fingerprint:
                    raise ValueError(
                        "Telegram delivery attempt key was reused with other content"
                    )
                return receipt
            existing_delivery = self._sent_by_key.get(delivery.idempotency_key)
            if existing_delivery is not None:
                existing_fingerprint, telegram_message_id = existing_delivery
                if existing_fingerprint != fingerprint:
                    raise ValueError("Telegram delivery key was reused with other content")
                receipt = self._receipt(
                    delivery,
                    now=now,
                    telegram_message_id=telegram_message_id,
                    deduplicated=True,
                )
                self._attempts[attempt_key] = (fingerprint, receipt)
                return receipt

        try:
            result = self._client.call(
                "sendMessage",
                {"chat_id": pairing.telegram_chat_id, "text": text},
                response_timeout_seconds=10.0,
            )
            telegram_message_id = _validate_sent_message(
                result,
                expected_chat_id=pairing.telegram_chat_id,
            )
        except _TelegramBotApiError as error:
            if error.outcome_unknown:
                raise PermanentClientDeliveryError(
                    "telegram.delivery.outcome_unknown"
                ) from error
            if error.retryable:
                raise TransientClientDeliveryError(error.reason_code) from error
            raise PermanentClientDeliveryError(error.reason_code) from error

        receipt = self._receipt(
            delivery,
            now=max(now, self._clock()),
            telegram_message_id=telegram_message_id,
            deduplicated=False,
        )
        with self._lock:
            existing_delivery = self._sent_by_key.setdefault(
                delivery.idempotency_key,
                (fingerprint, telegram_message_id),
            )
            if existing_delivery != (fingerprint, telegram_message_id):
                raise ValueError("Telegram delivery changed during publication")
            self._attempts[attempt_key] = (fingerprint, receipt)
        return receipt

    def capabilities(self) -> JsonObject:
        return {
            "transport": "telegram-bot-api",
            "network": True,
            "inbound": "getUpdates-long-polling",
            "text": True,
            "attachments": False,
            "max_text_length": _MAX_TELEGRAM_TEXT_LENGTH,
            "idempotency_scope": "process-local-successful-sends",
            "ambiguous_send_retries": False,
        }

    def health(self) -> JsonObject:
        return self._client.health()

    def _receipt(
        self,
        delivery: AuthorizedClientDelivery,
        *,
        now: datetime,
        telegram_message_id: int,
        deduplicated: bool,
    ) -> DeliveryAttempt:
        return DeliveryAttempt(
            delivery_id=self._id_factory("delivery"),
            message_id=delivery.message.message_id,
            client_adapter=self._config.adapter_id,
            destination_ref=delivery.destination_ref,
            attempt=delivery.attempt,
            state=DeliveryState.SENT,
            attempted_at=now,
            adapter_metadata={
                "action_hash": delivery.authorization_request.action_hash,
                "authorization_id": delivery.policy_decision.decision_id,
                "deduplicated": deduplicated,
                "telegram_message_id": telegram_message_id,
            },
        )


def normalized_telegram_api_origin(config: TelegramBotApiConfig) -> str:
    """Return a credential-free API origin suitable for diagnostics."""

    parts = urlsplit(config.api_base_url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), "", ""))


def _bounded_response_content(response: httpx.Response) -> bytes:
    content = bytearray()
    for chunk in response.iter_bytes():
        content.extend(chunk)
        if len(content) > _MAX_API_RESPONSE_BYTES:
            raise _TelegramBotApiError(
                "telegram.api.response_too_large",
                retryable=False,
            )
    return bytes(content)


def _decode_document(content: bytes) -> JsonObject:
    if not content:
        raise _TelegramBotApiError("telegram.api.invalid_response", retryable=False)
    try:
        document = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise _TelegramBotApiError(
            "telegram.api.invalid_response",
            retryable=False,
        ) from error
    if not isinstance(document, dict):
        raise _TelegramBotApiError("telegram.api.invalid_response", retryable=False)
    return document


def _http_error(status_code: int) -> _TelegramBotApiError:
    if status_code == 429:
        return _TelegramBotApiError("telegram.api.rate_limited", retryable=True)
    if status_code in {401, 403}:
        return _TelegramBotApiError("telegram.api.unauthorized", retryable=False)
    if status_code >= 500:
        return _TelegramBotApiError(
            "telegram.api.upstream_unavailable",
            retryable=True,
            outcome_unknown=True,
        )
    return _TelegramBotApiError("telegram.api.request_rejected", retryable=False)


def _required_int(
    document: JsonObject,
    key: str,
    *,
    minimum: int | None = None,
) -> int:
    value = document.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"Telegram {key} must be an integer")
    if minimum is not None and value < minimum:
        raise ValueError(f"Telegram {key} is below its minimum")
    return value


def _telegram_timestamp(value: int) -> datetime:
    try:
        return datetime.fromtimestamp(value, tz=UTC)
    except (OverflowError, OSError, ValueError) as error:
        raise ValueError("Telegram message timestamp is invalid") from error


def _attachment_references(
    raw_message: JsonObject,
    raw_update: JsonObject,
) -> tuple[TelegramAttachmentReference, ...]:
    references: list[TelegramAttachmentReference] = []
    photo = raw_message.get("photo")
    if photo is not None:
        if not isinstance(photo, list) or not photo or not isinstance(photo[-1], dict):
            raise ValueError("Telegram photo metadata is invalid")
        references.append(_file_reference(photo[-1], TelegramAttachmentKind.PHOTO))
    for field, kind in _SUPPORTED_FILE_FIELDS:
        value = raw_message.get(field)
        if value is None:
            continue
        if not isinstance(value, dict):
            raise ValueError(f"Telegram {field} metadata is invalid")
        references.append(_file_reference(value, kind))
    if _UNSUPPORTED_CONTENT_FIELDS.intersection(raw_message):
        digest = hashlib.sha256(canonical_json_bytes(raw_update)).hexdigest()
        references.append(
            TelegramAttachmentReference(
                kind=TelegramAttachmentKind.UNSUPPORTED,
                file_id=f"unsupported:{digest}",
                file_unique_id=f"unsupported:{digest}",
                declared_size_bytes=0,
            )
        )
    return tuple(references)


def _file_reference(
    document: JsonObject,
    kind: TelegramAttachmentKind,
) -> TelegramAttachmentReference:
    file_id = document.get("file_id")
    file_unique_id = document.get("file_unique_id")
    if not isinstance(file_id, str) or not file_id:
        raise ValueError("Telegram attachment file ID is invalid")
    if not isinstance(file_unique_id, str) or not file_unique_id:
        raise ValueError("Telegram attachment unique ID is invalid")
    file_size = document.get("file_size")
    if file_size is not None and (
        isinstance(file_size, bool) or not isinstance(file_size, int) or file_size < 0
    ):
        raise ValueError("Telegram attachment size is invalid")
    media_type = document.get("mime_type")
    if media_type is not None and (not isinstance(media_type, str) or not media_type):
        raise ValueError("Telegram attachment media type is invalid")
    file_name = document.get("file_name")
    if file_name is not None and (not isinstance(file_name, str) or not file_name):
        raise ValueError("Telegram attachment file name is invalid")
    return TelegramAttachmentReference(
        kind=kind,
        file_id=file_id,
        file_unique_id=file_unique_id,
        declared_size_bytes=file_size,
        media_type=media_type,
        file_name=file_name,
    )


def _challenge_fingerprint(challenge: TelegramPairingChallenge) -> str:
    return sha256_digest(
        canonical_json_bytes(
            {
                "candidate": challenge.candidate.model_dump(mode="json"),
                "confirmation_code_hash": sha256_digest(
                    challenge.confirmation_code.encode("utf-8")
                ),
            }
        )
    )


def _validate_sent_message(result: object, *, expected_chat_id: int) -> int:
    if not isinstance(result, dict):
        raise _TelegramBotApiError("telegram.api.invalid_response", retryable=False)
    chat = result.get("chat")
    if not isinstance(chat, dict) or _required_int(chat, "id") != expected_chat_id:
        raise _TelegramBotApiError("telegram.api.destination_mismatch", retryable=False)
    return _required_int(result, "message_id", minimum=1)


def _delivery_text(message: ConversationMessage) -> str:
    if any(part.kind is not MessageKind.TEXT for part in message.parts):
        raise PermanentClientDeliveryError("telegram.delivery.text_only")
    text = "\n\n".join(part.text or "" for part in message.parts)
    if not text or len(text) > _MAX_TELEGRAM_TEXT_LENGTH:
        raise PermanentClientDeliveryError("telegram.delivery.text_length")
    return text


def _is_private_endpoint(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        address = ip_address(host)
    except ValueError:
        return False
    if address.is_unspecified or address.is_multicast or address.is_link_local:
        return False
    if address.is_loopback:
        return True
    if isinstance(address, IPv4Address):
        return any(address in network for network in _PRIVATE_IPV4_NETWORKS)
    if isinstance(address, IPv6Address):
        return address in _PRIVATE_IPV6_NETWORK
    return False
