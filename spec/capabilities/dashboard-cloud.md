# Capability: Dashboard + 3D Charts + Cloud Connectors (opt-in)

> **Phase 5 — deferred.** In Phase 4 these surfaces ship only as clearly-labelled NON-FUNCTIONAL stubs. This capability makes them real. Cloud connectivity stays an opt-in, credential-gated preview so the build/gate need no AWS/Snowflake credentials.

## What It Does
Turns the workbench into an interactive dashboard that combines profile tiles with multiple charts — including a rotatable interactive 3D chart rendered locally with Plotly.js — and adds an opt-in "Connect & create table" flow that would create a table matching the uploaded file's schema in a local DB/Postgres (real) or in AWS S3 / Snowflake / another cloud DB (a labelled, credential-gated preview with no live call).

## Inputs
| Input | Type | Source | Required |
|-------|------|--------|----------|
| dataset_id | uuid | path (`GET /datasets/{id}/dashboard`, `.../chart3d`) | yes |
| x / y / z | column names | `GET /datasets/{id}/chart3d` query (optional — auto-picked from numeric columns when omitted) | no |
| target | enum (`local`/`postgresql`/`s3`/`snowflake`) | `POST /datasets/{id}/create-table` body | yes |
| connection config | JSON (DSN for local/Postgres; bucket/warehouse/creds for cloud) | `POST /datasets/{id}/create-table` body | conditional |

## Outputs
| Output | Type | Destination |
|--------|------|-------------|
| dashboard payload | JSON `{ tiles, charts:[vega specs], chart3d }` | `GET /datasets/{id}/dashboard` → Dashboard view |
| 3D chart spec | JSON (Plotly figure: bounded points, chosen x/y/z) | `GET /datasets/{id}/chart3d` → local Plotly.js render |
| table-create result | JSON `{ created, target, table_name, message }` | `POST /datasets/{id}/create-table` → confirmation / preview notice |

## External Calls
| System | Operation | On Failure |
|--------|-----------|------------|
| Local dataset store (`store.load_df`) | Read the full DataFrame locally to compute tiles/charts/3D points | Missing file → `NOT_FOUND` |
| Local DB / Postgres (SQLAlchemy) | `create_table_from_schema` — real DDL matching the file schema | Connect/DDL error → friendly `BAD_REQUEST` |
| **AWS S3 (boto3)** / **Snowflake (snowflake-connector)** | **STUB in-build** — validate config only; make a live call **only** when credentials are supplied | No credentials → friendly "add credentials" `BAD_REQUEST`; **no network call** and no crash |

> The 3D chart uses **bounded, locally-computed points** (capped like any result summary) — no raw bulk data is sent to any chart service; Plotly.js renders in the browser from a self-contained bundle (no external CDN).

## Business Rules
- **Local-first default.** Dashboard, tiles, 2D (Vega) + 3D (Plotly) charts are all computed locally from the full DataFrame; nothing leaves the machine for the local path.
- **3D axes:** auto-picked from the first suitable numeric columns when `x/y/z` are omitted; the user may override. Points are bounded (`AGENT_CHART3D_MAX_POINTS`, sampled deterministically when over cap) so the browser stays responsive and no bulk data is shipped.
- **Plotly bundled locally:** `plotly.js-dist-min` is bundled into the frontend static export — no external CDN dependency (matches the local-first, self-contained deployment). Existing 2D charts stay on Vega-Lite.
- **Cloud is opt-in and gated out of the build.** `boto3` + `snowflake-connector-python` ship as an **optional `cloud` extra** (`uv sync --extra cloud`), not in the base install or the gate. The S3/Snowflake adapters validate config and return a friendly "add credentials" preview error unless credentials are present — the build and gate exercise only the **local/Postgres** create-table path.
- **Explicit egress warning.** Any cloud target shows an explicit "this sends data to the cloud" warning in the UI before any action; the local/Postgres path shows no such warning.
- **Never mutate the source file.** Creating a table reads the schema and writes to the *target*; the uploaded file is untouched (honours the roadmap out-of-scope rule).

## Success Criteria
- [ ] `GET /datasets/{id}/dashboard` returns tiles + a set of chart specs + a 3D chart spec, all computed locally.
- [ ] `GET /datasets/{id}/chart3d` returns a valid Plotly figure with bounded points; omitting axes auto-picks numeric columns, supplying `x/y/z` uses them.
- [ ] The frontend Dashboard renders a **rotatable** Plotly 3D chart from the locally-bundled Plotly.js (no external CDN request) and lets the user pick x/y/z.
- [ ] `POST /datasets/{id}/create-table` with `target=local`/`postgresql` creates a table matching the file schema against a local SQLite/Postgres target (gate uses local, no external creds).
- [ ] `POST /datasets/{id}/create-table` with `target=s3`/`snowflake` and no credentials returns a friendly "add credentials" `BAD_REQUEST` and makes **no** network call (asserted in the gate without AWS/Snowflake credentials).
- [ ] Any cloud target surfaces the "this sends data to the cloud" warning in the UI.
