# -*- coding: utf-8 -*-
"""智能会议纪要最小接入接口。

Dify 配置要求：
- app_mode: workflow
- module_key: meeting_minutes
- endpoint: /workflows/run
- 输入变量: audio（文件）、name（文本，可选）
- 输出变量:
  transcript
  cleaned_transcript
  meeting_minutes
  structured_info
  generated_at
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

import requests
from fastapi import APIRouter, File, HTTPException, Request, UploadFile

from .auth_system import get_request_user, require_permission
from .dify_client import infer_app_mode

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "messages.db"

router = APIRouter(prefix="/api/ai/meeting-minutes", tags=["AI 会议纪要"])

ALLOWED_AUDIO_EXTENSIONS = {
    ".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".wma", ".amr"
}
ALLOWED_VIDEO_EXTENSIONS = {".mp4", ".mov"}
MAX_FILE_SIZE = 100 * 1024 * 1024
UPLOAD_READ_TIMEOUT_SECONDS = 60
DEFAULT_WORKFLOW_TIMEOUT_SECONDS = 300
MAX_WORKFLOW_TIMEOUT_SECONDS = 900


def _get_workflow() -> dict[str, Any] | None:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        """
        SELECT *
        FROM workflow_configs
        WHERE module_key = 'meeting_minutes'
          AND enabled = 1
        ORDER BY id DESC
        LIMIT 1
        """
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def _verify_ssl(workflow: dict[str, Any]) -> bool:
    value = workflow.get("verify_ssl", 1)
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "off"}
    return bool(value)


def _upload_timeout() -> tuple[int, int]:
    return 15, UPLOAD_READ_TIMEOUT_SECONDS


def _workflow_timeout_seconds(workflow: dict[str, Any]) -> int:
    """读取数据库中的工作流超时，限制在 60～900 秒。"""
    try:
        configured = int(
            workflow.get("timeout_seconds") or DEFAULT_WORKFLOW_TIMEOUT_SECONDS
        )
    except (TypeError, ValueError):
        configured = DEFAULT_WORKFLOW_TIMEOUT_SECONDS

    return max(60, min(configured, MAX_WORKFLOW_TIMEOUT_SECONDS))


def _workflow_timeout(workflow: dict[str, Any]) -> tuple[int, int]:
    return 15, _workflow_timeout_seconds(workflow)


def _session(workflow: dict[str, Any]) -> requests.Session:
    session = requests.Session()
    session.trust_env = bool(int(workflow.get("use_system_proxy") or 0))
    return session


def _api_base(workflow: dict[str, Any]) -> str:
    value = str(workflow.get("api_base") or "").strip().rstrip("/")
    if not value:
        raise HTTPException(status_code=500, detail="Dify 配置缺少 API Base")
    return value


def _api_key(workflow: dict[str, Any]) -> str:
    value = str(workflow.get("api_key") or "").strip()
    if not value:
        raise HTTPException(status_code=500, detail="Dify 配置缺少 API Key")
    return value


def _workflow_url(workflow: dict[str, Any]) -> str:
    endpoint = str(workflow.get("endpoint") or "/workflows/run").strip()
    if not endpoint.startswith("/"):
        endpoint = "/" + endpoint
    return _api_base(workflow) + endpoint


def _safe_json(response: requests.Response) -> Any:
    try:
        return response.json()
    except Exception:
        return {"raw_text": response.text[:4000]}


def _raise_http_error(response: requests.Response, action: str) -> None:
    if 200 <= response.status_code < 300:
        return
    body = _safe_json(response)
    message = body.get("message") if isinstance(body, dict) else ""
    raise HTTPException(
        status_code=502,
        detail=f"{action}失败（Dify HTTP {response.status_code}）：{message or body}",
    )


def _file_type(extension: str) -> str:
    if extension in ALLOWED_VIDEO_EXTENSIONS:
        return "video"
    return "audio"


def _parse_sse(
    response: requests.Response,
    hard_timeout_seconds: int = DEFAULT_WORKFLOW_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    outputs: dict[str, Any] = {}
    workflow_run_id = ""
    events: list[str] = []
    started_at = time.monotonic()
    last_node = ""

    for raw_line in response.iter_lines(decode_unicode=False):
        elapsed = time.monotonic() - started_at
        if elapsed > hard_timeout_seconds:
            raise HTTPException(
                status_code=504,
                detail=(
                    f"Dify 工作流执行超过 {hard_timeout_seconds} 秒。"
                    f"最后停留节点：{last_node or '未识别'}。"
                    "请在 Dify 运行日志中检查该节点。"
                ),
            )

        if not raw_line:
            continue

        line = (
            raw_line.decode("utf-8", errors="replace").strip()
            if isinstance(raw_line, bytes)
            else str(raw_line).strip()
        )
        if line.startswith("data:"):
            line = line[5:].strip()
        if not line or line == "[DONE]":
            continue

        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue

        event_name = str(event.get("event") or "")
        data = event.get("data") or {}

        if event_name:
            events.append(event_name)

        workflow_run_id = str(
            event.get("workflow_run_id")
            or data.get("workflow_run_id")
            or data.get("id")
            or workflow_run_id
        )

        node_title = str(
            data.get("title")
            or data.get("node_title")
            or data.get("node_name")
            or ""
        ).strip()

        if event_name == "node_started":
            last_node = node_title or str(data.get("node_id") or "未知节点")
            print(f"[MeetingMinutes] Dify 节点开始：{last_node}", flush=True)

        elif event_name == "node_finished":
            finished_node = node_title or str(data.get("node_id") or last_node or "未知节点")
            status = str(data.get("status") or "succeeded")
            print(
                f"[MeetingMinutes] Dify 节点结束：{finished_node}，状态={status}",
                flush=True,
            )
            if status == "failed":
                raise HTTPException(
                    status_code=502,
                    detail=(
                        f"Dify 节点执行失败：{finished_node}；"
                        f"{data.get('error') or '未知错误'}"
                    ),
                )

        elif event_name == "workflow_finished":
            if data.get("status") == "failed":
                raise HTTPException(
                    status_code=502,
                    detail=f"Dify 工作流执行失败：{data.get('error') or '未知错误'}",
                )
            outputs = data.get("outputs") or {}
            print("[MeetingMinutes] Dify 工作流执行完成", flush=True)

        elif event_name == "human_input_required":
            raise HTTPException(
                status_code=409,
                detail=(
                    "当前 Dify 工作流仍包含人工确认节点，API 已暂停。"
                    "请导入“智能会议纪要生成_平台接入版.yml”并重新发布。"
                ),
            )

        elif event_name in {"error", "workflow_error"}:
            raise HTTPException(
                status_code=502,
                detail=f"Dify 工作流执行失败：{event.get('message') or event}",
            )

    return {
        "outputs": outputs,
        "workflow_run_id": workflow_run_id,
        "events": events,
        "last_node": last_node,
    }


def _normalize_structured_info(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {"raw": parsed}
        except Exception:
            return {"raw": value}
    return {}


@router.get("/status")
def meeting_minutes_status(request: Request):
    user = get_request_user(request)
    require_permission(user, "ai.use")

    workflow = _get_workflow()
    return {
        "configured": bool(workflow),
        "workflow_name": workflow.get("name") if workflow else "",
        "app_mode": infer_app_mode(workflow) if workflow else "workflow",
        "message": "会议纪要工作流已配置" if workflow else "未找到启用中的会议纪要配置",
    }


@router.post("/generate")
def generate_meeting_minutes(
    request: Request,
    file: UploadFile = File(...),
):
    user = get_request_user(request)
    require_permission(user, "ai.use")

    workflow = _get_workflow()
    if not workflow:
        raise HTTPException(
            status_code=404,
            detail=(
                "未找到启用中的会议纪要 Dify 配置，"
                "请绑定 module_key=meeting_minutes。"
            ),
        )

    if infer_app_mode(workflow) != "workflow":
        raise HTTPException(
            status_code=400,
            detail="会议纪要应用模式必须为 Workflow，Endpoint 必须为 /workflows/run。",
        )

    filename = Path(file.filename or "meeting-audio").name
    extension = Path(filename).suffix.lower()
    if extension not in ALLOWED_AUDIO_EXTENSIONS | ALLOWED_VIDEO_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail="仅支持 mp3、wav、m4a、aac、flac、ogg、wma、amr、mp4、mov。",
        )

    # UploadFile 在部分 FastAPI 版本中没有可靠的 size 属性，因此读取后自行校验。
    file_bytes = file.file.read(MAX_FILE_SIZE + 1)
    if len(file_bytes) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="文件不能超过 100MB。")
    if not file_bytes:
        raise HTTPException(status_code=400, detail="上传文件为空。")

    user_key = f"meeting-minutes-user-{user['id']}"
    auth_headers = {"Authorization": f"Bearer {_api_key(workflow)}"}

    workflow_timeout_seconds = _workflow_timeout_seconds(workflow)
    session = _session(workflow)
    print(
        f"[MeetingMinutes] 1/4 收到文件：{filename}，大小={len(file_bytes)} 字节",
        flush=True,
    )
    try:
        print("[MeetingMinutes] 2/4 正在上传文件到 Dify...", flush=True)
        upload_response = session.post(
            _api_base(workflow) + "/files/upload",
            headers=auth_headers,
            files={
                "file": (
                    filename,
                    file_bytes,
                    file.content_type or "application/octet-stream",
                )
            },
            data={"user": user_key},
            timeout=_upload_timeout(),
            verify=_verify_ssl(workflow),
        )
        _raise_http_error(upload_response, "上传会议文件")
        upload_data = _safe_json(upload_response)
        upload_file_id = str((upload_data or {}).get("id") or "")
        if not upload_file_id:
            raise HTTPException(status_code=502, detail="Dify 上传成功但没有返回文件 ID。")
        print(
            f"[MeetingMinutes] 文件上传成功，upload_file_id={upload_file_id}",
            flush=True,
        )

        file_object = {
            "type": _file_type(extension),
            "transfer_method": "local_file",
            "upload_file_id": upload_file_id,
        }
        payload = {
            "inputs": {
                "audio": file_object,
                "name": str(user.get("name") or ""),
            },
            "response_mode": "blocking",
            "user": user_key,
        }

        print("[MeetingMinutes] 3/4 正在启动 Dify 工作流...", flush=True)
        run_response = session.post(
            _workflow_url(workflow),
            headers={
                **auth_headers,
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            },
            json=payload,
            timeout=_workflow_timeout(workflow),
            verify=_verify_ssl(workflow),
            stream=False,
        )
        _raise_http_error(run_response, "运行会议纪要工作流")

        content_type = str(run_response.headers.get("Content-Type") or "").lower()
        if "application/json" in content_type or run_response.text.lstrip().startswith("{"):
            raw = _safe_json(run_response)
            data = raw.get("data") if isinstance(raw, dict) else {}

            status = str((data or {}).get("status") or "").lower()
            if status == "failed":
                raise HTTPException(
                    status_code=502,
                    detail=f"Dify 工作流执行失败：{(data or {}).get('error') or raw}",
                )

            parsed = {
                "outputs": (data or {}).get("outputs") or {},
                "workflow_run_id": (
                    (raw or {}).get("workflow_run_id")
                    or (data or {}).get("id")
                    or ""
                ),
                "events": [],
            }
            print(
                f"[MeetingMinutes] Dify blocking 响应完成，status={status or 'unknown'}",
                flush=True,
            )
        else:
            # 兼容某些自托管版本仍返回 SSE 的情况。
            parsed = _parse_sse(
                run_response,
                hard_timeout_seconds=workflow_timeout_seconds,
            )

    except HTTPException:
        raise
    except requests.exceptions.ReadTimeout as exc:
        raise HTTPException(
            status_code=504,
            detail=(
                f"Dify 已连接，但会议纪要工作流在 {workflow_timeout_seconds} 秒内没有完成。"
                "请到 Dify 运行日志查看是否停在“语音转文字（ASR）”节点。"
            ),
        ) from exc
    except requests.exceptions.ConnectionError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"无法连接 Dify：{exc}",
        ) from exc
    except requests.exceptions.RequestException as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Dify 请求失败：{exc}",
        ) from exc
    finally:
        session.close()

    print("[MeetingMinutes] 4/4 正在整理并返回会议纪要...", flush=True)
    outputs = parsed.get("outputs") or {}
    meeting_minutes = str(outputs.get("meeting_minutes") or "").strip()
    if not meeting_minutes:
        raise HTTPException(
            status_code=502,
            detail=(
                "Dify 已执行完成，但没有返回 meeting_minutes。"
                "请确认使用的是平台接入版 YML，并已重新发布。"
            ),
        )

    return {
        "success": True,
        "workflow_name": workflow.get("name") or "智能会议纪要生成",
        "workflow_run_id": parsed.get("workflow_run_id") or "",
        "file_name": filename,
        "transcript": str(outputs.get("transcript") or "").strip(),
        "cleaned_transcript": str(outputs.get("cleaned_transcript") or "").strip(),
        "meeting_minutes": meeting_minutes,
        "structured_info": _normalize_structured_info(outputs.get("structured_info")),
        "generated_at": str(outputs.get("generated_at") or "").strip(),
    }
