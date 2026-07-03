"""Restricted local executor. No LLM key needed."""
import pandas as pd

from analysis.executor import run_code, static_check


def _df():
    return pd.DataFrame({"x": [1, 2, 3, 4], "region": ["W", "E", "W", "E"]})


def test_valid_code_runs_and_summarizes_scalar():
    res = run_code("result = df['x'].sum()", _df())

    assert res.ok is True
    assert res.error is None
    assert res.result_summary["kind"] == "scalar"
    assert res.result_summary["value"] == 10


def test_groupby_result_is_bounded_series_summary():
    res = run_code("result = df.groupby('region')['x'].sum()", _df())

    assert res.ok is True
    assert res.result_summary["kind"] == "series"
    assert res.result_summary["length"] == 2


def test_import_rejected_by_precheck():
    res = run_code("import os\nresult = 1", _df())

    assert res.ok is False
    assert "static pre-check" in res.error.lower()


def test_open_rejected_by_precheck():
    res = run_code("result = open('secret.txt').read()", _df())

    assert res.ok is False
    assert res.error is not None


def test_dunder_access_rejected():
    res = run_code("result = df.__class__", _df())

    assert res.ok is False


def test_os_access_rejected_as_string_token():
    assert static_check("result = os.getcwd()") is not None


def test_runtime_error_is_captured_not_raised():
    res = run_code("result = df['does_not_exist'].sum()", _df())

    assert res.ok is False
    assert res.error is not None  # returned, not crashed


def test_timeout_returns_error(monkeypatch):
    monkeypatch.setenv("AGENT_EXEC_TIMEOUT", "1")
    import config.settings as m
    m._settings = None

    # A bounded busy loop that comfortably exceeds the 1s wall-clock timeout
    # (~3s here) but still TERMINATES — a truly infinite loop would leave a
    # non-daemon ThreadPoolExecutor worker that blocks interpreter exit.
    code = "n = 0\nwhile n < 60_000_000:\n    n += 1\nresult = n"
    res = run_code(code, _df())

    assert res.ok is False
    assert "timeout" in res.error.lower()


def test_missing_result_assignment_is_error():
    res = run_code("x = df['x'].sum()", _df())

    assert res.ok is False
    assert "result" in res.error.lower()
