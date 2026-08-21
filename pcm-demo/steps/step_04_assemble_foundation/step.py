from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

from common.files import write_json
from common.state import write_state, write_step_result
from steps.step_01_create_workspace.workspace import (
    WorkspaceBlocked,
    git,
    inspect_root_repository,
    require_real_directory,
)
from steps.step_03_foundation_selection.step import (
    FoundationSelectionResult,
    TemplateSelection,
)

STEP = 4
NAME = "组装基础工程"
CURRENT_NODE = "project:04_assemble_foundation"
NEXT_NODE = "project:05_verify_readiness"
MARKER = ".pcm-assemble-owner.json"
TARGETS = ("frontend", "backend")


class AssemblyBlocked(RuntimeError):
    pass


def is_repository_access_error(error: Exception) -> bool:
    message = str(error).lower()
    return any(
        text in message
        for text in (
            "authentication failed",
            "could not read username",
            "terminal prompts disabled",
            "http basic: access denied",
            "403 forbidden",
        )
    )


def result(
    status: str,
    summary: str,
    *,
    applicable: bool = True,
    outputs: list[str] | None = None,
    assembly: dict[str, Any] | None = None,
    blocked: dict[str, Any] | None = None,
    error: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "step": STEP,
        "name": NAME,
        "status": status,
        "summary": summary,
        "applicable": applicable,
        "outputs": outputs or [],
        "blocked": blocked,
        "error": error,
        "assembly": assembly or {"frontend": None, "backend": None},
    }


def load_selection(run_dir: Path) -> FoundationSelectionResult:
    try:
        previous = json.loads((run_dir / "steps" / "03.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RuntimeError("第 3 步选型结果不可读取") from error
    if previous.get("step") != 3 or previous.get("status") != "success":
        raise RuntimeError("第 3 步选型结果未成功完成")
    try:
        return FoundationSelectionResult.model_validate(previous["template_selection"])
    except (KeyError, ValueError) as error:
        raise RuntimeError("第 3 步模板选择不符合约定") from error


def workspace_from_state(state: dict[str, Any]) -> Path:
    try:
        workspace = Path(state["workspace"]["final_path"]).resolve()
        root = Path(state["workspace"]["root"]).resolve()
    except (KeyError, TypeError) as error:
        raise RuntimeError("工作区状态记录不完整") from error
    if workspace.parent != root:
        raise RuntimeError("产品工作区路径与状态根目录不一致")
    root_repository = inspect_root_repository(workspace)
    if state.get("root_repository") != root_repository:
        raise RuntimeError("产品根 Git 仓库与运行记录不一致")
    return workspace


def target_status(target: Path) -> str:
    if target.is_symlink():
        raise RuntimeError(f"目标目录不能是符号链接：{target}")
    if not target.exists():
        return "missing"
    if not target.is_dir():
        raise RuntimeError(f"目标不是目录：{target}")
    entries = list(target.iterdir())
    if len(entries) != 1 or entries[0].name != ".gitkeep":
        raise RuntimeError(f"目标目录不是严格占位目录：{target}")
    placeholder = entries[0]
    if placeholder.is_symlink() or not placeholder.is_file():
        raise RuntimeError(f"目标占位文件不符合约定：{target}")
    return "placeholder"


def inspect_targets(workspace: Path) -> dict[str, str]:
    return {target: target_status(workspace / target) for target in TARGETS}


def temporary_root(workspace: Path, run_id: str) -> Path:
    if Path(run_id).name != run_id or run_id in {"", ".", ".."}:
        raise RuntimeError("运行 ID 不符合临时目录约定")
    return workspace.parent / f"{workspace.name}.pcm-assemble-{run_id}"


def ownership_marker(workspace: Path, run_id: str) -> dict[str, Any]:
    return {"run_id": run_id, "product_path": str(workspace), "step": STEP}


def owns_temporary_root(path: Path, marker: dict[str, Any]) -> bool:
    marker_path = path / MARKER
    if path.is_symlink() or not path.is_dir() or marker_path.is_symlink() or not marker_path.is_file():
        return False
    try:
        return json.loads(marker_path.read_text(encoding="utf-8")) == marker
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False


def prepare_temporary_root(workspace: Path, run_id: str) -> Path:
    temporary = temporary_root(workspace, run_id)
    marker = ownership_marker(workspace, run_id)
    if temporary.exists() or temporary.is_symlink():
        if temporary.parent != workspace.parent or temporary.name != f"{workspace.name}.pcm-assemble-{run_id}":
            raise RuntimeError("临时目录路径不符合约定")
        inspect_targets(workspace)
        if not owns_temporary_root(temporary, marker):
            raise RuntimeError("存在无法确认归属的组装临时目录，已保留现场")
        shutil.rmtree(temporary)
    temporary.mkdir()
    write_json(temporary / MARKER, marker)
    (temporary / "clones").mkdir()
    (temporary / "payloads").mkdir()
    return temporary


def validate_selection_path(selection: TemplateSelection, clone: Path) -> Path:
    raw_path = selection.path.strip()
    relative = Path(raw_path)
    if not raw_path or relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise RuntimeError(f"模板路径不符合相对路径约定：{selection.path}")
    source = clone / relative
    try:
        source.resolve().relative_to(clone.resolve())
    except ValueError as error:
        raise RuntimeError(f"模板路径超出 clone 根目录：{selection.path}") from error
    if source.is_symlink() or not source.is_dir():
        raise RuntimeError(f"模板路径不是真实目录：{selection.path}")
    return source


def verify_tree(root: Path) -> None:
    for directory, directories, files in os.walk(root, followlinks=False):
        for name in [*directories, *files]:
            child = Path(directory) / name
            if name == ".git":
                raise RuntimeError("选中模板子树不能包含 .git")
            if child.is_symlink():
                raise RuntimeError("选中模板子树不能包含符号链接")


def verify_no_nested_git(root: Path) -> None:
    require_real_directory(root, "基础工程目标")
    for directory, directories, files in os.walk(root, followlinks=False):
        if ".git" in directories or ".git" in files:
            raise RuntimeError(f"基础工程目标包含嵌套 .git：{root}")


def clone_repository(
    temporary: Path,
    index: int,
    git_url: str,
    branch: str,
    *,
    git_runner=git,
) -> tuple[Path, dict[str, str]]:
    clone = temporary / "clones" / f"repository-{index}"
    try:
        git_runner(
            "clone",
            "--depth",
            "1",
            "--branch",
            branch,
            "--single-branch",
            git_url,
            str(clone),
            remote_auth=True,
        )
    except WorkspaceBlocked:
        raise
    except Exception as error:
        if is_repository_access_error(error):
            raise AssemblyBlocked("缺少所选模板仓库的读取凭据或访问权限") from error
        raise RuntimeError("模板仓库 clone 失败") from error
    require_real_directory(clone, "模板 clone")
    if not (clone / ".git").is_dir():
        raise RuntimeError("模板 clone 未包含 Git 元数据")
    try:
        evidence = {
            "origin": git_runner("remote", "get-url", "origin", cwd=clone),
            "branch": git_runner("branch", "--show-current", cwd=clone),
            "commit_sha": git_runner("rev-parse", "HEAD", cwd=clone),
        }
    except WorkspaceBlocked:
        raise
    except Exception as error:
        raise RuntimeError("模板来源核验失败") from error
    if evidence["origin"] != git_url or evidence["branch"] != branch or not evidence["commit_sha"]:
        raise RuntimeError("模板 clone 的来源、分支或提交与选型不一致")
    return clone, evidence


def prepare_payloads(
    temporary: Path, selection: FoundationSelectionResult, *, git_runner=git
) -> dict[str, dict[str, Any] | None]:
    selections = {"frontend": selection.frontend, "backend": selection.backend}
    repositories: dict[tuple[str, str], tuple[Path, dict[str, str]]] = {}
    assembly: dict[str, dict[str, Any] | None] = {"frontend": None, "backend": None}
    for target in TARGETS:
        chosen = selections[target]
        if chosen is None:
            continue
        key = (chosen.git_url, chosen.default_branch)
        if key not in repositories:
            repositories[key] = clone_repository(
                temporary, len(repositories), *key, git_runner=git_runner
            )
        clone, evidence = repositories[key]
        source = validate_selection_path(chosen, clone)
        verify_tree(source)
        payload = temporary / "payloads" / target
        shutil.copytree(source, payload)
        verify_no_nested_git(payload)
        assembly[target] = {
            "target": target,
            "id": chosen.id,
            "git_url": chosen.git_url,
            "default_branch": chosen.default_branch,
            "path": chosen.path,
            **evidence,
        }
    return assembly


def publish_payloads(
    workspace: Path,
    targets: dict[str, str],
    assembly: dict[str, dict[str, Any] | None],
    temporary: Path,
) -> None:
    for target in TARGETS:
        destination = workspace / target
        if target_status(destination) != targets[target]:
            raise RuntimeError(f"发布前目标目录发生变化：{destination}")
        if targets[target] == "placeholder":
            shutil.rmtree(destination)
        payload = temporary / "payloads" / target
        if assembly[target] is not None:
            if not payload.is_dir() or payload.is_symlink():
                raise RuntimeError(f"待发布基础工程不存在：{target}")
            os.rename(payload, destination)
    for target in TARGETS:
        destination = workspace / target
        if assembly[target] is None:
            if destination.exists() or destination.is_symlink():
                raise RuntimeError(f"不适用端发布后仍存在：{destination}")
        else:
            verify_no_nested_git(destination)


def verify_existing_success(
    workspace: Path,
    selection: FoundationSelectionResult,
    existing: dict[str, Any],
    temporary: Path,
) -> None:
    if existing.get("step") != STEP or existing.get("status") != "success":
        raise RuntimeError("第 4 步成功结果不可复用")
    assembly = existing.get("assembly")
    expected_outputs = [
        target
        for target, chosen in (("frontend", selection.frontend), ("backend", selection.backend))
        if chosen is not None
    ]
    if (
        existing.get("applicable") != bool(expected_outputs)
        or existing.get("outputs") != expected_outputs
        or not isinstance(assembly, dict)
        or temporary.exists()
        or temporary.is_symlink()
    ):
        raise RuntimeError("第 4 步成功现场不完整")
    for target, chosen in (("frontend", selection.frontend), ("backend", selection.backend)):
        entry = assembly.get(target)
        destination = workspace / target
        if chosen is None:
            if entry is not None or destination.exists() or destination.is_symlink():
                raise RuntimeError(f"不适用端现场与成功结果不一致：{target}")
            continue
        if not isinstance(entry, dict) or any(
            entry.get(key) != value
            for key, value in {
                "target": target,
                "id": chosen.id,
                "git_url": chosen.git_url,
                "default_branch": chosen.default_branch,
                "path": chosen.path,
            }.items()
        ):
            raise RuntimeError(f"基础工程来源记录与第 3 步选型不一致：{target}")
        if (
            not all(isinstance(entry.get(key), str) and entry[key] for key in ("origin", "branch", "commit_sha"))
            or entry["origin"] != chosen.git_url
            or entry["branch"] != chosen.default_branch
        ):
            raise RuntimeError(f"基础工程来源证据不完整：{target}")
        verify_no_nested_git(destination)


def save_failure(
    run_dir: Path,
    state: dict[str, Any],
    error: Exception,
    *,
    applicable: bool,
) -> dict[str, Any]:
    if isinstance(error, (AssemblyBlocked, WorkspaceBlocked)):
        blocked = {
            "reason": str(error),
            "required_inputs": ["所选模板仓库的可用读取凭据或访问权限"],
            "resume_step": STEP,
        }
        saved = result(
            "blocked", "基础工程组装被模板仓库访问权限阻塞。", applicable=applicable, blocked=blocked
        )
    else:
        saved = result(
            "failed",
            "基础工程组装失败。",
            applicable=applicable,
            error={"type": type(error).__name__, "message": str(error)},
        )
    write_step_result(run_dir, STEP, saved)
    state.update(
        {
            "status": saved["status"],
            "current_step": STEP,
            "step": STEP,
            "current_node": CURRENT_NODE,
            "blocked": saved["blocked"],
            "error": saved["error"],
        }
    )
    write_state(run_dir, state)
    return saved


def run(run_dir: Path, state: dict[str, Any], *, git_runner=git) -> dict[str, Any]:
    selection: FoundationSelectionResult | None = None
    try:
        selection = load_selection(run_dir)
        applicable = selection.frontend is not None or selection.backend is not None
        workspace = workspace_from_state(state)
        temporary = temporary_root(workspace, str(state.get("run_id", "")))
        result_path = run_dir / "steps" / "04.json"
        if state.get("current_step") == 5 and state.get("current_node") == NEXT_NODE and result_path.is_file():
            existing = json.loads(result_path.read_text(encoding="utf-8"))
            verify_existing_success(workspace, selection, existing, temporary)
            return existing
        if state.get("current_step") != STEP or state.get("current_node") != CURRENT_NODE:
            raise RuntimeError("运行状态不位于第 4 步组装锚点")
        targets = inspect_targets(workspace)
        state.update({"status": "running", "blocked": None, "error": None})
        write_state(run_dir, state)
        temporary = prepare_temporary_root(workspace, state["run_id"])
        try:
            assembly = prepare_payloads(temporary, selection, git_runner=git_runner)
            publish_payloads(workspace, targets, assembly, temporary)
            if not owns_temporary_root(temporary, ownership_marker(workspace, state["run_id"])):
                raise RuntimeError("临时目录归属核验失败")
            shutil.rmtree(temporary)
            workspace_from_state(state)
        except WorkspaceBlocked as error:
            raise AssemblyBlocked(str(error)) from error
        outputs = [target for target in TARGETS if assembly[target] is not None]
        saved = result(
            "success", "基础工程已按已选模板组装。", applicable=applicable, outputs=outputs, assembly=assembly
        )
        write_step_result(run_dir, STEP, saved)
        state.update(
            {
                "status": "success",
                "phase": "project_initialization",
                "current_node": NEXT_NODE,
                "step": 5,
                "current_step": 5,
                "blocked": None,
                "error": None,
            }
        )
        write_state(run_dir, state)
        return saved
    except Exception as error:  # noqa: BLE001 - 步骤入口必须持久化所有失败结果。
        applicable = selection is None or selection.frontend is not None or selection.backend is not None
        return save_failure(run_dir, state, error, applicable=applicable)
