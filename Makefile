UV_CACHE_DIR ?= .cache/uv
UV := UV_CACHE_DIR=$(UV_CACHE_DIR) uv

.PHONY: bootstrap check check-generated dependency-sources docs integration lint recovery spec test typecheck web

bootstrap: dependency-sources
	$(UV) sync --frozen --all-groups
	npm --prefix apps/web ci --ignore-scripts

check: check-generated dependency-sources lint typecheck test web spec docs

dependency-sources:
	python3 tools/check_dependency_sources.py

check-generated:
	$(UV) run python tools/generate_schemas.py --check
	$(UV) run python tools/update_migration_manifest.py --check
	$(UV) run python tools/update_manifest.py --check
	bash -n tools/m0_restore_drill.sh tools/test_postgres_integration.sh

lint:
	$(UV) run ruff check src tests tools/check_dependency_sources.py tools/generate_schemas.py tools/update_manifest.py tools/update_migration_manifest.py

typecheck:
	$(UV) run mypy src

test:
	$(UV) run pytest tests/unit -q

web:
	npm --prefix apps/web run typecheck
	npm --prefix apps/web test
	npm --prefix apps/web run build

spec:
	$(UV) run python tools/validate_spec.py --json /tmp/melloa-validation.json >/dev/null

docs:
	$(UV) run mkdocs build --strict

integration:
	bash tools/test_postgres_integration.sh

recovery:
	bash tools/m0_restore_drill.sh
