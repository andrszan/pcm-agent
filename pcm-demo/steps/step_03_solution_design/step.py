from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
from typing import Any

from common.claude_agent import ClaudeRunResult, run_claude
from common.decision import SYSTEM_PROMPT, request_decision
from common.files import resolve_workspace_output, sha256, write_json
from common.openai_responses import request_json_response
from common.state import write_state
from config import LLMConfig

STEP = 3
NAME = "总体技术方案"
CONVERSATION_KEY = "solution_design"
SKILL_NAME = "solution-design"
CONVERSATION_PATH = Path("conversations/solution_design.json")
OUTPUTS = (Path("docs/design/技术方案.md"),)
MAX_DECISION_ROUNDS = 6
SOLUTION_DESIGN_MAX_BUDGET_USD = 4.0
COMPLETION_MESSAGE = "已完成 solution-design，总体技术方案和前后端基础模板选择均已确认。"
ADOPTIONS = {"direct", "trimmed", "substantial"}
SELECTION_ACTIONS = {"approve", "continue", "blocked"}
SELECTION_INSTRUCTIONS = """你负责判断 Claude Agent 是否已经明确报告 PCM 第 3 步的前后端模板选择，并把已作出的选择结构化。

输入只包含 Agent 最终自然语言回复和本次 catalog.json。你不能替 Agent 选择模板，也不能根据项目需求自行推荐候选。只有以下情况可以把 Agent 的表达解析为 catalog ID：
- Agent 明确写出了 repository_id 和 template_id；
- Agent 使用了 catalog 中能够唯一定位单个候选的完整名称或明确描述。

每个 approve 的 frontend/backend 选择都必须附带 evidence：从 Agent 原文逐字复制、能够支持该端选择和采用方式的连续短句。不要改写、翻译或拼接 Agent 原文。若找不到这样的原文证据，必须返回 continue。

只提到通用技术栈、偏好、多个候选、模糊简称，或缺少前端、后端、采用方式中的任何一项时，必须返回 continue，不得从 catalog 补选。

将 Agent 已明确表达的采用方式归一化为：
- direct：直接继承；
- trimmed：裁剪派生；
- substantial：实质派生。

action 规则：
- approve：前端和后端选择都明确，且都能在 catalog 中唯一定位；
- continue：选型遗漏、含糊、矛盾或尚未收敛；answer 必须给 Agent 一条可直接执行的补充指令；
- blocked：只有 Agent 明确指出缺少当前环境无法取得的不可替代外部资源时使用，并列出 required_inputs。

不要输出密钥、环境变量值或 JSON 之外的文字。"""
SELECTION_UNIT_SCHEMA = {
    "type": "object",
    "properties": {
        "repository_id": {"type": "string"},
        "template_id": {"type": "string"},
        "adoption": {"type": "string", "enum": sorted(ADOPTIONS)},
        "evidence": {"type": "string"},
    },
    "required": ["repository_id", "template_id", "adoption", "evidence"],
    "additionalProperties": False,
}
SELECTION_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": sorted(SELECTION_ACTIONS)},
        "frontend": {"anyOf": [SELECTION_UNIT_SCHEMA, {"type": "null"}]},
        "backend": {"anyOf": [SELECTION_UNIT_SCHEMA, {"type": "null"}]},
    },
    "required": ["action", "frontend", "backend"],
    "additionalProperties": False,
}


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
    template_selection: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "step": STEP,
        "name": NAME,
        "status": status,
        "summary": summary,
        "applicable": True,
        "outputs": outputs or [],
        "template_selection": template_selection,
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


def _required_string(data: dict[str, Any], field: str, subject: str) -> str:
    value = data.get(field)
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"{subject} 的 {field} 必须是非空字符串")
    return value


def _validate_template_path(value: str, subject: str) -> None:
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or value in {".", ".."} or ".." in path.parts:
        raise RuntimeError(f"{subject} 的 path 必须是安全的相对路径")


def read_catalog(path: Path) -> tuple[dict[str, Any], str]:
    content = _read_non_empty(path)
    try:
        data = json.loads(content)
    except json.JSONDecodeError as error:
        raise RuntimeError(f"模板 catalog 不是合法 JSON：{path}") from error
    if not isinstance(data, dict) or set(data) != {"schema_version", "repositories"}:
        raise RuntimeError("模板 catalog 顶层结构不符合约定")
    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise RuntimeError(f"不支持的模板 catalog schema_version：{data['schema_version']}")
    repositories = data["repositories"]
    if not isinstance(repositories, dict) or not repositories:
        raise RuntimeError("模板 catalog 缺少 repositories")

    repository_fields = {
        "git_url",
        "default_branch",
        "name",
        "description",
        "templates",
    }
    template_fields = {"id", "path", "name", "description"}
    for repository_id, repository in repositories.items():
        if not isinstance(repository_id, str) or not repository_id.strip():
            raise RuntimeError("模板 catalog 的 repository_id 必须是非空字符串")
        subject = f"仓库 {repository_id}"
        if not isinstance(repository, dict) or set(repository) != repository_fields:
            raise RuntimeError(f"{subject} 结构不符合约定")
        for field in repository_fields - {"templates"}:
            _required_string(repository, field, subject)
        templates = repository["templates"]
        if not isinstance(templates, list) or not templates:
            raise RuntimeError(f"{subject} 缺少 templates")
        template_ids: set[str] = set()
        for template in templates:
            if not isinstance(template, dict) or set(template) != template_fields:
                raise RuntimeError(f"{subject} 的模板结构不符合约定")
            template_id = _required_string(template, "id", subject)
            if template_id in template_ids:
                raise RuntimeError(f"{subject} 存在重复 template_id：{template_id}")
            template_ids.add(template_id)
            template_subject = f"模板 {repository_id}/{template_id}"
            template_path = _required_string(template, "path", template_subject)
            _validate_template_path(template_path, template_subject)
            _required_string(template, "name", template_subject)
            _required_string(template, "description", template_subject)
    return data, content


def catalog_identity(path: Path, catalog: dict[str, Any], source: str) -> dict[str, Any]:
    return {
        "path": str(path),
        "source": source,
        "sha256": sha256(path),
        "schema_version": catalog["schema_version"],
    }


def validate_inputs(
    run_dir: Path, state: dict[str, Any], catalog_path: Path
) -> tuple[Path, dict[str, str], list[Path], dict[str, Any], str]:
    current_step = state.get("current_step")
    if current_step not in {2, 3} or (current_step == 2 and state.get("status") != "success"):
        raise RuntimeError("第 2 步尚未成功，不能执行第 3 步")
    workspace_value = state.get("workspace", {}).get("final_path")
    if not workspace_value:
        raise RuntimeError("运行状态缺少产品工作区路径")
    workspace = Path(workspace_value).resolve()
    if not workspace.is_dir():
        raise RuntimeError(f"产品工作区不存在：{workspace}")

    previous_result_path = run_dir / "steps" / "02.json"
    try:
        previous_result = json.loads(previous_result_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RuntimeError("第 2 步结果不可读取") from error
    previous_outputs = previous_result.get("outputs")
    if (
        previous_result.get("step") != 2
        or previous_result.get("status") != "success"
        or not isinstance(previous_outputs, list)
        or not previous_outputs
        or not all(isinstance(path, str) and path for path in previous_outputs)
    ):
        raise RuntimeError("第 2 步结果缺少可用产物")
    requirement_paths = [
        resolve_workspace_output(workspace, path) for path in previous_outputs
    ]
    inputs = {str(path): _read_non_empty(path) for path in requirement_paths}
    catalog, catalog_content = read_catalog(catalog_path)
    inputs[str(catalog_path)] = catalog_content
    return workspace, inputs, requirement_paths, catalog, catalog_content


def output_contents(workspace: Path) -> dict[str, str] | None:
    contents: dict[str, str] = {}
    for relative in OUTPUTS:
        path = workspace / relative
        try:
            contents[str(relative)] = _read_non_empty(path)
        except (OSError, UnicodeError, RuntimeError):
            return None
    return contents


def validate_selection_decision(
    data: Any, agent_text: str | None = None
) -> dict[str, Any]:
    required = set(SELECTION_SCHEMA["required"])
    if not isinstance(data, dict) or set(data) != required:
        raise ValueError("模板选型裁决字段不符合约定")
    action = data["action"]
    if action not in SELECTION_ACTIONS:
        raise ValueError("模板选型裁决 action 不符合约定")

    if action == "approve":
        for unit in ("frontend", "backend"):
            selection = data[unit]
            if not isinstance(selection, dict) or set(selection) != set(
                SELECTION_UNIT_SCHEMA["required"]
            ):
                raise ValueError(f"approve 缺少合法的 {unit} 选型")
            for field in ("repository_id", "template_id", "adoption", "evidence"):
                if not isinstance(selection.get(field), str) or not selection[field].strip():
                    raise ValueError(f"{unit} 选型字段必须是非空字符串")
            if selection["evidence"] not in (agent_text or ""):
                raise ValueError(f"{unit} 选型缺少 Agent 原文证据")
            if selection["adoption"] not in ADOPTIONS:
                raise ValueError(f"{unit} adoption 不符合约定")
    elif data["frontend"] is not None or data["backend"] is not None:
        raise ValueError(f"{action} 不得携带已确认选型")
    return data


async def request_template_selection(
    agent_text: str,
    catalog: dict[str, Any],
    config: LLMConfig,
    *,
    max_attempts: int = 2,
) -> tuple[dict[str, Any], int, str]:
    previous_error: str | None = None
    for attempt in range(1, max_attempts + 1):
        payload: dict[str, Any] = {
            "agent_result": agent_text,
            "catalog": catalog,
        }
        if previous_error:
            payload["previous_error"] = previous_error
        raw = await request_json_response(
            config,
            instructions=SELECTION_INSTRUCTIONS,
            input_text=json.dumps(payload, ensure_ascii=False),
            schema_name="pcm_template_selection",
            schema=SELECTION_SCHEMA,
        )
        try:
            decision = validate_selection_decision(json.loads(raw), agent_text)
        except (json.JSONDecodeError, ValueError) as error:
            previous_error = f"{type(error).__name__}: {error}"
            continue
        return decision, attempt, json.dumps(decision, ensure_ascii=False)
    raise ValueError(f"模板选型裁决在 {max_attempts} 次内持续无效")


def normalize_template_selection(
    decision: dict[str, Any], catalog: dict[str, Any]
) -> dict[str, Any]:
    repositories = catalog["repositories"]
    normalized: dict[str, Any] = {}
    for unit, target_path in (("frontend", "frontend"), ("backend", "backend")):
        selected = decision[unit]
        repository_id = selected["repository_id"]
        repository = repositories.get(repository_id)
        if not isinstance(repository, dict):
            raise TypeError(f"{unit} repository_id 不存在于 catalog：{repository_id}")
        template_id = selected["template_id"]
        template = next(
            (
                item
                for item in repository["templates"]
                if item["id"] == template_id
            ),
            None,
        )
        if template is None:
            raise ValueError(
                f"{unit} template_id 不属于仓库 {repository_id}：{template_id}"
            )
        normalized[unit] = {
            "target_path": target_path,
            "repository_id": repository_id,
            "repository_name": repository["name"],
            "git_url": repository["git_url"],
            "default_branch": repository["default_branch"],
            "template_id": template_id,
            "template_path": template["path"],
            "adoption": selected["adoption"],
        }
    return normalized


def existing_template_selection(
    run_dir: Path, catalog: dict[str, Any]
) -> dict[str, Any] | None:
    path = run_dir / "steps" / "03.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if (
        not isinstance(data, dict)
        or data.get("step") != STEP
        or data.get("status") != "success"
        or data.get("outputs") != [OUTPUTS[0].as_posix()]
        or not isinstance(data.get("template_selection"), dict)
    ):
        return None
    selection = data["template_selection"]
    try:
        minimal = {
            unit: {
                field: selection[unit][field]
                for field in ("repository_id", "template_id", "adoption")
            }
            for unit in ("frontend", "backend")
        }
        normalized = normalize_template_selection(minimal, catalog)
    except (KeyError, TypeError, ValueError):
        return None
    return selection if selection == normalized else None


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


def append_decision(
    run_dir: Path,
    state: dict[str, Any],
    messages: list[dict[str, str]],
    agent_text: str,
    raw: str,
) -> None:
    messages.append({"role": "user", "content": agent_text})
    messages.append({"role": "assistant", "content": raw})
    current_turn = (
        state.get("decision_conversations", {})
        .get(CONVERSATION_KEY, {})
        .get("turn", 0)
    )
    save_conversation(run_dir, state, messages, decision_turn=current_turn + 1)


def decision_context(
    inputs: dict[str, str],
    catalog_path: Path,
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
            "completion": (
                "solution-design 正常结束、技术方案真实存在，且 Agent 最终回复明确报告"
                " catalog 中的前后端仓库、模板和采用方式"
            ),
            "catalog_path": str(catalog_path),
            "allowed_inputs": allowed,
            "agent_result": agent_text,
            "outputs_present": outputs is not None,
        },
        ensure_ascii=False,
    )


def decision_prompt(decision: dict[str, Any]) -> str:
    return decision["answer"]


def _requirements(requirement_paths: list[Path], workspace: Path) -> str:
    return " ".join(
        f"@./{path.relative_to(workspace).as_posix()}" for path in requirement_paths
    )


def initial_prompt(
    requirement_paths: list[Path], workspace: Path, catalog_path: Path
) -> str:
    requirements = _requirements(requirement_paths, workspace)
    return (
        f"/solution-design {requirements} @{catalog_path}\n\n"
        "这是 PCM 第 3 步。只生成或更新 docs/design/技术方案.md，不生成基础工程来源 JSON。"
        "请读取本次 catalog 完成前后端模板选型；最终自然语言回复必须分别明确说明 frontend "
        "和 backend 的 repository_id、template_id，以及采用方式（直接继承、裁剪派生或实质派生）。"
        "最终回复不需要使用 JSON。"
    )


def resume_prompt(
    requirement_paths: list[Path], workspace: Path, catalog_path: Path
) -> str:
    requirements = _requirements(requirement_paths, workspace)
    return (
        f"请重新读取 {requirements} 和 @{catalog_path}，核验当前事实并继续完成 PCM 第 3 步。"
        "只生成或更新 docs/design/技术方案.md；最终自然语言回复必须明确报告 frontend 和 "
        "backend 的 repository_id、template_id 和采用方式，不需要输出 JSON。"
    )


def selection_followup_prompt(catalog_path: Path) -> str:
    return (
        f"请重新读取 @{catalog_path}，只报告已经明确决定的 frontend 和 backend 选择。"
        "分别给出 repository_id、template_id 和采用方式（直接继承、裁剪派生或实质派生）；"
        "不要列候选，不要让编排器替你补选。"
    )


def selection_blocked_reason() -> tuple[str, list[str]]:
    return (
        "模板选型需要当前环境无法取得的不可替代外部资源。",
        ["SOLUTION_DESIGN_EXTERNAL_INPUT"],
    )


def _catalog_matches(recorded: Any, current: dict[str, Any]) -> bool:
    return isinstance(recorded, dict) and all(
        recorded.get(field) == current[field]
        for field in ("path", "sha256", "schema_version")
    )


async def run(
    run_dir: Path,
    state: dict[str, Any],
    catalog_path: Path,
    *,
    catalog_source: str = "argument",
    agent_runner=run_claude,
    decision_runner=request_decision,
    selection_runner=request_template_selection,
) -> dict[str, Any]:
    catalog_path = catalog_path.expanduser().absolute()
    if catalog_path.is_symlink():
        raise RuntimeError(f"模板 catalog 不得是符号链接：{catalog_path}")
    catalog_path = catalog_path.resolve()
    workspace, inputs, requirement_paths, catalog, _ = validate_inputs(
        run_dir, state, catalog_path
    )
    current_catalog = catalog_identity(catalog_path, catalog, catalog_source)
    design = state.setdefault("solution_design", {})
    recorded_catalog_present = "catalog" in design
    recorded_catalog = design.get("catalog")
    existing_session = state.get("claude_sessions", {}).get(CONVERSATION_KEY)
    if recorded_catalog_present and not _catalog_matches(recorded_catalog, current_catalog):
        raise RuntimeError("模板 catalog 与已有运行记录不一致")
    if existing_session and not recorded_catalog_present:
        raise RuntimeError("已有 solution-design session 缺少模板 catalog 运行记录")

    existing_outputs = output_contents(workspace)
    previous_result = design.get("last_agent_result", {})
    existing_selection = existing_template_selection(run_dir, catalog)
    if (
        state.get("status") == "success"
        and previous_result.get("subtype") == "success"
        and previous_result.get("is_error") is False
        and existing_outputs is not None
        and _catalog_matches(recorded_catalog, current_catalog)
        and existing_selection is not None
    ):
        design.pop("pending_agent_prompt", None)
        write_state(run_dir, state)
        return result(
            "success",
            "solution-design 已生成技术方案和模板选择，确认既有成功。",
            outputs=[relative.as_posix() for relative in OUTPUTS],
            template_selection=existing_selection,
        )

    design.pop("template_assets", None)
    design.pop("template_inputs", None)
    design["catalog"] = current_catalog
    state.update({"current_step": STEP, "status": "running", "blocked": None, "error": None})
    write_state(run_dir, state)

    pending = design.pop("pending_agent_prompt", None)
    prompt = pending or (
        initial_prompt(requirement_paths, workspace, catalog_path)
        if not existing_session
        else resume_prompt(requirement_paths, workspace, catalog_path)
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
            resume_session_id=state.get("claude_sessions", {}).get(CONVERSATION_KEY),
            max_budget_usd=SOLUTION_DESIGN_MAX_BUDGET_USD,
            on_update=lambda update: save_agent_update(run_dir, state, update),
        )
        save_agent_update(run_dir, state, run_result)
        if not run_result.result_subtype:
            raise RuntimeError(run_result.exception or "Agent SDK 未返回 ResultMessage")
        recoverable_subtypes = {"error_max_turns", "error_max_budget_usd"}
        if run_result.exception and run_result.result_subtype not in recoverable_subtypes:
            raise RuntimeError(run_result.exception)
        if run_result.is_error and run_result.result_subtype not in recoverable_subtypes:
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
            selection_decision, _, raw = await selection_runner(
                run_result.text, catalog, LLMConfig.load()
            )
            if selection_decision["action"] == "blocked":
                reason, required_inputs = selection_blocked_reason()
                raise SolutionDesignBlocked(reason, required_inputs)
            approved = False
            if selection_decision["action"] == "approve":
                try:
                    selection = normalize_template_selection(
                        selection_decision, catalog
                    )
                except (TypeError, ValueError) as error:
                    prompt = (
                        f"你最终报告的模板选择无法通过 catalog 引用校验：{error}。"
                        f"请重新读取 @{catalog_path}，明确报告合法的 frontend 和 backend "
                        "repository_id、template_id 和采用方式。"
                    )
                else:
                    approved = True
                    append_completion(run_dir, state, messages, run_result.text)
                    state.update({"status": "success", "blocked": None, "error": None})
                    design.pop("pending_agent_prompt", None)
                    write_state(run_dir, state)
                    return result(
                        "success",
                        "solution-design 已生成总体技术方案和前后端模板选择。",
                        outputs=[relative.as_posix() for relative in OUTPUTS],
                        template_selection=selection,
                    )
            else:
                prompt = selection_followup_prompt(catalog_path)
            if not approved:
                design["pending_agent_prompt"] = prompt
                write_state(run_dir, state)
        else:
            session_id = state.get("claude_sessions", {}).get(CONVERSATION_KEY)
            if not session_id:
                raise RuntimeError("Agent 未完成且没有可恢复的 session ID")
            messages.append(
                {
                    "role": "user",
                    "content": decision_context(
                        inputs, catalog_path, run_result.text, outputs
                    ),
                }
            )
            decision, _, raw = await decision_runner(messages, LLMConfig.load())
            prompt = decision_prompt(decision)
            messages.append({"role": "assistant", "content": raw})
            current_turn = (
                state.get("decision_conversations", {})
                .get(CONVERSATION_KEY, {})
                .get("turn", 0)
            )
            save_conversation(
                run_dir, state, messages, decision_turn=current_turn + 1
            )
            if decision["action"] == "blocked":
                raise SolutionDesignBlocked(
                    decision["reason"], decision["required_inputs"]
                )
        design["pending_agent_prompt"] = prompt
        write_state(run_dir, state)

    raise RuntimeError("solution-design 决策循环达到上限仍未产生产物和明确选型")
