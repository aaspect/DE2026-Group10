# Specification Quality Checklist: Elering Grid Data Ingestion Job

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-11-10
**Feature**: [spec.md](../spec.md)

## Content Quality

- [x] No implementation details (languages, frameworks, APIs)
- [x] Focused on user value and business needs
- [x] Written for non-technical stakeholders
- [x] All mandatory sections completed

## Requirement Completeness

- [x] No [NEEDS CLARIFICATION] markers remain
- [x] Requirements are testable and unambiguous
- [x] Success criteria are measurable
- [x] Success criteria are technology-agnostic (no implementation details)
- [x] All acceptance scenarios are defined
- [x] Edge cases are identified
- [x] Scope is clearly bounded
- [x] Dependencies and assumptions identified

## Feature Readiness

- [x] All functional requirements have clear acceptance criteria
- [x] User scenarios cover primary flows
- [x] Feature meets measurable outcomes defined in Success Criteria
- [x] No implementation details leak into specification

## Notes

- Iteration 1: provider behaviour was checked against sample responses retrieved on 2026-11-10
  (2025-11-01 to 2026-11-12). Findings that differ from the feature description are recorded in
  the spec: the actual feed delivers 5-minute rows (FR-010), renewable share is not delivered and
  losses are always empty (FR-009), actual values were hourly before 27 November 2025, solar
  production is published about a day late, and the plan feed only returns the latest plan.
- Iteration 1: one open item, FR-010 (Question 1 below). "Requirements are testable and
  unambiguous" passes for every requirement except FR-010, which is settled by the answer to
  Question 1. All other items pass.
- Iteration 2 (2026-11-10): Question 1 answered with A (store every delivered 5-minute row).
  FR-010 is resolved, and the answer is recorded under Clarifications in the spec. Updated to
  match: User Story 1's independent test (576 rows per 48 hours) and a new acceptance scenario 6
  for frequency-only rows, the resolution edge case, FR-014 (the filtering exception is removed),
  the actual grid record entity (5-minute grain), the resolution and existing-files assumptions,
  and the out-of-scope list (silver drops or aggregates frequency-only rows). All items pass.
- Tools are named only where they mark scope (Out of scope list) or point to existing repository
  files and data model tables (Key Entities, Assumptions), never as requirements. The feature
  description is quoted verbatim in the Input line and keeps its tool and address names.
  Environment-variable configuration and UTC storage come from the constitution.
- Items marked incomplete require spec updates before `/speckit-clarify` or `/speckit-plan`

### Question 1: Resolution of stored actual data

**Context**: FR-010: "The actual feed delivers a row every 5 minutes. Grid frequency is filled on
every row, while the other values are filled only on rows that start a quarter hour (or, for older
periods, a full hour)." The feature description says the data "comes in 15-minute intervals", and
`bronze.elering_system` describes its time column as the start of the market interval.

**What we need to know**: Should the job store every delivered 5-minute row as delivered, or only
the rows that start a quarter hour, matching the 15-minute market interval of
`bronze.elering_system`?

**Suggested Answers**:

| Option | Answer | Implications |
|--------|--------|--------------|
| A | Store every delivered 5-minute row | Follows "as delivered, no filtering" literally and keeps frequency at full resolution. About 3 times as many actual records (about 576 per 48-hour run and 105,000 per year instead of about 192 and 35,000), two thirds of them holding only frequency. The raw table's grain becomes 5 minutes, and the cleaned layer drops or aggregates the frequency-only rows. |
| B | Store only rows that start a quarter hour | Matches the 15-minute market interval and the raw table's grain. Drops two thirds of the frequency readings, which no business question uses. Adds one row filter to the job, a deliberate exception to "no filtering". |
| C | Take actual data from the plan feed's actual series instead | Already quarter-hourly with the same values, but frequency there is a constant placeholder, and the actual feed named in the description is no longer used. |
| Custom | Provide your own answer | Reply with "Q1: Custom - " followed by the rule to apply. |

**Answer** (2026-11-10): A. Store every delivered 5-minute row.
