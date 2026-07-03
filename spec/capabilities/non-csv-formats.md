# Capability: Non-CSV File Formats

## What It Does
Loads and profiles Excel, JSON, Parquet, PDF, and log/text files as file sources — each parsed to a DataFrame — under the same privacy invariant (only schema + bounded sample reach the LLM), with graceful degradation when a format has no clean tabular data.

## Inputs
| Input | Type | Source | Required |
|-------|------|--------|----------|
| file | multipart upload (`.xlsx/.json/.parquet/.pdf/.log/.txt`) | `POST /datasets` | yes |

## Outputs
| Output | Type | Destination |
|--------|------|-------------|
| dataset_id | uuid | response + `DatasetRow` |
| source_kind | enum (`excel`/`json`/`parquet`/`pdf`/`log`) | `DatasetRow.source_kind` |
| profile (schema + bounded sample + row_count) | JSON | response (LLM-visible sample) |

## External Calls
| System | Operation | On Failure |
|--------|-----------|------------|
| openpyxl (Excel) / pandas (JSON) / pyarrow (Parquet) / pdfplumber (PDF) / line reader (log) | load to DataFrame | friendly `BAD_REQUEST` at upload; no orphan file; no crash |

## Business Rules
- Same privacy invariant as CSV: only schema + ≤`AGENT_SAMPLE_ROWS` cell-capped sample rows ever leave; only the executor reads the full file.
- `store.load_df` dispatches by `source_kind`; files keep their original extension on disk (`<dataset_id>.<ext>`).
- **Graceful degradation:** a PDF with no detectable table (or an unparseable log) is rejected with a clear message ("Couldn't find a table in that PDF — try CSV/Excel/Parquet"), not a 500.
- Nested JSON is flattened (`json_normalize`); a log with no parseable fields becomes a single `line` column.

## Success Criteria
- [ ] Uploading a Parquet and an Excel file each returns a correct schema + sample, and a question answered against them matches a direct pandas computation on the full file.
- [ ] The privacy payload-capture test holds for a non-CSV source (schema + ≤N samples, none of the sentinel non-sampled values).
- [ ] A PDF with no table is rejected with the friendly message and leaves no file in `./data/uploads/`.
- [ ] An unsupported extension is rejected with a clear `BAD_REQUEST`.
