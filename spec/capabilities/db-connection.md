# Capability: Live SQL Database Sources (pushdown + sampling)

## What It Does
Connects to a live SQL database (Postgres/MySQL/SQLite via SQLAlchemy) as a queryable source, where the agent writes read-only SQL that is **pushed down to the database** — only the schema, a bounded sample, and a bounded result summary ever reach Claude, and the full table never leaves the DB.

## Inputs
| Input | Type | Source | Required |
|-------|------|--------|----------|
| name | string | `POST /connections` body | yes |
| kind | enum (`postgresql`/`mysql`/`sqlite`) | `POST /connections` body | yes |
| dsn | string (SecretStr) | `POST /connections` body | yes |
| session_id | uuid | `POST /connections` body | no |
| question (at ask time) | string | `POST /analyses` body | yes |

## Outputs
| Output | Type | Destination |
|--------|------|-------------|
| connection_id | uuid | response + `ConnectionRow` |
| dsn_masked | string | response (raw DSN never returned) |
| introspected schema | JSON `[{table, columns:[{name,dtype}]}]` | response + `ConnectionRow.schema_json` |
| bounded sample | JSON | `ConnectionRow.sample_rows_json` (LLM-visible) |
| answer / generated SQL / bounded result summary | via SSE `done` | UI + `AnalysisRunRow` |

## External Calls
| System | Operation | On Failure |
|--------|-----------|------------|
| User database (SQLAlchemy engine) | `inspect()` schema, `LIMIT N` sample, read-only pushdown `SELECT` | connect/query error caught → `execution_result.error` → retry; connect-fatal → `handle_error`; message never includes the DSN |
| Anthropic (via privacy choke point) | write SQL from schema + samples (+ annotations/history) ONLY | node sets `error` → `handle_error` |

## Business Rules
- **Privacy invariant (DB):** only the introspected schema, a `LIMIT AGENT_SAMPLE_ROWS` sample, and the bounded result summary reach Claude. Generated SQL runs **inside the DB**; DB-sized tables never load into memory or a prompt.
- **Read-only:** generated SQL must be a single `SELECT`/`WITH`; `INSERT/UPDATE/DELETE/DROP/ALTER/TRUNCATE/GRANT` and multiple statements are rejected before execution. A safety `LIMIT AGENT_SQL_MAX_ROWS` (default 100000) wraps un-aggregated fetches.
- **Secret hygiene:** the DSN is stored only in the git-ignored SQLite DB (`SecretStr`), never sent to the LLM, never logged, never returned in full (masked). See `harness/rules/secret-hygiene.md`.
- Source-agnostic graph: `execute_locally` dispatches file→pandas-local, DB→SQL-pushdown.

## Success Criteria
- [ ] Connecting to a seeded **local SQLite** DB (no external credentials) and asking "total revenue by region" returns numbers equal to a direct `SELECT region, SUM(revenue) ... GROUP BY region` against the full table.
- [ ] A payload-capture test proves the outbound Anthropic request for a DB source contains the schema + ≤N sample rows and **none** of the sentinel values planted in non-sampled rows, and **never** the connection string.
- [ ] `GET /connections` and `POST /connections` return a masked DSN; the raw DSN appears in no response, log line, or exception message.
- [ ] Generated SQL containing `DROP`/`UPDATE`/`;`-chained statements is rejected before execution.
- [ ] The pushed-down query fetches a bounded result even when the source table is far larger than `AGENT_SQL_MAX_ROWS` (proven on a seeded large SQLite table where a sampled vs full answer would differ).
