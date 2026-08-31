from __future__ import annotations

import argparse
import fcntl
import os
import shlex
import signal
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from secrets import token_hex
from typing import Any, TextIO

from common.state import read_state, step_result_status
from steps.step_13_select_requirement.step import registry_handoff

DEMO_ROOT = Path(__file__).resolve().parent
RUNS_DIR = DEMO_ROOT / "runs"
RUN_STEP_PATH = DEMO_ROOT / "run_step.py"
LOCK_PATH = RUNS_DIR / ".run_all.lock"

NODE_TO_STEP = {
    "project:00_product_draft": 0,
    "project:01_create_workspace": 1,
    "project:02_intake": 2,
    "project:03_foundation_selection": 3,
    "project:04_assemble_foundation": 4,
    "project:05_verify_readiness": 5,
    "project:06_bootstrap_foundation": 6,
    "project:07_solution_design": 7,
    "project:08_initialize_repositories": 8,
    "project:09_engineering_architecture": 9,
    "project:10_ui_ux_framework": 10,
    "project:11_requirement_breakdown": 11,
    "phase_1:initialize_requirement_registry": 12,
    "phase_1:select_requirement": 13,
    "requirement:14_trd_design": 14,
    "requirement:15_development": 15,
    "requirement:16_rule_retrospective": 16,
    "requirement:17_commit": 17,
    "requirement:18_merge": 18,
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="顺序运行 PCM Demo 当前已实现的阶段一流程")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--product-draft", type=Path)
    source.add_argument("--resume")
    parser.add_argument("--run-id")
    parser.add_argument("--workspace-root", type=Path)
    parser.add_argument("--catalog-path", type=Path)
    args = parser.parse_args(argv)
    if args.resume and args.run_id:
        parser.error("--resume 不能与 --run-id 同时使用")
    return args


def new_run_id() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}-{token_hex(3)}"


def run_dir_for(run_id: str) -> Path:
    if Path(run_id).name != run_id or run_id in {"", ".", ".."}:
        raise ValueError(f"无效运行 ID：{run_id}")
    resolved_runs = RUNS_DIR.resolve()
    run_dir = (resolved_runs / run_id).resolve()
    try:
        run_dir.relative_to(resolved_runs)
    except ValueError as error:
        raise ValueError(f"无效运行 ID：{run_id}") from error
    return run_dir


def acquire_global_lock() -> TextIO:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    handle = LOCK_PATH.open("a+", encoding="utf-8")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        raise RuntimeError("已有 PCM 完整编排正在运行") from None
    except OSError:
        handle.close()
        raise
    return handle


def _legacy_step(run_dir: Path, state: dict[str, Any]) -> int:
    current_step = state.get("current_step")
    status = state.get("status")
    if type(current_step) is not int or current_step not in {0, 1, 2, 3}:
        raise RuntimeError("旧运行状态缺少可恢复的早期步骤位置")
    if status in {"running", "failed", "blocked"}:
        return current_step
    if status != "success" or current_step == 3:
        raise RuntimeError("旧运行状态的早期步骤位置不符合约定")
    if step_result_status(run_dir, current_step) != "success":
        raise RuntimeError(f"旧运行状态缺少第 {current_step} 步成功结果")
    return current_step + 1


def step_for_state(run_dir: Path, state: dict[str, Any]) -> int:
    node = state.get("current_node")
    if node is None:
        return _legacy_step(run_dir, state)
    if not isinstance(node, str) or node not in NODE_TO_STEP:
        raise RuntimeError(f"当前流程节点尚未实现：{node}")
    expected = NODE_TO_STEP[node]
    if state.get("step") != expected or state.get("current_step") != expected:
        raise RuntimeError("运行状态的 step、current_step 与 current_node 不一致")
    return expected


def phase_one_completed(state: dict[str, Any]) -> bool:
    if (
        state.get("status") != "success"
        or state.get("phase") != "phase_1_requirement_development"
        or (state.get("step"), state.get("current_step"), state.get("current_node"))
        != (13, 13, "phase_1:select_requirement")
        or state.get("active_requirement") is not None
        or state.get("requirement_cycle") is not None
    ):
        return False
    try:
        _catalog, requirements = registry_handoff(state)
    except RuntimeError:
        return False
    if not requirements:
        return False
    return all(
        isinstance(requirement, dict)
        and requirement.get("status") == "completed"
        and requirement.get("completion") == {"step": 18}
        for requirement in requirements
    )


def build_step_command(
    step: int,
    run_id: str,
    args: argparse.Namespace,
    state: dict[str, Any] | None,
) -> list[str]:
    command = [
        sys.executable,
        str(RUN_STEP_PATH),
        "--step",
        str(step),
        "--run-id",
        run_id,
    ]
    if step == 0:
        draft = args.product_draft
        if draft is None and state is not None:
            source_path = state.get("input", {}).get("source_path")
            if isinstance(source_path, str) and source_path:
                draft = Path(source_path)
        if draft is None:
            raise RuntimeError("第 0 步恢复状态缺少产品初稿路径")
        command.extend(["--product-draft", str(draft.resolve())])
    if step == 1 and args.workspace_root is not None:
        command.extend(["--workspace-root", str(args.workspace_root.resolve())])
    if step == 3 and args.catalog_path is not None:
        command.extend(["--catalog-path", str(args.catalog_path.resolve())])
    return command


def recovery_command(run_id: str, args: argparse.Namespace) -> str:
    command = [sys.executable, str(Path(__file__).resolve()), "--resume", run_id]
    if args.workspace_root is not None:
        command.extend(["--workspace-root", str(args.workspace_root.resolve())])
    if args.catalog_path is not None:
        command.extend(["--catalog-path", str(args.catalog_path.resolve())])
    return shlex.join(command)


def fresh_command(run_id: str, args: argparse.Namespace) -> str:
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--product-draft",
        str(args.product_draft.resolve()),
        "--run-id",
        run_id,
    ]
    if args.workspace_root is not None:
        command.extend(["--workspace-root", str(args.workspace_root.resolve())])
    if args.catalog_path is not None:
        command.extend(["--catalog-path", str(args.catalog_path.resolve())])
    return shlex.join(command)


def run_child(command: list[str]) -> int:
    child = subprocess.Popen(command, cwd=DEMO_ROOT, start_new_session=True)
    received_signal: int | None = None
    previous_handlers: dict[int, Any] = {}

    def forward(signum: int, _frame: Any) -> None:
        nonlocal received_signal
        if received_signal is None:
            received_signal = signum
        try:
            os.killpg(child.pid, signum)
        except ProcessLookupError:
            pass

    for signum in (signal.SIGINT, signal.SIGTERM):
        previous_handlers[signum] = signal.getsignal(signum)
        signal.signal(signum, forward)
    try:
        return_code = child.wait()
    finally:
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)

    if received_signal is not None:
        return 128 + received_signal
    if return_code < 0:
        return 128 - return_code
    return return_code


def _print_stop(run_id: str, run_dir: Path, args: argparse.Namespace) -> None:
    try:
        state = read_state(run_dir)
    except Exception:  # noqa: BLE001 - 停止摘要不能覆盖原始步骤错误。
        state = None
    if state is not None:
        print(
            f"完整编排已停止：run={run_id} status={state.get('status')} "
            f"node={state.get('current_node')} step={state.get('current_step')}",
            file=sys.stderr,
        )
    print(f"恢复命令：{recovery_command(run_id, args)}", file=sys.stderr)


def orchestrate(args: argparse.Namespace) -> int:
    run_id = args.resume or args.run_id or new_run_id()
    run_dir = run_dir_for(run_id)
    if args.resume:
        if not run_dir.is_dir():
            print(f"运行记录不存在：{run_id}", file=sys.stderr)
            return 2
    elif run_dir.exists():
        print(f"运行目录已存在，拒绝覆盖：{run_dir}", file=sys.stderr)
        return 2

    while True:
        try:
            state = read_state(run_dir) if run_dir.is_dir() else None
        except Exception as error:  # noqa: BLE001 - 损坏状态必须受控停止并保留现场。
            print(f"运行状态不可读取：{error}", file=sys.stderr)
            _print_stop(run_id, run_dir, args)
            return 1
        if state is not None and phase_one_completed(state):
            print(f"阶段一已完成：{run_dir / 'state.json'}")
            return 0
        try:
            step = 0 if state is None else step_for_state(run_dir, state)
            command = build_step_command(step, run_id, args, state)
        except Exception as error:  # noqa: BLE001 - 编排器必须给出稳定停止摘要。
            print(f"无法确定下一执行步骤：{error}", file=sys.stderr)
            if run_dir.is_dir():
                _print_stop(run_id, run_dir, args)
            return 1

        try:
            return_code = run_child(command)
        except OSError as error:
            print(f"无法启动步骤进程：{error}", file=sys.stderr)
            if run_dir.is_dir():
                _print_stop(run_id, run_dir, args)
            else:
                print(f"重试命令：{fresh_command(run_id, args)}", file=sys.stderr)
            return 1
        if return_code != 0:
            if run_dir.is_dir():
                _print_stop(run_id, run_dir, args)
            else:
                print(f"重试命令：{fresh_command(run_id, args)}", file=sys.stderr)
            return return_code
        if not run_dir.is_dir():
            print("步骤执行成功但运行目录不存在", file=sys.stderr)
            return 1


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        lock = acquire_global_lock()
    except (OSError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
        return 2
    try:
        return orchestrate(args)
    finally:
        lock.close()


if __name__ == "__main__":
    sys.exit(main())
