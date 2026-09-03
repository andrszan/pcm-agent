from __future__ import annotations

import json
import re
from dataclasses import replace
from pathlib import Path
from typing import Any

from common.agent_decision_loop import AgentDecisionLoopSpec, run_agent_decision_loop
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
TAILWIND_THEME_MAX_TURNS = 24
LEGACY_COMPLETION_MESSAGES = (
    "已完成 project-bootstrap：基础工程已完成项目化并通过完成条件与工程边界核验。",
)

BOOTSTRAP_DECISION_RULES = """- completed：产品根 README 和各适用工程的项目身份、基础配置、必要文档及安全确认的模板残留已经收口；允许为匹配工程实际加载合同维护受保护的实际 `.env` 或等价配置、调整环境变量名称和配置结构并同步无秘密公开示例，但必须复用同一既有资源绑定，保留 endpoint、权限范围和秘密值，不重新选择、创建、派生、轮换或替换外部资源或凭据；每个适用工程的依赖安装、检查、测试、构建、启动和基础联调均已真实通过或明确不适用；涉及界面时已用真实浏览器检查代表性页面及阻断性控制台、网络错误；保持可替换的 Tailwind 语义颜色基础设施，不把模板默认主题认定为项目专属主题，也不在本任务选择或生成项目专属配色；没有项目化范围内的失败或未验证项，且未实施业务功能或 Git 写操作。
- continue：项目化修改、配置读取或迁移、工程接线、安装、检查、测试、构建、启动、健康检查、联调、浏览器验证或完成证据尚不完整，但可使用既有准备事实、工程和工具继续修复并重跑。
- blocked：只能用于已经使用既有配置排除工程接线问题后，当前环境无法恢复的既有外部账号、授权、凭据、服务、私有数据、专用设备、付费条件或线下动作本身不可用；必须说明实际失败入口和补验条件，不得通过重新选择、创建、派生、轮换或替换资源或凭据消除阻塞。"""

TAILWIND_THEME_DECISION_RULES = """- completed：已经确认当前 frontend 符合 Tailwind CSS v4 CSS-first 合同，唯一识别实际活动全局样式入口和既有 dark selector；根据权威产品定义选择经校验的 tweakcn preset 或生成自定义配色，完整落实并验证项目专属 light/dark 语义颜色；只修改允许的颜色值和确实缺失的颜色映射，字体、圆角、阴影、间距、tracking、布局、组件、页面和业务逻辑保持不变；适用前端构建与真实浏览器 light/dark 切换、实际渲染、控制台和失败网络请求检查均已完成，没有未验证项，也没有 Git 写操作。
- continue：主题方向、light/dark 颜色集合、允许范围内的修改、前端构建或真实两种模式渲染证据尚不完整，但可基于当前产品定义、Tailwind v4 工程和已有工具继续完成或修正。
- blocked：只能用于当前环境无法取得、且完成真实主题验收不可替代的外部品牌资料、授权素材、私有数据、专用设备、付费服务或线下动作；tweakcn 网络不可用必须回退到自定义配色，本地版本、主题入口、dark selector、工作树或文件结构冲突不得作为 blocked。"""

DECISION_LOOP_SPEC = AgentDecisionLoopSpec(
    key=CONVERSATION_KEY,
    state_key="project_bootstrap",
    skill_name=SKILL_NAME,
    max_decision_rounds=MAX_DECISION_ROUNDS,
    max_turns=PROJECT_BOOTSTRAP_MAX_TURNS,
    model_tier="medium",
    effort="high",
    decision_system_prompt=render_decision_system_prompt(BOOTSTRAP_DECISION_RULES, {}),
    legacy_completion_messages=LEGACY_COMPLETION_MESSAGES,
)
TAILWIND_THEME_DECISION_LOOP_SPEC = AgentDecisionLoopSpec(
    key=TAILWIND_THEME_CONVERSATION_KEY,
    state_key="tailwind_theme",
    skill_name=TAILWIND_THEME_SKILL_NAME,
    max_decision_rounds=MAX_DECISION_ROUNDS,
    max_turns=TAILWIND_THEME_MAX_TURNS,
    model_tier="medium",
    effort="high",
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
            "project-bootstrap 已完成基础工程项目化和验证，tailwind-theme 已完成项目专属 light/dark 配色。"
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
    project_references = "\n".join(
        f"- @./{output}" for output in assembly.get("outputs", [])
    )
    runtime_reference = (
        f"\n当前产品本机运行配置：\n- @./{runtime_path}\n"
        if runtime_path is not None
        else ""
    )
    assembly_json = json.dumps(prompt_assembly(assembly), ensure_ascii=False, indent=2)
    return f"""/project-bootstrap
调用方已授权你直接在当前项目完成有限范围的基础工程项目化，并执行真实安装、检查、测试、构建、启动、浏览器检查和基础联调。

权威产品定义：
{product_references}

项目准备事实：
- @./{checklist}

实际适用工程：
{project_references}
{runtime_reference}
组装白名单事实：
```json
{assembly_json}
```

请依据这些输入和当前工程事实完成产品根 README、适用工程身份、基础配置、必要运行说明及可安全确认的模板残留收口。已提供本机运行配置时，使用其中已分配的 host、port 和 endpoint 完成启动、前后端连接、CORS、健康检查和浏览器入口接线；不得自行递增、随机选择或依赖框架静默切换端口，端口被未知进程占用时报告冲突且不终止未知进程。保持或建立可替换的 Tailwind 语义颜色基础设施，但不要选择或生成项目专属主题配色，也不要把模板默认主题认定为最终产品主题。按锁文件和工程说明完成所有适用的依赖安装、静态或类型检查、测试、构建、启动；验证后端健康与就绪入口，存在前端时用真实浏览器读取代表性页面并检查阻断性控制台和失败网络请求，前后端同时适用时完成最小真实联调。失败时先修复项目化范围内的配置读取、变量迁移、脚本、代码、代理、服务启动、健康入口、前后端连接、测试或浏览器入口问题并重跑。完成前删除本轮测试或模板遗留的未忽略 `.coverage` 覆盖率数据库，或将这类可再生产物加入所属仓库的 `.gitignore`；不得把覆盖率数据库作为项目文件保留。

已提供的准备基线、受保护运行配置和资源身份是项目化的既定输入。可以按工程实际加载合同维护每个适用仓库被 Git 忽略的实际 `.env` 或等价本地配置，以及对应 `.env.example` 或既有公开配置示例；必要时允许环境变量改名和配置结构迁移。迁移只能复用同一既有资源绑定和真实值，必须保留资源身份、endpoint 与权限范围；不得重新选择、创建、派生、轮换或替换外部资源或凭据，公开示例不得包含秘密。

若真实工程命令仍失败，只有在确认工程接线无法继续修复且既有资源、授权、凭据、服务、设备或付费条件本身不可用时，才保留验收标准并报告具体失败入口、影响、未验证范围和补验条件；不得用替代资源或新凭据规避阻塞。

不得修改权威产品定义或项目准备清单，不得提前实现业务页面、导航、数据模型、业务接口、认证权限、迁移、业务数据、总体技术方案或工程架构；不得初始化、暂存、提交、建分支、合并或推送 Git；不得泄露秘密。最终完整回复须说明处理的工程、主要变更和保留项、每项真实验证结果、浏览器或联调结果，以及未验证范围、阻塞或后续事项。"""


def tailwind_theme_initial_prompt(product_outputs: list[str]) -> str:
    product_references = "\n".join(f"- @./{output}" for output in product_outputs)
    return f"""/tailwind-theme
调用方已授权你依据当前产品事实，为现有 Tailwind CSS v4 CSS-first 前端形成并落实项目专属主题配色。

权威产品定义：
{product_references}

实际前端：
- @./frontend

请从权威产品定义、目标用户、核心任务、信息密度和当前前端事实提取颜色方向；从经过校验的 tweakcn 内置主题中选择明显适配项，或在没有合适 preset、网络不可用或远程数据不合格时生成自定义配色。必须同时完成完整 light/dark 语义颜色，定位实际活动全局样式入口并保留项目现有 dark selector。

只允许修改语义颜色值和确实缺失的 `@theme inline` 颜色映射。不得修改字体、字阶、圆角、阴影、间距、tracking、布局、组件、页面、主题切换交互或业务功能；不得安装、升级或迁移 Tailwind，不得初始化组件库，不得导入完整远程 CSS 或非颜色 token。

按当前前端工程已有命令完成适用静态检查、测试和构建，并在真实浏览器中分别切换 light/dark，实际读取代表性页面渲染、computed color、控制台和失败网络请求。不得初始化、暂存、提交、建分支、合并或推送 Git；不得泄露秘密。最终完整回复须说明主题来源、选择依据、实际修改文件、light/dark 完整性、所有真实验证结果和未解决限制。"""


async def run(
    run_dir: Path,
    state: dict[str, Any],
    *,
    agent_runner=run_claude,
    decision_runner=request_decision,
    config_loader=LLMConfig.load,
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
                "主题合同": (
                    "当前 frontend 必须保持 Tailwind CSS v4 CSS-first；完整 light/dark 项目专属语义颜色必须同时落实并真实验证；"
                    "只允许颜色值和必要颜色映射，不修改字体、圆角、阴影、间距、tracking、布局、组件、页面或业务。"
                ),
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
