"""THE PRIVACY INVARIANT.

Only schema (columns+dtypes) + <=N bounded sample rows (and, for the answer
node, a bounded result summary) may cross into an LLM prompt. Sentinel cell
values planted in NON-sampled rows must never appear in the rendered prompt.
No LLM key required — this asserts on the choke point directly.
"""
import pandas as pd
import pytest

from analysis import privacy, store


SENTINEL = "SENTINEL_LEAK_MARKER_9f83"


def _meta_with_sentinel():
    # 50 rows; the sentinel lives ONLY in rows beyond the sample window.
    rows = 50
    regions = ["West"] * rows
    secrets = ["ordinary"] * rows
    secrets[40] = SENTINEL   # deep in the file, never in head(5)
    df = pd.DataFrame({"region": regions, "secret_note": secrets, "revenue": range(rows)})
    dataset_id = store.save(df.to_csv(index=False).encode("utf-8"), "data.csv")
    return store.profile(dataset_id).to_dict()


def test_rendered_prompt_contains_schema():
    meta = _meta_with_sentinel()
    ctx = privacy.build_context(meta, question="What is total revenue?")
    rendered = privacy.render_context(ctx)

    assert "region" in rendered
    assert "secret_note" in rendered
    assert "revenue" in rendered


def test_rendered_prompt_bounds_sample_rows():
    from config.settings import get_settings

    meta = _meta_with_sentinel()
    ctx = privacy.build_context(meta, question="q")

    assert len(ctx.sample_rows) <= get_settings().sample_rows


def test_sentinel_from_nonsampled_row_never_leaks():
    meta = _meta_with_sentinel()
    ctx = privacy.build_context(meta, question="q")
    rendered = privacy.render_context(ctx)

    assert SENTINEL not in rendered
    # and it is absent from the structured context too
    assert SENTINEL not in str(ctx.sample_rows)


def test_build_context_rejects_a_dataframe():
    df = pd.DataFrame({"a": [1, 2, 3]})
    with pytest.raises(TypeError):
        privacy.build_context(df, question="q")  # type: ignore[arg-type]


def test_generate_code_node_sends_only_bounded_context(monkeypatch):
    """Exercise the real generate_code node with a fake LLM that captures the
    outbound prompt. It must be a plain string with schema + <=N samples and
    NONE of the sentinel/raw data — and never a DataFrame."""
    from graph import nodes

    captured = {}

    class FakeClient:
        def call_with_usage(self, prompt, *, system=None):
            captured["prompt"] = prompt
            captured["system"] = system
            return "```python\nresult = df['revenue'].sum()\n```", {
                "prompt_tokens": 1,
                "completion_tokens": 1,
            }

    monkeypatch.setattr(nodes, "LLMClient", FakeClient)

    meta = _meta_with_sentinel()
    state = {"run_id": "r1", "dataset_id": "d1", "question": "total revenue", "dataset_meta": meta}
    out = nodes.generate_code(state)

    assert out.get("error") is None
    assert isinstance(captured["prompt"], str)
    assert "revenue" in captured["prompt"]          # schema present
    assert SENTINEL not in captured["prompt"]        # raw data absent
    assert "result = df['revenue'].sum()" in out["generated_code"]


def test_result_summary_rows_are_rebounded():
    meta = _meta_with_sentinel()
    big_summary = {"kind": "series", "rows": [{"index": i, "value": i} for i in range(100)]}
    ctx = privacy.build_context(meta, question="q", result_summary=big_summary)

    from config.settings import get_settings

    assert len(ctx.result_summary["rows"]) <= get_settings().result_rows
