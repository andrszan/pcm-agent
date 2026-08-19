from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from common.claude_agent import ClaudeRunResult, run_claude
from common.decision import SYSTEM_PROMPT, request_decision
from common.files import sha256, write_json
from common.state import write_state
from config import LLMConfig

STEP = 3
NAME = "总体技术方案"
CONVERSATION_KEY = "solution_design"
SKILL_NAME = "solution-design"
CONVERSATION_PATH = Path("conversations/solution_design.json")
OUTPUTS = (
    Path("docs/design/技术方案.md"),
    Path("docs/design/基础工程来源.json"),
)
TEMPLATE_INPUTS = ("repositories.yaml", "templates.yaml")
MAX_DECISION_ROUNDS = 6
SOLUTION_DESIGN_MAX_BUDGET_USD = 4.0
COMPLETION_MESSAGE = "已完成 solution-design，总体技术方案和基础工程来源选择结果均已生成。"


class SolutionDesignBlocked(RuntimeError):
    def __init__(self, reason: str, required_inputs: list[str]):
        super().__init__(reason)
        self.required_inputs = required_inputs


def result(
    status: str,
    summary: str,
    *,
    blocked: dict[str, Any] | None = None,
    error: dict[str, Any] | None = None,
    outputs: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "step": STEP,
        "name": NAME,
        "status": status,
        "summary": summary,
        "applicable": True,
        "outputs": outputs or [],
        "blocked": blocked,
        "error": error,
    }


def _read_non_empty(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f"输入文件不存在或不可读：{path}")
    content = path.read_text(encoding="utf-8")
    if not content.strip():
        raise RuntimeError(f"输入文件为空：{path}")
    return content


def validate_inputs(state: dict[str, Any], template_assets: Path) -> tuple[Path, dict[str, str]]:
    current_step = state.get("current_step")
    if current_step not in {2, 3} or (current_step == 2 and state.get("status") != "success"):
        raise RuntimeError("第 2 步尚未成功，不能执行第 3 步")
    workspace_value = state.get("workspace", {}).get("final_path")
    if not workspace_value:
        raise RuntimeError("运行状态缺少产品工作区路径")
    workspace = Path(workspace_value)
    if not workspace.is_dir():
        raise RuntimeError(f"产品工作区不存在：{workspace}")

    inputs = {
        "docs/requirements/项目需求说明.md": _read_non_empty(
            workspace / "docs/requirements/项目需求说明.md"
        ),
        "docs/requirements/产品功能说明.md": _read_non_empty(
            workspace / "docs/requirements/产品功能说明.md"
        ),
    }
    if template_assets.is_symlink() or not template_assets.is_dir():
        raise RuntimeError(f"基础模板资产目录不存在或不可读：{template_assets}")
    for name in TEMPLATE_INPUTS:
        inputs[name] = _read_non_empty(template_assets / name)
    return workspace, inputs


def output_contents(workspace: Path) -> dict[str, str] | None:
    contents: dict[str, str] = {}
    for relative in OUTPUTS:
        path = workspace / relative
        try:
            content = _read_non_empty(path)
        except (OSError, UnicodeError, RuntimeError):
            return None
        if relative.suffix == ".json":
            try:
                data = json.loads(content)
            except json.JSONDecodeError:
                return None
            if not isinstance(data, dict) or not all(
                isinstance(data.get(unit), dict)
                and all(data[unit].get(field) for field in (
                    "target_path",
                    "repository_id",
                    "template_id",
                    "template_path",
                    "adoption",
                ))
                for unit in ("frontend", "backend")
            ):
                return None
        contents[str(relative)] = content
    return contents


def safe_result(run: ClaudeRunResult) -> dict[str, Any]:
    return {
        "subtype": run.result_subtype,
        "is_error": run.is_error,
        "stop_reason": run.stop_reason,
        "session_id": run.session_id,
        "num_turns": run.num_turns,
        "total_cost_usd": run.total_cost_usd,
        "exception": run.exception,
    }


def save_agent_update(run_dir: Path, state: dict[str, Any], run: ClaudeRunResult) -> None:
    previous_session = state.get("claude_sessions", {}).get(CONVERSATION_KEY)
    if previous_session and run.session_id and previous_session != run.session_id:
        raise RuntimeError(
            f"恢复 session ID 不一致：期望 {previous_session}，实际 {run.session_id}"
        )
    if run.session_id:
        state.setdefault("claude_sessions", {})[CONVERSATION_KEY] = run.session_id
    design = state.setdefault("solution_design", {})
    if run.init:
        skills = {str(item) for item in run.init.get("skills") or []}
        commands = {str(item) for item in run.init.get("slash_commands") or []}
        design["skill_loaded"] = SKILL_NAME in skills
        design["slash_command_loaded"] = SKILL_NAME in commands
        design["init"] = {
            key: run.init.get(key)
            for key in ("cwd", "model", "permissionMode", "claude_code_version")
        }
    if run.result_subtype:
        design["last_agent_result"] = safe_result(run)
    write_state(run_dir, state)


def load_conversation(run_dir: Path, state: dict[str, Any]) -> list[dict[str, str]]:
    reference = state.get("decision_conversations", {}).get(CONVERSATION_KEY)
    if reference is None:
        return [{"role": "system", "content": SYSTEM_PROMPT}]
    if set(reference) != {"path", "turn"} or reference["path"] != str(CONVERSATION_PATH):
        raise RuntimeError("决策历史引用不符合约定")
    data = json.loads((run_dir / CONVERSATION_PATH).read_text(encoding="utf-8"))
    messages = data.get("messages")
    if not isinstance(messages, list) or not messages:
        raise RuntimeError("决策历史内容不符合约定")
    return messages


def save_conversation(
    run_dir: Path,
    state: dict[str, Any],
    messages: list[dict[str, str]],
    *,
    decision_turn: int | None = None,
) -> None:
    path = run_dir / CONVERSATION_PATH
    path.parent.mkdir(exist_ok=True)
    write_json(path, {"messages": messages})
    if decision_turn is None:
        decision_turn = (
            state.get("decision_conversations", {})
            .get(CONVERSATION_KEY, {})
            .get("turn", 0)
        )
    state.setdefault("decision_conversations", {})[CONVERSATION_KEY] = {
        "path": str(CONVERSATION_PATH),
        "turn": decision_turn,
    }
    write_state(run_dir, state)


def append_initial_agent_prompt(
    run_dir: Path, state: dict[str, Any], prompt: str
) -> None:
    messages = load_conversation(run_dir, state)
    if len(messages) == 1:
        messages.append({"role": "assistant", "content": prompt})
        save_conversation(run_dir, state, messages)


def append_completion(
    run_dir: Path,
    state: dict[str, Any],
    messages: list[dict[str, str]],
    agent_text: str,
) -> None:
    messages.append({"role": "user", "content": agent_text})
    messages.append({"role": "assistant", "content": COMPLETION_MESSAGE})
    save_conversation(run_dir, state, messages)


def decision_context(
    inputs: dict[str, str],
    template_assets: Path,
    agent_text: str,
    outputs: dict[str, str] | None,
) -> str:
    allowed = dict(inputs)
    if outputs:
        allowed.update(outputs)
    return json.dumps(
        {
            "step": STEP,
            "name": NAME,
            "completion": "solution-design 正常结束且两份默认产物真实存在并可读",
            "template_assets": str(template_assets),
            "allowed_inputs": allowed,
            "agent_result": agent_text,
            "outputs_present": outputs is not None,
        },
        ensure_ascii=False,
    )


def decision_prompt(decision: dict[str, Any]) -> str:
    action = decision["action"]
    if action == "approve":
        return (
            "作为 PCM 的等效开发者授权，我现在明确同意创建或更新 solution-design 的正式技术方案和基础工程来源结果。"
            "请按已确认决定完成当前步骤。"
        )
    if action == "continue":
        return "继续使用当前已有事实完成同一个 solution-design 步骤，不扩大输入范围。"
    return f"PCM 决定：{decision['answer']}\n理由：{decision['reason']}\n请据此继续当前步骤。"


def initial_prompt(workspace: Path, template_assets: Path) -> str:
    return (
        "/solution-design 请基于第 2 步产品定义和必需的基础模板资产完成当前 PCM 第 3 步。\n"
        f"产品工作区：{workspace}\n"
        f"基础模板资产入口：{template_assets}\n"
        "请读取 docs/requirements/项目需求说明.md、docs/requirements/产品功能说明.md，"
        "以及模板入口中的 repositories.yaml、templates.yaml 和本次选型所需的候选模板说明。\n"
        "完成总体技术方案和前后端基础模板选型后，在获得 PCM 等效开发者确认时写入："
        "docs/design/技术方案.md 和 docs/design/基础工程来源.json。\n"
        "基础工程来源 JSON 必须包含 frontend、backend 两个对象，每个对象至少包含 "
        "target_path、repository_id、template_id、template_path、adoption 字段。"
        "本步骤不获取、复制或组装模板内容，不处理项目化、工程架构、Backlog 或具体业务实现。"
    )


async def run(
    run_dir: Path,
    state: dict[str, Any],
    template_assets: Path,
    *,
    agent_runner=run_claude,
    decision_runner=request_decision,
) -> dict[str, Any]:
    template_assets = template_assets.resolve()
    workspace, inputs = validate_inputs(state, template_assets)
    existing_outputs = output_contents(workspace)
    previous_result = state.get("solution_design", {}).get("last_agent_result", {})
    if (
        state.get("status") == "success"
        and previous_result.get("subtype") == "success"
        and previous_result.get("is_error") is False
        and existing_outputs is not None
    ):
        state.setdefault("solution_design", {}).pop("pending_agent_prompt", None)
        write_state(run_dir, state)
        return result(
            "success",
            "solution-design 已生成技术方案，确认既有成功。",
            outputs=[str(workspace / relative) for relative in OUTPUTS],
        )

    design = state.setdefault("solution_design", {})
    recorded_assets = design.get("template_assets")
    if recorded_assets and Path(recorded_assets) != template_assets:
        raise RuntimeError("基础模板资产与已有运行记录不一致")
    design["template_assets"] = str(template_assets)
    design["template_inputs"] = {
        name: sha256(template_assets / name) for name in TEMPLATE_INPUTS
    }
    state.update({"current_step": STEP, "status": "running", "blocked": None, "error": None})
    write_state(run_dir, state)

    existing_session = state.get("claude_sessions", {}).get(CONVERSATION_KEY)
    pending = design.pop("pending_agent_prompt", None)
    prompt = pending or (
        initial_prompt(workspace, template_assets)
        if not existing_session
        else "重新核验当前产品定义、模板资产和 solution-design 产物事实，继续完成当前步骤。"
    )

    if not existing_session:
        append_initial_agent_prompt(run_dir, state, prompt)

    for _ in range(MAX_DECISION_ROUNDS + 1):
        pending = design.pop("pending_agent_prompt", None)
        if pending:
            prompt = pending
            write_state(run_dir, state)
        run_result = await agent_runner(
            prompt,
            cwd=workspace,
            skill=SKILL_NAME,
            resume_session_id=state.get("claude_sessions", {}).get(CONVERSATION_KEY),
            max_budget_usd=SOLUTION_DESIGN_MAX_BUDGET_USD,
            on_update=lambda update: save_agent_update(run_dir, state, update),
        )
        save_agent_update(run_dir, state, run_result)
        if not run_result.result_subtype:
            raise RuntimeError(run_result.exception or "Agent SDK 未返回 ResultMessage")
        if run_result.exception and run_result.result_subtype not in {
            "error_max_turns",
            "error_max_budget_usd",
        }:
            raise RuntimeError(run_result.exception)
        if run_result.is_error and run_result.result_subtype not in {
            "error_max_turns",
            "error_max_budget_usd",
        }:
            raise RuntimeError(f"Agent SDK 执行失败：{run_result.result_subtype}")
        init = run_result.init or {}
        if SKILL_NAME not in {str(item) for item in init.get("skills") or []}:
            raise RuntimeError("Agent SDK 未加载 solution-design Skill")
        if SKILL_NAME not in {str(item) for item in init.get("slash_commands") or []}:
            raise RuntimeError("Agent SDK 未加载 solution-design slash command")

        outputs = output_contents(workspace)
        messages = load_conversation(run_dir, state)
        if (
            run_result.result_subtype == "success"
            and not run_result.is_error
            and outputs is not None
        ):
            append_completion(run_dir, state, messages, run_result.text)
            state.update({"status": "success", "blocked": None, "error": None})
            design.pop("pending_agent_prompt", None)
            write_state(run_dir, state)
            return result(
                "success",
                "solution-design 已生成总体技术方案和基础工程来源选择结果。",
                outputs=[str(workspace / relative) for relative in OUTPUTS],
            )

        session_id = state.get("claude_sessions", {}).get(CONVERSATION_KEY)
        if not session_id:
            raise RuntimeError("Agent 未完成且没有可恢复的 session ID")
        messages = load_conversation(run_dir, state)
        messages.append(
            {
                "role": "user",
                "content": decision_context(inputs, template_assets, run_result.text, outputs),
            }
        )
        decision, _, raw = await decision_runner(messages, LLMConfig.load())
        prompt = decision_prompt(decision)
        messages.append(
            {
                "role": "assistant",
                "content": f"{raw}\n\n发送给 Claude Agent SDK 的指令：\n{prompt}",
            }
        )
        current_turn = (
            state.get("decision_conversations", {})
            .get(CONVERSATION_KEY, {})
            .get("turn", 0)
        )
        save_conversation(run_dir, state, messages, decision_turn=current_turn + 1)
        if decision["action"] == "blocked":
            raise SolutionDesignBlocked(decision["reason"], decision["required_inputs"])
        design["pending_agent_prompt"] = prompt
        write_state(run_dir, state)

    raise RuntimeError("solution-design 决策循环达到上限仍未产生产物")
