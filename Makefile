# Auto-detect Docker Compose or Podman Compose (override e.g. `make up COMPOSE="podman compose"`).
COMPOSE ?= $(shell \
	if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then \
		echo "docker compose"; \
	elif command -v podman-compose >/dev/null 2>&1; then \
		echo "podman-compose"; \
	elif command -v podman >/dev/null 2>&1 && podman compose version >/dev/null 2>&1; then \
		echo "podman compose"; \
	else \
		echo "docker compose"; \
	fi)
ENGINE = $(if $(findstring podman,$(COMPOSE)),podman,docker)

.PHONY: up down reset ps logs dbt-debug dbt-build lint format test

# Start the whole stack and wait until every service is healthy.
up:
	mkdir -p airflow/logs ingestion/output/open_meteo
	@set -e; \
	if [ -z "$$AIRFLOW_UID" ] \
		&& ! grep -qE '^[[:space:]]*AIRFLOW_UID=' .env 2>/dev/null \
		&& [ "$$($(ENGINE) info --format '{{.Host.Security.Rootless}}' 2>/dev/null)" = "true" ]; then \
		export AIRFLOW_UID=0; \
	fi; \
	if $(COMPOSE) up --help 2>&1 | grep -q -- '--wait'; then \
		$(COMPOSE) up -d --build --wait; \
	else \
		$(COMPOSE) up -d --build; \
		echo "Waiting for all services to become healthy..."; \
		ids=$$($(COMPOSE) ps -q); \
		[ -n "$$ids" ] || { echo "No containers found." >&2; exit 1; }; \
		while true; do \
			pending=0; \
			for id in $$ids; do \
				set -- $$($(ENGINE) inspect --format '{{.Name}} {{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$$id"); \
				name=$$1; status=$$2; health=$$3; \
				if [ "$$status" != "running" ]; then \
					echo "Container $$name is not running (status: $$status)." >&2; \
					exit 1; \
				fi; \
				case "$$health" in \
					healthy|none) ;; \
					unhealthy) echo "Container $$name is unhealthy." >&2; exit 1 ;; \
					*) pending=1 ;; \
				esac; \
			done; \
			[ "$$pending" -eq 0 ] && break; \
			sleep 2; \
		done; \
		echo "All services are healthy."; \
	fi

# Stop the stack. Data is kept.
down:
	$(COMPOSE) down

# Stop the stack and delete all warehouse and metadata data.
reset:
	$(COMPOSE) down -v

ps:
	$(COMPOSE) ps

logs:
	$(COMPOSE) logs -f

# Check that dbt can connect to the warehouse (the stack must be running).
dbt-debug:
	$(COMPOSE) exec -T airflow /opt/venvs/dbt/bin/dbt debug --project-dir /opt/dbt

# Build and test all dbt models (the stack must be running).
dbt-build:
	$(COMPOSE) exec -T airflow /opt/venvs/dbt/bin/dbt build --project-dir /opt/dbt

lint:
	cd ingestion && uv run ruff check . && uv run ruff format --check .
	uvx ruff check airflow superset && uvx ruff format --check airflow superset

format:
	cd ingestion && uv run ruff format . && uv run ruff check --fix .
	uvx ruff format airflow superset && uvx ruff check --fix airflow superset

test:
	cd ingestion && uv run pytest
