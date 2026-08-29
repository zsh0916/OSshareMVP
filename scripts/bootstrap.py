# -*- coding: utf-8 -*-
r"""
SmartOffice Python 依赖一键安装脚本
================================

适用项目：
    E:\PyCharm_2023.2.5\feishu_ai_mvp

推荐用法：
    1. 将本文件放到项目根目录。
    2. 激活项目虚拟环境。
    3. 执行：
       .\.venv\Scripts\python.exe install_smartoffice_dependencies.py

仅检查，不安装：
    .\.venv\Scripts\python.exe install_smartoffice_dependencies.py --check-only

跳过 pip/setuptools/wheel 升级：
    .\.venv\Scripts\python.exe install_smartoffice_dependencies.py --no-upgrade-tools

说明：
- 本脚本安装项目直接依赖；pip 会自动安装这些包的间接依赖。
- sqlite3、json、csv、pathlib、hashlib、threading 等属于 Python 标准库，
  不需要也不能单独通过 pip 安装。
- 前端 Vue/NPM 依赖不属于 Python 依赖，需要在 frontend 目录执行 npm install。
"""

from __future__ import annotations

import argparse
import importlib
import importlib.metadata
import os
import subprocess
import sys
from dataclasses import dataclass


MIN_PYTHON = (3, 10)


@dataclass(frozen=True)
class Dependency:
    pip_spec: str
    import_name: str
    display_name: str
    purpose: str


# 项目当前代码直接依赖。
# 使用兼容范围而不是锁死单一版本，避免不同电脑/镜像缺少某个精确版本。
DEPENDENCIES: tuple[Dependency, ...] = (
    Dependency(
        "fastapi>=0.115,<1.0",
        "fastapi",
        "FastAPI",
        "平台后端 API、路由、中间件、文件上传接口",
    ),
    Dependency(
        "uvicorn[standard]>=0.30,<1.0",
        "uvicorn",
        "Uvicorn",
        "运行 FastAPI 的 ASGI 服务器；standard 包含常用性能和开发依赖",
    ),
    Dependency(
        "pydantic>=2.8,<3.0",
        "pydantic",
        "Pydantic",
        "请求参数、表单和响应数据校验",
    ),
    Dependency(
        "requests>=2.32,<3.0",
        "requests",
        "Requests",
        "调用 Dify、飞书开放平台和其他 HTTP 接口",
    ),
    Dependency(
        "python-dotenv>=1.0,<2.0",
        "dotenv",
        "python-dotenv",
        "读取项目根目录 .env 环境变量",
    ),
    Dependency(
        "PyYAML>=6.0,<7.0",
        "yaml",
        "PyYAML",
        "读取 config.yaml 业务规则配置",
    ),
    Dependency(
        "lark-oapi>=1.6.4,<2.0",
        "lark_oapi",
        "lark-oapi",
        "飞书开放平台 SDK、事件订阅、长连接和交互卡片",
    ),
    Dependency(
        "python-multipart>=0.0.20,<1.0",
        "multipart",
        "python-multipart",
        "FastAPI Form、UploadFile、会议文件和答卷文件上传",
    ),
    Dependency(
        "websocket-client>=1.8,<2.0",
        "websocket",
        "websocket-client",
        "飞书 SDK 长连接底层支持",
    ),
    Dependency(
        "requests-toolbelt>=1.0,<2.0",
        "requests_toolbelt",
        "requests-toolbelt",
        "飞书 SDK 与文件上传相关 HTTP 扩展",
    ),
)


def print_header() -> None:
    print("=" * 68)
    print(" SmartOffice Python 依赖安装器")
    print("=" * 68)
    print(f"Python：{sys.version.split()[0]}")
    print(f"解释器：{sys.executable}")
    print(f"工作目录：{os.getcwd()}")
    print(
        "虚拟环境："
        + ("是" if sys.prefix != getattr(sys, "base_prefix", sys.prefix) else "否")
    )
    print()


def ensure_python_version() -> None:
    if sys.version_info < MIN_PYTHON:
        required = ".".join(map(str, MIN_PYTHON))
        current = ".".join(map(str, sys.version_info[:3]))
        raise RuntimeError(
            f"当前 Python 为 {current}，项目至少需要 Python {required}。"
        )


def run_command(command: list[str], description: str) -> None:
    print(f"\n>>> {description}")
    print(" ".join(command))
    completed = subprocess.run(command)
    if completed.returncode != 0:
        raise RuntimeError(
            f"{description}失败，退出码：{completed.returncode}"
        )


def upgrade_install_tools() -> None:
    run_command(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--upgrade",
            "pip",
            "setuptools",
            "wheel",
        ],
        "升级 pip、setuptools 和 wheel",
    )


def install_dependencies() -> None:
    specs = [item.pip_spec for item in DEPENDENCIES]
    run_command(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--upgrade",
            *specs,
        ],
        "安装 SmartOffice 运行依赖",
    )


def installed_version(import_name: str, display_name: str) -> str:
    candidates = [
        display_name,
        display_name.lower(),
        display_name.replace("_", "-"),
        display_name.replace("-", "_"),
    ]
    for candidate in candidates:
        try:
            return importlib.metadata.version(candidate)
        except importlib.metadata.PackageNotFoundError:
            continue

    # 部分包的导入名和发行名不同，再通过顶级包映射尝试。
    packages = importlib.metadata.packages_distributions()
    distributions = packages.get(import_name, [])
    for distribution in distributions:
        try:
            return importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError:
            continue
    return "版本未知"


def verify_dependencies() -> bool:
    print("\n" + "=" * 68)
    print(" 依赖导入检查")
    print("=" * 68)

    all_ok = True
    for dependency in DEPENDENCIES:
        try:
            importlib.import_module(dependency.import_name)
            version = installed_version(
                dependency.import_name,
                dependency.display_name,
            )
            print(
                f"[通过] {dependency.display_name:<20} "
                f"{version:<14} {dependency.purpose}"
            )
        except Exception as exc:
            all_ok = False
            print(
                f"[失败] {dependency.display_name:<20} "
                f"{type(exc).__name__}: {exc}"
            )

    return all_ok


def print_project_commands() -> None:
    print("\n" + "=" * 68)
    print(" 安装完成后的启动命令")
    print("=" * 68)
    print(
        r"""
后端：
    .\.venv\Scripts\python.exe -m uvicorn web_api:app --host 0.0.0.0 --port 8000

飞书监听：
    .\.venv\Scripts\python.exe main.py

前端依赖（需要单独执行）：
    cd frontend
    npm install

前端启动：
    npm run dev -- --host 0.0.0.0 --port 5173 --strictPort

前端构建：
    npm run build
""".strip()
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="安装并检查 SmartOffice 项目 Python 依赖"
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="只检查依赖是否可导入，不执行安装",
    )
    parser.add_argument(
        "--no-upgrade-tools",
        action="store_true",
        help="安装前不升级 pip、setuptools 和 wheel",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    print_header()

    try:
        ensure_python_version()

        if not args.check_only:
            if not args.no_upgrade_tools:
                upgrade_install_tools()
            install_dependencies()

        success = verify_dependencies()
        if not success:
            print(
                "\n存在未成功导入的依赖。"
                "请检查上面的错误、网络、PyPI 镜像或当前虚拟环境。"
            )
            return 1

        print("\n全部 Python 依赖检查通过。")
        print_project_commands()
        return 0

    except KeyboardInterrupt:
        print("\n用户取消安装。")
        return 130
    except Exception as exc:
        print(f"\n安装失败：{type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
