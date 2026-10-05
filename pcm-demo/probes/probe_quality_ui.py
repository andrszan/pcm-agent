from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import shutil
import subprocess
import sys
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

DEMO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DEMO_ROOT))

from common.files import write_json
from common.timing import StepTiming
from quality import workflow

FIXTURE = Path(__file__).with_name("fixtures") / "quality-ui"
SKILLS = ("product-experience-audit", "requirement-breakdown", "commit-changes")


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *args], stderr=subprocess.PIPE, text=True).strip()


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare_fixture(run_dir: Path) -> dict:
    root = run_dir / "product"
    (root / "docs/backlog").mkdir(parents=True)
    (root / "public").mkdir()
    shutil.copyfile(FIXTURE / "index.html", root / "public/index.html")
    for name in SKILLS:
        shutil.copytree(DEMO_ROOT.parent / ".claude/skills" / name, root / ".claude/skills" / name)
    (root / "plugins-lock.json").write_text('{"version":1,"plugins":[]}\n', encoding="utf-8")
    (root / "CLAUDE.md").write_text("@AGENTS.md\n", encoding="utf-8")
    (root / "AGENTS.md").write_text(
        "# 工作规范\n\n使用中文，遵守当前任务的只读、文档及提交边界。"
        "这是隔离验证产品，单仓、无构建依赖；运行配置见 .pcm/runtime.json，服务由探针托管，不另启或停止服务。"
        "现有 playwright-cli 可用于真实浏览器，使用本产品目录名关联的命名 session，结束时只关闭自己的 session。"
        "临时截图统一放本根 .test-screenshots/，实际读取图片后判断，不记录浏览器其它项目数据。"
        "允许在专属浏览器本地存储准备非敏感便签，禁止全局浏览器关闭、外发和操作其它产品。"
        "不得新增系统权限。没有账号或服务端业务接口，不把它们当作运行条件缺口。\n", encoding="utf-8")
    (root / "README.md").write_text(
        "# 交班便签\n\n这是完整可运行的本机单人浏览器便签产品样本，用于验证质量审查通道，不是客户交付。"
        "来源完成状态由探针构造，不代表真实阶段一验收；产品仍须按实际界面审计，不能因样本身份降低质量标准。\n\n"
        "主要任务：按分类浏览和进入便签；从详情返回原分类；新建非空标题及事项内容；标记已完成与恢复待处理；"
        "刷新后保持已保存结果；阅读用途及存储边界说明。只有交接、物品两个分类，无删除或多人协作承诺。"
        "便签真实保存于当前浏览器 localStorage，不承诺跨浏览器、跨设备、服务器数据库、账户或远程同步。"
        "界面须便于扫描事项和结果，必要说明清楚，适合桌面及窄窗口，不强制图片、动画或特定组件。\n\n"
        "入口为 .pcm/runtime.json 的 endpoint；public/index.html 是实际运行的全部应用。探针使用已安装 Chrome 和"
        "playwright-cli，命名 session 请包含本目录的上级 run 名称。截图放 .test-screenshots/，不要只生成而不读取。"
        "帮助页与各业务任务都属于完整范围，按实际事实判断；不要仅因缺少某种组件或媒体提出改造。\n", encoding="utf-8")
    (root / ".gitignore").write_text(".pcm/\n.test-screenshots/\n.playwright-cli/\n", encoding="utf-8")
    backlog = root / "docs/backlog/backlog.md"
    backlog.write_text(
        "# 正式需求\n\n## BR-001 浏览和办理交班便签\n\n顺序1，无前置依赖。单人在当前浏览器按分类查找、"
        "查看便签和返回原分类；添加非空标题及内容，拒绝纯空白输入且不改变已有数据；"
        "标记完成或恢复待处理，明确结果，刷新后保留已保存数据。提供用途与本浏览器存储边界说明，"
        "桌面和窄窗口可用，界面支持快速扫描，不固定组件方案。不承诺账户、远程同步、删除或上传。\n", encoding="utf-8")
    for args in (("init", "-b", "main"), ("config", "user.name", "前端质量探针"),
                 ("config", "user.email", "quality-ui-probe@example.com")):
        git(root, *args)
    paths = [str(p.relative_to(root)) for p in root.rglob("*") if p.is_file() and ".git" not in p.relative_to(root).parts]
    git(root, "add", "--", *paths)
    git(root, "commit", "-m", "test: 建立隔离浏览器便签现场")
    source = {
        "status": "success", "phase": "phase_1_requirement_development", "step": 13, "current_step": 13,
        "current_node": "phase_1:select_requirement", "active_requirement": None, "requirement_cycle": None,
        "blocked": None, "error": None, "workspace": {"root": str(run_dir), "final_path": str(root)},
        "applicable_repositories": ["root"], "repositories": [{"name": "root", "path": str(root)}],
        "requirement_registry": {"schema_version": 1, "source": {"path": "docs/backlog/backlog.md", "sha256": digest(backlog)},
            "requirements": [{"id": "BR-001", "title": "浏览和办理交班便签", "order": 1,
                "depends_on": [], "status": "completed", "completion": {"step": 18}}]},
    }
    source_id = f"synthetic-{run_dir.name}-source"
    source["run_id"] = source_id
    source_dir = run_dir.parent / source_id
    source_dir.mkdir(exist_ok=False)
    write_json(source_dir / "state.json", source)
    state = workflow.new_state(source, source_id, run_dir.name)
    write_json(run_dir / "state.json", state)
    write_json(run_dir / "source.json", source)
    write_json(run_dir / "fixture.json", {"kind": "quality-ui-fixture", "base": git(root, "rev-parse", "HEAD"),
        "audit_skill_sha256": digest(root / ".claude/skills/product-experience-audit/SKILL.md")})
    return state


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        pass


@contextmanager
def serve(root: Path):
    runtime = root / ".pcm/runtime.json"
    runtime.parent.mkdir(parents=True, exist_ok=True)
    port = json.loads(runtime.read_text())["port"] if runtime.exists() else 0
    server = ThreadingHTTPServer(("127.0.0.1", port), partial(QuietHandler, directory=str(root / "public")))
    endpoint = f"http://127.0.0.1:{server.server_port}"
    write_json(runtime, {"host": "127.0.0.1", "port": server.server_port, "endpoint": endpoint})
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield endpoint
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def verify_browser(endpoint: str, output: Path) -> dict:
    process = subprocess.run(["node", str(FIXTURE / "verify.cjs"), endpoint, str(output)],
        capture_output=True, text=True, timeout=120)
    output.mkdir(parents=True, exist_ok=True)
    (output / "browser.log").write_text(process.stdout + process.stderr, encoding="utf-8")
    if process.returncode:
        raise RuntimeError(f"隔离浏览器验证失败，见 {output / 'browser.log'}")
    return json.loads((output / "verification.json").read_text())


def improve_fixture(source: str) -> str:
    old = '.note-card{padding:2.2rem;min-height:12rem;margin-bottom:1.5rem;'
    new = '.note-card{padding:1rem 1.2rem;min-height:0;margin-bottom:.7rem;'
    if old not in source:
        raise ValueError("原始渲染样本与最小改善不匹配")
    return source.replace(old, new).replace(
        '当前界面展示本客户端读取到的便签数据。请通过相关记录进入后续操作，依据记录的当前技术状态选择下一步。',
        '查看待办，记录新事项；完成后保留原内容供交班核对。').replace(
        "el('p',`当前记录的技术字段：id=${note.id}，category=${note.category}，done=${note.done}。这是当前浏览器读取到的对象，请进入记录进行操作。`,{class:'meta'})",
        "el('span','',{'aria-hidden':'true'})").replace(
        '.status{font-size:1rem;font-weight:400}', '.status{font-size:.9rem;font-weight:650;color:#175b9c}').replace(
        "{class:'status'}", "{class:'status','data-done':String(note.done)}").replace(
        '</style>', '.message:empty{display:none}.note-card,h1{overflow-wrap:anywhere}'
        '.status[data-done=true]{color:#526477}.toolbar a[href="#new"]{display:inline-block;'
        'background:#175b9c;color:white;padding:.55rem 1rem;border-radius:6px}</style>')


async def probe(run_dir: Path, *, resume: bool, browser_only: bool = False) -> int:
    if resume:
        state = json.loads((run_dir / "state.json").read_text())
        fixture = json.loads((run_dir / "fixture.json").read_text())
        if fixture.get("kind") != "quality-ui-fixture" or Path(state["workspace"]["final_path"]) != run_dir / "product":
            raise ValueError("只能恢复本探针的隔离产品")
    else:
        run_dir.mkdir(parents=True, exist_ok=False)
        (run_dir / "logs").mkdir()
        state = prepare_fixture(run_dir)
        fixture = json.loads((run_dir / "fixture.json").read_text())
    root = Path(state["workspace"]["final_path"])
    if digest(root / ".claude/skills/product-experience-audit/SKILL.md") != fixture["audit_skill_sha256"]:
        raise ValueError("探针产品的审计Skill快照发生变化")
    nodes = []
    with serve(root) as endpoint:
        before = verify_browser(endpoint, root / ".test-screenshots/probe-before")
        if not browser_only:
            while state["current_node"] in {"quality:prepare", "quality:audit", "quality:route", "quality:pool"}:
                node = state["current_node"]
                print(f"执行：{node}", flush=True)
                nodes.append(node)
                timing = StepTiming()
                try:
                    with timing.activate():
                        timing.begin_attempt(node=node, round_number=state["quality"]["round"])
                        timing.bind_run(run_dir, existing=True)
                        result = await workflow.run_node(run_dir, state)
                        timing.observe_result(run_dir, result)
                        timing.finish(returned=True)
                except Exception as error:
                    workflow.record_failure(run_dir, state, error)
                    raise
    repaired = run_dir / "render-check"
    (repaired / "public").mkdir(parents=True, exist_ok=True)
    (repaired / "public/index.html").write_text(improve_fixture((root / "public/index.html").read_text()), encoding="utf-8")
    with serve(repaired) as endpoint:
        after = verify_browser(endpoint, repaired / ".test-screenshots/probe-after")
    checks = {"functional_before": before["status"] == "passed", "functional_after": after["status"] == "passed",
        "same_initial_content": before["initial"] == after["initial"],
        "reduced_repetition_space": after["layout"]["pageHeight"] < before["layout"]["pageHeight"],
        "fixture_worktree_clean": not git(root, "status", "--porcelain"),
        "application_source_unchanged": (root / "public/index.html").read_bytes() == (FIXTURE / "index.html").read_bytes()}
    scope = "隔离完整浏览器便签的真实任务与独立渲染改善，不代表客户产品或完整质量修复周期。"
    if not browser_only:
        directory = run_dir / "quality/rounds/0001"
        audit = json.loads((directory / "audit.json").read_text())["data"]
        route = json.loads((directory / "route.json").read_text())["data"]
        checks.update(real_agent_sessions=len(state.get("claude_sessions", {})) >= 2,
            has_candidates=bool(audit["candidates"]), real_task_coverage=bool(audit["coverage"]),
            pool_completed=(directory / "pool-plan.json").exists(), stopped_before_development=state["current_node"] == "quality:register")
        write_json(run_dir / "semantic-review.json", {"audit": audit, "route": route})
        scope += "真实模型范围为准备、审计、提取、分流和入池；改善由探针在独立副本实施验证，未执行正式需求开发、提交合并或整批完成。"
    outcome = "passed" if all(checks.values()) else "failed"
    write_json(run_dir / "probe-result.json", {"status": outcome, "checks": checks, "nodes": nodes,
        "final_node": state["current_node"], "audit_skill_sha256": fixture["audit_skill_sha256"], "scope": scope})
    print(json.dumps({"status": outcome, "result": str(run_dir / 'probe-result.json')}, ensure_ascii=False), flush=True)
    return 0 if outcome == "passed" else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="隔离图形产品上的真实质量审计与非阻断改善验证")
    location = parser.add_mutually_exclusive_group()
    location.add_argument("--run-dir", type=Path)
    location.add_argument("--resume", type=Path)
    parser.add_argument("--browser-only", action="store_true")
    args = parser.parse_args()
    target = args.resume or args.run_dir or DEMO_ROOT / "runs" / datetime.now(timezone.utc).strftime("quality-ui-%Y%m%dT%H%M%SZ")
    try:
        return asyncio.run(probe(target.resolve(), resume=args.resume is not None, browser_only=args.browser_only))
    except Exception as error:
        print(json.dumps({"status": "failed", "error_type": type(error).__name__, "resume": str(target.resolve())}), flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
