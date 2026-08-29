# -*- coding: utf-8 -*-
"""AI 最终结果按员工所属部门推送给部门领导。

适用范围：
- 普通员工答卷批阅完成后的最终考核结果；
- 普通员工提交日报或生成阶段报表后的最终结果。

路由规则与 OA 提交通知保持一致：
1. 只处理 role_code=employee 的普通员工；
2. 只推送给该员工所属部门、处于启用状态的 department_manager；
3. 部门没有领导时，仅由 super_admin 兜底；
4. 不向其他部门领导或平台管理员广播；
5. 使用稳定 business_id 去重，避免同一结果重复通知。
"""
from __future__ import annotations

import hashlib
import logging
import sqlite3
from pathlib import Path
from typing import Any

from .auth_system import create_notification
from .db import connect

BASE_DIR = Path(__file__).resolve().parent.parent
LOGGER = logging.getLogger(__name__)
MAX_NOTIFICATION_CONTENT = 12000


def _conn() -> sqlite3.Connection:
    return connect()


def _clean_text(value: Any, *, limit: int = MAX_NOTIFICATION_CONTENT) -> str:
    text = str(value or "").replace("\x00", "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n\n（结果内容较长，通知中已截取前部分。）"


def _stable_business_id(*parts: Any) -> int:
    payload = "\n---\n".join(str(part or "") for part in parts).encode("utf-8", errors="replace")
    digest = hashlib.blake2b(payload, digest_size=8).digest()
    # SQLite INTEGER 是有符号 64 位，清除最高位。
    return int.from_bytes(digest, "big") & 0x7FFF_FFFF_FFFF_FFFF


def _employee_by_employee_id(employee_id: str) -> dict[str, Any] | None:
    value = str(employee_id or "").strip().upper()
    if not value:
        return None
    conn = _conn()
    try:
        row = conn.execute(
            """
            SELECT u.id, u.employee_id, u.name, u.department_id, u.role_code,
                   u.is_active, d.name AS department_name
            FROM users u
            LEFT JOIN departments d ON d.id = u.department_id
            WHERE UPPER(COALESCE(u.employee_id, '')) = ?
              AND u.is_active = 1
            ORDER BY u.id
            LIMIT 1
            """,
            (value,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def _employee_by_user_id(user_id: int) -> dict[str, Any] | None:
    conn = _conn()
    try:
        row = conn.execute(
            """
            SELECT u.id, u.employee_id, u.name, u.department_id, u.role_code,
                   u.is_active, d.name AS department_name
            FROM users u
            LEFT JOIN departments d ON d.id = u.department_id
            WHERE u.id = ? AND u.is_active = 1
            LIMIT 1
            """,
            (int(user_id),),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def _department_leaders(employee: dict[str, Any]) -> list[dict[str, Any]]:
    """严格按 OA 的部门隔离规则选择接收人。"""
    employee_id = int(employee.get("id") or 0)
    department_id = int(employee.get("department_id") or 0)
    if not employee_id or not department_id:
        return []

    conn = _conn()
    try:
        rows = conn.execute(
            """
            SELECT id, employee_id, name, department_id, role_code
            FROM users
            WHERE is_active = 1
              AND department_id = ?
              AND role_code = 'department_manager'
              AND id <> ?
            ORDER BY id
            """,
            (department_id, employee_id),
        ).fetchall()

        if not rows:
            rows = conn.execute(
                """
                SELECT id, employee_id, name, department_id, role_code
                FROM users
                WHERE is_active = 1
                  AND role_code = 'super_admin'
                  AND id <> ?
                ORDER BY id
                """,
                (employee_id,),
            ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def _skip_reason(employee: dict[str, Any] | None) -> str:
    if not employee:
        return "未找到对应的启用员工账号"
    if str(employee.get("role_code") or "") != "employee":
        return "目标账号不是普通员工，不执行部门领导推送"
    if not int(employee.get("department_id") or 0):
        return "普通员工未绑定部门"
    return ""


def _send_to_leaders(
    *,
    employee: dict[str, Any],
    title: str,
    content: str,
    notification_type: str,
    business_type: str,
    business_id: int,
) -> dict[str, Any]:
    leaders = _department_leaders(employee)
    if not leaders:
        return {
            "pushed": False,
            "count": 0,
            "reason": "本部门没有部门领导，且未找到超级管理员兜底",
            "recipient_names": [],
            "business_id": business_id,
        }

    names: list[str] = []
    notification_ids: list[int] = []
    for leader in leaders:
        notification_id = create_notification(
            int(leader["id"]),
            title,
            _clean_text(content),
            notification_type=notification_type,
            business_type=business_type,
            business_id=business_id,
            target_page="notifications",
            deduplicate=True,
        )
        names.append(str(leader.get("name") or leader.get("employee_id") or leader["id"]))
        notification_ids.append(int(notification_id))

    return {
        "pushed": True,
        "count": len(leaders),
        "reason": "",
        "recipient_names": names,
        "notification_ids": notification_ids,
        "business_id": business_id,
    }


def push_assessment_result(
    *,
    emp_id: str,
    assessment_type: str,
    parsed_result: dict[str, Any] | None,
    raw_result: str,
    file_name: str,
    file_digest: str,
) -> dict[str, Any]:
    """把普通员工的答卷最终批阅结果推送给本部门领导。"""
    try:
        employee = _employee_by_employee_id(emp_id)
        reason = _skip_reason(employee)
        if reason:
            return {"pushed": False, "count": 0, "reason": reason, "recipient_names": []}
        assert employee is not None

        result = parsed_result or {}
        grade = _clean_text(result.get("result"), limit=80) or "已完成批阅"
        assessment_date = _clean_text(result.get("assessment_date"), limit=80)
        wrong_questions = result.get("wrong_questions")
        if isinstance(wrong_questions, (list, tuple)):
            wrong_text = "；".join(_clean_text(item, limit=500) for item in wrong_questions if str(item or "").strip())
        else:
            wrong_text = _clean_text(wrong_questions, limit=2000)
        analysis = _clean_text(result.get("result_analysis"), limit=4000)

        business_id = _stable_business_id(
            "employee_assessment_result",
            employee.get("id"),
            emp_id,
            assessment_type,
            assessment_date,
            file_digest,
            raw_result,
        )
        title = f"{employee.get('name') or emp_id}的{assessment_type}批阅结果：{grade}"
        lines = [
            f"员工：{employee.get('name') or '-'}（{employee.get('employee_id') or emp_id}）",
            f"所属部门：{employee.get('department_name') or '-'}",
            f"考核类型：{assessment_type}",
            f"答卷文件：{file_name or '-'}",
            f"最终结果：{grade}",
        ]
        if assessment_date:
            lines.append(f"考核日期：{assessment_date}")
        if wrong_text:
            lines.append(f"错题/薄弱项：{wrong_text}")
        if analysis:
            lines.append(f"结果分析：{analysis}")
        if not (wrong_text or analysis) and raw_result:
            lines.append("完整批阅结果：\n" + _clean_text(raw_result, limit=8000))

        return _send_to_leaders(
            employee=employee,
            title=title,
            content="\n".join(lines),
            notification_type="employee_assessment_result",
            business_type="employee_assessment",
            business_id=business_id,
        )
    except Exception as exc:  # 推送失败不能导致 Dify 结果丢失或重复执行
        LOGGER.exception("推送员工考核结果失败：%s", exc)
        return {"pushed": False, "count": 0, "reason": f"推送失败：{exc}", "recipient_names": []}


def _report_kind(query: str) -> str:
    query = str(query or "")
    report_words = ("周报", "月报", "阶段", "汇总", "统计", "查询", "报表", "最近", "本周", "本月", "上周", "上月")
    return "阶段报表" if any(word in query for word in report_words) else "日报"


def push_report_result(
    *,
    source_user_id: int,
    query: str,
    answer: str,
    message_id: str = "",
    task_id: str = "",
) -> dict[str, Any]:
    """把普通员工的日报或阶段报表最终结果推送给本部门领导。"""
    try:
        employee = _employee_by_user_id(source_user_id)
        reason = _skip_reason(employee)
        if reason:
            return {"pushed": False, "count": 0, "reason": reason, "recipient_names": []}
        assert employee is not None

        kind = _report_kind(query)
        business_id = _stable_business_id(
            "report_generate_result",
            source_user_id,
            message_id,
            task_id,
            query,
            answer,
        )
        title = f"{employee.get('name') or employee.get('employee_id')}的{kind}结果已生成"
        content = "\n".join(
            [
                f"员工：{employee.get('name') or '-'}（{employee.get('employee_id') or '-'}）",
                f"所属部门：{employee.get('department_name') or '-'}",
                f"结果类型：{kind}",
                f"员工请求：{_clean_text(query, limit=1200)}",
                "最终结果：\n" + _clean_text(answer),
            ]
        )
        return _send_to_leaders(
            employee=employee,
            title=title,
            content=content,
            notification_type="employee_report_result",
            business_type="report_generate",
            business_id=business_id,
        )
    except Exception as exc:  # 推送失败不能让员工重复提交日报
        LOGGER.exception("推送日报/阶段报表结果失败：%s", exc)
        return {"pushed": False, "count": 0, "reason": f"推送失败：{exc}", "recipient_names": []}
