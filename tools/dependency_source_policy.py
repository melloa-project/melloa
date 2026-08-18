"""Shared dependency source URL policy for lockfile validation."""

from __future__ import annotations

import base64
import binascii
import re
from typing import Any, Literal
from urllib.parse import urlsplit

_RAW_CONTROL_OR_WHITESPACE = re.compile(r"[\u0000-\u0020\u007f]")
_LOWERCASE_SHA256 = re.compile(r"sha256:([0-9a-f]{64})")
_SRI_ALGORITHMS = {
    "sha256": ("SHA-256", 32),
    "sha384": ("SHA-384", 48),
    "sha512": ("SHA-512", 64),
}


def is_approved_https_url(value: str, allowed_hosts: frozenset[str]) -> bool:
    """Accept only raw, credential-free HTTPS URLs on reviewed registry hosts."""

    if not isinstance(value, str) or not value.startswith("https://"):
        return False
    if _RAW_CONTROL_OR_WHITESPACE.search(value):
        return False
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except (UnicodeError, ValueError):
        return False
    return (
        parsed.scheme == "https"
        and parsed.hostname in allowed_hosts
        and parsed.netloc == parsed.hostname
        and parsed.username is None
        and parsed.password is None
        and port is None
        and not parsed.query
        and not parsed.fragment
    )


def approved_python_source_kind(
    value: Any,
    allowed_hosts: frozenset[str],
) -> Literal["editable", "registry"] | None:
    """Classify the two uv package source shapes this repository permits."""

    if not isinstance(value, dict):
        return None
    if value == {"editable": "."}:
        return "editable"
    if set(value) == {"registry"} and isinstance(value["registry"], str):
        if is_approved_https_url(value["registry"], allowed_hosts):
            return "registry"
    return None


def lowercase_sha256_content(value: Any) -> str | None:
    """Return a canonical uv SHA-256 digest, or reject the lock value."""

    if not isinstance(value, str):
        return None
    match = _LOWERCASE_SHA256.fullmatch(value)
    return match.group(1) if match is not None else None


def supported_sri_hashes(value: Any) -> tuple[tuple[str, str], ...] | None:
    """Parse supported npm SRI hashes into sorted CycloneDX algorithm/digest pairs."""

    if not isinstance(value, str):
        return None
    hashes: list[tuple[str, str]] = []
    for item in value.split():
        algorithm, separator, encoded = item.partition("-")
        if not separator or algorithm not in _SRI_ALGORITHMS:
            return None
        try:
            decoded = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError):
            return None
        cyclone_algorithm, digest_size = _SRI_ALGORITHMS[algorithm]
        if len(decoded) != digest_size:
            return None
        hashes.append((cyclone_algorithm, decoded.hex()))
    return tuple(sorted(hashes)) or None
