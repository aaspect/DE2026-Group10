.PHONY: lint format test

lint:
	cd ingestion && uv run ruff check . && uv run ruff format --check .

format:
	cd ingestion && uv run ruff format . && uv run ruff check --fix .

test:
	cd ingestion && uv run pytest
