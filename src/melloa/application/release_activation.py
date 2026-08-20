"""Read-only gate that keeps background work held until a release is active."""

from __future__ import annotations

import os
import re
import stat
from pathlib import Path

_MAX_ACTIVATION_BYTES = 128
_REVISION = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$")


class ReleaseActivationGate:
    def __init__(self, path: Path, revision: str) -> None:
        if _REVISION.fullmatch(revision) is None:
            raise ValueError("source revision has an invalid activation identifier")
        self._path = path
        self._revision = revision

    def is_active(self) -> bool:
        try:
            descriptor = os.open(self._path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
        except OSError:
            return False
        try:
            metadata = os.fstat(descriptor)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_mode & 0o022
                or not 1 <= metadata.st_size <= _MAX_ACTIVATION_BYTES
            ):
                return False
            document = os.read(descriptor, _MAX_ACTIVATION_BYTES + 1)
        except OSError:
            return False
        finally:
            os.close(descriptor)
        if not document or len(document) > _MAX_ACTIVATION_BYTES:
            return False
        try:
            active_revision = document.decode("ascii").removesuffix("\n")
        except UnicodeDecodeError:
            return False
        return active_revision == self._revision


__all__ = ["ReleaseActivationGate"]
