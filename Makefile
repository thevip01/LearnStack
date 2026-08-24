.DEFAULT_GOAL := help
COMPOSE := docker compose
SCHEMA := packages/knowledge-schema
SUBJECTS := subjects

.PHONY: help
help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'

# ---------------------------------------------------------------------------
# Stack
# ---------------------------------------------------------------------------

.PHONY: up
up: runner ## Build the runner image, then bring the whole stack up
	$(COMPOSE) up --build -d
	@echo
	@echo "  web  http://localhost:$${WEB_PORT:-3000}"
	@echo "  api  http://localhost:$${API_PORT:-8000}/docs"
	@echo "  demo demo@learnos.dev / learnos-demo-2026"
	@echo
	@echo "  waiting on /readyz ..."
	@$(MAKE) --no-print-directory wait-ready
	@echo
	@echo "  then: make verify-loop"

.PHONY: down
down: ## Stop the stack, keep volumes
	$(COMPOSE) down

.PHONY: nuke
nuke: ## Stop the stack and delete all data
	$(COMPOSE) down -v

.PHONY: logs
logs: ## Tail logs for every service
	$(COMPOSE) logs -f --tail=100

.PHONY: ps
ps: ## Show service status
	$(COMPOSE) ps

.PHONY: runner
runner: ## Build the sandbox runner image the execution service launches
	docker build -t learnos/runner-python:3.12 infrastructure/docker/runner-python

.PHONY: wait-ready
wait-ready: ## Block until the API reports ready
	@for i in $$(seq 1 60); do \
		if curl -fsS http://localhost:$${API_PORT:-8000}/readyz >/dev/null 2>&1; then \
			curl -fsS http://localhost:$${API_PORT:-8000}/readyz; echo; exit 0; fi; \
		sleep 2; done; \
	echo "api did not become ready; try 'make logs'" >&2; exit 1

.PHONY: shell-api
shell-api: ## Shell into the running api container
	$(COMPOSE) exec api bash

.PHONY: psql
psql: ## Open psql against the dev database
	$(COMPOSE) exec postgres psql -U learnos -d learnos

# ---------------------------------------------------------------------------
# Local (host) development, which needs a virtualenv and node installed
# ---------------------------------------------------------------------------

.PHONY: install
install: ## Install python packages editable + web deps on the host
	pip install -e $(SCHEMA)[dev] -e services/sandbox[dev] -e apps/api[dev] -e services/ingestion[dev]
	cd apps/web && npm install

.PHONY: dev-api
dev-api: ## Run the API on the host with reload
	cd apps/api && uvicorn learnos_api.main:app --reload --port $${API_PORT:-8000}

.PHONY: dev-web
dev-web: ## Run the web app on the host with reload
	cd apps/web && npm run dev

.PHONY: dev-local
dev-local: ## Run the whole stack on the host with no Docker, Postgres or Redis
	tools/dev_local.sh

.PHONY: dev-local-api
dev-local-api: ## Same, but the API only
	tools/dev_local.sh --api-only

# ---------------------------------------------------------------------------
# Content
# ---------------------------------------------------------------------------

.PHONY: validate
validate: ## Validate every subject package (needs pydantic installed)
	learnos-validate check $(SUBJECTS) --strict

.PHONY: validate-nodeps
validate-nodeps: ## Validate subject packages with the stdlib-only checker
	python3 $(SUBJECTS)/validate_package.py $(SUBJECTS)/programming/python

.PHONY: schemas
schemas: ## Export JSON Schema for every content model
	learnos-validate export-schema --out docs/schemas

.PHONY: reload-subjects
reload-subjects: ## Make the running API re-read subject packages from disk
	curl -fsS -X POST http://localhost:$${API_PORT:-8000}/api/v1/admin/subjects/reload \
		-H "Authorization: Bearer $$LEARNOS_ADMIN_TOKEN" | python3 -m json.tool

# ---------------------------------------------------------------------------
# Quality
# ---------------------------------------------------------------------------

.PHONY: test
test: test-schema test-api test-ingestion ## Run every test suite that exists

# pytest exits 4 on a missing directory, which reads as "the tests failed" and
# teaches everyone to stop running `make test`. Saying "no suite yet" out loud is
# more honest and keeps the target usable while the gap gets closed. All three
# suites exist now; the guards stay because a suite can be deleted or moved, and
# the failure mode they prevent is silent.
#
# Three invocations rather than one `pytest` over all three paths. Each suite has
# its own `tests/` package, so a single run would import two different
# `tests.conftest` modules and fail collection with ImportPathMismatchError.
.PHONY: test-schema
test-schema:
	@if [ -d $(SCHEMA)/tests ]; then pytest $(SCHEMA)/tests -q; else echo "no suite yet: $(SCHEMA)/tests"; fi

.PHONY: test-api
test-api:
	@if [ -d apps/api/tests ]; then pytest apps/api/tests -q; else echo "no suite yet: apps/api/tests"; fi

.PHONY: test-ingestion
test-ingestion:
	@if [ -d services/ingestion/tests ]; then pytest services/ingestion/tests -q; else echo "no suite yet: services/ingestion/tests"; fi

.PHONY: test-web
test-web: ## Typecheck and build the web app
	cd apps/web && npx tsc --noEmit && npm run build

.PHONY: compile
compile: ## Syntax-check every Python file without installing anything
	@find packages apps/api services subjects -name '*.py' -not -path '*/.venv/*' -print0 \
		| xargs -0 -n1 python3 -m py_compile && echo "all python files compile"

.PHONY: check-imports
check-imports: ## Resolve every intra-repo import and module attribute, stdlib only
	python3 tools/check_imports.py

.PHONY: check-web
check-web: ## Frontend structural checks (imports, panel registry, routes, client boundary)
	python3 tools/check_web.py

.PHONY: check-contract
check-contract: ## Every web API call has a route, and shared models agree field for field
	python3 tools/check_contract.py

.PHONY: check-enums
check-enums: ## No `x is SomeEnum.MEMBER`, which use_enum_values makes silently never match
	python3 tools/check_enum_identity.py

.PHONY: check
check: compile check-imports check-web check-contract check-enums validate-nodeps ## Everything verifiable with no dependencies installed

.PHONY: verify-loop
verify-loop: ## Walk learn -> practice -> grade against the running stack and assert the invariants
	@bash tools/verify_loop.sh

.PHONY: lint
lint:
	ruff check packages apps/api services
	@if [ -x apps/web/node_modules/.bin/eslint ]; then cd apps/web && npx eslint .; \
	else echo "skipping eslint: not in apps/web devDependencies yet"; fi

.PHONY: fmt
fmt:
	ruff format packages apps/api services
	cd apps/web && npx prettier --write "src/**/*.{ts,tsx,css}"
