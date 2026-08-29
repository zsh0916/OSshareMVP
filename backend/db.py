import sqlite3
import json
from contextlib import contextmanager
from pathlib import Path
from datetime import datetime
from typing import Iterator

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "messages.db"
DATA_DIR.mkdir(exist_ok=True)


def connect(*, rows_as_dict: bool = True) -> sqlite3.Connection:
    """Open the shared SQLite database with consistent safety settings."""
    conn = sqlite3.connect(DB_PATH)
    if rows_as_dict:
        conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def get_conn() -> sqlite3.Connection:
    """Compatibility connection used by the original message repository."""
    return connect(rows_as_dict=False)


@contextmanager
def transaction() -> Iterator[sqlite3.Connection]:
    """Commit a unit of work or roll it back when an operation fails."""
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()



def _ensure_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def _extract_target_department(value) -> str:
    """兼容 Dify 多层 JSON，递归提取目标部门。"""
    if value is None:
        return ""
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return ""
        try:
            value = json.loads(text)
        except Exception:
            return ""
    if isinstance(value, dict):
        for key in ("target_department", "department_name", "targetDepartment"):
            department = str(value.get(key) or "").strip()
            if department:
                return department
        for nested in value.values():
            department = _extract_target_department(nested)
            if department:
                return department
    elif isinstance(value, list):
        for item in value:
            department = _extract_target_department(item)
            if department:
                return department
    return ""


def init_db():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id TEXT UNIQUE,
            chat_id TEXT,
            chat_type TEXT,
            sender_open_id TEXT,
            sender_type TEXT,
            message_type TEXT,
            content_text TEXT,
            raw_content TEXT,
            create_time TEXT,
            received_at INTEGER,

            local_score INTEGER,
            local_level TEXT,
            local_reasons TEXT,

            ai_category TEXT,
            ai_priority TEXT,
            ai_need_push INTEGER,
            ai_assignee TEXT,
            ai_summary TEXT,
            ai_suggested_action TEXT,
            ai_result_json TEXT,

            card_status TEXT,
            card_sent_at TEXT,

            created_at TEXT,
            updated_at TEXT
        )
        """
    )

    # 记录消息最终归属部门。旧数据库会自动补列，不删除任何历史数据。
    _ensure_column(conn, "messages", "target_department", "TEXT")
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_messages_target_department ON messages(target_department)"
    )

    # 从历史 ai_result_json 回填目标部门，使升级前的消息也能按部门显示。
    rows = cur.execute(
        """
        SELECT id, ai_result_json
        FROM messages
        WHERE trim(COALESCE(target_department, '')) = ''
          AND trim(COALESCE(ai_result_json, '')) <> ''
        """
    ).fetchall()
    for message_row in rows:
        department = _extract_target_department(message_row[1])
        if department:
            cur.execute(
                "UPDATE messages SET target_department = ? WHERE id = ?",
                (department, int(message_row[0])),
            )

    conn.commit()
    conn.close()


def message_exists(message_id: str) -> bool:
    conn = get_conn()
    cur = conn.cursor()

    cur.execute(
        "SELECT 1 FROM messages WHERE message_id = ? LIMIT 1",
        (message_id,),
    )

    row = cur.fetchone()
    conn.close()

    return row is not None


def save_message_received(payload: dict):
    """
    消息刚收到时保存。
    如果 message_id 已存在，则忽略。
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn = get_conn()
    cur = conn.cursor()

    cur.execute(
        """
        INSERT OR IGNORE INTO messages (
            message_id,
            chat_id,
            chat_type,
            sender_open_id,
            sender_type,
            message_type,
            content_text,
            raw_content,
            create_time,
            received_at,
            card_status,
            created_at,
            updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            payload.get("message_id"),
            payload.get("chat_id"),
            payload.get("chat_type"),
            payload.get("sender_open_id"),
            payload.get("sender_type"),
            payload.get("message_type"),
            payload.get("content_text"),
            payload.get("raw_content"),
            payload.get("create_time"),
            payload.get("received_at"),
            "received",
            now,
            now,
        ),
    )

    conn.commit()
    conn.close()


def update_local_score(message_id: str, score_info: dict):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn = get_conn()
    cur = conn.cursor()

    cur.execute(
        """
        UPDATE messages
        SET
            local_score = ?,
            local_level = ?,
            local_reasons = ?,
            updated_at = ?
        WHERE message_id = ?
        """,
        (
            score_info.get("score"),
            score_info.get("level"),
            json.dumps(score_info.get("reasons", []), ensure_ascii=False),
            now,
            message_id,
        ),
    )

    conn.commit()
    conn.close()


def update_ai_result(message_id: str, ai_result: dict):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn = get_conn()
    cur = conn.cursor()

    cur.execute(
        """
        UPDATE messages
        SET
            ai_category = ?,
            ai_priority = ?,
            ai_need_push = ?,
            ai_assignee = ?,
            ai_summary = ?,
            ai_suggested_action = ?,
            ai_result_json = ?,
            target_department = ?,
            updated_at = ?
        WHERE message_id = ?
        """,
        (
            ai_result.get("category"),
            ai_result.get("priority"),
            1 if ai_result.get("need_push") else 0,
            ai_result.get("assignee"),
            ai_result.get("summary"),
            ai_result.get("suggested_action"),
            json.dumps(ai_result, ensure_ascii=False),
            str(ai_result.get("target_department") or "").strip(),
            now,
            message_id,
        ),
    )

    conn.commit()
    conn.close()


def update_card_status(message_id: str, status: str):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn = get_conn()
    cur = conn.cursor()

    cur.execute(
        """
        UPDATE messages
        SET
            card_status = ?,
            card_sent_at = ?,
            updated_at = ?
        WHERE message_id = ?
        """,
        (
            status,
            now if status == "sent" else None,
            now,
            message_id,
        ),
    )

    conn.commit()
    conn.close()


def print_recent_messages(limit: int = 10):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT
            id,
            content_text,
            local_score,
            ai_category,
            ai_priority,
            card_status,
            created_at
        FROM messages
        ORDER BY id DESC
        LIMIT ?
        """,
        (limit,),
    )

    rows = cur.fetchall()
    conn.close()

    print("\n最近消息记录：")
    for row in rows:
        print(row)

def get_message_by_message_id(message_id: str) -> dict | None:
    conn = get_conn()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute(
        """
        SELECT *
        FROM messages
        WHERE message_id = ?
        LIMIT 1
        """,
        (message_id,),
    )

    row = cur.fetchone()
    conn.close()

    if row is None:
        return None

    return dict(row)

# =========================
# Dify / 工作流配置
# =========================

WORKFLOW_EXTRA_COLUMNS = {
    "app_mode": "TEXT DEFAULT 'workflow'",
    "module_key": "TEXT",
    "timeout_seconds": "INTEGER DEFAULT 300",
    "response_mode": "TEXT DEFAULT 'auto'",
    "verify_ssl": "INTEGER DEFAULT 1",
    "use_system_proxy": "INTEGER DEFAULT 0",
}


def init_workflow_table():
    """创建并迁移工作流配置表，兼容早期单工作流版本。"""
    conn = get_conn()
    cur = conn.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS workflow_configs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            workflow_type TEXT DEFAULT 'dify',
            app_mode TEXT DEFAULT 'workflow',
            module_key TEXT,
            api_base TEXT NOT NULL,
            api_key TEXT NOT NULL,
            endpoint TEXT DEFAULT '/workflows/run',
            timeout_seconds INTEGER DEFAULT 300,
            response_mode TEXT DEFAULT 'auto',
            verify_ssl INTEGER DEFAULT 1,
            use_system_proxy INTEGER DEFAULT 0,
            description TEXT,
            input_schema_json TEXT,
            enabled INTEGER DEFAULT 1,
            created_at TEXT,
            updated_at TEXT
        )
        """
    )

    cur.execute("PRAGMA table_info(workflow_configs)")
    existing = {row[1] for row in cur.fetchall()}
    for column, ddl in WORKFLOW_EXTRA_COLUMNS.items():
        if column not in existing:
            cur.execute(f"ALTER TABLE workflow_configs ADD COLUMN {column} {ddl}")

    # 自动迁移旧记录：依据 endpoint 推断应用模式，并为已知模块补绑定键。
    cur.execute(
        """
        UPDATE workflow_configs
        SET app_mode = CASE
            WHEN lower(COALESCE(endpoint, '')) LIKE '%chat-messages%' THEN 'advanced-chat'
            ELSE 'workflow'
        END
        WHERE app_mode IS NULL OR trim(app_mode) = '' OR app_mode = 'dify'
        """
    )
    cur.execute(
        """
        UPDATE workflow_configs
        SET module_key = 'feishu_message_router'
        WHERE name = '飞书消息分类器' AND (module_key IS NULL OR trim(module_key) = '')
        """
    )
    cur.execute(
        """
        UPDATE workflow_configs
        SET module_key = 'oa_application_agent', app_mode = 'advanced-chat',
            endpoint = CASE WHEN trim(COALESCE(endpoint, '')) = '' THEN '/chat-messages' ELSE endpoint END,
            response_mode = CASE WHEN trim(COALESCE(response_mode, '')) = '' OR response_mode = 'auto' THEN 'streaming' ELSE response_mode END
        WHERE name = 'OA智能申请对话Agent'
        """
    )

    conn.commit()
    conn.close()


def get_enabled_workflow_by_name(name: str) -> dict | None:
    conn = get_conn()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(
        """
        SELECT * FROM workflow_configs
        WHERE name = ? AND enabled = 1
        ORDER BY id DESC LIMIT 1
        """,
        (name,),
    )
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def get_enabled_workflow_by_module(module_key: str) -> dict | None:
    conn = get_conn()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(
        """
        SELECT * FROM workflow_configs
        WHERE module_key = ? AND enabled = 1
        ORDER BY id DESC LIMIT 1
        """,
        (module_key,),
    )
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def resolve_enabled_workflow(*, module_key: str = "", name: str = "") -> dict | None:
    """优先按模块绑定查找，兼容按旧名称查找。"""
    if module_key:
        row = get_enabled_workflow_by_module(module_key)
        if row:
            return row
    if name:
        return get_enabled_workflow_by_name(name)
    return None
