from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCS_SITE = ROOT / "docs-site"


def test_public_site_source_replaces_stale_preview_framing() -> None:
    homepage = (DOCS_SITE / "src/content/docs/index.mdx").read_text(
        encoding="utf-8"
    )
    command_spine = (DOCS_SITE / "src/components/CommandSpine.astro").read_text(
        encoding="utf-8"
    )
    status_strip = (DOCS_SITE / "src/components/StatusStrip.astro").read_text(
        encoding="utf-8"
    )

    assert "Run Melloa on a home server" in homepage
    assert "setup discovers your numeric owner ID during private pairing" in homepage
    assert "hosted OpenAI-compatible model routes" in homepage
    assert "You do not need a local GPU or local model to begin" in homepage
    assert "gpt-5.6-luna" in homepage
    assert "Melloa is not starting as a generic multi-agent harness" in homepage
    assert "Harness comparison" in homepage
    assert "Hermes is the most relevant reference for the later proactive layer" in homepage
    assert "proactive goal loop" in homepage
    assert "Goals become loops" in homepage
    assert "RuntimeLoop" in homepage
    assert "StatusStrip" in homepage
    assert "Self-change is core" in homepage
    assert "CommandSpine" in homepage
    assert "Implemented path" in status_strip
    assert "One real dedicated-server run" in status_strip
    assert "Fork decision" in status_strip
    assert "First server path" in command_spine
    assert "findmnt --mountpoint /mnt/melloa-off-device-backup" in command_spine
    assert 'stat --format=\'%d\' /mnt/melloa-off-device-backup' in command_spine
    assert (
        'sudo infra/server/bootstrap-debian.sh --source "$PWD" --self-change-tools'
        in command_spine
    )
    assert (
        "git clone https://github.com/melloa-project/melloa-guardian.git"
        in command_spine
    )
    assert "make preview-state" in command_spine
    assert 'sudo infra/server/first-install.sh --source "$PWD"' in command_spine
    assert "owner-approved self-change" in command_spine
    runtime_loop = (DOCS_SITE / "src/components/RuntimeLoop.astro").read_text(
        encoding="utf-8"
    )
    assert "Message → reply → self-change → restart and recover" in runtime_loop
    assert "routes do not silently fall back" in runtime_loop

    stale_claims = [
        "not ready",
        "incomplete",
        "v0.2.0 preview",
        "milestone M1",
        "architecture baseline",
        "Current release",
        "Start Melloa locally",
    ]
    for claim in stale_claims:
        assert claim not in homepage


def test_readme_opens_with_first_owner_server_path() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    opening = readme.split("## Current status", 1)[0]

    assert "## Start here: first-owner home server" in opening
    assert "https://melloa-project.github.io/melloa/deploy/" in opening
    assert "findmnt --mountpoint /mnt/melloa-off-device-backup" in opening
    assert 'sudo infra/server/bootstrap-debian.sh --source "$PWD" --self-change-tools' in opening
    assert 'sudo infra/server/first-install.sh --source "$PWD"' in opening
    assert "## Evidence status" in opening
    assert "Telegram message → routed hosted-model reply" in opening
    assert "separate conversation adapter" in readme
    assert "OpenClaw, Hermes, AgentTeams, GBrain-style" in readme
    assert "exact-owner Telegram, hosted model routing" in readme
    assert "Deployment readiness: NOT READY" not in opening
    assert "Do not deploy this repository" not in opening
    assert "disposable preview" not in opening
    assert "readiness banner" not in readme


def test_repository_deployment_guide_is_actionable_not_warning_first() -> None:
    guide = (ROOT / "docs/server-deployment.md").read_text(encoding="utf-8")
    opening = guide.split("## Supported starting point", 1)[0]
    normalized_guide = " ".join(guide.split())
    server_reference = (ROOT / "infra/server/README.md").read_text(
        encoding="utf-8"
    )

    assert "Follow it on\nthe real server" in opening
    assert "The current gap is evidence, not a second hidden installation path" in opening
    assert "Telegram message → hosted model reply → owner-approved" in opening
    assert "not a generic\nmulti-agent harness" in opening
    assert "gpt-5.6-luna" in guide
    assert "separate reviewed hardening pass" in normalized_guide
    assert "findmnt --mountpoint /mnt/melloa-off-device-backup" in opening
    assert "Self-change proof" in guide
    assert "readiness banner" not in guide
    assert "NOT READY" not in guide
    assert "not ready" not in guide.lower()
    assert "Self-change qualification" not in guide
    assert "NOT READY" not in server_reference
    assert "readiness banner" not in server_reference


def test_local_preview_is_not_presented_as_first_run_path() -> None:
    preview = (ROOT / "docs/getting-started.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    development = (ROOT / "docs/development.md").read_text(encoding="utf-8")
    login = (ROOT / "apps/web/src/pages/login.tsx").read_text(encoding="utf-8")

    assert preview.startswith("# Local disposable preview")
    assert "For first owner deployment" in preview
    assert "server-deployment.md" in preview
    assert "## Start the disposable preview" in preview
    assert "## Current limitations" not in preview
    assert "short baseline guide" not in readme
    assert "[getting started](getting-started.md)" not in development
    assert "First run? See <code>docs/getting-started.md</code>" not in login
    assert "Server setup: <code>docs/server-deployment.md</code>" in login


def test_public_site_is_static_pages_source_not_mkdocs() -> None:
    workflow = (ROOT / ".github/workflows/pages.yml").read_text(encoding="utf-8")
    config = (DOCS_SITE / "astro.config.mjs").read_text(encoding="utf-8")

    assert "path: docs-site/dist" in workflow
    assert "starlight" in config
    assert "mkdocs" not in workflow.lower()
    assert (DOCS_SITE / "public/.nojekyll").is_file()
    assert not (DOCS_SITE / "src/pages/404.astro").exists()


def test_public_site_has_actionable_deployment_and_self_change_pages() -> None:
    deploy = (DOCS_SITE / "src/content/docs/deploy.mdx").read_text(
        encoding="utf-8"
    )
    self_change = (DOCS_SITE / "src/content/docs/self-change.mdx").read_text(
        encoding="utf-8"
    )
    runtime_loop = (DOCS_SITE / "src/content/docs/runtime-loop.mdx").read_text(
        encoding="utf-8"
    )
    harnesses = (DOCS_SITE / "src/content/docs/harnesses.mdx").read_text(
        encoding="utf-8"
    )
    normalized_runtime_loop = " ".join(runtime_loop.split())

    assert "sudo apt-get install --yes --no-install-recommends ca-certificates git" in deploy
    assert "findmnt --mountpoint /mnt/melloa-off-device-backup" in deploy
    assert 'sudo infra/server/bootstrap-debian.sh --source "$PWD" --self-change-tools' in deploy
    assert "git clone https://github.com/melloa-project/melloa-guardian.git" in deploy
    assert "make preview-state" in deploy
    assert "Press Enter at the Guardian prompts" in deploy
    assert 'sudo infra/server/first-install.sh --source "$PWD"' in deploy
    assert "Leave blank to pair now" in deploy
    assert "exact `/start ...` phrase" in deploy
    assert "sudo /usr/local/libexec/melloa/verify-owner-journey" in deploy
    assert "sudo /usr/local/libexec/melloa/restore-drill" in deploy
    assert "`api-key`" in deploy
    assert "@BotFather" in deploy
    assert "/newbot" in deploy
    assert "Do not send `/start` to the bot yet" in deploy
    assert "current input/output prices as GBP decimals" in deploy
    assert "The `openai` preset fills the OpenAI HTTPS base URL" in deploy
    assert "gpt-5.6-luna" in deploy
    assert "gpt-5.6-terra` as the capable default" in deploy
    assert "(../runtime-loop/)" in deploy
    assert "/change diff <change_id>" in deploy
    assert "/change approve <change_id> <16-character proposal token>" in deploy
    assert "qualification-record" in deploy
    assert "/change propose" in self_change
    assert "/change show <change_id>" in self_change
    assert "Avoid recovery-spine changes" in self_change
    assert "commits, pushes, deploys" in self_change
    assert "Codex CLI is the confined planner" in self_change
    assert "disposable checkout outside the active runtime" in self_change
    assert "Do not fork Hermes, OpenClaw, AgentTeams" in runtime_loop
    assert "AgentTeams/OpenClaw-style stacks" in runtime_loop
    assert "Hermes deserves special attention after this base loop" in runtime_loop
    assert "event hooks and external datastore writes" in normalized_runtime_loop
    assert "separate conversation adapter" in runtime_loop
    assert "no source checkout" in runtime_loop
    assert "do not fork OpenClaw, Hermes, AgentTeams, or GBrain" in harnesses
    assert "Hermes is the serious proactive-loop reference" in harnesses
    assert "scheduled checks that decide whether to message the owner" in harnesses
    assert "email, calendar, webhook, or filesystem events" in harnesses
    assert "creating a small owner-facing task app" in harnesses
    assert "run a focused Hermes-adoption spike" in harnesses
    assert "exact one-owner Telegram binding" in harnesses
    assert "retained proposal diffs and exact owner approval" in harnesses
    assert "independent Guardian remaining outside" in harnesses


def test_public_site_uses_github_pages_safe_links() -> None:
    homepage = (DOCS_SITE / "src/content/docs/index.mdx").read_text(
        encoding="utf-8"
    )
    deploy = (DOCS_SITE / "src/content/docs/deploy.mdx").read_text(
        encoding="utf-8"
    )
    config = (DOCS_SITE / "astro.config.mjs").read_text(encoding="utf-8")

    assert "base: \"/melloa\"" in config
    assert "edit/main/docs-site/" in config
    assert "link: ./deploy/" in homepage
    assert "link: ./self-change/" in homepage
    assert "link: ./proactive-goals/" in homepage
    assert "(./deploy/)" in homepage
    assert "(./runtime-loop/)" in homepage
    assert "(./harnesses/)" in homepage
    assert "(./proactive-goals/)" in homepage
    assert "(../self-change/)" in deploy
    assert "(../runtime-loop/)" in deploy
    assert "link: /deploy/" not in homepage
    assert "](/deploy/)" not in homepage


def test_public_site_captures_proactive_goal_direction_without_expanding_install() -> None:
    proactive = (DOCS_SITE / "src/content/docs/proactive-goals.mdx").read_text(
        encoding="utf-8"
    )
    config = (DOCS_SITE / "astro.config.mjs").read_text(encoding="utf-8")
    product_direction = (ROOT / "PRODUCT_DIRECTION.md").read_text(encoding="utf-8")

    assert "Proactive goal work is part of Melloa's intended direction" in proactive
    assert "Deterministic connectors collect agreed facts" in proactive
    assert "calendar events, email metadata, Strava or workout" in proactive
    assert "task completions, webhook payloads" in proactive
    assert "Scheduled jobs aggregate state without calling a model for every event" in proactive
    assert "owner approval, capability checks, cost limits, provenance" in proactive
    assert "Hermes-style cron, skills, provider switching" in proactive
    assert "Proactive goals" in config
    assert "goal-first and event-bounded" in product_direction
    assert "not ambient autonomy" in product_direction
