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


def test_self_change_workers_are_explicitly_enablement_gated() -> None:
    planner = _unit("melloa-self-change-planner.service")
    applier = _unit("melloa-self-change-applier.service")
    gate = (ROOT / "infra/server/self-change-enabled.sh").read_text(encoding="utf-8")
    default_environment = (
        ROOT / "infra/server/self-change.env.example"
    ).read_text(encoding="utf-8")

    for unit in (planner, applier):
        assert "EnvironmentFile=/etc/melloa/self-change.env" in unit
        assert "ExecCondition=/usr/local/libexec/melloa/self-change-enabled" in unit
    assert "Environment=MELLOA_CODEX_USE_API_KEY=true" not in planner
    assert "MELLOA_SELF_CHANGE_ENABLED=false" in default_environment
    assert "MELLOA_CODEX_USE_API_KEY=false" in default_environment
    assert '[[ "$ENABLED" == false ]]' in gate
    assert "exit 1" in gate
    assert "exit 255" in gate


def test_codex_cli_is_optional_until_self_change_workers_are_enabled() -> None:
    bootstrap = (ROOT / "infra/server/bootstrap-debian.sh").read_text(
        encoding="utf-8"
    )
    preflight = (ROOT / "infra/server/preflight.sh").read_text(encoding="utf-8")
    first_install = (ROOT / "infra/server/first-install.sh").read_text(
        encoding="utf-8"
    )

    bootstrap_required_commands = (
        bootstrap.split("for command in bwrap ", 1)[1].split("; do", 1)[0].split()
    )
    preflight_required_commands = (
        preflight.split("for command in \\\n", 1)[1].split("; do", 1)[0].split()
    )

    assert "SELF_CHANGE_TOOLS=false" in bootstrap
    assert "--self-change-tools" in bootstrap
    assert "verify_codex_cli" in bootstrap
    assert 'if [[ "$SELF_CHANGE_TOOLS" == true ]]; then' in bootstrap
    assert "codex" not in bootstrap_required_commands
    assert "codex" not in preflight_required_commands
    assert "verify_codex_cli" in preflight
    assert "require_codex_self_change_tools" in first_install
    assert "optional self-change workers require Codex CLI" in first_install


def test_guided_first_install_defaults_self_change_for_real_interactive_qualification() -> None:
    first_install = (ROOT / "infra/server/first-install.sh").read_text(
        encoding="utf-8"
    )

    assert "self_change_prompt_default()" in first_install
    assert '[[ "$DESTINATION_ROOT" == / && -t 0 ]]' in first_install
    assert "printf 'yes'" in first_install
    assert "printf 'no'" in first_install
    assert 'readonly SELF_CHANGE_DEFAULT="$(self_change_prompt_default)"' in first_install
    assert (
        '"Enable bounded self-change workers for readiness qualification" '
        '"$SELF_CHANGE_DEFAULT"'
    ) in first_install
    assert "conversation-only bring-up, not a readiness qualification" in first_install


def test_guided_first_install_suppresses_lower_level_installer_handoff() -> None:
    installer = (ROOT / "infra/server/install.sh").read_text(encoding="utf-8")
    first_install = (ROOT / "infra/server/first-install.sh").read_text(
        encoding="utf-8"
    )

    assert "--guided-first-install" in first_install
    assert "GUIDED_FIRST_INSTALL=false" in installer
    assert "--guided-first-install)" in installer
    assert (
        "Server service assets installed; continuing guided first-owner setup."
        in installer
    )
    guided_branches = installer.split('if [[ "$GUIDED_FIRST_INSTALL" == true ]]; then')[
        1:
    ]
    assert len(guided_branches) == 2
    for branch in guided_branches:
        guided_branch = branch.split("fi", 1)[0]
        assert "Pair the dedicated Telegram bot" not in guided_branch
        assert "Or run the guided first-owner setup" not in guided_branch


def test_guided_first_install_reports_safe_activation_and_verification_recovery() -> None:
    first_install = (ROOT / "infra/server/first-install.sh").read_text(
        encoding="utf-8"
    )

    assert "first_install_resume_command" in first_install
    assert "sudo /usr/local/libexec/melloa/first-install" in first_install
    assert "if ! \"$activate_bin\" \"${activate_args[@]}\"; then" in first_install
    assert (
        "activation failed; fix the reported cause, then rerun $resume_command"
        in first_install
    )
    assert "Existing private configuration will be reused" in first_install
    assert "if ! \"$verify_bin\" --source \"$SOURCE\"; then" in first_install
    assert (
        "owner verification failed; fix the reported cause or send the exact Telegram phrase"
        in first_install
    )


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


def test_server_activation_reports_phase_specific_safe_recovery_commands() -> None:
    activation = (ROOT / "infra/server/activate.sh").read_text(encoding="utf-8")

    assert "activation_rerun_command" in activation
    assert "sudo /usr/local/libexec/melloa/activate" in activation
    assert (
        "pre-activation live Guardian, model, or Telegram check failed; "
        "fix the reported cause"
    ) in activation
    assert (
        "release deployment failed; run sudo systemctl start "
        "melloa-release-recovery.service"
    ) in activation
    assert (
        "the first post-activation encrypted backup failed; fix the reported backup cause"
        in activation
    )
