from __future__ import annotations

import pytest

from melloa.application.release_activation import ReleaseActivationGate


def test_release_activation_requires_exact_protected_revision(tmp_path) -> None:
    active = tmp_path / "active-revision"
    active.write_text("abc123\n", encoding="ascii")
    active.chmod(0o644)

    assert ReleaseActivationGate(active, "abc123").is_active()
    assert not ReleaseActivationGate(active, "def456").is_active()

    active.chmod(0o666)
    assert not ReleaseActivationGate(active, "abc123").is_active()


def test_release_activation_fails_closed_for_missing_symlink_or_invalid_revision(
    tmp_path,
) -> None:
    missing = tmp_path / "missing"
    assert not ReleaseActivationGate(missing, "abc123").is_active()

    target = tmp_path / "target"
    target.write_text("abc123\n", encoding="ascii")
    target.chmod(0o600)
    linked = tmp_path / "linked"
    linked.symlink_to(target)
    assert not ReleaseActivationGate(linked, "abc123").is_active()

    with pytest.raises(ValueError, match="revision"):
        ReleaseActivationGate(target, "invalid revision")
