from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import ANY, Mock, patch

DEMO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(DEMO_ROOT))

import run_step
from common.agent_decision_loop import ResumeMessage

_REAL_PARSE_ARGS = run_step.parse_args


class RunStepRetryTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        for patcher in (
            patch.object(run_step, "DEMO_ROOT", Path(temporary.name)),
            patch.object(run_step, "parse_args", return_value=Mock(step=1, run_id="test-run")),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_invalid_step_numbers_are_rejected_before_execution(self) -> None:
        for step in (-1, 0, 19):
            with (
                self.subTest(step=step),
                patch.object(sys, "argv", ["run_step.py", "--step", str(step)]),
                contextlib.redirect_stderr(io.StringIO()),
                self.assertRaises(SystemExit) as raised,
            ):
                _REAL_PARSE_ARGS()
            self.assertEqual(raised.exception.code, 2)
        self.assertFalse((run_step.DEMO_ROOT / "runs").exists())

    def test_run_directory_identity_is_protected(self) -> None:
        runs = run_step.DEMO_ROOT / "runs"
        run_step.create_run_dir(runs, "same-run")
        with self.assertRaises(FileExistsError):
            run_step.create_run_dir(runs, "same-run")
        with self.assertRaises(ValueError):
            run_step.create_run_dir(runs, "../outside")

    def test_initial_resources_rejected_outside_creation_steps(self) -> None:
        with (
            patch.object(sys, "argv", [
                "run_step.py", "--step", "2", "--run-id", "existing",
                "--initial-resources", "资料",
            ]),
            contextlib.redirect_stderr(io.StringIO()),
            self.assertRaises(SystemExit) as raised,
        ):
            _REAL_PARSE_ARGS()
        self.assertEqual(raised.exception.code, 2)

    def test_resume_message_help_explains_supported_states_and_utf8_contract(self) -> None:
        stdout = io.StringIO()
        with (
            patch.object(sys, "argv", ["run_step.py", "--help"]),
            contextlib.redirect_stdout(stdout),
            self.assertRaises(SystemExit) as raised,
        ):
            _REAL_PARSE_ARGS()
        self.assertEqual(raised.exception.code, 0)
        help_text = stdout.getvalue()
        self.assertIn("blocked、running 中断或 AgentExecutionFailure", help_text)
        self.assertIn("UTF-8 文件作为人工负责人恢复指令", help_text)

    def test_success_does_not_retry(self) -> None:
        runner = Mock(return_value=0)
        sleeper = Mock()
        with (
            patch.object(run_step, "_execute", runner),
            patch.object(run_step.time, "sleep", sleeper),
        ):
            self.assertEqual(run_step.retrying_main(), 0)
        runner.assert_called_once_with(ANY, ANY, ANY)
        sleeper.assert_not_called()

    def test_retry_requested_retries_twice(self) -> None:
        runner = Mock(
            side_effect=[
                run_step._RETRY_REQUESTED_EXIT_CODE,
                run_step._RETRY_REQUESTED_EXIT_CODE,
                0,
            ]
        )
        sleeper = Mock()
        stderr = io.StringIO()
        with (
            patch.object(run_step, "_execute", runner),
            patch.object(run_step.time, "sleep", sleeper),
            contextlib.redirect_stderr(stderr),
        ):
            self.assertEqual(run_step.retrying_main(), 0)
        self.assertEqual(runner.call_count, 3)
        self.assertEqual([call.args[0] for call in sleeper.call_args_list], [10, 30])
        self.assertIn("10 秒后重试", stderr.getvalue())
        self.assertIn("30 秒后重试", stderr.getvalue())

    def test_retry_exhaustion_returns_public_failure(self) -> None:
        runner = Mock(return_value=run_step._RETRY_REQUESTED_EXIT_CODE)
        with (
            patch.object(run_step, "_execute", runner),
            patch.object(run_step.time, "sleep"),
        ):
            self.assertEqual(run_step.retrying_main(), 1)
        self.assertEqual(runner.call_count, 3)

    def test_regular_failure_does_not_retry(self) -> None:
        runner = Mock(return_value=1)
        sleeper = Mock()
        with (
            patch.object(run_step, "_execute", runner),
            patch.object(run_step.time, "sleep", sleeper),
        ):
            self.assertEqual(run_step.retrying_main(), 1)
        runner.assert_called_once_with(ANY, ANY, ANY)
        sleeper.assert_not_called()

    def test_cli_error_does_not_retry(self) -> None:
        runner = Mock(return_value=2)
        sleeper = Mock()
        with (
            patch.object(run_step, "_execute", runner),
            patch.object(run_step.time, "sleep", sleeper),
        ):
            self.assertEqual(run_step.retrying_main(), 2)
        runner.assert_called_once_with(ANY, ANY, ANY)
        sleeper.assert_not_called()

    def test_main_maps_only_explicit_retry_request_to_internal_exit(self) -> None:
        for retry_requested, expected in (
            (False, 1),
            (True, run_step._RETRY_REQUESTED_EXIT_CODE),
        ):
            with self.subTest(retry_requested=retry_requested):
                error = run_step.AgentExecutionFailure(
                    "Agent SDK 执行失败",
                    "logs/agent.json",
                    retry_requested=retry_requested,
                )
                stderr = io.StringIO()
                with (
                    tempfile.TemporaryDirectory() as directory,
                    patch.object(run_step, "DEMO_ROOT", Path(directory)),
                    patch.object(run_step, "parse_args", return_value=Mock(step=4)),
                    patch.object(run_step, "run_step_four", side_effect=error),
                    contextlib.redirect_stderr(stderr),
                ):
                    self.assertEqual(run_step.main(), expected)
                self.assertIn("第 4 步执行失败", stderr.getvalue())

    def test_sdk_retry_reuses_one_prepared_resume_message(self) -> None:
        root = run_step.DEMO_ROOT
        run_dir = root / "runs/test-run"
        (run_dir / "steps").mkdir(parents=True)
        (run_dir / "state.json").write_text(
            json.dumps(
                {
                    "status": "blocked",
                    "step": 2,
                    "current_step": 2,
                    "current_node": "project:02_intake",
                }
            ),
            encoding="utf-8",
        )
        path = root / "message"
        path.write_text("负责人决定", encoding="utf-8")
        args = Mock(
            step=2,
            run_id="test-run",
            resume_message_file=path,
            coordination_locks=None,
        )
        message = ResumeMessage("project_intake", "负责人决定")
        seen: list[object] = []

        def execute(current_args, *_args):
            seen.append(current_args.resume_message)
            return run_step._RETRY_REQUESTED_EXIT_CODE if len(seen) == 1 else 0

        with (
            patch.object(run_step, "parse_args", return_value=args),
            patch.object(run_step, "prepare_resume_message", return_value=message) as prepare,
            patch.object(run_step, "_execute", side_effect=execute),
            patch.object(run_step.time, "sleep"),
        ):
            self.assertEqual(run_step.retrying_main(), 0)

        prepare.assert_called_once()
        self.assertEqual(seen, [message, message])

    def test_running_and_agent_failure_prepare_message_before_business_execution(self) -> None:
        root = run_step.DEMO_ROOT
        message_path = root / "message"
        message_path.write_text("负责人指令", encoding="utf-8")
        for status, error in (
            ("running", None),
            ("failed", {"type": "AgentExecutionFailure", "message": "SDK 失败"}),
        ):
            with self.subTest(status=status):
                run_id = f"test-{status}"
                run_dir = root / "runs" / run_id
                (run_dir / "steps").mkdir(parents=True)
                (run_dir / "conversations").mkdir()
                state = {
                    "run_id": run_id,
                    "status": status,
                    "step": 2,
                    "current_step": 2,
                    "current_node": "project:02_intake",
                    "error": error,
                    "claude_sessions": {"project_intake": "session-1"},
                    "decision_conversations": {
                        "project_intake": {"path": "conversations/project_intake.json"}
                    },
                }
                (run_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")
                (run_dir / "conversations/project_intake.json").write_text(
                    json.dumps(
                        {
                            "messages": [
                                {"role": "system", "content": "system"},
                                {"role": "assistant", "content": "待发送指令"},
                            ]
                        }
                    ),
                    encoding="utf-8",
                )
                args = Mock(
                    step=2,
                    run_id=run_id,
                    resume_message_file=message_path,
                    coordination_locks=None,
                )
                seen: list[ResumeMessage] = []

                def execute(current_args, *_args):
                    seen.append(current_args.resume_message)
                    current_args.resume_message.consumed = True
                    return 0

                with (
                    patch.object(run_step, "parse_args", return_value=args),
                    patch.object(run_step, "_execute", side_effect=execute),
                ):
                    self.assertEqual(run_step.main(), 0)

                self.assertEqual(len(seen), 1)
                self.assertEqual(seen[0].target_key, "project_intake")
                self.assertEqual(seen[0].content, "负责人指令")

    def test_invalid_resume_file_stops_before_business_execution(self) -> None:
        root = run_step.DEMO_ROOT
        run_dir = root / "runs/test-run"
        (run_dir / "steps").mkdir(parents=True)
        (run_dir / "conversations").mkdir()
        state = {
            "run_id": "test-run",
            "status": "blocked",
            "step": 2,
            "current_step": 2,
            "current_node": "project:02_intake",
            "claude_sessions": {"project_intake": "session-1"},
            "decision_conversations": {
                "project_intake": {"path": "conversations/project_intake.json"}
            },
        }
        (run_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")
        blocked = json.dumps(
            {
                "verdict": "blocked",
                "answer": "",
                "reason": "缺少输入",
                "required_inputs": ["负责人决定"],
            }
        )
        (run_dir / "conversations/project_intake.json").write_text(
            json.dumps(
                {
                    "messages": [
                        {"role": "system", "content": "system"},
                        {"role": "assistant", "content": "初始提示"},
                        {"role": "user", "content": "Agent 回复"},
                        {"role": "assistant", "content": blocked},
                    ]
                }
            ),
            encoding="utf-8",
        )
        message = root / "invalid"
        message.write_bytes(b"\xff")
        args = Mock(
            step=2,
            run_id="test-run",
            resume_message_file=message,
            coordination_locks=None,
        )
        before_state = (run_dir / "state.json").read_bytes()
        before_conversation = (run_dir / "conversations/project_intake.json").read_bytes()

        with (
            patch.object(run_step, "parse_args", return_value=args),
            patch.object(run_step, "_execute") as execute,
            contextlib.redirect_stderr(io.StringIO()),
        ):
            self.assertEqual(run_step.main(), 2)

        execute.assert_not_called()
        self.assertEqual((run_dir / "state.json").read_bytes(), before_state)
        self.assertEqual(
            (run_dir / "conversations/project_intake.json").read_bytes(),
            before_conversation,
        )
        self.assertEqual(list((run_dir / "steps").iterdir()), [])
        self.assertFalse((run_dir / "timings.json").exists())

    def test_real_cli_reads_relative_utf8_file_and_preserves_newlines(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir = root / "runs/test-run"
            (run_dir / "steps").mkdir(parents=True)
            (run_dir / "conversations").mkdir()
            state = {
                "run_id": "test-run",
                "status": "blocked",
                "phase": "project_initialization",
                "step": 2,
                "current_step": 2,
                "current_node": "project:02_intake",
                "claude_sessions": {"project_intake": "session-1"},
                "decision_conversations": {
                    "project_intake": {"path": "conversations/project_intake.json"}
                },
            }
            (run_dir / "state.json").write_text(
                json.dumps(state, ensure_ascii=False), encoding="utf-8"
            )
            blocked = json.dumps(
                {
                    "verdict": "blocked",
                    "answer": "",
                    "reason": "缺少决定",
                    "required_inputs": ["负责人决定"],
                },
                ensure_ascii=False,
            )
            (run_dir / "conversations/project_intake.json").write_text(
                json.dumps(
                    {
                        "messages": [
                            {"role": "system", "content": "system"},
                            {"role": "assistant", "content": "初始提示"},
                            {"role": "user", "content": "Agent 回复"},
                            {"role": "assistant", "content": blocked},
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            raw = "第一行\r\n第二行\r\n".encode("utf-8")
            (root / "message.any").write_bytes(raw)
            script = f"""
import sys
sys.path.insert(0, {str(DEMO_ROOT)!r})
from pathlib import Path
import run_step
from common.state import write_state
run_step.DEMO_ROOT = Path({str(root)!r})
async def fake(run_dir, state, *, resume_message=None):
    assert resume_message is not None
    (Path({str(root)!r}) / 'captured.bin').write_bytes(resume_message.content.encode('utf-8'))
    resume_message.consumed = True
    state.update({{'status': 'success', 'step': 3, 'current_step': 3, 'current_node': 'project:03_foundation_selection', 'blocked': None, 'error': None}})
    write_state(run_dir, state)
    return {{'step': 2, 'name': '项目定义澄清', 'status': 'success', 'summary': '完成', 'applicable': True, 'outputs': [], 'blocked': None, 'error': None}}
run_step.run_project_intake = fake
raise SystemExit(run_step.retrying_main())
"""
            completed = __import__("subprocess").run(
                [
                    sys.executable,
                    "-c",
                    script,
                    "--step",
                    "2",
                    "--run-id",
                    "test-run",
                    "--resume-message-file",
                    "message.any",
                ],
                cwd=root,
                text=True,
                capture_output=True,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual((root / "captured.bin").read_bytes(), raw)

    def test_step_one_fresh_run_binds_draft_and_initial_resources(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            demo_root = Path(directory)
            draft = demo_root / "draft.md"
            draft.write_text("产品初稿", encoding="utf-8")
            resources = demo_root / "资料"
            resources.mkdir()
            args = Mock(
                run_id="fresh-run",
                product_draft=draft,
                initial_resources=resources,
            )

            with patch.object(run_step, "DEMO_ROOT", demo_root):
                run_dir, state, draft_path = run_step.load_or_create_step_one_run(args)

            self.assertEqual(draft_path, draft.resolve())
            self.assertEqual(state["input"]["content"], "产品初稿")
            self.assertEqual(state["input"]["source_sha256"], run_step.sha256(draft))
            self.assertEqual(
                state["initial_resources"],
                {
                    "source_path": str(resources.resolve()),
                    "basename": "资料",
                    "published_path": None,
                },
            )

    def test_step_one_rejects_invalid_draft_before_run_or_ai(self) -> None:
        for label, raw in (
            ("missing", None),
            ("empty", b""),
            ("blank", b" \n\t"),
            ("invalid-utf8", b"\xff"),
        ):
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                demo_root = Path(directory)
                draft = demo_root / "draft.md"
                if raw is not None:
                    draft.write_bytes(raw)
                args = Mock(
                    step=1,
                    run_id=f"fresh-{label}",
                    product_draft=draft,
                    initial_resources=None,
                    workspace_root=None,
                )
                with (
                    patch.object(run_step, "DEMO_ROOT", demo_root),
                    patch.object(run_step, "extract_project_identity") as ai,
                    contextlib.redirect_stderr(io.StringIO()),
                ):
                    self.assertEqual(run_step._execute(args, None), 1)

                ai.assert_not_called()
                self.assertFalse((demo_root / "runs" / f"fresh-{label}").exists())

    def test_existing_runs_reject_adding_initial_resources_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            demo_root = Path(directory).resolve()
            draft = demo_root / "draft.md"
            draft.write_text("产品初稿", encoding="utf-8")
            resources = demo_root / "资料.txt"
            resources.write_text("客户资料", encoding="utf-8")
            for legacy in (False, True):
                with self.subTest(legacy=legacy):
                    run_id = f"existing-{legacy}"
                    run_dir = demo_root / "runs" / run_id
                    (run_dir / "steps").mkdir(parents=True)
                    state = {
                        "run_id": run_id,
                        "status": "failed",
                        "current_step": 1,
                        "input": {"source_path": str(draft)},
                    }
                    if not legacy:
                        state.update({
                            "phase": "project_initialization",
                            "step": 1,
                            "current_node": run_step.CREATE_WORKSPACE_NODE,
                        })
                    state_path = run_dir / "state.json"
                    state_path.write_text(json.dumps(state), encoding="utf-8")
                    result_path = run_dir / "steps/01.json"
                    result_path.write_text('{"status": "failed"}', encoding="utf-8")
                    before = (state_path.read_bytes(), result_path.read_bytes())
                    args = Mock(
                        run_id=run_id, product_draft=None, initial_resources=resources
                    )
                    with (
                        patch.object(run_step, "DEMO_ROOT", demo_root),
                        self.assertRaisesRegex(RuntimeError, "已有运行不能追加"),
                    ):
                        run_step.load_or_create_step_one_run(args)
                    self.assertEqual(
                        (state_path.read_bytes(), result_path.read_bytes()), before
                    )

    def test_step_one_success_writes_result_before_advancing_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir = root / "run"
            (run_dir / "steps").mkdir(parents=True)
            draft = root / "draft.md"
            draft.write_text("产品初稿", encoding="utf-8")
            workspace_root = root / "products"
            final_path = workspace_root / "project"
            (final_path / "docs").mkdir(parents=True)
            (final_path / "docs/产品初稿.md").write_bytes(draft.read_bytes())
            (final_path / "initial-resources").mkdir()
            (final_path / "initial-resources/removed-source.txt").write_text("saved copy", encoding="utf-8")
            removed_source = root / "removed-source.txt"
            staging_path = workspace_root / "project.pcm-tmp-test-run"
            workspace_env_file = root / "agent-workspace.env"
            workspace_env_file.write_bytes(b"MEDIA_KEY=test-value\n")
            repository = {"path": str(final_path.resolve()), "branch": "main", "head": None}
            state = {
                "run_id": "test-run",
                "status": "running",
                "phase": "project_initialization",
                "step": 1,
                "current_step": 1,
                "current_node": "project:01_create_workspace",
                "input": {
                    "source_path": str(draft),
                    "source_sha256": run_step.sha256(draft),
                    "content": draft.read_text(encoding="utf-8"),
                    "published_path": None,
                },
                "project": {"project_directory_name": "project"},
                "initial_resources": {
                    "source_path": str(removed_source),
                    "basename": "removed-source.txt",
                    "published_path": str(final_path / "initial-resources/removed-source.txt"),
                },
                "workspace": {
                    "root": str(workspace_root.resolve()),
                    "staging_path": str(staging_path.resolve()),
                    "final_path": str(final_path.resolve()),
                    "template_repository": "template.git",
                    "agent_workspace_env_file": str(workspace_env_file.resolve()),
                },
                "publication_phase": "git_initialized",
                "root_repository": repository,
                "blocked": None,
                "error": None,
            }
            order: list[str] = []

            def record_result(*_args, **_kwargs):
                order.append("result")

            def record_state(*_args, **_kwargs):
                order.append("state")

            args = Mock(workspace_root=workspace_root)
            with (
                patch.object(run_step, "DEMO_ROOT", root),
                patch.object(run_step, "load_workspace_root", return_value=(workspace_root.resolve(), "cli")),
                patch.object(run_step, "load_template_repository", return_value=("template.git", "env")),
                patch.object(
                    run_step,
                    "load_agent_workspace_env_file",
                    return_value=(workspace_env_file.resolve(), "env_file"),
                ),
                patch.object(run_step, "verify_published_content", return_value=True),
                patch.object(
                    run_step, "reject_nested_workspace",
                    side_effect=AssertionError("已发布副本恢复不得重新探测源目录"),
                ),
                patch.object(run_step, "workspace_env_is_ignored", return_value=True),
                patch.object(run_step, "initial_resources_are_ignored", autospec=True, return_value=True),
                patch.object(run_step, "inspect_root_repository", return_value=repository),
                patch.object(run_step, "write_step_result", side_effect=record_result),
                patch.object(run_step, "write_state", side_effect=record_state),
            ):
                _, completed = run_step.complete_step_one(args, run_dir, state, draft)

            self.assertEqual(completed["status"], "success")
            self.assertEqual(order[-2:], ["result", "state"])
            self.assertEqual(
                (state["step"], state["current_step"], state["current_node"]),
                (2, 2, "project:02_intake"),
            )

    def test_legacy_own_step_success_is_not_downgraded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            demo_root = Path(directory)
            runs = demo_root / "runs"

            step_one_dir = runs / "step-one"
            (step_one_dir / "steps").mkdir(parents=True)
            draft = demo_root / "draft.md"
            draft.write_text("产品初稿", encoding="utf-8")
            step_one_state = {
                "status": "success",
                "current_step": 1,
                "input": {"source_path": str(draft)},
            }
            (step_one_dir / "state.json").write_text(
                json.dumps(step_one_state, ensure_ascii=False), encoding="utf-8"
            )
            step_one_before = (step_one_dir / "state.json").read_bytes()

            step_two_dir = runs / "step-two"
            (step_two_dir / "steps").mkdir(parents=True)
            step_two_state = {"status": "success", "current_step": 2}
            (step_two_dir / "state.json").write_text(
                json.dumps(step_two_state, ensure_ascii=False), encoding="utf-8"
            )
            step_two_before = (step_two_dir / "state.json").read_bytes()

            with patch.object(run_step, "DEMO_ROOT", demo_root):
                with self.assertRaisesRegex(RuntimeError, "第 1 步恢复锚点"):
                    run_step.load_or_create_step_one_run(
                        Mock(run_id="step-one", product_draft=None)
                    )

                args = Mock(
                    step=2,
                    run_id="step-two",
                    product_draft=None,
                    workspace_root=None,
                    catalog_path=None,
                )
                with (
                    patch.object(run_step, "parse_args", return_value=args),
                    contextlib.redirect_stderr(io.StringIO()),
                ):
                    self.assertEqual(run_step.main(), 1)

            self.assertEqual((step_one_dir / "state.json").read_bytes(), step_one_before)
            self.assertEqual((step_two_dir / "state.json").read_bytes(), step_two_before)
            self.assertFalse((step_two_dir / "steps/02.json").exists())

    def test_step_two_advanced_state_is_not_downgraded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            demo_root = Path(directory)
            run_dir = demo_root / "runs" / "test-run"
            (run_dir / "steps").mkdir(parents=True)
            state = {
                "status": "running",
                "phase": "project_initialization",
                "step": 3,
                "current_step": 3,
                "current_node": "project:03_foundation_selection",
            }
            (run_dir / "state.json").write_text(
                json.dumps(state, ensure_ascii=False), encoding="utf-8"
            )
            success = {"step": 2, "status": "success"}
            (run_dir / "steps/02.json").write_text(
                json.dumps(success, ensure_ascii=False), encoding="utf-8"
            )
            state_before = (run_dir / "state.json").read_bytes()
            result_before = (run_dir / "steps/02.json").read_bytes()
            args = Mock(
                step=2,
                run_id="test-run",
                product_draft=None,
                workspace_root=None,
                catalog_path=None,
            )
            with (
                patch.object(run_step, "DEMO_ROOT", demo_root),
                patch.object(run_step, "parse_args", return_value=args),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                self.assertEqual(run_step.main(), 1)

            self.assertEqual((run_dir / "state.json").read_bytes(), state_before)
            self.assertEqual((run_dir / "steps/02.json").read_bytes(), result_before)

    def test_cancellation_is_not_retried(self) -> None:
        runner = Mock(side_effect=KeyboardInterrupt)
        with (
            patch.object(run_step, "_execute", runner),
            patch.object(run_step.time, "sleep") as sleeper,
            self.assertRaises(KeyboardInterrupt),
        ):
            run_step.retrying_main()
        runner.assert_called_once_with(ANY, ANY, ANY)
        sleeper.assert_not_called()


if __name__ == "__main__":
    unittest.main()
