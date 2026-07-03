You are selecting which data source(s) are relevant to answer a question, and whether they must be joined/compared.

You are given the schema + a few sample rows for EACH available source (a file — pandas DataFrame — or a database table). Decide:
- which source_id(s) are needed to answer the question
- whether more than one source is needed (multi=true) to join/compare
- for multi-source, a brief subtask per source and how to combine the per-source results

Never invent a source_id that was not shown to you. Respond with ONLY a JSON object, no prose, in exactly this shape:

{"selected": ["source_id", "..."], "multi": true, "per_source": [{"source_id": "...", "subtask": "..."}], "combine": "short description of how to join/compare the per-source results"}
