from __future__ import annotations

import argparse
import asyncio
import shlex
import sys
from pathlib import Path
from typing import Any

import run_all
from common.agent_decision_loop import (
    prepare_node_resume_message,
    validate_node_resume_target,
    validate_resume_target,
)
from common.coordination import (
    acquire_execution_locks,
    adopt_execution_locks,
    attach_product,
    inherited_lock_argument,
)
from common.error_diagnostics import write_diagnostic
from common.state import create_run_dir, read_state, write_state
from common.timing import print_timing_summary
from config import load_settings
from model_policy import load_model_policy, _model_policy_snapshot, _model_policy_table
from run_step import _RETRY_REQUESTED_EXIT_CODE, _retry_locked, safe_error_projection

QUALITY_NODES = tuple(f"quality:{name}" for name in (
    "prepare", "audit", "route", "pool", "register", "select_requirement", "complete",
))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="附着既有产品，创建或恢复独立质量运行")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--source-run")
    source.add_argument("--resume")
    parser.add_argument("--run-id")
    parser.add_argument("--node", choices=QUALITY_NODES)
    parser.add_argument("--resume-message-file", type=Path)
    parser.add_argument("--coordination-locks", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.source_run and not args.run_id:
        parser.error("新质量运行必须指定 --run-id")
    if args.resume and args.run_id:
        parser.error("--resume 不能与 --run-id 同时使用")
    if (args.node or args.resume_message_file) and not args.resume:
        parser.error("--node 和 --resume-message-file 只能用于 --resume")
    return args


def _workflow():
    from quality import workflow
    return workflow


def _require_quality(state: dict[str, Any], run_id: str) -> None:
    if (
        state.get("workflow") != "product_quality"
        or state.get("phase") != "product_quality_iteration"
        or state.get("run_id") != run_id
    ):
        raise RuntimeError("运行记录不是指定的产品质量运行")


def _numeric_step(state: dict[str, Any]) -> int | None:
    node = state.get("current_node")
    if node == "quality:select_requirement":
        position = (state.get("step"), state.get("current_step"))
        if position == (13, 13):
            return 13
        if position != (None, None):
            raise RuntimeError("质量需求选择位置与数字步骤不一致")
        return None
    if isinstance(node, str) and node.startswith("requirement:"):
        step = run_all.step_for_state(Path(), state)
        if step not in range(14, 19):
            raise RuntimeError("质量需求步骤无效")
        return step
    if node not in QUALITY_NODES and node != "quality:completed":
        raise RuntimeError(f"未知质量节点：{node}")
    return None


def _execute_node(args, locks, timing) -> int:
    workflow = _workflow()
    run_dir = run_all.run_dir_for(args.resume)
    state = read_state(run_dir)
    if state.get("current_node") != args.node:
        raise RuntimeError("--node 只能执行当前质量节点")
    node = args.node
    round_number = state["quality"]["round"] if node in {
        "quality:audit", "quality:route", "quality:pool", "quality:register",
        "quality:select_requirement",
    } else None
    timing.begin_attempt(node=node, round_number=round_number)
    timing.bind_run(run_dir, existing=True)
    timing.announce()
    message = getattr(args, "resume_message", None)
    retry_requested = False
    diagnostic_path = None
    try:
        result = asyncio.run(workflow.run_node(run_dir, state, resume_message=message))
        if message is not None and not message.consumed:
            raise RuntimeError("负责人消息未被目标原对话消费")
    except Exception as error:
        diagnostic_path = write_diagnostic(
            run_dir, f"{node.replace(':', '-')}-{round_number or 0}-error.json",
            source="run_quality", kind="generic", error=error,
            context={"node": node, "round": round_number},
        )
        result = workflow.record_failure(run_dir, state, error)
        if result.get("status") == "success":
            # 已落盘的成功结果受保护，但本次状态推进异常不能报告成功。
            result = {"status": "failed", "error": safe_error_projection(error)}
        retry_requested = bool(getattr(error, "retry_requested", False))
    timing.observe_result(run_dir, result)
    if result.get("status") == "success":
        return 0
    detail = result.get("blocked") or result.get("error") or {}
    message = detail.get("reason") or detail.get("message") or result.get("summary", "")
    print(f"质量节点 {node} {result.get('status')}：{message}\n"
          f"详细结果：{workflow.node_result_path(run_dir, state)}", file=sys.stderr)
    diagnostic_path = diagnostic_path or detail.get("diagnostic_path")
    if diagnostic_path:
        print(f"诊断：{diagnostic_path}", file=sys.stderr)
    return _RETRY_REQUESTED_EXIT_CODE if retry_requested else 1


def _drive(args, run_id, run_dir, locks, snapshot) -> int:
    workflow = _workflow()
    while True:
        state = read_state(run_dir)
        _require_quality(state, run_id)
        if workflow.is_completed(state):
            print(f"质量周期已完成：{run_dir / 'state.json'}")
            return 0
        step = _numeric_step(state)
        if step is not None:
            command = [sys.executable, str(run_all.RUN_STEP_PATH), "--step", str(step), "--run-id", run_id]
        else:
            command = [sys.executable, str(Path(__file__).resolve()), "--resume", run_id,
                       "--node", state["current_node"]]
        if args.resume_message_file is not None:
            command.extend(["--resume-message-file", str(args.resume_message_file.resolve())])
        command.extend(["--coordination-locks", inherited_lock_argument(locks)])
        code = run_all.run_child(command, locks.file_descriptors(), run_all._child_environment(snapshot))
        if code:
            return code
        args.resume_message_file = None
        if read_state(run_dir) == state:
            raise RuntimeError("节点成功但未推进质量运行状态")


def _locked(args, run_id, run_dir, locks, snapshot) -> int:
    workflow = _workflow()
    if args.source_run:
        if run_dir.exists():
            raise ValueError(f"运行目录已存在，拒绝覆盖：{run_dir}")
        source = read_state(run_all.run_dir_for(args.source_run))
        if source.get("run_id") != args.source_run:
            raise ValueError("来源运行身份与运行目录不一致")
        state = workflow.new_state(source, args.source_run, run_id)
        source_coordination = source.get("coordination")
        if not isinstance(source_coordination, dict):
            raise ValueError("质量来源缺少产品协调身份")
        state["coordination"] = {
            **source_coordination, "execution_run_id": run_id, "claim_phase": "attached",
            "owner_run_id": source_coordination.get("owner_run_id")
            if source_coordination.get("claim_phase") == "attached"
            else source_coordination.get("execution_run_id"),
        }
        create_run_dir(run_all.RUNS_DIR, run_id)
        write_state(run_dir, state)
        try:
            state["coordination"] = attach_product(run_all.COORDINATION_ROOT, run_id, source, locks, source=True)
        except (OSError, RuntimeError, ValueError) as error:
            workflow.record_failure(run_dir, state, error)
            print(f"质量运行附着失败：{safe_error_projection(error)['message']}\n"
                  f"详细结果：{workflow.node_result_path(run_dir, state)}", file=sys.stderr)
            return 1
        write_state(run_dir, state)
    else:
        state = read_state(run_dir)
        _require_quality(state, run_id)
        if args.node is not None and state.get("current_node") != args.node:
            raise ValueError("--node 只能执行当前质量节点")
        attach_product(run_all.COORDINATION_ROOT, run_id, state, locks)
    if args.resume_message_file is not None:
        step = _numeric_step(state)
        if step is not None:
            validate_resume_target(run_dir, state, step)
        else:
            keys = workflow.node_resume_keys(state)
            if args.node:
                args.resume_message = prepare_node_resume_message(
                    run_dir, state, args.node, keys, args.resume_message_file,
                )
            else:
                validate_node_resume_target(run_dir, state, state["current_node"], keys)
    if args.node:
        step = _numeric_step(state)
        if step is not None:
            command = [sys.executable, str(run_all.RUN_STEP_PATH), "--step", str(step),
                       "--run-id", run_id, "--coordination-locks", inherited_lock_argument(locks)]
            return run_all.run_child(command, locks.file_descriptors(), run_all._child_environment(snapshot))
        return _retry_locked(args, locks, execute=_execute_node)
    return _drive(args, run_id, run_dir, locks, snapshot)


def orchestrate(args: argparse.Namespace) -> int:
    run_id = args.resume or args.run_id
    try:
        run_dir = run_all.run_dir_for(run_id)
        policy = load_model_policy()
        snapshot = _model_policy_snapshot(policy)
        print(_model_policy_table(policy))
        maximum = load_settings().pcm_max_concurrent_projects
        locks = (
            adopt_execution_locks(run_all.COORDINATION_ROOT, run_id, args.coordination_locks, maximum)
            if args.coordination_locks else
            acquire_execution_locks(run_all.COORDINATION_ROOT, run_id, maximum)
        )
        with locks:
            try:
                code = _locked(args, run_id, run_dir, locks, snapshot)
                if code:
                    print(f"恢复命令：{shlex.join([sys.executable, str(Path(__file__).resolve()), '--resume', run_id])}", file=sys.stderr)
                return code
            finally:
                if run_dir.is_dir():
                    print_timing_summary(run_dir)
    except (OSError, RuntimeError, ValueError) as error:
        print(f"质量运行停止：{error}", file=sys.stderr)
        return 2


def main(argv: list[str] | None = None) -> int:
    return orchestrate(parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
