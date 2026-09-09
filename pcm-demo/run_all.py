from __future__ import annotations

import argparse
import json
import os
import shlex
import signal
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from secrets import token_hex
from typing import Any

from common.agent_decision_loop import validate_resume_target
from common.coordination import (
    ExecutionLocks,
    acquire_execution_locks,
    acquire_product_lock,
    claim_product,
    coordination_root,
    ensure_runtime,
    get_product,
    inherited_lock_argument,
    lock_status,
    product_key,
    release_product,
    run_lock_path,
)
from common.state import read_state, step_result_status, write_state
from common.timing import print_timing_summary
from config import load_settings
from model_policy import (
    _MODEL_POLICY_SNAPSHOT_ENV,
    _load_model_policy_from_file,
    _model_policy_snapshot,
    _model_policy_table,
)
from steps.step_13_select_requirement.step import registry_handoff

DEMO_ROOT = Path(__file__).resolve().parent
RUNS_DIR = DEMO_ROOT / "runs"
RUN_STEP_PATH = DEMO_ROOT / "run_step.py"
COORDINATION_ROOT = coordination_root(DEMO_ROOT)

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
    source.add_argument("--product-status", type=Path)
    source.add_argument("--release-product", type=Path)
    parser.add_argument("--run-id")
    parser.add_argument("--initial-resources", type=Path)
    parser.add_argument("--workspace-root", type=Path)
    parser.add_argument("--catalog-path", type=Path)
    parser.add_argument(
        "--resume-message-file",
        type=Path,
        help="仅用于当前 blocked：读取 UTF-8 文件作为人工负责人恢复指令",
    )
    args = parser.parse_args(argv)
    if args.initial_resources is not None and args.product_draft is None:
        parser.error("--initial-resources 只能用于提供产品初稿的新运行")
    if args.resume and args.run_id:
        parser.error("--resume 不能与 --run-id 同时使用")
    if args.resume_message_file is not None and not args.resume:
        parser.error("--resume-message-file 只能与 --resume 一起使用")
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


def _attach_product_lock(
    locks: ExecutionLocks,
    state: dict[str, Any] | None,
    run_dir: Path,
    execution_run_id: str,
) -> None:
    if locks.product is not None or state is None:
        return
    coordination = state.get("coordination")
    if isinstance(coordination, dict):
        key = coordination.get("product_key")
        path = coordination.get("product_path")
        run_id = coordination.get("execution_run_id")
        if not all(isinstance(value, str) and value for value in (key, path, run_id)):
            raise RuntimeError("运行状态中的产品协调身份无效")
        if run_id != execution_run_id:
            raise RuntimeError("运行状态中的 execution run 与运行目录不一致")
        locks.product = locks.stack.enter_context(
            acquire_product_lock(COORDINATION_ROOT, run_id, key, Path(path))
        )
        return

    workspace = state.get("workspace")
    final_path = workspace.get("final_path") if isinstance(workspace, dict) else None
    if not isinstance(final_path, str) or not final_path:
        return
    key, canonical = product_key(Path(final_path))
    locks.product = locks.stack.enter_context(
        acquire_product_lock(COORDINATION_ROOT, execution_run_id, key, canonical)
    )
    record = claim_product(
        COORDINATION_ROOT, execution_run_id, key, canonical
    )
    state["coordination"] = {
        "schema_version": 1,
        "execution_run_id": execution_run_id,
        "claim_phase": "claimed",
        "product_key": key,
        "product_path": str(canonical),
        "port_slot": record["port_slot"],
        "ports": record["ports"],
        "runtime_path": ".pcm/runtime.json",
    }
    write_state(run_dir, state)
    if canonical.is_dir():
        ensure_runtime(canonical, key, execution_run_id, record)


def _product_status(path: Path) -> int:
    key, canonical = product_key(path)
    try:
        record = get_product(COORDINATION_ROOT, key)
    except RuntimeError as error:
        print(str(error), file=sys.stderr)
        return 1
    if record.get("product_path") != str(canonical):
        print("产品注册记录与路径不一致", file=sys.stderr)
        return 1
    try:
        held, lock_metadata = lock_status(
            COORDINATION_ROOT / "locks" / "products" / f"{key}.lock"
        )
        owner_run = record.get("owner_run_id")
        if not isinstance(owner_run, str) or not owner_run:
            raise RuntimeError("产品 owner run 无效")
        run_held, run_lock_metadata = lock_status(
            run_lock_path(COORDINATION_ROOT, owner_run)
        )
    except RuntimeError as error:
        print(str(error), file=sys.stderr)
        return 1
    state_path = run_dir_for(owner_run) / "state.json"
    owner_state: dict[str, Any] | None = None
    if state_path is not None and state_path.is_file():
        try:
            current = read_state(state_path.parent)
            owner_state = {
                "status": current.get("status"),
                "current_node": current.get("current_node"),
                "current_step": current.get("current_step"),
            }
        except Exception:
            owner_state = {"error": "state 不可读取"}
    print(
        json.dumps(
            {
                "product_key": key,
                **record,
                "product_lock_held": held,
                "lock_metadata": lock_metadata,
                "run_lock_held": run_held,
                "run_lock_metadata": run_lock_metadata,
                "state_path": str(state_path) if state_path is not None else None,
                "owner_state": owner_state,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _release_product(path: Path) -> int:
    try:
        record = release_product(COORDINATION_ROOT, path)
    except (OSError, RuntimeError, ValueError) as error:
        print(f"产品释放失败：{error}", file=sys.stderr)
        return 1
    print(
        f"产品端口已释放：{record['product_path']} "
        f"frontend={record['ports']['frontend']} backend={record['ports']['backend']}"
    )
    return 0


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
    locks: ExecutionLocks | None = None,
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
        resources = args.initial_resources
        if resources is None and state is not None:
            resource_record = state.get("initial_resources")
            source_path = (
                resource_record.get("source_path")
                if isinstance(resource_record, dict)
                else None
            )
            if isinstance(source_path, str) and source_path:
                resources = Path(source_path)
        if resources is not None:
            command.extend(["--initial-resources", str(resources.absolute())])
    if step == 1:
        if args.initial_resources is not None:
            command.extend(
                ["--initial-resources", str(args.initial_resources.absolute())]
            )
        if args.workspace_root is not None:
            command.extend(["--workspace-root", str(args.workspace_root.resolve())])
    if step == 3 and args.catalog_path is not None:
        command.extend(["--catalog-path", str(args.catalog_path.resolve())])
    resume_message_file = getattr(args, "resume_message_file", None)
    if isinstance(resume_message_file, Path):
        command.extend(["--resume-message-file", str(resume_message_file.resolve())])
    if locks is not None:
        command.extend(["--coordination-locks", inherited_lock_argument(locks)])
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
    if args.initial_resources is not None:
        command.extend(["--initial-resources", str(args.initial_resources.absolute())])
    if args.workspace_root is not None:
        command.extend(["--workspace-root", str(args.workspace_root.resolve())])
    if args.catalog_path is not None:
        command.extend(["--catalog-path", str(args.catalog_path.resolve())])
    return shlex.join(command)


def run_child(
    command: list[str],
    pass_fds: tuple[int, ...] = (),
    env: dict[str, str] | None = None,
) -> int:
    child = subprocess.Popen(
        command,
        cwd=DEMO_ROOT,
        start_new_session=True,
        pass_fds=pass_fds,
        env=env,
    )
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


def _child_environment(model_policy_snapshot: str) -> dict[str, str]:
    env = dict(os.environ)
    env[_MODEL_POLICY_SNAPSHOT_ENV] = model_policy_snapshot
    return env


def _orchestrate_locked(
    args: argparse.Namespace,
    run_id: str,
    run_dir: Path,
    locks: ExecutionLocks,
    model_policy_snapshot: str,
) -> int:
    try:
        if args.resume:
            if not run_dir.is_dir():
                print(f"运行记录不存在：{run_id}", file=sys.stderr)
                return 2
            message_file = getattr(args, "resume_message_file", None)
            if isinstance(message_file, Path):
                state = read_state(run_dir)
                step = step_for_state(run_dir, state)
                validate_resume_target(run_dir, state, step)
                args.resume_message_file = message_file.resolve()
        elif run_dir.exists():
            print(f"运行目录已存在，拒绝覆盖：{run_dir}", file=sys.stderr)
            return 2
        return _run_steps(
            args, run_id, run_dir, locks, model_policy_snapshot
        )
    finally:
        print_timing_summary(run_dir)


def _run_steps(
    args: argparse.Namespace,
    run_id: str,
    run_dir: Path,
    locks: ExecutionLocks,
    model_policy_snapshot: str,
) -> int:
    child_env = _child_environment(model_policy_snapshot)
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
            _attach_product_lock(locks, state, run_dir, run_id)
            step = 0 if state is None else step_for_state(run_dir, state)
            command = build_step_command(step, run_id, args, state, locks)
        except Exception as error:  # noqa: BLE001 - 编排器必须给出稳定停止摘要。
            print(f"无法确定下一执行步骤：{error}", file=sys.stderr)
            if run_dir.is_dir():
                _print_stop(run_id, run_dir, args)
            return 1

        try:
            return_code = run_child(
                command, locks.file_descriptors(), child_env
            )
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
        args.resume_message_file = None
        if not run_dir.is_dir():
            print("步骤执行成功但运行目录不存在", file=sys.stderr)
            return 1


def orchestrate(args: argparse.Namespace) -> int:
    run_id = args.resume or args.run_id or new_run_id()
    run_dir = run_dir_for(run_id)
    try:
        model_policy = _load_model_policy_from_file()
        model_policy_snapshot = _model_policy_snapshot(model_policy)
        print(_model_policy_table(model_policy))
        maximum = load_settings().pcm_max_concurrent_projects
        with acquire_execution_locks(COORDINATION_ROOT, run_id, maximum) as locks:
            return _orchestrate_locked(
                args, run_id, run_dir, locks, model_policy_snapshot
            )
    except (OSError, RuntimeError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 2


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.product_status is not None:
        return _product_status(args.product_status)
    if args.release_product is not None:
        return _release_product(args.release_product)
    return orchestrate(args)


if __name__ == "__main__":
    sys.exit(main())
