from __future__ import annotations

import re
from pathlib import Path

REQUIRED_SECTIONS = (
    "## A. 产品身份与文档边界",
    "## C. 用户与使用场景",
    "## D. 核心价值与业务闭环",
    "## E. 产品范围",
    "## P. 产品验收",
)
NEXT_SECTION = re.compile(r"^## (?!#)", re.MULTILINE)


def missing_sections(content: str) -> list[str]:
    missing: list[str] = []
    for section in REQUIRED_SECTIONS:
        heading = re.search(rf"^{re.escape(section)}\s*$", content, re.MULTILINE)
        if heading is None:
            missing.append(section)
            continue
        next_heading = NEXT_SECTION.search(content, heading.end())
        body_end = next_heading.start() if next_heading else len(content)
        if not content[heading.end() : body_end].strip():
            missing.append(section)
    return missing


def run(prd_path: Path) -> dict[str, object]:
    content = prd_path.read_text(encoding="utf-8")
    missing = missing_sections(content)
    if missing:
        return {
            "step": 0,
            "name": "形成产品初稿",
            "status": "failed",
            "summary": "产品初稿不完整，缺少必要章节。",
            "applicable": True,
            "outputs": [],
            "blocked": None,
            "error": {
                "type": "incomplete_product_draft",
                "message": f"缺少必要章节：{', '.join(missing)}",
            },
        }

    return {
        "step": 0,
        "name": "形成产品初稿",
        "status": "success",
        "summary": "输入已包含完整产品初稿，第 0 步无副作用跳过。",
        "applicable": False,
        "outputs": [],
        "blocked": None,
        "error": None,
        "skip_reason": "已包含产品身份、用户场景、核心业务闭环、产品范围和验收标准。",
    }
