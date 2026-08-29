"""Feishu event worker and message-routing pipeline.

Configuration comes from the private ``.env`` and public alias-based YAML.
External AI access remains behind ``dify_client`` so another provider can be
adapted without changing event normalization or card delivery behavior.
"""

import os
import json
import time
import yaml
import socket
import sqlite3
import threading
import requests
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

import lark_oapi as lark
from lark_oapi.api.im.v1 import (
    P2ImMessageReceiveV1,
    CreateMessageRequest,
    CreateMessageRequestBody,
)

from lark_oapi.event.callback.model.p2_card_action_trigger import(
    P2CardActionTrigger,
    P2CardActionTriggerResponse,
)

from .db import (
    init_db,
    message_exists,
    save_message_received,
    update_local_score,
    update_ai_result,
    update_card_status,
    print_recent_messages,
    get_message_by_message_id,
    init_workflow_table,
    resolve_enabled_workflow,
)


# =========================
# 基础路径与配置
# =========================

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = BASE_DIR / ".env"
CONFIG_PATH = BASE_DIR / "config.yaml"

DATA_DIR = BASE_DIR / "data"
LOG_PATH = DATA_DIR / "received_messages.ndjson"
DATA_DIR.mkdir(exist_ok=True)

load_dotenv(dotenv_path=ENV_PATH)

FEISHU_APP_ID = os.getenv("FEISHU_APP_ID")
FEISHU_APP_SECRET = os.getenv("FEISHU_APP_SECRET")

TARGET_CHAT_ID_LIST = [
    x.strip()
    for x in os.getenv("TARGET_CHAT_IDS", "").split(",")
    if x.strip()
]
TARGET_CHAT_IDS = set(TARGET_CHAT_ID_LIST)

PUSH_CHAT_ID = os.getenv("PUSH_CHAT_ID")


def _load_json_env_dict(name: str) -> dict:
    raw = os.getenv(name, "").strip()
    if not raw:
        return {}
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else {}
    except Exception as exc:
        print(f"环境变量 {name} 不是合法 JSON，将忽略：{exc}")
        return {}


# 部门定向推送配置。识别到具体部门后，不再默认广播到全局群。
DEPARTMENT_FEISHU_CHAT_IDS = _load_json_env_dict("DEPARTMENT_FEISHU_CHAT_IDS_JSON")
CUSTOM_CATEGORY_DEPARTMENT_MAP = _load_json_env_dict("CATEGORY_DEPARTMENT_MAP_JSON")
STRICT_DEPARTMENT_ROUTING = os.getenv("STRICT_DEPARTMENT_ROUTING", "1").strip().lower() not in {"0", "false", "no"}
ENABLE_PLATFORM_DEPARTMENT_NOTIFICATIONS = os.getenv(
    "ENABLE_PLATFORM_DEPARTMENT_NOTIFICATIONS", "1"
).strip().lower() not in {"0", "false", "no"}

DEFAULT_CATEGORY_DEPARTMENT_MAP = {
    "技术故障": "技术部",
    "销售商机": "销售部",
    "财务事项": "财务部",
    "人事行政": "人事部",
    "合同法务": "行政部",
    "客户投诉": "业务部",
    "退款处理": "财务部",
    "售后服务": "业务部",
    "交付物流": "业务部",
}

MARKET_KEYWORDS = (
    "市场", "营销", "推广", "品牌", "投放", "宣传", "渠道",
    "竞品", "展会", "活动策划", "市场活动", "客户沙龙",
)
TECH_KEYWORDS = (
    "技术", "系统", "接口", "代码", "程序", "服务器", "数据库",
    "故障", "宕机", "报警", "崩溃", "不可用", "网络", "部署", "BUG", "bug",
)

DIFY_API_BASE = os.getenv("DIFY_API_BASE", "http://127.0.0.1/v1").strip()
DIFY_API_KEY = os.getenv("DIFY_API_KEY", "").strip()
DIFY_WORKFLOW_NAME = os.getenv("DIFY_WORKFLOW_NAME", "飞书消息分类器").strip()

with open(CONFIG_PATH, "r", encoding="utf-8") as f:
    CONFIG = yaml.safe_load(f)

# Public config uses aliases. Private deployments resolve them from .env while
# keeping real Feishu resource IDs out of source control.
_chat_aliases = {
    f"CHAT_ID_{name}": value
    for name, value in zip(("PRIMARY", "SECONDARY", "TERTIARY"), TARGET_CHAT_ID_LIST)
}
CONFIG["group_weights"] = {
    _chat_aliases.get(str(key), str(key)): weight
    for key, weight in CONFIG.get("group_weights", {}).items()
}


EVENT_COUNT = 0


# =========================
# 单实例保护
# =========================

def ensure_single_instance():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", 39527))
        s.listen(1)
        print("单实例锁定成功：当前是唯一运行的监听进程")
        return s
    except OSError:
        raise RuntimeError(
            "检测到已有一个飞书监听进程在运行。请先关闭旧窗口，或执行："
            "Get-Process python,pythonw -ErrorAction SilentlyContinue | Stop-Process -Force"
        )


# =========================
# 消息解析
# =========================

def extract_text(message_type: str, content: str) -> str:
    try:
        data = json.loads(content or "{}")
    except Exception:
        return content or ""

    if message_type == "text":
        return data.get("text", "")

    if message_type == "post":
        parts = []
        post_content = data.get("content", {})
        for lang_block in post_content.values():
            for line in lang_block:
                for item in line:
                    if item.get("tag") == "text":
                        parts.append(item.get("text", ""))
        return "\n".join(parts)

    return f"[{message_type}] {content or ''}"


def normalize_event(data: P2ImMessageReceiveV1) -> dict:
    event = data.event
    message = event.message
    sender = event.sender

    sender_open_id = ""
    sender_type = ""

    if sender:
        sender_type = sender.sender_type or ""
        if sender.sender_id:
            sender_open_id = sender.sender_id.open_id or ""

    return {
        "source": "feishu",
        "message_id": message.message_id,
        "chat_id": message.chat_id,
        "chat_type": message.chat_type,
        "sender_open_id": sender_open_id,
        "sender_type": sender_type,
        "message_type": message.message_type,
        "content_text": extract_text(message.message_type, message.content),
        "raw_content": message.content,
        "create_time": message.create_time,
        "received_at": int(time.time()),
    }


# =========================
# 本地评分
# =========================

def calc_time_weight() -> tuple[int, str]:
    now = datetime.now()
    weekday = now.weekday()
    hour = now.hour

    time_weights = CONFIG.get("time_weights", {})

    if weekday >= 5:
        return int(time_weights.get("weekend", 0)), "周末"

    if 9 <= hour < 18:
        return int(time_weights.get("workday_daytime", 0)), "工作日白天"

    return int(time_weights.get("workday_night", 0)), "工作日夜间"


def local_score(payload: dict) -> dict:
    text = payload.get("content_text", "") or ""
    chat_id = payload.get("chat_id", "") or ""

    score = 0
    reasons = []

    source_score = int(CONFIG.get("source_weights", {}).get("feishu", 0))
    score += source_score
    reasons.append(f"飞书来源 +{source_score}")

    group_score = int(CONFIG.get("group_weights", {}).get(chat_id, 0))
    if group_score:
        score += group_score
        reasons.append(f"指定业务群 +{group_score}")

    for keyword, weight in CONFIG.get("keyword_weights", {}).items():
        if keyword in text:
            weight = int(weight)
            score += weight
            reasons.append(f"关键词「{keyword}」+{weight}")

    time_score, time_label = calc_time_weight()
    score += time_score
    reasons.append(f"{time_label} +{time_score}")

    thresholds = CONFIG.get("thresholds", {})
    ignore_below = int(thresholds.get("ignore_below", 35))
    push_above = int(thresholds.get("push_above", 75))
    urgent_above = int(thresholds.get("urgent_above", 110))

    if score >= urgent_above:
        level = "P0-紧急"
        action = "进入 Dify AI 分类并推送卡片"
    elif score >= push_above:
        level = "P1-重要"
        action = "进入 Dify AI 分类并推送卡片"
    elif score >= ignore_below:
        level = "P2-普通关注"
        action = "暂不推送，仅记录"
    else:
        level = "P3-忽略"
        action = "忽略"

    return {
        "score": score,
        "level": level,
        "action": action,
        "reasons": reasons,
        "should_push": score >= push_above,
        "is_urgent": score >= urgent_above,
    }


# =========================
# 本地 ndjson 日志
# =========================

def save_raw_log(
    event_no: int,
    payload: dict,
    score_info: dict | None = None,
    ai_result: dict | None = None,
    status: str = "received",
):
    record = {
        "event_no": event_no,
        "status": status,
        "received_local_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "payload": payload,
        "score_info": score_info,
        "ai_result": ai_result,
    }

    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


# =========================
# Dify 调用
# =========================
def get_tenant_access_token() -> str | None:
    """
    获取飞书 tenant_access_token，用于调用延时更新卡片接口。
    """
    url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"

    body = {
        "app_id": FEISHU_APP_ID,
        "app_secret": FEISHU_APP_SECRET,
    }

    try:
        resp = requests.post(url, json=body, timeout=20)
        data = resp.json()

        if data.get("code") != 0:
            print("获取 tenant_access_token 失败：", data)
            return None

        return data.get("tenant_access_token")

    except Exception as e:
        print("获取 tenant_access_token 异常：", repr(e))
        return None

def update_interactive_card(card_token: str, new_card: dict, open_id: str | None = None) -> bool:
    """
    使用飞书延时更新消息卡片接口，主动刷新用户点击的那张卡片。

    注意：
    非共享卡片必须传 open_ids，否则会报：
    code 300090: update card with token openid empty err
    """
    tenant_access_token = get_tenant_access_token()

    if not tenant_access_token:
        return False

    url = "https://open.feishu.cn/open-apis/interactive/v1/card/update"

    headers = {
        "Authorization": f"Bearer {tenant_access_token}",
        "Content-Type": "application/json",
    }

    # 飞书要求 open_ids 放在 card 内部
    card_to_update = dict(new_card)

    if open_id:
        card_to_update["open_ids"] = [open_id]
    else:
        print("警告：没有拿到点击人的 open_id，可能会导致 300090 错误")

    body = {
        "token": card_token,
        "card": card_to_update,
    }

    try:
        print("延时更新卡片请求 body:")
        print(json.dumps(body, ensure_ascii=False, indent=2))

        resp = requests.post(url, headers=headers, json=body, timeout=20)
        data = resp.json()

        print("延时更新卡片返回：", json.dumps(data, ensure_ascii=False))

        if data.get("code") == 0:
            print("原卡片已更新")
            return True

        print("原卡片更新失败：", data)
        return False

    except Exception as e:
        print("延时更新卡片异常：", repr(e))
        return False


def update_interactive_card_later(card_token: str, new_card: dict, open_id: str | None = None):
    """
    先让卡片回调正常返回 toast，再稍后调用延时更新接口。
    """
    def worker():
        time.sleep(0.5)
        update_interactive_card(card_token, new_card, open_id=open_id)

    threading.Thread(target=worker, daemon=True).start()
def call_dify(payload: dict, score_info: dict) -> dict:
    """
    调用 Dify Workflow。

    优先按 module_key=feishu_message_router 从 workflow_configs 读取，
    同时兼容旧名称 DIFY_WORKFLOW_NAME。

    如果数据库没有配置，则回退到 .env 里的 DIFY_API_BASE / DIFY_API_KEY。
    """
    workflow = resolve_enabled_workflow(
        module_key="feishu_message_router",
        name=DIFY_WORKFLOW_NAME,
    )

    if workflow:
        api_base = workflow.get("api_base", "").strip()
        api_key = workflow.get("api_key", "").strip()
        endpoint = workflow.get("endpoint", "/workflows/run").strip() or "/workflows/run"

        print(f"使用数据库工作流配置：{workflow.get('name')}，ID={workflow.get('id')}")
    else:
        api_base = DIFY_API_BASE
        api_key = DIFY_API_KEY
        endpoint = "/workflows/run"

        print(
            "未找到 module_key=feishu_message_router "
            f"或名称为「{DIFY_WORKFLOW_NAME}」的启用配置，回退使用 .env 中的 Dify 配置"
        )

    if not api_key:
        print("未配置 Dify API Key，使用本地兜底分类")
        return fallback_ai_result(payload, score_info)

    url = api_base.rstrip("/") + endpoint

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    body = {
        "inputs": {
            "source": payload.get("source", "feishu"),
            "chat_id": payload.get("chat_id", ""),
            "sender_open_id": payload.get("sender_open_id", ""),
            "content_text": payload.get("content_text", ""),
            "local_score": str(score_info.get("score", "")),
            "score_reasons": "\n".join(score_info.get("reasons", [])),
        },
        "response_mode": "blocking",
        "user": payload.get("sender_open_id") or "feishu-user",
    }

    try:
        print("Dify 请求地址:", url)

        resp = requests.post(url, headers=headers, json=body, timeout=60)
        print("Dify HTTP状态码:", resp.status_code)

        if resp.status_code != 200:
            print("Dify 原始返回:", resp.text)
            return fallback_ai_result(payload, score_info)

        data = resp.json()
        outputs = data.get("data", {}).get("outputs", {})
        result = outputs.get("result")

        if isinstance(result, dict):
            return result

        if isinstance(result, str):
            try:
                return json.loads(result)
            except Exception:
                print("Dify result 不是合法 JSON:", result)
                return fallback_ai_result(payload, score_info)

        print("Dify outputs 中没有 result，使用兜底分类")
        return fallback_ai_result(payload, score_info)

    except Exception as e:
        print("调用 Dify 异常:", repr(e))
        return fallback_ai_result(payload, score_info)


def fallback_ai_result(payload: dict, score_info: dict) -> dict:
    text = payload.get("content_text", "")

    if "投诉" in text or "客诉" in text:
        category = "客户投诉"
        assignee = "客服主管"
    elif "退款" in text:
        category = "退款处理"
        assignee = "客服负责人"
    elif "故障" in text or "宕机" in text or "报警" in text:
        category = "技术故障"
        assignee = "技术负责人"
    elif "合同" in text:
        category = "合同法务"
        assignee = "法务负责人"
    elif "回款" in text or "发票" in text:
        category = "财务事项"
        assignee = "财务负责人"
    else:
        category = "重要消息"
        assignee = "相关负责人"

    priority = "P0" if score_info.get("is_urgent") else "P1"

    return {
        "category": category,
        "priority": priority,
        "need_push": score_info.get("should_push", False),
        "assignee": assignee,
        "summary": text[:80],
        "suggested_action": "请相关负责人尽快确认，并在群内同步处理进展。",
    }


# =========================
# 部门定向路由与站内通知
# =========================

def resolve_target_department(payload: dict, ai_result: dict) -> str:
    """根据 AI 分类和消息正文确定唯一目标部门。"""
    explicit = str(ai_result.get("target_department") or "").strip()
    if explicit:
        return explicit

    category = str(ai_result.get("category") or "").strip()
    text = str(payload.get("content_text") or "")

    # 明确的技术故障优先归技术部，避免“市场系统故障”被误投市场部。
    if category == "技术故障":
        return "技术部"

    # 市场类关键词优先于“销售商机”等宽泛分类。
    if any(keyword in text for keyword in MARKET_KEYWORDS):
        return "市场部"

    if any(keyword in text for keyword in TECH_KEYWORDS):
        return "技术部"

    category_map = dict(DEFAULT_CATEGORY_DEPARTMENT_MAP)
    category_map.update({str(k): str(v) for k, v in CUSTOM_CATEGORY_DEPARTMENT_MAP.items()})
    return category_map.get(category, "")


def _normalize_chat_ids(value) -> list[str]:
    if isinstance(value, str):
        candidates = value.split(",")
    elif isinstance(value, (list, tuple, set)):
        candidates = value
    else:
        candidates = []
    result = []
    for item in candidates:
        chat_id = str(item or "").strip()
        if chat_id and chat_id not in result:
            result.append(chat_id)
    return result


def get_department_target_chat_ids(target_department: str, source_chat_id: str) -> list[str]:
    """
    已识别部门时优先发送到该部门群。
    严格模式下，如果没有配置部门群，不允许回退到全局 PUSH_CHAT_ID，避免跨部门广播。
    """
    if target_department:
        configured = _normalize_chat_ids(DEPARTMENT_FEISHU_CHAT_IDS.get(target_department))
        if configured:
            return configured
        if STRICT_DEPARTMENT_ROUTING:
            print(f"未配置 {target_department} 的飞书群ID，严格路由模式下不发送到全局群。")
            return []

    fallback = PUSH_CHAT_ID or source_chat_id
    return [fallback] if fallback else []


def create_platform_department_notifications(
    target_department: str,
    payload: dict,
    ai_result: dict,
) -> int:
    """给目标部门所有在职员工生成站内通知，不影响 OA 通知。"""
    if not ENABLE_PLATFORM_DEPARTMENT_NOTIFICATIONS or not target_department:
        return 0

    db_path = DATA_DIR / "messages.db"
    if not db_path.exists():
        return 0

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        table_names = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        if not {"departments", "users", "notifications", "messages"}.issubset(table_names):
            return 0

        department = conn.execute(
            "SELECT id FROM departments WHERE name = ? LIMIT 1",
            (target_department,),
        ).fetchone()
        if not department:
            print(f"站内通知未生成：员工表中不存在部门 {target_department}")
            return 0


        message_row = conn.execute(
            "SELECT id FROM messages WHERE message_id = ? LIMIT 1",
            (payload.get("message_id"),),
        ).fetchone()
        business_id = int(message_row["id"]) if message_row else None

        users = conn.execute(
            """
            SELECT id
            FROM users
            WHERE department_id = ? AND is_active = 1
            ORDER BY id
            """,
            (int(department["id"]),),
        ).fetchall()

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        category = str(ai_result.get("category") or "业务消息")
        priority = str(ai_result.get("priority") or "P1")
        summary = str(ai_result.get("summary") or payload.get("content_text") or "")[:300]
        count = 0

        for user in users:
            duplicate = conn.execute(
                """
                SELECT id FROM notifications
                WHERE user_id = ?
                  AND notification_type = 'feishu_department_message'
                  AND business_type = 'message'
                  AND business_id IS ?
                LIMIT 1
                """,
                (int(user["id"]), business_id),
            ).fetchone()
            if duplicate:
                continue
            conn.execute(
                """
                INSERT INTO notifications(
                    user_id, notification_type, title, content,
                    business_type, business_id, target_page, is_read, created_at
                ) VALUES (?, 'feishu_department_message', ?, ?, 'message', ?, 'message_center', 0, ?)
                """,
                (
                    int(user["id"]),
                    f"{target_department}｜{category}｜{priority}",
                    summary,
                    business_id,
                    now,
                ),
            )
            count += 1

        conn.commit()
        print(f"已向 {target_department} 生成 {count} 条站内通知")
        return count
    except Exception as exc:
        conn.rollback()
        print("生成部门站内通知失败：", repr(exc))
        return 0
    finally:
        conn.close()


# =========================
# 飞书卡片
# =========================

def build_alert_card(payload: dict, score_info: dict, ai_result: dict) -> dict:
    category = ai_result.get("category", "待确认")
    priority = ai_result.get("priority", score_info.get("level", "P1"))
    assignee = ai_result.get("assignee", "相关负责人")
    summary = ai_result.get("summary", payload.get("content_text", "")[:80])
    suggested_action = ai_result.get("suggested_action", "请相关负责人确认处理")
    need_push = ai_result.get("need_push", True)
    target_department = ai_result.get("target_department") or "未指定"

    if priority == "P0" or score_info.get("is_urgent"):
        template = "red"
        title_prefix = "紧急"
    elif priority == "P1":
        template = "orange"
        title_prefix = "重要"
    else:
        template = "blue"
        title_prefix = "提醒"

    reasons_text = "\n".join([f"- {r}" for r in score_info["reasons"]])

    return {
        "config": {
            "wide_screen_mode": True
        },
        "header": {
            "template": template,
            "title": {
                "tag": "plain_text",
                "content": f"{title_prefix}｜{category}｜AI消息分流提醒"
            }
        },
        "elements": [
            {
                "tag": "markdown",
                "content": (
                    f"**AI分类：** {category}\n\n"
                    f"**AI优先级：** {priority}\n\n"
                    f"**建议负责人：** {assignee}\n\n"
                    f"**目标部门：** {target_department}\n\n"
                    f"**规则分：** {score_info['score']}\n\n"
                    f"**AI建议推送：** {need_push}"
                )
            },
            {
                "tag": "hr"
            },
            {
                "tag": "markdown",
                "content": f"**AI摘要：**\n{summary}"
            },
            {
                "tag": "markdown",
                "content": f"**建议动作：**\n{suggested_action}"
            },
            {
                "tag": "hr"
            },
            {
                "tag": "markdown",
                "content": f"**原始消息：**\n{payload.get('content_text', '')}"
            },
            {
                "tag": "markdown",
                "content": f"**命中原因：**\n{reasons_text}"
            },
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {
                            "tag": "plain_text",
                            "content": "已处理"
                        },
                        "type": "primary",
                        "value": {
                            "action": "handled",
                            "message_id": payload.get("message_id"),
                            "category": category,
                            "priority": priority
                        }
                    },
                    {
                        "tag": "button",
                        "text": {
                            "tag": "plain_text",
                            "content": "误判"
                        },
                        "type": "danger",
                        "value": {
                            "action": "wrong",
                            "message_id": payload.get("message_id"),
                            "category": category,
                            "priority": priority
                        }
                    },
                    {
                        "tag": "button",
                        "text": {
                            "tag": "plain_text",
                            "content": "转人工"
                        },
                        "type": "default",
                        "value": {
                            "action": "manual",
                            "message_id": payload.get("message_id"),
                            "category": category,
                            "priority": priority
                        }
                    }
                ]
            },
            {
                "tag": "note",
                "elements": [
                    {
                        "tag": "plain_text",
                        "content": (
                            f"来源群：{payload.get('chat_id')}｜"
                            f"消息ID：{payload.get('message_id')}"
                        )
                    }
                ]
            }
        ]
    }

def build_status_card(record: dict, action_type: str, status_text: str) -> dict:
    """
    用户点击 已处理 / 误判 / 转人工 后，返回一张更新后的状态卡片。
    这样飞书里的原卡片会发生明显变化。
    """
    if action_type == "handled":
        template = "green"
        title = "已处理｜AI消息分流提醒"
        status_line = "✅ 已处理"
    elif action_type == "wrong":
        template = "red"
        title = "AI误判｜AI消息分流提醒"
        status_line = "⚠️ 已标记为 AI 误判"
    elif action_type == "manual":
        template = "purple"
        title = "转人工｜AI消息分流提醒"
        status_line = "👤 已转人工处理"
    else:
        template = "blue"
        title = "状态已更新｜AI消息分流提醒"
        status_line = status_text

    local_reasons = record.get("local_reasons") or "[]"
    try:
        reasons = json.loads(local_reasons)
    except Exception:
        reasons = []

    reasons_text = "\n".join([f"- {r}" for r in reasons]) if reasons else "无"

    category = record.get("ai_category") or "待确认"
    priority = record.get("ai_priority") or "待确认"
    assignee = record.get("ai_assignee") or "相关负责人"
    summary = record.get("ai_summary") or ""
    suggested_action = record.get("ai_suggested_action") or ""
    content_text = record.get("content_text") or ""

    return {
        "config": {
            "wide_screen_mode": True
        },
        "header": {
            "template": template,
            "title": {
                "tag": "plain_text",
                "content": title
            }
        },
        "elements": [
            {
                "tag": "markdown",
                "content": (
                    f"**当前状态：** {status_line}\n\n"
                    f"**AI分类：** {category}\n\n"
                    f"**AI优先级：** {priority}\n\n"
                    f"**建议负责人：** {assignee}\n\n"
                    f"**规则分：** {record.get('local_score')}"
                )
            },
            {
                "tag": "hr"
            },
            {
                "tag": "markdown",
                "content": f"**AI摘要：**\n{summary}"
            },
            {
                "tag": "markdown",
                "content": f"**建议动作：**\n{suggested_action}"
            },
            {
                "tag": "hr"
            },
            {
                "tag": "markdown",
                "content": f"**原始消息：**\n{content_text}"
            },
            {
                "tag": "markdown",
                "content": f"**命中原因：**\n{reasons_text}"
            },
            {
                "tag": "note",
                "elements": [
                    {
                        "tag": "plain_text",
                        "content": (
                            f"该卡片已被操作：{status_text}｜"
                            f"消息ID：{record.get('message_id')}"
                        )
                    }
                ]
            }
        ]
    }
def send_feishu_card(chat_id: str, card: dict):
    client = (
        lark.Client.builder()
        .app_id(FEISHU_APP_ID)
        .app_secret(FEISHU_APP_SECRET)
        .log_level(lark.LogLevel.WARNING)
        .build()
    )

    body = (
        CreateMessageRequestBody.builder()
        .receive_id(chat_id)
        .msg_type("interactive")
        .content(json.dumps(card, ensure_ascii=False))
        .build()
    )

    request = (
        CreateMessageRequest.builder()
        .receive_id_type("chat_id")
        .request_body(body)
        .build()
    )

    response = client.im.v1.message.create(request)

    if not response.success():
        print("飞书卡片发送失败：")
        print("code:", response.code)
        print("msg:", response.msg)
        return False

    print("飞书卡片已推送")
    return True


# =========================
# 主消息处理
# =========================
def extract_operator_open_id(raw: dict) -> str | None:
    """
    从飞书卡片回调数据里提取点击按钮用户的 open_id。
    不同 SDK / 事件版本字段可能略有差异，所以做多路径兼容。
    """
    event = raw.get("event", {}) or {}

    candidates = [
        event.get("operator", {}).get("open_id"),
        event.get("operator", {}).get("operator_id", {}).get("open_id"),
        event.get("operator_id", {}).get("open_id"),
        event.get("user", {}).get("open_id"),
        event.get("open_id"),
        raw.get("operator", {}).get("open_id"),
        raw.get("open_id"),
    ]

    for item in candidates:
        if item:
            return item

    return None
def handle_card_action(data: P2CardActionTrigger) -> P2CardActionTriggerResponse:
    """
    处理飞书卡片按钮点击：
    已处理 / 误判 / 转人工

    这版修复：
    code 300090: update card with token openid empty err
    """
    try:
        raw = json.loads(lark.JSON.marshal(data))
        event = raw.get("event", {}) or {}
        action = event.get("action", {}) or {}
        value = action.get("value", {}) or {}

        action_type = value.get("action")
        message_id = value.get("message_id")

        card_update_token = event.get("token")
        operator_open_id = extract_operator_open_id(raw)

        print("\n========== 收到卡片按钮回调 ==========")
        print("action_type:", action_type)
        print("message_id:", message_id)
        print("card_update_token 是否存在:", bool(card_update_token))
        print("operator_open_id:", operator_open_id)

        if not message_id:
            return P2CardActionTriggerResponse({
                "toast": {
                    "type": "error",
                    "content": "未找到消息ID，无法更新状态"
                }
            })

        if action_type == "handled":
            update_card_status(message_id, "handled")
            toast_type = "success"
            toast_text = "已标记为：已处理"

        elif action_type == "wrong":
            update_card_status(message_id, "wrong_ai_result")
            toast_type = "warning"
            toast_text = "已标记为：AI误判"

        elif action_type == "manual":
            update_card_status(message_id, "manual_followup")
            toast_type = "success"
            toast_text = "已标记为：转人工处理"

        else:
            update_card_status(message_id, f"unknown_action_{action_type}")
            toast_type = "warning"
            toast_text = f"未知操作：{action_type}"

        record = get_message_by_message_id(message_id)

        if not record:
            return P2CardActionTriggerResponse({
                "toast": {
                    "type": "error",
                    "content": "数据库中未找到该消息"
                }
            })

        new_card = build_status_card(
            record=record,
            action_type=action_type,
            status_text=toast_text,
        )

        if card_update_token:
            update_interactive_card_later(
                card_update_token,
                new_card,
                open_id=operator_open_id,
            )
        else:
            print("没有拿到 card_update_token，无法主动刷新原卡片")

        if not operator_open_id:
            print("没有拿到 operator_open_id，下面打印 raw 便于定位字段：")
            print(json.dumps(raw, ensure_ascii=False, indent=2))

        print("卡片状态已更新：", toast_text)

        return P2CardActionTriggerResponse({
            "toast": {
                "type": toast_type,
                "content": toast_text
            }
        })

    except Exception as e:
        print("处理卡片回调异常:", repr(e))

        return P2CardActionTriggerResponse({
            "toast": {
                "type": "error",
                "content": "处理失败，请查看后台日志"
            }
        })
def handle_message(data: P2ImMessageReceiveV1) -> None:
    global EVENT_COUNT

    try:
        EVENT_COUNT += 1
        payload = normalize_event(data)
        message_id = payload["message_id"]

        print("\n========== 收到飞书消息 ==========")
        print("本地接收序号:", EVENT_COUNT)
        print("message_id:", message_id)
        print("chat_id:", payload["chat_id"])
        print("sender_type:", payload["sender_type"])
        print("content_text:", payload["content_text"])

        save_raw_log(
            event_no=EVENT_COUNT,
            payload=payload,
            status="received_before_filter",
        )

        # 数据库持久去重
        if message_exists(message_id):
            print("处理结果：数据库中已存在该 message_id，跳过")
            save_raw_log(
                event_no=EVENT_COUNT,
                payload=payload,
                status="ignored_duplicate_in_db",
            )
            return

        # 先保存收到的消息
        save_message_received(payload)

        if TARGET_CHAT_IDS and payload["chat_id"] not in TARGET_CHAT_IDS:
            print("处理结果：非指定业务群，忽略")
            update_card_status(message_id, "ignored_not_target_chat")
            save_raw_log(
                event_no=EVENT_COUNT,
                payload=payload,
                status="ignored_not_target_chat",
            )
            return

        if payload["sender_type"] in ("app", "bot"):
            print("处理结果：机器人消息，忽略")
            update_card_status(message_id, "ignored_bot_message")
            save_raw_log(
                event_no=EVENT_COUNT,
                payload=payload,
                status="ignored_bot_message",
            )
            return

        score_info = local_score(payload)
        update_local_score(message_id, score_info)

        print("\n本地评分结果：")
        print("score:", score_info["score"])
        print("level:", score_info["level"])
        print("action:", score_info["action"])
        print("命中原因:")
        for reason in score_info["reasons"]:
            print("-", reason)

        save_raw_log(
            event_no=EVENT_COUNT,
            payload=payload,
            score_info=score_info,
            status="scored",
        )

        if not score_info["should_push"]:
            print("\n未达到推送阈值，不调用 Dify，不推送卡片")
            update_card_status(message_id, "not_pushed_low_score")
            return

        print("\n达到推送阈值，开始调用 Dify AI 分类...")
        ai_result = call_dify(payload, score_info)
        target_department = resolve_target_department(payload, ai_result)
        ai_result["target_department"] = target_department
        update_ai_result(message_id, ai_result)

        print("Dify AI结果：")
        print(json.dumps(ai_result, ensure_ascii=False, indent=2))

        save_raw_log(
            event_no=EVENT_COUNT,
            payload=payload,
            score_info=score_info,
            ai_result=ai_result,
            status="ai_classified",
        )

        need_push = bool(ai_result.get("need_push", False)) or score_info["should_push"]

        if not need_push:
            print("AI 判断无需推送")
            update_card_status(message_id, "ai_no_push")
            return

        print("开始按部门生成并推送消息...")
        target_department = str(ai_result.get("target_department") or "").strip()
        target_chat_ids = get_department_target_chat_ids(target_department, payload["chat_id"])
        card = build_alert_card(payload, score_info, ai_result)

        sent_count = 0
        for target_chat_id in target_chat_ids:
            print(f"飞书目标部门={target_department or '未分类'}，目标群={target_chat_id}")
            if send_feishu_card(target_chat_id, card):
                sent_count += 1

        platform_count = create_platform_department_notifications(
            target_department, payload, ai_result
        )

        if sent_count > 0:
            final_status = "sent"
        elif platform_count > 0:
            final_status = "platform_notified"
        else:
            final_status = "no_department_route" if target_department else "send_failed"

        update_card_status(message_id, final_status)

        save_raw_log(
            event_no=EVENT_COUNT,
            payload=payload,
            score_info=score_info,
            ai_result=ai_result,
            status=final_status,
        )

        print_recent_messages(5)

    except Exception as e:
        print("处理消息异常:", repr(e))


event_handler = (
    lark.EventDispatcherHandler.builder("", "", lark.LogLevel.WARNING)
    .register_p2_im_message_receive_v1(handle_message)
    .register_p2_card_action_trigger(handle_card_action)
    .build()
)


def main():
    lock_socket = ensure_single_instance()

    init_db()
    init_workflow_table()

    print("当前项目目录 =", BASE_DIR)
    print(".env 路径 =", ENV_PATH)
    print("config.yaml 路径 =", CONFIG_PATH)
    print("本地消息日志 =", LOG_PATH)
    print("FEISHU_APP_ID =", FEISHU_APP_ID)
    print("FEISHU_APP_SECRET 是否存在 =", bool(FEISHU_APP_SECRET))
    print("TARGET_CHAT_IDS =", TARGET_CHAT_IDS)
    print("PUSH_CHAT_ID =", PUSH_CHAT_ID)
    print("STRICT_DEPARTMENT_ROUTING =", STRICT_DEPARTMENT_ROUTING)
    print("DEPARTMENT_FEISHU_CHAT_IDS =", DEPARTMENT_FEISHU_CHAT_IDS)
    print("ENABLE_PLATFORM_DEPARTMENT_NOTIFICATIONS =", ENABLE_PLATFORM_DEPARTMENT_NOTIFICATIONS)
    print("DIFY_API_BASE =", DIFY_API_BASE)
    print("DIFY_API_KEY 是否存在 =", bool(DIFY_API_KEY))
    print("DIFY_WORKFLOW_NAME =", DIFY_WORKFLOW_NAME)


    if not FEISHU_APP_ID or not FEISHU_APP_SECRET:
        raise RuntimeError("请检查 .env 中的 FEISHU_APP_ID 和 FEISHU_APP_SECRET")

    ws_client = lark.ws.Client(
        FEISHU_APP_ID,
        FEISHU_APP_SECRET,
        event_handler=event_handler,
        log_level=lark.LogLevel.WARNING,
    )

    print("飞书 + Dify AI + SQLite 消息分流服务已启动，请不要关闭窗口...")
    ws_client.start()


if __name__ == "__main__":
    main()
