from __future__ import annotations

import importlib.util
import json
import re
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

from common.files import write_json
from quality.git import main_versions, repositories


SCRIPT_PATH = Path(__file__).resolve().parents[2] / ".claude/skills/push-changes/scripts/push.py"


def enabled(state: dict[str, Any]) -> bool:
    if "remote_sync" not in state:
        return False
    binding = state["remote_sync"]
    if not isinstance(binding, dict) or binding.get("enabled") is not True:
        raise RuntimeError("远程同步启用记录无效，不能降级为旧运行")
    return True


@lru_cache(maxsize=1)
def push_module():
    spec = importlib.util.spec_from_file_location("pcm_push_changes", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("缺少独立推送脚本")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def push_inputs(state: dict[str, Any]) -> list[dict[str, str]]:
    paths = repositories(state)
    expected = {}
    if enabled(state):
        from common.gitlab import remote_parent_path

        parent_path = remote_parent_path(state)
        binding = state["remote_sync"]
        name = binding.get("project_name")
        records = binding.get("repositories")
        if (
            not isinstance(name, str)
            or re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name) is None
            or not isinstance(records, dict)
            or set(records) != {key for key, _ in paths}
        ):
            raise RuntimeError("远程产品身份或仓库绑定记录不完整")
        for key, _ in paths:
            if key not in {"root", "frontend", "backend"}:
                raise RuntimeError("远程仓库名称不在产品交付范围内")
            project = name if key == "root" else f"{name}-{key}"
            url = f"git@gitlab.com:{parent_path}/{name}/{project}.git"
            if not isinstance(records[key], dict) or records[key].get("url") != url:
                raise RuntimeError(f"仓库 {key} 的登记地址与产品身份不一致")
            expected[key] = url
    ordered = [item for item in paths if item[0] != "root"] + [item for item in paths if item[0] == "root"]
    return [
        {"name": name, "path": str(path), **({"expected_url": expected[name]} if name in expected else {})}
        for name, path in ordered
    ]


def sync_repositories(
    run_dir: Path,
    state: dict[str, Any],
    receipt_path: Path,
    *,
    targets: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    if not enabled(state):
        raise RuntimeError("旧运行未启用自动远程同步")
    inputs = push_inputs(state)
    if receipt_path.is_symlink() or not receipt_path.resolve().is_relative_to(run_dir.resolve()):
        raise RuntimeError("推送结果路径越出当前运行或为符号链接")
    if receipt_path.exists():
        saved = json.loads(receipt_path.read_text(encoding="utf-8"))
        rows = saved.get("repositories") if isinstance(saved, dict) else None
        if (
            not isinstance(saved, dict)
            or saved.get("status") not in {"running", "failed", "blocked", "success"}
            or not isinstance(rows, list)
            or len(rows) != len(inputs)
        ):
            raise RuntimeError("推送结果记录无效")
        for item, row in zip(inputs, rows, strict=True):
            if (
                not isinstance(row, dict)
                or row.get("name") != item["name"]
                or row.get("path") != item["path"]
                or row.get("expected_url") != item["expected_url"]
                or row.get("branch") != "main"
                or not isinstance(row.get("target_sha"), str)
                or re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", row["target_sha"]) is None
            ):
                raise RuntimeError("推送结果与当前仓库绑定不一致")
        recorded = {row["name"]: row["target_sha"] for row in rows}
        if targets is not None and targets != recorded:
            raise RuntimeError("本地完成版本与原推送目标不一致，保留现场")
        targets = recorded
    elif targets is None:
        targets = main_versions(state)
    if not isinstance(targets, dict) or set(targets) != {item["name"] for item in inputs}:
        raise RuntimeError("推送目标版本与适用仓库不一致")
    for item in inputs:
        target = targets[item["name"]]
        if not isinstance(target, str) or re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", target) is None:
            raise RuntimeError("推送目标不是完整提交 SHA")
        item["target_sha"] = target
    rows = [
        {"name": item["name"], "path": item["path"], "url": item["expected_url"],
         "branch": "main", "target_sha": item["target_sha"], "remote_sha": None, "status": "pending"}
        for item in inputs
    ]

    def save(results, status="running", error=None):
        evidence = []
        for item, row in zip(inputs, results, strict=True):
            evidence.append({**row, "name": item["name"], "path": item["path"],
                             "branch": "main", "target_sha": item["target_sha"],
                             "expected_url": item["expected_url"]})
        write_json(receipt_path, {"status": status, "repositories": evidence, "error": error})

    save(rows)
    module = push_module()
    try:
        results = module.push_repositories(inputs, on_update=save)
    except module.PushError as error:
        status = "blocked" if error.blocked else "failed"
        save(error.results, status, str(error))
        if error.blocked:
            from common.gitlab import RemoteBlocked

            raise RemoteBlocked(str(error)) from error
        raise
    save(results, "success")
    return results
