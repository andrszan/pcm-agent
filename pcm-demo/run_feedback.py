from __future__ import annotations

import argparse
import asyncio
import json
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
from common.files import write_json
from common.frontend_scope import ensure_frontend_capabilities
from common.state import create_run_dir, read_state, write_state
from common.timing import print_timing_summary
from config import load_settings
from model_policy import load_model_policy, _model_policy_snapshot, _model_policy_table
from run_step import _RETRY_REQUESTED_EXIT_CODE, _retry_locked, safe_error_projection

FEEDBACK_NODES = tuple(f"feedback:{name}" for name in (
    "prepare", "triage", "route", "pool", "register", "select_requirement", "complete",
))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="附着既有产品，创建或恢复独立人工反馈批次")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--source-run")
    source.add_argument("--resume")
    parser.add_argument("--run-id")
    parser.add_argument("--feedback-file", type=Path)
    parser.add_argument("--attachment", type=Path, action="append", default=[])
    parser.add_argument("--intent-file", type=Path)
    parser.add_argument("--node", choices=FEEDBACK_NODES)
    parser.add_argument("--resume-message-file", type=Path)
    parser.add_argument("--coordination-locks", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.source_run and (not args.run_id or args.feedback_file is None):
        parser.error("新反馈运行必须指定 --run-id 和 --feedback-file")
    if args.resume and (args.run_id or args.feedback_file or args.attachment or args.intent_file):
        parser.error("--resume 不能提供 --run-id 或初次反馈输入")
    if (args.node or args.resume_message_file) and not args.resume:
        parser.error("--node 和 --resume-message-file 只能用于 --resume")
    return args


def _workflow():
    from feedback import workflow
    return workflow


def _read_text(path: Path, label: str) -> str:
    try:
        if not path.is_file():
            raise ValueError()
        # 保留换行及首尾空白，不让原始正文出现在解码异常输出中。
        return path.read_bytes().decode("utf-8")
    except (OSError, UnicodeError, ValueError):
        raise ValueError(f"{label}必须是可读的 UTF-8 普通文件") from None


def _initial_input(args) -> dict[str, Any]:
    source = args.feedback_file.resolve()
    content = _read_text(source, "反馈文件")
    if not content.strip():
        raise ValueError("反馈正文不能为空白")
    attachments = []
    for path in args.attachment:
        path = path.resolve()
        try:
            if not path.is_file():
                raise ValueError()
            with path.open("rb") as handle:
                handle.read(1)
        except (OSError, ValueError):
            raise ValueError("反馈附件必须是可读的普通文件") from None
        attachments.append(str(path))
    intent_source = args.intent_file.resolve() if args.intent_file else None
    intent = _read_text(intent_source, "目标说明文件") if intent_source else ""
    return {"source": str(source), "content": content, "attachments": attachments, "intent": intent,
            "intent_source": str(intent_source) if intent_source else None}


def _saved_input(run_dir: Path) -> dict[str, Any]:
    try:
        data = json.loads((run_dir / "feedback/input.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        raise ValueError("本批保存的反馈输入缺失或不可读，不能恢复空批次") from None
    if (
        not isinstance(data, dict)
        or set(data) not in ({"source", "content", "attachments", "intent"},
                             {"source", "content", "attachments", "intent", "intent_source"})
        or (data.get("intent_source") is not None and (
            not isinstance(data["intent_source"], str) or not Path(data["intent_source"]).is_absolute()
        ))
        or not isinstance(data["source"], str) or not Path(data["source"]).is_absolute()
        or not isinstance(data["content"], str) or not data["content"].strip()
        or not isinstance(data["intent"], str)
        or not isinstance(data["attachments"], list)
        or any(not isinstance(path, str) or not Path(path).is_absolute() for path in data["attachments"])
    ):
        raise ValueError("本批保存的反馈输入无效，不能恢复空批次")
    return data


def _require_feedback(state: dict[str, Any], run_id: str) -> None:
    if (
        state.get("workflow") != "product_feedback"
        or state.get("phase") != "product_feedback_iteration"
        or state.get("run_id") != run_id
    ):
        raise RuntimeError("运行记录不是指定的产品反馈运行")


def _numeric_step(state: dict[str, Any]) -> int | None:
    node = state.get("current_node")
    if node == "feedback:select_requirement":
        position = (state.get("step"), state.get("current_step"))
        if position == (13, 13):
            return 13
        if position != (None, None):
            raise RuntimeError("反馈需求选择位置与数字步骤不一致")
        return None
    if isinstance(node, str) and node.startswith("requirement:"):
        step = run_all.step_for_state(Path(), state)
        if step not in range(14, 19):
            raise RuntimeError("反馈需求步骤无效")
        return step
    if node not in FEEDBACK_NODES and node != "feedback:completed":
        raise RuntimeError(f"未知反馈节点：{node}")
    return None


def _execute_node(args, locks, timing) -> int:
    workflow = _workflow()
    run_dir = run_all.run_dir_for(args.resume)
    state = read_state(run_dir)
    if state.get("current_node") != args.node:
        raise RuntimeError("--node 只能执行当前反馈节点")
    node = args.node
    timing.begin_attempt(node=node)
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
            run_dir, f"{node.replace(':', '-')}-error.json",
            source="run_feedback", kind="generic", error=error,
            context={"node": node},
        )
        result = workflow.record_failure(run_dir, state, error)
        if result.get("status") == "success":
            # 成功产物受保护，但状态推进失败不能报告成功。
            result = {"status": "failed", "error": safe_error_projection(error)}
        retry_requested = bool(getattr(error, "retry_requested", False))
    timing.observe_result(run_dir, result)
    if result.get("status") == "success":
        return 0
    detail = result.get("blocked") or result.get("error") or {}
    message = detail.get("reason") or detail.get("message") or result.get("summary", "")
    print(f"反馈节点 {node} {result.get('status')}：{message}\n"
          f"详细结果：{workflow.node_result_path(run_dir, state)}", file=sys.stderr)
    diagnostic_path = diagnostic_path or detail.get("diagnostic_path")
    if diagnostic_path:
        print(f"诊断：{diagnostic_path}", file=sys.stderr)
    return _RETRY_REQUESTED_EXIT_CODE if retry_requested else 1


def _drive(args, run_id, run_dir, locks, snapshot) -> int:
    workflow = _workflow()
    while True:
        state = read_state(run_dir)
        _require_feedback(state, run_id)
        if workflow.is_completed(state):
            print(f"反馈批次已完成：{run_dir / 'state.json'}")
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
            raise RuntimeError("节点成功但未推进反馈运行状态")


def _reject_unfinished_feedback(product_key: str) -> None:
    """调用方持有产品锁；只读既有状态，避免另开批次绕过未完成范围。"""
    workflow = _workflow()
    for path in sorted(run_all.RUNS_DIR.iterdir()):
        if path.name.startswith(".") or not (path / "state.json").is_file():
            continue
        previous = read_state(path)
        coordination = previous.get("coordination")
        if (
            previous.get("workflow") == "product_feedback"
            and isinstance(coordination, dict)
            and coordination.get("product_key") == product_key
            and not workflow.is_completed(previous)
        ):
            command = shlex.join([sys.executable, str(Path(__file__).resolve()), "--resume", path.name])
            raise RuntimeError(f"同一产品尚有未完成反馈批次 {path.name}，请恢复原运行：{command}")


def _locked(args, run_id, run_dir, locks, snapshot) -> int:
    workflow = _workflow()
    if args.source_run:
        if run_dir.exists():
            raise ValueError(f"运行目录已存在，拒绝覆盖：{run_dir}")
        batch_input = _initial_input(args)
        source = read_state(run_all.run_dir_for(args.source_run))
        if source.get("run_id") != args.source_run:
            raise ValueError("来源运行身份与运行目录不一致")
        state = workflow.new_state(source, args.source_run, run_id)
        if "frontend" in state["applicable_repositories"]:
            try:
                ensure_frontend_capabilities(Path(state["workspace"]["final_path"]))
            except (OSError, RuntimeError, ValueError) as error:
                print(f"反馈运行 failed：{safe_error_projection(error)['message']}", file=sys.stderr)
                return 1
        source_coordination = source.get("coordination")
        if not isinstance(source_coordination, dict):
            raise ValueError("反馈来源缺少产品协调身份")
        state["coordination"] = attach_product(run_all.COORDINATION_ROOT, run_id, source, locks, source=True)
        _reject_unfinished_feedback(state["coordination"]["product_key"])
        create_run_dir(run_all.RUNS_DIR, run_id)
        try:
            (run_dir / "feedback").mkdir()
            write_json(run_dir / "feedback/input.json", batch_input)
            # 输入完整落盘后才发布批次身份；此前中断的目录可保留并换 ID 重建。
            write_state(run_dir, state)
        except (OSError, RuntimeError, ValueError) as error:
            print(f"反馈运行准备失败：{safe_error_projection(error)['message']}", file=sys.stderr)
            if (run_dir / "state.json").is_file():
                workflow.record_failure(run_dir, state, error)
                print(f"详细结果：{workflow.node_result_path(run_dir, state)}", file=sys.stderr)
            else:
                print(f"批次尚未开始产品工作，初始化目录已保留：{run_dir}\n"
                      "请解除读写问题后使用新的 --run-id 重新创建批次。", file=sys.stderr)
            return 1
    else:
        state = read_state(run_dir)
        _require_feedback(state, run_id)
        if args.node is not None and state.get("current_node") != args.node:
            raise ValueError("--node 只能执行当前反馈节点")
        _saved_input(run_dir)
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
        required_tasks = {"feedback_prepare", "feedback_triage", "feedback_route", "feedback_pool"}
        if required_tasks - set(policy.steps):
            raise ValueError("当前模型策略缺少反馈任务，请使用完整策略启动反馈运行")
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
                if code and (run_dir / "state.json").is_file():
                    print(f"恢复命令：{shlex.join([sys.executable, str(Path(__file__).resolve()), '--resume', run_id])}", file=sys.stderr)
                return code
            finally:
                if run_dir.is_dir():
                    print_timing_summary(run_dir)
    except (OSError, RuntimeError, ValueError) as error:
        print(f"反馈运行停止：{safe_error_projection(error)['message']}", file=sys.stderr)
        return 2


def main(argv: list[str] | None = None) -> int:
    return orchestrate(parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
