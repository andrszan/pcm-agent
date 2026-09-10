from __future__ import annotations

from pathlib import Path


def run(prd_path: Path) -> dict[str, object]:
    content = prd_path.read_text(encoding="utf-8")
    if not content.strip():
        return {
            "step": 0,
            "name": "接收产品初稿",
            "status": "failed",
            "summary": "产品初稿为空。",
            "applicable": True,
            "outputs": [],
            "blocked": None,
            "error": {
                "type": "empty_product_draft",
                "message": "请提供非空的产品想法或资料。",
            },
        }

    return {
        "step": 0,
        "name": "接收产品初稿",
        "status": "success",
        "summary": "已接收产品初稿，不在此步骤判断内容完整度。",
        "applicable": False,
        "outputs": [],
        "blocked": None,
        "error": None,
        "skip_reason": "已有非空产品输入，无需生成初稿。",
    }
