"""统一的 Dify 调用客户端。

支持：
- Dify Workflow: /workflows/run
- Dify Advanced Chat / Chatbot: /chat-messages

设计目标：
1. 每条应用配置使用自己的 API Base、API Key、Endpoint 和超时；
2. Advanced Chat 默认使用 SSE streaming，避免复杂工作流在 blocking 模式下被 60 秒读超时截断；
3. 内网 Dify 默认不继承系统 HTTP_PROXY/HTTPS_PROXY，避免 192.168.x.x 请求被代理劫持；
4. 对外返回统一结构，前后端无需分别理解多种 Dify 返回格式。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional

import requests


CHAT_MODES = {"advanced-chat", "chat", "chatbot", "agent-chat"}
WORKFLOW_MODES = {"workflow", "dify-workflow"}


@dataclass
class DifyCallError(Exception):
    message: str
    status_code: int = 502
    url: str = ""
    response: Any = None
    error_type: str = "dify_error"

    def __str__(self) -> str:
        return self.message

    def as_dict(self) -> Dict[str, Any]:
        return {
            "message": self.message,
            "error_type": self.error_type,
            "url": self.url,
            "status_code": self.status_code,
            "response": self.response,
        }


def infer_app_mode(workflow: Dict[str, Any]) -> str:
    raw_mode = str(workflow.get("app_mode") or "").strip().lower()
    endpoint = str(workflow.get("endpoint") or "").strip().lower()

    if raw_mode in CHAT_MODES or "chat-messages" in endpoint:
        return "advanced-chat"
    return "workflow"


def default_endpoint(app_mode: str) -> str:
    return "/chat-messages" if app_mode == "advanced-chat" else "/workflows/run"


def build_url(workflow: Dict[str, Any]) -> str:
    api_base = str(workflow.get("api_base") or workflow.get("base_url") or "").strip()
    if not api_base:
        raise DifyCallError("Dify 配置缺少 API Base", status_code=500, error_type="config_error")

    app_mode = infer_app_mode(workflow)
    endpoint = str(workflow.get("endpoint") or default_endpoint(app_mode)).strip()
    if not endpoint.startswith("/"):
        endpoint = "/" + endpoint
    return api_base.rstrip("/") + endpoint


def _timeout(workflow: Dict[str, Any]) -> tuple[int, int]:
    try:
        read_timeout = int(workflow.get("timeout_seconds") or 300)
    except (TypeError, ValueError):
        read_timeout = 300
    read_timeout = max(30, min(read_timeout, 900))
    return 10, read_timeout


def _verify_ssl(workflow: Dict[str, Any]) -> bool:
    value = workflow.get("verify_ssl", 1)
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "off"}
    return bool(value)


def _session(workflow: Dict[str, Any]) -> requests.Session:
    session = requests.Session()
    # 内网地址最常见的问题之一是系统代理。默认不继承系统代理环境变量。
    session.trust_env = bool(int(workflow.get("use_system_proxy") or 0))
    return session


def _headers(workflow: Dict[str, Any]) -> Dict[str, str]:
    api_key = str(workflow.get("api_key") or workflow.get("apikey") or "").strip()
    if not api_key:
        raise DifyCallError("Dify 配置缺少 API Key", status_code=500, error_type="config_error")
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }


def _safe_json_response(resp: requests.Response) -> Any:
    try:
        return resp.json()
    except Exception:
        return {"raw_text": resp.text[:4000]}


def _raise_for_response(resp: requests.Response, url: str) -> None:
    if 200 <= resp.status_code < 300:
        return
    data = _safe_json_response(resp)
    message = "Dify 返回错误"
    if isinstance(data, dict):
        message = str(data.get("message") or data.get("error") or message)
    raise DifyCallError(
        message=message,
        status_code=resp.status_code,
        url=url,
        response=data,
        error_type="http_error",
    )


def _post(
    workflow: Dict[str, Any],
    payload: Dict[str, Any],
    *,
    stream: bool,
) -> requests.Response:
    url = build_url(workflow)
    session = _session(workflow)
    try:
        resp = session.post(
            url,
            headers=_headers(workflow),
            json=payload,
            timeout=_timeout(workflow),
            verify=_verify_ssl(workflow),
            stream=stream,
        )
        _raise_for_response(resp, url)
        return resp
    except DifyCallError:
        raise
    except requests.exceptions.ConnectTimeout as exc:
        raise DifyCallError(
            "连接 Dify 超时，请检查 IP、端口、防火墙和 Docker 端口映射。",
            status_code=504,
            url=url,
            response=repr(exc),
            error_type="connect_timeout",
        ) from exc
    except requests.exceptions.ReadTimeout as exc:
        raise DifyCallError(
            "Dify 已连接但长时间未返回数据。请检查模型、知识库节点和 Dify worker。",
            status_code=504,
            url=url,
            response=repr(exc),
            error_type="read_timeout",
        ) from exc
    except requests.exceptions.ConnectionError as exc:
        text = repr(exc)
        error_type = "read_timeout" if "Read timed out" in text or "ReadTimeout" in text else "connection_error"
        message = (
            "Dify 已连接但处理超时。系统已改用流式调用；若仍出现该错误，请检查 Dify worker/模型节点日志。"
            if error_type == "read_timeout"
            else "无法连接 Dify，请检查 API Base、端口、防火墙、代理和 Docker 服务。"
        )
        raise DifyCallError(
            message,
            status_code=504 if error_type == "read_timeout" else 502,
            url=url,
            response=text,
            error_type=error_type,
        ) from exc
    except requests.exceptions.RequestException as exc:
        raise DifyCallError(
            "Dify 请求失败",
            status_code=502,
            url=url,
            response=repr(exc),
            error_type="request_error",
        ) from exc


def call_workflow(
    workflow: Dict[str, Any],
    *,
    inputs: Optional[Dict[str, Any]] = None,
    user: str = "api-user",
) -> Dict[str, Any]:
    payload = {
        "inputs": inputs or {},
        "response_mode": "blocking",
        "user": user,
    }
    resp = _post(workflow, payload, stream=False)
    data = _safe_json_response(resp)
    if not isinstance(data, dict):
        data = {"data": data}
    return {
        "success": True,
        "app_mode": "workflow",
        "url": build_url(workflow),
        "status_code": resp.status_code,
        "raw": data,
        "data": data.get("data", data),
        "outputs": (data.get("data") or {}).get("outputs", {}) if isinstance(data.get("data"), dict) else {},
    }


def _iter_sse_json(resp: requests.Response) -> Iterable[Dict[str, Any]]:
    """逐条解析 Dify SSE，减少代理缓冲导致的等待。"""
    for raw_line in resp.iter_lines(chunk_size=1, decode_unicode=False):
        if raw_line is None:
            continue
        if isinstance(raw_line, bytes):
            line = raw_line.decode("utf-8", errors="replace").strip()
        else:
            line = str(raw_line).strip()
        if not line or line.startswith(":"):
            continue
        if line.startswith("data:"):
            line = line[5:].strip()
        if line == "[DONE]":
            break
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            yield obj


_TEXT_KEYS = ("answer", "result", "report", "text", "output", "response", "content")


def _extract_event_text(value: Any, *, depth: int = 0) -> str:
    """从 Dify 不同版本的事件或 outputs 中提取最终文本。"""
    if depth > 5 or value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return ""
    if isinstance(value, list):
        parts = [_extract_event_text(item, depth=depth + 1) for item in value]
        return "\n".join(part for part in parts if part).strip()
    if not isinstance(value, dict):
        return ""

    for key in _TEXT_KEYS:
        if key in value:
            text = _extract_event_text(value.get(key), depth=depth + 1)
            if text:
                return text

    for key in ("outputs", "data"):
        nested = value.get(key)
        if isinstance(nested, (dict, list)):
            text = _extract_event_text(nested, depth=depth + 1)
            if text:
                return text
    return ""


def call_chat(
    workflow: Dict[str, Any],
    *,
    query: str,
    user: str,
    conversation_id: str = "",
    inputs: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    if not query or not query.strip():
        raise DifyCallError("聊天测试内容不能为空", status_code=400, error_type="validation_error")

    configured_mode = str(workflow.get("response_mode") or "auto").strip().lower()
    use_streaming = configured_mode != "blocking"
    payload: Dict[str, Any] = {
        "inputs": inputs or {},
        "query": query,
        "response_mode": "streaming" if use_streaming else "blocking",
        "user": user,
    }
    if conversation_id:
        payload["conversation_id"] = conversation_id

    resp = _post(workflow, payload, stream=use_streaming)

    if not use_streaming:
        data = _safe_json_response(resp)
        if not isinstance(data, dict):
            data = {"raw": data}
        data.setdefault("answer", "")
        data["success"] = True
        data["app_mode"] = "advanced-chat"
        data["url"] = build_url(workflow)
        data["status_code"] = resp.status_code
        return data

    answer_parts: list[str] = []
    fallback_answer = ""
    conversation = conversation_id
    message_id = ""
    task_id = ""
    metadata: Dict[str, Any] = {}
    workflow_outputs: Dict[str, Any] = {}
    events: list[str] = []

    try:
        for event in _iter_sse_json(resp):
            event_name = str(event.get("event") or "")
            if event_name:
                events.append(event_name)

            conversation = str(event.get("conversation_id") or conversation or "")
            message_id = str(event.get("message_id") or event.get("id") or message_id or "")
            task_id = str(event.get("task_id") or task_id or "")

            if event_name in {"message", "agent_message"}:
                answer_parts.append(str(event.get("answer") or ""))
            elif event_name == "message_replace":
                answer_parts = [str(event.get("answer") or "")]
            elif event_name == "message_end":
                if isinstance(event.get("metadata"), dict):
                    metadata = event["metadata"]
                candidate = _extract_event_text(event)
                if candidate:
                    fallback_answer = candidate
            elif event_name == "workflow_finished":
                data = event.get("data")
                if isinstance(data, dict) and isinstance(data.get("outputs"), dict):
                    workflow_outputs = data["outputs"]
                candidate = _extract_event_text(event)
                if candidate:
                    fallback_answer = candidate
            elif event_name == "node_finished":
                data = event.get("data")
                if isinstance(data, dict):
                    node_type = str(data.get("node_type") or data.get("type") or "").lower()
                    title = str(data.get("title") or "").lower()
                    if node_type == "answer" or "answer" in title or "返回" in title or "回复" in title:
                        candidate = _extract_event_text(data.get("outputs") or data)
                        if candidate:
                            fallback_answer = candidate
            elif event_name in {"error", "workflow_error"}:
                raise DifyCallError(
                    str(event.get("message") or "Dify 流式执行失败"),
                    status_code=int(event.get("status") or 502),
                    url=build_url(workflow),
                    response=event,
                    error_type="stream_error",
                )
    finally:
        resp.close()

    answer = "".join(answer_parts).strip() or fallback_answer.strip()
    return {
        "success": True,
        "app_mode": "advanced-chat",
        "url": build_url(workflow),
        "status_code": resp.status_code,
        "answer": answer,
        "conversation_id": conversation,
        "message_id": message_id,
        "task_id": task_id,
        "metadata": metadata,
        "outputs": workflow_outputs,
        "events": events,
    }


def call_dify_app(
    workflow: Dict[str, Any],
    *,
    inputs: Optional[Dict[str, Any]] = None,
    query: str = "",
    user: str = "api-user",
    conversation_id: str = "",
) -> Dict[str, Any]:
    app_mode = infer_app_mode(workflow)
    if app_mode == "advanced-chat":
        return call_chat(
            workflow,
            query=query,
            user=user,
            conversation_id=conversation_id,
            inputs=inputs,
        )
    return call_workflow(workflow, inputs=inputs, user=user)
