"""Fail when common private artifacts or credential shapes may be published."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXCLUDED_PARTS = {".venv", "node_modules", "dist", "__pycache__", ".idea"}
PRIVATE_FILES = {
    ROOT / ".env",
    ROOT / "data" / "messages.db",
    ROOT / "data" / "employee_info.csv",
    ROOT / "data" / "employee_initial_accounts.csv",
    ROOT / "data" / "received_messages.ndjson",
}
PATTERNS = {
    "Feishu app id": re.compile(r"\bcli_[A-Za-z0-9]{12,}\b"),
    "Feishu resource id": re.compile(r"\b(?:oc|ou|om)_[A-Za-z0-9]{16,}\b"),
    "Dify key": re.compile(r"\bapp-[A-Za-z0-9_-]{16,}\b"),
}


def public_text_files():
    for path in ROOT.rglob("*"):
        if not path.is_file() or any(part in EXCLUDED_PARTS for part in path.parts):
            continue
        if path in PRIVATE_FILES or path.suffix.lower() in {".db", ".jpg", ".png", ".mp4"}:
            continue
        yield path


def main() -> int:
    findings: list[str] = []
    for path in public_text_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for label, pattern in PATTERNS.items():
            if pattern.search(text):
                findings.append(f"{path.relative_to(ROOT)}: possible {label}")
    if findings:
        print("Public release check failed:")
        print("\n".join(f"- {item}" for item in findings))
        return 1
    print("Public release check passed; private runtime files remain covered by .gitignore.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
