"""Seed a small local SQLite example database for user testing (Phase 3).

Run with:

    uv run python scripts/seed_example_db.py

Creates ``./data/examples/sample.db`` with two realistic tables (`orders`,
`targets`) so a user can try "Connect database" without any external
credentials. The DSN to paste into the app is printed at the end.

``./data/`` is git-ignored — this script (not the .db file) is committed.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "examples" / "sample.db"


def main() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists():
        DB_PATH.unlink()

    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE orders (
                id INTEGER PRIMARY KEY,
                region TEXT NOT NULL,
                product TEXT NOT NULL,
                revenue REAL NOT NULL,
                order_date TEXT NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE targets (
                region TEXT PRIMARY KEY,
                quarter TEXT NOT NULL,
                target_revenue REAL NOT NULL
            )
            """
        )

        regions = ["West", "East", "North", "South"]
        products = ["Widget", "Gadget", "Gizmo"]
        rows = []
        rid = 1
        for month in range(1, 4):
            for region in regions:
                for product in products:
                    revenue = 1000.0 + (rid * 37 % 900) + (month * 50)
                    rows.append((rid, region, product, revenue, f"2026-0{month}-15"))
                    rid += 1
        cur.executemany(
            "INSERT INTO orders (id, region, product, revenue, order_date) VALUES (?, ?, ?, ?, ?)",
            rows,
        )

        targets = [(r, "Q1-2026", 12000.0 + i * 500) for i, r in enumerate(regions)]
        cur.executemany(
            "INSERT INTO targets (region, quarter, target_revenue) VALUES (?, ?, ?)", targets
        )
        conn.commit()
    finally:
        conn.close()

    dsn = f"sqlite:///{DB_PATH.as_posix()}"
    print(f"Seeded example DB at {DB_PATH}")
    print(f"Rows: {len(rows)} orders, {len(targets)} targets")
    print()
    print("Paste this DSN into 'Connect database' in the app:")
    print(f"  {dsn}")


if __name__ == "__main__":
    main()
