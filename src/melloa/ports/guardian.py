"""Read-only access to independently controlled Guardian status."""

from typing import Protocol

from melloa.domain.guardian import VerifiedGuardianStatus


class GuardianStatusReader(Protocol):
    def read_status(self) -> VerifiedGuardianStatus:
        """Return cryptographically verified status without mutation authority."""
