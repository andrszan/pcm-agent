from __future__ import annotations

import asyncio
import json
import subprocess
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
    _root_main_sha,
    _safe_workspace_output,
    extract_requirements,
    formal_cards,
    result,
    run,
)
import steps.step_12_initialize_requirement_registry.step as registry_step


BACKLOG = """# Backlog

## 5. 大需求总览

| 序号 | 需求 ID | 需求标题 | 前置依赖 |
| --- | --- | --- | --- |
| 1 | REQ-001 | 账户访问 | 无 |
| 2 | REQ-002 | 订单管理 | REQ-001 |
| 3 | REQ-003 | 通知中心 | REQ-002 |

## 6. 需求详情

#### REQ-001 账户访问

范围与验收要点。

##### 前置依赖

无。

#### REQ-002 订单管理

范围与验收要点。

##### 前置依赖

- REQ-001。

#### REQ-003 通知中心

范围与验收要点。

##### 前置依赖

- REQ-002。

## 附录

#### NOTE-1 普通说明

这不是正式需求详情卡。
"""


def command(*args: str, cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=cwd, text=True, capture_output=True, check=check
    )


def commit(repository: Path, *paths: str, message: str = "test commit") -> None:
    command("add", "--", *paths, cwd=repository)
    command(
        "-c",
        "user.name=PCM Test",
        "-c",
        "user.email=pcm@example.invalid",
        "commit",
        "-m",
        message,
        cwd=repository,
    )


class RequirementRegistryTests(unittest.TestCase):
    def make_run(self, root: Path, markdown: str = BACKLOG) -> tuple[Path, Path, dict]:
        run_dir = root / "run"
        (run_dir / "steps").mkdir(parents=True)
        workspace_root = root / "workspace-root"
        workspace = workspace_root / "project"
        backlog = workspace / BACKLOG_PATH
        backlog.parent.mkdir(parents=True)
        backlog.write_text(markdown, encoding="utf-8")
        command("init", "-b", "main", cwd=workspace)
        commit(workspace, BACKLOG_PATH.as_posix(), message="docs: add backlog")
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
        return RequirementCatalog.model_validate({"requirements": requirements or RequirementRegistryTests.requirements()})

    def run_step(self, run_dir: Path, state: dict, **kwargs: object) -> dict:
        return asyncio.run(run(run_dir, state, **kwargs))

    def test_models_and_prompt_are_static_only(self) -> None:
        with self.assertRaises(ValidationError):
            BacklogExtractionInput.model_validate({"backlog_markdown": "x", "unexpected": True})
        with self.assertRaises(ValidationError):
            RequirementCatalog.model_validate(
                {"requirements": [{"id": "REQ-1", "title": "x", "order": 1, "depends_on": [], "status": "pending"}]}
            )
        self.assertEqual(
            RequirementStatic(id=" REQ-1 ", title=" 功能 ", order=1, depends_on=[" REQ-0 "]).model_dump(),
            {"id": "REQ-1", "title": "功能", "order": 1, "depends_on": ["REQ-0"]},
        )
        for identifier in ("REQ.001", "REQ/001", "../REQ-001"):
            with self.subTest(identifier=identifier), self.assertRaises(ValidationError):
                RequirementStatic(id=identifier, title="功能", order=1, depends_on=[])
        calls: list[dict] = []

        async def fake_model(config: object, **kwargs: object) -> RequirementCatalog:
            calls.append({"config": config, **kwargs})
            return self.catalog()

        extracted = asyncio.run(extract_requirements("# Backlog", object(), model_runner=fake_model))
        self.assertEqual(extracted, self.catalog())
        self.assertEqual(calls[0]["max_output_tokens"], 4096)
        self.assertEqual(calls[0]["max_retries"], 0)
        self.assertIs(calls[0]["input_model"].__class__, BacklogExtractionInput)  # type: ignore[index]
        self.assertIs(calls[0]["output_model"], RequirementCatalog)
        self.assertIn("<task>", SYSTEM_PROMPT)
        self.assertIn("<formal_requirement_rules>", SYSTEM_PROMPT)
        self.assertIn("<output>", SYSTEM_PROMPT)
        self.assertIn("严格 JSON", SYSTEM_PROMPT)
        self.assertIn("代码围栏", SYSTEM_PROMPT)
        for field in ("requirements", "id", "title", "order", "depends_on"):
            self.assertIn(field, SYSTEM_PROMPT)
        for forbidden in ("第 12 步", "PCM", "session", "Skill"):
            self.assertNotIn(forbidden, SYSTEM_PROMPT)

    def test_overview_dependencies_and_detail_cards_are_exact_sources(self) -> None:
        cards = formal_cards(BACKLOG)
        self.assertEqual(
            [(card.id, card.depends_on) for card in cards],
            [("REQ-001", ()), ("REQ-002", ("REQ-001",)), ("REQ-003", ("REQ-002",))],
        )
        mendmark_style = """## 5. 大需求总览
| 序号 | 需求 ID | 需求标题 | 前置依赖 |
| --- | --- | --- | --- |
| 1 | BR-001 | 账户 | 无。 |
| 2 | BR-002 | 订单 | - |
| 3 | BR-003 | 通知 | BR-001、BR-002 |

## 6. 需求详情
#### BR-001 账户
##### 前置依赖
无。
#### BR-002 订单
##### 前置依赖
-
#### BR-003 通知
##### 前置依赖
- BR-001。
- BR-002。
"""
        self.assertEqual(
            formal_cards(mendmark_style)[2].depends_on,
            ("BR-001", "BR-002"),
        )
        unknown_card = BACKLOG.replace(
            "## 附录",
            "#### REQ-004 未入总览\n\n范围与验收要点。\n\n## 附录",
        )
        out_of_order = (
            BACKLOG.replace("#### REQ-002", "#### TEMP")
            .replace("#### REQ-003", "#### REQ-002")
            .replace("#### TEMP", "#### REQ-003")
        )
        unknown_dependency = BACKLOG.replace("REQ-001 |\n| 3", "REQ-001、REQ-999 |\n| 3")
        missing_dependency_column = BACKLOG.replace("前置依赖", "说明")
        detail_writes_none = BACKLOG.replace("- REQ-001。", "无。", 1)
        missing_detail_dependency = BACKLOG.replace(
            "##### 前置依赖\n\n- REQ-001。\n\n", ""
        )
        duplicate_detail_dependency = BACKLOG.replace(
            "##### 前置依赖\n\n- REQ-001。\n\n#### REQ-003",
            "##### 前置依赖\n\n- REQ-001。\n\n##### 前置依赖\n\n- REQ-001。\n\n#### REQ-003",
        )
        detail_without_bullet = BACKLOG.replace("- REQ-001。", "REQ-001。", 1)
        detail_multiple_ids = BACKLOG.replace(
            "- REQ-001。", "- REQ-001、REQ-002。", 1
        )
        detail_explanation = BACKLOG.replace(
            "- REQ-001。", "- REQ-001（说明）", 1
        )
        for label, markdown in {
            "unknown-detail-card": unknown_card,
            "out-of-order-detail-card": out_of_order,
            "unknown-dependency": unknown_dependency,
            "missing-dependency-column": missing_dependency_column,
            "detail-writes-none": detail_writes_none,
            "missing-detail-dependency": missing_detail_dependency,
            "duplicate-detail-dependency": duplicate_detail_dependency,
            "detail-without-bullet": detail_without_bullet,
            "detail-multiple-ids": detail_multiple_ids,
            "detail-explanation": detail_explanation,
        }.items():
            with self.subTest(label=label), self.assertRaises(RuntimeError):
                formal_cards(markdown)

    def test_success_initializes_static_and_dynamic_catalog_without_product_writes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))
            backlog = workspace / BACKLOG_PATH
            before = (backlog.read_bytes(), command("rev-parse", "HEAD", cwd=workspace).stdout)
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
            self.assertEqual(saved["step"], STEP)
            self.assertEqual(saved["outputs"], [])
            self.assertEqual(saved["requirement_catalog"], self.requirements())
            self.assertEqual(saved["source"]["path"], BACKLOG_PATH.as_posix())
            self.assertEqual(len(calls), 1)
            completed = read_state(run_dir)
            self.assertEqual(
                (completed["phase"], completed["step"], completed["current_step"], completed["current_node"]),
                (PHASE, 13, 13, NEXT_NODE),
            )
            self.assertEqual(completed["active_requirement"], None)
            self.assertEqual(completed["requirement_cycle"], None)
            self.assertNotIn("phase_two", completed)
            self.assertNotIn("completed_requirements", completed)
            self.assertEqual(
                completed["requirement_registry"]["requirements"],
                [{**item, "status": "pending", "completion": None} for item in self.requirements()],
            )
            self.assertEqual((backlog.read_bytes(), command("rev-parse", "HEAD", cwd=workspace).stdout), before)

    def test_rejects_model_omissions_and_static_contract_violations(self) -> None:
        cases = {
            "missing": self.requirements()[:2],
            "invented": [*self.requirements()[:2], {"id": "REQ-999", "title": "虚构", "order": 3, "depends_on": []}],
            "duplicate-id": [self.requirements()[0], {"id": "REQ-001", "title": "订单管理", "order": 2, "depends_on": []}, self.requirements()[2]],
            "casefold-duplicate-id": [self.requirements()[0], {"id": "req-001", "title": "订单管理", "order": 2, "depends_on": []}, self.requirements()[2]],
            "duplicate-order": [self.requirements()[0], {**self.requirements()[1], "order": 1}, self.requirements()[2]],
            "non-continuous-order": [self.requirements()[0], {**self.requirements()[1], "order": 3}, {**self.requirements()[2], "order": 4}],
            "title-mismatch": [{**self.requirements()[0], "title": "不同标题"}, *self.requirements()[1:]],
            "missing-dependency": [self.requirements()[0], {**self.requirements()[1], "depends_on": []}, self.requirements()[2]],
            "dependency-order": [self.requirements()[0], self.requirements()[1], {**self.requirements()[2], "depends_on": ["REQ-001", "REQ-002"]}],
            "self-dependency": [{**self.requirements()[0], "depends_on": ["REQ-001"]}, *self.requirements()[1:]],
            "duplicate-dependency": [self.requirements()[0], {**self.requirements()[1], "depends_on": ["REQ-001", "REQ-001"]}, self.requirements()[2]],
            "cycle": [{**self.requirements()[0], "depends_on": ["REQ-003"]}, *self.requirements()[1:]],
        }
        for label, requirements in cases.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                run_dir, _workspace, state = self.make_run(Path(directory))

                async def fake_model(*args: object, **kwargs: object) -> RequirementCatalog:
                    return self.catalog(requirements)

                with self.assertRaises(RuntimeError):
                    self.run_step(run_dir, state, config_loader=lambda: object(), model_runner=fake_model)
                self.assertEqual(read_state(run_dir)["status"], "running")

    def test_rejects_unsafe_or_empty_backlog_outputs_before_model_execution(self) -> None:
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
                self.run_step(run_dir, state, config_loader=lambda: object(), model_runner=unexpected)

        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))
            (workspace / BACKLOG_PATH).write_text(" \n", encoding="utf-8")

            async def unexpected(*args: object, **kwargs: object) -> RequirementCatalog:
                raise AssertionError("空 Backlog 不得调用模型")

            with self.assertRaises(RuntimeError):
                self.run_step(run_dir, state, config_loader=lambda: object(), model_runner=unexpected)

    def test_rejects_non_main_dirty_and_headless_root_facts(self) -> None:
        for mutation in ("branch", "dirty"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                run_dir, workspace, state = self.make_run(Path(directory))
                if mutation == "branch":
                    command("switch", "-c", "other", cwd=workspace)
                else:
                    (workspace / "dirty.txt").write_text("dirty", encoding="utf-8")

                async def unexpected(*args: object, **kwargs: object) -> RequirementCatalog:
                    raise AssertionError("Git 事实无效时不得调用模型")

                with self.assertRaises(RuntimeError):
                    self.run_step(run_dir, state, config_loader=lambda: object(), model_runner=unexpected)

        with tempfile.TemporaryDirectory() as directory:
            _run_dir, workspace, _state = self.make_run(Path(directory))
            with patch.object(
                registry_step,
                "_git_read",
                side_effect=[str(workspace), "main", "", ""],
            ):
                with self.assertRaisesRegex(RuntimeError, "HEAD"):
                    _root_main_sha(workspace, BACKLOG_PATH.as_posix())

    def test_step_eleven_handoff_and_legacy_select_node_are_not_accepted(self) -> None:
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

            with patch.object(registry_step, "write_state", side_effect=interrupt_final_state):
                with self.assertRaises(OSError):
                    self.run_step(run_dir, state, config_loader=lambda: object(), model_runner=fake_model)
            saved = json.loads((run_dir / "steps/12.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["status"], "success")
            self.assertEqual(read_state(run_dir)["current_node"], CURRENT_NODE)

            async def unexpected(*args: object, **kwargs: object) -> RequirementCatalog:
                raise AssertionError("恢复不得调用模型")

            recovered = self.run_step(run_dir, read_state(run_dir), model_runner=unexpected)
            self.assertEqual(recovered, saved)
            self.assertEqual(read_state(run_dir)["current_node"], NEXT_NODE)

    def test_advanced_idempotence_and_source_catalog_registry_drift_fail(self) -> None:
        for mutation in ("hash", "root-sha", "catalog", "registry"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                run_dir, workspace, state = self.make_run(Path(directory))

                async def fake_model(*args: object, **kwargs: object) -> RequirementCatalog:
                    return self.catalog()

                self.run_step(run_dir, state, config_loader=lambda: object(), model_runner=fake_model)
                completed = read_state(run_dir)

                async def unexpected(*args: object, **kwargs: object) -> RequirementCatalog:
                    raise AssertionError("完整成功重跑不得调用模型")

                if mutation == "hash":
                    (workspace / BACKLOG_PATH).write_text(BACKLOG + "\n", encoding="utf-8")
                    commit(workspace, BACKLOG_PATH.as_posix(), message="docs: change backlog")
                elif mutation == "root-sha":
                    (workspace / "README.md").write_text("change", encoding="utf-8")
                    commit(workspace, "README.md", message="docs: change root")
                elif mutation == "catalog":
                    saved = json.loads((run_dir / "steps/12.json").read_text(encoding="utf-8"))
                    saved["requirement_catalog"][0]["title"] = "冲突标题"
                    write_json(run_dir / "steps/12.json", saved)
                else:
                    completed["requirement_registry"]["requirements"][0]["status"] = "active"
                    write_state(run_dir, completed)

                with self.assertRaises(RuntimeError):
                    self.run_step(run_dir, read_state(run_dir), model_runner=unexpected)

        with tempfile.TemporaryDirectory() as directory:
            run_dir, _workspace, state = self.make_run(Path(directory))

            async def fake_model(*args: object, **kwargs: object) -> RequirementCatalog:
                return self.catalog()

            self.run_step(run_dir, state, config_loader=lambda: object(), model_runner=fake_model)

            async def unexpected(*args: object, **kwargs: object) -> RequirementCatalog:
                raise AssertionError("幂等重跑不得调用模型")

            repeated = self.run_step(run_dir, read_state(run_dir), model_runner=unexpected)
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

            saved = self.run_step(run_dir, read_state(run_dir), config_loader=lambda: object(), model_runner=fake_model)
            self.assertEqual(saved["status"], "success")

        with tempfile.TemporaryDirectory() as directory:
            run_dir, _workspace, state = self.make_run(Path(directory))
            state["requirement_registry"] = {"schema_version": 1}
            write_state(run_dir, state)
            with self.assertRaises(RuntimeError):
                self.run_step(run_dir, read_state(run_dir))

    def test_production_git_reads_are_allowlisted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir, workspace, state = self.make_run(Path(directory))

            async def fake_model(*args: object, **kwargs: object) -> RequirementCatalog:
                return self.catalog()

            with patch.object(registry_step.subprocess, "run", wraps=subprocess.run) as mocked:
                self.run_step(run_dir, state, config_loader=lambda: object(), model_runner=fake_model)
            commands = [tuple(call.args[0][1:]) for call in mocked.call_args_list]
            allowed = {
                ("rev-parse", "--show-toplevel"),
                ("branch", "--show-current"),
                ("status", "--porcelain=v1", "--untracked-files=all"),
                ("ls-files", "--error-unmatch", "--", BACKLOG_PATH.as_posix()),
                ("rev-parse", "HEAD"),
            }
            self.assertTrue(commands)
            self.assertTrue(all(item in allowed for item in commands))
            self.assertFalse({"add", "commit", "switch", "checkout", "reset", "merge"} & {item[0] for item in commands})
            self.assertEqual(command("status", "--porcelain=v1", cwd=workspace).stdout, "")


if __name__ == "__main__":
    unittest.main()
