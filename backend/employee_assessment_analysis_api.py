# -*- coding: utf-8 -*-
"""员工考核评估与培训建议 Workflow 接口。

Dify 配置要求：
- app_mode: workflow
- module_key: employee_assessment_analysis
- endpoint: /workflows/run
- 开始节点输入：input
- 结束节点输出：report

平台侧通过结构化表单拼出完整查询语句，尽量避免当前 YML 进入 Human Input 暂停节点。
"""
from __future__ import annotations

import json
import re
import sqlite3

import requests
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from .auth_system import get_request_user, require_permission
from .dify_client import DifyCallError, call_dify_app, infer_app_mode

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "messages.db"

router = APIRouter(
    prefix="/api/ai/employee-assessment-analysis",
    tags=["AI 员工考核评估与培训建议"],
)

ASSESSMENT_TYPES = {
    "员工入职考核",
    "技能考核",
    "业务知识考核",
    "学习能力考核",
    "综合考核",
    "全部",
}
MANAGER_ROLES = {"department_manager", "platform_admin", "super_admin"}
ADMIN_ROLES = {"platform_admin", "super_admin"}


class AssessmentAnalysisRequest(BaseModel):
    scope: Literal["personal", "department", "all"]
    target: str = Field(default="", max_length=80)
    assessment_type: str = Field(default="全部", max_length=30)
    extra_requirements: str = Field(default="", max_length=500)


def _get_workflow() -> dict[str, Any] | None:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        """
        SELECT *
        FROM workflow_configs
        WHERE module_key = 'employee_assessment_analysis'
          AND enabled = 1
        ORDER BY id DESC
        LIMIT 1
        """
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def _require_workflow() -> dict[str, Any]:
    workflow = _get_workflow()
    if not workflow:
        raise HTTPException(
            status_code=404,
            detail=(
                "未找到启用中的员工考核评估 Dify 配置，"
                "请在 Dify 应用管理中绑定 module_key=employee_assessment_analysis。"
            ),
        )
    if infer_app_mode(workflow) != "workflow":
        raise HTTPException(
            status_code=400,
            detail="员工考核评估应用必须配置为 Workflow，Endpoint 必须为 /workflows/run。",
        )
    return workflow


def _verify_ssl(workflow: dict[str, Any]) -> bool:
    value = workflow.get("verify_ssl", 1)
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "off"}
    return bool(value)


def _local_input_variables(workflow: dict[str, Any]) -> set[str]:
    raw = workflow.get("input_schema_json") or "{}"
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        return set()
    return {str(key).strip() for key in data.keys()} if isinstance(data, dict) else set()


def _remote_input_variables(workflow: dict[str, Any]) -> set[str]:
    """读取 Dify 应用真实开始节点变量；旧版本不支持 /parameters 时静默跳过。"""
    api_base = str(workflow.get("api_base") or "").strip().rstrip("/")
    api_key = str(workflow.get("api_key") or "").strip()
    if not api_base or not api_key:
        return set()

    session = requests.Session()
    session.trust_env = bool(int(workflow.get("use_system_proxy") or 0))
    try:
        response = session.get(
            api_base + "/parameters",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=(5, 12),
            verify=_verify_ssl(workflow),
        )
        if not 200 <= response.status_code < 300:
            return set()
        payload = response.json()
    except Exception:
        return set()
    finally:
        session.close()

    variables: set[str] = set()
    forms = payload.get("user_input_form") if isinstance(payload, dict) else None
    if isinstance(forms, list):
        for item in forms:
            if not isinstance(item, dict):
                continue
            for config in item.values():
                if isinstance(config, dict) and config.get("variable"):
                    variables.add(str(config["variable"]).strip())
    return variables


def _ensure_analysis_binding(workflow: dict[str, Any]) -> None:
    local_variables = _local_input_variables(workflow)
    if "operation" in local_variables and "input" not in local_variables:
        raise HTTPException(
            status_code=409,
            detail=(
                f"当前模块绑定记录「{workflow.get('name') or workflow.get('id')}」的输入字段是 operation，"
                "说明它仍指向‘考核出题与批阅’应用。请将 module_key=employee_assessment_analysis "
                "绑定到‘员工考核评估与培训建议’Dify 应用，并填写该应用自己的 API Key；"
                "正确开始节点变量应为 input。"
            ),
        )

    remote_variables = _remote_input_variables(workflow)
    if remote_variables and "input" not in remote_variables:
        actual = "、".join(sorted(remote_variables)) or "未识别"
        raise HTTPException(
            status_code=409,
            detail=(
                f"Dify API Key 实际对应的应用开始节点变量为：{actual}，不是考核评估所需的 input。"
                "请在 Dify 应用管理中编辑‘员工考核评估与培训建议’，更换为该应用自己的 API Key，"
                "不要使用‘考核出题与批阅’应用的 Key。"
            ),
        )


def _safe_target(value: str) -> str:
    value = re.sub(r"[\r\n\t]+", " ", str(value or "").strip())[:80]
    if any(token in value for token in ("'", '"', ";", "--", "/*", "*/")):
        raise HTTPException(status_code=400, detail="查询对象包含不允许的字符。")
    return value


def _find_local_user(target: str) -> dict[str, Any] | None:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        """
        SELECT u.id, u.employee_id, u.username, u.name, u.department_id,
               d.name AS department_name
        FROM users u
        LEFT JOIN departments d ON d.id = u.department_id
        WHERE u.is_active = 1
          AND (u.employee_id = ? OR u.username = ? OR u.name = ?)
        ORDER BY u.id
        LIMIT 1
        """,
        (target, target, target),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def _normalize_scope_and_target(
    user: dict[str, Any],
    scope: str,
    target: str,
) -> tuple[str, str]:
    role = str(user.get("role_code") or "employee")
    own_target = str(user.get("employee_id") or user.get("name") or "").strip()
    own_department = str(user.get("department_name") or "").strip()
    target = _safe_target(target)

    if role == "employee":
        if scope != "personal":
            raise HTTPException(status_code=403, detail="普通员工只能查看本人的考核分析。")
        return "personal", own_target

    if role == "department_manager":
        if scope == "all":
            raise HTTPException(status_code=403, detail="部门领导不能查看全公司考核分析。")
        if scope == "department":
            if not own_department:
                raise HTTPException(status_code=400, detail="当前账号未配置部门。")
            return "department", own_department

        # 部门领导可查看本人或本部门员工。
        lookup_target = target or own_target
        local_user = _find_local_user(lookup_target)
        if not local_user:
            raise HTTPException(status_code=400, detail="未在平台员工表中找到该员工，无法校验部门权限。")
        if int(local_user.get("department_id") or 0) != int(user.get("department_id") or 0):
            raise HTTPException(status_code=403, detail="部门领导只能查看本部门员工的考核分析。")
        return "personal", str(local_user.get("employee_id") or local_user.get("name") or lookup_target)

    if role in ADMIN_ROLES:
        if scope in {"personal", "department"} and not target:
            raise HTTPException(status_code=400, detail="请选择或填写查询对象。")
        return scope, target

    if role in MANAGER_ROLES:
        return scope, target

    raise HTTPException(status_code=403, detail="当前账号无权使用该查询范围。")


def _build_query(scope: str, target: str, assessment_type: str, extra: str) -> str:
    if scope == "personal":
        query = f"查询员工{target}的{assessment_type}考核结果，分析个人薄弱项并给出学习与复核建议。"
    elif scope == "department":
        query = f"分析{target}的{assessment_type}考核结果，生成人员分层、共性薄弱项和部门培训方案。"
    else:
        query = f"分析公司全员的{assessment_type}考核结果，生成整体能力短板和年度培训建议。"

    extra = re.sub(r"[\r\n\t]+", " ", str(extra or "").strip())[:500]
    if extra:
        query += f"补充要求：{extra}"
    return query


def _extract_report(result: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    outputs = result.get("outputs") or {}
    report = str(outputs.get("report") or "").strip()
    if report:
        return report, outputs

    raw = result.get("raw") or {}
    data = raw.get("data") if isinstance(raw, dict) else {}
    nested_outputs = data.get("outputs") if isinstance(data, dict) else {}
    if isinstance(nested_outputs, dict):
        report = str(nested_outputs.get("report") or "").strip()
        return report, nested_outputs
    return "", outputs if isinstance(outputs, dict) else {}


@router.get("/status")
def employee_assessment_analysis_status(request: Request):
    user = get_request_user(request)
    require_permission(user, "ai.use")
    workflow = _get_workflow()
    role = str(user.get("role_code") or "employee")
    allowed_scopes = ["personal"]
    if role == "department_manager":
        allowed_scopes.append("department")
    elif role in ADMIN_ROLES:
        allowed_scopes = ["personal", "department", "all"]

    return {
        "configured": bool(workflow),
        "workflow_id": workflow.get("id") if workflow else None,
        "workflow_name": workflow.get("name") if workflow else "",
        "app_mode": infer_app_mode(workflow) if workflow else "workflow",
        "expected_input": "input",
        "configured_input_fields": sorted(_local_input_variables(workflow)) if workflow else [],
        "module_key": "employee_assessment_analysis",
        "allowed_scopes": allowed_scopes,
        "message": "员工考核评估工作流已配置" if workflow else "尚未配置员工考核评估工作流",
    }


@router.post("/analyze")
def analyze_employee_assessment(req: AssessmentAnalysisRequest, request: Request):
    user = get_request_user(request)
    require_permission(user, "ai.use")
    workflow = _require_workflow()

    assessment_type = str(req.assessment_type or "全部").strip()
    if assessment_type not in ASSESSMENT_TYPES:
        raise HTTPException(status_code=400, detail="不支持的考核类型。")

    scope, target = _normalize_scope_and_target(user, req.scope, req.target)
    query = _build_query(scope, target, assessment_type, req.extra_requirements)
    _ensure_analysis_binding(workflow)

    try:
        result = call_dify_app(
            workflow,
            inputs={"input": query},
            user=f"employee-assessment-analysis-user-{user['id']}",
        )
    except DifyCallError as exc:
        message = str(exc.message or "")
        lowered = message.lower()
        if "operation is required" in lowered or "operation" in lowered and "required" in lowered:
            raise HTTPException(
                status_code=409,
                detail=(
                    "当前 employee_assessment_analysis 模块使用了‘考核出题与批阅’应用的 API Key。"
                    "该应用要求 operation，而考核评估应用只应要求 input。"
                    "请在 Dify 应用管理中编辑本模块，换成‘员工考核评估与培训建议’应用独立生成的 API Key。"
                ),
            ) from exc
        raise HTTPException(status_code=exc.status_code, detail=message) from exc

    report, outputs = _extract_report(result)
    if not report:
        if outputs.get("input"):
            raise HTTPException(
                status_code=409,
                detail=(
                    "工作流进入了人工补充节点，但平台本次已提交完整条件。"
                    "请检查 Dify 中的人员、部门或考核类型提取节点。"
                ),
            )
        raise HTTPException(
            status_code=502,
            detail="Dify 已执行完成，但没有返回 report。请检查结束节点输出变量。",
        )

    return {
        "success": True,
        "report": report,
        "scope": scope,
        "target": target,
        "assessment_type": assessment_type,
        "query": query,
        "workflow_name": workflow.get("name") or "",
    }
