from __future__ import annotations

import json
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from common.files import write_json
from common.state import is_valid_requirement_id, read_state, requirement_step_result_path


STEP_NAMES = (
    "形成产品初稿", "建立项目工作区", "项目需求与产品定义", "基础工程选型",
    "组装基础工程", "核验项目准备状态", "项目化基础工程与主题配色", "总体技术方案",
    "首次提交适用仓库", "工程架构设计", "产品级 UI/UX 框架", "拆分 Backlog",
    "解析 Backlog 并初始化需求注册表", "选择需求并建立统一需求分支", "形成活动 TRD",
    "实现与验证", "规则复盘", "统一提交需求变更", "程序化合并并完成需求",
)
STATUSES = {"success", "blocked", "failed"}


def _emit(message: str) -> None:
    try:
        print(message, file=sys.stderr, flush=True)
    except Exception:  # noqa: BLE001 - 旁路输出不可改变业务退出结果。
        pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def format_duration(seconds: float | None) -> str:
    if seconds is None:
        return "未记录"
    if seconds < 60:
        return f"{seconds:.2f} 秒"
    minutes, second = divmod(int(seconds), 60)
    hours, minute = divmod(minutes, 60)
    return f"{hours} 小时 {minute:02d} 分 {second:02d} 秒" if hours else f"{minute} 分 {second:02d} 秒"


def _label(step: int, requirement_id: str | None, name: str) -> str:
    scope = requirement_id or ("未选定需求" if step >= 13 else "项目")
    return f"{scope} · 第 {step} 步 {name}"


def _read_result(run_dir: Path, step: int, requirement_id: str | None) -> dict[str, Any] | None:
    if step >= 13 and requirement_id is None:
        return None
    path = (
        requirement_step_result_path(run_dir, requirement_id, step)
        if requirement_id is not None
        else run_dir / "steps" / f"{step:02d}.json"
    )
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else None


def _read_timings(run_dir: Path) -> dict[str, Any]:
    path = run_dir / "timings.json"
    if not path.exists():
        return {"schema_version": 1, "executions": []}
    if path.is_symlink():
        raise ValueError("计时文件不能是符号链接")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema_version") != 1 or not isinstance(data.get("executions"), list):
        raise ValueError("计时文件格式不符合约定")
    fields = {
        "step", "name", "requirement_id", "started_at", "finished_at", "elapsed_seconds",
        "attempt_count", "status", "applicable", "reused_success", "history_missing",
    }
    for entry in data["executions"]:
        if (
            not isinstance(entry, dict)
            or not fields <= entry.keys()
            or not isinstance(entry.get("name"), str)
            or type(entry.get("attempt_count")) is not int
            or entry["attempt_count"] < 1
            or type(entry.get("reused_success")) is not bool
            or type(entry.get("history_missing")) is not bool
            or type(entry.get("step")) is not int
            or entry["step"] not in range(len(STEP_NAMES))
            or (entry.get("requirement_id") is not None and not is_valid_requirement_id(entry["requirement_id"]))
            or entry.get("status") not in STATUSES | {None}
            or not isinstance(entry.get("started_at"), str)
        ):
            raise ValueError("计时执行记录不符合约定")
        for field in ("started_at", "finished_at"):
            value = entry[field]
            if value is not None and (
                not isinstance(value, str) or datetime.fromisoformat(value).tzinfo is None
            ):
                raise ValueError("计时时间戳必须带时区")
        duration = entry.get("elapsed_seconds")
        if duration is not None and (type(duration) not in {int, float} or not math.isfinite(duration) or duration < 0):
            raise ValueError("计时耗时不符合约定")
    return data


def summarize(executions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[int, str | None], list[dict[str, Any]]] = {}
    for entry in executions:
        groups.setdefault((entry["step"], entry["requirement_id"]), []).append(entry)
    summaries = []
    for (step, requirement_id), entries in groups.items():
        work = []
        completed = None
        for entry in entries:
            if entry["reused_success"]:
                continue
            work.append(entry)
            if entry["status"] == "success" and entry["finished_at"] is not None:
                completed = entry
                break
        durations = [entry["elapsed_seconds"] for entry in work if entry["elapsed_seconds"] is not None]
        incomplete = (
            not work
            or (completed is None and any(entry["reused_success"] for entry in entries))
            or any(
                entry["history_missing"] or entry["finished_at"] is None or entry["status"] is None
                for entry in work
            )
        )
        started_at = work[0]["started_at"] if work else None
        completed_at = completed["finished_at"] if completed is not None else None
        span = None
        if started_at is not None and completed_at is not None and not incomplete:
            span = (datetime.fromisoformat(completed_at) - datetime.fromisoformat(started_at)).total_seconds()
            if span < 0:
                span = None
        total = sum(durations) if durations else None
        if total is not None and not math.isfinite(total):
            raise ValueError("累计耗时必须为有限数值")
        last = completed or entries[-1]
        summaries.append({
            "step": step,
            "requirement_id": requirement_id,
            "name": last["name"],
            "status": last["status"],
            "applicable": last["applicable"],
            "elapsed_seconds": total,
            "started_at": started_at,
            "completed_at": completed_at,
            "span_seconds": span,
            "incomplete": incomplete,
            "reused_count": sum(entry["reused_success"] for entry in entries),
        })
    return summaries


class StepTiming:
    def __init__(self) -> None:
        self.run_dir: Path | None = None
        self.record: dict[str, Any] | None = None
        self.history: dict[str, Any] | None = None
        self.previous_result: dict[str, Any] | None = None
        self.started = 0.0
        self.disabled = False

    def begin_attempt(self, step: int) -> None:
        if self.record is None:
            self.started = time.monotonic()
            self.record = {
                "step": step,
                "name": STEP_NAMES[step],
                "requirement_id": None,
                "started_at": utc_now(),
                "finished_at": None,
                "elapsed_seconds": None,
                "attempt_count": 0,
                "status": None,
                "applicable": None,
                "reused_success": False,
                "history_missing": False,
            }
        self.record["attempt_count"] += 1
        self._save()

    def bind_run(self, run_dir: Path, *, existing: bool = False) -> None:
        if self.run_dir is not None or self.record is None or self.disabled:
            return
        try:
            if not run_dir.is_dir():
                return
            self.run_dir = run_dir
            self.history = _read_timings(run_dir)
            if existing:
                state = read_state(run_dir)
                self._set_requirement(state.get("active_requirement"))
                self.previous_result = _read_result(run_dir, self.record["step"], self.record["requirement_id"])
                previous = [entry for entry in self.history["executions"] if self._same_scope(entry)]
                interrupted = (
                    state.get("current_step") == self.record["step"]
                    and state.get("status") in {"running", "failed", "blocked"}
                )
                self.record["history_missing"] = not previous and (self.previous_result is not None or interrupted)
            self.history["executions"].append(self.record)
            self._save()
        except Exception:  # noqa: BLE001 - 旁路计时不可改变业务退出结果。
            self._disable()

    def announce(self) -> None:
        if self.record is not None and self.record["attempt_count"] == 1:
            _emit(
                f"开始  {_label(self.record['step'], self.record['requirement_id'], self.record['name'])}"
                f" · {self.record['started_at']}"
            )

    def observe_result(self, run_dir: Path | None, result: dict[str, Any]) -> None:
        if self.record is None:
            return
        if run_dir is not None:
            self.bind_run(run_dir)
        self._set_requirement(result.get("requirement_id"))
        self._refresh_requirement()
        self.record["name"] = result.get("name", self.record["name"])
        self.record["status"] = result["status"]
        self.record["applicable"] = result.get("applicable")
        self.record["reused_success"] = (
            result["status"] == "success"
            and self.previous_result is not None
            and self.previous_result.get("status") == "success"
            and self.previous_result.get("step") == self.record["step"]
            and self.previous_result.get("requirement_id") == self.record["requirement_id"]
        )
        self._save()

    def finish(self, *, returned: bool) -> None:
        if self.record is None:
            return
        self.record["elapsed_seconds"] = max(0.0, time.monotonic() - self.started)
        self.record["finished_at"] = utc_now()
        if not returned:
            self.record["status"] = None
            self.record["reused_success"] = False
        self._refresh_requirement()
        self._save()
        status = self.record["status"] or "执行中断"
        if self.record["reused_success"]:
            status += "（成功复用）"
        elif self.record["status"] == "success" and self.record["applicable"] is False:
            status += "（不适用跳过）"
        total = None
        incomplete = True
        if self.history is not None and not self.disabled:
            try:
                summaries = summarize(self.history["executions"])
                summary = next(item for item in summaries if self._same_scope(item))
                total, incomplete = summary["elapsed_seconds"], summary["incomplete"]
            except Exception:  # noqa: BLE001 - 旁路汇总不可改变业务退出结果。
                self._disable()
        suffix = "（计时不完整）" if incomplete else ""
        _emit(
            f"结束  {_label(self.record['step'], self.record['requirement_id'], self.record['name'])}"
            f" · {status}\n"
            f"      本次耗时：{format_duration(self.record['elapsed_seconds'])}"
            f"；累计运行：{format_duration(total)}{suffix}"
        )

    def _same_scope(self, entry: dict[str, Any]) -> bool:
        return self.record is not None and (entry["step"], entry["requirement_id"]) == (self.record["step"], self.record["requirement_id"])

    def _set_requirement(self, requirement_id: object) -> None:
        if self.record is not None and self.record["step"] >= 13 and is_valid_requirement_id(requirement_id):
            self.record["requirement_id"] = requirement_id

    def _refresh_requirement(self) -> None:
        if self.run_dir is None or self.record is None or self.record["step"] < 13 or self.record["requirement_id"] is not None:
            return
        try:
            self._set_requirement(read_state(self.run_dir).get("active_requirement"))
        except Exception:  # noqa: BLE001 - 归属不可读时保留已知计时，不干扰业务。
            pass

    def _disable(self) -> None:
        if not self.disabled:
            _emit("警告：计时记录不可读写，本次持久化计时不可用；业务执行不受影响。")
        self.disabled = True

    def _save(self) -> None:
        if self.run_dir is None or self.history is None or self.disabled:
            return
        try:
            write_json(self.run_dir / "timings.json", self.history)
        except Exception:  # noqa: BLE001 - 计时持久化不可改变业务退出结果。
            self._disable()


def print_timing_summary(run_dir: Path) -> None:
    try:
        if not run_dir.is_dir():
            return
        summaries = summarize(_read_timings(run_dir)["executions"])
        known = {(item["step"], item["requirement_id"]) for item in summaries}
        paths = list((run_dir / "steps").glob("*.json"))
        paths.extend((run_dir / "steps" / "requirements").glob("*/*.json"))
        for path in sorted(paths):
            try:
                result = json.loads(path.read_text(encoding="utf-8"))
                step = result.get("step")
                requirement_id = result.get("requirement_id") if type(step) is int and step >= 13 else None
                key = (step, requirement_id)
                if type(step) is not int or step not in range(len(STEP_NAMES)) or key in known:
                    continue
                known.add(key)
                summaries.append({
                    "step": step, "requirement_id": requirement_id,
                    "name": result.get("name", STEP_NAMES[step]), "status": result.get("status"),
                    "applicable": result.get("applicable"), "elapsed_seconds": None,
                    "span_seconds": None, "incomplete": True, "reused_count": 0,
                })
            except (OSError, ValueError, TypeError, AttributeError):
                continue
        _emit("步骤耗时汇总（累计运行不含停机等待及成功复用检查）：")
        if not summaries:
            _emit("  尚无计时记录。")
        for item in sorted(summaries, key=lambda row: (row["requirement_id"] is not None or row["step"] >= 13, row["requirement_id"] or "", row["step"])):
            status = item["status"] or "计时未闭合"
            if item["status"] == "success" and item["applicable"] is False:
                status += "（不适用跳过）"
            incomplete = "（计时不完整）" if item["incomplete"] and item["elapsed_seconds"] is not None else ""
            reused = f"；成功复用 {item['reused_count']} 次" if item["reused_count"] else ""
            _emit(
                f"  {_label(item['step'], item['requirement_id'], item['name'])} · {status}"
                f" · 累计 {format_duration(item['elapsed_seconds'])}{incomplete}"
                f"；总历时 {format_duration(item['span_seconds'])}{reused}"
            )
        if (run_dir / "timings.json").is_file():
            _emit(f"计时记录：{run_dir / 'timings.json'}")
    except Exception:  # noqa: BLE001 - 旁路汇总不可覆盖业务退出结果。
        _emit("警告：计时汇总不可读取；业务状态与退出码不受影响。")
