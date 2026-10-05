from __future__ import annotations

import argparse
import asyncio
import copy
import json
import shlex
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from common.agent_decision_loop import (
    AgentDecisionLoopSpec,
    latest_agent_reply,
    prepare_node_resume_message,
    run_agent_decision_loop,
)
from common.coordination import (
    acquire_execution_locks,
    acquire_product_lock,
    attach_product,
    coordination_root,
    get_product,
    product_key,
)
from common.decision import render_decision_system_prompt
from common.error_diagnostics import redact_text, write_diagnostic
from common.state import create_run_dir, read_state, write_state
from config import load_settings
from model_policy import get_agent_profile
from quality.git import check_operations, clean_repository, git, repositories, workspace


DEMO_ROOT = Path(__file__).resolve().parent
RUNS_DIR = DEMO_ROOT / "runs"
COORDINATION_ROOT = coordination_root(DEMO_ROOT)
SKILL_ROOT = DEMO_ROOT.parent / ".claude" / "skills" / "code-comments"
WORKFLOW = "code_comments"
NODE = "comments:maintain"
COMPLETED_NODE = "comments:completed"
KEY = "code_comments"
RESPONSIBILITY = """完成当前授权仓库的全量注释检查与必要补充、修正，保留清晰代码和有效注释。
准确性、必要性和维护价值优先，不追求注释率，不强制每个文件或方法产生修改。
Agent 应基于实现、调用方、测试及必要的有效资料理解约束，不编造设计原因或行为保障。
任务仅限注释维护，不批准业务修复、重构、修改检查规则、Git 提交、分支操作或推送。
覆盖完整、必要说明准确、变更经过复核且适用验证完成时可以结束，允许无代码变更。
信任已报告的有效证据，不要求逐项复述或重复执行已完成检查；真实覆盖或验证缺口不能冒充完成。
发现无关注释任务的既有 Bug 或无法证明的历史动机时可以准确交接，不扩大本次任务。
"""


def run_dir_for(run_id: str) -> Path:
    if not run_id or run_id in {".", ".."} or Path(run_id).name != run_id:
        raise ValueError("运行 ID 必须是单段非空名称")
    path = RUNS_DIR / run_id
    if path.is_symlink() or path.resolve().parent != RUNS_DIR.resolve():
        raise ValueError("运行目录不能是符号链接或位于 runs 之外")
    return path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="手动维护 PCM 产品代码注释，不执行开发流程或提交")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--workspace", type=Path, help="已登记产品工作区的绝对路径")
    source.add_argument("--resume", help="恢复原注释运行")
    parser.add_argument("--run-id", help="新运行标识，默认按当前时间生成")
    parser.add_argument("--resume-message-file", type=Path, help="向可恢复的原 Agent 对话补充说明")
    args = parser.parse_args(argv)
    if args.resume and args.run_id:
        parser.error("--resume 不能与 --run-id 同时使用")
    if args.resume_message_file and not args.resume:
        parser.error("--resume-message-file 只能用于 --resume")
    return args


def initial_prompt(state: dict[str, Any]) -> str:
    inputs = json.dumps(
        {"工作区": str(workspace(state)), "仓库": [
            {"名称": name, "路径": str(path)} for name, path in repositories(state)
        ]}, ensure_ascii=False, indent=2,
    )
    skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    conventions = (SKILL_ROOT / "references" / "language-conventions.md").read_text(encoding="utf-8")
    if not skill.strip() or not conventions.strip():
        raise ValueError("注释维护能力或语言约定为空")
    return (
        "对以下项目执行一次完整的代码注释维护，直接完成必要编辑、复核和适用验证。\n"
        "范围是所列仓库内自行维护的代码，包括适用的测试、迁移和脚本；"
        "项目说明、规则和设计资料只读。保持源码行为、类型、配置、依赖、测试断言与特殊工具指令不变。\n"
        "先统一注释标准，再按内聚模块有限并发；允许跨模块读取，同一文件只能有一个写入者。"
        "小项目可串行，整合验证不重复派发。不要为凑注释修改清晰代码。\n"
        "当前从干净的 main 开始；不暂存、提交、切分支、合并或推送，不新增或删除受跟踪文件。"
        "中断后先读取当前 diff 与已有对话，只继续未完成工作；无法确认归属的变化保留并说明。\n"
        "以下是本次直接提供的能力正文及其语言参考，无需安装、复制或更新目标项目的 Skill。"
        "目标项目已有规则仍适用；只按本次注释任务工作，不启动其它开发流程。\n\n"
        f"项目范围：\n{inputs}\n\n"
        f"能力正文：\n{skill}\n\n语言参考：\n{conventions}"
    )


def load_product(path: Path, run_id: str, locks) -> dict[str, Any]:
    if not path.is_absolute() or path.is_symlink() or not path.is_dir():
        raise ValueError("产品工作区必须是绝对路径的真实目录")
    key, canonical = product_key(path)
    locks.product = locks.stack.enter_context(
        acquire_product_lock(COORDINATION_ROOT, run_id, key, canonical)
    )
    record = get_product(COORDINATION_ROOT, key)
    owner = record.get("owner_run_id")
    if not isinstance(owner, str):
        raise RuntimeError("产品创建 run 归属无效")
    source = read_state(run_dir_for(owner))
    if source.get("run_id") != owner or source.get("workspace", {}).get("final_path") != str(canonical):
        raise RuntimeError("产品创建记录与工作区不一致")
    coordination = attach_product(COORDINATION_ROOT, run_id, source, locks, source=True)
    state = {
        "run_id": run_id, "workflow": WORKFLOW, "current_node": NODE,
        "status": "running", "blocked": None, "error": None,
        "workspace": copy.deepcopy(source["workspace"]),
        "applicable_repositories": copy.deepcopy(source.get("applicable_repositories")),
        "repositories": copy.deepcopy(source.get("repositories")),
        "coordination": coordination,
    }
    state["entry_versions"] = {
        name: clean_repository(repo, "main") for name, repo in repositories(state)
    }
    state["initial_prompt"] = initial_prompt(state)
    return state


def check_boundary(state: dict[str, Any]) -> None:
    repos = repositories(state)
    baseline = state.get("entry_versions")
    if not isinstance(baseline, dict) or set(baseline) != {name for name, _ in repos}:
        raise RuntimeError("注释运行缺少完整仓库基线")
    for name, repo in repos:
        if repo.is_symlink() or git(repo, "rev-parse", "--show-toplevel") != str(repo):
            raise RuntimeError(f"仓库 {name} 不再是原独立仓库")
        check_operations(repo)
        if git(repo, "branch", "--show-current") != "main" or git(repo, "rev-parse", "HEAD") != baseline[name]:
            raise RuntimeError(f"仓库 {name} 的分支或提交已改变；保留现场，不自动恢复 Git")
        if git(repo, "diff", "--cached", "--name-only", "-z"):
            raise RuntimeError(f"仓库 {name} 出现暂存变更；保留现场，不自动取消暂存")
        if git(repo, "ls-files", "--others", "--exclude-standard", "-z"):
            raise RuntimeError(f"仓库 {name} 出现未跟踪文件；保留现场，请先核对归属")
        if git(repo, "diff", "--summary"):
            raise RuntimeError(f"仓库 {name} 出现文件新增、删除、移动或权限变化；注释任务不能改变文件结构")


def require_comments(state: dict[str, Any], run_id: str) -> None:
    if (
        state.get("workflow") != WORKFLOW or state.get("run_id") != run_id
        or state.get("current_node") not in {NODE, COMPLETED_NODE}
        or state.get("status") not in {"running", "success", "failed", "blocked"}
        or not isinstance(state.get("initial_prompt"), str) or not state["initial_prompt"].strip()
        or (state.get("current_node") == COMPLETED_NODE and state.get("status") != "success")
    ):
        raise RuntimeError("运行记录不是合法的注释维护现场")


def loop_spec(state: dict[str, Any]) -> AgentDecisionLoopSpec:
    return AgentDecisionLoopSpec(
        key=KEY, state_key=KEY, skill_name=None, max_decision_rounds=32, max_turns=9999,
        task="development",
        decision_system_prompt=render_decision_system_prompt(
            RESPONSIBILITY, {"当前任务": state["initial_prompt"]},
        ),
    )


async def maintain(run_dir: Path, state: dict[str, Any], message=None) -> None:
    spec = loop_spec(state)

    def verify() -> None:
        check_boundary(state)

    decision = await run_agent_decision_loop(
        run_dir, state, workspace(state), spec, state["initial_prompt"], verify,
        resume_message=message,
    )
    if message is not None and not message.consumed:
        raise RuntimeError("负责人消息未被目标原对话消费")
    if decision.verdict == "blocked":
        state.update(status="blocked", blocked={
            "reason": decision.reason, "required_inputs": decision.required_inputs,
        }, error=None)
    elif decision.verdict == "completed":
        check_boundary(state)
        state.update(
            status="success", current_node=COMPLETED_NODE, blocked=None, error=None,
            summary=latest_agent_reply(run_dir, state, spec),
        )
    else:
        raise RuntimeError("注释维护未完成")
    write_state(run_dir, state)


def execute(args: argparse.Namespace, run_id: str, run_dir: Path, locks) -> int:
    if args.workspace is not None:
        if run_dir.exists():
            raise ValueError("运行目录已存在；使用 --resume 恢复，不覆盖已有记录")
        state = load_product(args.workspace, run_id, locks)
        create_run_dir(RUNS_DIR, run_id)
        write_state(run_dir, state)
    else:
        state = read_state(run_dir)
        require_comments(state, run_id)
        if state["current_node"] == COMPLETED_NODE:
            if args.resume_message_file:
                raise ValueError("已完成的注释运行不能追加恢复消息")
            print("本轮注释维护已完成，返回原结果，不重新检查或修改产品。")
            print(state.get("summary", ""))
            return 0
        attach_product(COORDINATION_ROOT, run_id, state, locks)
        check_boundary(state)
    message = None
    if args.resume_message_file:
        message = prepare_node_resume_message(
            run_dir, state, NODE, (KEY,), args.resume_message_file,
        )
    if state["status"] != "blocked":
        state.update(status="running", error=None, blocked=None)
        write_state(run_dir, state)
    try:
        asyncio.run(maintain(run_dir, state, message))
    except Exception as error:
        diagnostic = write_diagnostic(
            run_dir, "comments-error.json", source="run_comments", kind="generic", error=error,
        )
        state.update(status="failed", error={
            "type": type(error).__name__, "message": redact_text(str(error)),
            "diagnostic_path": str(diagnostic),
        }, blocked=None)
        write_state(run_dir, state)
        raise
    if state["status"] == "blocked":
        print(f"注释维护阻塞：{redact_text(state['blocked']['reason'])}", file=sys.stderr)
        return 2
    print(state.get("summary", ""))
    print(f"注释维护完成：{run_dir / 'state.json'}；产品变更尚未提交。")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    run_id = args.resume or args.run_id or datetime.now().strftime("comments-%Y%m%d-%H%M%S")
    resume_command = shlex.join(["uv", "run", "python", "run_comments.py", "--resume", run_id])
    run_dir = None
    try:
        run_dir = run_dir_for(run_id)
        profile = get_agent_profile("development")
        print(f"注释维护模型：{profile.model}，effort={profile.effort}（复用 development 配置）")
        with acquire_execution_locks(
            COORDINATION_ROOT, run_id, load_settings().pcm_max_concurrent_projects,
        ) as locks:
            code = execute(args, run_id, run_dir, locks)
        if code and run_dir.is_dir():
            print(f"恢复命令：{resume_command}", file=sys.stderr)
        return code
    except (OSError, RuntimeError, ValueError) as error:
        print(f"注释维护未完成：{redact_text(str(error))}", file=sys.stderr)
        if run_dir is not None and run_dir.is_dir():
            print(f"恢复命令：{resume_command}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
