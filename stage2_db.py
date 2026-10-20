"""SQLite storage for the stage two business workflow."""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

ROOT = Path(__file__).resolve().parent
DEFAULT_DB_PATH = ROOT / "data" / "stage2.db"
SEED_PATH = ROOT / "data" / "stage2_seed.json"
SCHEMA_VERSION = 5
# The demo inventory is reusable equipment.  Keep the expansion in one
# migration so an existing database gets the same capacity as a fresh seed,
# while startup remains idempotent.
TOOL_QUANTITY_BOOST = 3

SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS pumps (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, location TEXT NOT NULL,
  model TEXT NOT NULL, simulated INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS workers (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, role TEXT NOT NULL, simulated INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS worker_skills (
  worker_id TEXT NOT NULL REFERENCES workers(id) ON DELETE CASCADE,
  skill TEXT NOT NULL, PRIMARY KEY(worker_id, skill)
);
CREATE TABLE IF NOT EXISTS worker_availability (
  id INTEGER PRIMARY KEY AUTOINCREMENT, worker_id TEXT NOT NULL REFERENCES workers(id) ON DELETE CASCADE,
  work_date TEXT NOT NULL, start_time TEXT NOT NULL, end_time TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS inventory_items (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, category TEXT NOT NULL,
  total_qty INTEGER NOT NULL, available_qty INTEGER NOT NULL, unit TEXT NOT NULL,
  simulated INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS inspection_requests (
  id TEXT PRIMARY KEY, pump_id TEXT REFERENCES pumps(id), work_date TEXT,
  start_time TEXT, duration_minutes INTEGER, end_time TEXT, description TEXT,
  required_skill TEXT,
  status TEXT NOT NULL, missing_fields TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS plans (
  id TEXT PRIMARY KEY, request_id TEXT NOT NULL REFERENCES inspection_requests(id),
  status TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1, worker_id TEXT,
  inventory_json TEXT NOT NULL DEFAULT '[]', reason TEXT, work_order_id TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reservations (
  id TEXT PRIMARY KEY, plan_id TEXT NOT NULL REFERENCES plans(id), request_id TEXT NOT NULL,
  resource_type TEXT NOT NULL, resource_id TEXT NOT NULL, quantity INTEGER NOT NULL,
  status TEXT NOT NULL, start_at TEXT NOT NULL, end_at TEXT NOT NULL,
  created_at TEXT NOT NULL, released_at TEXT
);
CREATE TABLE IF NOT EXISTS work_orders (
  id TEXT PRIMARY KEY, number TEXT NOT NULL UNIQUE, request_id TEXT NOT NULL,
  plan_id TEXT NOT NULL, status TEXT NOT NULL, failure_reason TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS task_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, request_id TEXT, work_order_id TEXT,
  event_type TEXT NOT NULL, actor TEXT NOT NULL, details_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS idempotency_keys (
  key TEXT PRIMARY KEY, operation TEXT NOT NULL, response_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audio_analyses (
  id TEXT PRIMARY KEY, sha256 TEXT NOT NULL, original_filename TEXT NOT NULL,
  storage_path TEXT NOT NULL, model_version TEXT NOT NULL, sample_rate INTEGER NOT NULL,
  duration_seconds REAL NOT NULL, anomaly_score REAL NOT NULL, threshold REAL NOT NULL,
  verdict TEXT NOT NULL, status TEXT NOT NULL, user_confirmed INTEGER NOT NULL DEFAULT 0,
  error_message TEXT, request_id TEXT REFERENCES inspection_requests(id),
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_reservations_resource_window
  ON reservations(resource_type, resource_id, status, start_at, end_at);
CREATE INDEX IF NOT EXISTS idx_events_request ON task_events(request_id, created_at);
CREATE INDEX IF NOT EXISTS idx_audio_sha256 ON audio_analyses(sha256, created_at);
CREATE TABLE IF NOT EXISTS agent_sessions (
  session_id TEXT PRIMARY KEY, leader_aic TEXT NOT NULL, status TEXT NOT NULL,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS agent_tasks (
  task_id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES agent_sessions(session_id),
  external_task_id TEXT NOT NULL UNIQUE, request_id TEXT, plan_id TEXT,
  status TEXT NOT NULL, context_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS agent_messages (
  message_id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES agent_sessions(session_id),
  task_id TEXT NOT NULL REFERENCES agent_tasks(task_id), role TEXT NOT NULL,
  content TEXT NOT NULL, parsed_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS task_subtasks (
  subtask_id TEXT PRIMARY KEY, parent_task_id TEXT NOT NULL REFERENCES agent_tasks(task_id),
  external_task_id TEXT NOT NULL UNIQUE, partner TEXT NOT NULL, action TEXT NOT NULL,
  message_id TEXT, status TEXT NOT NULL, result_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS user_confirmations (
  confirmation_id TEXT PRIMARY KEY, task_id TEXT NOT NULL, action TEXT NOT NULL,
  decision TEXT NOT NULL, payload_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS partner_discovery_snapshots (
  snapshot_id TEXT PRIMARY KEY, task_id TEXT, query_json TEXT NOT NULL,
  candidates_json TEXT NOT NULL, source TEXT NOT NULL, duration_ms REAL NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS partner_selections (
  selection_id TEXT PRIMARY KEY, snapshot_id TEXT NOT NULL,
  partner_aic TEXT NOT NULL, reason TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_agent_messages_session ON agent_messages(session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_task_subtasks_parent ON task_subtasks(parent_task_id, created_at);
CREATE INDEX IF NOT EXISTS idx_discovery_task ON partner_discovery_snapshots(task_id, created_at);
"""


class ManagedConnection(sqlite3.Connection):
    """Close SQLite handles used by ``with connect_db()`` on Windows."""

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


def database_path(path: str | Path | None = None) -> Path:
    value = path or os.environ.get("GONGWEI_STAGE2_DB")
    return Path(value).expanduser().resolve() if value else DEFAULT_DB_PATH


def connect_db(path: str | Path | None = None) -> sqlite3.Connection:
    db_path = database_path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path, timeout=10, isolation_level=None, factory=ManagedConnection)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    return connection


@contextmanager
def transaction(path: str | Path | None = None) -> Iterator[sqlite3.Connection]:
    connection = connect_db(path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize_database(path: str | Path | None = None, seed_path: str | Path = SEED_PATH) -> Path:
    db_path = database_path(path)
    with transaction(db_path) as connection:
        connection.executescript(SCHEMA)
        audio_columns = {row[1] for row in connection.execute("PRAGMA table_info(audio_analyses)").fetchall()}
        if "request_id" not in audio_columns:
            connection.execute("ALTER TABLE audio_analyses ADD COLUMN request_id TEXT REFERENCES inspection_requests(id)")
        request_columns = {row[1] for row in connection.execute("PRAGMA table_info(inspection_requests)").fetchall()}
        if "required_skill" not in request_columns:
            connection.execute("ALTER TABLE inspection_requests ADD COLUMN required_skill TEXT")
        current_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        if current_version < 1:
            # Version 1 is the original stage-two schema.  CREATE IF NOT EXISTS
            # above makes upgrading an older file additive and preserves data.
            connection.execute("PRAGMA user_version = 1")
            current_version = 1
        if current_version < 2:
            # Version 2 records the explicit migration boundary used by the
            # final audit.  Future migrations must be additive and transactional.
            connection.execute("PRAGMA user_version = 2")
            current_version = 2
        if current_version < 3:
            connection.execute("PRAGMA user_version = 3")
            current_version = 3
        if current_version < 4:
            connection.execute("PRAGMA user_version = 4")
            current_version = 4
        if current_version < 5:
            # Existing installations were seeded with only one to three units
            # per tool.  Add capacity without touching active reservations:
            # increasing total and available by the same amount preserves the
            # currently reserved quantity and makes the migration safe to run
            # while an earlier test order is still open.
            connection.execute(
                "UPDATE inventory_items SET total_qty=total_qty+?, available_qty=available_qty+? WHERE category='tool'",
                (TOOL_QUANTITY_BOOST, TOOL_QUANTITY_BOOST),
            )
            connection.execute("PRAGMA user_version = 5")
            current_version = 5
        if current_version > SCHEMA_VERSION:
            raise RuntimeError(f"数据库版本 {current_version} 高于当前代码支持的 {SCHEMA_VERSION}。")
        if connection.execute("SELECT COUNT(*) FROM pumps").fetchone()[0] == 0:
            seed = json.loads(Path(seed_path).read_text(encoding="utf-8"))
            if seed.get("simulated") is not True:
                raise ValueError("阶段二数据库只允许使用 simulated=true 的演示数据")
            for pump in seed["pumps"]:
                connection.execute("INSERT INTO pumps(id,name,location,model) VALUES(?,?,?,?)",
                                   (pump["id"], pump["name"], pump["location"], pump["model"]))
            for worker in seed["workers"]:
                connection.execute("INSERT INTO workers(id,name,role) VALUES(?,?,?)",
                                   (worker["id"], worker["name"], worker["role"]))
                connection.executemany("INSERT INTO worker_skills(worker_id,skill) VALUES(?,?)",
                                       [(worker["id"], skill) for skill in worker["skills"]])
            for availability in seed["availability"]:
                connection.execute("INSERT INTO worker_availability(worker_id,work_date,start_time,end_time) VALUES(?,?,?,?)",
                                   (availability["worker_id"], availability["work_date"], availability["start_time"], availability["end_time"]))
            for item in seed["inventory"]:
                connection.execute("INSERT INTO inventory_items(id,name,category,total_qty,available_qty,unit) VALUES(?,?,?,?,?,?)",
                                   (item["id"], item["name"], item["category"], item["total_qty"], item["available_qty"], item["unit"]))
    return db_path


def upsert_agent_subtask(
    parent_task_id: str,
    external_task_id: str,
    partner: str,
    action: str,
    *,
    message_id: str | None = None,
    status: str = "working",
    result: dict | None = None,
    path: str | Path | None = None,
) -> None:
    """Persist the parent/child task relation used by MQ and local calls."""
    initialize_database(path)
    timestamp = datetime.now(timezone.utc).isoformat()
    with transaction(path) as connection:
        connection.execute(
            """INSERT INTO task_subtasks(subtask_id,parent_task_id,external_task_id,partner,action,message_id,status,result_json,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(external_task_id) DO UPDATE SET message_id=excluded.message_id,status=excluded.status,result_json=excluded.result_json,updated_at=excluded.updated_at""",
            (
                f"subtask-{external_task_id}",
                parent_task_id,
                external_task_id,
                partner,
                action,
                message_id,
                status,
                json.dumps(result or {}, ensure_ascii=False),
                timestamp,
                timestamp,
            ),
        )


def reopen_database(path: str | Path | None = None) -> Path:
    """Simulate a restart by closing any caller-owned connection and reopening the file."""
    return initialize_database(path)


def row_to_dict(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row is not None else None
