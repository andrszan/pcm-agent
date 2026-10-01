from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib
import inspect
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

DEMO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DEMO_ROOT))

from common.agent_decision_loop import prepare_node_resume_message, prepare_resume_message
from run_step import safe_error_projection
from common.files import write_json
from common.state import read_state, write_state
from common.timing import StepTiming
from feedback import workflow

SKILLS = (
    "product-feedback-triage", "requirement-breakdown", "project-intake",
    "trd-design", "dev-workflow", "session-rule-retrospective", "commit-changes",
)
STEP_MODULES = {
    13: "step_13_select_requirement", 14: "step_14_trd_design",
    15: "step_15_development", 16: "step_16_rule_retrospective",
    17: "step_17_commit", 18: "step_18_merge",
}
CLI_SOURCE = '''import argparse
import json
from pathlib import Path

parser = argparse.ArgumentParser(description="本地便签：添加文本并查看已保存便签")
parser.add_argument("action", choices=["add", "list"])
parser.add_argument("text", nargs="?")
args = parser.parse_args()
if args.action == "add" and (args.text is None or not args.text.strip()):
    parser.error("添加便签需要非空文本")
path = Path(__file__).parent / ".data" / "notes.json"
notes = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
if args.action == "add":
    notes.append(args.text.strip()__NORMALIZE__)
    path.parent.mkdir(exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(notes, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)
print(json.dumps(notes, ensure_ascii=False))
'''
TEST_SOURCE = '''import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class NotesTests(unittest.TestCase):
    def test_case_and_chinese_survive_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / "notes.py"
            shutil.copyfile(Path(__file__).with_name("notes.py"), script)
            subprocess.run([sys.executable, str(script), "add", "Hello PCM 中文"], check=True, capture_output=True)
            result = subprocess.run([sys.executable, str(script), "list"], check=True, capture_output=True, text=True)
            self.assertEqual(json.loads(result.stdout), ["Hello PCM 中文"])
            rejected = subprocess.run([sys.executable, str(script), "add", "   "], capture_output=True)
            self.assertNotEqual(rejected.returncode, 0)
            result = subprocess.run([sys.executable, str(script), "list"], check=True, capture_output=True, text=True)
            self.assertEqual(json.loads(result.stdout), ["Hello PCM 中文"])
'''


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *args], stderr=subprocess.PIPE, text=True).strip()


def changed_paths_since(root: Path, base: str) -> list[str]:
    return [path for path in git(root, "diff", "--name-only", "-z", base, "HEAD").split("\0") if path]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare_fixture(run_dir: Path, scenario: str) -> dict:
    root = run_dir / "product"
    (root / "docs/backlog").mkdir(parents=True)
    (root / ".claude/agents").mkdir(parents=True)
    source_root = DEMO_ROOT.parent / ".claude"
    for skill in SKILLS:
        shutil.copytree(source_root / "skills" / skill, root / ".claude/skills" / skill)
    for name in ("dev.md", "reviewer.md"):
        shutil.copyfile(source_root / "agents" / name, root / ".claude/agents" / name)
    (root / "notes.py").write_text(CLI_SOURCE.replace("__NORMALIZE__", ".lower()" if scenario == "repair" else ""), encoding="utf-8")
    (root / "test_notes.py").write_text(TEST_SOURCE, encoding="utf-8")
    (root / "README.md").write_text(
        "# 本地便签反馈探针\n\n这是反馈工作流真实执行通道的隔离 CLI 产品 fixture，不是客户产品。"
        "来源已完成状态是测试输入；repair 场景有故意引入的大小写回归，用于验证真实修复。\n\n"
        "当前产品仅供单用户顺序执行添加非空文本、列出便签和重启后保留结果。输入去除首尾空白后须原样保存，"
        "包括英文大小写和中文。命令始终输出 JSON 字符串数组。空白输入报错且不修改已有数据。"
        "没有网络、图形界面、账号、删除、编辑、并发或外部资源要求。\n\n"
        "运行：`python3 notes.py add 'Hello PCM 中文'`、`python3 notes.py list`。"
        "验证：`python3 -m unittest -v`。数据位于 `.data/notes.json`，不存在时自动创建；"
        "本探针无需安装包或启动服务。可在本目录内准备非敏感测试数据，不操作其他产品。\n", encoding="utf-8")
    (root / "AGENTS.md").write_text(
        "# 工作规范\n\n使用中文。遵守当前调用任务限定的写入范围与 Git 职责。"
        "这是单仓 Python 标准库 CLI 工程，无 Web UI 和外部资源；按实际命令、退出码、JSON 结果和持久化验证，"
        "不要要求浏览器、截图、账号、数据库、容量工程或网络服务。"
        "开发可修改必要代码、测试及活动 TRD，独立审查使用已有 reviewer。"
        "领域任务不提交，只有明确提交任务才可精确提交，不合并或推送。"
        "测试输入只用非敏感数据；不删除 fixture 之外的文件。\n", encoding="utf-8")
    (root / "CLAUDE.md").write_text("@AGENTS.md\n", encoding="utf-8")
    (root / "plugins-lock.json").write_text('{"version":1,"plugins":[]}\n', encoding="utf-8")
    (root / ".gitignore").write_text(".data/\n.pcm/\n__pycache__/\n", encoding="utf-8")
    backlog = root / "docs/backlog/backlog.md"
    backlog.write_text(
        "# 正式需求\n\n## BR-001 保存与查看便签\n\n顺序 1，无前置依赖。"
        "单用户顺序添加非空文本并查看已有便签，去除首尾空白后保留大小写和中文，重启后结果不变。"
        "命令输出 JSON 字符串数组。空白文本返回非零且不改变已有数据。"
        "不涉及编辑、删除、网络、图形界面、多用户与并发。\n", encoding="utf-8")
    for args in (("init", "-b", "main"), ("config", "user.name", "反馈探针"),
                 ("config", "user.email", "feedback-probe@example.com")):
        git(root, *args)
    files = [str(path.relative_to(root)) for path in root.rglob("*") if path.is_file() and ".git" not in path.relative_to(root).parts]
    git(root, "add", "--", *files)
    git(root, "commit", "-m", "test: 建立隔离反馈现场")
    baseline = subprocess.run([sys.executable, "-m", "unittest", "-v"], cwd=root, capture_output=True, text=True)
    (run_dir / "baseline.log").write_text(baseline.stdout + baseline.stderr, encoding="utf-8")
    if (baseline.returncode == 0) != (scenario == "no-change"):
        raise RuntimeError("隔离 fixture 未呈现预期的原始行为")
    source = {
        "run_id": "synthetic-completed-quality-fixture", "workflow": "product_quality",
        "phase": "product_quality_iteration", "current_node": "quality:completed",
        "status": "success", "step": None, "current_step": None,
        "active_requirement": None, "requirement_cycle": None, "blocked": None, "error": None,
        "workspace": {"root": str(run_dir), "final_path": str(root)},
        "applicable_repositories": ["root"], "repositories": [{"name": "root", "path": str(root)}],
        "requirement_registry": {"schema_version": 1,
            "source": {"path": "docs/backlog/backlog.md", "sha256": digest(backlog)},
            "requirements": [{"id": "BR-001", "title": "保存与查看便签", "order": 1,
                "depends_on": [], "status": "completed", "completion": {"step": 18}}]},
    }
    write_json(run_dir / "source.json", source)
    original = run_dir / "original-feedback.md"
    original.write_text(
        "添加 Hello PCM 中文，再次打开查看变成 hello pcm 中文，大小写丢失。请修复为去除首尾空白后原样保留，"
        "已有空白输入拒绝和重启持久化行为仍需保留。这是本批必须解决的问题。\n"
        if scenario == "repair" else
        "我希望便签拒绝只有空格的输入，失败时不要改变之前保存的内容。请核验，若当前已经满足就不改代码。\n",
        encoding="utf-8")
    payload = {"source": str(original), "content": original.read_text(encoding="utf-8"), "attachments": [],
               "intent": "只处理上述现有 CLI 行为，不新增业务能力、依赖或外部服务；保持 JSON 数组输出。"}
    (run_dir / "feedback").mkdir()
    write_json(run_dir / "feedback/input.json", payload)
    state = workflow.new_state(source, source["run_id"], run_dir.name)
    write_state(run_dir, state)
    write_json(run_dir / "fixture.json", {
        "scenario": scenario, "base": git(root, "rev-parse", "HEAD"),
        "source_sha256": digest(run_dir / "source.json"), "input_sha256": digest(original),
        "kind": "feedback-cli-fixture",
    })
    return state


async def execute_current(run_dir: Path, state: dict, message_file: Path | None) -> dict:
    step = state.get("step")
    if step is None:
        message = prepare_node_resume_message(run_dir, state, state["current_node"], workflow.node_resume_keys(state), message_file) if message_file else None
        return await workflow.run_node(run_dir, state, resume_message=message)
    module = importlib.import_module(f"steps.{STEP_MODULES[step]}.step")
    kwargs = {}
    if message_file:
        kwargs["resume_message"] = prepare_resume_message(message_file, run_dir, state, step)
    result = module.run(run_dir, state, **kwargs)
    return await result if inspect.isawaitable(result) else result


async def probe(run_dir: Path, *, scenario: str, resume: bool, stop_after: str | None,
                message_file: Path | None) -> int:
    if resume:
        fixture = json.loads((run_dir / "fixture.json").read_text(encoding="utf-8"))
        state = read_state(run_dir)
        if fixture.get("kind") != "feedback-cli-fixture" or Path(state["workspace"]["final_path"]) != run_dir / "product":
            raise ValueError("只能恢复本探针创建的隔离产品")
    else:
        run_dir.mkdir(parents=True, exist_ok=False)
        (run_dir / "logs").mkdir()
        state = prepare_fixture(run_dir, scenario)
        fixture = json.loads((run_dir / "fixture.json").read_text(encoding="utf-8"))
    nodes = []
    try:
        while not workflow.is_completed(state):
            node = state["current_node"]
            step = state.get("step")
            nodes.append(node)
            print(f"执行：{node}", flush=True)
            timing = StepTiming()
            with timing.activate():
                if step is None:
                    timing.begin_attempt(node=node)
                else:
                    timing.begin_attempt(step=step)
                timing.bind_run(run_dir, existing=True)
                result = await execute_current(run_dir, state, message_file)
                message_file = None
                timing.observe_result(run_dir, result)
                timing.finish(returned=True)
            if node == stop_after:
                print(json.dumps({"status": "paused", "resume": str(run_dir), "node": state["current_node"]}, ensure_ascii=False))
                return 0
        root = Path(state["workspace"]["final_path"])
        verification = subprocess.run([sys.executable, "-m", "unittest", "-v"], cwd=root, capture_output=True, text=True)
        (run_dir / "verification.log").write_text(verification.stdout + verification.stderr, encoding="utf-8")
        sentinel = "FeedbackProbe ABC 中文"
        added = subprocess.run([sys.executable, "notes.py", "add", sentinel], cwd=root, capture_output=True, text=True, check=True)
        listed = subprocess.run([sys.executable, "notes.py", "list"], cwd=root, capture_output=True, text=True, check=True)
        rejected = subprocess.run([sys.executable, "notes.py", "add", "   "], cwd=root, capture_output=True)
        after_reject = subprocess.run([sys.executable, "notes.py", "list"], cwd=root, capture_output=True, text=True, check=True)
        batch = state["feedback"]["batch_requirement_ids"]
        changed = changed_paths_since(root, fixture["base"])
        checks = {
            "real_agent_sessions": len(state.get("claude_sessions", {})) >= 2,
            "source_unchanged": digest(run_dir / "source.json") == fixture["source_sha256"],
            "original_feedback_unchanged": digest(run_dir / "original-feedback.md") == fixture["input_sha256"],
            "tests_passed": verification.returncode == 0,
            "original_scenario_passed": json.loads(added.stdout)[-1] == sentinel and json.loads(listed.stdout)[-1] == sentinel,
            "failure_keeps_data": rejected.returncode != 0 and json.loads(after_reject.stdout) == json.loads(listed.stdout),
            "clean_main": git(root, "branch", "--show-current") == "main" and not git(root, "status", "--porcelain"),
            "feedback_document_committed": any(path.startswith("docs/feedback/") for path in changed),
            "batch_matches_scenario": bool(batch) == (fixture["scenario"] == "repair"),
            "document_only_when_no_work": fixture["scenario"] != "no-change" or all(path.startswith("docs/feedback/") for path in changed),
        }
        for identifier in batch:
            merged = json.loads((run_dir / f"steps/requirements/{identifier}/18.json").read_text(encoding="utf-8"))
            checks[f"merged_{identifier}"] = merged.get("status") == "success"
        outcome = "passed" if all(checks.values()) else "failed"
        write_json(run_dir / "probe-result.json", {
            "status": outcome, "checks": checks, "nodes": nodes,
            "completed_requirement_ids": batch, "scenario": fixture["scenario"],
            "scope": "隔离 CLI fixture 上的真实 Agent、负责人、文档收尾及适用需求开发链；来源完成状态是测试输入，不代表客户产品质量验收。锁与入口子进程接线另由自动化验证。",
        })
        print(json.dumps({"status": outcome, "result": str(run_dir / "probe-result.json")}, ensure_ascii=False))
        return 0 if outcome == "passed" else 1
    except Exception as error:
        if state.get("step") is None:
            workflow.record_failure(run_dir, state, error)
        else:
            required = getattr(error, "required_inputs", None)
            detail = safe_error_projection(error)
            if required:
                state.update(status="blocked", error=None, blocked={"reason": detail["message"], "required_inputs": required})
            else:
                state.update(status="failed", error=detail, blocked=None)
            write_state(run_dir, state)
        print(json.dumps({"status": state.get("status", "failed"), "error_type": type(error).__name__, "resume": str(run_dir)}, ensure_ascii=False))
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="在隔离 CLI fixture 验证真实反馈批次，不操作已有产品")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--run-dir", type=Path)
    source.add_argument("--resume", type=Path)
    parser.add_argument("--scenario", choices=["no-change", "repair"], default="repair")
    parser.add_argument("--timeout", type=int, default=3600)
    parser.add_argument("--stop-after", choices=[f"feedback:{name}" for name in workflow.NODES if name != "completed"])
    parser.add_argument("--resume-message-file", type=Path)
    args = parser.parse_args()
    if args.resume_message_file and not args.resume:
        parser.error("恢复消息只用于已有探针")
    target = args.resume or args.run_dir or DEMO_ROOT / "runs" / datetime.now(timezone.utc).strftime("feedback-channel-%Y%m%dT%H%M%SZ")
    try:
        return asyncio.run(asyncio.wait_for(probe(target.resolve(), scenario=args.scenario, resume=args.resume is not None,
            stop_after=args.stop_after, message_file=args.resume_message_file), timeout=args.timeout))
    except TimeoutError:
        print(json.dumps({"status": "interrupted", "reason": "probe_timeout", "resume": str(target.resolve())}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
