from __future__ import annotations

import base64
import json

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from melloa.adapters.guardian.file import (
    FileGuardianStatusReader,
    GuardianVerificationError,
    verify_guardian_envelope,
)
from melloa.domain.guardian import GuardianMode, GuardianStatusPayload


def base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def signed_status(fixed_time):
    private_key = Ed25519PrivateKey.generate()
    payload = GuardianStatusPayload(
        instance_id="home-guardian",
        mode=GuardianMode.NO_ACTIONS,
        sequence=1,
        changed_at=fixed_time,
        reason_code="guardian.initialized",
    ).model_dump_json().encode()
    signature = private_key.sign(b"MELLOA-GUARDIAN-STATUS-V1\x00" + payload)
    envelope = json.dumps(
        {
            "envelope_version": "1.0.0",
            "algorithm": "Ed25519",
            "key_id": "guardian.status-v1",
            "payload": base64url(payload),
            "signature": base64url(signature),
        },
        separators=(",", ":"),
    ).encode()
    public_key = private_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return envelope, public_key


def test_signed_status_verifies_and_tampering_fails(fixed_time) -> None:
    envelope, public_key = signed_status(fixed_time)
    verified = verify_guardian_envelope(envelope, public_key)
    assert verified.payload.mode is GuardianMode.NO_ACTIONS
    assert verified.receipt_hash.startswith("sha256:")

    document = json.loads(envelope)
    document["signature"] = base64url(b"x" * 64)
    with pytest.raises(GuardianVerificationError, match="signature"):
        verify_guardian_envelope(json.dumps(document).encode(), public_key)


def test_file_reader_rejects_symlink_status(tmp_path, fixed_time) -> None:
    envelope, public_key = signed_status(fixed_time)
    real_status = tmp_path / "real-status.json"
    status_link = tmp_path / "status.json"
    public_key_path = tmp_path / "guardian.pub.pem"
    real_status.write_bytes(envelope)
    status_link.symlink_to(real_status)
    public_key_path.write_bytes(public_key)

    reader = FileGuardianStatusReader(status_link, public_key_path)
    with pytest.raises(GuardianVerificationError, match="regular file"):
        reader.read_status()
