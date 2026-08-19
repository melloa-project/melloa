"""Verify a Guardian status envelope from an owner-controlled file."""

from __future__ import annotations

import base64
import binascii
import stat
from pathlib import Path
from threading import Lock
from typing import Final

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import load_pem_public_key
from pydantic import ValidationError

from melloa.domain.base import sha256_digest
from melloa.domain.guardian import (
    GuardianStatusPayload,
    SignedGuardianStatus,
    VerifiedGuardianStatus,
)

_SIGNING_DOMAIN: Final = b"MELLOA-GUARDIAN-STATUS-V1\x00"
_RECEIPT_DOMAIN: Final = b"MELLOA-GUARDIAN-RECEIPT-V1\x00"
_MAX_STATUS_BYTES: Final = 16_384
_MAX_PUBLIC_KEY_BYTES: Final = 4_096


class GuardianVerificationError(RuntimeError):
    """Guardian state was unavailable, malformed, or unauthentic."""


def _decode_base64url(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    try:
        return base64.urlsafe_b64decode(value + padding)
    except (binascii.Error, ValueError) as error:
        raise GuardianVerificationError("invalid base64url in Guardian envelope") from error


def guardian_receipt_hash(
    payload_bytes: bytes,
    signature_bytes: bytes,
    key_id: str,
) -> str:
    material = (
        _RECEIPT_DOMAIN
        + payload_bytes
        + b"\x00"
        + signature_bytes
        + b"\x00"
        + key_id.encode()
    )
    return sha256_digest(material)


def verify_guardian_envelope(
    envelope_document: bytes,
    public_key_document: bytes,
) -> VerifiedGuardianStatus:
    try:
        envelope = SignedGuardianStatus.model_validate_json(envelope_document)
        key = load_pem_public_key(public_key_document)
    except (TypeError, ValueError, ValidationError) as error:
        raise GuardianVerificationError("invalid Guardian envelope or public key") from error
    if not isinstance(key, Ed25519PublicKey):
        raise GuardianVerificationError("Guardian public key must be Ed25519")

    payload_bytes = _decode_base64url(envelope.payload)
    signature_bytes = _decode_base64url(envelope.signature)
    try:
        key.verify(signature_bytes, _SIGNING_DOMAIN + payload_bytes)
        payload = GuardianStatusPayload.model_validate_json(payload_bytes)
    except (InvalidSignature, ValidationError) as error:
        raise GuardianVerificationError(
            "Guardian status signature or payload is invalid"
        ) from error

    return VerifiedGuardianStatus(
        payload=payload,
        receipt_hash=guardian_receipt_hash(payload_bytes, signature_bytes, envelope.key_id),
        key_id=envelope.key_id,
    )


def _read_regular_file(path: Path, maximum_size: int) -> bytes:
    try:
        metadata = path.lstat()
    except OSError as error:
        raise GuardianVerificationError(f"cannot inspect Guardian file: {path}") from error
    if not stat.S_ISREG(metadata.st_mode):
        raise GuardianVerificationError(f"Guardian path is not a regular file: {path}")
    if metadata.st_size > maximum_size:
        raise GuardianVerificationError(f"Guardian file exceeds size limit: {path}")
    try:
        return path.read_bytes()
    except OSError as error:
        raise GuardianVerificationError(f"cannot read Guardian file: {path}") from error


class FileGuardianStatusReader:
    def __init__(self, status_path: Path, public_key_path: Path) -> None:
        self._status_path = status_path
        self._public_key_path = public_key_path
        self._lock = Lock()
        self._pinned_public_key: bytes | None = None
        self._last_status: VerifiedGuardianStatus | None = None

    def read_status(self) -> VerifiedGuardianStatus:
        with self._lock:
            envelope = _read_regular_file(self._status_path, _MAX_STATUS_BYTES)
            public_key = _read_regular_file(self._public_key_path, _MAX_PUBLIC_KEY_BYTES)
            verified = verify_guardian_envelope(envelope, public_key)
            self._accept_observation(public_key, verified)
            return verified

    def _accept_observation(
        self,
        public_key: bytes,
        current: VerifiedGuardianStatus,
    ) -> None:
        if self._pinned_public_key is not None and public_key != self._pinned_public_key:
            raise GuardianVerificationError("Guardian public key changed during this process")

        previous = self._last_status
        if previous is not None:
            if current.receipt_hash == previous.receipt_hash:
                return
            if (
                current.payload.instance_id != previous.payload.instance_id
                or current.key_id != previous.key_id
            ):
                raise GuardianVerificationError(
                    "Guardian identity changed during this process"
                )
            if current.payload.sequence < previous.payload.sequence:
                raise GuardianVerificationError("Guardian sequence moved backwards")
            if current.payload.sequence == previous.payload.sequence:
                raise GuardianVerificationError(
                    "Guardian sequence was reused with a different receipt"
                )
            if (
                current.payload.sequence == previous.payload.sequence + 1
                and current.payload.previous_receipt_hash != previous.receipt_hash
            ):
                raise GuardianVerificationError(
                    "Guardian receipt chain does not extend the last observation"
                )

        self._pinned_public_key = public_key
        self._last_status = current
