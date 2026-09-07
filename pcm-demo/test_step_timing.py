from __future__ import annotations

import asyncio
import contextlib
import io
import json
import select
import signal
import subprocess
import sys
import tempfile
import unittest
from argparse import Namespace
from datetime import datetime, timedelta
from functools import partial
from pathlib import Path
from unittest.mock import patch

DEMO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(DEMO_ROOT))

import run_all
import run_step
from common import timing as timing_module
from common.agent_decision_loop import (
    AgentDecisionLoopSpec,
    AgentExecutionFailure,
    run_agent_decision_loop,
)
from common.claude_agent import ClaudeRunResult
from common.files import sha256, write_json
from common.test_agent_decision_loop import FakeAgentRunner, FakeDecisionRunner, decision
from model_policy import get_agent_profile


STEP_FIELDS = {
    "step",
    "name",
    "requirement_id",
    "status",
    "started_at",
    "finished_at",
    "agent_elapsed_seconds",
    "wall_elapsed_seconds",
    "agent_executions",
}
CALL_FIELDS = {
    "task",
    "model",
    "effort",
    "started_at",
    "finished_at",
    "interrupted_at",
    "elapsed_seconds",
    "end_reason",
    "usage",
    "model_usage",
    "total_cost_usd",
}


def make_result(
    step: int,
    status: str,
    *,
    requirement_id: str | None = None,
) -> dict[str, object]:
    result: dict[str, object] = {
        "step": step,
        "name": timing_module.STEP_NAMES[step],
        "status": status,
        "summary": f"第 {step} 步 {status}",
        "outputs": [],
        "applicable": True,
        "blocked": {"reason": "缺少不可替代的外部资源"} if status == "blocked" else None,
        "error": {"message": "任务执行失败"} if status == "failed" else None,
    }
    if requirement_id is not None:
        result["requirement_id"] = requirement_id
    return result


def make_call(
    elapsed_seconds: float,
    *,
    started_at: str = "2026-01-01T09:00:00+08:00",
    finished_at: str = "2026-01-01T09:00:42+08:00",
    interrupted_at: str | None = None,
    end_reason: str = "returned",
) -> dict[str, object]:
    return {
        "started_at": started_at,
        "finished_at": finished_at,
        "interrupted_at": interrupted_at,
        "elapsed_seconds": elapsed_seconds,
        "end_reason": end_reason,
    }


def make_step_record(
    step: int,
    status: str | None,
    *,
    requirement_id: str | None = None,
    started_at: str | None = "2026-01-01T08:59:50+08:00",
    finished_at: str | None = "2026-01-01T09:00:50+08:00",
    agent_executions: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    calls = agent_executions or []
    known = [call["elapsed_seconds"] for call in calls if call["elapsed_seconds"] is not None]
    wall_elapsed = None
    if started_at is not None and finished_at is not None:
        wall_elapsed = (
            datetime.fromisoformat(finished_at) - datetime.fromisoformat(started_at)
        ).total_seconds()
    return {
        "step": step,
        "name": timing_module.STEP_NAMES[step],
        "requirement_id": requirement_id,
        "status": status,
        "started_at": started_at,
        "finished_at": finished_at,
        "agent_elapsed_seconds": float(sum(known)),
        "wall_elapsed_seconds": wall_elapsed,
        "agent_executions": calls,
    }


def fake_now(clock: list[float]) -> str:
    start = datetime(2026, 1, 1, 9, 0, 0, tzinfo=timing_module.BEIJING)
    return (start + timedelta(seconds=clock[0])).isoformat()


def claude_result(
    text: str,
    workspace: Path,
    *,
    session_id: str = "session-1",
    skill_name: str = "test-skill",
) -> ClaudeRunResult:
    return ClaudeRunResult(
        init={
            "cwd": str(workspace),
            "skills": [skill_name],
            "slash_commands": [skill_name],
        },
        text=text,
        result_subtype="success",
        is_error=False,
        session_id=session_id,
        stop_reason=None,
        num_turns=1,
        total_cost_usd=0.01,
        exception=None,
        api_error_status=None,
        terminal_reason=None,
        has_errors=False,
        exception_type=None,
        retry_requested=False,
    )


class AdvancingAgentRunner(FakeAgentRunner):
    def __init__(
        self,
        results: list[ClaudeRunResult],
        clock: list[float],
        durations: list[float],
    ) -> None:
        super().__init__(results)
        self.clock = clock
        self.durations = iter(durations)

    async def __call__(self, prompt: str, **kwargs: object) -> ClaudeRunResult:
        result = await super().__call__(prompt, **kwargs)
        self.clock[0] += next(self.durations)
        return result


class AdvancingDecisionRunner(FakeDecisionRunner):
    def __init__(self, decisions, clock: list[float], duration: float) -> None:
        super().__init__(decisions)
        self.clock = clock
        self.duration = duration

    async def __call__(self, messages, config, *, system_prompt):
        result = await super().__call__(messages, config, system_prompt=system_prompt)
        self.clock[0] += self.duration
        return result


class AgentTimingIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_public_decision_loop_records_only_two_agent_continuations(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir = root / "run"
            workspace = root / "workspace"
            run_dir.mkdir()
            workspace.mkdir()
            state: dict[str, object] = {}
            spec = AgentDecisionLoopSpec(
                key="timed_conversation",
                state_key="timed_step",
                skill_name="test-skill",
                max_decision_rounds=3,
                max_turns=7,
                task="project_intake",
                decision_system_prompt="决策 system prompt",
            )
            clock = [0.0]
            agent = AdvancingAgentRunner(
                [
                    claude_result("第一轮回复", workspace),
                    claude_result("第二轮回复", workspace),
                ],
                clock,
                [3.0, 5.0],
            )
            owner = AdvancingDecisionRunner(
                [decision("continue", answer="继续完成"), decision("completed")],
                clock,
                13.0,
            )

            def verify() -> None:
                clock[0] += 7.0
                return None

            timing = timing_module.StepTiming()
            with (
                patch.object(timing_module.time, "monotonic", side_effect=lambda: clock[0]),
                patch.object(timing_module, "beijing_now", side_effect=lambda: fake_now(clock)),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                timing.begin_attempt(2)
                timing.bind_run(run_dir)
                with timing.activate():
                    final = await run_agent_decision_loop(
                        run_dir,
                        state,
                        workspace,
                        spec,
                        "初始 Agent 提示",
                        verify,
                        agent_runner=agent,
                        decision_runner=owner,
                        config_loader=lambda: object(),
                    )
                timing.observe_result(run_dir, make_result(2, "success"))
                timing.finish(returned=True)

            self.assertEqual(final.verdict, "completed")
            self.assertEqual([call[0] for call in agent.calls], ["初始 Agent 提示", "继续完成"])
            self.assertEqual(len(owner.calls), 2)
            profile = get_agent_profile(spec.task)
            for index, (_prompt, kwargs) in enumerate(agent.calls):
                self.assertEqual(kwargs["cwd"], workspace)
                self.assertEqual(kwargs["max_turns"], 7)
                self.assertEqual(kwargs["task"], spec.task)
                self.assertEqual(kwargs["model"], profile.model)
                self.assertEqual(kwargs["effort"], profile.effort)
                self.assertEqual(
                    kwargs["resume_session_id"], None if index == 0 else "session-1"
                )

            record = json.loads((run_dir / "timings.json").read_text(encoding="utf-8"))["steps"][0]
            self.assertEqual(
                [call["elapsed_seconds"] for call in record["agent_executions"]],
                [3.0, 5.0],
            )
            self.assertEqual(
                [call["end_reason"] for call in record["agent_executions"]],
                ["returned", "returned"],
            )
            self.assertEqual(record["agent_elapsed_seconds"], 8.0)
            self.assertEqual(record["wall_elapsed_seconds"], 41.0)

    async def test_completion_repair_is_a_separate_agent_execution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir = root / "run"
            workspace = root / "workspace"
            run_dir.mkdir()
            workspace.mkdir()
            spec = AgentDecisionLoopSpec(
                key="repair_conversation",
                state_key="repair_step",
                skill_name="test-skill",
                max_decision_rounds=3,
                max_turns=7,
                task="project_intake",
                decision_system_prompt="决策 system prompt",
            )
            clock = [0.0]
            agent = AdvancingAgentRunner(
                [claude_result("待核验", workspace), claude_result("已修复", workspace)],
                clock,
                [2.0, 4.0],
            )
            owner = AdvancingDecisionRunner(
                [decision("completed"), decision("completed")], clock, 6.0
            )
            repairs = iter(["请修复产物", None])

            def verify() -> str | None:
                clock[0] += 9.0
                return next(repairs)

            timing = timing_module.StepTiming()
            with (
                patch.object(timing_module.time, "monotonic", side_effect=lambda: clock[0]),
                patch.object(timing_module, "beijing_now", side_effect=lambda: fake_now(clock)),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                timing.begin_attempt(2)
                timing.bind_run(run_dir)
                with timing.activate():
                    final = await run_agent_decision_loop(
                        run_dir,
                        {},
                        workspace,
                        spec,
                        "初始提示",
                        verify,
                        agent_runner=agent,
                        decision_runner=owner,
                        config_loader=lambda: object(),
                    )
                timing.observe_result(run_dir, make_result(2, "success"))
                timing.finish(returned=True)

            self.assertEqual(final.verdict, "completed")
            self.assertEqual([call[0] for call in agent.calls], ["初始提示", "请修复产物"])
            record = json.loads((run_dir / "timings.json").read_text(encoding="utf-8"))["steps"][0]
            self.assertEqual(
                [call["elapsed_seconds"] for call in record["agent_executions"]],
                [2.0, 4.0],
            )
            self.assertEqual(record["agent_elapsed_seconds"], 6.0)
            self.assertEqual(record["wall_elapsed_seconds"], 36.0)

    async def test_run_timed_agent_records_only_inside_activated_step(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory) / "run"
            run_dir.mkdir()
            clock = [0.0]

            async def agent() -> ClaudeRunResult:
                clock[0] += 3.0
                return claude_result("完成", run_dir)

            timing = timing_module.StepTiming()
            with (
                patch.object(timing_module.time, "monotonic", side_effect=lambda: clock[0]),
                patch.object(timing_module, "beijing_now", side_effect=lambda: fake_now(clock)),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                timing.begin_attempt(0)
                timing.bind_run(run_dir)
                await timing_module.run_timed_agent(agent)
                with timing.activate():
                    await timing_module.run_timed_agent(agent)
                timing.observe_result(run_dir, make_result(0, "success"))
                timing.finish(returned=True)

            record = json.loads((run_dir / "timings.json").read_text(encoding="utf-8"))["steps"][0]
            self.assertEqual(len(record["agent_executions"]), 1)
            self.assertEqual(record["agent_executions"][0]["elapsed_seconds"], 3.0)
            self.assertEqual(record["agent_elapsed_seconds"], 3.0)


class StepTimingIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        for patcher in (
            patch.object(run_step, "DEMO_ROOT", root),
            patch.object(run_all, "COORDINATION_ROOT", run_step.coordination_root(root)),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def _write_step_two_state(self, run_dir: Path) -> None:
        write_json(
            run_dir / "state.json",
            {
                "run_id": run_dir.name,
                "status": "success",
                "phase": "project_initialization",
                "step": 2,
                "current_step": 2,
                "current_node": "project:02_intake",
                "active_requirement": None,
                "blocked": None,
                "error": None,
            },
        )

    def test_automatic_retries_keep_delays_and_record_each_agent_call(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir = root / "runs" / "retry-run"
            (run_dir / "steps").mkdir(parents=True)
            self._write_step_two_state(run_dir)
            clock = [0.0]
            delays: list[int] = []
            attempts = [0]
            durations = [2.0, 3.0, 4.0]

            async def run_attempt(_args: Namespace):
                index = attempts[0]
                attempts[0] += 1

                async def agent_call() -> ClaudeRunResult:
                    clock[0] += durations[index]
                    if index < 2:
                        raise AgentExecutionFailure(
                            "Agent SDK 执行失败",
                            "logs/agent.json",
                            retry_requested=True,
                        )
                    return claude_result("完成", run_dir)

                await timing_module.run_timed_agent(agent_call)
                return run_dir, make_result(2, "success")

            def backoff(delay: int) -> None:
                delays.append(delay)
                clock[0] += delay

            with (
                patch.object(run_step, "DEMO_ROOT", root),
                patch.object(
                    run_step,
                    "parse_args",
                    return_value=Namespace(step=2, run_id="retry-run"),
                ),
                patch.object(run_step, "run_step_two", side_effect=run_attempt),
                patch.object(run_step.time, "sleep", side_effect=backoff),
                patch.object(timing_module.time, "monotonic", side_effect=lambda: clock[0]),
                patch.object(timing_module, "beijing_now", side_effect=lambda: fake_now(clock)),
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                self.assertEqual(run_step.retrying_main(), 0)

            self.assertEqual(delays, [10, 30])
            record = json.loads((run_dir / "timings.json").read_text(encoding="utf-8"))["steps"][0]
            self.assertEqual(
                [call["elapsed_seconds"] for call in record["agent_executions"]],
                durations,
            )
            self.assertEqual(
                [call["end_reason"] for call in record["agent_executions"]],
                ["exception", "exception", "returned"],
            )
            self.assertEqual(record["agent_elapsed_seconds"], 9.0)
            self.assertEqual(record["wall_elapsed_seconds"], 49.0)

    def test_exhausted_automatic_retries_keep_failure_exit_code(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir = root / "runs" / "retry-run"
            (run_dir / "steps").mkdir(parents=True)
            self._write_step_two_state(run_dir)
            clock = [0.0]
            delays: list[int] = []

            async def run_attempt(_args: Namespace):
                async def agent_call() -> ClaudeRunResult:
                    clock[0] += 1.0
                    raise AgentExecutionFailure(
                        "Agent SDK 执行失败",
                        "logs/agent.json",
                        retry_requested=True,
                    )

                await timing_module.run_timed_agent(agent_call)
                raise AssertionError("Agent 异常必须向入口传播")

            def backoff(delay: int) -> None:
                delays.append(delay)
                clock[0] += delay

            with (
                patch.object(run_step, "DEMO_ROOT", root),
                patch.object(
                    run_step,
                    "parse_args",
                    return_value=Namespace(step=2, run_id="retry-run"),
                ),
                patch.object(run_step, "run_step_two", side_effect=run_attempt),
                patch.object(run_step.time, "sleep", side_effect=backoff),
                patch.object(timing_module.time, "monotonic", side_effect=lambda: clock[0]),
                patch.object(timing_module, "beijing_now", side_effect=lambda: fake_now(clock)),
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                self.assertEqual(run_step.retrying_main(), 1)

            self.assertEqual(delays, [10, 30])
            record = json.loads((run_dir / "timings.json").read_text(encoding="utf-8"))["steps"][0]
            self.assertEqual(len(record["agent_executions"]), 3)
            self.assertEqual(record["agent_elapsed_seconds"], 3.0)
            self.assertEqual(record["wall_elapsed_seconds"], None)

    def test_actual_registry_success_reuse_preserves_business_files_and_first_finish(self) -> None:
        from steps.step_12_initialize_requirement_registry import step as registry_step
        from steps.step_12_initialize_requirement_registry import test_step as fixtures

        with tempfile.TemporaryDirectory() as directory:
            fixture = fixtures.RequirementRegistryTests()
            run_dir, workspace, state = fixture.make_run(Path(directory))
            source = {
                "path": registry_step.BACKLOG_PATH.as_posix(),
                "sha256": sha256(workspace / registry_step.BACKLOG_PATH),
            }
            registry_step._advance_success(run_dir, state, source, fixture.requirements())
            result_path = run_dir / "steps" / "12.json"
            historical_result = json.loads(result_path.read_text(encoding="utf-8"))
            historical_result["summary"] = "已完成且应原样复用的历史摘要。"
            write_json(result_path, historical_result)
            original_state = (run_dir / "state.json").read_bytes()
            original_result = result_path.read_bytes()
            original_record = make_step_record(
                12,
                "success",
                agent_executions=[make_call(42.0)],
            )
            write_json(
                run_dir / "timings.json",
                {"schema_version": 2, "steps": [original_record]},
            )

            stderr = io.StringIO()
            with (
                patch.object(run_step, "run_dir_for", return_value=run_dir),
                patch.object(
                    run_step,
                    "parse_args",
                    return_value=Namespace(step=12, run_id="test-run"),
                ),
                patch.object(
                    run_step,
                    "run_requirement_registry",
                    partial(
                        registry_step.run,
                        config_loader=lambda: self.fail("成功复用不得加载模型配置"),
                    ),
                ),
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(stderr),
            ):
                self.assertEqual(run_step.retrying_main(), 0)

            stored = json.loads((run_dir / "timings.json").read_text(encoding="utf-8"))["steps"]
            self.assertEqual(len(stored), 1)
            self.assertEqual(stored[0], original_record)
            self.assertIn("成功复用", stderr.getvalue())
            self.assertEqual((run_dir / "state.json").read_bytes(), original_state)
            self.assertEqual(result_path.read_bytes(), original_result)

    def test_step_thirteen_uses_requirement_selected_during_step(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir = root / "runs" / "selection-run"
            (run_dir / "steps").mkdir(parents=True)
            state = {
                "status": "running",
                "phase": "phase_1_requirement_development",
                "step": 13,
                "current_step": 13,
                "current_node": "phase_1:select_requirement",
                "active_requirement": None,
            }
            write_json(run_dir / "state.json", state)

            def select_requirement(_args: Namespace):
                state["active_requirement"] = "BR-013"
                write_json(run_dir / "state.json", state)
                return run_dir, make_result(13, "success")

            with (
                patch.object(run_step, "DEMO_ROOT", root),
                patch.object(
                    run_step,
                    "parse_args",
                    return_value=Namespace(step=13, run_id="selection-run"),
                ),
                patch.object(run_step, "run_step_thirteen", side_effect=select_requirement),
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                self.assertEqual(run_step.retrying_main(), 0)

            record = json.loads((run_dir / "timings.json").read_text(encoding="utf-8"))["steps"][0]
            self.assertEqual(record["step"], 13)
            self.assertEqual(record["requirement_id"], "BR-013")

    def test_step_eighteen_retains_requirement_after_active_is_cleared(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir = root / "runs" / "merge-run"
            (run_dir / "steps").mkdir(parents=True)
            state = {
                "status": "running",
                "phase": "phase_1_requirement_development",
                "step": 18,
                "current_step": 18,
                "current_node": "requirement:18_merge",
                "active_requirement": "BR-018",
            }
            write_json(run_dir / "state.json", state)

            def merge_requirement(_args: Namespace):
                state["active_requirement"] = None
                write_json(run_dir / "state.json", state)
                return run_dir, make_result(18, "success")

            with (
                patch.object(run_step, "DEMO_ROOT", root),
                patch.object(
                    run_step,
                    "parse_args",
                    return_value=Namespace(step=18, run_id="merge-run"),
                ),
                patch.object(run_step, "run_step_eighteen", side_effect=merge_requirement),
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                self.assertEqual(run_step.retrying_main(), 0)

            record = json.loads((run_dir / "timings.json").read_text(encoding="utf-8"))["steps"][0]
            self.assertEqual(record["step"], 18)
            self.assertEqual(record["requirement_id"], "BR-018")

    def test_real_step_zero_subprocess_preserves_stdout_and_writes_compact_v2(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            draft = root / "draft.md"
            draft.write_text(
                "## A. 产品身份与文档边界\n产品。\n"
                "## C. 用户与使用场景\n用户。\n"
                "## D. 核心价值与业务闭环\n闭环。\n"
                "## E. 产品范围\n范围。\n"
                "## P. 产品验收\n验收。\n",
                encoding="utf-8",
            )
            child_code = (
                "import sys\n"
                "from pathlib import Path\n"
                "import run_step\n"
                "root, cli = Path(sys.argv[1]), sys.argv[2:]\n"
                "run_step.DEMO_ROOT = root\n"
                "sys.argv = ['run_step.py', *cli]\n"
                "raise SystemExit(run_step.retrying_main())\n"
            )
            completed = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    child_code,
                    str(root),
                    "--step",
                    "0",
                    "--product-draft",
                    str(draft),
                    "--run-id",
                    "subprocess-run",
                ],
                cwd=DEMO_ROOT,
                text=True,
                capture_output=True,
                check=False,
                timeout=20,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            run_dir = root / "runs" / "subprocess-run"
            result_path = run_dir / "steps" / "00.json"
            self.assertEqual(completed.stdout.strip(), str(result_path.resolve()))
            self.assertIn("开始  第 0 步 形成产品初稿", completed.stderr)
            self.assertIn("结束  项目 · 第 0 步", completed.stderr)
            self.assertIn("Claude Code 累计执行", completed.stderr)

            timings = json.loads((run_dir / "timings.json").read_text(encoding="utf-8"))
            self.assertEqual(set(timings), {"schema_version", "steps"})
            self.assertEqual(timings["schema_version"], 2)
            self.assertEqual(len(timings["steps"]), 1)
            record = timings["steps"][0]
            self.assertEqual(set(record), STEP_FIELDS)
            self.assertEqual(record["step"], 0)
            self.assertEqual(record["status"], "success")
            self.assertEqual(record["agent_elapsed_seconds"], 0.0)
            self.assertEqual(record["agent_executions"], [])
            self.assertGreaterEqual(record["wall_elapsed_seconds"], 0)
            for field in ("started_at", "finished_at"):
                parsed = datetime.fromisoformat(record[field])
                self.assertEqual(parsed.utcoffset(), timedelta(hours=8))

            state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
            result = json.loads(result_path.read_text(encoding="utf-8"))
            self.assertNotIn("timing", json.dumps(state, ensure_ascii=False).lower())
            self.assertNotIn("timing", json.dumps(result, ensure_ascii=False).lower())

    def _start_signal_child(self, run_dir: Path) -> subprocess.Popen[str]:
        child_code = (
            "import asyncio, signal, sys\n"
            "from pathlib import Path\n"
            "from common.timing import StepTiming, run_timed_agent\n"
            "run_dir = Path(sys.argv[1])\n"
            "run_dir.mkdir()\n"
            "timing = StepTiming()\n"
            "timing.begin_attempt(0)\n"
            "timing.bind_run(run_dir)\n"
            "returned = False\n"
            "async def wait_for_signal():\n"
            "    print('READY', flush=True)\n"
            "    signal.pause()\n"
            "try:\n"
            "    with timing.activate():\n"
            "        try:\n"
            "            asyncio.run(run_timed_agent(wait_for_signal))\n"
            "            returned = True\n"
            "        finally:\n"
            "            timing.finish(returned=returned)\n"
            "except KeyboardInterrupt:\n"
            "    raise SystemExit(130)\n"
        )
        return subprocess.Popen(
            [sys.executable, "-c", child_code, str(run_dir)],
            cwd=DEMO_ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def _wait_for_ready(self, process: subprocess.Popen[str]) -> None:
        self.assertIsNotNone(process.stdout)
        ready, _, _ = select.select([process.stdout], [], [], 10)
        if not ready:
            process.kill()
            _stdout, stderr = process.communicate(timeout=10)
            self.fail(f"子进程未就绪：{stderr}")
        self.assertEqual(process.stdout.readline().strip(), "READY")

    def test_sigterm_and_sigint_record_observable_agent_interruption(self) -> None:
        for signum, reason, returncode in (
            (signal.SIGTERM, "sigterm", 143),
            (signal.SIGINT, "sigint", 130),
        ):
            with self.subTest(signal=signum), tempfile.TemporaryDirectory() as directory:
                run_dir = Path(directory) / "run"
                process = self._start_signal_child(run_dir)
                try:
                    self._wait_for_ready(process)
                    process.send_signal(signum)
                    process.communicate(timeout=10)
                    self.assertEqual(process.returncode, returncode)
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.communicate(timeout=10)

                record = json.loads((run_dir / "timings.json").read_text(encoding="utf-8"))["steps"][0]
                self.assertEqual(len(record["agent_executions"]), 1)
                call = record["agent_executions"][0]
                self.assertEqual(set(call), CALL_FIELDS)
                self.assertEqual(call["end_reason"], reason)
                self.assertIsNotNone(call["interrupted_at"])
                self.assertIsNotNone(call["finished_at"])
                self.assertIsNotNone(call["elapsed_seconds"])
                self.assertTrue(call["interrupted_at"].endswith("+08:00"))
                self.assertIsNone(record["finished_at"])
                self.assertIsNone(record["wall_elapsed_seconds"])

    def test_sigterm_after_success_observation_does_not_revoke_finish(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            draft = root / "draft.md"
            draft.write_text(
                "## A. 产品身份与文档边界\n产品。\n"
                "## C. 用户与使用场景\n用户。\n"
                "## D. 核心价值与业务闭环\n闭环。\n"
                "## E. 产品范围\n范围。\n"
                "## P. 产品验收\n验收。\n", encoding="utf-8",
            )
            child_code = (
                "import builtins, signal, sys\n"
                "from pathlib import Path\n"
                "import run_step\n"
                "root = Path(sys.argv[1])\n"
                "run_step.DEMO_ROOT = root\n"
                "sys.argv = ['run_step.py', '--step', '0', '--run-id', 'success-signal', '--product-draft', str(root / 'draft.md')]\n"
                "original_print = builtins.print\n"
                "def checkpoint(*args, **kwargs):\n"
                "    if args and isinstance(args[0], Path) and args[0].name == '00.json':\n"
                "        original_print('READY', flush=True)\n"
                "        signal.pause()\n"
                "    else:\n"
                "        original_print(*args, **kwargs)\n"
                "builtins.print = checkpoint\n"
                "raise SystemExit(run_step.retrying_main())\n"
            )
            process = subprocess.Popen(
                [sys.executable, "-c", child_code, str(root)], cwd=DEMO_ROOT,
                text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            try:
                self._wait_for_ready(process)
                path = root / "runs" / "success-signal" / "timings.json"
                before = json.loads(path.read_text())["steps"][0]
                self.assertEqual(before["status"], "success")
                self.assertIsNotNone(before["finished_at"])
                process.send_signal(signal.SIGTERM)
                process.communicate(timeout=10)
                self.assertEqual(process.returncode, 143)
                self.assertEqual(json.loads(path.read_text())["steps"][0], before)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.communicate(timeout=10)

    @unittest.skipUnless(hasattr(signal, "SIGKILL"), "当前平台没有 SIGKILL")
    def test_sigkill_leaves_unknown_open_agent_execution_and_recovery_note(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory) / "run"
            process = self._start_signal_child(run_dir)
            try:
                self._wait_for_ready(process)
                process.kill()
                process.communicate(timeout=10)
                self.assertEqual(process.returncode, -signal.SIGKILL)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.communicate(timeout=10)

            path = run_dir / "timings.json"
            record = json.loads(path.read_text(encoding="utf-8"))["steps"][0]
            call = record["agent_executions"][0]
            self.assertIsNone(call["finished_at"])
            self.assertIsNone(call["interrupted_at"])
            self.assertIsNone(call["elapsed_seconds"])
            self.assertIsNone(call["end_reason"])

            resumed = timing_module.StepTiming()
            with contextlib.redirect_stderr(io.StringIO()):
                resumed.begin_attempt(0)
                resumed.bind_run(run_dir)

            recovered = json.loads(path.read_text(encoding="utf-8"))["steps"][0]
            recovered_call = recovered["agent_executions"][0]
            self.assertIsNone(recovered_call["finished_at"])
            self.assertIsNone(recovered_call["interrupted_at"])
            self.assertIsNone(recovered_call["elapsed_seconds"])
            self.assertEqual(recovered_call["end_reason"], "unknown")
            self.assertIn("未闭合", recovered["note"])

    def test_old_format_is_not_rewritten_and_business_exit_is_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir = root / "runs" / "old-format"
            run_dir.mkdir(parents=True)
            path = run_dir / "timings.json"
            raw = b'{"schema_version":1,"executions":[{"opaque":"keep"}]}'
            path.write_bytes(raw)
            stderr = io.StringIO()
            with (
                patch.object(run_step, "DEMO_ROOT", root),
                patch.object(run_step, "parse_args", return_value=Namespace(step=0, run_id="old-format")),
                patch.object(run_step, "run_step_zero", return_value=(run_dir, make_result(0, "success"))),
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(stderr),
            ):
                self.assertEqual(run_step.retrying_main(), 0)
            self.assertEqual(path.read_bytes(), raw)
            self.assertFalse((run_dir / "timings.v1.json").exists())
            self.assertIn("计时记录不可读写", stderr.getvalue())

    def test_damaged_timing_file_does_not_change_success_exit_code(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir = root / "runs" / "damaged-run"
            run_dir.mkdir(parents=True)
            (run_dir / "timings.json").write_text("{broken", encoding="utf-8")
            stderr = io.StringIO()
            with (
                patch.object(run_step, "DEMO_ROOT", root),
                patch.object(
                    run_step,
                    "parse_args",
                    return_value=Namespace(step=0, run_id="damaged-run"),
                ),
                patch.object(
                    run_step,
                    "run_step_zero",
                    return_value=(run_dir, make_result(0, "success")),
                ),
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(stderr),
            ):
                self.assertEqual(run_step.retrying_main(), 0)

            self.assertIn("计时记录不可读写", stderr.getvalue())
            self.assertEqual((run_dir / "timings.json").read_text(encoding="utf-8"), "{broken")

    def test_timing_write_failure_does_not_change_business_failure_exit_code(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory) / "run"
            run_dir.mkdir()
            stderr = io.StringIO()
            with (
                patch.object(
                    run_step,
                    "parse_args",
                    return_value=Namespace(step=0, run_id=None),
                ),
                patch.object(
                    run_step,
                    "run_step_zero",
                    return_value=(run_dir, make_result(0, "failed")),
                ),
                patch.object(timing_module, "write_json", side_effect=OSError("只读文件系统")),
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(stderr),
            ):
                self.assertEqual(run_step.retrying_main(), 1)

            self.assertIn("计时记录不可读写", stderr.getvalue())
            self.assertFalse((run_dir / "timings.json").exists())

    def test_bad_summary_data_does_not_change_run_all_failure_exit_code(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory) / "run"
            run_dir.mkdir()
            path = run_dir / "timings.json"
            path.write_text("{broken", encoding="utf-8")
            stderr = io.StringIO()
            with (
                patch.object(run_all, "run_dir_for", return_value=run_dir),
                patch.object(run_all, "_run_steps", return_value=1),
                contextlib.redirect_stderr(stderr),
            ):
                self.assertEqual(
                    run_all.orchestrate(Namespace(resume="run", run_id=None)),
                    1,
                )

            self.assertEqual(path.read_text(encoding="utf-8"), "{broken")
            self.assertIn("计时汇总不可读取", stderr.getvalue())
            self.assertIn("退出码不受影响", stderr.getvalue())

    def test_invalid_cli_arguments_do_not_create_timing_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir = root / "runs" / "invalid-run"
            run_dir.mkdir(parents=True)
            stderr = io.StringIO()
            with (
                patch.object(run_step, "DEMO_ROOT", root),
                patch.object(
                    sys,
                    "argv",
                    ["run_step.py", "--step", "not-a-number", "--run-id", "invalid-run"],
                ),
                contextlib.redirect_stderr(stderr),
                self.assertRaises(SystemExit) as raised,
            ):
                run_step.retrying_main()

            self.assertEqual(raised.exception.code, 2)
            self.assertIn("invalid int value", stderr.getvalue())
            self.assertFalse((run_dir / "timings.json").exists())

    def test_unimplemented_step_keeps_exit_code_two_without_timing_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir = root / "runs" / "unsupported-run"
            run_dir.mkdir(parents=True)
            with (
                patch.object(run_step, "DEMO_ROOT", root),
                patch.object(
                    run_step,
                    "parse_args",
                    return_value=Namespace(step=99, run_id="unsupported-run"),
                ),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                self.assertEqual(run_step.retrying_main(), 2)
            self.assertFalse((run_dir / "timings.json").exists())

    def test_run_all_success_and_failure_summaries_are_read_only(self) -> None:
        for exit_code in (0, 1):
            with self.subTest(exit_code=exit_code), tempfile.TemporaryDirectory() as directory:
                run_dir = Path(directory) / "run"
                run_dir.mkdir()
                path = run_dir / "timings.json"
                write_json(
                    path,
                    {
                        "schema_version": 2,
                        "steps": [make_step_record(0, "success", agent_executions=[])],
                    },
                )
                before = path.read_bytes()
                stderr = io.StringIO()
                with (
                    patch.object(run_all, "run_dir_for", return_value=run_dir),
                    patch.object(run_all, "_run_steps", return_value=exit_code),
                    contextlib.redirect_stderr(stderr),
                ):
                    self.assertEqual(
                        run_all.orchestrate(Namespace(resume="run", run_id=None)),
                        exit_code,
                    )

                self.assertIn("步骤耗时汇总", stderr.getvalue())
                self.assertEqual(path.read_bytes(), before)

    def test_run_all_existing_run_refusal_prints_read_only_summary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory) / "run"
            run_dir.mkdir()
            path = run_dir / "timings.json"
            write_json(
                path,
                {
                    "schema_version": 2,
                    "steps": [make_step_record(0, "success", agent_executions=[])],
                },
            )
            before = path.read_bytes()
            stderr = io.StringIO()
            with (
                patch.object(run_all, "run_dir_for", return_value=run_dir),
                patch.object(run_all, "_run_steps") as run_steps,
                contextlib.redirect_stderr(stderr),
            ):
                self.assertEqual(
                    run_all.orchestrate(Namespace(resume=None, run_id="existing")),
                    2,
                )

            run_steps.assert_not_called()
            self.assertIn("拒绝覆盖", stderr.getvalue())
            self.assertIn("步骤耗时汇总", stderr.getvalue())
            self.assertEqual(path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
