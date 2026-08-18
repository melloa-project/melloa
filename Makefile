UV_CACHE_DIR ?= .cache/uv
UV := UV_CACHE_DIR=$(UV_CACHE_DIR) uv
GUARDIAN_ROOT ?= ../melloa-guardian
PREVIEW_STATE_DIR ?=
PREVIEW_STATE_ARG := $(if $(strip $(PREVIEW_STATE_DIR)),--state-dir "$(PREVIEW_STATE_DIR)")
SBOM_OUTPUT ?= dist/melloa-dependency-sbom.cdx.json

.PHONY: bootstrap bootstrap-docs bootstrap-python check check-generated dependency-sources docs integration lint preview recovery sbom sbom-check spec test typecheck web

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
		--guardian-root "$(GUARDIAN_ROOT)" $(PREVIEW_STATE_ARG)

bootstrap-python: dependency-sources
	$(UV) sync --frozen --all-groups --no-install-project
	$(UV) sync --frozen --all-groups --no-build-isolation-package melloa

bootstrap-docs: dependency-sources
	$(UV) sync --frozen --no-default-groups --group docs --group build --no-install-project
	$(UV) sync --frozen --no-default-groups --group docs --group build --no-build-isolation-package melloa

check: check-generated dependency-sources lint typecheck test web spec docs

dependency-sources:
	python3 tools/check_dependency_sources.py

sbom: dependency-sources
	python3 tools/generate_dependency_sbom.py --guardian-root "$(GUARDIAN_ROOT)" --output "$(SBOM_OUTPUT)"

sbom-check: dependency-sources
	python3 tools/generate_dependency_sbom.py --guardian-root "$(GUARDIAN_ROOT)" --output "$(SBOM_OUTPUT)" --check

check-generated:
	$(UV) run python tools/build_consolidated.py --check
	$(UV) run python tools/generate_schemas.py --check
	$(UV) run python tools/update_migration_manifest.py --check
	$(UV) run python tools/update_manifest.py --check
	bash -n tools/m0_restore_drill.sh tools/test_postgres_integration.sh

lint:
	$(UV) run ruff check src tests \
		tools/build_consolidated.py \
		tools/check_dependency_sources.py \
		tools/dependency_source_policy.py \
		tools/generate_dependency_sbom.py \
		tools/generate_schemas.py \
		tools/update_manifest.py \
		tools/update_migration_manifest.py \
		tools/validate_spec.py

typecheck:
	$(UV) run mypy src

test:
	$(UV) run pytest tests/unit -q

web:
	npm --prefix apps/web run typecheck
	npm --prefix apps/web test
	npm --prefix apps/web run build

spec:
	$(UV) run python tools/validate_spec.py --check-json validation.json --check-report VALIDATION.md >/dev/null

docs:
	$(UV) run --frozen --no-sync mkdocs build --strict

integration:
	bash tools/test_postgres_integration.sh

recovery:
	bash tools/m0_restore_drill.sh
