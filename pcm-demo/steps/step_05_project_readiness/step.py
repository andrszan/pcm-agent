from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from common.claude_agent import ClaudeRunResult, run_claude
from common.decision import Decision, SYSTEM_PROMPT, request_decision
from common.files import resolve_workspace_output, write_json
from common.state import write_state, write_step_result
from config import LLMConfig, load_dev_resource_list
from steps.step_03_foundation_selection.step import FoundationSelectionResult
from steps.step_04_assemble_foundation.step import (
    temporary_root,
    verify_existing_success,
    workspace_from_state,
)

STEP = 5
NAME = "核验项目准备状态"
CURRENT_NODE = "project:05_verify_readiness"
NEXT_NODE = "project:06_bootstrap_foundation"
CONVERSATION_KEY = "project_readiness"
SKILL_NAME = "project-readiness"
CONVERSATION_PATH = Path("conversations/project_readiness.json")
CHECKLIST = Path("docs/requirements/项目准备清单.md")
MAX_DECISION_ROUNDS = 6
PROJECT_READINESS_MAX_TURNS = 24
PROJECT_READINESS_MAX_BUDGET_USD = 8.0
COMPLETION_MESSAGE = "已完成 project-readiness：项目准备清单已生成并通过文件事实核验。"


class ProjectReadinessBlocked(RuntimeError):
    def __init__(
        self,
        reason: str,
        required_inputs: list[str],
        outputs: list[str] | None = None,
    ):
        super().__init__(reason)
        self.required_inputs = required_inputs
        self.outputs = outputs or []


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


def checklist_present(workspace: Path) -> bool:
    try:
        path = resolve_workspace_output(workspace, CHECKLIST.as_posix())
    except ValueError:
        return False
    current = workspace
    for part in CHECKLIST.parts:
        current /= part
        if current.is_symlink():
            return False
    if not path.is_file():
        return False
    try:
        return bool(path.read_text(encoding="utf-8").strip())
    except (OSError, UnicodeError):
        return False


def verify_existing_readiness_success(run_dir: Path) -> dict[str, Any]:
    try:
        existing = json.loads((run_dir / "steps" / "05.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RuntimeError("第 5 步成功结果不可读取") from error
    if (
        existing.get("step") != STEP
        or existing.get("status") != "success"
        or existing.get("outputs") != [CHECKLIST.as_posix()]
    ):
        raise RuntimeError("第 5 步成功结果不可复用")
    return existing


def load_product_outputs(run_dir: Path, workspace: Path) -> list[str]:
    try:
        previous = json.loads((run_dir / "steps" / "02.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RuntimeError("第 2 步产品定义结果不可读取") from error
    outputs = previous.get("outputs")
    if (
        previous.get("step") != 2
        or previous.get("status") != "success"
        or not isinstance(outputs, list)
        or len(outputs) != 2
        or any(not isinstance(output, str) or not output for output in outputs)
    ):
        raise RuntimeError("第 2 步结果缺少两份成功的产品定义产物")
    resolved: list[Path] = []
    for output in outputs:
        relative = Path(output)
        if ".." in relative.parts:
            raise RuntimeError("第 2 步产品定义产物路径不能包含 ..")
        current = workspace
        for part in relative.parts:
            current /= part
            if current.is_symlink():
                raise RuntimeError("第 2 步产品定义产物路径不能包含符号链接")
        try:
            path = resolve_workspace_output(workspace, output)
        except ValueError as error:
            raise RuntimeError("第 2 步产品定义产物路径不符合约定") from error
        if not path.is_file() or path.stat().st_size == 0:
            raise RuntimeError("第 2 步产品定义产物不是非空普通文件")
        resolved.append(path)
    if len({path.resolve() for path in resolved}) != 2:
        raise RuntimeError("第 2 步产品定义产物不能指向同一文件")
    return outputs


def load_selection(run_dir: Path) -> tuple[FoundationSelectionResult, dict[str, Any]]:
    try:
        previous = json.loads((run_dir / "steps" / "03.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RuntimeError("第 3 步选型结果不可读取") from error
    if previous.get("step") != 3 or previous.get("status") != "success":
        raise RuntimeError("第 3 步选型结果未成功完成")
    try:
        selection_data = previous["template_selection"]
        selection = FoundationSelectionResult.model_validate(selection_data)
    except (KeyError, ValueError) as error:
        raise RuntimeError("第 3 步模板选择不符合约定") from error
    if not isinstance(selection_data, dict):
        raise RuntimeError("第 3 步模板选择不符合约定")
    return selection, selection_data


def validate_inputs(
    run_dir: Path, state: dict[str, Any]
) -> tuple[Path, list[str], FoundationSelectionResult, dict[str, Any], dict[str, Any]]:
    position = (state.get("step"), state.get("current_step"), state.get("current_node"))
    if position not in {(STEP, STEP, CURRENT_NODE), (STEP + 1, STEP + 1, NEXT_NODE)}:
        raise RuntimeError("运行状态不位于项目准备核验锚点")
    workspace = workspace_from_state(state)
    product_outputs = load_product_outputs(run_dir, workspace)
    selection, selection_data = load_selection(run_dir)
    try:
        assembly = json.loads((run_dir / "steps" / "04.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RuntimeError("第 4 步组装结果不可读取") from error
    verify_existing_success(
        workspace,
        selection,
        assembly,
        temporary_root(workspace, str(state.get("run_id", ""))),
    )
    return workspace, product_outputs, selection, selection_data, assembly


def safe_result(run: ClaudeRunResult) -> dict[str, Any]:
    return {
        "subtype": run.result_subtype,
        "is_error": run.is_error,
        "stop_reason": run.stop_reason,
        "session_id": run.session_id,
        "num_turns": run.num_turns,
        "total_cost_usd": run.total_cost_usd,
        "exception": "Agent SDK 返回异常" if run.exception else None,
    }


def save_agent_update(run_dir: Path, state: dict[str, Any], run: ClaudeRunResult) -> None:
    previous_session = state.get("claude_sessions", {}).get(CONVERSATION_KEY)
    if previous_session and run.session_id and previous_session != run.session_id:
        raise RuntimeError(
            f"恢复 session ID 不一致：期望 {previous_session}，实际 {run.session_id}"
        )
    if run.session_id:
        state.setdefault("claude_sessions", {})[CONVERSATION_KEY] = run.session_id
    readiness = state.setdefault("project_readiness", {})
    if run.init:
        skills = {str(item) for item in run.init.get("skills") or []}
        commands = {str(item) for item in run.init.get("slash_commands") or []}
        readiness["skill_loaded"] = SKILL_NAME in skills
        readiness["slash_command_loaded"] = SKILL_NAME in commands
        readiness["init"] = {
            key: run.init.get(key)
            for key in ("cwd", "model", "permissionMode", "claude_code_version")
        }
    if run.result_subtype:
        readiness["last_agent_result"] = safe_result(run)
        readiness["pending_agent_text"] = run.text
    write_state(run_dir, state)


def load_conversation(run_dir: Path, state: dict[str, Any]) -> list[dict[str, str]]:
    reference = state.get("decision_conversations", {}).get(CONVERSATION_KEY)
    if reference is None:
        return [{"role": "system", "content": SYSTEM_PROMPT}]
    if set(reference) != {"path", "turn"} or reference["path"] != str(CONVERSATION_PATH):
        raise RuntimeError("决策历史引用不符合约定")
    try:
        data = json.loads((run_dir / CONVERSATION_PATH).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RuntimeError("决策历史不可读取") from error
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


def append_initial_agent_prompt(run_dir: Path, state: dict[str, Any], prompt: str) -> None:
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


def clear_pending_agent_text(run_dir: Path, state: dict[str, Any]) -> None:
    state.setdefault("project_readiness", {}).pop("pending_agent_text", None)
    write_state(run_dir, state)


def completion_recorded(messages: list[dict[str, str]], agent_text: str) -> bool:
    return (
        len(messages) >= 2
        and messages[-2] == {"role": "user", "content": agent_text}
        and messages[-1] == {"role": "assistant", "content": COMPLETION_MESSAGE}
    )


def last_decision(messages: list[dict[str, str]]) -> dict[str, Any] | None:
    if not messages or messages[-1].get("role") != "assistant":
        return None
    try:
        return Decision.model_validate_json(messages[-1]["content"]).model_dump()
    except ValueError:
        return None


def decision_turn(state: dict[str, Any]) -> int:
    turn = (
        state.get("decision_conversations", {})
        .get(CONVERSATION_KEY, {})
        .get("turn", 0)
    )
    if not isinstance(turn, int) or turn < 0:
        raise RuntimeError("决策历史轮次不符合约定")
    return turn


def conversation_decision_count(messages: list[dict[str, str]]) -> int:
    count = 0
    for message in messages:
        if message.get("role") != "assistant":
            continue
        try:
            Decision.model_validate_json(message["content"])
        except ValueError:
            continue
        count += 1
    return count


def synchronize_decision_turn(
    run_dir: Path,
    state: dict[str, Any],
    messages: list[dict[str, str]],
) -> int:
    recorded = decision_turn(state)
    actual = conversation_decision_count(messages)
    if recorded > actual:
        raise RuntimeError("决策历史轮次与消息内容不一致")
    if actual > recorded:
        state.setdefault("decision_conversations", {})[CONVERSATION_KEY] = {
            "path": str(CONVERSATION_PATH),
            "turn": actual,
        }
        write_state(run_dir, state)
    return actual


def require_decision_round(
    run_dir: Path,
    state: dict[str, Any],
    messages: list[dict[str, str]],
) -> int:
    turn = synchronize_decision_turn(run_dir, state, messages)
    if turn >= MAX_DECISION_ROUNDS:
        raise RuntimeError("project-readiness 决策循环达到上限仍未完成")
    return turn


def append_agent_reply(
    run_dir: Path,
    state: dict[str, Any],
    messages: list[dict[str, str]],
    agent_text: str,
) -> None:
    messages.append({"role": "user", "content": agent_text})
    save_conversation(run_dir, state, messages)


def advance_success(
    run_dir: Path,
    state: dict[str, Any],
    messages: list[dict[str, str]],
    agent_text: str,
) -> dict[str, Any]:
    if not completion_recorded(messages, agent_text):
        append_completion(run_dir, state, messages, agent_text)
    state.setdefault("project_readiness", {}).pop("pending_agent_prompt", None)
    state.setdefault("project_readiness", {}).pop("pending_agent_text", None)
    state.update(
        {
            "status": "success",
            "phase": "project_initialization",
            "step": STEP + 1,
            "current_step": STEP + 1,
            "current_node": NEXT_NODE,
            "blocked": None,
            "error": None,
        }
    )
    saved = result(
        "success", "project-readiness 已生成项目准备清单。", outputs=[CHECKLIST.as_posix()]
    )
    write_step_result(run_dir, STEP, saved)
    write_state(run_dir, state)
    return saved


def initial_prompt(
    product_outputs: list[str],
    assembly_outputs: list[str],
    selection_data: dict[str, Any],
    resource_list: Path,
) -> str:
    product_references = "\n".join(f"- @./{output}" for output in product_outputs)
    assembly_references = (
        "\n".join(f"- @./{output}" for output in assembly_outputs)
        if assembly_outputs
        else "- 当前产品没有适用的已组装工程。"
    )
    selection_json = json.dumps(selection_data, ensure_ascii=False, indent=2)
    return f"""/project-readiness
调用方已要求并同意直接生成或更新 `docs/requirements/项目准备清单.md`。请基于当前项目事实完成该清单，并用工具核验结果。

产品定义：
{product_references}

已组装工程路径：
{assembly_references}

完整模板选择 JSON：
```json
{selection_json}
```

可信开发资源清单：@{resource_list}
可以原样读取该资源清单；可按其提供的可信开发资源写入被 Git 忽略的实际 `.env`，并使用工具验证。允许使用清单中已有的本地开发权限创建当前项目专用开发库和可丢弃测试库，但不得创建生产资源。

本清单用于判断当前工程是否具备进入基础工程项目化的前提。依赖安装、构建、测试、启动和最小联调属于随后要执行的项目化工作；前后端独立 Git 初始化和首次提交属于后续显式 Git 工作；业务功能、初始化业务数据和完整浏览器验收属于后续开发工作。不得把这些尚未执行的后续工作标记为当前准备阻塞。两份产品定义是当前产品范围的权威来源，不得因更早的产品初稿表述差异阻塞本次准备核验。

当前开发必需的外部资源、访问条件和本地配置均已 `ready` 或 `not-applicable` 时，明确说明核验完成；只有实际缺少不可替代外部资源时才明确返回阻塞。
不得将任何秘密写入准备清单、回复、日志或提交。不得 stage、commit 或 push。"""


def resume_prompt(product_outputs: list[str], resource_list: Path) -> str:
    references = "、".join(f"@./{output}" for output in product_outputs)
    return (
        f"请重新读取 {references} 和可信开发资源清单 @{resource_list}，核验当前项目事实并继续完成项目准备清单。"
        "请补齐和验证当前开发必需的外部资源、访问条件与本地配置；依赖安装、构建、测试、启动、独立 Git 初始化、业务实现和完整验收属于后续工作，不作为本次准备阻塞。"
    )


async def run(
    run_dir: Path,
    state: dict[str, Any],
    *,
    agent_runner=run_claude,
    decision_runner=request_decision,
    config_loader=LLMConfig.load,
    resource_loader=load_dev_resource_list,
) -> dict[str, Any]:
    workspace, product_outputs, _selection, selection_data, assembly = validate_inputs(
        run_dir, state
    )
    previous_result = state.get("project_readiness", {}).get("last_agent_result", {})
    position = (state.get("step"), state.get("current_step"), state.get("current_node"))
    successful_agent_and_checklist = (
        previous_result.get("subtype") == "success"
        and previous_result.get("is_error") is False
        and checklist_present(workspace)
    )
    if position == (STEP + 1, STEP + 1, NEXT_NODE) and state.get("status") == "success":
        if not successful_agent_and_checklist:
            raise RuntimeError("第 5 步成功现场不完整")
        verify_existing_readiness_success(run_dir)
        state.setdefault("project_readiness", {}).pop("pending_agent_prompt", None)
        state.setdefault("project_readiness", {}).pop("pending_agent_text", None)
        write_state(run_dir, state)
        return result(
            "success",
            "project-readiness 已生成项目准备清单，确认既有成功。",
            outputs=[CHECKLIST.as_posix()],
        )

    if (
        position == (STEP, STEP, CURRENT_NODE)
        and successful_agent_and_checklist
        and (run_dir / "steps" / "05.json").is_file()
    ):
        existing = verify_existing_readiness_success(run_dir)
        state.setdefault("project_readiness", {}).pop("pending_agent_prompt", None)
        state.setdefault("project_readiness", {}).pop("pending_agent_text", None)
        state.update(
            {
                "status": "success",
                "phase": "project_initialization",
                "step": STEP + 1,
                "current_step": STEP + 1,
                "current_node": NEXT_NODE,
                "blocked": None,
                "error": None,
            }
        )
        write_state(run_dir, state)
        return existing

    if position == (STEP, STEP, CURRENT_NODE) and successful_agent_and_checklist:
        pending_agent_text = state.get("project_readiness", {}).get("pending_agent_text")
        if not isinstance(pending_agent_text, str):
            raise RuntimeError("Agent 成功结果缺少可恢复的完整回复")
        return advance_success(
            run_dir,
            state,
            load_conversation(run_dir, state),
            pending_agent_text,
        )

    if position != (
        STEP,
        STEP,
        CURRENT_NODE,
    ):
        raise RuntimeError("运行状态不位于项目准备核验锚点")
    resource_list, _ = resource_loader()
    state.update({"current_step": STEP, "status": "running", "blocked": None, "error": None})
    write_state(run_dir, state)
    existing_session = state.get("claude_sessions", {}).get(CONVERSATION_KEY)
    messages = load_conversation(run_dir, state)
    synchronize_decision_turn(run_dir, state, messages)
    pending = state.get("project_readiness", {}).pop("pending_agent_prompt", None)
    if pending is not None and (not isinstance(pending, str) or not pending):
        raise RuntimeError("待恢复 Agent 提示不符合约定")
    if not pending and existing_session and messages[-1].get("role") == "user":
        current_turn = require_decision_round(run_dir, state, messages)
        state.setdefault("project_readiness", {}).pop("pending_agent_text", None)
        write_state(run_dir, state)
        try:
            decision, _, raw = await decision_runner(messages, config_loader())
        except Exception:
            raise RuntimeError("AI-compatible 决策失败") from None
        messages.append({"role": "assistant", "content": raw})
        save_conversation(run_dir, state, messages, decision_turn=current_turn + 1)
        if decision["action"] == "blocked":
            raise ProjectReadinessBlocked(
                decision["reason"],
                decision["required_inputs"],
                [CHECKLIST.as_posix()] if checklist_present(workspace) else [],
            )
        pending = decision["answer"]
        state.setdefault("project_readiness", {})["pending_agent_prompt"] = pending
        state.setdefault("project_readiness", {}).pop("pending_agent_text", None)
        write_state(run_dir, state)
    if not pending and existing_session:
        recovered_decision = last_decision(messages)
        if recovered_decision:
            if recovered_decision["action"] == "blocked":
                raise ProjectReadinessBlocked(
                    recovered_decision["reason"],
                    recovered_decision["required_inputs"],
                    [CHECKLIST.as_posix()] if checklist_present(workspace) else [],
                )
            pending = recovered_decision["answer"]
            state.setdefault("project_readiness", {})["pending_agent_prompt"] = pending
            write_state(run_dir, state)
    if pending:
        prompt = pending
        write_state(run_dir, state)
    elif existing_session:
        prompt = resume_prompt(product_outputs, resource_list)
    else:
        prompt = initial_prompt(product_outputs, assembly["outputs"], selection_data, resource_list)
        append_initial_agent_prompt(run_dir, state, prompt)

    for _ in range(MAX_DECISION_ROUNDS):
        run_result = await agent_runner(
            prompt,
            cwd=workspace,
            resume_session_id=state.get("claude_sessions", {}).get(CONVERSATION_KEY),
            max_turns=PROJECT_READINESS_MAX_TURNS,
            max_budget_usd=PROJECT_READINESS_MAX_BUDGET_USD,
            on_update=lambda update: save_agent_update(run_dir, state, update),
        )
        save_agent_update(run_dir, state, run_result)
        if not run_result.result_subtype:
            raise RuntimeError("Agent SDK 未返回 ResultMessage")
        recoverable_subtypes = {"error_max_turns", "error_max_budget_usd"}
        if run_result.exception and run_result.result_subtype not in recoverable_subtypes:
            clear_pending_agent_text(run_dir, state)
            raise RuntimeError("Agent SDK 执行异常")
        if run_result.is_error and run_result.result_subtype not in recoverable_subtypes:
            clear_pending_agent_text(run_dir, state)
            raise RuntimeError(f"Agent SDK 执行失败：{run_result.result_subtype}")
        init = run_result.init or {}
        init_cwd = init.get("cwd")
        if not isinstance(init_cwd, str) or Path(init_cwd).resolve() != workspace:
            clear_pending_agent_text(run_dir, state)
            raise RuntimeError("Agent SDK 实际工作目录与产品项目根不一致")
        if SKILL_NAME not in {str(item) for item in init.get("skills") or []}:
            clear_pending_agent_text(run_dir, state)
            raise RuntimeError("Agent SDK 未加载 project-readiness Skill")
        if SKILL_NAME not in {str(item) for item in init.get("slash_commands") or []}:
            clear_pending_agent_text(run_dir, state)
            raise RuntimeError("Agent SDK 未加载 project-readiness slash command")
        messages = load_conversation(run_dir, state)
        present = checklist_present(workspace)
        if (
            run_result.result_subtype == "success"
            and not run_result.is_error
            and present
        ):
            try:
                validate_inputs(run_dir, state)
            except Exception:
                clear_pending_agent_text(run_dir, state)
                raise
            return advance_success(run_dir, state, messages, run_result.text)

        session_id = state.get("claude_sessions", {}).get(CONVERSATION_KEY)
        if not session_id:
            clear_pending_agent_text(run_dir, state)
            raise RuntimeError("Agent 未完成且没有可恢复的 session ID")
        append_agent_reply(run_dir, state, messages, run_result.text)
        state.setdefault("project_readiness", {}).pop("pending_agent_text", None)
        write_state(run_dir, state)
        current_turn = require_decision_round(run_dir, state, messages)
        try:
            decision, _, raw = await decision_runner(messages, config_loader())
        except Exception:
            raise RuntimeError("AI-compatible 决策失败") from None
        messages.append({"role": "assistant", "content": raw})
        save_conversation(run_dir, state, messages, decision_turn=current_turn + 1)
        if decision["action"] == "blocked":
            raise ProjectReadinessBlocked(
                decision["reason"],
                decision["required_inputs"],
                [CHECKLIST.as_posix()] if present else [],
            )
        answer = decision.get("answer")
        if not isinstance(answer, str) or not answer:
            raise RuntimeError("决策模型未提供可恢复的 Agent 提示")
        state.setdefault("project_readiness", {})["pending_agent_prompt"] = answer
        state.setdefault("project_readiness", {}).pop("pending_agent_text", None)
        write_state(run_dir, state)
        prompt = answer

    raise RuntimeError("project-readiness 决策循环达到上限仍未完成")
