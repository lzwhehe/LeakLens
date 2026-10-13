#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Export LeakLens SQLite results to data/leaklens-results.json for Vercel."""

from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime
from pathlib import Path


def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def export_data(db_path: Path, output_path: Path) -> dict:
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "scanned_blobs": 0,
        "progress": {"current_index": 0, "total": 0, "is_completed": False},
        "items": [],
    }

    if not db_path.exists():
        return payload

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row

        if table_exists(conn, "scanned_blobs"):
            payload["scanned_blobs"] = conn.execute("SELECT COUNT(*) FROM scanned_blobs").fetchone()[0]

        if table_exists(conn, "scan_progress"):
            row = conn.execute(
                "SELECT current_index, total, is_completed FROM scan_progress WHERE id = 1"
            ).fetchone()
            if row:
                payload["progress"] = {
                    "current_index": row["current_index"] or 0,
                    "total": row["total"] or 0,
                    "is_completed": bool(row["is_completed"]),
                }

        if table_exists(conn, "leaked_keys"):
            rows = conn.execute(
                "SELECT id, platform, api_key, base_url, status, balance, source_url, "
                "model_tier, rpm, is_high_value, found_time "
                "FROM leaked_keys ORDER BY found_time DESC, id DESC"
            ).fetchall()
            payload["items"] = [dict(row) for row in rows]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Export LeakLens data for Vercel")
    parser.add_argument("--db", default="leaked_keys.db", help="SQLite database path")
    parser.add_argument("--out", default="data/leaklens-results.json", help="Output JSON path")
    args = parser.parse_args()

    payload = export_data(Path(args.db), Path(args.out))
    print(f"Exported {len(payload['items'])} keys to {args.out}")


if __name__ == "__main__":
    main()
