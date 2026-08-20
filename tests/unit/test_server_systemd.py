from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SYSTEMD = ROOT / "infra/server/systemd"


def _unit(name: str) -> str:
    return (SYSTEMD / name).read_text(encoding="utf-8")


def test_release_recovery_precedes_both_self_change_workers() -> None:
    recovery = _unit("melloa-release-recovery.service")
    planner = _unit("melloa-self-change-planner.service")
    applier = _unit("melloa-self-change-applier.service")

    assert "server_release.sh recover" in recovery
    assert (
        "Before=melloa-self-change-planner.service melloa-self-change-applier.service"
        in recovery
    )
    assert "Requires=melloa-release-recovery.service" in planner
    assert "After=melloa-release-recovery.service" in planner
    assert "Requires=melloa-release-recovery.service" in applier
    assert "After=melloa-release-recovery.service" in applier


def test_planner_has_only_bounded_root_broker_authority() -> None:
    planner = _unit("melloa-self-change-planner.service")

    assert "User=root" in planner
    assert (
        "CapabilityBoundingSet=CAP_CHOWN CAP_DAC_OVERRIDE CAP_FOWNER CAP_SETGID CAP_SETUID"
        in planner
    )
    assert "LoadCredential=planner-dsn:" in planner
    assert "LoadCredential=codex-api-key:" in planner
    assert "/run/docker.sock" in planner
    assert "/var/run/docker.sock" in planner
    assert "/srv/melloa/release-source" in planner
    assert "/var/lib/melloa/release-state" in planner
    assert "EnvironmentFile=-/etc/melloa/release.env" not in planner


def test_applier_has_release_authority_without_model_credentials() -> None:
    applier = _unit("melloa-self-change-applier.service")

    assert "CapabilityBoundingSet=\n" in applier
    assert "LoadCredential=applier-dsn:" in applier
    assert "LoadCredential=codex-api-key:" not in applier
    assert "UnsetEnvironment=CODEX_HOME OPENAI_API_KEY" in applier
    assert "/var/lib/melloa/codex-agent" in applier
    assert "/etc/melloa/private/codex-api-key" in applier
    assert "/etc/melloa/private/model-credentials" in applier


def test_all_server_services_apply_the_common_hardening_floor() -> None:
    for path in sorted(SYSTEMD.glob("*.service")):
        unit = path.read_text(encoding="utf-8")
        assert "NoNewPrivileges=yes" in unit
        assert "PrivateDevices=yes" in unit
        assert "PrivateTmp=yes" in unit
        assert "ProtectControlGroups=yes" in unit
        assert "ProtectHome=yes" in unit
        assert "ProtectKernelModules=yes" in unit
        assert "ProtectKernelTunables=yes" in unit
        assert "ProtectSystem=strict" in unit
        assert "RestrictSUIDSGID=yes" in unit
        assert "SystemCallArchitectures=native" in unit


def test_external_verifier_imports_the_candidate_without_syncing_dependencies() -> None:
    verifier = (ROOT / "tools/self_change_verify.sh").read_text(encoding="utf-8")

    assert '--setenv PYTHONPATH "$CHECKOUT/src"' in verifier
    assert "--setenv UV_NO_SYNC 1" in verifier


def test_server_installer_packages_only_tracked_worker_code_and_reconciles_checkouts() -> None:
    installer = (ROOT / "infra/server/install.sh").read_text(encoding="utf-8")

    assert 'git -C "$SOURCE" archive --format=tar "$SOURCE_REVISION"' in installer
    assert '--no-owner --no-group --chmod=D0755,F0644' in installer
    assert 'chown -R root:root /opt/melloa/worker' in installer
    assert 'reset --quiet --hard "$SOURCE_REVISION"' in installer


def test_server_activation_orders_recovery_before_release_and_workers() -> None:
    activation = (ROOT / "infra/server/activate.sh").read_text(encoding="utf-8")

    recovery = activation.index("systemctl start melloa-release-recovery.service")
    deployment = activation.index('"$RELEASE_SOURCE/tools/server_release.sh" deploy')
    workers = activation.index("systemctl restart \\")
    assert recovery < deployment < workers
    assert "deployment-check" in activation
    assert "backup once" in activation
