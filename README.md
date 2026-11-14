# DE2026-Group10
The project of Group 10 for the Data Engineering course in Fall 2026.

The objective of the project is to provide analytics related to electricity prices, combined with the weather data and historical consumption.

## Architecture

![Architecture diagram](docs/architecture.png)

## Data Dictionary

See [infra/README.md](infra/README.md).

## Example Queries and DDL

See [docs/examples.sql](docs/examples.sql) for example queries.

See [infra/clickhouse/init/](infra/clickhouse/init/) for the DDL.

## Spec-Driven Development

Features are developed with [Spec Kit](https://github.com/github/spec-kit).

- Project principles: [.specify/memory/constitution.md](.specify/memory/constitution.md)
- Feature specs, plans and tasks: [specs/](specs/)

Workflow: `/speckit-specify` → `/speckit-clarify` → `/speckit-plan` → `/speckit-tasks` → `/speckit-analyze` → `/speckit-implement`.

Other commands: `/speckit-constitution` (update principles), `/speckit-checklist` (generate a quality checklist), `/speckit-converge` (add tasks for unbuilt work).

No separate LLM disclosure file is provided, as the specs already cover LLM usage.
