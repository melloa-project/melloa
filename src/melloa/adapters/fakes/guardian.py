"""Synthetic read-only Guardian status source."""

from __future__ import annotations

from melloa.domain.guardian import GuardianStatusPayload, VerifiedGuardianStatus


class FakeGuardianStatusReader:
    def __init__(self, status: VerifiedGuardianStatus) -> None:
        self._status = status

    @classmethod
    def from_payload(
        cls,
        payload: GuardianStatusPayload,
        *,
        receipt_hash: str,
        key_id: str = "guardian.test-key",
    ) -> FakeGuardianStatusReader:
        return cls(
            VerifiedGuardianStatus(
                payload=payload,
                receipt_hash=receipt_hash,
                key_id=key_id,
            )
        )

    def read_status(self) -> VerifiedGuardianStatus:
        return self._status
