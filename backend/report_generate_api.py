# -*- coding: utf-8 -*-
"""日报与阶段报表 Dify Advanced Chat 接口。

配置要求：advanced-chat、module_key=report_generate、/chat-messages。
本模块固定使用 streaming，并保留现有部门领导结果推送。
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from .auth_system import get_request_user, require_permission
from .dify_client import DifyCallError, call_dify_app, infer_app_mode
from .department_result_push import push_report_result

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "messages.db"

router = APIRouter(prefix="/api/ai/report-generate", tags=["AI 日报与阶段报表"])


class ReportChatRequest(BaseModel):
    query: str = Field(min_length=1, max_length=3000)
    receiver_name: str = Field(default="", max_length=100)
    conversation_id: str = Field(default="", max_length=200)


def _get_workflow() -> dict[str, Any] | None:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        """
        SELECT *
        FROM workflow_configs
        WHERE module_key = 'report_generate'
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
            detail="未找到启用中的日报与阶段报表 Dify 配置，请绑定 module_key=report_generate。",
        )
    if infer_app_mode(workflow) != "advanced-chat":
        raise HTTPException(
            status_code=400,
            detail="日报与阶段报表必须配置为 Advanced Chat，Endpoint 必须为 /chat-messages。",
        )
    return workflow


def _extract_answer(result: dict[str, Any]) -> str:
    if not isinstance(result, dict):
        return ""
    direct = str(result.get("answer") or "").strip()
    if direct:
        return direct
    for key in ("outputs", "data", "raw"):
        container = result.get(key)
        if not isinstance(container, dict):
            continue
        text = str(
            container.get("answer")
            or container.get("result")
            or container.get("report")
            or container.get("text")
            or container.get("output")
            or ""
        ).strip()
        if text:
            return text
        nested = container.get("data")
        if isinstance(nested, dict):
            text = str(
                nested.get("answer")
                or nested.get("result")
                or nested.get("report")
                or nested.get("text")
                or nested.get("output")
                or ""
            ).strip()
            if text:
                return text
            outputs = nested.get("outputs")
            if isinstance(outputs, dict):
                text = str(
                    outputs.get("answer")
                    or outputs.get("result")
                    or outputs.get("report")
                    or outputs.get("text")
                    or outputs.get("output")
                    or ""
                ).strip()
                if text:
                    return text
    return ""


@router.get("/status")
def report_generate_status(request: Request):
    user = get_request_user(request)
    require_permission(user, "ai.use")
    workflow = _get_workflow()
    return {
        "configured": bool(workflow),
        "workflow_name": workflow.get("name") if workflow else "",
        "app_mode": infer_app_mode(workflow) if workflow else "advanced-chat",
        "module_key": "report_generate",
        "message": "日报与阶段报表工作流已配置" if workflow else "尚未配置日报与阶段报表工作流",
    }


@router.post("/chat")
def report_generate_chat(req: ReportChatRequest, request: Request):
    user = get_request_user(request)
    require_permission(user, "ai.use")
    workflow = _require_workflow()

    query = str(req.query or "").strip()
    receiver_name = str(user.get("name") or req.receiver_name or "当前员工").strip()[:100]
    conversation_id = str(req.conversation_id or "").strip()
    user_key = f"report-generate-user-{user['id']}"

    call_args = {
        "inputs": {"query": query, "name": receiver_name},
        "query": query,
        "user": user_key,
        "conversation_id": conversation_id,
    }

    streaming_workflow = dict(workflow)
    streaming_workflow["response_mode"] = "streaming"

    restarted = False
    try:
        result = call_dify_app(streaming_workflow, **call_args)
    except DifyCallError as exc:
        if conversation_id and exc.status_code in {400, 404}:
            restarted = True
            call_args["conversation_id"] = ""
            try:
                result = call_dify_app(streaming_workflow, **call_args)
            except DifyCallError as retry_exc:
                raise HTTPException(
                    status_code=retry_exc.status_code,
                    detail=retry_exc.message,
                ) from retry_exc
        else:
            raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    answer = _extract_answer(result)
    if not answer:
        events = result.get("events") if isinstance(result, dict) else []
        raise HTTPException(
            status_code=502,
            detail=(
                "Dify 流式执行已结束，但没有取得最终报表文本。"
                "请确认所有分支均连接到 Answer 节点并重新发布应用。"
                f" 已收到事件：{events or '无'}"
            ),
        )

    message_id = str(result.get("message_id") or "")
    task_id = str(result.get("task_id") or "")
    leader_push = push_report_result(
        source_user_id=int(user["id"]),
        query=query,
        answer=answer,
        message_id=message_id,
        task_id=task_id,
    )

    return {
        "success": True,
        "answer": answer,
        "conversation_id": str(result.get("conversation_id") or ""),
        "message_id": message_id,
        "task_id": task_id,
        "restarted": restarted,
        "workflow_name": workflow.get("name") or "",
        "response_mode": "streaming",
        "leader_push": leader_push,
    }
