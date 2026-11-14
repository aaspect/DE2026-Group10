.PHONY: up down reset ps logs dbt-debug dbt-build lint format test

# Start the whole stack and wait until every service is healthy.
up:
	mkdir -p airflow/logs ingestion/output/open_meteo
	docker compose up -d --build --wait

# Stop the stack. Data is kept.
down:
	docker compose down

# Stop the stack and delete all warehouse and metadata data.
reset:
	docker compose down -v

ps:
	docker compose ps

logs:
	docker compose logs -f

# Check that dbt can connect to the warehouse (the stack must be running).
dbt-debug:
	docker compose exec airflow /opt/venvs/dbt/bin/dbt debug --project-dir /opt/dbt

# Build and test all dbt models (the stack must be running).
dbt-build:
	docker compose exec airflow /opt/venvs/dbt/bin/dbt build --project-dir /opt/dbt

lint:
	cd ingestion && uv run ruff check . && uv run ruff format --check .
	uvx ruff check airflow superset && uvx ruff format --check airflow superset

format:
	cd ingestion && uv run ruff format . && uv run ruff check --fix .
	uvx ruff format airflow superset && uvx ruff check --fix airflow superset

test:
	cd ingestion && uv run pytest
