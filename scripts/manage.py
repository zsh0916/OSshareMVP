"""Unified maintenance CLI for configuration, database and AI diagnostics."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
from pathlib import Path

import yaml
from dotenv import load_dotenv

from backend.db import DB_PATH, get_enabled_workflow_by_name, init_db, init_workflow_table, print_recent_messages
from backend.dify_client import DifyCallError, call_dify_app, infer_app_mode

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"
CONFIG_PATH = ROOT / "config.yaml"


def check_config(_args: argparse.Namespace) -> int:
    load_dotenv(ENV_PATH)
    print("项目目录 =", ROOT)
    print(".env 是否存在 =", ENV_PATH.exists())
    print("config.yaml 是否存在 =", CONFIG_PATH.exists())
    for key in ("FEISHU_APP_ID", "FEISHU_APP_SECRET", "TARGET_CHAT_IDS", "PUSH_CHAT_ID"):
        print(f"{key} 是否存在 =", bool(os.getenv(key)))
    with CONFIG_PATH.open("r", encoding="utf-8") as file:
        print("公开规则配置 =", yaml.safe_load(file))
    return 0


def initialize_db(_args: argparse.Namespace) -> int:
    init_db()
    print("数据库已初始化：", DB_PATH)
    print_recent_messages()
    return 0


def inspect_oa(_args: argparse.Namespace) -> int:
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            """SELECT id, application_type, application_type_name, applicant_name,
                      department, status, source, module_key, workflow_name,
                      created_at, submitted_at
               FROM oa_applications WHERE status = 'submitted' ORDER BY id DESC"""
        ).fetchall()
    finally:
        connection.close()
    print("已提交申请数量：", len(rows))
    for row in rows:
        print(dict(row))
    return 0


def check_ai(args: argparse.Namespace) -> int:
    init_workflow_table()
    workflow = get_enabled_workflow_by_name(args.workflow)
    if not workflow:
        print(f"未找到启用中的 AI 配置：{args.workflow}")
        return 1
    print("应用名称 =", workflow.get("name"))
    print("应用模式 =", infer_app_mode(workflow))
    print("模块绑定 =", workflow.get("module_key"))
    print("API Key 是否存在 =", bool(workflow.get("api_key")))
    try:
        if infer_app_mode(workflow) == "advanced-chat":
            result = call_dify_app(workflow, query=args.query, inputs={}, user="diagnostic-user")
        else:
            result = call_dify_app(
                workflow,
                inputs={
                    "source": "feishu", "chat_id": "CHAT_ID_TEST",
                    "sender_open_id": "USER_OPEN_ID_TEST", "content_text": args.query,
                    "local_score": "100", "score_reasons": "diagnostic input",
                },
                user="diagnostic-user",
            )
    except DifyCallError as exc:
        print(json.dumps(exc.as_dict(), ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Smart Office maintenance commands")
    commands = root.add_subparsers(dest="command", required=True)
    commands.add_parser("check-config").set_defaults(handler=check_config)
    commands.add_parser("init-db").set_defaults(handler=initialize_db)
    commands.add_parser("inspect-oa").set_defaults(handler=inspect_oa)
    ai = commands.add_parser("check-ai")
    ai.add_argument("workflow", nargs="?", default="WORKFLOW_ALIAS")
    ai.add_argument("query", nargs="?", default="示例业务消息")
    ai.set_defaults(handler=check_ai)
    return root


def main() -> int:
    args = parser().parse_args()
    return int(args.handler(args))


if __name__ == "__main__":
    raise SystemExit(main())

