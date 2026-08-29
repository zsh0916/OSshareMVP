# -*- coding: utf-8 -*-
"""员工考核一体化（出题与批阅）最小接入接口。

Dify 配置要求：
- app_mode: workflow
- module_key: employee_assessment
- endpoint: /workflows/run
- 开始节点输入：
  operation, emp_id, assessment_type, level, question, answer_file
- 结束节点输出：result

说明：
- 出题分支使用 JSON 请求；
- 批阅分支先上传单个答卷文档，再把 Dify file 对象传给 answer_file；
- 工作流内部的知识库、数据库插件和模型凭据仍在 Dify 中维护。
"""
from __future__ import annotations

import ast
import hashlib
import json
import re
import sqlite3
from pathlib import Path
from typing import Any

import requests
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field

from .auth_system import get_request_user, require_permission
from .dify_client import DifyCallError, call_dify_app, infer_app_mode
from .department_result_push import push_assessment_result

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "messages.db"

router = APIRouter(prefix="/api/ai/employee-assessment", tags=["AI 员工考核"])

ASSESSMENT_TYPES = {"员工入职考核", "技能考核"}
LEVELS = {"普通", "初级", "中级", "高级", "专家"}
ALLOWED_DOCUMENT_EXTENSIONS = {
    ".pdf", ".doc", ".docx", ".txt", ".md", ".rtf",
    ".xls", ".xlsx", ".csv", ".ppt", ".pptx",
}
MAX_FILE_SIZE = 30 * 1024 * 1024
UPLOAD_TIMEOUT = (15, 120)


class AssessmentGenerateRequest(BaseModel):
    emp_id: str = Field(min_length=4, max_length=4)
    assessment_type: str = Field(min_length=1, max_length=30)
    level: str = Field(default="普通", max_length=20)
    question: str = Field(default="", max_length=500)


def _get_workflow() -> dict[str, Any] | None:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        """
        SELECT *
        FROM workflow_configs
        WHERE module_key = 'employee_assessment'
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
                "未找到启用中的员工考核 Dify 配置，"
                "请在 Dify 应用管理中绑定 module_key=employee_assessment。"
            ),
        )
    if infer_app_mode(workflow) != "workflow":
        raise HTTPException(
            status_code=400,
            detail="员工考核应用模式必须为 Workflow，Endpoint 必须为 /workflows/run。",
        )
    return workflow


def _validate_emp_id(emp_id: str) -> str:
    value = str(emp_id or "").strip().upper()
    if not re.fullmatch(r"E\d{3}", value):
        raise HTTPException(
            status_code=400,
            detail="考核员工ID格式应为 E 加三位数字，例如 E002。",
        )
    return value


def _validate_assessment_type(value: str) -> str:
    value = str(value or "").strip()
    if value not in ASSESSMENT_TYPES:
        raise HTTPException(status_code=400, detail="考核类型只能是员工入职考核或技能考核。")
    return value


def _validate_level(assessment_type: str, value: str) -> str:
    if assessment_type == "员工入职考核":
        return "普通"
    value = str(value or "").strip()
    if value not in LEVELS - {"普通"}:
        raise HTTPException(status_code=400, detail="技能考核难度只能是初级、中级、高级或专家。")
    return value


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, indent=2)
    return str(value).strip()


def _extract_result(call_result: dict[str, Any]) -> str:
    outputs = call_result.get("outputs") or {}
    result = _stringify(outputs.get("result"))
    if result:
        return result

    raw = call_result.get("raw") or {}
    data = raw.get("data") if isinstance(raw, dict) else {}
    nested_outputs = data.get("outputs") if isinstance(data, dict) else {}
    return _stringify((nested_outputs or {}).get("result"))


def _parse_questions(result: str) -> list[str]:
    questions: list[str] = []
    for line in str(result or "").splitlines():
        text = re.sub(r"^\s*(?:第?\d+[题、.．:：)]|[-*•])\s*", "", line).strip()
        if not text:
            continue
        if text not in questions:
            questions.append(text)
        if len(questions) == 5:
            break
    return questions


def _parse_review_result(result: str) -> dict[str, Any]:
    """兼容当前 YML 的元组输出，也兼容后续改成 JSON 的情况。"""
    text = str(result or "").strip()
    text = re.sub(r"^```(?:json|python)?\s*", "", text, flags=re.I)
    text = re.sub(r"\s*```$", "", text)

    parsed: Any = None
    try:
        parsed = json.loads(text)
    except Exception:
        try:
            parsed = ast.literal_eval(text)
        except Exception:
            parsed = None

    keys = [
        "emp_id",
        "assessment_type",
        "result",
        "assessment_date",
        "wrong_questions",
        "result_analysis",
    ]

    if isinstance(parsed, dict):
        normalized = {}
        for key, value in parsed.items():
            normalized[str(key).strip()] = value
        return {key: normalized.get(key) for key in keys if key in normalized}

    if isinstance(parsed, (list, tuple)) and len(parsed) >= 6:
        return {key: parsed[index] for index, key in enumerate(keys)}

    return {}


def _verify_ssl(workflow: dict[str, Any]) -> bool:
    value = workflow.get("verify_ssl", 1)
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "off"}
    return bool(value)


def _session(workflow: dict[str, Any]) -> requests.Session:
    session = requests.Session()
    session.trust_env = bool(int(workflow.get("use_system_proxy") or 0))
    return session


def _api_base(workflow: dict[str, Any]) -> str:
    value = str(workflow.get("api_base") or "").strip().rstrip("/")
    if not value:
        raise HTTPException(status_code=500, detail="Dify 配置缺少 API Base。")
    return value


def _api_key(workflow: dict[str, Any]) -> str:
    value = str(workflow.get("api_key") or "").strip()
    if not value:
        raise HTTPException(status_code=500, detail="Dify 配置缺少 API Key。")
    return value


def _safe_json(response: requests.Response) -> Any:
    try:
        return response.json()
    except Exception:
        return {"raw_text": response.text[:4000]}


def _upload_document(
    workflow: dict[str, Any],
    *,
    filename: str,
    content_type: str,
    file_bytes: bytes,
    user_key: str,
) -> str:
    session = _session(workflow)
    try:
        response = session.post(
            _api_base(workflow) + "/files/upload",
            headers={"Authorization": f"Bearer {_api_key(workflow)}"},
            files={
                "file": (
                    filename,
                    file_bytes,
                    content_type or "application/octet-stream",
                )
            },
            data={"user": user_key},
            timeout=UPLOAD_TIMEOUT,
            verify=_verify_ssl(workflow),
        )
    except requests.exceptions.ConnectTimeout as exc:
        raise HTTPException(status_code=504, detail="连接 Dify 文件上传接口超时。") from exc
    except requests.exceptions.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"上传答卷到 Dify 失败：{exc}") from exc
    finally:
        session.close()

    if not 200 <= response.status_code < 300:
        body = _safe_json(response)
        message = body.get("message") if isinstance(body, dict) else ""
        raise HTTPException(
            status_code=502,
            detail=f"上传答卷到 Dify 失败（HTTP {response.status_code}）：{message or body}",
        )

    data = _safe_json(response)
    upload_file_id = str((data or {}).get("id") or "")
    if not upload_file_id:
        raise HTTPException(status_code=502, detail="Dify 文件上传成功，但没有返回文件ID。")
    return upload_file_id


def _call_workflow(
    workflow: dict[str, Any],
    *,
    inputs: dict[str, Any],
    user_key: str,
) -> dict[str, Any]:
    try:
        result = call_dify_app(workflow, inputs=inputs, user=user_key)
    except DifyCallError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    output = _extract_result(result)
    if not output:
        raise HTTPException(
            status_code=502,
            detail="Dify 已执行完成，但没有返回 result。请确认两个结束节点的输出变量均为 result。",
        )
    return {"call_result": result, "result": output}


@router.get("/status")
def employee_assessment_status(request: Request):
    user = get_request_user(request)
    require_permission(user, "ai.use")

    workflow = _get_workflow()
    return {
        "configured": bool(workflow),
        "workflow_name": workflow.get("name") if workflow else "",
        "app_mode": infer_app_mode(workflow) if workflow else "workflow",
        "message": "员工考核工作流已配置" if workflow else "未找到启用中的员工考核配置",
        "module_key": "employee_assessment",
    }


@router.post("/generate")
def generate_assessment(req: AssessmentGenerateRequest, request: Request):
    user = get_request_user(request)
    require_permission(user, "ai.use")
    workflow = _require_workflow()

    emp_id = _validate_emp_id(req.emp_id)
    assessment_type = _validate_assessment_type(req.assessment_type)
    level = _validate_level(assessment_type, req.level)
    question = str(req.question or "").strip()[:500]
    user_key = f"employee-assessment-user-{user['id']}"

    executed = _call_workflow(
        workflow,
        inputs={
            "operation": "出题",
            "emp_id": emp_id,
            "assessment_type": assessment_type,
            "level": level,
            "question": question,
        },
        user_key=user_key,
    )
    questions = _parse_questions(executed["result"])

    return {
        "success": True,
        "operation": "出题",
        "workflow_name": workflow.get("name") or "员工考核一体化（出题与批阅）",
        "emp_id": emp_id,
        "assessment_type": assessment_type,
        "level": level,
        "question_count": len(questions),
        "questions": questions,
        "raw_result": executed["result"],
    }


@router.post("/review")
def review_assessment(
    request: Request,
    emp_id: str = Form(...),
    assessment_type: str = Form(...),
    file: UploadFile = File(...),
):
    user = get_request_user(request)
    require_permission(user, "ai.use")
    workflow = _require_workflow()

    emp_id = _validate_emp_id(emp_id)
    assessment_type = _validate_assessment_type(assessment_type)

    filename = Path(file.filename or "answer-document").name
    extension = Path(filename).suffix.lower()
    if extension not in ALLOWED_DOCUMENT_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail="答卷仅支持 PDF、Word、TXT、Markdown、Excel、CSV、PPT 等文档格式。",
        )

    file_bytes = file.file.read(MAX_FILE_SIZE + 1)
    if len(file_bytes) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="答卷文件不能超过30MB。")
    if not file_bytes:
        raise HTTPException(status_code=400, detail="上传的答卷文件为空。")

    user_key = f"employee-assessment-user-{user['id']}"
    upload_file_id = _upload_document(
        workflow,
        filename=filename,
        content_type=file.content_type or "application/octet-stream",
        file_bytes=file_bytes,
        user_key=user_key,
    )

    executed = _call_workflow(
        workflow,
        inputs={
            "operation": "批阅",
            "emp_id": emp_id,
            "assessment_type": assessment_type,
            "level": "普通",
            "question": "",
            "answer_file": {
                "type": "document",
                "transfer_method": "local_file",
                "upload_file_id": upload_file_id,
            },
        },
        user_key=user_key,
    )

    parsed_assessment = _parse_review_result(executed["result"])
    leader_push = push_assessment_result(
        emp_id=emp_id,
        assessment_type=assessment_type,
        parsed_result=parsed_assessment,
        raw_result=executed["result"],
        file_name=filename,
        file_digest=hashlib.sha256(file_bytes).hexdigest(),
    )

    return {
        "success": True,
        "operation": "批阅",
        "workflow_name": workflow.get("name") or "员工考核一体化（出题与批阅）",
        "file_name": filename,
        "emp_id": emp_id,
        "assessment_type": assessment_type,
        "assessment": parsed_assessment,
        "raw_result": executed["result"],
        "leader_push": leader_push,
    }
