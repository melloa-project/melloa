UV_CACHE_DIR ?= .cache/uv
UV_SYSTEM_CERTS ?= true
UV := UV_CACHE_DIR=$(UV_CACHE_DIR) UV_SYSTEM_CERTS=$(UV_SYSTEM_CERTS) uv
GUARDIAN_ROOT ?= ../melloa-guardian
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
endif

.PHONY: bootstrap bootstrap-python check check-generated integration lint preview recovery test typecheck web

bootstrap: bootstrap-python
	npm --prefix apps/web ci --ignore-scripts

preview:
	@test -f "$(GUARDIAN_ROOT)/go.mod" || { \
		echo "Guardian checkout not found at $(GUARDIAN_ROOT). Clone https://github.com/melloa-project/melloa-guardian.git beside this repository." >&2; \
		exit 2; \
	}
	$(MAKE) bootstrap
	$(MAKE) -C "$(GUARDIAN_ROOT)" check build
	npm --prefix apps/web run build
	$(UV) run --frozen --no-sync python -m melloa.apps.local_preview \
		--guardian-root "$(GUARDIAN_ROOT)" $(PREVIEW_STATE_ARG) $(PREVIEW_MODEL_ARG)

bootstrap-python:
	$(UV) sync --frozen --all-groups --no-install-project
	$(UV) sync --frozen --all-groups --no-build-isolation-package melloa

check: check-generated lint typecheck test web

check-generated:
	$(UV) run python tools/update_migration_manifest.py --check
	bash -n tools/restore_drill.sh tools/test_postgres_integration.sh

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
