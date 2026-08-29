"""Identity, authorization, notifications, task aggregation and OA approval.

This module retains the original route contracts. Security primitives and
permission checks are server-side; frontend visibility is never treated as an
authorization boundary.
"""

from __future__ import annotations

import base64
import csv
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
import warnings
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from .db import DB_PATH, connect

BASE_DIR = Path(__file__).resolve().parent.parent
EMPLOYEE_CSV_PATH = Path(os.getenv("EMPLOYEE_CSV_PATH", str(BASE_DIR / "data" / "employee_info.csv")))
INITIAL_ACCOUNT_EXPORT_PATH = BASE_DIR / "data" / "employee_initial_accounts.csv"

ROLE_DEFINITIONS = {
    "employee": {
        "name": "普通员工",
        "level": 10,
        "permissions": [
            "workbench.view",
            "oa.create",
            "oa.view_own",
            "notification.view",
            "message.view_department",
            "profile.manage",
            "ai.use",
        ],
    },
    "department_manager": {
        "name": "部门领导",
        "level": 50,
        "permissions": [
            "workbench.view",
            "oa.create",
            "oa.view_own",
            "oa.view_department",
            "oa.approve",
            "notification.view",
            "message.view_department",
            "profile.manage",
            "ai.use",
            "department.dashboard",
        ],
    },
    "platform_admin": {
        "name": "平台管理员",
        "level": 80,
        "permissions": [
            "workbench.view",
            "oa.create",
            "oa.view_own",
            "oa.view_department",
            "oa.view_all",
            "oa.approve",
            "notification.view",
            "message.view_department",
            "profile.manage",
            "ai.use",
            "department.dashboard",
            "message.view",
            "workflow.manage",
            "rule.manage",
            "user.manage",
            "system.audit",
        ],
    },
    "super_admin": {
        "name": "超级管理员",
        "level": 100,
        "permissions": ["*"],
    },
}

PERMISSION_NAMES = {
    "workbench.view": "查看工作台",
    "oa.create": "发起 OA 申请",
    "oa.view_own": "查看本人 OA",
    "oa.view_department": "查看本部门 OA",
    "oa.view_all": "查看全部 OA",
    "oa.approve": "审批 OA",
    "notification.view": "查看通知",
    "message.view_department": "查看本部门消息中心",
    "profile.manage": "管理个人资料",
    "ai.use": "使用 AI 功能",
    "department.dashboard": "查看部门工作台",
    "message.view": "查看消息中心",
    "workflow.manage": "管理 Dify 应用",
    "rule.manage": "管理规则",
    "user.manage": "管理员工账户",
    "system.audit": "查看操作审计",
}

LEADER_KEYWORDS = (
    "总监",
    "经理",
    "主管",
    "主任",
    "组长",
    "班长",
    "负责人",
)


def _load_dotenv() -> None:
    env_path = BASE_DIR / ".env"
    if not env_path.exists():
        return
    try:
        for raw_line in env_path.read_text(encoding="utf-8-sig").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
    except Exception:
        return


_load_dotenv()

APP_ENV = os.getenv("APP_ENV", "development").strip().lower()
JWT_SECRET = os.getenv("APP_JWT_SECRET", "").strip()
JWT_TTL_SECONDS = max(3600, int(os.getenv("APP_JWT_TTL_SECONDS", "28800")))
ADMIN_USERNAME = os.getenv("APP_ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("APP_ADMIN_PASSWORD", "").strip()

if len(JWT_SECRET) < 32:
    if APP_ENV == "production":
        raise RuntimeError("APP_JWT_SECRET must be set to at least 32 characters in production")
    JWT_SECRET = secrets.token_urlsafe(48)
    warnings.warn("Using an ephemeral development JWT secret; sessions reset on restart.", stacklevel=1)
if not ADMIN_PASSWORD:
    if APP_ENV == "production":
        raise RuntimeError("APP_ADMIN_PASSWORD must be configured in production")
    ADMIN_PASSWORD = secrets.token_urlsafe(16)
    warnings.warn("Generated an ephemeral development administrator password.", stacklevel=1)


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def get_conn() -> sqlite3.Connection:
    return connect()


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def is_leader_position(position: str) -> bool:
    position = position or ""
    return any(keyword in position for keyword in LEADER_KEYWORDS)


def hash_password(password: str, salt: bytes | None = None) -> str:
    if not password:
        raise ValueError("密码不能为空")
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 210_000)
    return f"pbkdf2_sha256$210000${base64.urlsafe_b64encode(salt).decode()}${base64.urlsafe_b64encode(digest).decode()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations_text, salt_text, digest_text = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        salt = base64.urlsafe_b64decode(salt_text.encode())
        expected = base64.urlsafe_b64decode(digest_text.encode())
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iterations_text))
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode((data + padding).encode("ascii"))


def create_access_token(user: dict[str, Any]) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "sub": str(user["id"]),
        "username": user["username"],
        "role": user["role_code"],
        "iat": int(time.time()),
        "exp": int(time.time()) + JWT_TTL_SECONDS,
        "jti": secrets.token_hex(8),
    }
    header_part = _b64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    payload_part = _b64url_encode(json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    signing_input = f"{header_part}.{payload_part}".encode("ascii")
    signature = hmac.new(JWT_SECRET.encode("utf-8"), signing_input, hashlib.sha256).digest()
    return f"{header_part}.{payload_part}.{_b64url_encode(signature)}"


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        header_part, payload_part, signature_part = token.split(".", 2)
        signing_input = f"{header_part}.{payload_part}".encode("ascii")
        expected = hmac.new(JWT_SECRET.encode("utf-8"), signing_input, hashlib.sha256).digest()
        actual = _b64url_decode(signature_part)
        if not hmac.compare_digest(expected, actual):
            raise ValueError("签名错误")
        payload = json.loads(_b64url_decode(payload_part).decode("utf-8"))
        if int(payload.get("exp", 0)) < int(time.time()):
            raise ValueError("登录已过期")
        return payload
    except Exception as exc:
        raise HTTPException(status_code=401, detail=f"登录状态无效：{exc}") from exc


def role_permissions(role_code: str) -> list[str]:
    return list(ROLE_DEFINITIONS.get(role_code, ROLE_DEFINITIONS["employee"])["permissions"])


def has_permission(user: dict[str, Any], permission: str) -> bool:
    permissions = user.get("permissions") or role_permissions(user.get("role_code", "employee"))
    return "*" in permissions or permission in permissions


def require_permission(user: dict[str, Any], permission: str) -> None:
    if not has_permission(user, permission):
        raise HTTPException(status_code=403, detail=f"无权限执行该操作：{permission}")


def serialize_user(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    data = dict(row)
    data.pop("password_hash", None)
    data["permissions"] = role_permissions(data.get("role_code", "employee"))
    data["role_name"] = ROLE_DEFINITIONS.get(data.get("role_code", "employee"), {}).get("name", "普通员工")
    data["is_department_leader"] = data.get("role_code") in {"department_manager", "platform_admin", "super_admin"}
    return data


def get_user_by_id(user_id: int) -> dict[str, Any] | None:
    conn = get_conn()
    row = conn.execute(
        """
        SELECT u.*, d.name AS department_name
        FROM users u
        LEFT JOIN departments d ON d.id = u.department_id
        WHERE u.id = ?
        LIMIT 1
        """,
        (user_id,),
    ).fetchone()
    conn.close()
    return serialize_user(row) if row else None


def authenticate_header(authorization: str | None) -> dict[str, Any]:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="请先登录")
    token = authorization.split(" ", 1)[1].strip()
    payload = decode_access_token(token)
    user = get_user_by_id(int(payload["sub"]))
    if not user or not int(user.get("is_active", 0)):
        raise HTTPException(status_code=401, detail="账号不存在或已停用")
    return user


def get_request_user(request: Request) -> dict[str, Any]:
    user = getattr(request.state, "current_user", None)
    if not user:
        user = authenticate_header(request.headers.get("Authorization"))
        request.state.current_user = user
    return user


def init_auth_system() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = get_conn()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS departments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            manager_user_id INTEGER,
            created_at TEXT,
            updated_at TEXT
        );

        CREATE TABLE IF NOT EXISTS roles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            level INTEGER DEFAULT 10,
            description TEXT
        );

        CREATE TABLE IF NOT EXISTS permissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS role_permissions (
            role_code TEXT NOT NULL,
            permission_code TEXT NOT NULL,
            PRIMARY KEY (role_code, permission_code)
        );

        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id TEXT UNIQUE,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            name TEXT NOT NULL,
            department_id INTEGER,
            hire_date TEXT,
            position TEXT,
            email TEXT,
            role_code TEXT NOT NULL DEFAULT 'employee',
            is_active INTEGER NOT NULL DEFAULT 1,
            must_change_password INTEGER NOT NULL DEFAULT 1,
            last_login_at TEXT,
            created_at TEXT,
            updated_at TEXT,
            FOREIGN KEY (department_id) REFERENCES departments(id)
        );

        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            notification_type TEXT NOT NULL DEFAULT 'system',
            title TEXT NOT NULL,
            content TEXT,
            business_type TEXT,
            business_id INTEGER,
            target_page TEXT,
            is_read INTEGER NOT NULL DEFAULT 0,
            created_at TEXT,
            read_at TEXT,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS oa_approval_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            application_id INTEGER NOT NULL,
            approver_user_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            comment TEXT,
            created_at TEXT,
            FOREIGN KEY (approver_user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS operation_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            action TEXT NOT NULL,
            resource_type TEXT,
            resource_id TEXT,
            detail_json TEXT,
            ip_address TEXT,
            created_at TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_users_department ON users(department_id);
        CREATE INDEX IF NOT EXISTS idx_users_role ON users(role_code);
        CREATE INDEX IF NOT EXISTS idx_notifications_user_read ON notifications(user_id, is_read);
        CREATE INDEX IF NOT EXISTS idx_notifications_business ON notifications(business_type, business_id);
        CREATE INDEX IF NOT EXISTS idx_approval_application ON oa_approval_records(application_id);
        """
    )

    for role_code, definition in ROLE_DEFINITIONS.items():
        conn.execute(
            "INSERT OR IGNORE INTO roles(code, name, level, description) VALUES (?, ?, ?, ?)",
            (role_code, definition["name"], definition["level"], definition["name"]),
        )
        for permission in definition["permissions"]:
            permission_name = "全部权限" if permission == "*" else PERMISSION_NAMES.get(permission, permission)
            conn.execute("INSERT OR IGNORE INTO permissions(code, name) VALUES (?, ?)", (permission, permission_name))
            conn.execute(
                "INSERT OR IGNORE INTO role_permissions(role_code, permission_code) VALUES (?, ?)",
                (role_code, permission),
            )

    now = now_text()
    admin_row = conn.execute("SELECT id FROM users WHERE username = ?", (ADMIN_USERNAME,)).fetchone()
    if not admin_row:
        must_change_password = 1 if APP_ENV == "production" else 0
        conn.execute(
            """
            INSERT INTO users(
                employee_id, username, password_hash, name, department_id,
                hire_date, position, email, role_code, is_active,
                must_change_password, created_at, updated_at
            ) VALUES (?, ?, ?, ?, NULL, '', ?, '', 'super_admin', 1, ?, ?, ?)
            """,
            (
                "ADMIN", ADMIN_USERNAME, hash_password(ADMIN_PASSWORD), "系统管理员",
                "超级管理员", must_change_password, now, now,
            ),
        )
    elif APP_ENV in {"development", "demo"} and os.getenv("APP_ADMIN_PASSWORD", "").strip():
        # Demo convenience: keep the existing SQLite administrator aligned with
        # .env. Production deliberately never overwrites a stored password.
        conn.execute(
            """UPDATE users
               SET password_hash = ?, role_code = 'super_admin', is_active = 1,
                   must_change_password = 0, updated_at = ?
               WHERE id = ?""",
            (hash_password(ADMIN_PASSWORD), now, int(admin_row["id"])),
        )

    conn.commit()
    conn.close()
    import_employees_from_csv()
    migrate_oa_columns()


def import_employees_from_csv() -> dict[str, int]:
    if not EMPLOYEE_CSV_PATH.exists():
        return {"imported": 0, "existing": 0, "skipped": 0}

    conn = get_conn()
    imported = 0
    existing = 0
    skipped = 0
    exported_credentials: list[list[str]] = []

    with EMPLOYEE_CSV_PATH.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.reader(file)
        for row in reader:
            if len(row) < 6:
                skipped += 1
                continue
            employee_id, name, department_name, hire_date, position, email = [cell.strip() for cell in row[:6]]
            if not employee_id or not name:
                skipped += 1
                continue

            department = conn.execute("SELECT id FROM departments WHERE name = ?", (department_name,)).fetchone()
            if department:
                department_id = int(department["id"])
            else:
                cursor = conn.execute(
                    "INSERT INTO departments(name, created_at, updated_at) VALUES (?, ?, ?)",
                    (department_name, now_text(), now_text()),
                )
                department_id = int(cursor.lastrowid)

            role_code = "department_manager" if is_leader_position(position) else "employee"
            username = employee_id.lower()
            initial_password = f"Emp@{employee_id}!"
            now = now_text()

            user_exists = conn.execute(
                "SELECT id, role_code FROM users WHERE employee_id = ? OR username = ?",
                (employee_id, username),
            ).fetchone()
            if user_exists:
                # 旧版本只跳过已存在员工，可能导致部门、岗位及领导角色长期不更新。
                # 此处同步员工主数据，但不覆盖密码、启停状态和已人工提升的管理员角色。
                current_role = str(user_exists["role_code"] or "employee")
                synced_role = current_role
                if current_role == "employee" and role_code == "department_manager":
                    synced_role = "department_manager"
                conn.execute(
                    """
                    UPDATE users
                    SET name = ?, department_id = ?, hire_date = ?, position = ?, email = ?,
                        role_code = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        name,
                        department_id,
                        hire_date,
                        position,
                        email,
                        synced_role,
                        now,
                        int(user_exists["id"]),
                    ),
                )
                existing += 1
                continue

            conn.execute(
                """
                INSERT INTO users(
                    employee_id, username, password_hash, name, department_id,
                    hire_date, position, email, role_code, is_active,
                    must_change_password, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 1, ?, ?)
                """,
                (
                    employee_id,
                    username,
                    hash_password(initial_password),
                    name,
                    department_id,
                    hire_date,
                    position,
                    email,
                    role_code,
                    now,
                    now,
                ),
            )
            imported += 1
            exported_credentials.append([
                employee_id,
                username,
                initial_password,
                name,
                department_name,
                position,
                ROLE_DEFINITIONS[role_code]["name"],
                email,
            ])

    # 每个部门选出一个主负责人；同部门其他领导仍然保留部门领导权限。
    departments = conn.execute("SELECT id FROM departments").fetchall()
    for department in departments:
        candidates = conn.execute(
            """
            SELECT id, position
            FROM users
            WHERE department_id = ? AND role_code = 'department_manager' AND is_active = 1
            ORDER BY CASE
                WHEN position LIKE '%总监%' THEN 1
                WHEN position LIKE '%经理%' THEN 2
                WHEN position LIKE '%主任%' THEN 3
                WHEN position LIKE '%主管%' THEN 4
                WHEN position LIKE '%组长%' OR position LIKE '%班长%' THEN 5
                ELSE 9
            END, id
            LIMIT 1
            """,
            (department["id"],),
        ).fetchone()
        if candidates:
            conn.execute(
                "UPDATE departments SET manager_user_id = ?, updated_at = ? WHERE id = ?",
                (candidates["id"], now_text(), department["id"]),
            )

    conn.commit()
    conn.close()

    if exported_credentials:
        write_header = not INITIAL_ACCOUNT_EXPORT_PATH.exists()
        with INITIAL_ACCOUNT_EXPORT_PATH.open("a", encoding="utf-8-sig", newline="") as file:
            writer = csv.writer(file)
            if write_header:
                writer.writerow(["工号", "登录账号", "初始密码", "姓名", "部门", "岗位", "角色", "邮箱"])
            writer.writerows(exported_credentials)

    return {"imported": imported, "existing": existing, "skipped": skipped}


def migrate_oa_columns() -> None:
    conn = get_conn()
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    if "oa_applications" in tables:
        additions = {
            "applicant_user_id": "INTEGER",
            "department_id": "INTEGER",
            "approver_user_id": "INTEGER",
            "approval_comment": "TEXT",
            "approved_at": "TEXT",
            "rejected_at": "TEXT",
        }
        for column, ddl in additions.items():
            _ensure_column(conn, "oa_applications", column, ddl)

        # 姓名与部门完全一致时，修复缺失或错误的申请人账号绑定。
        # 旧数据如果 applicant_user_id 为空，员工“我的申请”和审批结果通知都会失效。
        conn.execute(
            """
            UPDATE oa_applications
            SET applicant_user_id = (
                SELECT u.id
                FROM users u
                LEFT JOIN departments d ON d.id = u.department_id
                WHERE u.name = oa_applications.applicant_name
                  AND d.name = oa_applications.department
                ORDER BY u.id
                LIMIT 1
            )
            WHERE applicant_name IS NOT NULL
              AND department IS NOT NULL
              AND EXISTS (
                  SELECT 1
                  FROM users u
                  LEFT JOIN departments d ON d.id = u.department_id
                  WHERE u.name = oa_applications.applicant_name
                    AND d.name = oa_applications.department
              )
              AND COALESCE(applicant_user_id, 0) <> COALESCE((
                  SELECT u.id
                  FROM users u
                  LEFT JOIN departments d ON d.id = u.department_id
                  WHERE u.name = oa_applications.applicant_name
                    AND d.name = oa_applications.department
                  ORDER BY u.id
                  LIMIT 1
              ), 0)
            """
        )
        conn.execute(
            """
            UPDATE oa_applications
            SET department_id = (
                SELECT d.id FROM departments d
                WHERE d.name = oa_applications.department
                LIMIT 1
            )
            WHERE department IS NOT NULL
              AND EXISTS (SELECT 1 FROM departments d WHERE d.name = oa_applications.department)
              AND COALESCE(department_id, 0) <> COALESCE((
                  SELECT d.id FROM departments d
                  WHERE d.name = oa_applications.department
                  LIMIT 1
              ), 0)
            """
        )
    if "oa_agent_sessions" in tables:
        _ensure_column(conn, "oa_agent_sessions", "user_id", "INTEGER")
    conn.commit()
    conn.close()


def create_notification(
    user_id: int,
    title: str,
    content: str,
    *,
    notification_type: str = "system",
    business_type: str = "",
    business_id: int | None = None,
    target_page: str = "notifications",
    deduplicate: bool = False,
) -> int:
    """
    创建站内通知。

    deduplicate=True 时，同一用户、通知类型、业务类型、业务 ID 只保留一条，
    用于避免员工重复点击提交按钮时给领导生成重复待办。
    """
    conn = get_conn()
    if deduplicate and business_type and business_id is not None:
        existing = conn.execute(
            """
            SELECT id
            FROM notifications
            WHERE user_id = ?
              AND notification_type = ?
              AND business_type = ?
              AND business_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (user_id, notification_type, business_type, business_id),
        ).fetchone()
        if existing:
            conn.close()
            return int(existing["id"])

    cursor = conn.execute(
        """
        INSERT INTO notifications(
            user_id, notification_type, title, content,
            business_type, business_id, target_page, is_read, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)
        """,
        (user_id, notification_type, title, content, business_type, business_id, target_page, now_text()),
    )
    conn.commit()
    notification_id = int(cursor.lastrowid)
    conn.close()
    return notification_id


def _application_applicant(application: dict[str, Any]) -> dict[str, Any]:
    applicant_user_id = int(application.get("applicant_user_id") or 0)
    if not applicant_user_id:
        return {}
    return get_user_by_id(applicant_user_id) or {}


def _submission_recipient_ids(application: dict[str, Any]) -> list[int]:
    """
    OA 提交通知严格按部门路由：
    1. 普通员工 -> 仅本部门全部部门领导；
    2. 本部门没有任何部门领导 -> 仅超级管理员兜底；
    3. 部门领导、平台管理员提交自己的 OA -> 超级管理员；
    4. 不再把普通员工 OA 广播给其他部门领导或所有平台管理员。
    """
    applicant = _application_applicant(application)
    applicant_id = int(application.get("applicant_user_id") or applicant.get("id") or 0)
    applicant_role = applicant.get("role_code") or "employee"
    department_id = int(application.get("department_id") or applicant.get("department_id") or 0)

    conn = get_conn()
    try:
        rows: Iterable[sqlite3.Row]
        if applicant_role == "employee" and department_id:
            rows = conn.execute(
                """
                SELECT id
                FROM users
                WHERE is_active = 1
                  AND department_id = ?
                  AND role_code = 'department_manager'
                  AND id <> ?
                ORDER BY id
                """,
                (department_id, applicant_id),
            ).fetchall()

            # 部门未配置领导时才由超级管理员兜底，绝不广播给其他部门。
            if not rows:
                rows = conn.execute(
                    """
                    SELECT id
                    FROM users
                    WHERE is_active = 1
                      AND role_code = 'super_admin'
                      AND id <> ?
                    ORDER BY id
                    """,
                    (applicant_id,),
                ).fetchall()
        else:
            # 部门领导或管理员自己的申请不能交给本人或同级跨部门人员审批。
            rows = conn.execute(
                """
                SELECT id
                FROM users
                WHERE is_active = 1
                  AND role_code = 'super_admin'
                  AND id <> ?
                ORDER BY id
                """,
                (applicant_id,),
            ).fetchall()
    finally:
        conn.close()

    return list(dict.fromkeys(int(row["id"]) for row in rows))


def notify_application_submitted(application: dict[str, Any]) -> int:
    recipient_ids = _submission_recipient_ids(application)
    count = 0
    for recipient_id in recipient_ids:
        create_notification(
            recipient_id,
            f"新的 {application.get('application_type_name') or 'OA申请'}",
            f"{application.get('department') or ''}{application.get('applicant_name') or '员工'} "
            f"提交了一条 {application.get('application_type_name') or 'OA申请'}，请及时处理。",
            notification_type="oa_submitted",
            business_type="oa_application",
            business_id=int(application["id"]),
            target_page="approval_center",
            deduplicate=True,
        )
        count += 1
    return count


def write_operation_log(
    user: dict[str, Any] | None,
    action: str,
    resource_type: str = "",
    resource_id: str = "",
    detail: dict[str, Any] | None = None,
    ip_address: str = "",
) -> None:
    conn = get_conn()
    conn.execute(
        """
        INSERT INTO operation_logs(
            user_id, username, action, resource_type, resource_id,
            detail_json, ip_address, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user.get("id") if user else None,
            user.get("username") if user else "",
            action,
            resource_type,
            resource_id,
            json.dumps(detail or {}, ensure_ascii=False),
            ip_address,
            now_text(),
        ),
    )
    conn.commit()
    conn.close()


def _resolve_application_owner(conn: sqlite3.Connection, application: dict[str, Any]) -> int | None:
    """按申请中的姓名+部门修复并返回真实申请人账号 ID。"""
    current_id = int(application.get("applicant_user_id") or 0)
    applicant_name = str(application.get("applicant_name") or "").strip()
    department = str(application.get("department") or "").strip()

    matched = None
    if applicant_name and department:
        matched = conn.execute(
            """
            SELECT u.id, u.department_id
            FROM users u
            LEFT JOIN departments d ON d.id = u.department_id
            WHERE u.name = ? AND d.name = ? AND u.is_active = 1
            ORDER BY u.id
            LIMIT 1
            """,
            (applicant_name, department),
        ).fetchone()

    if matched:
        matched_id = int(matched["id"])
        matched_department_id = int(matched["department_id"] or 0)
        if current_id != matched_id or int(application.get("department_id") or 0) != matched_department_id:
            conn.execute(
                "UPDATE oa_applications SET applicant_user_id = ?, department_id = ? WHERE id = ?",
                (matched_id, matched_department_id or None, int(application["id"])),
            )
        return matched_id

    if current_id:
        exists = conn.execute(
            "SELECT id FROM users WHERE id = ? AND is_active = 1",
            (current_id,),
        ).fetchone()
        if exists:
            return current_id
    return None


def repair_oa_links_and_notifications() -> dict[str, int]:
    """
    修复并重建 OA 路由：
    1. 按姓名+部门重新绑定申请人和 department_id；
    2. 删除全部旧的 oa_submitted 待审批通知；
    3. 仅按“本部门领导”规则重建待审批通知；
    4. 为已审批申请补齐申请人结果通知。

    删除并重建待审批通知是为了彻底清除历史版本产生的跨部门广播。
    """
    conn = get_conn()
    applications = [dict(row) for row in conn.execute("SELECT * FROM oa_applications ORDER BY id").fetchall()]
    rebound = 0
    for application in applications:
        before_user_id = int(application.get("applicant_user_id") or 0)
        before_department_id = int(application.get("department_id") or 0)
        owner_id = _resolve_application_owner(conn, application)
        if owner_id:
            owner = conn.execute(
                "SELECT department_id FROM users WHERE id = ? LIMIT 1",
                (owner_id,),
            ).fetchone()
            matched_department_id = int(owner["department_id"] or 0) if owner else 0
            if owner_id != before_user_id or matched_department_id != before_department_id:
                rebound += 1
            application["applicant_user_id"] = owner_id
            application["department_id"] = matched_department_id or None
    conn.commit()

    # 旧版本可能把同一 OA 广播给所有领导；全部清除后按新规则重建。
    deleted = conn.execute(
        "DELETE FROM notifications WHERE notification_type = 'oa_submitted'"
    ).rowcount

    processed_rows = [
        dict(row)
        for row in conn.execute(
            """
            SELECT a.*, approver.name AS approver_name
            FROM oa_applications a
            LEFT JOIN users approver ON approver.id = a.approver_user_id
            WHERE a.status IN ('approved', 'rejected')
              AND a.applicant_user_id IS NOT NULL
            ORDER BY a.id
            """
        ).fetchall()
    ]
    pending_rows = [
        dict(row)
        for row in conn.execute(
            "SELECT * FROM oa_applications WHERE status = 'submitted' ORDER BY id"
        ).fetchall()
    ]
    conn.commit()
    conn.close()

    result_notifications = 0
    for application in processed_rows:
        approved = application.get("status") == "approved"
        result_text = "已通过" if approved else "已驳回"
        notification_type = "oa_approved" if approved else "oa_rejected"
        comment = str(application.get("approval_comment") or "").strip()
        approver_name = str(application.get("approver_name") or "系统").strip()
        notification_id = create_notification(
            int(application["applicant_user_id"]),
            f"你的 {application.get('application_type_name') or 'OA申请'}{result_text}",
            f"审批人：{approver_name}。{('审批意见：' + comment) if comment else '请进入我的申请查看详情。'}",
            notification_type=notification_type,
            business_type="oa_application",
            business_id=int(application["id"]),
            target_page="my_applications",
            deduplicate=True,
        )
        if notification_id:
            result_notifications += 1

    pending_notifications = 0
    for application in pending_rows:
        pending_notifications += notify_application_submitted(application)

    return {
        "rebound_applications": rebound,
        "deleted_old_pending_notifications": max(0, int(deleted or 0)),
        "checked_result_notifications": result_notifications,
        "rebuilt_pending_notifications": pending_notifications,
    }


class LoginRequest(BaseModel):
    username: str
    password: str


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str = Field(min_length=8)


class UserUpdateRequest(BaseModel):
    role_code: str | None = None
    is_active: int | None = None
    department_id: int | None = None
    position: str | None = None
    email: str | None = None


class ResetPasswordRequest(BaseModel):
    new_password: str = Field(default="", min_length=0)


class ApprovalRequest(BaseModel):
    comment: str = ""


auth_router = APIRouter(prefix="/api", tags=["账号与权限"])


@auth_router.post("/auth/login")
def login(req: LoginRequest, request: Request):
    conn = get_conn()
    row = conn.execute(
        """
        SELECT u.*, d.name AS department_name
        FROM users u
        LEFT JOIN departments d ON d.id = u.department_id
        WHERE lower(u.username) = lower(?) OR lower(COALESCE(u.email, '')) = lower(?)
        LIMIT 1
        """,
        (req.username.strip(), req.username.strip()),
    ).fetchone()
    if not row or not int(row["is_active"] or 0) or not verify_password(req.password, row["password_hash"]):
        conn.close()
        raise HTTPException(status_code=401, detail="账号或密码错误")

    login_time = now_text()
    conn.execute("UPDATE users SET last_login_at = ?, updated_at = ? WHERE id = ?", (login_time, login_time, row["id"]))
    conn.commit()
    conn.close()

    user = serialize_user(row)
    user["last_login_at"] = login_time
    token = create_access_token(user)
    write_operation_log(user, "login", "user", str(user["id"]), ip_address=request.client.host if request.client else "")
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": JWT_TTL_SECONDS,
        "user": user,
    }


@auth_router.get("/auth/me")
def current_user(request: Request):
    return get_request_user(request)


@auth_router.post("/auth/change-password")
def change_password(req: ChangePasswordRequest, request: Request):
    user = get_request_user(request)
    conn = get_conn()
    row = conn.execute("SELECT password_hash FROM users WHERE id = ?", (user["id"],)).fetchone()
    if not row or not verify_password(req.old_password, row["password_hash"]):
        conn.close()
        raise HTTPException(status_code=400, detail="原密码不正确")
    if req.old_password == req.new_password:
        conn.close()
        raise HTTPException(status_code=400, detail="新密码不能与原密码相同")
    conn.execute(
        "UPDATE users SET password_hash = ?, must_change_password = 0, updated_at = ? WHERE id = ?",
        (hash_password(req.new_password), now_text(), user["id"]),
    )
    conn.commit()
    conn.close()
    write_operation_log(user, "change_password", "user", str(user["id"]))
    return {"success": True, "message": "密码修改成功"}


@auth_router.post("/auth/logout")
def logout(request: Request):
    user = get_request_user(request)
    write_operation_log(user, "logout", "user", str(user["id"]))
    return {"success": True}



OA_NOTIFICATION_TYPES = {"oa_submitted", "oa_approved", "oa_rejected"}


def _notification_category(notification_type: str) -> str:
    notification_type = str(notification_type or "system")
    if notification_type in OA_NOTIFICATION_TYPES:
        return "oa"
    if notification_type == "feishu_department_message":
        return "business"
    return "system"


def _task_priority_from_text(text: str, default: str = "normal") -> str:
    text = str(text or "")
    high_words = ("紧急", "立即", "宕机", "故障", "投诉", "今天必须", "P0", "驳回")
    if any(word in text for word in high_words):
        return "high"
    return default


def _collect_user_tasks(conn: sqlite3.Connection, user: dict[str, Any]) -> list[dict[str, Any]]:
    """把 OA 待审批、本人审批中申请、未读通知和部门消息统一为待办列表。"""
    tasks: list[dict[str, Any]] = []
    approval_business_ids: set[int] = set()

    if has_permission(user, "oa.approve"):
        approval_rows = conn.execute(
            """
            SELECT id, applicant_user_id, department_id, application_type_name,
                   applicant_name, department, summary, status, submitted_at, created_at
            FROM oa_applications
            WHERE status = 'submitted'
            ORDER BY COALESCE(submitted_at, created_at) DESC, id DESC
            """
        ).fetchall()
        for raw_row in approval_rows:
            row = dict(raw_row)
            if not _approval_access(user, row):
                continue
            application_id = int(row["id"])
            approval_business_ids.add(application_id)
            created_at = row.get("submitted_at") or row.get("created_at") or ""
            tasks.append(
                {
                    "id": f"approval:{application_id}",
                    "task_type": "approval",
                    "category": "approval",
                    "title": f"{row.get('applicant_name') or '员工'}提交了{row.get('application_type_name') or 'OA申请'}",
                    "description": f"{row.get('department') or '未分配部门'} · {row.get('summary') or '请进入审批中心查看申请详情'}",
                    "status": "pending",
                    "priority": _task_priority_from_text(row.get("summary") or "", "high"),
                    "created_at": created_at,
                    "target_page": "approval_center",
                    "business_id": application_id,
                    "notification_id": None,
                    "source": "OA审批",
                    "action_label": "去审批",
                }
            )

    own_rows = conn.execute(
        """
        SELECT id, application_type_name, summary, status, submitted_at, created_at
        FROM oa_applications
        WHERE applicant_user_id = ? AND status = 'submitted'
        ORDER BY COALESCE(submitted_at, created_at) DESC, id DESC
        """,
        (user["id"],),
    ).fetchall()
    for raw_row in own_rows:
        row = dict(raw_row)
        application_id = int(row["id"])
        tasks.append(
            {
                "id": f"application:{application_id}",
                "task_type": "application",
                "category": "application",
                "title": f"你的{row.get('application_type_name') or 'OA申请'}正在审批中",
                "description": row.get("summary") or "可进入“我的申请”查看审批进度",
                "status": "waiting",
                "priority": "normal",
                "created_at": row.get("submitted_at") or row.get("created_at") or "",
                "target_page": "my_applications",
                "business_id": application_id,
                "notification_id": None,
                "source": "我的申请",
                "action_label": "查看进度",
            }
        )

    notification_rows = conn.execute(
        """
        SELECT id, notification_type, title, content, business_type,
               business_id, target_page, is_read, created_at
        FROM notifications
        WHERE user_id = ? AND is_read = 0
        ORDER BY id DESC
        """,
        (user["id"],),
    ).fetchall()

    for raw_row in notification_rows:
        row = dict(raw_row)
        notification_type = str(row.get("notification_type") or "system")
        business_id = row.get("business_id")
        # OA待审批已经作为独立审批任务展示，避免重复出现两条。
        if (
            notification_type == "oa_submitted"
            and business_id is not None
            and int(business_id) in approval_business_ids
        ):
            continue

        if notification_type == "feishu_department_message":
            category = "department_message"
            source = "部门业务消息"
            action_label = "查看消息"
        else:
            category = "notification"
            source = "审批结果" if notification_type in {"oa_approved", "oa_rejected"} else "系统通知"
            action_label = "查看通知"

        title = row.get("title") or "新通知"
        content = row.get("content") or ""
        tasks.append(
            {
                "id": f"notification:{int(row['id'])}",
                "task_type": "notification",
                "category": category,
                "title": title,
                "description": content,
                "status": "unread",
                "priority": _task_priority_from_text(f"{title} {content}", "normal"),
                "created_at": row.get("created_at") or "",
                "target_page": row.get("target_page") or "notifications",
                "business_id": business_id,
                "notification_id": int(row["id"]),
                "source": source,
                "action_label": action_label,
            }
        )

    # 先按时间倒序，再稳定地按优先级排序，保证紧急事项优先。
    tasks.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    priority_order = {"high": 0, "normal": 1, "low": 2}
    tasks.sort(key=lambda item: priority_order.get(str(item.get("priority")), 1))
    return tasks


def _task_counts(tasks: list[dict[str, Any]]) -> dict[str, int]:
    counts = {
        "all": len(tasks),
        "approval": 0,
        "application": 0,
        "department_message": 0,
        "notification": 0,
        "high_priority": 0,
    }
    for task in tasks:
        category = str(task.get("category") or "notification")
        if category in counts:
            counts[category] += 1
        if task.get("priority") == "high":
            counts["high_priority"] += 1
    return counts



@auth_router.get("/workbench/summary")
def workbench_summary(request: Request):
    user = get_request_user(request)
    conn = get_conn()

    own_total = conn.execute(
        "SELECT COUNT(*) FROM oa_applications WHERE applicant_user_id = ?",
        (user["id"],),
    ).fetchone()[0]
    own_pending = conn.execute(
        "SELECT COUNT(*) FROM oa_applications WHERE applicant_user_id = ? AND status = 'submitted'",
        (user["id"],),
    ).fetchone()[0]
    own_approved = conn.execute(
        "SELECT COUNT(*) FROM oa_applications WHERE applicant_user_id = ? AND status = 'approved'",
        (user["id"],),
    ).fetchone()[0]
    own_rejected = conn.execute(
        "SELECT COUNT(*) FROM oa_applications WHERE applicant_user_id = ? AND status = 'rejected'",
        (user["id"],),
    ).fetchone()[0]
    unread = conn.execute(
        "SELECT COUNT(*) FROM notifications WHERE user_id = ? AND is_read = 0",
        (user["id"],),
    ).fetchone()[0]
    unread_department_messages = conn.execute(
        """
        SELECT COUNT(*)
        FROM notifications
        WHERE user_id = ? AND is_read = 0
          AND notification_type = 'feishu_department_message'
        """,
        (user["id"],),
    ).fetchone()[0]

    tasks = _collect_user_tasks(conn, user)
    task_counts = _task_counts(tasks)
    department_pending = task_counts["approval"]

    recent_applications = [
        dict(row)
        for row in conn.execute(
            """
            SELECT id, application_type_name, applicant_name, department, summary,
                   status, created_at, submitted_at
            FROM oa_applications
            WHERE applicant_user_id = ?
            ORDER BY id DESC
            LIMIT 6
            """,
            (user["id"],),
        ).fetchall()
    ]

    recent_notifications = [
        dict(row)
        for row in conn.execute(
            """
            SELECT id, notification_type, title, content, business_type,
                   business_id, target_page, is_read, created_at
            FROM notifications
            WHERE user_id = ?
            ORDER BY id DESC
            LIMIT 6
            """,
            (user["id"],),
        ).fetchall()
    ]

    category_rows = conn.execute(
        """
        SELECT notification_type, COUNT(*) AS total,
               SUM(CASE WHEN is_read = 0 THEN 1 ELSE 0 END) AS unread
        FROM notifications
        WHERE user_id = ?
        GROUP BY notification_type
        """,
        (user["id"],),
    ).fetchall()
    notification_summary = {"all": 0, "oa": 0, "business": 0, "system": 0, "unread": unread}
    for row in category_rows:
        category = _notification_category(row["notification_type"])
        total = int(row["total"] or 0)
        notification_summary["all"] += total
        notification_summary[category] += total

    conn.close()

    hour = datetime.now().hour
    greeting = "早上好" if hour < 11 else "中午好" if hour < 14 else "下午好" if hour < 18 else "晚上好"
    return {
        "greeting": greeting,
        "welcome_title": f"{greeting}，{user['name']}",
        "welcome_subtitle": f"{user.get('department_name') or '平台管理'} · {user.get('position') or user.get('role_name')}",
        "today_text": datetime.now().strftime("%Y年%m月%d日"),
        "stats": {
            "my_total": own_total,
            "my_pending": own_pending,
            "my_approved": own_approved,
            "my_rejected": own_rejected,
            "unread_notifications": unread,
            "unread_department_messages": unread_department_messages,
            "department_pending": department_pending,
            "total_tasks": task_counts["all"],
            "high_priority_tasks": task_counts["high_priority"],
        },
        "task_counts": task_counts,
        "task_preview": tasks[:6],
        "notification_summary": notification_summary,
        "recent_applications": recent_applications,
        "recent_notifications": recent_notifications,
    }


@auth_router.get("/tasks/summary")
def task_summary(request: Request):
    user = get_request_user(request)
    conn = get_conn()
    tasks = _collect_user_tasks(conn, user)
    conn.close()
    return {"counts": _task_counts(tasks), "items": tasks[:6]}


@auth_router.get("/tasks")
def list_tasks(
    request: Request,
    page: int = 1,
    page_size: int = 20,
    category: str = "all",
    keyword: str = "",
):
    user = get_request_user(request)
    page = max(1, page)
    page_size = max(1, min(100, page_size))
    category = str(category or "all").strip()
    keyword = str(keyword or "").strip().lower()

    conn = get_conn()
    all_tasks = _collect_user_tasks(conn, user)
    conn.close()
    counts = _task_counts(all_tasks)

    filtered = all_tasks
    if category != "all":
        filtered = [item for item in filtered if item.get("category") == category]
    if keyword:
        filtered = [
            item for item in filtered
            if keyword in f"{item.get('title', '')} {item.get('description', '')} {item.get('source', '')}".lower()
        ]

    total = len(filtered)
    start = (page - 1) * page_size
    return {
        "items": filtered[start:start + page_size],
        "total": total,
        "counts": counts,
        "page": page,
        "page_size": page_size,
        "category": category,
    }


@auth_router.get("/notifications")
def list_notifications(
    request: Request,
    page: int = 1,
    page_size: int = 20,
    unread_only: int = 0,
    category: str = "all",
    keyword: str = "",
):
    user = get_request_user(request)
    page = max(1, page)
    page_size = max(1, min(100, page_size))
    category = str(category or "all").strip()
    keyword = str(keyword or "").strip()

    where_parts = ["user_id = ?"]
    params: list[Any] = [user["id"]]
    if unread_only:
        where_parts.append("is_read = 0")
    if category == "oa":
        placeholders = ",".join("?" for _ in OA_NOTIFICATION_TYPES)
        where_parts.append(f"notification_type IN ({placeholders})")
        params.extend(sorted(OA_NOTIFICATION_TYPES))
    elif category == "business":
        where_parts.append("notification_type = ?")
        params.append("feishu_department_message")
    elif category == "system":
        placeholders = ",".join("?" for _ in OA_NOTIFICATION_TYPES)
        where_parts.append(
            f"notification_type NOT IN ({placeholders}) AND notification_type <> ?"
        )
        params.extend(sorted(OA_NOTIFICATION_TYPES))
        params.append("feishu_department_message")
    if keyword:
        where_parts.append("(title LIKE ? OR content LIKE ?)")
        like = f"%{keyword}%"
        params.extend([like, like])

    where = " AND ".join(where_parts)
    conn = get_conn()
    total = conn.execute(
        f"SELECT COUNT(*) FROM notifications WHERE {where}",
        tuple(params),
    ).fetchone()[0]
    rows = [
        dict(row)
        for row in conn.execute(
            f"""
            SELECT id, notification_type, title, content, business_type,
                   business_id, target_page, is_read, created_at, read_at
            FROM notifications
            WHERE {where}
            ORDER BY is_read ASC, id DESC
            LIMIT ? OFFSET ?
            """,
            tuple(params + [page_size, (page - 1) * page_size]),
        ).fetchall()
    ]

    all_rows = conn.execute(
        "SELECT notification_type, is_read FROM notifications WHERE user_id = ?",
        (user["id"],),
    ).fetchall()
    category_counts = {"all": 0, "oa": 0, "business": 0, "system": 0, "unread": 0}
    for row in all_rows:
        category_counts["all"] += 1
        category_counts[_notification_category(row["notification_type"])] += 1
        if not int(row["is_read"] or 0):
            category_counts["unread"] += 1
    conn.close()

    return {
        "items": rows,
        "total": total,
        "unread_count": category_counts["unread"],
        "category_counts": category_counts,
        "page": page,
        "page_size": page_size,
        "category": category,
    }


@auth_router.post("/notifications/{notification_id}/read")
def mark_notification_read(notification_id: int, request: Request):
    user = get_request_user(request)
    conn = get_conn()
    cursor = conn.execute(
        "UPDATE notifications SET is_read = 1, read_at = ? WHERE id = ? AND user_id = ?",
        (now_text(), notification_id, user["id"]),
    )
    conn.commit()
    conn.close()
    return {"success": cursor.rowcount > 0}


@auth_router.post("/notifications/read-all")
def mark_all_notifications_read(request: Request):
    user = get_request_user(request)
    conn = get_conn()
    cursor = conn.execute(
        "UPDATE notifications SET is_read = 1, read_at = ? WHERE user_id = ? AND is_read = 0",
        (now_text(), user["id"]),
    )
    conn.commit()
    conn.close()
    return {"success": True, "affected": cursor.rowcount}


@auth_router.get("/departments")
def list_departments(request: Request):
    get_request_user(request)
    conn = get_conn()
    rows = [dict(row) for row in conn.execute(
        """
        SELECT d.id, d.name, d.manager_user_id,
               u.name AS manager_name,
               COUNT(member.id) AS employee_count
        FROM departments d
        LEFT JOIN users u ON u.id = d.manager_user_id
        LEFT JOIN users member ON member.department_id = d.id AND member.is_active = 1
        GROUP BY d.id, d.name, d.manager_user_id, u.name
        ORDER BY d.name
        """
    ).fetchall()]
    conn.close()
    return rows


@auth_router.get("/roles")
def list_roles(request: Request):
    user = get_request_user(request)
    require_permission(user, "user.manage")
    return [
        {
            "code": code,
            "name": definition["name"],
            "level": definition["level"],
            "permissions": definition["permissions"],
        }
        for code, definition in ROLE_DEFINITIONS.items()
    ]


@auth_router.get("/users")
def list_users(
    request: Request,
    page: int = 1,
    page_size: int = 30,
    keyword: str = "",
    department_id: int | None = None,
    role_code: str = "",
):
    user = get_request_user(request)
    require_permission(user, "user.manage")
    page = max(page, 1)
    page_size = max(1, min(100, page_size))
    clauses = ["1=1"]
    params: list[Any] = []
    if keyword.strip():
        clauses.append("(u.name LIKE ? OR u.employee_id LIKE ? OR u.username LIKE ? OR u.email LIKE ? OR u.position LIKE ?)")
        like = f"%{keyword.strip()}%"
        params.extend([like, like, like, like, like])
    if department_id:
        clauses.append("u.department_id = ?")
        params.append(department_id)
    if role_code:
        clauses.append("u.role_code = ?")
        params.append(role_code)
    where = " AND ".join(clauses)
    conn = get_conn()
    total = conn.execute(f"SELECT COUNT(*) FROM users u WHERE {where}", tuple(params)).fetchone()[0]
    rows = conn.execute(
        f"""
        SELECT u.*, d.name AS department_name
        FROM users u
        LEFT JOIN departments d ON d.id = u.department_id
        WHERE {where}
        ORDER BY CASE WHEN u.role_code = 'super_admin' THEN 0 ELSE 1 END, u.employee_id
        LIMIT ? OFFSET ?
        """,
        tuple(params + [page_size, (page - 1) * page_size]),
    ).fetchall()
    conn.close()
    return {"items": [serialize_user(row) for row in rows], "total": total, "page": page, "page_size": page_size}


@auth_router.put("/users/{user_id}")
def update_user(user_id: int, req: UserUpdateRequest, request: Request):
    current = get_request_user(request)
    require_permission(current, "user.manage")
    data = req.model_dump(exclude_unset=True)
    if not data:
        return {"success": False, "message": "没有需要更新的字段"}
    if "role_code" in data and data["role_code"] not in ROLE_DEFINITIONS:
        raise HTTPException(status_code=400, detail="角色不存在")
    fields = [f"{key} = ?" for key in data]
    values = list(data.values())
    fields.append("updated_at = ?")
    values.append(now_text())
    values.append(user_id)
    conn = get_conn()
    cursor = conn.execute(f"UPDATE users SET {', '.join(fields)} WHERE id = ?", tuple(values))
    conn.commit()
    conn.close()
    write_operation_log(current, "update_user", "user", str(user_id), data)
    return {"success": cursor.rowcount > 0}


@auth_router.post("/users/{user_id}/reset-password")
def reset_user_password(user_id: int, req: ResetPasswordRequest, request: Request):
    current = get_request_user(request)
    require_permission(current, "user.manage")
    temporary_password = req.new_password.strip() or f"Reset@{secrets.token_hex(3)}!"
    if len(temporary_password) < 8:
        raise HTTPException(status_code=400, detail="临时密码至少 8 位")
    conn = get_conn()
    cursor = conn.execute(
        "UPDATE users SET password_hash = ?, must_change_password = 1, updated_at = ? WHERE id = ?",
        (hash_password(temporary_password), now_text(), user_id),
    )
    conn.commit()
    conn.close()
    if not cursor.rowcount:
        raise HTTPException(status_code=404, detail="员工不存在")
    write_operation_log(current, "reset_password", "user", str(user_id))
    return {"success": True, "temporary_password": temporary_password}


def _approval_access(user: dict[str, Any], application: sqlite3.Row | dict[str, Any]) -> bool:
    """审批权限强制按部门隔离，前端隐藏之外，后端接口也必须再次校验。"""
    application_data = dict(application)
    applicant_user_id = int(application_data.get("applicant_user_id") or 0)
    current_user_id = int(user.get("id") or 0)

    # 任何角色都禁止审批自己的申请。
    if applicant_user_id and applicant_user_id == current_user_id:
        return False

    if not has_permission(user, "oa.approve"):
        return False

    applicant = get_user_by_id(applicant_user_id) if applicant_user_id else None
    applicant_role = (applicant or {}).get("role_code") or "employee"
    user_role = user.get("role_code") or "employee"

    application_department_id = int(
        application_data.get("department_id")
        or (applicant or {}).get("department_id")
        or 0
    )
    user_department_id = int(user.get("department_id") or 0)
    same_department = (
        application_department_id > 0
        and user_department_id > 0
        and application_department_id == user_department_id
    )

    # 超级管理员仅作为无部门领导或领导本人申请时的兜底审批者。
    if user_role == "super_admin":
        return applicant_role != "super_admin"

    # 部门领导和平台管理员都只能审批自己部门的普通员工申请。
    # 即使某技术部领导被额外授予 platform_admin，也不能审批市场部 OA。
    if user_role in {"department_manager", "platform_admin"}:
        return same_department and applicant_role == "employee"

    return False


def _approval_rows_for_user(user: dict[str, Any], statuses: tuple[str, ...]) -> list[dict[str, Any]]:
    placeholders = ",".join("?" for _ in statuses)
    conn = get_conn()
    rows = [
        dict(row)
        for row in conn.execute(
            f"""
            SELECT a.id, a.application_type, a.application_type_name, a.applicant_name,
                   a.department, a.summary, a.status, a.created_at, a.submitted_at,
                   a.applicant_user_id, a.department_id, a.approver_user_id,
                   a.approval_comment, a.approved_at, a.rejected_at,
                   applicant.role_code AS applicant_role_code,
                   approver.name AS approver_name
            FROM oa_applications a
            LEFT JOIN users applicant ON applicant.id = a.applicant_user_id
            LEFT JOIN users approver ON approver.id = a.approver_user_id
            WHERE a.status IN ({placeholders})
            ORDER BY COALESCE(a.submitted_at, a.created_at) DESC, a.id DESC
            """,
            statuses,
        ).fetchall()
    ]
    conn.close()
    return rows


@auth_router.get("/oa/approvals/pending")
def pending_approvals(request: Request, page: int = 1, page_size: int = 30):
    user = get_request_user(request)
    require_permission(user, "oa.approve")
    page = max(1, page)
    page_size = max(1, min(100, page_size))

    accessible_rows = [
        row for row in _approval_rows_for_user(user, ("submitted",))
        if _approval_access(user, row)
    ]
    total = len(accessible_rows)
    start = (page - 1) * page_size
    return {
        "items": accessible_rows[start:start + page_size],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@auth_router.get("/oa/approvals/history")
def approval_history(request: Request, page: int = 1, page_size: int = 30):
    user = get_request_user(request)
    require_permission(user, "oa.approve")
    page = max(1, page)
    page_size = max(1, min(100, page_size))

    rows = [
        row for row in _approval_rows_for_user(user, ("approved", "rejected"))
        if int(row.get("approver_user_id") or 0) == int(user.get("id") or -1)
    ]
    total = len(rows)
    start = (page - 1) * page_size
    return {
        "items": rows[start:start + page_size],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def _handle_approval(application_id: int, action: str, comment: str, request: Request) -> dict[str, Any]:
    user = get_request_user(request)
    require_permission(user, "oa.approve")
    conn = get_conn()
    application_row = conn.execute("SELECT * FROM oa_applications WHERE id = ?", (application_id,)).fetchone()
    if not application_row:
        conn.close()
        raise HTTPException(status_code=404, detail="OA 申请不存在")
    application = dict(application_row)
    resolved_owner_id = _resolve_application_owner(conn, application)
    if resolved_owner_id:
        application["applicant_user_id"] = resolved_owner_id
    if not _approval_access(user, application):
        conn.close()
        raise HTTPException(status_code=403, detail="无权审批该申请：仅允许本部门领导审批本部门普通员工的 OA")
    if application.get("status") != "submitted":
        conn.close()
        raise HTTPException(status_code=400, detail="该申请当前不是待审批状态")

    new_status = "approved" if action == "approve" else "rejected"
    timestamp_column = "approved_at" if action == "approve" else "rejected_at"
    now = now_text()
    conn.execute(
        f"""
        UPDATE oa_applications
        SET status = ?, approver_user_id = ?, approval_comment = ?,
            {timestamp_column} = ?, updated_at = ?
        WHERE id = ?
        """,
        (new_status, user["id"], comment, now, now, application_id),
    )
    conn.execute(
        "INSERT INTO oa_approval_records(application_id, approver_user_id, action, comment, created_at) VALUES (?, ?, ?, ?, ?)",
        (application_id, user["id"], action, comment, now),
    )
    # 该申请已处理，所有领导端待审批通知同步标记为已读。
    conn.execute(
        """
        UPDATE notifications
        SET is_read = 1, read_at = COALESCE(read_at, ?)
        WHERE notification_type = 'oa_submitted'
          AND business_type = 'oa_application'
          AND business_id = ?
        """,
        (now, application_id),
    )
    conn.commit()
    conn.close()

    applicant_user_id = application.get("applicant_user_id")
    if applicant_user_id:
        result_text = "已通过" if action == "approve" else "已驳回"
        create_notification(
            int(applicant_user_id),
            f"你的 {application.get('application_type_name') or 'OA申请'}{result_text}",
            f"审批人：{user['name']}。{('审批意见：' + comment) if comment else '请进入我的申请查看详情。'}",
            notification_type=f"oa_{new_status}",
            business_type="oa_application",
            business_id=application_id,
            target_page="my_applications",
            deduplicate=True,
        )
    write_operation_log(user, action, "oa_application", str(application_id), {"comment": comment})
    return {"success": True, "id": application_id, "status": new_status, "processed_at": now}


@auth_router.post("/oa/applications/{application_id}/approve")
def approve_application(application_id: int, req: ApprovalRequest, request: Request):
    return _handle_approval(application_id, "approve", req.comment, request)


@auth_router.post("/oa/applications/{application_id}/reject")
def reject_application(application_id: int, req: ApprovalRequest, request: Request):
    if not req.comment.strip():
        raise HTTPException(status_code=400, detail="驳回时必须填写原因")
    return _handle_approval(application_id, "reject", req.comment, request)


init_auth_system()
repair_oa_links_and_notifications()
