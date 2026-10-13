#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LeakLens Web Dashboard

Web control panel for the scanner and the SQLite database it produces.
It intentionally uses only the Python standard library so the dashboard works
with the existing project dependencies.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import mimetypes
import os
import signal
import sqlite3
import subprocess
import sys
import threading
import time
import re
from collections import deque
from datetime import datetime
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse


APP_NAME = "LeakLens"
ROOT_DIR = Path(__file__).resolve().parent
WEB_DIR = ROOT_DIR / "web"
STATIC_DIR = WEB_DIR / "static"
INDEX_FILE = WEB_DIR / "index.html"
VALID_STATUSES = {
    "pending",
    "valid",
    "invalid",
    "quota_exceeded",
    "connection_error",
    "unverified",
}
ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


class ScanController:
    """Start and stop scanner subprocesses from the Web UI."""

    def __init__(self, default_db_path: str):
        self.default_db_path = default_db_path
        self.process: subprocess.Popen[str] | None = None
        self.started_at: str | None = None
        self.stopped_at: str | None = None
        self.returncode: int | None = None
        self.command_label = ""
        self.db_path = default_db_path
        self.logs: deque[str] = deque(maxlen=500)
        self._lock = threading.Lock()

    def is_running(self) -> bool:
        with self._lock:
            return self.process is not None and self.process.poll() is None

    def start(self, payload: dict[str, Any]) -> tuple[bool, dict[str, Any], int]:
        with self._lock:
            if self.process is not None and self.process.poll() is None:
                return False, {"error": "scan already running"}, 409

            tokens = self._token_list(payload.get("github_tokens", ""))
            if not tokens:
                return False, {"error": "GitHub Tokens are required"}, 400

            mode = str(payload.get("mode") or "classic")
            script = {
                "classic": "main.py",
                "v2.1": "main_v2.1.py",
                "v2.2": "main_v2.2.py",
            }.get(mode, "main.py")

            db_path = str(payload.get("db_path") or self.default_db_path).strip() or self.default_db_path
            args = [sys.executable, str(ROOT_DIR / script), "--db", db_path]
            if script in {"main.py", "main_v2.1.py", "main_v2.2.py"}:
                args.append("--headless")

            if payload.get("proxy_url"):
                args.extend(["--proxy", str(payload["proxy_url"]).strip()])
            if script == "main_v2.2.py" and payload.get("no_cache"):
                args.append("--no-cache")
            if payload.get("all_sources"):
                args.append("--all-sources")
            else:
                for flag in ("pastebin", "gist", "searchcode", "gitlab", "realtime"):
                    if payload.get(flag):
                        args.append(f"--{flag}")
            if payload.get("pastebin_key"):
                args.extend(["--pastebin-key", str(payload["pastebin_key"]).strip()])

            env = os.environ.copy()
            env["GITHUB_TOKENS"] = ",".join(tokens)
            env["PYTHONUNBUFFERED"] = "1"
            env["TERM"] = "dumb"
            env["NO_COLOR"] = "1"
            if payload.get("proxy_url"):
                env["PROXY_URL"] = str(payload["proxy_url"]).strip()
            if payload.get("pastebin_key"):
                env["PASTEBIN_API_KEY"] = str(payload["pastebin_key"]).strip()

            self.logs.clear()
            self.started_at = datetime.now().isoformat(timespec="seconds")
            self.stopped_at = None
            self.returncode = None
            self.db_path = db_path
            self.command_label = " ".join([Path(args[0]).name, Path(args[1]).name, *args[2:]])
            self._append_log(f"Starting {self.command_label}")

            try:
                self.process = subprocess.Popen(
                    args,
                    cwd=str(ROOT_DIR),
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    start_new_session=True,
                )
            except OSError as exc:
                self.process = None
                self.returncode = 1
                self.stopped_at = datetime.now().isoformat(timespec="seconds")
                self._append_log(f"Failed to start scanner: {exc}")
                return False, {"error": str(exc)}, 500

            threading.Thread(target=self._read_output, daemon=True).start()
            threading.Thread(target=self._watch_process, daemon=True).start()
            return True, {
                "running": True,
                "pid": self.process.pid,
                "started_at": self.started_at,
                "stopped_at": self.stopped_at,
                "returncode": self.returncode,
                "command": self.command_label,
                "db_path": str(Path(self.db_path).expanduser().resolve()),
                "logs": list(self.logs)[-160:],
            }, 200

    def stop(self) -> dict[str, Any]:
        with self._lock:
            process = self.process
            should_stop = process is not None and process.poll() is None
            if should_stop:
                self._append_log("Stopping scanner...")

        if not should_stop or process is None:
            return self.status()

        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass

        deadline = time.time() + 8
        while process.poll() is None and time.time() < deadline:
            time.sleep(0.2)
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        return self.status()

    def status(self) -> dict[str, Any]:
        with self._lock:
            running = self.process is not None and self.process.poll() is None
            if self.process is not None and not running:
                self.returncode = self.process.poll()
            return {
                "running": running,
                "pid": self.process.pid if self.process else None,
                "started_at": self.started_at,
                "stopped_at": self.stopped_at,
                "returncode": self.returncode,
                "command": self.command_label,
                "db_path": str(Path(self.db_path).expanduser().resolve()),
                "logs": list(self.logs)[-160:],
            }

    def _read_output(self) -> None:
        process = self.process
        if process is None or process.stdout is None:
            return
        for raw_line in process.stdout:
            line = ANSI_RE.sub("", raw_line).strip()
            if line:
                self._append_log(line)

    def _watch_process(self) -> None:
        process = self.process
        if process is None:
            return
        returncode = process.wait()
        with self._lock:
            self.returncode = returncode
            self.stopped_at = datetime.now().isoformat(timespec="seconds")
            self._append_log(f"Scanner exited with code {returncode}")

    def _append_log(self, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.logs.append(f"{timestamp} {message}")

    @staticmethod
    def _token_list(raw: Any) -> list[str]:
        if isinstance(raw, list):
            values = raw
        else:
            values = re.split(r"[\s,]+", str(raw or ""))
        return [value.strip() for value in values if value and value.strip()]


def mask_secret(value: str) -> str:
    """Mask a secret while leaving enough shape for visual triage."""
    if not value:
        return ""
    if len(value) <= 10:
        return value[:2] + "*" * max(len(value) - 4, 0) + value[-2:]
    return f"{value[:6]}...{value[-4:]}"


def parse_int(value: str | None, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value or default)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))


def format_time(value: Any) -> str:
    if not value:
        return ""
    text = str(value)
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d %H:%M")
        except ValueError:
            continue
    return text[:16]


class DashboardStore:
    def __init__(self, db_path: str):
        self.db_path = Path(db_path).expanduser().resolve()

    def exists(self) -> bool:
        return self.db_path.exists()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def table_exists(self, conn: sqlite3.Connection, table_name: str) -> bool:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table_name,),
        ).fetchone()
        return row is not None

    def empty_summary(self) -> dict[str, Any]:
        return {
            "app": APP_NAME,
            "db_path": str(self.db_path),
            "db_exists": self.exists(),
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "stats": {
                "total": 0,
                "valid": 0,
                "high_value": 0,
                "scanned_blobs": 0,
                "statuses": {},
                "platforms": {},
            },
            "progress": {"current_index": 0, "total": 0, "is_completed": False},
            "recent": [],
            "trend": [],
        }

    def summary(self) -> dict[str, Any]:
        summary = self.empty_summary()
        if not self.exists():
            return summary

        with self.connect() as conn:
            if not self.table_exists(conn, "leaked_keys"):
                return summary

            total = conn.execute("SELECT COUNT(*) FROM leaked_keys").fetchone()[0]
            valid = conn.execute(
                "SELECT COUNT(*) FROM leaked_keys WHERE status IN ('valid', 'quota_exceeded')"
            ).fetchone()[0]
            high_value = conn.execute(
                "SELECT COUNT(*) FROM leaked_keys WHERE is_high_value = 1"
            ).fetchone()[0]
            statuses = {
                row["status"] or "unknown": row["count"]
                for row in conn.execute(
                    "SELECT COALESCE(status, 'unknown') AS status, COUNT(*) AS count "
                    "FROM leaked_keys GROUP BY COALESCE(status, 'unknown')"
                )
            }
            platforms = {
                row["platform"] or "unknown": row["count"]
                for row in conn.execute(
                    "SELECT COALESCE(platform, 'unknown') AS platform, COUNT(*) AS count "
                    "FROM leaked_keys GROUP BY COALESCE(platform, 'unknown') "
                    "ORDER BY count DESC, platform ASC"
                )
            }

            scanned_blobs = 0
            if self.table_exists(conn, "scanned_blobs"):
                scanned_blobs = conn.execute("SELECT COUNT(*) FROM scanned_blobs").fetchone()[0]

            progress = summary["progress"]
            if self.table_exists(conn, "scan_progress"):
                row = conn.execute(
                    "SELECT current_index, total, is_completed FROM scan_progress WHERE id = 1"
                ).fetchone()
                if row:
                    progress = {
                        "current_index": row["current_index"] or 0,
                        "total": row["total"] or 0,
                        "is_completed": bool(row["is_completed"]),
                    }

            recent = [
                self.serialize_key(row)
                for row in conn.execute(
                    "SELECT * FROM leaked_keys ORDER BY found_time DESC, id DESC LIMIT 8"
                )
            ]
            trend = [
                {"date": row["bucket"], "count": row["count"]}
                for row in conn.execute(
                    "SELECT substr(COALESCE(found_time, ''), 1, 10) AS bucket, COUNT(*) AS count "
                    "FROM leaked_keys WHERE COALESCE(found_time, '') != '' "
                    "GROUP BY bucket ORDER BY bucket DESC LIMIT 14"
                )
            ]
            trend.reverse()

            summary.update(
                {
                    "stats": {
                        "total": total,
                        "valid": valid,
                        "high_value": high_value,
                        "scanned_blobs": scanned_blobs,
                        "statuses": statuses,
                        "platforms": platforms,
                    },
                    "progress": progress,
                    "recent": recent,
                    "trend": trend,
                }
            )
            return summary

    def serialize_key(self, row: sqlite3.Row) -> dict[str, Any]:
        source_url = row["source_url"] or ""
        return {
            "id": row["id"],
            "platform": row["platform"] or "",
            "status": row["status"] or "",
            "api_key": mask_secret(row["api_key"] or ""),
            "base_url": row["base_url"] or "",
            "balance": row["balance"] or "",
            "source_url": source_url,
            "source_host": source_url.split("/")[2] if source_url.startswith("http") and "/" in source_url[8:] else "",
            "model_tier": row["model_tier"] or "",
            "rpm": row["rpm"] or 0,
            "is_high_value": bool(row["is_high_value"]),
            "found_time": format_time(row["found_time"]),
        }

    def keys(self, params: dict[str, list[str]]) -> dict[str, Any]:
        if not self.exists():
            return {"items": [], "total": 0, "db_exists": False}

        status = params.get("status", [""])[0].strip()
        platform = params.get("platform", [""])[0].strip()
        query = params.get("q", [""])[0].strip()
        limit = parse_int(params.get("limit", ["100"])[0], 100, 1, 500)
        offset = parse_int(params.get("offset", ["0"])[0], 0, 0, 1000000)

        where = []
        values: list[Any] = []
        if status in VALID_STATUSES:
            where.append("status = ?")
            values.append(status)
        if platform:
            where.append("platform = ?")
            values.append(platform)
        if query:
            like = f"%{query}%"
            where.append(
                "(platform LIKE ? OR status LIKE ? OR base_url LIKE ? OR balance LIKE ? "
                "OR source_url LIKE ? OR model_tier LIKE ?)"
            )
            values.extend([like, like, like, like, like, like])

        where_sql = f"WHERE {' AND '.join(where)}" if where else ""
        with self.connect() as conn:
            if not self.table_exists(conn, "leaked_keys"):
                return {"items": [], "total": 0, "db_exists": True}

            total = conn.execute(
                f"SELECT COUNT(*) FROM leaked_keys {where_sql}", values
            ).fetchone()[0]
            rows = conn.execute(
                f"SELECT * FROM leaked_keys {where_sql} "
                "ORDER BY found_time DESC, id DESC LIMIT ? OFFSET ?",
                values + [limit, offset],
            ).fetchall()
            return {
                "items": [self.serialize_key(row) for row in rows],
                "total": total,
                "db_exists": True,
                "limit": limit,
                "offset": offset,
            }

    def export_csv(self, params: dict[str, list[str]]) -> str:
        data = self.keys({**params, "limit": ["500"]})
        output = io.StringIO()
        fieldnames = [
            "id",
            "platform",
            "status",
            "api_key_masked",
            "base_url",
            "balance",
            "source_url",
            "model_tier",
            "rpm",
            "is_high_value",
            "found_time",
        ]
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        for item in data["items"]:
            writer.writerow(
                {
                    "id": item["id"],
                    "platform": item["platform"],
                    "status": item["status"],
                    "api_key_masked": item["api_key"],
                    "base_url": item["base_url"],
                    "balance": item["balance"],
                    "source_url": item["source_url"],
                    "model_tier": item["model_tier"],
                    "rpm": item["rpm"],
                    "is_high_value": int(item["is_high_value"]),
                    "found_time": item["found_time"],
                }
            )
        return output.getvalue()


class LeakLensHandler(BaseHTTPRequestHandler):
    store: DashboardStore
    controller: ScanController

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {self.address_string()} {fmt % args}")

    def send_json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_text(self, body: str, content_type: str, status: int = 200) -> None:
        encoded = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        try:
            if parsed.path == "/":
                self.serve_file(INDEX_FILE, "text/html; charset=utf-8")
            elif parsed.path.startswith("/static/"):
                relative = parsed.path.removeprefix("/static/")
                target = (STATIC_DIR / relative).resolve()
                if not str(target).startswith(str(STATIC_DIR.resolve())):
                    self.send_error(404)
                    return
                self.serve_file(target)
            elif parsed.path == "/api/summary":
                self.send_json(self.store.summary())
            elif parsed.path == "/api/keys":
                self.send_json(self.store.keys(params))
            elif parsed.path == "/api/health":
                self.send_json({
                    "ok": True,
                    "app": APP_NAME,
                    "db_path": str(self.store.db_path),
                    "scanner_running": self.controller.is_running(),
                })
            elif parsed.path == "/api/scan/status":
                self.send_json(self.controller.status())
            elif parsed.path == "/api/export.csv":
                body = self.store.export_csv(params)
                self.send_response(200)
                self.send_header("Content-Type", "text/csv; charset=utf-8")
                self.send_header("Content-Disposition", 'attachment; filename="leaklens-results.csv"')
                self.send_header("Content-Length", str(len(body.encode("utf-8"))))
                self.end_headers()
                self.wfile.write(body.encode("utf-8"))
            else:
                self.send_error(404)
        except sqlite3.Error as exc:
            self.send_json({"error": f"database error: {exc}"}, status=500)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try:
            payload = self.read_json_body()
            if parsed.path == "/api/scan/start":
                ok, response, status = self.controller.start(payload)
                if ok:
                    self.store.db_path = Path(response["db_path"])
                self.send_json(response, status=status)
            elif parsed.path == "/api/scan/stop":
                self.send_json(self.controller.stop())
            else:
                self.send_error(404)
        except json.JSONDecodeError:
            self.send_json({"error": "invalid JSON body"}, status=400)

    def read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0:
            return {}
        body = self.rfile.read(length).decode("utf-8")
        payload = json.loads(body)
        if isinstance(payload, dict):
            return payload
        return {}

    def do_HEAD(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/" and INDEX_FILE.exists():
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            return
        if parsed.path.startswith("/static/"):
            relative = parsed.path.removeprefix("/static/")
            target = (STATIC_DIR / relative).resolve()
            if str(target).startswith(str(STATIC_DIR.resolve())) and target.exists():
                guessed = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
                self.send_response(200)
                self.send_header("Content-Type", guessed)
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                return
        self.send_error(404)

    def serve_file(self, path: Path, content_type: str | None = None) -> None:
        if not path.exists() or not path.is_file():
            self.send_error(404)
            return
        body = path.read_bytes()
        guessed = content_type or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", guessed)
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def run(host: str, port: int, db_path: str) -> None:
    store = DashboardStore(db_path)
    controller = ScanController(db_path)

    class Handler(LeakLensHandler):
        pass

    Handler.store = store
    Handler.controller = controller
    server = ThreadingHTTPServer((host, port), Handler)
    url_host = "localhost" if host in {"0.0.0.0", "::"} else host
    print(f"{APP_NAME} Web Dashboard: http://{url_host}:{port}")
    print(f"Database: {store.db_path}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping dashboard...")
    finally:
        controller.stop()
        server.server_close()


def main() -> None:
    parser = argparse.ArgumentParser(description="LeakLens Web Dashboard")
    parser.add_argument("--host", default=os.getenv("LEAKLENS_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("LEAKLENS_PORT", "8787")))
    parser.add_argument("--db", default=os.getenv("LEAKLENS_DB", "leaked_keys.db"))
    args = parser.parse_args()
    run(args.host, args.port, args.db)


if __name__ == "__main__":
    main()
