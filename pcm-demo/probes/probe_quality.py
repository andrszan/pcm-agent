from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

DEMO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DEMO_ROOT))

from common.agent_decision_loop import prepare_node_resume_message
from common.files import write_json
from common.timing import StepTiming
from quality.workflow import new_state, node_resume_keys, record_failure, run_node

CLI_SOURCE = '''import argparse
import json
from pathlib import Path

parser = argparse.ArgumentParser(description="本地便签：添加非空文本并查看已保存便签")
parser.add_argument("action", choices=["add", "list"])
parser.add_argument("text", nargs="?")
args = parser.parse_args()
path = Path(__file__).parent / ".data" / "notes.json"
if args.action == "add" and (args.text is None or not args.text.strip()):
    parser.error("添加便签需要非空文本")
notes = json.loads(path.read_text()) if path.exists() else []
if args.action == "add":
    notes.append(args.text.strip())
    path.parent.mkdir(exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(notes, ensure_ascii=False))
    temporary.replace(path)
print(json.dumps(notes, ensure_ascii=False))
'''


def prepare_fixture(run_dir: Path) -> dict:
    root = run_dir / "product"
    (root / "docs/backlog").mkdir(parents=True)
    (root / ".claude/skills/product-experience-audit").mkdir(parents=True)
    (root / "notes.py").write_text(CLI_SOURCE, encoding="utf-8")
    (root / "README.md").write_text(
        "# 本地便签探针\n这是质量执行通道的隔离CLI产品fixture，不是客户交付物。"
        "当前范围仅为单用户顺序执行添加非空文本、列出已有便签、进程重启后保留结果。"
        "没有Web界面、网络服务、账户、删除、编辑、并发写入或外部资源合同。"
        "运行 python3 notes.py add '中文便签'，然后 python3 notes.py list。"
        "可在本目录 .data 内创建非敏感测试数据；不操作目录外的数据，不更改受跟踪文件。\n", encoding="utf-8")
    (root / "AGENTS.md").write_text("使用中文。此处只执行当前CLI产品真实任务和只读审计，不改受跟踪文件或Git。测试数据只写 .data。\n", encoding="utf-8")
    (root / "CLAUDE.md").write_text("@AGENTS.md\n", encoding="utf-8")
    (root / "plugins-lock.json").write_text('{"version":1,"plugins":[]}\n', encoding="utf-8")
    (root / ".gitignore").write_text(".data/\n.pcm/\n__pycache__/\n", encoding="utf-8")
    (root / "docs/backlog/backlog.md").write_text(
        "# 当前范围\n\n## BR-001 本地便签添加与列出\n"
        "顺序1，无前置依赖。单用户可以添加非空文本、列出已保存便签；中文及再次启动后结果正确，空文本拒绝。"
        "只要求顺序本地CLI操作，不承诺编辑、删除、并发、多用户或网络界面。\n", encoding="utf-8")
    shutil.copyfile(DEMO_ROOT.parent / ".claude/skills/product-experience-audit/SKILL.md",
                    root / ".claude/skills/product-experience-audit/SKILL.md")
    for args in (("init", "-b", "main"), ("config", "user.name", "质量探针"),
                 ("config", "user.email", "quality-probe@example.com"), ("add", "."), ("commit", "-m", "test: 隔离便签现场")):
        subprocess.run(["git", "-C", str(root), *args], capture_output=True, check=True)
    source = {"status": "success", "phase": "phase_1_requirement_development", "step": 13, "current_step": 13,
              "current_node": "phase_1:select_requirement", "active_requirement": None, "requirement_cycle": None,
              "blocked": None, "error": None, "workspace": {"root": str(run_dir), "final_path": str(root)},
              "applicable_repositories": ["root"], "repositories": [{"name": "root", "path": str(root)}],
              "requirement_registry": {"schema_version": 1, "source": {"path": "docs/backlog/backlog.md", "sha256": "fixture"},
                  "requirements": [{"id": "BR-001", "title": "本地便签添加与列出", "order": 1, "depends_on": [], "status": "completed", "completion": {"step": 18}}]}}
    state = new_state(source, "synthetic-completed-fixture", run_dir.name)
    write_json(run_dir / "state.json", state)
    return state


async def probe(run_dir: Path, *, resume: bool = False, message_file: Path | None = None) -> int:
    if resume:
        state = json.loads((run_dir / "state.json").read_text())
        if state.get("source_run_id") != "synthetic-completed-fixture" or Path(state["workspace"]["final_path"]) != run_dir / "product":
            raise ValueError("只能恢复本探针创建的隔离 fixture")
    else:
        run_dir.mkdir(parents=True, exist_ok=False)
        (run_dir / "logs").mkdir()
        state = prepare_fixture(run_dir)
    message = prepare_node_resume_message(run_dir, state, state["current_node"], node_resume_keys(state), message_file) if message_file else None
    before = subprocess.check_output(["git", "-C", state["workspace"]["final_path"], "rev-parse", "HEAD"])
    nodes = []
    try:
        while state["current_node"] in {"quality:prepare", "quality:audit", "quality:route", "quality:complete"}:
            nodes.append(state["current_node"])
            timing = StepTiming()
            with timing.activate():
                timing.begin_attempt(node=state["current_node"], round_number=state["quality"]["round"])
                timing.bind_run(run_dir, existing=True)
                result = await run_node(run_dir, state, resume_message=message)
                message = None
                timing.observe_result(run_dir, result)
                timing.finish(returned=True)
        after = subprocess.check_output(["git", "-C", state["workspace"]["final_path"], "rev-parse", "HEAD"])
        audit = json.loads((run_dir / "quality/rounds/0001/audit.json").read_text())["data"]
        checks = {"real_agent_sessions": len(state.get("claude_sessions", {})) >= 2,
                  "real_task_coverage": bool(audit["coverage"]), "no_product_commit": before == after,
                  "routed": (run_dir / "quality/rounds/0001/route.json").is_file(),
                  "no_route_agent": not any(key.startswith("quality_route_") for key in state.get("claude_sessions", {}))}
        passed = all(checks.values())
        write_json(run_dir / "probe-result.json", {"status": "passed" if passed else "failed", "checks": checks,
            "nodes": nodes, "final_node": state["current_node"], "candidate_count": len(audit["candidates"]),
            "scope": "隔离CLI fixture的真实Agent、负责人、静态提取与审计分流；来源完成状态为测试输入，不代表Rulefolio审计或真实阶段一交付"})
        print(json.dumps({"status": "passed" if passed else "failed", "result": str(run_dir / "probe-result.json")}, ensure_ascii=False))
        return 0 if passed else 1
    except Exception as error:
        record_failure(run_dir, state, error)
        print(json.dumps({"status": "failed", "state": str(run_dir / "state.json"), "error_type": type(error).__name__}))
        return 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="在隔离CLI产品上验证真实质量执行通道，不操作已有产品")
    location = parser.add_mutually_exclusive_group()
    location.add_argument("--run-dir", type=Path)
    location.add_argument("--resume", type=Path)
    parser.add_argument("--timeout", type=int, default=1200)
    parser.add_argument("--resume-message-file", type=Path)
    args = parser.parse_args()
    if args.resume_message_file and not args.resume:
        parser.error("恢复消息只能用于已有探针的 --resume")
    target = args.resume or args.run_dir or DEMO_ROOT / "runs" / datetime.now(timezone.utc).strftime("quality-channel-%Y%m%dT%H%M%SZ")
    try:
        exit_code = asyncio.run(asyncio.wait_for(probe(target.resolve(), resume=args.resume is not None, message_file=args.resume_message_file), timeout=args.timeout))
    except TimeoutError:
        print(json.dumps({"status": "interrupted", "reason": "probe_timeout", "resume": str(target.resolve())}))
        exit_code = 1
    sys.exit(exit_code)
