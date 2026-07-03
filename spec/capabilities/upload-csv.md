# Capability: Upload & Profile a CSV

## What It Does
Accepts a CSV upload, stores the raw file locally, and returns a profile (schema + row count + a small bounded sample) — the profile is exactly the data that the agent is later allowed to send to the LLM.

## Inputs
| Input | Type | Source | Required |
|-------|------|--------|----------|
| file | multipart CSV | `POST /datasets` upload control | yes |

## Outputs
| Output | Type | Destination |
|--------|------|-------------|
| dataset_id | uuid | UI (used for subsequent asks) |
| profile (filename, row_count, columns[name,dtype], sample_rows) | JSON | UI system message |
| DatasetRow | DB row | `datasets` table |
| raw file | file | `./data/uploads/<dataset_id>.csv` |

## External Calls
| System | Operation | On Failure |
|--------|-----------|------------|
| Local filesystem | write raw file to uploads store | 500 `INTERNAL` |
| pandas | read CSV to compute schema + samples + row count | 400 `BAD_REQUEST` (unparseable) |
| SQLite | insert DatasetRow | 500 `INTERNAL` |

## Business Rules
- Only `.csv` accepted in Phase 1; other types rejected with a friendly message (not an error stub).
- Files over `AGENT_MAX_UPLOAD_MB` (default 500) rejected with 413.
- `sample_rows` bounded to `AGENT_SAMPLE_ROWS` (default 5), each cell string-length-capped (default 200 chars).
- The full file is read only to compute the profile; its contents are never returned beyond the bounded sample, never stored in the DB.
- Sampling is deterministic (head) for reproducibility.

## Success Criteria
- [ ] Uploading a valid CSV returns a `dataset_id` and a profile whose `columns` match the file's header and inferred dtypes, and `row_count` equals the file's row count.
- [ ] `sample_rows` length ≤ `AGENT_SAMPLE_ROWS`.
- [ ] A non-CSV or unparseable upload returns 400 with a readable message and writes no DatasetRow.
- [ ] The raw file exists at `./data/uploads/<dataset_id>.csv` after upload and its bytes are never present in any DB column.
