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


def signed_status(
    fixed_time,
    *,
    private_key: Ed25519PrivateKey | None = None,
    instance_id: str = "home-guardian",
    mode: GuardianMode = GuardianMode.NO_ACTIONS,
    sequence: int = 1,
    previous_receipt_hash: str | None = None,
    key_id: str = "guardian.status-v1",
):
    private_key = private_key or Ed25519PrivateKey.generate()
    payload = GuardianStatusPayload(
        instance_id=instance_id,
        mode=mode,
        sequence=sequence,
        changed_at=fixed_time,
        reason_code="guardian.initialized",
        previous_receipt_hash=previous_receipt_hash,
    ).model_dump_json().encode()
    signature = private_key.sign(b"MELLOA-GUARDIAN-STATUS-V1\x00" + payload)
    envelope = json.dumps(
        {
            "envelope_version": "1.0.0",
            "algorithm": "Ed25519",
            "key_id": key_id,
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


def test_file_reader_accepts_repeat_and_contiguous_successor(tmp_path, fixed_time) -> None:
    private_key = Ed25519PrivateKey.generate()
    first, public_key = signed_status(fixed_time, private_key=private_key)
    first_receipt = verify_guardian_envelope(first, public_key).receipt_hash
    second, _ = signed_status(
        fixed_time,
        private_key=private_key,
        sequence=2,
        previous_receipt_hash=first_receipt,
    )
    status_path = tmp_path / "status.json"
    public_key_path = tmp_path / "public.pem"
    status_path.write_bytes(first)
    public_key_path.write_bytes(public_key)
    reader = FileGuardianStatusReader(status_path, public_key_path)

    assert reader.read_status().payload.sequence == 1
    assert reader.read_status().receipt_hash == first_receipt
    status_path.write_bytes(second)
    assert reader.read_status().payload.sequence == 2


def test_file_reader_rejects_rollback_and_retains_last_good_status(
    tmp_path,
    fixed_time,
) -> None:
    private_key = Ed25519PrivateKey.generate()
    first, public_key = signed_status(fixed_time, private_key=private_key)
    first_receipt = verify_guardian_envelope(first, public_key).receipt_hash
    second, _ = signed_status(
        fixed_time,
        private_key=private_key,
        sequence=2,
        previous_receipt_hash=first_receipt,
    )
    second_receipt = verify_guardian_envelope(second, public_key).receipt_hash
    third, _ = signed_status(
        fixed_time,
        private_key=private_key,
        sequence=3,
        previous_receipt_hash=second_receipt,
    )
    status_path = tmp_path / "status.json"
    public_key_path = tmp_path / "public.pem"
    status_path.write_bytes(second)
    public_key_path.write_bytes(public_key)
    reader = FileGuardianStatusReader(status_path, public_key_path)
    assert reader.read_status().payload.sequence == 2

    status_path.write_bytes(first)
    with pytest.raises(GuardianVerificationError, match="backwards"):
        reader.read_status()

    status_path.write_bytes(third)
    assert reader.read_status().payload.sequence == 3


def test_file_reader_rejects_same_sequence_fork_and_broken_next_link(
    tmp_path,
    fixed_time,
) -> None:
    private_key = Ed25519PrivateKey.generate()
    first, public_key = signed_status(fixed_time, private_key=private_key)
    status_path = tmp_path / "status.json"
    public_key_path = tmp_path / "public.pem"
    status_path.write_bytes(first)
    public_key_path.write_bytes(public_key)
    reader = FileGuardianStatusReader(status_path, public_key_path)
    reader.read_status()

    fork, _ = signed_status(
        fixed_time,
        private_key=private_key,
        mode=GuardianMode.OFFLINE,
    )
    status_path.write_bytes(fork)
    with pytest.raises(GuardianVerificationError, match="reused"):
        reader.read_status()

    broken_next, _ = signed_status(
        fixed_time,
        private_key=private_key,
        sequence=2,
        previous_receipt_hash="sha256:" + "0" * 64,
    )
    status_path.write_bytes(broken_next)
    with pytest.raises(GuardianVerificationError, match="does not extend"):
        reader.read_status()

    skipped, _ = signed_status(
        fixed_time,
        private_key=private_key,
        sequence=3,
        previous_receipt_hash="sha256:" + "1" * 64,
    )
    status_path.write_bytes(skipped)
    assert reader.read_status().payload.sequence == 3


def test_file_reader_pins_guardian_identity_key_id_and_public_key(
    tmp_path,
    fixed_time,
) -> None:
    private_key = Ed25519PrivateKey.generate()
    first, public_key = signed_status(fixed_time, private_key=private_key)
    first_receipt = verify_guardian_envelope(first, public_key).receipt_hash
    status_path = tmp_path / "status.json"
    public_key_path = tmp_path / "public.pem"
    status_path.write_bytes(first)
    public_key_path.write_bytes(public_key)
    reader = FileGuardianStatusReader(status_path, public_key_path)
    reader.read_status()

    changed_instance, _ = signed_status(
        fixed_time,
        private_key=private_key,
        instance_id="other-guardian",
        sequence=2,
        previous_receipt_hash=first_receipt,
    )
    status_path.write_bytes(changed_instance)
    with pytest.raises(GuardianVerificationError, match="identity changed"):
        reader.read_status()

    changed_key_id, _ = signed_status(
        fixed_time,
        private_key=private_key,
        sequence=2,
        previous_receipt_hash=first_receipt,
        key_id="guardian.other-key",
    )
    status_path.write_bytes(changed_key_id)
    with pytest.raises(GuardianVerificationError, match="identity changed"):
        reader.read_status()

    other_private_key = Ed25519PrivateKey.generate()
    changed_key, changed_public_key = signed_status(
        fixed_time,
        private_key=other_private_key,
        sequence=2,
        previous_receipt_hash=first_receipt,
    )
    status_path.write_bytes(changed_key)
    public_key_path.write_bytes(changed_public_key)
    with pytest.raises(GuardianVerificationError, match="public key changed"):
        reader.read_status()
