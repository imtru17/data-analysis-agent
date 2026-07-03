# Capability: Show the Generated Code

## What It Does
Surfaces the exact pandas code the agent generated and ran, in a collapsible panel under each answer, so the user can inspect and trust how a number was produced.

## Inputs
| Input | Type | Source | Required |
|-------|------|--------|----------|
| generated_code | string | SSE `done` event / `GET /analyses/{id}` | yes |

## Outputs
| Output | Type | Destination |
|--------|------|-------------|
| rendered code panel | UI | collapsible disclosure under the answer |
| copy-to-clipboard | UI action | clipboard |

## External Calls
| System | Operation | On Failure |
|--------|-----------|------------|
| (none — client-side rendering of already-returned code) | — | — |

## Business Rules
- The code shown is the **exact** string that was executed locally (not a re-render or paraphrase).
- Panel is collapsed by default ("Show code ▸") and expandable.
- Monospace, with a copy button; no execution from the UI.
- Also retrievable later via `GET /analyses/{run_id}.generated_code` (persisted).

## Success Criteria
- [ ] For any completed run, the code panel displays the same string stored in `analysis_runs.generated_code`.
- [ ] Re-running the shown code locally against the same file reproduces the reported numbers.
- [ ] The panel is collapsed by default and expands on click; copy places the code on the clipboard.
