"""Small, immutable SQLite record store for the bounded local demo."""

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .domain import DomainError, hash_json


class Store:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute(
                "CREATE TABLE IF NOT EXISTS demo_analyses ("
                "id TEXT PRIMARY KEY, created_at TEXT NOT NULL, "
                "payload TEXT NOT NULL, payload_sha256 TEXT NOT NULL)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS demo_import_failures ("
                "request_id TEXT PRIMARY KEY, created_at TEXT NOT NULL, "
                "code TEXT NOT NULL, input_hashes TEXT NOT NULL)"
            )

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    def save(self, record: dict):
        public = record["public"]
        with self.connection() as db:
            db.execute(
                "INSERT INTO demo_analyses VALUES (?, ?, ?, ?)",
                (
                    public["id"], public["created_at"],
                    json.dumps(record, ensure_ascii=False, allow_nan=False), hash_json(record),
                ),
            )

    def load(self, analysis_id: str) -> dict:
        with self.connection() as db:
            row = db.execute(
                "SELECT payload, payload_sha256 FROM demo_analyses WHERE id = ?", (analysis_id,)
            ).fetchone()
        if row is None:
            raise DomainError("NOT_FOUND", "分析记录不存在。")
        try:
            record = json.loads(row[0])
            if hash_json(record) != row[1]:
                raise ValueError("checksum")
        except (ValueError, TypeError, DomainError):
            raise DomainError("STORAGE_ERROR", "历史记录校验失败，已停止读取。") from None
        return record

    def summaries(self, page: int = 1, page_size: int = 100) -> dict:
        with self.connection() as db:
            total = db.execute("SELECT COUNT(*) FROM demo_analyses").fetchone()[0]
            ids = db.execute(
                "SELECT id FROM demo_analyses ORDER BY created_at DESC, id ASC LIMIT ? OFFSET ?",
                (page_size, (page - 1) * page_size),
            ).fetchall()
        items = []
        for (analysis_id,) in ids:
            public = self.load(analysis_id)["public"]
            metrics = public["metrics"]["discovery"]
            items.append({
                "id": public["id"], "name": public["name"], "created_at": public["created_at"],
                "fixture_only": public["fixture_only"], "old_model_name": public["old_model"]["name"],
                "new_model_name": public["new_model"]["name"], "discovery_count": metrics["n"],
                "negative_flips": metrics["b"], "accuracy_drop": metrics["accuracy_drop"],
            })
        return {"items": items, "total": total, "page": page, "page_size": page_size}

    def save_failure(self, request_id: str, created_at: str, code: str, input_hashes: dict):
        with self.connection() as db:
            db.execute(
                "INSERT OR IGNORE INTO demo_import_failures VALUES (?, ?, ?, ?)",
                (request_id, created_at, code, json.dumps(input_hashes, sort_keys=True)),
            )

    def check(self):
        with self.connection() as db:
            status = db.execute("PRAGMA integrity_check").fetchone()[0]
            ids = db.execute("SELECT id FROM demo_analyses").fetchall()
        if status != "ok":
            raise DomainError("STORAGE_ERROR", "SQLite 完整性检查失败。")
        for (analysis_id,) in ids:
            self.load(analysis_id)
        return {"sqlite": status, "verified_records": len(ids)}
