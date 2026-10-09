from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.frontend_scope import (
    FRONTEND_PLUGIN_FILES,
    FRONTEND_SKILL_FILES,
    PROTOTYPE_ENTRY,
    FrontendScope,
    classify_frontend_scope,
    ensure_frontend_capabilities,
    validate_frontend_scope,
    validate_prototype,
)


class FrontendScopeTests(unittest.IsolatedAsyncioTestCase):
    async def test_passes_complete_context_to_existing_structured_client(self) -> None:
        context = "产品定义\n" + "完整资料，不能截断。" * 1000
        config = object()
        parser = AsyncMock(return_value=FrontendScope(applicable=True, reason="存在预约界面"))
        with patch("common.frontend_scope.parse_response", parser):
            scope = await classify_frontend_scope(config, purpose="prototype", context=context)
        self.assertEqual(scope, {"applicable": True, "reason": "存在预约界面"})
        self.assertIs(parser.call_args.args[0], config)
        self.assertEqual(parser.call_args.kwargs["input_model"].context, context)
        self.assertEqual(parser.call_args.kwargs["input_model"].purpose, "prototype")
        self.assertIs(parser.call_args.kwargs["output_model"], FrontendScope)

    async def test_request_failure_is_not_not_applicable(self) -> None:
        with patch("common.frontend_scope.parse_response", side_effect=RuntimeError("请求失败")):
            with self.assertRaises(RuntimeError):
                await classify_frontend_scope(object(), purpose="requirement", context="需求 TRD")

    def test_scope_rejects_non_boolean_empty_reason_and_unknown_fields(self) -> None:
        for value in [
            {"applicable": "false", "reason": "后端"},
            {"applicable": 0, "reason": "后端"},
            {"applicable": False, "reason": "  "},
            {"applicable": False, "reason": "后端", "extra": True},
            None,
        ]:
            with self.subTest(value=value), self.assertRaises(ValidationError):
                validate_frontend_scope(value)
        self.assertEqual(
            validate_frontend_scope({"applicable": False, "reason": "纯后端规则"}),
            {"applicable": False, "reason": "纯后端规则"},
        )

    def test_prototype_entry_is_fixed_and_not_applicable_has_no_entry(self) -> None:
        for applicable, entry in [(True, PROTOTYPE_ENTRY.as_posix()), (False, None)]:
            value = {"applicable": applicable, "entry": entry, "reason": "已判断"}
            self.assertEqual(validate_prototype(value), value)
        for entry in ["../index.html", "/tmp/index.html", None]:
            with self.subTest(entry=entry), self.assertRaises(ValueError):
                validate_prototype({"applicable": True, "entry": entry, "reason": "有界面"})
        with self.assertRaises(ValueError):
            validate_prototype({"applicable": False, "entry": PROTOTYPE_ENTRY.as_posix(), "reason": "无界面"})

    def test_capabilities_are_complete_and_locked_inside_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in FRONTEND_SKILL_FILES:
                path = root / ".claude/skills/frontend-ui-ux" / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("受控能力", encoding="utf-8")
            plugin = root / ".agents/plugins/ui-ux-pro-max"
            (plugin / ".claude-plugin").mkdir(parents=True)
            (plugin / ".claude-plugin/plugin.json").write_text('{"name":"ui-ux-pro-max","skills":"./.claude/skills/"}', encoding="utf-8")
            for name in FRONTEND_PLUGIN_FILES:
                skill = plugin / ".claude/skills/ui-ux-pro-max" / name
                skill.parent.mkdir(parents=True, exist_ok=True)
                skill.write_text("插件能力", encoding="utf-8")
            role = root / ".claude/agents/dev.md"
            role.parent.mkdir(parents=True)
            role.write_text("---\nname: dev\ntools: Read, Skill\n---\n开发角色\n", encoding="utf-8")
            lock = root / "plugins-lock.json"
            lock.write_text(json.dumps({"version": 1, "plugins": [{"id": "ui-ux-pro-max@test", "path": ".agents/plugins/ui-ux-pro-max"}]}), encoding="utf-8")
            ensure_frontend_capabilities(root)
            manifest = plugin / ".claude-plugin/plugin.json"
            manifest.write_text('{"name":"ui-ux-pro-max","skills":"missing"}', encoding="utf-8")
            with self.assertRaises(RuntimeError):
                ensure_frontend_capabilities(root)
            manifest.write_text('{"name":"ui-ux-pro-max","skills":"./.claude/skills/"}', encoding="utf-8")
            search = plugin / ".claude/skills/ui-ux-pro-max/scripts/search.py"
            search.unlink()
            with self.assertRaises(RuntimeError):
                ensure_frontend_capabilities(root)
            search.write_text("插件搜索", encoding="utf-8")
            role.write_text("---\nname: dev\ntools: Read, Bash\n---\n开发角色\n", encoding="utf-8")
            with self.assertRaises(RuntimeError):
                ensure_frontend_capabilities(root)
            role.write_text("---\nname: dev\n---\n继承工具\n", encoding="utf-8")
            ensure_frontend_capabilities(root)
            target = root / ".claude/skills/frontend-ui-ux/references/plugin-usage.md"
            original = target.read_text()
            target.unlink()
            with self.assertRaises(RuntimeError):
                ensure_frontend_capabilities(root)
            outside = root.parent / (root.name + "-outside.md")
            try:
                outside.write_text(original, encoding="utf-8")
                target.symlink_to(outside)
                with self.assertRaises(RuntimeError):
                    ensure_frontend_capabilities(root)
                target.unlink()
                target.write_text(original, encoding="utf-8")
            finally:
                outside.unlink(missing_ok=True)
            lock.write_text('{"version":1,"plugins":[]}', encoding="utf-8")
            with self.assertRaises(RuntimeError):
                ensure_frontend_capabilities(root)
