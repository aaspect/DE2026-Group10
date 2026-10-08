# LLM Disclosure

## LLM Usage - Fact Table Grain

**Tool:** Claude (Anthropic)

**Prompt:**
> Nord Pool moved to 15-minute day-ahead intervals in October 2025, but Open-Meteo weather data is hourly. What grain should our electricity price fact table use?

**Response (summary):**
> Since the analysis relies on combining price with weather, use an hourly grain (one row per bidding zone per delivery hour). Aggregate the 15-minute prices to hourly by averaging the four intervals, which is also how Nord Pool reports hourly reference prices. This keeps prices and weather aligned without repeating or interpolating weather values, and makes data from before and after October 2025 consistent. You can optionally store the hourly min and max price as extra measures to keep some of the within-hour volatility.

**How it was used:** Helped confirm the move to an hourly grain and how to aggregate the 15-minute price data. The final schema design was done by the team.

## LLM Usage - initializing the git repo

**Tool:** Claude Code (Anthropic)

**Prompt:**
> Let's initialize this monorepo for the course project based on the architecture diagram. The main language is Python. *(Shared with our architecture diagram: ingestion jobs → ClickHouse staging/main/marts via dbt → Superset, orchestrated by Airflow, with Postgres for metadata.)*

**Response (summary):**
> Proposed a monorepo layout based on the diagram: a Python ingestion package with one plugin module per data source, a dbt project for the staging → main → marts layers, an Airflow image and DAGs, Superset config, init SQL for ClickHouse and Postgres, and a single compose file for the local stack. It also suggested shared tooling (uv workspace, ruff, pytest, pre-commit, CI) and ideas for later, such as astronomer-cosmos, incremental models, dbt data quality tests, Superset dashboards as code and dbt docs on GitHub Pages. When we asked about folder names, it explained two common conventions: naming folders by pipeline stage (`extract/`, `transform/`, `orchestrate/`) or by tool (`dbt/`, `airflow/`, `superset/`). It noted that a top-level `airflow/` or `dbt/` folder does not shadow the installed packages as long as it has no `__init__.py`.

**How it was used:** The team picked the folder names (by tool: `ingestion/`, `dbt/`, `airflow/`, `superset/`, `infra/`) and limited the scope to a boilerplate structure, without choosing data sources or ingestion libraries yet. Claude created the folders with placeholder files (one-line TODOs only), updated the README with the diagram and a folder overview, and added dbt/Airflow output folders to `.gitignore`. The actual pipeline code and configuration will be written by the team.
