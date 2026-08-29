"""HTTP application composition and compatibility API routes.

Existing endpoint paths are intentionally preserved. New feature domains should
be implemented as independent ``APIRouter`` modules and registered near the app
construction block below.
"""

import json
import re
import yaml
from datetime import datetime
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional, Dict, Any, List

from pydantic import BaseModel, Field
import sqlite3
import os
from pathlib import Path

from .db import DB_PATH

from .dify_client import DifyCallError, call_dify_app, infer_app_mode, default_endpoint

from .auth_system import (
    auth_router,
    authenticate_header,
    get_request_user,
    has_permission,
    require_permission,
    migrate_oa_columns,
    notify_application_submitted,
    write_operation_log,
)
from .document_search_api import router as document_search_router
from .meeting_minutes_api import router as meeting_minutes_router
from .employee_assessment_api import router as employee_assessment_router
from .employee_assessment_analysis_api import router as employee_assessment_analysis_router
from .report_generate_api import router as report_generate_router
BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = BASE_DIR / "config.yaml"

app = FastAPI(
    title="Smart Office AI Platform",
    description="Extensible OA, knowledge, assessment and message-routing API.",
    version="1.0.0",
)

cors_origins = [
    value.strip()
    for value in os.getenv("APP_CORS_ORIGINS", "http://localhost:5173").split(",")
    if value.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(document_search_router)
app.include_router(meeting_minutes_router)
app.include_router(employee_assessment_router)
app.include_router(employee_assessment_analysis_router)
app.include_router(report_generate_router)


def _required_permission_for_path(path: str, method: str) -> str:
    if path.startswith("/api/workflows"):
        return "workflow.manage"
    if path.startswith("/api/rules"):
        return "rule.manage"

    # 所有在职员工都可以进入消息中心，但普通员工和部门领导只能查看
    # main.py 已为目标部门每名员工生成 feishu_department_message 通知；
    # GET 列表再依据当前用户通知做数据隔离。
    if path == "/api/messages" and method == "GET":
        return "message.view_department"

    # 修改消息状态仍属于平台管理操作，普通员工不能调用。
    if path.startswith("/api/messages") or path.startswith("/api/dashboard/summary"):
        return "message.view"

    if path.startswith("/api/oa/agent") or path.startswith("/api/oa/intent"):
        return "oa.create"
    if path == "/api/oa/applications" and method == "POST":
        return "oa.create"
    return ""


@app.middleware("http")
async def authenticate_api_request(request: Request, call_next):
    path = request.url.path
    if request.method == "OPTIONS" or not path.startswith("/api") or path == "/api/auth/login":
        return await call_next(request)

    try:
        user = authenticate_header(request.headers.get("Authorization"))
        request.state.current_user = user
        if int(user.get("must_change_password") or 0) and path not in {
            "/api/auth/me", "/api/auth/change-password", "/api/auth/logout"
        }:
            return JSONResponse(
                status_code=403,
                content={
                    "detail": "首次登录必须先修改初始密码",
                    "code": "PASSWORD_CHANGE_REQUIRED",
                },
            )
        permission = _required_permission_for_path(path, request.method.upper())
        if permission:
            require_permission(user, permission)
    except HTTPException as exc:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    return await call_next(request)


def query_db(sql: str, params: tuple = ()):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(sql, params)
    rows = cur.fetchall()
    conn.close()
    return [dict(row) for row in rows]



MESSAGE_CATEGORY_DEPARTMENT_CANDIDATES = {
    "技术故障": ("技术部",),
    "销售商机": ("销售部", "市场部", "业务部"),
    "市场推广": ("市场部", "销售部", "业务部"),
    "财务事项": ("财务部",),
    "人事行政": ("人事部", "行政部"),
    "合同法务": ("法务部", "行政部"),
    "客户投诉": ("业务部", "客服部", "市场部"),
    "退款处理": ("财务部", "业务部"),
    "售后服务": ("业务部", "客服部", "市场部"),
    "交付物流": ("物流部", "业务部"),
}


def _extract_message_department(value) -> str:
    """从 Dify 多层输出中递归提取 target_department。"""
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
            department = _extract_message_department(nested)
            if department:
                return department
    elif isinstance(value, list):
        for item in value:
            department = _extract_message_department(item)
            if department:
                return department
    return ""


def _department_from_notification_title(title: str, known_departments: set[str]) -> str:
    text = str(title or "").strip()
    if not text:
        return ""
    for separator in ("｜", "|"):
        prefix = text.split(separator, 1)[0].strip()
        if prefix in known_departments:
            return prefix
    return ""


def _fallback_department_for_category(category: str, known_departments: set[str]) -> str:
    for candidate in MESSAGE_CATEGORY_DEPARTMENT_CANDIDATES.get(str(category or "").strip(), ()):
        if candidate in known_departments:
            return candidate
    return ""


def init_message_department_routing() -> dict[str, int]:
    """
    为 messages 增加 target_department 并恢复历史归属。

    回填优先级：
    1. ai_result_json.target_department；
    2. 已生成部门通知标题；
    3. 仅在缺少显式部门时，按 AI 分类和现有部门名称兼容推断。
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        tables = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        if "messages" not in tables:
            return {"added_column": 0, "backfilled": 0}

        columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(messages)").fetchall()
        }
        added_column = 0
        if "target_department" not in columns:
            conn.execute("ALTER TABLE messages ADD COLUMN target_department TEXT")
            added_column = 1
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_messages_target_department "
            "ON messages(target_department)"
        )

        known_departments: set[str] = set()
        if "departments" in tables:
            known_departments = {
                str(row["name"] or "").strip()
                for row in conn.execute("SELECT name FROM departments").fetchall()
                if str(row["name"] or "").strip()
            }

        notification_departments: dict[int, str] = {}
        if "notifications" in tables:
            notification_rows = conn.execute(
                """
                SELECT business_id, title
                FROM notifications
                WHERE notification_type = 'feishu_department_message'
                  AND business_type = 'message'
                  AND business_id IS NOT NULL
                ORDER BY id DESC
                """
            ).fetchall()
            for row in notification_rows:
                message_id = int(row["business_id"] or 0)
                if not message_id or message_id in notification_departments:
                    continue
                department = _department_from_notification_title(
                    row["title"], known_departments
                )
                if department:
                    notification_departments[message_id] = department

        rows = conn.execute(
            """
            SELECT id, target_department, ai_result_json, ai_category
            FROM messages
            WHERE trim(COALESCE(target_department, '')) = ''
            ORDER BY id
            """
        ).fetchall()
        backfilled = 0
        for row in rows:
            department = _extract_message_department(row["ai_result_json"])
            if not department:
                department = notification_departments.get(int(row["id"]), "")
            if not department:
                department = _fallback_department_for_category(
                    row["ai_category"], known_departments
                )
            if department:
                conn.execute(
                    "UPDATE messages SET target_department = ? WHERE id = ?",
                    (department, int(row["id"])),
                )
                backfilled += 1

        conn.commit()
        return {"added_column": added_column, "backfilled": backfilled}
    finally:
        conn.close()


# 后端启动时自动迁移，不删除、重建或覆盖 messages 历史数据。
MESSAGE_DEPARTMENT_MIGRATION = init_message_department_routing()


@app.get("/")
def home():
    return {
        "name": "飞书 AI 消息分流平台",
        "status": "running"
    }


@app.get("/api/meta/capabilities", tags=["platform"])
def platform_capabilities():
    """Describe stable extension points without exposing private configuration."""
    return {
        "api_version": "1.0",
        "modules": [
            "oa", "document_search", "meeting_minutes", "employee_assessment",
            "assessment_analysis", "report_generation", "message_routing",
        ],
        "extension_points": {
            "ai_provider": "backend.dify_client",
            "database": "backend.db",
            "event_worker": "backend.feishu_worker",
        },
    }


class MessageStatusUpdateRequest(BaseModel):
    status: str = Field(..., min_length=1, max_length=50)


MANUAL_MESSAGE_STATUSES = {"handled", "wrong_ai_result", "manual_followup"}


@app.post("/api/messages/{message_id}/status")
def update_message_status(
    message_id: str,
    req: MessageStatusUpdateRequest,
    request: Request,
):
    status = req.status.strip()
    if status not in MANUAL_MESSAGE_STATUSES:
        raise HTTPException(status_code=400, detail="不支持的消息状态")

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE messages
        SET card_status = ?, updated_at = ?
        WHERE message_id = ?
        """,
        (status, now, message_id),
    )
    affected = cur.rowcount
    conn.commit()
    conn.close()

    if affected == 0:
        raise HTTPException(status_code=404, detail="消息不存在")

    user = get_request_user(request)
    write_operation_log(
        user,
        "update_message_status",
        "message",
        message_id,
        {"status": status},
        request.client.host if request.client else "",
    )
    return {"success": True, "message_id": message_id, "status": status}


@app.get("/api/messages")
def list_messages(request: Request, limit: int = 50):
    """
    按当前账号权限返回飞书业务消息。

    - 平台管理员、超级管理员：查看全部历史消息；
    - 普通员工、部门领导：查看 target_department 与本人部门一致的全部历史消息；
    - 同时兼容旧版已经给本人生成 feishu_department_message 通知的消息。
    """
    user = get_request_user(request)
    safe_limit = max(1, min(int(limit or 50), 200))

    select_sql = """
        SELECT
            m.id,
            m.message_id,
            m.chat_id,
            m.sender_open_id,
            m.content_text,
            m.local_score,
            m.local_level,
            m.ai_category,
            m.ai_priority,
            m.ai_assignee,
            m.ai_summary,
            m.target_department,
            m.card_status,
            m.created_at
        FROM messages m
    """

    if has_permission(user, "message.view"):
        return query_db(
            select_sql + """
            ORDER BY m.id DESC
            LIMIT ?
            """,
            (safe_limit,),
        )

    department_name = str(user.get("department_name") or "").strip()
    if not department_name:
        return []

    # 直接按消息归属部门查询，历史消息不再依赖升级后才生成的个人通知。
    # EXISTS 保留对早期通知记录的兼容，且不会造成重复行。
    return query_db(
        select_sql + """
        WHERE trim(COALESCE(m.target_department, '')) = ?
           OR EXISTS (
                SELECT 1
                FROM notifications n
                WHERE n.user_id = ?
                  AND n.notification_type = 'feishu_department_message'
                  AND n.business_type = 'message'
                  AND n.business_id = m.id
           )
        ORDER BY m.id DESC
        LIMIT ?
        """,
        (department_name, int(user["id"]), safe_limit),
    )


@app.get("/api/dashboard/summary")
def dashboard_summary():
    total = query_db("SELECT COUNT(*) AS c FROM messages")[0]["c"]

    p0 = query_db(
        "SELECT COUNT(*) AS c FROM messages WHERE ai_priority = 'P0'"
    )[0]["c"]

    p1 = query_db(
        "SELECT COUNT(*) AS c FROM messages WHERE ai_priority = 'P1'"
    )[0]["c"]

    handled = query_db(
        "SELECT COUNT(*) AS c FROM messages WHERE card_status = 'handled'"
    )[0]["c"]

    wrong = query_db(
        "SELECT COUNT(*) AS c FROM messages WHERE card_status = 'wrong_ai_result'"
    )[0]["c"]

    sent = query_db(
        "SELECT COUNT(*) AS c FROM messages WHERE card_status = 'sent'"
    )[0]["c"]

    return {
        "total": total,
        "p0": p0,
        "p1": p1,
        "handled": handled,
        "wrong_ai_result": wrong,
        "sent": sent,
    }

# =========================
# Dify 应用配置管理
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
    conn = sqlite3.connect(DB_PATH)
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
        SET module_key = 'oa_application_agent',
            app_mode = 'advanced-chat',
            endpoint = '/chat-messages',
            response_mode = 'streaming',
            timeout_seconds = CASE WHEN timeout_seconds IS NULL OR timeout_seconds < 120 THEN 300 ELSE timeout_seconds END
        WHERE name = 'OA智能申请对话Agent'
        """
    )
    conn.commit()
    conn.close()


init_workflow_table()


class WorkflowCreateRequest(BaseModel):
    name: str
    workflow_type: str = "dify"
    app_mode: str = "workflow"
    module_key: str = ""
    api_base: str = "http://127.0.0.1/v1"
    api_key: str
    endpoint: str = ""
    timeout_seconds: int = 300
    response_mode: str = "auto"
    verify_ssl: int = 1
    use_system_proxy: int = 0
    description: str = ""
    input_schema_json: str = "{}"
    enabled: int = 1


class WorkflowUpdateRequest(BaseModel):
    name: str | None = None
    workflow_type: str | None = None
    app_mode: str | None = None
    module_key: str | None = None
    api_base: str | None = None
    api_key: str | None = None
    endpoint: str | None = None
    timeout_seconds: int | None = None
    response_mode: str | None = None
    verify_ssl: int | None = None
    use_system_proxy: int | None = None
    description: str | None = None
    input_schema_json: str | None = None
    enabled: int | None = None


class WorkflowTestRequest(BaseModel):
    inputs: dict = Field(default_factory=dict)
    query: str = ""
    user: str = "web-test-user"
    conversation_id: str = ""


def mask_api_key(key: str | None):
    if not key:
        return ""
    if len(key) <= 10:
        return key[:3] + "***"
    return key[:6] + "****" + key[-4:]


def normalize_workflow_values(data: dict) -> dict:
    result = dict(data)
    app_mode = str(result.get("app_mode") or "").strip().lower()
    endpoint = str(result.get("endpoint") or "").strip()
    if not app_mode:
        app_mode = "advanced-chat" if "chat-messages" in endpoint.lower() else "workflow"
    if app_mode in {"chat", "chatbot", "agent-chat"}:
        app_mode = "advanced-chat"
    result["app_mode"] = app_mode
    if not endpoint:
        result["endpoint"] = default_endpoint(app_mode)
    elif not endpoint.startswith("/"):
        result["endpoint"] = "/" + endpoint
    result["api_base"] = str(result.get("api_base") or "").rstrip("/")
    result["timeout_seconds"] = max(30, min(int(result.get("timeout_seconds") or 300), 900))
    result["response_mode"] = str(result.get("response_mode") or "auto").lower()
    return result


def get_workflow_config(*, workflow_id: int | None = None, name: str = "", module_key: str = "", enabled_only: bool = True):
    clauses = []
    params = []
    if workflow_id is not None:
        clauses.append("id = ?")
        params.append(workflow_id)
    elif module_key:
        clauses.append("module_key = ?")
        params.append(module_key)
    elif name:
        clauses.append("name = ?")
        params.append(name)
    else:
        return None
    if enabled_only:
        clauses.append("enabled = 1")
    rows = query_db(
        f"SELECT * FROM workflow_configs WHERE {' AND '.join(clauses)} ORDER BY id DESC LIMIT 1",
        tuple(params),
    )
    return rows[0] if rows else None


@app.get("/api/workflows")
def list_workflows():
    rows = query_db("SELECT * FROM workflow_configs ORDER BY id DESC")
    for row in rows:
        row["app_mode"] = infer_app_mode(row)
        row["api_key_masked"] = mask_api_key(row.get("api_key"))
        row.pop("api_key", None)
    return rows


@app.post("/api/workflows")
def create_workflow(req: WorkflowCreateRequest):
    data = normalize_workflow_values(req.model_dump())
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO workflow_configs (
            name, workflow_type, app_mode, module_key, api_base, api_key, endpoint,
            timeout_seconds, response_mode, verify_ssl, use_system_proxy,
            description, input_schema_json, enabled, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            data["name"], data["workflow_type"], data["app_mode"], data.get("module_key", ""),
            data["api_base"], data["api_key"], data["endpoint"], data["timeout_seconds"],
            data["response_mode"], data.get("verify_ssl", 1), data.get("use_system_proxy", 0),
            data.get("description", ""), data.get("input_schema_json", "{}"), data.get("enabled", 1),
            now, now,
        ),
    )
    conn.commit()
    workflow_id = cur.lastrowid
    conn.close()
    return {"success": True, "id": workflow_id}


@app.put("/api/workflows/{workflow_id}")
def update_workflow(workflow_id: int, req: WorkflowUpdateRequest):
    data = req.model_dump(exclude_unset=True)
    if "api_key" in data and not data["api_key"]:
        data.pop("api_key")
    if not data:
        return {"success": False, "message": "没有需要更新的字段"}

    current = get_workflow_config(workflow_id=workflow_id, enabled_only=False)
    if not current:
        raise HTTPException(status_code=404, detail="未找到 Dify 应用配置")
    merged = dict(current)
    merged.update(data)
    normalized = normalize_workflow_values(merged)
    for key in ("app_mode", "endpoint", "api_base", "timeout_seconds", "response_mode"):
        if key in data or key in {"app_mode", "endpoint"}:
            data[key] = normalized[key]

    fields = [f"{key} = ?" for key in data]
    values = list(data.values())
    fields.append("updated_at = ?")
    values.append(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    values.append(workflow_id)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(f"UPDATE workflow_configs SET {', '.join(fields)} WHERE id = ?", tuple(values))
    conn.commit()
    affected = cur.rowcount
    conn.close()
    return {"success": affected > 0, "affected": affected}


@app.delete("/api/workflows/{workflow_id}")
def delete_workflow(workflow_id: int):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("DELETE FROM workflow_configs WHERE id = ?", (workflow_id,))
    conn.commit()
    affected = cur.rowcount
    conn.close()
    return {"success": affected > 0, "affected": affected}


@app.post("/api/workflows/{workflow_id}/test")
def test_workflow(workflow_id: int, req: WorkflowTestRequest):
    workflow = get_workflow_config(workflow_id=workflow_id, enabled_only=False)
    if not workflow:
        raise HTTPException(status_code=404, detail="未找到 Dify 应用配置")
    try:
        result = call_dify_app(
            workflow,
            inputs=req.inputs,
            query=req.query,
            user=req.user,
            conversation_id=req.conversation_id,
        )
        return result
    except DifyCallError as exc:
        return {"success": False, **exc.as_dict(), "app_mode": infer_app_mode(workflow)}


# =========================
# 规则配置管理
# =========================

def init_rule_table():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS rule_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rule_type TEXT NOT NULL,
            rule_key TEXT NOT NULL,
            rule_value TEXT,
            weight INTEGER DEFAULT 0,
            enabled INTEGER DEFAULT 1,
            description TEXT,
            created_at TEXT,
            updated_at TEXT
        )
        """
    )

    conn.commit()
    conn.close()


def seed_rules_from_config_yaml():
    """
    如果 rule_items 为空，则从 config.yaml 初始化一份规则。
    只初始化一次，后续以网页数据库配置为准。
    """
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM rule_items")
    count = cur.fetchone()[0]

    if count > 0:
        conn.close()
        return

    if not CONFIG_PATH.exists():
        conn.close()
        return

    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    rows = []

    for key, weight in config.get("keyword_weights", {}).items():
        rows.append(("keyword", key, "", int(weight), 1, "关键词权重", now, now))

    private_chat_ids = [value.strip() for value in os.getenv("TARGET_CHAT_IDS", "").split(",") if value.strip()]
    chat_aliases = {
        f"CHAT_ID_{name}": value
        for name, value in zip(("PRIMARY", "SECONDARY", "TERTIARY"), private_chat_ids)
    }
    for key, weight in config.get("group_weights", {}).items():
        rows.append(("group", chat_aliases.get(str(key), str(key)), "", int(weight), 1, "飞书群权重", now, now))

    for key, weight in config.get("time_weights", {}).items():
        rows.append(("time", key, "", int(weight), 1, "时间段权重", now, now))

    for key, value in config.get("thresholds", {}).items():
        rows.append(("threshold", key, "", int(value), 1, "推送阈值", now, now))

    for key, weight in config.get("source_weights", {}).items():
        rows.append(("source", key, "", int(weight), 1, "来源权重", now, now))

    cur.executemany(
        """
        INSERT INTO rule_items (
            rule_type,
            rule_key,
            rule_value,
            weight,
            enabled,
            description,
            created_at,
            updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )

    conn.commit()
    conn.close()


init_rule_table()
seed_rules_from_config_yaml()


class RuleCreateRequest(BaseModel):
    rule_type: str
    rule_key: str
    rule_value: str = ""
    weight: int = 0
    enabled: int = 1
    description: str = ""


class RuleUpdateRequest(BaseModel):
    rule_type: str | None = None
    rule_key: str | None = None
    rule_value: str | None = None
    weight: int | None = None
    enabled: int | None = None
    description: str | None = None


@app.get("/api/rules")
def list_rules():
    rows = query_db(
        """
        SELECT
            id,
            rule_type,
            rule_key,
            rule_value,
            weight,
            enabled,
            description,
            created_at,
            updated_at
        FROM rule_items
        ORDER BY
            CASE rule_type
                WHEN 'source' THEN 1
                WHEN 'group' THEN 2
                WHEN 'keyword' THEN 3
                WHEN 'time' THEN 4
                WHEN 'threshold' THEN 5
                ELSE 9
            END,
            id DESC
        """
    )

    return rows


@app.post("/api/rules")
def create_rule(req: RuleCreateRequest):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO rule_items (
            rule_type,
            rule_key,
            rule_value,
            weight,
            enabled,
            description,
            created_at,
            updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            req.rule_type,
            req.rule_key,
            req.rule_value,
            req.weight,
            req.enabled,
            req.description,
            now,
            now,
        ),
    )

    conn.commit()
    rule_id = cur.lastrowid
    conn.close()

    return {
        "success": True,
        "id": rule_id,
    }


@app.put("/api/rules/{rule_id}")
def update_rule(rule_id: int, req: RuleUpdateRequest):
    data = req.model_dump(exclude_unset=True)

    if not data:
        return {
            "success": False,
            "message": "没有需要更新的字段"
        }

    fields = []
    values = []

    for key, value in data.items():
        fields.append(f"{key} = ?")
        values.append(value)

    fields.append("updated_at = ?")
    values.append(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    values.append(rule_id)

    sql = f"""
    UPDATE rule_items
    SET {", ".join(fields)}
    WHERE id = ?
    """

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(sql, tuple(values))
    conn.commit()

    affected = cur.rowcount
    conn.close()

    return {
        "success": affected > 0,
        "affected": affected,
        "id": rule_id,
    }


@app.delete("/api/rules/{rule_id}")
def delete_rule(rule_id: int):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute(
        "DELETE FROM rule_items WHERE id = ?",
        (rule_id,),
    )

    conn.commit()
    affected = cur.rowcount
    conn.close()

    return {
        "success": affected > 0,
        "affected": affected,
        "id": rule_id,
    }
# =========================
# OA 智能申请
# =========================


def init_oa_application_table():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS oa_applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            application_type TEXT,
            application_type_name TEXT,
            scene TEXT,
            intent_text TEXT,
            applicant_name TEXT,
            department TEXT,
            summary TEXT,
            form_data_json TEXT,
            submit_data_json TEXT,
            status TEXT DEFAULT 'draft',
            source TEXT,
            module_key TEXT,
            workflow_name TEXT,
            dify_result_json TEXT,
            created_at TEXT,
            updated_at TEXT,
            submitted_at TEXT
        )
        """
    )
    cur.execute("PRAGMA table_info(oa_applications)")
    existing = {row[1] for row in cur.fetchall()}
    additions = {
        "submit_data_json": "TEXT", "module_key": "TEXT", "workflow_name": "TEXT",
        "dify_result_json": "TEXT", "submitted_at": "TEXT",
        "applicant_user_id": "INTEGER", "department_id": "INTEGER",
        "approver_user_id": "INTEGER", "approval_comment": "TEXT",
        "approved_at": "TEXT", "rejected_at": "TEXT",
    }
    for column, ddl in additions.items():
        if column not in existing:
            cur.execute(f"ALTER TABLE oa_applications ADD COLUMN {column} {ddl}")
    conn.commit()
    conn.close()


def init_oa_agent_session_table():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS oa_agent_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT UNIQUE NOT NULL,
            dify_conversation_id TEXT,
            workflow_id INTEGER,
            workflow_name TEXT,
            user_id INTEGER,
            created_at TEXT,
            updated_at TEXT
        )
        """
    )
    cur.execute("PRAGMA table_info(oa_agent_sessions)")
    existing = {row[1] for row in cur.fetchall()}
    if "workflow_id" not in existing:
        cur.execute("ALTER TABLE oa_agent_sessions ADD COLUMN workflow_id INTEGER")
    if "user_id" not in existing:
        cur.execute("ALTER TABLE oa_agent_sessions ADD COLUMN user_id INTEGER")
    conn.commit()
    conn.close()


init_oa_application_table()
init_oa_agent_session_table()
migrate_oa_columns()


class OaIntentRecognizeRequest(BaseModel):
    text: str
    workflow_name: str = ""
    workflow_id: int | None = None
    module_key: str = "oa_application_intent"


class OaAgentChatRequest(BaseModel):
    session_id: str = Field(..., description="前端本地会话ID")
    message: str = Field(..., description="员工本轮输入")
    workflow_name: str = ""
    workflow_id: int | None = None
    module_key: str = "oa_application_agent"


class OaApplicationCreateRequest(BaseModel):
    application_type: str = ""
    application_type_name: str = ""
    scene: str = ""
    intent_text: str = ""
    applicant_name: str = ""
    department: str = ""
    form_data: Dict[str, Any] = Field(default_factory=dict)
    submit_data: Optional[Dict[str, Any]] = None
    dify_result: Optional[Dict[str, Any]] = None
    summary: str = ""
    status: str = "draft"
    source: str = "web_oa_agent_dify_chat"
    module_key: str = "oa_application_agent"
    workflow_name: str = ""


class OaApplicationUpdateRequest(BaseModel):
    application_type: Optional[str] = None
    application_type_name: Optional[str] = None
    scene: Optional[str] = None
    intent_text: Optional[str] = None
    applicant_name: Optional[str] = None
    department: Optional[str] = None
    form_data: Optional[Dict[str, Any]] = None
    submit_data: Optional[Dict[str, Any]] = None
    dify_result: Optional[Dict[str, Any]] = None
    summary: Optional[str] = None
    status: Optional[str] = None
    source: Optional[str] = None
    module_key: Optional[str] = None
    workflow_name: Optional[str] = None


def resolve_oa_workflow(*, workflow_id: int | None = None, workflow_name: str = "", module_key: str = ""):
    workflow = get_workflow_config(workflow_id=workflow_id) if workflow_id else None
    if not workflow and module_key:
        workflow = get_workflow_config(module_key=module_key)
    if not workflow and workflow_name:
        workflow = get_workflow_config(name=workflow_name)
    return workflow


@app.get("/api/oa/agent/config")
def get_oa_agent_config(request: Request):
    get_request_user(request)
    rows = query_db(
        """
        SELECT id, name, app_mode, module_key, endpoint, description, enabled
        FROM workflow_configs
        WHERE enabled = 1
          AND (module_key = 'oa_application_agent' OR lower(COALESCE(endpoint, '')) LIKE '%chat-messages%')
        ORDER BY CASE WHEN module_key = 'oa_application_agent' THEN 0 ELSE 1 END, id DESC
        """
    )
    return rows


def local_oa_intent_recognize(text: str):
    text = text or ""
    if any(k in text for k in ["请假", "事假", "病假", "年假", "调休", "婚假", "产假"]):
        return {"application_type": "leave", "application_type_name": "请假申请", "confidence": 0.88, "reason": "识别到请假关键词。", "prefill_data": {}}
    if any(k in text for k in ["加班", "周末", "延时", "通宵"]):
        return {"application_type": "overtime", "application_type_name": "加班申请", "confidence": 0.86, "reason": "识别到加班关键词。", "prefill_data": {}}
    if any(k in text for k in ["出差", "差旅", "高铁", "飞机", "目的地", "住宿酒店"]):
        return {"application_type": "business_trip", "application_type_name": "出差申请", "confidence": 0.9, "reason": "识别到明确差旅或跨城市行程。", "prefill_data": {}}
    if any(k in text for k in ["外出", "外勤", "拜访", "供应商", "客户拜访"]):
        return {"application_type": "out", "application_type_name": "外出申请", "confidence": 0.84, "reason": "识别到外出或拜访关键词。", "prefill_data": {}}
    if any(k in text for k in ["报销", "发票", "餐费", "打车", "交通费"]):
        return {"application_type": "expense_reimbursement", "application_type_name": "费用报销申请单", "confidence": 0.9, "reason": "识别到普通费用报销；未出现明确差旅行程信息。", "prefill_data": {}}
    if any(k in text for k in ["经费", "活动", "预算", "沙龙", "团建", "推广"]):
        return {"application_type": "activity_budget", "application_type_name": "活动经费申请", "confidence": 0.85, "reason": "识别到活动经费关键词。", "prefill_data": {}}
    return {"application_type": "", "application_type_name": "", "confidence": 0.0, "reason": "未识别到明确申请类型。", "prefill_data": {}}


def extract_dify_outputs(resp_data: dict):
    if not isinstance(resp_data, dict):
        return {}
    outputs = resp_data.get("outputs") or {}
    if not outputs and isinstance(resp_data.get("data"), dict):
        outputs = resp_data["data"].get("outputs") or {}
    if isinstance(outputs, dict) and "result" in outputs:
        result = outputs.get("result")
        if isinstance(result, dict):
            return result
        if isinstance(result, str):
            try:
                return json.loads(result)
            except Exception:
                return {"raw_result": result}
    return outputs if isinstance(outputs, dict) else {}


@app.post("/api/oa/intent/recognize")
def recognize_oa_intent(req: OaIntentRecognizeRequest):
    workflow = resolve_oa_workflow(
        workflow_id=req.workflow_id,
        workflow_name=req.workflow_name,
        module_key=req.module_key,
    )
    if not workflow:
        fallback = local_oa_intent_recognize(req.text)
        fallback["source"] = "local_fallback_no_workflow"
        return fallback
    try:
        response = call_dify_app(
            workflow,
            inputs={"text": req.text, "content": req.text, "module_key": req.module_key, "task_type": "oa_intent_recognize"},
            query=req.text if infer_app_mode(workflow) == "advanced-chat" else "",
            user="oa-intent-user",
        )
        outputs = extract_dify_outputs(response)
        if outputs.get("application_type"):
            return {
                "application_type": outputs.get("application_type"),
                "application_type_name": outputs.get("application_type_name", ""),
                "confidence": outputs.get("confidence", 0.8),
                "reason": outputs.get("reason", "由 Dify 返回。"),
                "prefill_data": outputs.get("prefill_data", {}),
                "source": "Dify",
            }
    except DifyCallError as exc:
        fallback = local_oa_intent_recognize(req.text)
        fallback.update({"source": "local_fallback", "dify_error": exc.as_dict()})
        return fallback
    fallback = local_oa_intent_recognize(req.text)
    fallback["source"] = "local_fallback_empty_output"
    return fallback


def get_oa_status_name(status: str | None):
    return {"draft": "草稿", "submitted": "待审批", "approved": "已通过", "rejected": "已驳回", "cancelled": "已撤销"}.get(status or "", status or "未知")


def _bind_form_to_logged_user(payload: dict | None, user: dict) -> dict:
    data = dict(payload or {})
    data["applicant_name"] = user.get("name", "")
    data["department"] = user.get("department_name", "")
    return data


def _bind_submit_to_logged_user(payload: dict | None, user: dict) -> dict:
    data = dict(payload or {})
    fields = dict(data.get("fields") or {})
    applicant = dict(fields.get("applicant_name") or {})
    applicant.update({"label": applicant.get("label") or "申请人姓名", "value": user.get("name", "")})
    fields["applicant_name"] = applicant
    department = dict(fields.get("department") or {})
    department.update({"label": department.get("label") or "所属部门", "value": user.get("department_name", "")})
    fields["department"] = department
    data["fields"] = fields
    return data


def _oa_row_accessible(user: dict, row: dict, *, edit: bool = False) -> bool:
    if has_permission(user, "oa.view_all"):
        return True

    applicant_user_id = int(row.get("applicant_user_id") or 0)
    if applicant_user_id == int(user.get("id") or -1):
        return True

    # 兼容账号体系上线前产生的历史申请：尚未绑定账号时，姓名和部门同时一致可视为本人。
    legacy_owner_match = (
        not applicant_user_id
        and str(row.get("applicant_name") or "").strip() == str(user.get("name") or "").strip()
        and str(row.get("department") or "").strip() == str(user.get("department_name") or "").strip()
    )
    if legacy_owner_match:
        return True

    same_department = (
        int(row.get("department_id") or 0) == int(user.get("department_id") or -1)
        or (row.get("department") and row.get("department") == user.get("department_name"))
    )
    if not edit and has_permission(user, "oa.view_department") and same_department:
        return True
    return False


@app.post("/api/oa/applications")
def create_oa_application(req: OaApplicationCreateRequest, request: Request):
    user = get_request_user(request)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    status = "draft" if req.status not in {"draft", "submitted"} else req.status
    submitted_at = now if status == "submitted" else None
    form_data = _bind_form_to_logged_user(req.form_data, user)
    submit_data = _bind_submit_to_logged_user(req.submit_data, user)
    summary = req.summary or f"{user.get('department_name') or ''}{user.get('name')}提交{req.application_type_name or 'OA申请'}"

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO oa_applications (
            application_type, application_type_name, scene, intent_text, applicant_name,
            department, summary, form_data_json, submit_data_json, status, source,
            module_key, workflow_name, dify_result_json, created_at, updated_at, submitted_at,
            applicant_user_id, department_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            req.application_type, req.application_type_name, req.scene, req.intent_text,
            user.get("name", ""), user.get("department_name", ""), summary,
            json.dumps(form_data, ensure_ascii=False),
            json.dumps(submit_data, ensure_ascii=False),
            status, req.source, req.module_key, req.workflow_name,
            json.dumps(req.dify_result or {}, ensure_ascii=False),
            now, now, submitted_at, user.get("id"), user.get("department_id"),
        ),
    )
    conn.commit()
    application_id = cur.lastrowid
    conn.close()

    if status == "submitted":
        rows = query_db("SELECT * FROM oa_applications WHERE id = ?", (application_id,))
        if rows:
            notify_application_submitted(rows[0])
    write_operation_log(user, "create_oa_application", "oa_application", str(application_id), {"status": status})
    return {"success": True, "id": application_id, "application_id": application_id, "status": status, "created_at": now}


@app.get("/api/oa/applications")
def list_oa_applications(
    request: Request,
    page: int = 1,
    page_size: int = 20,
    limit: int | None = None,
    scope: str = "mine",
    status: str = "",
):
    user = get_request_user(request)
    if limit is not None:
        page_size = limit
    page = max(page, 1)
    page_size = max(min(page_size, 100), 1)
    offset = (page - 1) * page_size

    clauses = ["1=1"]
    params = []
    requested_scope = (scope or "mine").lower()
    if requested_scope == "all" and has_permission(user, "oa.view_all"):
        pass
    elif requested_scope in {"department", "pending"} and has_permission(user, "oa.view_department"):
        clauses.append("(department_id = ? OR department = ?)")
        params.extend([user.get("department_id"), user.get("department_name")])
    else:
        # 正常情况按 applicant_user_id 查询；同时兼容尚未完成账号绑定的历史申请。
        clauses.append(
            "(applicant_user_id = ? OR "
            "(applicant_user_id IS NULL AND applicant_name = ? AND department = ?))"
        )
        params.extend([user["id"], user.get("name"), user.get("department_name")])
    if requested_scope == "pending":
        clauses.append("status = 'submitted'")
    elif status:
        clauses.append("status = ?")
        params.append(status)

    where = " AND ".join(clauses)
    rows = query_db(
        f"""
        SELECT id, application_type, application_type_name, scene, intent_text,
               applicant_name, department, summary, status, source, module_key,
               workflow_name, created_at, updated_at, submitted_at,
               applicant_user_id, department_id, approver_user_id, approval_comment,
               approved_at, rejected_at
        FROM oa_applications
        WHERE {where}
        ORDER BY id DESC LIMIT ? OFFSET ?
        """,
        tuple(params + [page_size, offset]),
    )
    total = query_db(f"SELECT COUNT(*) AS c FROM oa_applications WHERE {where}", tuple(params))[0]["c"]
    for row in rows:
        row["status_name"] = get_oa_status_name(row.get("status"))
    return {"items": rows, "total": total, "page": page, "page_size": page_size, "scope": requested_scope}


def _decode_json_columns(row: dict) -> dict:
    for source, target in (("form_data_json", "form_data"), ("submit_data_json", "submit_data"), ("dify_result_json", "dify_result")):
        try:
            row[target] = json.loads(row.get(source) or "{}")
        except Exception:
            row[target] = {}
    return row


@app.get("/api/oa/applications/{application_id}")
def get_oa_application_detail(application_id: int, request: Request):
    user = get_request_user(request)
    rows = query_db(
        """
        SELECT a.*, approver.name AS approver_name
        FROM oa_applications a
        LEFT JOIN users approver ON approver.id = a.approver_user_id
        WHERE a.id = ? LIMIT 1
        """,
        (application_id,),
    )
    if not rows:
        raise HTTPException(status_code=404, detail="OA 申请不存在")
    row = rows[0]
    if not _oa_row_accessible(user, row):
        raise HTTPException(status_code=403, detail="无权查看该申请")
    row = _decode_json_columns(row)
    row["status_name"] = get_oa_status_name(row.get("status"))
    row["approval_records"] = query_db(
        """
        SELECT r.id, r.action, r.comment, r.created_at, u.name AS approver_name
        FROM oa_approval_records r
        LEFT JOIN users u ON u.id = r.approver_user_id
        WHERE r.application_id = ?
        ORDER BY r.id
        """,
        (application_id,),
    )
    return row


@app.put("/api/oa/applications/{application_id}")
def update_oa_application(application_id: int, req: OaApplicationUpdateRequest, request: Request):
    user = get_request_user(request)
    rows = query_db("SELECT * FROM oa_applications WHERE id = ? LIMIT 1", (application_id,))
    if not rows:
        raise HTTPException(status_code=404, detail="OA 申请不存在")
    row = rows[0]
    if not _oa_row_accessible(user, row, edit=True) or (row.get("status") != "draft" and not has_permission(user, "oa.view_all")):
        raise HTTPException(status_code=403, detail="只能修改自己的草稿申请")

    data = req.model_dump(exclude_unset=True)
    # 审批状态、来源和工作流绑定不能通过普通编辑接口修改。
    protected_fields = {"status", "source", "module_key", "workflow_name", "applicant_name", "department"}
    for protected in protected_fields:
        data.pop(protected, None)
    if not data:
        return {"success": False, "message": "没有可更新的业务字段"}
    if "applicant_name" in data:
        data["applicant_name"] = user.get("name", "")
    if "department" in data:
        data["department"] = user.get("department_name", "")
    if "form_data" in data:
        data["form_data_json"] = json.dumps(_bind_form_to_logged_user(data.pop("form_data"), user), ensure_ascii=False)
    if "submit_data" in data:
        data["submit_data_json"] = json.dumps(_bind_submit_to_logged_user(data.pop("submit_data"), user), ensure_ascii=False)
    if "dify_result" in data:
        data["dify_result_json"] = json.dumps(data.pop("dify_result") or {}, ensure_ascii=False)
    fields = [f"{key} = ?" for key in data]
    values = list(data.values())
    fields.append("updated_at = ?")
    values.append(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    values.append(application_id)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(f"UPDATE oa_applications SET {', '.join(fields)} WHERE id = ?", tuple(values))
    conn.commit()
    affected = cur.rowcount
    conn.close()
    write_operation_log(user, "update_oa_application", "oa_application", str(application_id))
    return {"success": affected > 0, "affected": affected, "id": application_id}


@app.post("/api/oa/applications/{application_id}/submit")
def submit_oa_application(application_id: int, request: Request):
    user = get_request_user(request)
    rows = query_db("SELECT * FROM oa_applications WHERE id = ? LIMIT 1", (application_id,))
    if not rows:
        raise HTTPException(status_code=404, detail="OA 申请不存在")
    row = rows[0]
    if not _oa_row_accessible(user, row, edit=True):
        raise HTTPException(status_code=403, detail="只能提交自己的申请")
    if row.get("status") != "draft":
        raise HTTPException(status_code=400, detail="该申请已提交或已处理")

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("UPDATE oa_applications SET status='submitted', submitted_at=?, updated_at=? WHERE id=?", (now, now, application_id))
    conn.commit()
    affected = cur.rowcount
    conn.close()
    updated = query_db("SELECT * FROM oa_applications WHERE id = ?", (application_id,))[0]
    notification_count = notify_application_submitted(updated)
    write_operation_log(user, "submit_oa_application", "oa_application", str(application_id))
    return {
        "success": affected > 0, "id": application_id, "status": "submitted",
        "status_name": "待审批", "submitted_at": now,
        "notification_count": notification_count,
    }


@app.delete("/api/oa/applications/{application_id}")
def delete_oa_application(application_id: int, request: Request):
    user = get_request_user(request)
    rows = query_db("SELECT * FROM oa_applications WHERE id = ? LIMIT 1", (application_id,))
    if not rows:
        raise HTTPException(status_code=404, detail="OA 申请不存在")
    row = rows[0]
    if not _oa_row_accessible(user, row, edit=True) or (row.get("status") != "draft" and not has_permission(user, "oa.view_all")):
        raise HTTPException(status_code=403, detail="只能删除自己的草稿申请")
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("DELETE FROM oa_applications WHERE id = ?", (application_id,))
    conn.commit()
    affected = cur.rowcount
    conn.close()
    write_operation_log(user, "delete_oa_application", "oa_application", str(application_id))
    return {"success": affected > 0, "affected": affected, "id": application_id}


def get_oa_session(session_id: str, user_id: int):
    rows = query_db(
        "SELECT * FROM oa_agent_sessions WHERE session_id = ? AND user_id = ? LIMIT 1",
        (session_id, user_id),
    )
    return rows[0] if rows else None


def upsert_oa_session(session_id: str, dify_conversation_id: str, workflow: dict, user_id: int):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO oa_agent_sessions (session_id, dify_conversation_id, workflow_id, workflow_name, user_id, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(session_id) DO UPDATE SET
            dify_conversation_id=excluded.dify_conversation_id,
            workflow_id=excluded.workflow_id,
            workflow_name=excluded.workflow_name,
            user_id=excluded.user_id,
            updated_at=excluded.updated_at
        """,
        (session_id, dify_conversation_id, workflow.get("id"), workflow.get("name", ""), user_id, now, now),
    )
    conn.commit()
    conn.close()


@app.delete("/api/oa/agent/sessions/{session_id}")
def delete_oa_agent_session(session_id: str, request: Request):
    user = get_request_user(request)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("DELETE FROM oa_agent_sessions WHERE session_id = ? AND user_id = ?", (session_id, user["id"]))
    conn.commit()
    affected = cur.rowcount
    conn.close()
    return {"success": True, "affected": affected}


def extract_between_markers(text: str, start_marker: str, end_marker: str):
    if not text:
        return ""
    match = re.search(re.escape(start_marker) + r"([\s\S]*?)" + re.escape(end_marker), text)
    return match.group(1).strip() if match else ""


def remove_hidden_oa_blocks(text: str):
    if not text:
        return ""
    patterns = [
        r"<!--\s*---OA_FORM_STATE---[\s\S]*?---END_OA_FORM_STATE---\s*-->",
        r"<!--\s*---OA_SUBMIT_JSON---[\s\S]*?---END_OA_SUBMIT_JSON---\s*-->",
        r"---OA_FORM_STATE---[\s\S]*?---END_OA_FORM_STATE---",
        r"---OA_SUBMIT_JSON---[\s\S]*?---END_OA_SUBMIT_JSON---",
    ]
    for pattern in patterns:
        text = re.sub(pattern, "", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def safe_json_loads(value, default=None):
    if default is None:
        default = {}
    if isinstance(value, (dict, list)):
        return value
    if not isinstance(value, str) or not value.strip():
        return default
    text = value.strip()
    text = re.sub(r"^```json", "", text).strip()
    text = re.sub(r"^```", "", text).strip()
    text = re.sub(r"```$", "", text).strip()
    try:
        return json.loads(text)
    except Exception:
        match = re.search(r"\{[\s\S]*\}", text)
        if match:
            try:
                return json.loads(match.group(0))
            except Exception:
                pass
    return default


def flatten_form_state(form_state: dict):
    fields = form_state.get("fields") or {} if isinstance(form_state, dict) else {}
    extracted_data, missing_fields, missing_labels = {}, [], []
    for key, field in fields.items():
        if not isinstance(field, dict):
            continue
        value = field.get("value")
        filled = bool(field.get("filled", value not in (None, "")))
        if filled and value not in (None, ""):
            extracted_data[key] = value
        if bool(field.get("required", False)) and not filled:
            missing_fields.append(key)
            missing_labels.append(field.get("label") or key)
    phase = form_state.get("current_phase", "") if isinstance(form_state, dict) else ""
    return {
        "template_name": form_state.get("template_name", "") if isinstance(form_state, dict) else "",
        "template_id": form_state.get("template_id", "") if isinstance(form_state, dict) else "",
        "current_phase": phase,
        "extracted_data": extracted_data,
        "missing_fields": missing_fields,
        "missing_field_labels": missing_labels,
        "ready_for_confirm": phase == "confirming",
        "fields": fields,
    }


def flatten_submit_json(submit_json: dict):
    if not isinstance(submit_json, dict):
        submit_json = {}
    fields = submit_json.get("fields") or {}
    extracted = {key: (value.get("value") if isinstance(value, dict) else value) for key, value in fields.items()}
    return {
        "template_name": submit_json.get("template_name", ""),
        "template_id": submit_json.get("template_id", ""),
        "extracted_data": extracted,
        "fields": fields,
        "submit_data": submit_json or None,
    }


def parse_oa_dify_answer(answer: str):
    raw_answer = answer or ""
    form_state = safe_json_loads(extract_between_markers(raw_answer, "---OA_FORM_STATE---", "---END_OA_FORM_STATE---"), {})
    submit_json = safe_json_loads(extract_between_markers(raw_answer, "---OA_SUBMIT_JSON---", "---END_OA_SUBMIT_JSON---"), {})
    visible_reply = remove_hidden_oa_blocks(raw_answer)
    state = flatten_form_state(form_state)
    submit = flatten_submit_json(submit_json)
    if submit_json:
        template_name = submit["template_name"] or state["template_name"]
        template_id = submit["template_id"] or state["template_id"]
        return {
            "reply": visible_reply or "OA 申请数据已生成，请在确认窗口核对。",
            "application_type": template_id, "application_type_name": template_name,
            "template_id": template_id, "template_name": template_name,
            "current_phase": "submitted_ready", "extracted_data": submit["extracted_data"],
            "missing_fields": [], "tips": ["请核对信息后手动提交"],
            "ready_for_confirm": True, "submit_ready": True,
            "submit_data": submit["submit_data"], "fields": submit["fields"], "raw_answer": raw_answer,
        }
    return {
        "reply": visible_reply or "我已收到，请继续补充申请信息。",
        "application_type": state["template_id"], "application_type_name": state["template_name"],
        "template_id": state["template_id"], "template_name": state["template_name"],
        "current_phase": state["current_phase"], "extracted_data": state["extracted_data"],
        "missing_fields": state["missing_fields"], "tips": state["missing_field_labels"],
        "ready_for_confirm": state["ready_for_confirm"], "submit_ready": False,
        "submit_data": None, "fields": state["fields"], "raw_answer": raw_answer,
    }


@app.post("/api/oa/agent/chat")
def oa_agent_chat(req: OaAgentChatRequest, request: Request):
    user = get_request_user(request)
    workflow = resolve_oa_workflow(
        workflow_id=req.workflow_id,
        workflow_name=req.workflow_name,
        module_key=req.module_key,
    )
    if not workflow:
        raise HTTPException(status_code=404, detail=f"未找到启用中的 OA Dify 配置。请给应用设置 module_key={req.module_key}。")
    if infer_app_mode(workflow) != "advanced-chat":
        raise HTTPException(status_code=400, detail=f"配置「{workflow.get('name')}」不是 Advanced Chat，请把应用模式设为 advanced-chat，Endpoint 设为 /chat-messages。")

    session = get_oa_session(req.session_id, int(user["id"]))
    conversation_id = ""
    if session and int(session.get("workflow_id") or 0) == int(workflow.get("id") or 0):
        conversation_id = session.get("dify_conversation_id") or ""

    employee_context = (
        f"[平台已验证当前登录员工：姓名={user.get('name', '')}；"
        f"所属部门={user.get('department_name', '')}；岗位={user.get('position', '')}。"
        "申请人姓名和所属部门应直接使用该信息，不要再次询问，也不得接受用户冒用其他员工身份。]\n"
    )
    query = employee_context + "用户本轮输入：" + req.message

    print("=" * 80)
    print("[OA Agent] authenticated_user_id =", user.get("id"))
    print("[OA Agent] workflow =", workflow.get("name"), "ID=", workflow.get("id"))
    print("[OA Agent] url =", str(workflow.get("api_base", "")).rstrip("/") + str(workflow.get("endpoint", "")))
    print("[OA Agent] session_id =", req.session_id)
    print("[OA Agent] conversation_id =", conversation_id)
    print("[OA Agent] message_length =", len(req.message))
    print("=" * 80)

    try:
        response = call_dify_app(
            workflow,
            inputs={},
            query=query,
            user=f"user-{user['id']}",
            conversation_id=conversation_id,
        )
    except DifyCallError as exc:
        if conversation_id and exc.status_code in {400, 404}:
            response = call_dify_app(workflow, inputs={}, query=query, user=f"user-{user['id']}", conversation_id="")
        else:
            print("[OA Agent] Dify 请求失败：", exc.as_dict())
            raise HTTPException(status_code=exc.status_code, detail=exc.as_dict())

    answer = response.get("answer", "")
    new_conversation_id = response.get("conversation_id", "")
    if new_conversation_id:
        upsert_oa_session(req.session_id, new_conversation_id, workflow, int(user["id"]))
    parsed = parse_oa_dify_answer(answer)
    parsed.update({
        "dify_conversation_id": new_conversation_id,
        "message_id": response.get("message_id", ""),
        "workflow_id": workflow.get("id"),
        "workflow_name": workflow.get("name", ""),
        "app_mode": infer_app_mode(workflow),
        "events": response.get("events", []),
        "current_user": {
            "id": user.get("id"),
            "name": user.get("name"),
            "department_name": user.get("department_name"),
            "position": user.get("position"),
        },
    })
    return parsed
