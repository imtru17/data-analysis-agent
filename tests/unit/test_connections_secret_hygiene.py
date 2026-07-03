"""Secret hygiene (Phase 3): a DB connection's raw DSN/password must NEVER
appear in a `POST /connections` or `GET /connections` response, and never in
an outbound Anthropic request. No LLM key required for the response checks."""
from __future__ import annotations

import sqlite3


PASSWORD_MARKER = "s3cr3t_pw_should_never_leak"


def _seed_sqlite(tmp_path):
    db_path = tmp_path / "hygiene.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, val TEXT)")
    conn.execute("INSERT INTO t (val) VALUES ('a'), ('b')")
    conn.commit()
    conn.close()
    return db_path


def test_post_connections_never_echoes_dsn(api_client, tmp_path):
    db_path = _seed_sqlite(tmp_path)
    dsn = f"sqlite:///{db_path.as_posix()}"

    r = api_client.post("/connections", json={"name": "hygiene", "kind": "sqlite", "dsn": dsn})
    assert r.status_code == 200, r.text
    data = r.json()["data"]

    # SQLite DSNs carry no password, so the file path itself is not a secret
    # (nothing to mask) — the hygiene bar here is the RESPONSE SHAPE: the raw
    # `dsn` field is never returned, only `dsn_masked`.
    assert "dsn" not in data  # only dsn_masked is ever returned
    assert data["dsn_masked"]  # present and non-empty


def test_get_connections_never_echoes_dsn(api_client, tmp_path):
    db_path = _seed_sqlite(tmp_path)
    dsn = f"sqlite:///{db_path.as_posix()}"
    api_client.post("/connections", json={"name": "hygiene2", "kind": "sqlite", "dsn": dsn})

    r = api_client.get("/connections")
    assert r.status_code == 200
    for item in r.json()["data"]:
        assert "dsn" not in item
        assert item["dsn_masked"]


def test_garbled_dsn_is_rejected_without_leaking(api_client):
    """A DSN that fails dialect detection is rejected fast (no network call),
    and the rejection message never embeds the raw input."""
    garbled = f"not-a-real-dsn:{PASSWORD_MARKER}"
    r = api_client.post("/connections", json={"name": "bad", "kind": "sqlite", "dsn": garbled})
    assert r.status_code == 400
    blob = r.text
    assert PASSWORD_MARKER not in blob
    assert garbled not in blob


def test_scrub_removes_dsn_and_password_from_error_text():
    """Unit-level: `_scrub` (used on every DB exception) must never leak the
    DSN or its password into a surfaced/logged error message."""
    from pydantic import SecretStr

    from analysis.db_source import _scrub

    dsn = SecretStr(f"postgresql://user:{PASSWORD_MARKER}@unreachable-host:5432/db")
    message = f"connection failed: {dsn.get_secret_value()}"
    safe = _scrub(message, dsn)
    assert PASSWORD_MARKER not in safe
    assert dsn.get_secret_value() not in safe


def test_mask_dsn_masks_password():
    from analysis.db_source import mask_dsn

    dsn = f"postgresql://user:{PASSWORD_MARKER}@host:5432/db"
    masked = mask_dsn(dsn)
    assert PASSWORD_MARKER not in masked
    assert "user" in masked
    assert "host" in masked
