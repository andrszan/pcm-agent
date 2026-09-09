from __future__ import annotations

import json
import re
from dataclasses import replace
from pathlib import Path
from typing import Any

from common.agent_decision_loop import AgentDecisionLoopSpec, ResumeMessage, run_agent_decision_loop
from common.claude_agent import run_claude
from common.decision import render_decision_system_prompt, request_decision
from common.state import step_result_status, write_state, write_step_result
from config import LLMConfig
from steps.step_01_create_workspace.workspace import git, inspect_root_repository
from steps.step_04_assemble_foundation.step import (
    temporary_root,
    verify_existing_success,
    workspace_from_state,
)
from steps.step_05_project_readiness.step import (
    checklist_contents,
    checklist_present,
    load_product_outputs,
    load_selection,
    product_output_contents,
    verify_existing_readiness_success,
)

STEP = 6
NAME = "项目化基础工程"
CURRENT_NODE = "project:06_bootstrap_foundation"
NEXT_NODE = "project:07_solution_design"
CONVERSATION_KEY = "project_bootstrap"
SKILL_NAME = "project-bootstrap"
TAILWIND_THEME_CONVERSATION_KEY = "tailwind_theme"
TAILWIND_THEME_SKILL_NAME = "tailwind-theme"
CHECKLIST = Path("docs/requirements/项目准备清单.md")
MAX_DECISION_ROUNDS = 32
PROJECT_BOOTSTRAP_MAX_TURNS = 9999
TAILWIND_THEME_MAX_TURNS = 9999
LEGACY_COMPLETION_MESSAGES = (
    "已完成 project-bootstrap：基础工程已完成项目化并通过完成条件与工程边界核验。",
)

BOOTSTRAP_DECISION_RULES = """- completed：产品根 README 和各适用工程的项目身份、配置、文档及模板残留已完成项目化。
- continue：项目化或上述验证尚未完成，可用既有工程、配置和工具继续修复。"""

TAILWIND_THEME_DECISION_RULES = """- completed：项目风格定制已完成。
- continue：本次风格定制尚未完成，可用当前产品定义、工程和工具继续处理。"""

DECISION_LOOP_SPEC = AgentDecisionLoopSpec(
    key=CONVERSATION_KEY,
    state_key="project_bootstrap",
    skill_name=SKILL_NAME,
    max_decision_rounds=MAX_DECISION_ROUNDS,
    max_turns=PROJECT_BOOTSTRAP_MAX_TURNS,
    task="project_bootstrap",
    decision_system_prompt=render_decision_system_prompt(BOOTSTRAP_DECISION_RULES, {}),
    legacy_completion_messages=LEGACY_COMPLETION_MESSAGES,
)
TAILWIND_THEME_DECISION_LOOP_SPEC = AgentDecisionLoopSpec(
    key=TAILWIND_THEME_CONVERSATION_KEY,
    state_key="tailwind_theme",
    skill_name=TAILWIND_THEME_SKILL_NAME,
    max_decision_rounds=MAX_DECISION_ROUNDS,
    max_turns=TAILWIND_THEME_MAX_TURNS,
    task="tailwind_theme",
    decision_system_prompt=render_decision_system_prompt(
        TAILWIND_THEME_DECISION_RULES, {}
    ),
)
README_REPAIR_PROMPT = "产品根 README 缺失或为空。请仅补齐该文件的项目身份和必要基础运行说明，然后报告结果。"
COVERAGE_ARTIFACT_REPAIR_PROMPT = (
    "检测到未忽略的 .coverage 测试覆盖率数据库。请删除可确认的覆盖率临时产物，"
    "或将它加入所属仓库的 .gitignore；不得把覆盖率数据库作为项目文件保留，然后重新核验并报告。"
)
TAILWIND_CSS_IMPORT_PATTERN = re.compile(
    r"^\s*@import\s+(?P<quote>['\"])tailwindcss(?P=quote)\s*;?\s*$",
    re.MULTILINE,
)
CSS_COMMENT_PATTERN = re.compile(r"/\*.*?\*/", re.DOTALL)
TAILWIND_SIMPLE_V4_PATTERN = re.compile(
    r"^(?:workspace:)?[~^]?4(?:\.(?:\d+|x|\*)){0,2}(?:-[0-9A-Za-z.-]+)?$"
)
TAILWIND_BOUNDED_V4_PATTERN = re.compile(
    r"^>=\s*4(?:\.\d+){0,2}\s+<\s*5(?:\.0+){0,2}$"
)


class ProjectBootstrapBlocked(RuntimeError):
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
    applicable: bool = True,
    blocked: dict[str, Any] | None = None,
    error: dict[str, Any] | None = None,
    outputs: list[str] | None = None,
    tailwind_theme: bool = False,
) -> dict[str, Any]:
    return {
        "step": STEP,
        "name": NAME,
        "status": status,
        "summary": summary,
        "applicable": applicable,
        "outputs": outputs or [],
        "tailwind_theme": tailwind_theme,
        "blocked": blocked,
        "error": error,
    }


def load_assembly(run_dir: Path) -> dict[str, Any]:
    try:
        assembly = json.loads((run_dir / "steps" / "04.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RuntimeError("第 4 步组装结果不可读取") from error
    return assembly


def validate_inputs(
    run_dir: Path, state: dict[str, Any]
) -> tuple[Path, list[str], dict[str, Any], str]:
    position = (state.get("step"), state.get("current_step"), state.get("current_node"))
    if position not in {(STEP, STEP, CURRENT_NODE), (STEP + 1, STEP + 1, NEXT_NODE)}:
        raise RuntimeError("运行状态不位于基础工程项目化锚点")
    workspace = workspace_from_state(state)
    product_outputs = load_product_outputs(run_dir, workspace)
    selection = load_selection(run_dir)
    assembly = load_assembly(run_dir)
    verify_existing_success(
        workspace,
        selection,
        assembly,
        temporary_root(workspace, str(state.get("run_id", ""))),
    )
    verify_existing_readiness_success(run_dir, workspace, product_outputs)
    if not checklist_present(workspace):
        raise RuntimeError("第 5 步项目准备清单不存在或不可读取")
    outputs = assembly.get("outputs")
    if not isinstance(outputs, list) or any(
        not isinstance(output, str) or not output for output in outputs
    ):
        raise RuntimeError("第 4 步适用工程目录不符合约定")
    return workspace, product_outputs, assembly, CHECKLIST.as_posix()


def verify_git_boundaries(workspace: Path, outputs: list[str]) -> None:
    inspect_root_repository(workspace)
    for output in outputs:
        inspect_root_repository(workspace / output)


def verify_tailwind_v4_frontend(workspace: Path) -> None:
    frontend = workspace / "frontend"
    package_path = frontend / "package.json"
    if package_path.is_symlink() or not package_path.is_file():
        raise RuntimeError("frontend/package.json 不存在或不是普通文件")
    try:
        package = json.loads(package_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RuntimeError("frontend/package.json 不可读取或不是合法 JSON") from error
    if not isinstance(package, dict):
        raise RuntimeError("frontend/package.json 顶层必须是对象")

    dependency_sections = [package.get("dependencies"), package.get("devDependencies")]
    version: str | None = None
    for section in dependency_sections:
        if section is None:
            continue
        if not isinstance(section, dict):
            raise RuntimeError("frontend/package.json 依赖字段必须是对象")
        candidate = section.get("tailwindcss")
        if candidate is not None:
            if version is not None or not isinstance(candidate, str) or not candidate.strip():
                raise RuntimeError("frontend 的 tailwindcss 版本声明不唯一或不可解析")
            version = candidate.strip()
    if version is None:
        raise RuntimeError("frontend 未直接声明 tailwindcss 依赖")
    normalized_version = version.replace(" ", "")
    if not (
        TAILWIND_SIMPLE_V4_PATTERN.fullmatch(normalized_version)
        or TAILWIND_BOUNDED_V4_PATTERN.fullmatch(version.strip())
    ):
        raise RuntimeError("frontend 不符合 Tailwind CSS v4 模板合同")

    css_files = git(
        "ls-files",
        "--cached",
        "--others",
        "--exclude-standard",
        "--",
        "*.css",
        cwd=frontend,
    ).splitlines()
    for raw_path in css_files:
        relative_path = Path(raw_path)
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise RuntimeError("frontend CSS 文件路径不符合约定")
        css_path = frontend / relative_path
        if css_path.is_symlink() or not css_path.is_file():
            continue
        try:
            contents = css_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            raise RuntimeError("frontend CSS 文件不可读取") from error
        if TAILWIND_CSS_IMPORT_PATTERN.search(
            CSS_COMMENT_PATTERN.sub(" ", contents)
        ):
            return
    raise RuntimeError("frontend 缺少 Tailwind CSS v4 CSS-first @import 入口")


def coverage_artifact_repair(workspace: Path, outputs: list[str]) -> str | None:
    for relative in [".", *outputs]:
        repository = workspace if relative == "." else workspace / relative
        status = git("status", "--porcelain", "--untracked-files=all", cwd=repository)
        for line in status.splitlines():
            path = line[3:].strip()
            if path == ".coverage" or path.endswith("/.coverage"):
                return COVERAGE_ARTIFACT_REPAIR_PROMPT
    return None


def verify_existing_bootstrap_success(
    run_dir: Path, expected_outputs: list[str]
) -> dict[str, Any]:
    try:
        existing = json.loads((run_dir / "steps" / "06.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RuntimeError("第 6 步成功结果不可读取") from error
    expected_tailwind_theme = "frontend" in expected_outputs
    marker = existing.get("tailwind_theme")
    if (
        existing.get("step") != STEP
        or existing.get("status") != "success"
        or existing.get("applicable") != bool(expected_outputs)
        or existing.get("outputs") != expected_outputs
        or type(marker) is not bool
        or marker is not expected_tailwind_theme
    ):
        raise RuntimeError("第 6 步成功结果不可复用")
    return existing


def root_readme_repair(workspace: Path) -> str | None:
    path = workspace / "README.md"
    if path.is_symlink():
        raise RuntimeError("产品根 README 不能是符号链接")
    if not path.exists():
        return README_REPAIR_PROMPT
    if not path.is_file():
        raise RuntimeError("产品根 README 必须是普通文件")
    try:
        if not path.read_text(encoding="utf-8").strip():
            return README_REPAIR_PROMPT
    except (OSError, UnicodeError) as error:
        raise RuntimeError("产品根 README 不可读取") from error
    return None


def advance_success(
    run_dir: Path,
    state: dict[str, Any],
    outputs: list[str],
) -> dict[str, Any]:
    tailwind_theme = "frontend" in outputs
    saved = result(
        "success",
        (
            "project-bootstrap 已完成基础工程项目化和验证，tailwind-theme 已完成项目风格定制。"
            if tailwind_theme
            else "project-bootstrap 已完成基础工程项目化和验证；当前无 frontend，tailwind-theme 已跳过。"
        ),
        applicable=bool(outputs),
        outputs=outputs,
        tailwind_theme=tailwind_theme,
    )
    write_step_result(run_dir, STEP, saved)
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
    return saved


def advance_not_applicable(run_dir: Path, state: dict[str, Any]) -> dict[str, Any]:
    saved = result(
        "success",
        "当前没有适用的基础工程，项目化无副作用跳过。",
        applicable=False,
    )
    write_step_result(run_dir, STEP, saved)
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
    return saved


def prompt_assembly(assembly: dict[str, Any]) -> dict[str, Any]:
    visible: dict[str, Any] = {}
    for target, entry in (assembly.get("assembly") or {}).items():
        if entry is None:
            visible[target] = None
            continue
        if not isinstance(entry, dict):
            raise RuntimeError("第 4 步组装来源不符合约定")
        visible[target] = {
            key: entry.get(key)
            for key in (
                "target",
                "id",
                "default_branch",
                "path",
                "branch",
                "commit_sha",
            )
        }
    return visible


def initial_prompt(
    product_outputs: list[str],
    assembly: dict[str, Any],
    checklist: str,
    runtime_path: str | None = None,
) -> str:
    product_references = "\n".join(f"- @./{output}" for output in product_outputs)
    project_references = "\n".join(f"- @./{output}" for output in assembly.get("outputs", []))
    runtime_reference = f"- @./{runtime_path}" if runtime_path else "- 未提供。"
    assembly_json = json.dumps(prompt_assembly(assembly), ensure_ascii=False, indent=2)
    return f"""/project-bootstrap
调用方授权你依据以下权威输入完成基础工程项目化。

权威产品定义：
{product_references}
项目准备事实：
- @./{checklist}
实际工程：
{project_references}
本机运行配置：
{runtime_reference}
组装白名单：
```json
{assembly_json}
```

复用既有资源绑定，不重新选择、创建、派生、轮换或替换凭据。保持可替换的 Tailwind 基础视觉主题基础设施，但不选择项目专属主题。"""


def tailwind_theme_initial_prompt(product_outputs: list[str]) -> str:
    product_references = "\n".join(f"- @./{output}" for output in product_outputs)
    return f"""/tailwind-theme
请依据以下权威产品定义和实际前端，完成项目风格定制：
{product_references}
- @./frontend"""


async def run(
    run_dir: Path,
    state: dict[str, Any],
    *,
    agent_runner=run_claude,
    decision_runner=request_decision,
    config_loader=LLMConfig.load,
    resume_message: ResumeMessage | None = None,
) -> dict[str, Any]:
    workspace, product_outputs, assembly, checklist = validate_inputs(run_dir, state)
    outputs = assembly["outputs"]
    position = (state.get("step"), state.get("current_step"), state.get("current_node"))

    verify_git_boundaries(workspace, outputs)
    if not outputs:
        if position == (STEP + 1, STEP + 1, NEXT_NODE):
            return verify_existing_bootstrap_success(run_dir, outputs)
        return advance_not_applicable(run_dir, state)

    def bootstrap_completion_verifier() -> str | None:
        verified_workspace, _, verified_assembly, _ = validate_inputs(run_dir, state)
        verified_outputs = verified_assembly["outputs"]
        verify_git_boundaries(verified_workspace, verified_outputs)
        readme_repair = root_readme_repair(verified_workspace)
        if readme_repair is not None:
            return readme_repair
        return coverage_artifact_repair(verified_workspace, verified_outputs)

    def tailwind_theme_completion_verifier() -> str | None:
        verified_workspace, _, verified_assembly, _ = validate_inputs(run_dir, state)
        verified_outputs = verified_assembly["outputs"]
        if "frontend" not in verified_outputs:
            raise RuntimeError("tailwind-theme 仅在 frontend 适用时运行")
        verify_git_boundaries(verified_workspace, verified_outputs)
        verify_tailwind_v4_frontend(verified_workspace)
        return coverage_artifact_repair(verified_workspace, verified_outputs)

    if position == (STEP + 1, STEP + 1, NEXT_NODE) and state.get("status") == "success":
        verify_existing_bootstrap_success(run_dir, outputs)
        if bootstrap_completion_verifier() is not None:
            raise RuntimeError("第 6 步既有成功缺少非空产品根 README")
        if "frontend" in outputs:
            verify_tailwind_v4_frontend(workspace)
            if tailwind_theme_completion_verifier() is not None:
                raise RuntimeError("第 6 步既有成功仍包含未处理的覆盖率数据库")
        return result(
            "success",
            "基础工程项目化及条件性 Tailwind 主题处理已完成，确认既有成功。",
            applicable=bool(outputs),
            outputs=outputs,
            tailwind_theme="frontend" in outputs,
        )

    if position != (STEP, STEP, CURRENT_NODE):
        raise RuntimeError("运行状态不位于基础工程项目化锚点")

    if step_result_status(run_dir, STEP) == "success":
        verify_existing_bootstrap_success(run_dir, outputs)
        if bootstrap_completion_verifier() is not None:
            raise RuntimeError("第 6 步既有成功缺少非空产品根 README")
        if "frontend" in outputs:
            verify_tailwind_v4_frontend(workspace)
            if tailwind_theme_completion_verifier() is not None:
                raise RuntimeError("第 6 步既有成功仍包含未处理的覆盖率数据库")
        return advance_success(run_dir, state, outputs)

    if state.get("status") != "blocked":
        state.update(
            {"current_step": STEP, "status": "running", "blocked": None, "error": None}
        )
        write_state(run_dir, state)

    checklist_content = checklist_contents(workspace)
    if checklist_content is None:
        raise RuntimeError("第 5 步项目准备清单不存在或不可读取")
    runtime_path: str | None = None
    coordination = state.get("coordination")
    if isinstance(coordination, dict):
        candidate = coordination.get("runtime_path")
        if candidate != ".pcm/runtime.json" or not (workspace / candidate).is_file():
            raise RuntimeError("产品本机运行配置不存在或与协调状态不一致")
        runtime_path = candidate
    bootstrap_context: dict[str, Any] = {
        "产品定义": product_output_contents(workspace, product_outputs),
        "已完成的项目准备基线": checklist_content,
        "配置迁移与既有资源边界": (
            "可以调整实际本地配置的变量名称和结构并同步公开示例，但必须复用同一既有资源绑定、endpoint、权限范围和秘密值；"
            "不得重新选择、创建、派生、轮换或替换外部资源或凭据。"
        ),
        "适用工程": outputs,
        "组装白名单事实": prompt_assembly(assembly),
    }
    if runtime_path is not None:
        bootstrap_context["产品本机运行配置"] = {
            "path": runtime_path,
            "要求": "使用已分配 endpoint；不得静默换端口或终止未知进程。",
        }
    bootstrap_spec = replace(
        DECISION_LOOP_SPEC,
        decision_system_prompt=render_decision_system_prompt(
            BOOTSTRAP_DECISION_RULES,
            bootstrap_context,
        ),
    )
    bootstrap_decision = await run_agent_decision_loop(
        run_dir,
        state,
        workspace,
        bootstrap_spec,
        initial_prompt(product_outputs, assembly, checklist, runtime_path),
        bootstrap_completion_verifier,
        agent_runner=agent_runner,
        decision_runner=decision_runner,
        config_loader=config_loader,
        resume_message=resume_message,
    )
    if bootstrap_decision.verdict == "blocked":
        verified_workspace, _, verified_assembly, _ = validate_inputs(run_dir, state)
        verified_outputs = verified_assembly["outputs"]
        verify_git_boundaries(verified_workspace, verified_outputs)
        if coverage_artifact_repair(verified_workspace, verified_outputs) is not None:
            raise RuntimeError("项目化过程仍包含未删除或未忽略的 .coverage 覆盖率数据库")
        raise ProjectBootstrapBlocked(
            bootstrap_decision.reason, bootstrap_decision.required_inputs, outputs
        )

    if "frontend" not in outputs:
        return advance_success(run_dir, state, outputs)

    verify_tailwind_v4_frontend(workspace)
    tailwind_theme_spec = replace(
        TAILWIND_THEME_DECISION_LOOP_SPEC,
        decision_system_prompt=render_decision_system_prompt(
            TAILWIND_THEME_DECISION_RULES,
            {
                "产品定义": product_output_contents(workspace, product_outputs),
                "实际前端": ["frontend"],
            },
        ),
    )
    tailwind_theme_decision = await run_agent_decision_loop(
        run_dir,
        state,
        workspace,
        tailwind_theme_spec,
        tailwind_theme_initial_prompt(product_outputs),
        tailwind_theme_completion_verifier,
        agent_runner=agent_runner,
        decision_runner=decision_runner,
        config_loader=config_loader,
        resume_message=resume_message,
    )
    if tailwind_theme_decision.verdict == "blocked":
        verified_workspace, _, verified_assembly, _ = validate_inputs(run_dir, state)
        verified_outputs = verified_assembly["outputs"]
        verify_git_boundaries(verified_workspace, verified_outputs)
        verify_tailwind_v4_frontend(verified_workspace)
        if coverage_artifact_repair(verified_workspace, verified_outputs) is not None:
            raise RuntimeError("主题处理仍包含未删除或未忽略的 .coverage 覆盖率数据库")
        raise ProjectBootstrapBlocked(
            tailwind_theme_decision.reason,
            tailwind_theme_decision.required_inputs,
            outputs,
        )
    return advance_success(run_dir, state, outputs)
