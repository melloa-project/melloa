UV_CACHE_DIR ?= .cache/uv
UV_SYSTEM_CERTS ?= true
UV := UV_CACHE_DIR=$(UV_CACHE_DIR) UV_SYSTEM_CERTS=$(UV_SYSTEM_CERTS) uv
WEB_INSTALL_STAMP := apps/web/node_modules/.package-lock.json
GUARDIAN_STATUS ?=
GUARDIAN_PUBLIC_KEY ?=
PREVIEW_STATE_DIR ?=
PREVIEW_STATE_ARG := $(if $(strip $(PREVIEW_STATE_DIR)),--state-dir "$(PREVIEW_STATE_DIR)")
PREVIEW_MODEL ?=
PREVIEW_MODEL_ARG :=
ifeq ($(strip $(PREVIEW_MODEL)),ollama)
PREVIEW_MODEL_ARG := --model-config "$(CURDIR)/config/model/ollama.example.json"
endif

ifneq ($(filter preview,$(MAKECMDGOALS)),)
ifneq ($(strip $(PREVIEW_MODEL)),)
ifneq ($(strip $(PREVIEW_MODEL)),ollama)
$(error Unknown PREVIEW_MODEL '$(PREVIEW_MODEL)'. Supported value: ollama; leave it empty for a preview without conversation)
endif
endif
ifeq ($(strip $(GUARDIAN_STATUS)),)
$(error GUARDIAN_STATUS is required; prepare an owner-controlled public handoff first (docs/getting-started.md))
endif
ifeq ($(strip $(GUARDIAN_PUBLIC_KEY)),)
$(error GUARDIAN_PUBLIC_KEY is required; prepare an owner-controlled public handoff first (docs/getting-started.md))
endif
endif

.PHONY: bootstrap bootstrap-python check check-generated integration lint preview preview-web recovery server-bootstrap server-runtime test typecheck web

bootstrap: bootstrap-python
	npm --prefix apps/web ci --ignore-scripts

preview:
	@test -f "$(GUARDIAN_STATUS)" && test ! -L "$(GUARDIAN_STATUS)" && test -r "$(GUARDIAN_STATUS)" || { \
		echo "GUARDIAN_STATUS must be a readable regular file, not a symlink." >&2; \
		exit 2; \
	}
	@test -f "$(GUARDIAN_PUBLIC_KEY)" && test ! -L "$(GUARDIAN_PUBLIC_KEY)" && test -r "$(GUARDIAN_PUBLIC_KEY)" || { \
		echo "GUARDIAN_PUBLIC_KEY must be a readable regular file, not a symlink." >&2; \
		exit 2; \
	}
	$(MAKE) bootstrap-python
	$(UV) run --frozen --no-sync python -m melloa.apps.local_preview \
		--guardian-status "$(GUARDIAN_STATUS)" \
		--guardian-public-key "$(GUARDIAN_PUBLIC_KEY)" \
		--verify-guardian-only
	$(MAKE) preview-web
	npm --prefix apps/web run build
	$(UV) run --frozen --no-sync python -m melloa.apps.local_preview \
		--guardian-status "$(GUARDIAN_STATUS)" \
		--guardian-public-key "$(GUARDIAN_PUBLIC_KEY)" \
		$(PREVIEW_STATE_ARG) $(PREVIEW_MODEL_ARG)

preview-web: $(WEB_INSTALL_STAMP)

$(WEB_INSTALL_STAMP): apps/web/package-lock.json apps/web/package.json .nvmrc
	npm --prefix apps/web ci --ignore-scripts

bootstrap-python:
	$(UV) sync --frozen --all-groups --no-install-project
	$(UV) sync --frozen --all-groups --no-build-isolation-package melloa

check: check-generated lint typecheck test web

check-generated:
	$(UV) run python tools/update_migration_manifest.py --check
	bash -n \
		infra/server/activate.sh \
		infra/server/backup.sh \
		infra/server/bootstrap-debian.sh \
		infra/server/codex-wrapper.sh \
		infra/server/configure.sh \
		infra/server/first-install.sh \
		infra/server/install.sh \
		infra/server/preflight.sh \
		infra/server/reconcile-logins.sh \
		infra/server/rollback.sh \
		infra/server/restore-drill.sh \
		infra/server/self-change-enabled.sh \
		infra/server/self-change-apply.sh \
		infra/server/self-change-plan.sh \
		infra/server/update.sh \
		infra/server/verify-owner-journey.sh \
		tools/server_release.sh \
		tools/self_change_verify.sh \
		tools/restore_drill.sh \
		tools/test_postgres_integration.sh \
		tools/test_server_bootstrap.sh \
		tools/test_server_configuration.sh \
		tools/test_server_first_install.sh \
		tools/test_server_installer.sh \
		tools/test_server_owner_verification.sh \
		tools/test_server_restore_drill.sh \
		tools/test_server_update_rollback.sh \
		tools/test_server_runtime.sh
	bash tools/test_server_configuration.sh
	bash tools/test_server_first_install.sh
	bash tools/test_server_installer.sh
	bash tools/test_server_owner_verification.sh
	bash tools/test_server_restore_drill.sh
	bash tools/test_server_update_rollback.sh

lint:
	$(UV) run ruff check src tests \
		tools/recovery_owner_journey.py \
		tools/update_migration_manifest.py

typecheck:
	$(UV) run mypy src

test:
	$(UV) run pytest tests/unit -q

web:
	npm --prefix apps/web run typecheck
	npm --prefix apps/web test
	npm --prefix apps/web run build

integration:
	bash tools/test_postgres_integration.sh

recovery:
	bash tools/restore_drill.sh

server-runtime:
	bash tools/test_server_runtime.sh

server-bootstrap:
	bash tools/test_server_bootstrap.sh
