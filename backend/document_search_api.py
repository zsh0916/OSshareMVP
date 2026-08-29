# -*- coding: utf-8 -*-
"""文档检索业务接口。

接入方式：
1. Dify 应用类型必须为 Workflow；
2. workflow_configs.module_key 必须为 document_search；
3. Dify 开始节点输入变量必须为 input；
4. Dify 结束节点输出变量必须为 result。
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from .auth_system import get_request_user, require_permission
from .dify_client import DifyCallError, call_dify_app, infer_app_mode

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "messages.db"

router = APIRouter(prefix="/api/ai/document-search", tags=["AI 文档检索"])


class DocumentSearchRequest(BaseModel):
    question: str = Field(min_length=2, max_length=2000)


def _get_document_search_workflow() -> dict[str, Any] | None:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        """
        SELECT *
        FROM workflow_configs
        WHERE module_key = 'document_search'
          AND enabled = 1
        ORDER BY id DESC
        LIMIT 1
        """
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def _stringify_answer(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, indent=2)
    return str(value).strip()


@router.get("/status")
def document_search_status(request: Request):
    user = get_request_user(request)
    require_permission(user, "ai.use")

    workflow = _get_document_search_workflow()
    return {
        "configured": bool(workflow),
        "workflow_name": workflow.get("name") if workflow else "",
        "app_mode": infer_app_mode(workflow) if workflow else "workflow",
        "message": "文档检索已配置" if workflow else "未找到启用中的文档检索配置",
    }


@router.post("")
def search_documents(req: DocumentSearchRequest, request: Request):
    user = get_request_user(request)
    require_permission(user, "ai.use")

    workflow = _get_document_search_workflow()
    if not workflow:
        raise HTTPException(
            status_code=404,
            detail="未找到启用中的文档检索 Dify 配置，请在 Dify 应用管理中绑定 module_key=document_search。",
        )

    if infer_app_mode(workflow) != "workflow":
        raise HTTPException(
            status_code=400,
            detail="文档检索应用模式必须设置为 Workflow，Endpoint 必须为 /workflows/run。",
        )

    question = req.question.strip()
    try:
        result = call_dify_app(
            workflow,
            inputs={"input": question},
            user=f"document-search-user-{user['id']}",
        )
    except DifyCallError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    outputs = result.get("outputs") or {}
    answer = _stringify_answer(outputs.get("result"))

    # 兼容部分 Dify 版本的嵌套返回结构。
    if not answer:
        raw = result.get("raw") or {}
        data = raw.get("data") if isinstance(raw, dict) else {}
        nested_outputs = data.get("outputs") if isinstance(data, dict) else {}
        answer = _stringify_answer((nested_outputs or {}).get("result"))

    if not answer:
        raise HTTPException(
            status_code=502,
            detail="Dify 已执行完成，但没有返回 result。请确认结束节点输出变量名为 result。",
        )

    return {
        "success": True,
        "question": question,
        "answer": answer,
        "workflow_name": workflow.get("name") or "文档检索",
    }
