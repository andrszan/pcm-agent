from __future__ import annotations

import asyncio
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError

DEMO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(DEMO_ROOT))

from common.files import write_json
from common.state import read_state, write_state
from steps.step_12_initialize_requirement_registry.step import (
    BACKLOG_PATH,
    CURRENT_NODE,
    NAME,
    NEXT_NODE,
    PHASE,
    STEP,
    SYSTEM_PROMPT,
    BacklogExtractionInput,
    RequirementCatalog,
    RequirementStatic,
    _safe_workspace_output,
    extract_requirements,
    has_complete_success,
    result,
    run,
    validate_catalog,
)
import steps.step_12_initialize_requirement_registry.step as registry_step


BACKLOG = """# 社区维修产品 Backlog

当前正式交付范围由以下三项需求组成，编号和名称均为正式定义：

第一项是 REQ-001「账户访问」。它没有前置需求，负责让居民与维修人员进入系统。

随后实现 REQ-002「订单管理」。文档明确规定 REQ-001 是它的前置需求。

最后是 REQ-003「通知中心」，并明确以 REQ-002 完成为前提。

补充说明：示例编号 NOTE-001 只是写作说明，不属于正式需求；未来可能考虑支付能力，但不在当前正式范围。
"""


class RequirementRegistryTests(unittest.TestCase):
    def make_run(self, root: Path, backlog: str = BACKLOG) -> tuple[Path, Path, dict]:
        run_dir = root / "run"
        (run_dir / "steps").mkdir(parents=True)
        workspace_root = root / "workspace-root"
        workspace = workspace_root / "project"
        backlog_path = workspace / BACKLOG_PATH
        backlog_path.parent.mkdir(parents=True)
        backlog_path.write_text(backlog, encoding="utf-8")
        write_json(
            run_dir / "steps/11.json",
            {
                "step": 11,
                "name": "拆分 Backlog",
                "status": "success",
                "summary": "已完成 Backlog 拆分。",
                "applicable": True,
                "outputs": [BACKLOG_PATH.as_posix()],
                "blocked": None,
                "error": None,
            },
        )
        state = {
            "run_id": "test-run",
            "status": "success",
            "phase": PHASE,
            "step": STEP,
            "current_step": STEP,
            "current_node": CURRENT_NODE,
            "workspace": {"root": str(workspace_root), "final_path": str(workspace)},
            "active_requirement": None,
            "requirement_cycle": None,
            "blocked": None,
            "error": None,
        }
        write_state(run_dir, state)
        return run_dir, workspace, state

    @staticmethod
    def requirements() -> list[dict]:
        return [
            {"id": "REQ-001", "title": "账户访问", "order": 1, "depends_on": []},
            {"id": "REQ-002", "title": "订单管理", "order": 2, "depends_on": ["REQ-001"]},
            {"id": "REQ-003", "title": "通知中心", "order": 3, "depends_on": ["REQ-002"]},
        ]

    @staticmethod
    def catalog(requirements: list[dict] | None = None) -> RequirementCatalog:
        return RequirementCatalog.model_validate(
            {"requirements": requirements or RequirementRegistryTests.requirements()}
        )

    def run_step(self, run_dir: Path, state: dict, **kwargs: object) -> dict:
        return asyncio.run(run(run_dir, state, **kwargs))

    def test_models_and_extraction_call_are_wired_for_complete_free_format_input(self) -> None:
        with self.assertRaises(ValidationError):
            BacklogExtractionInput.model_validate(
                {"backlog_markdown": "x", "unexpected": True}
            )
        with self.assertRaises(ValidationError):
            RequirementCatalog.model_validate(
                {
                    "requirements": [
                        {
                            "id": "REQ-1",
                            "title": "x",
                            "order": 1,
                            "depends_on": [],
                            "status": "pending",
                        }
                    ]
                }
            )
        self.assertEqual(
            RequirementStatic(
                id=" REQ-1 ", title=" 功能 ", order=1, depends_on=[" REQ-0 "]
            ).model_dump(),
            {"id": "REQ-1", "title": "功能", "order": 1, "depends_on": ["REQ-0"]},
        )
        for identifier in ("REQ.001", "REQ/001", "../REQ-001"):
            with self.subTest(identifier=identifier), self.assertRaises(ValidationError):
                RequirementStatic(id=identifier, title="功能", order=1, depends_on=[])

        calls: list[dict] = []

        async def fake_model(config: object, **kwargs: object) -> RequirementCatalog:
            calls.append({"config": config, **kwargs})
            return self.catalog()

        extracted = asyncio.run(
            extract_requirements(BACKLOG, object(), model_runner=fake_model)
        )
        self.assertEqual(extracted, self.catalog())
        self.assertNotIn("max_output_tokens", calls[0])
        self.assertEqual(calls[0]["max_retries"], 0)
        self.assertEqual(calls[0]["system_prompt"], SYSTEM_PROMPT)
        self.assertEqual(calls[0]["input_model"].backlog_markdown, BACKLOG)
        self.assertIs(calls[0]["output_model"], RequirementCatalog)

    def test_success_initializes_registry_from_free_format_without_git(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))
            backlog = workspace / BACKLOG_PATH
            before = backlog.read_bytes()
            calls: list[object] = []

            async def fake_model(config: object, **kwargs: object) -> RequirementCatalog:
                calls.append(config)
                return self.catalog()

            saved = self.run_step(
                run_dir,
                state,
                config_loader=lambda: object(),
                model_runner=fake_model,
            )
            self.assertFalse((workspace / ".git").exists())
            self.assertEqual(saved["step"], STEP)
            self.assertEqual(saved["outputs"], [])
            self.assertEqual(saved["requirement_catalog"], self.requirements())
            self.assertEqual(
                saved["source"],
                {
                    "path": BACKLOG_PATH.as_posix(),
                    "sha256": hashlib.sha256(before).hexdigest(),
                },
            )
            self.assertEqual(len(calls), 1)
            completed = read_state(run_dir)
            self.assertEqual(
                (
                    completed["phase"],
                    completed["step"],
                    completed["current_step"],
                    completed["current_node"],
                ),
                (PHASE, 13, 13, NEXT_NODE),
            )
            self.assertIsNone(completed["active_requirement"])
            self.assertIsNone(completed["requirement_cycle"])
            self.assertNotIn("phase_two", completed)
            self.assertNotIn("completed_requirements", completed)
            self.assertEqual(
                completed["requirement_registry"]["requirements"],
                [
                    {**item, "status": "pending", "completion": None}
                    for item in self.requirements()
                ],
            )
            self.assertEqual(backlog.read_bytes(), before)

    def test_rejects_catalogs_that_cannot_drive_lifecycle(self) -> None:
        base = self.requirements()
        cases = {
            "empty": [],
            "duplicate-id": [
                base[0],
                {"id": "REQ-001", "title": "订单管理", "order": 2, "depends_on": []},
                base[2],
            ],
            "casefold-duplicate-id": [
                base[0],
                {"id": "req-001", "title": "订单管理", "order": 2, "depends_on": []},
                base[2],
            ],
            "physical-order": [
                {**base[0], "order": 2},
                {**base[1], "order": 1},
                base[2],
            ],
            "duplicate-order": [base[0], {**base[1], "order": 1}, base[2]],
            "non-continuous-order": [
                base[0],
                {**base[1], "order": 3},
                {**base[2], "order": 4},
            ],
            "unknown-dependency": [
                base[0],
                {**base[1], "depends_on": ["REQ-999"]},
                base[2],
            ],
            "duplicate-dependency": [
                base[0],
                {**base[1], "depends_on": ["REQ-001", "REQ-001"]},
                base[2],
            ],
            "self-dependency": [
                {**base[0], "depends_on": ["REQ-001"]},
                *base[1:],
            ],
            "cycle": [
                {**base[0], "depends_on": ["REQ-003"]},
                *base[1:],
            ],
        }
        for label, requirements in cases.items():
            with self.subTest(label=label), self.assertRaises(
                (RuntimeError, ValidationError)
            ):
                validate_catalog(requirements)

        for invalid in (
            [{"id": "REQ/001", "title": "账户", "order": 1, "depends_on": []}],
            [{"id": "REQ-001", "title": "账户", "order": 1, "depends_on": ["REQ/000"]}],
            [
                {
                    "id": "REQ-001",
                    "title": "账户",
                    "order": 1,
                    "depends_on": [],
                    "status": "pending",
                }
            ],
        ):
            with self.assertRaises(ValidationError):
                validate_catalog(invalid)

    def test_rejects_unsafe_or_empty_backlog_before_model_execution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))
            with self.assertRaises(RuntimeError):
                _safe_workspace_output(workspace, "/tmp/backlog.md")
            with self.assertRaises(RuntimeError):
                _safe_workspace_output(workspace, "../backlog.md")

            external = Path(directory) / "external.md"
            external.write_text(BACKLOG, encoding="utf-8")
            (workspace / BACKLOG_PATH).unlink()
            (workspace / BACKLOG_PATH).symlink_to(external)

            async def unexpected(*args: object, **kwargs: object) -> RequirementCatalog:
                raise AssertionError("无效 Backlog 不得调用模型")

            with self.assertRaises(RuntimeError):
                self.run_step(
                    run_dir,
                    state,
                    config_loader=lambda: object(),
                    model_runner=unexpected,
                )

        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory), " \n")

            async def unexpected(*args: object, **kwargs: object) -> RequirementCatalog:
                raise AssertionError("空 Backlog 不得调用模型")

            with self.assertRaises(RuntimeError):
                self.run_step(
                    run_dir,
                    state,
                    config_loader=lambda: object(),
                    model_runner=unexpected,
                )

        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))
            external = Path(directory) / "external-docs"
            external.mkdir()
            (external / "backlog.md").write_text(BACKLOG, encoding="utf-8")
            (workspace / BACKLOG_PATH).unlink()
            (workspace / BACKLOG_PATH).parent.rmdir()
            (workspace / "docs").rmdir()
            (workspace / "docs").symlink_to(external)

            async def unexpected(*args: object, **kwargs: object) -> RequirementCatalog:
                raise AssertionError("符号链接父目录不得调用模型")

            with self.assertRaises(RuntimeError):
                self.run_step(
                    run_dir,
                    state,
                    config_loader=lambda: object(),
                    model_runner=unexpected,
                )

    def test_model_call_detects_backlog_content_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))

            async def changing_model(*args: object, **kwargs: object) -> RequirementCatalog:
                (workspace / BACKLOG_PATH).write_text(
                    BACKLOG + "\n正式需求 REQ-004 已加入。\n", encoding="utf-8"
                )
                return self.catalog()

            with self.assertRaisesRegex(RuntimeError, "Backlog 发生变化"):
                self.run_step(
                    run_dir,
                    state,
                    config_loader=lambda: object(),
                    model_runner=changing_model,
                )
            self.assertFalse((run_dir / "steps/12.json").exists())
            self.assertEqual(read_state(run_dir)["status"], "running")

    def test_legacy_select_node_is_not_accepted(self) -> None:
        self.assertEqual(CURRENT_NODE, "phase_1:initialize_requirement_registry")
        with tempfile.TemporaryDirectory() as directory:
            run_dir, _workspace, state = self.make_run(Path(directory))
            state["current_node"] = "phase_1:select_requirement"
            with self.assertRaises(RuntimeError):
                self.run_step(run_dir, state)

    def test_result_then_state_interruption_recovers_without_model_call(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, _workspace, state = self.make_run(Path(directory))
            original_write_state = registry_step.write_state

            def interrupt_final_state(target: Path, value: dict) -> None:
                if value.get("current_node") == NEXT_NODE:
                    raise OSError("模拟状态写入中断")
                original_write_state(target, value)

            async def fake_model(*args: object, **kwargs: object) -> RequirementCatalog:
                return self.catalog()

            with patch.object(
                registry_step, "write_state", side_effect=interrupt_final_state
            ):
                with self.assertRaises(OSError):
                    self.run_step(
                        run_dir,
                        state,
                        config_loader=lambda: object(),
                        model_runner=fake_model,
                    )
            saved = json.loads((run_dir / "steps/12.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["status"], "success")
            self.assertEqual(read_state(run_dir)["current_node"], CURRENT_NODE)

            async def unexpected(*args: object, **kwargs: object) -> RequirementCatalog:
                raise AssertionError("恢复不得调用模型")

            recovered = self.run_step(
                run_dir, read_state(run_dir), model_runner=unexpected
            )
            self.assertEqual(recovered, saved)
            self.assertEqual(read_state(run_dir)["current_node"], NEXT_NODE)

    def test_idempotence_and_source_catalog_registry_drift(self) -> None:
        for mutation in ("hash", "catalog", "registry"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                run_dir, workspace, state = self.make_run(Path(directory))

                async def fake_model(*args: object, **kwargs: object) -> RequirementCatalog:
                    return self.catalog()

                self.run_step(
                    run_dir,
                    state,
                    config_loader=lambda: object(),
                    model_runner=fake_model,
                )
                completed = read_state(run_dir)

                async def unexpected(*args: object, **kwargs: object) -> RequirementCatalog:
                    raise AssertionError("完整成功重跑不得调用模型")

                if mutation == "hash":
                    (workspace / BACKLOG_PATH).write_text(BACKLOG + "\n", encoding="utf-8")
                elif mutation == "catalog":
                    saved = json.loads(
                        (run_dir / "steps/12.json").read_text(encoding="utf-8")
                    )
                    saved["requirement_catalog"][0]["title"] = "冲突标题"
                    write_json(run_dir / "steps/12.json", saved)
                else:
                    completed["requirement_registry"]["requirements"][0]["status"] = "active"
                    write_state(run_dir, completed)

                with self.assertRaises(RuntimeError):
                    self.run_step(
                        run_dir, read_state(run_dir), model_runner=unexpected
                    )

        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))

            async def fake_model(*args: object, **kwargs: object) -> RequirementCatalog:
                return self.catalog()

            self.run_step(
                run_dir,
                state,
                config_loader=lambda: object(),
                model_runner=fake_model,
            )
            (workspace / "README.md").write_text("无关变化", encoding="utf-8")

            async def unexpected(*args: object, **kwargs: object) -> RequirementCatalog:
                raise AssertionError("幂等重跑不得调用模型")

            repeated = self.run_step(
                run_dir, read_state(run_dir), model_runner=unexpected
            )
            self.assertIn("确认既有", repeated["summary"])

    def test_failed_result_can_rerun_and_registry_without_success_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, _workspace, state = self.make_run(Path(directory))
            write_json(
                run_dir / "steps/12.json",
                result(
                    "failed",
                    "初始化失败。",
                    error={"type": "RuntimeError", "message": "已脱敏"},
                ),
            )
            state["status"] = "failed"
            write_state(run_dir, state)

            async def fake_model(*args: object, **kwargs: object) -> RequirementCatalog:
                return self.catalog()

            saved = self.run_step(
                run_dir,
                read_state(run_dir),
                config_loader=lambda: object(),
                model_runner=fake_model,
            )
            self.assertEqual(saved["status"], "success")

        with tempfile.TemporaryDirectory() as directory:
            run_dir, _workspace, state = self.make_run(Path(directory))
            state["requirement_registry"] = {"schema_version": 1}
            write_state(run_dir, state)
            with self.assertRaises(RuntimeError):
                self.run_step(run_dir, read_state(run_dir))

    def test_old_source_schema_is_not_a_complete_success(self) -> None:
        source = {
            "path": BACKLOG_PATH.as_posix(),
            "sha256": "a" * 64,
            "root_main_sha": "b" * 40,
        }
        saved = result(
            "success",
            "旧合同结果。",
            source=source,
            requirement_catalog=self.requirements(),
        )
        self.assertFalse(has_complete_success(saved))


if __name__ == "__main__":
    unittest.main()
