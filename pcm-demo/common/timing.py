from __future__ import annotations

import asyncio
import json
import math
import signal
import sys
import time
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
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
BEIJING = timezone(timedelta(hours=8))
MISSING_AGENT_NOTE = "历史 Claude Code 执行区间未记录；Agent 累计仅含已记录区间。"
MISSING_START_NOTE = "步骤早期起点未记录，无法计算完整总历时。"
MISSING_END_NOTE = "步骤此前已成功，但首次完成时间未记录，无法计算完整总历时。"
OPEN_CALL_NOTE = "存在未闭合的历史 Agent 区间，无法确定其中断时刻；Agent 累计仅含已知耗时。"
_ACTIVE_TIMING: ContextVar[StepTiming | None] = ContextVar("pcm_step_timing", default=None)


def _emit(message: str) -> None:
    try:
        print(message, file=sys.stderr, flush=True)
    except Exception:  # noqa: BLE001 - 旁路输出不可改变业务退出结果。
        pass


def beijing_now() -> str:
    return datetime.now(BEIJING).isoformat()


def _beijing(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("计时时间戳必须是带时区的字符串")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("计时时间戳必须带时区")
    return parsed.astimezone(BEIJING).isoformat()


def _duration(value: Any) -> float | None:
    if value is None:
        return None
    if type(value) not in {int, float} or not math.isfinite(value) or value < 0:
        raise ValueError("耗时必须是非负有限数值")
    return value


def format_duration(seconds: float | None) -> str:
    if seconds is None:
        return "未记录"
    _duration(seconds)
    if seconds < 60:
        return f"{seconds:.2f} 秒"
    minutes, second = divmod(int(seconds), 60)
    hours, minute = divmod(minutes, 60)
    return (
        f"{hours} 小时 {minute:02d} 分 {second:02d} 秒"
        if hours else f"{minute} 分 {second:02d} 秒"
    )


def _label(record: dict[str, Any]) -> str:
    scope = record["requirement_id"] or ("未选定需求" if record["step"] >= 13 else "项目")
    return f"{scope} · 第 {record['step']} 步 {record['name']}"


def _note(record: dict[str, Any], text: str) -> None:
    current = record.get("note", "")
    if text not in current:
        record["note"] = f"{current} {text}".strip()


def _new_step(step: int, requirement_id: str | None, started_at: str | None) -> dict[str, Any]:
    return {
        "step": step,
        "name": STEP_NAMES[step],
        "requirement_id": requirement_id,
        "status": None,
        "started_at": started_at,
        "finished_at": None,
        "agent_elapsed_seconds": 0.0,
        "wall_elapsed_seconds": None,
        "agent_executions": [],
    }


def _update_totals(record: dict[str, Any]) -> None:
    durations = [
        call["elapsed_seconds"] for call in record["agent_executions"]
        if call["elapsed_seconds"] is not None
    ]
    if durations:
        record["agent_elapsed_seconds"] = _duration(sum(durations))
    start, end = record["started_at"], record["finished_at"]
    if start is not None and end is not None:
        elapsed = (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds()
        record["wall_elapsed_seconds"] = elapsed if elapsed >= 0 else None
        if elapsed < 0:
            _note(record, "系统时钟变化导致起止时间倒置，总历时未记录。")
    else:
        record["wall_elapsed_seconds"] = None


def _read_timings(run_dir: Path) -> dict[str, Any]:
    path = run_dir / "timings.json"
    if path.is_symlink():
        raise ValueError("计时文件不能是符号链接")
    if not path.exists():
        return {"schema_version": 2, "steps": []}
    data = json.loads(path.read_bytes())
    if not isinstance(data, dict):
        raise ValueError("计时文件必须是 JSON 对象")
    if data.get("schema_version") != 2 or not isinstance(data.get("steps"), list):
        raise ValueError("计时文件版本或步骤列表无效")
    for record in data["steps"]:
        if (
            type(record["step"]) is not int or record["step"] not in range(len(STEP_NAMES))
            or not isinstance(record["name"], str)
            or record["status"] not in STATUSES | {None}
            or (record["requirement_id"] is not None and not is_valid_requirement_id(record["requirement_id"]))
            or not isinstance(record["agent_executions"], list)
            or ("note" in record and not isinstance(record["note"], str))
        ):
            raise ValueError("步骤计时格式无效")
        for field in ("started_at", "finished_at"):
            record[field] = _beijing(record[field])
        _duration(record["agent_elapsed_seconds"])
        _duration(record["wall_elapsed_seconds"])
        for call in record["agent_executions"]:
            for field in ("started_at", "finished_at", "interrupted_at"):
                call[field] = _beijing(call[field])
            if call["started_at"] is None or call["end_reason"] not in {
                None, "returned", "turn_limit", "budget_limit", "api_error", "error",
                "exception", "cancelled", "sigint", "sigterm", "unknown",
            }:
                raise ValueError("Agent 执行区间格式无效")
            _duration(call["elapsed_seconds"])
        _update_totals(record)
    return data


def _read_result(run_dir: Path, step: int, requirement_id: str | None) -> dict[str, Any] | None:
    if step >= 13 and requirement_id is None:
        return None
    path = (
        requirement_step_result_path(run_dir, requirement_id, step)
        if requirement_id is not None else run_dir / "steps" / f"{step:02d}.json"
    )
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else None


class StepTiming:
    def __init__(self) -> None:
        self.run_dir: Path | None = None
        self.record: dict[str, Any] | None = None
        self.history: dict[str, Any] | None = None
        self.started_at: str | None = None
        self.step: int | None = None
        self.attempts = 0
        self.completed_before = False
        self.disabled = False
        self.active_call: dict[str, Any] | None = None
        self.signal_reason: str | None = None

    @contextmanager
    def activate(self):
        token = _ACTIVE_TIMING.set(self)
        previous = {}

        def interrupt(signum, _frame):
            if self.signal_reason is None:
                self.signal_reason = "sigint" if signum == signal.SIGINT else "sigterm"
            if self.active_call is not None and self.active_call["interrupted_at"] is None:
                self.active_call["interrupted_at"] = beijing_now()
            if signum == signal.SIGINT:
                raise KeyboardInterrupt
            raise SystemExit(128 + signum)

        try:
            for signum, default in (
                (signal.SIGINT, signal.default_int_handler), (signal.SIGTERM, signal.SIG_DFL),
            ):
                handler = signal.getsignal(signum)
                if handler == default:
                    try:
                        signal.signal(signum, interrupt)
                    except ValueError:
                        continue
                    previous[signum] = handler
            yield
        finally:
            for signum, handler in previous.items():
                signal.signal(signum, handler)
            _ACTIVE_TIMING.reset(token)

    def begin_attempt(self, step: int) -> None:
        if self.step is None:
            self.step, self.started_at = step, beijing_now()
        self.attempts += 1
        if self.record is not None and not self.completed_before:
            self.record["status"] = None
            self._save()

    def bind_run(self, run_dir: Path, *, existing: bool = False) -> None:
        if self.run_dir is not None or self.step is None or self.disabled:
            return
        try:
            if not run_dir.is_dir():
                return
            self.run_dir = run_dir
            self.history = _read_timings(run_dir)
            state = read_state(run_dir) if existing else {}
            requirement_id = state.get("active_requirement") if self.step >= 13 else None
            if not is_valid_requirement_id(requirement_id):
                requirement_id = None
            prior_result = _read_result(run_dir, self.step, requirement_id) if existing else None
            self.completed_before = (
                prior_result is not None and prior_result.get("status") == "success"
                and prior_result.get("step") == self.step
                and prior_result.get("requirement_id") == requirement_id
            )
            if self.step < 13 or requirement_id is not None:
                self.record = next((
                    record for record in self.history["steps"]
                    if (record["step"], record["requirement_id"]) == (self.step, requirement_id)
                ), None)
            if self.record is None:
                independent_selection = (
                    self.step == 13 and requirement_id is None
                    and any(record["step"] == 13 and record["requirement_id"] is None for record in self.history["steps"])
                )
                missing = existing and not independent_selection and (
                    prior_result is not None
                    or (state.get("current_step") == self.step and state.get("status") in {"running", "failed", "blocked"})
                )
                self.record = _new_step(self.step, requirement_id, None if missing else self.started_at)
                if missing:
                    self.record["agent_elapsed_seconds"] = None
                    _note(self.record, MISSING_AGENT_NOTE)
                    _note(self.record, MISSING_START_NOTE)
                self.history["steps"].append(self.record)
            self.completed_before = self.completed_before or self.record["status"] == "success"
            if self.completed_before:
                self.record["status"] = "success"
                if self.record["finished_at"] is None:
                    _note(self.record, MISSING_END_NOTE)
            else:
                self.record["status"] = None
            for call in self.record["agent_executions"]:
                if call["finished_at"] is None:
                    call["end_reason"] = "unknown"
                    _note(self.record, OPEN_CALL_NOTE)
            self._save()
        except Exception:  # noqa: BLE001 - 旁路计时不可改变业务退出结果。
            self._disable()

    def announce(self) -> None:
        if self.step is not None and self.attempts == 1:
            label = _label(self.record) if self.record else f"第 {self.step} 步 {STEP_NAMES[self.step]}"
            _emit(f"开始  {label} · {self.started_at}（北京时间）")

    def observe_result(self, run_dir: Path | None, result: dict[str, Any]) -> None:
        if run_dir is not None:
            self.bind_run(run_dir)
        if self.record is None:
            return
        self._set_requirement(result.get("requirement_id"))
        self._refresh_requirement()
        if not self.completed_before:
            update = {"name": result.get("name", self.record["name"]), "status": result["status"]}
            if result["status"] == "success":
                update["finished_at"] = self.record["finished_at"] or beijing_now()
            self.record.update(update)
        self._save()

    def finish(self, *, returned: bool) -> None:
        if self.record is None:
            return
        try:
            self._refresh_requirement()
            if not self.completed_before and not returned and self.record["status"] != "success":
                self.record["status"] = None
            self._save()
            suffix = "（成功复用）" if self.completed_before else ""
            _emit(
                f"结束  {_label(self.record)} · {self.record['status'] or '执行中断'}{suffix}\n"
                f"      Claude Code 累计执行：{format_duration(self.record['agent_elapsed_seconds'])}"
                f"；步骤总历时：{format_duration(self.record['wall_elapsed_seconds'])}"
            )
            if self.record.get("note"):
                _emit(f"      提示：{self.record['note']}")
        except Exception:  # noqa: BLE001 - 旁路收口不可覆盖业务退出结果。
            self._disable()

    def begin_agent(self) -> tuple[dict[str, Any], float] | None:
        if self.record is None or self.disabled:
            return None
        call = {
            "started_at": beijing_now(),
            "finished_at": None,
            "interrupted_at": None,
            "elapsed_seconds": None,
            "end_reason": None,
        }
        self.record["agent_executions"].append(call)
        self.active_call = call
        self._save()
        return call, time.monotonic()

    def finish_agent(
        self, measurement: tuple[dict[str, Any], float], reason: str,
        ended: float, finished_at: str,
    ) -> None:
        try:
            call, started = measurement
            call["elapsed_seconds"] = _duration(ended - started)
            call["finished_at"] = finished_at
            call["end_reason"] = self.signal_reason or reason
            if call["end_reason"] != "returned" and call["interrupted_at"] is None:
                call["interrupted_at"] = call["finished_at"]
            self.active_call = None
            self._save()
        except Exception:  # noqa: BLE001 - 调用区间记录不可干扰 Agent 执行。
            self._disable()

    def _set_requirement(self, requirement_id: object) -> None:
        if (
            self.record is not None and self.record["step"] >= 13
            and self.record["requirement_id"] is None and is_valid_requirement_id(requirement_id)
        ):
            self.record["requirement_id"] = requirement_id

    def _refresh_requirement(self) -> None:
        if self.run_dir is None or self.record is None or self.record["step"] < 13 or self.record["requirement_id"] is not None:
            return
        try:
            self._set_requirement(read_state(self.run_dir).get("active_requirement"))
        except Exception:  # noqa: BLE001 - 保留已知归属，不干扰业务。
            pass

    def _disable(self) -> None:
        if not self.disabled:
            _emit("警告：计时记录不可读写，本次持久化计时不可用；业务执行不受影响。")
        self.disabled = True
        if self.record is not None:
            self.record["agent_elapsed_seconds"] = None
            self.record["wall_elapsed_seconds"] = None

    def _save(self) -> None:
        if self.run_dir is None or self.history is None or self.disabled:
            return
        try:
            for record in self.history["steps"]:
                _update_totals(record)
            write_json(self.run_dir / "timings.json", self.history)
        except Exception:  # noqa: BLE001 - 计时持久化不可改变业务退出结果。
            self._disable()


def _agent_end_reason(result: Any) -> str:
    if result.result_subtype == "error_max_turns":
        return "turn_limit"
    if result.result_subtype == "error_max_budget_usd":
        return "budget_limit"
    if result.api_error_status is not None or result.terminal_reason == "api_error":
        return "api_error"
    if (
        result.is_error or result.has_errors or result.exception_type is not None
        or result.exception is not None or result.result_subtype != "success"
        or result.terminal_reason not in {None, "completed"}
    ):
        return "error"
    return "returned"


async def run_timed_agent(agent_runner, *args, **kwargs):
    timing = _ACTIVE_TIMING.get()
    measurement = timing.begin_agent() if timing is not None else None
    try:
        result = await agent_runner(*args, **kwargs)
    except BaseException as error:
        if measurement is not None:
            ended, finished_at = time.monotonic(), beijing_now()
            reason = "cancelled" if isinstance(error, (asyncio.CancelledError, KeyboardInterrupt, SystemExit)) else "exception"
            timing.finish_agent(measurement, reason, ended, finished_at)
        raise
    else:
        if measurement is not None:
            ended, finished_at = time.monotonic(), beijing_now()
            try:
                reason = _agent_end_reason(result)
            except Exception:
                reason = "error"
            timing.finish_agent(measurement, reason, ended, finished_at)
        return result


def print_timing_summary(run_dir: Path) -> None:
    try:
        if not run_dir.is_dir():
            return
        data = _read_timings(run_dir)
        records = data["steps"]
        known = {(record["step"], record["requirement_id"]) for record in records}
        paths = list((run_dir / "steps").glob("*.json"))
        paths.extend((run_dir / "steps" / "requirements").glob("*/*.json"))
        for path in sorted(paths):
            try:
                result = json.loads(path.read_bytes())
                step = result["step"]
                requirement_id = result.get("requirement_id") if step >= 13 else None
                if type(step) is not int or step not in range(len(STEP_NAMES)) or (step, requirement_id) in known:
                    continue
                record = _new_step(step, requirement_id, None)
                record.update(status=result["status"], agent_elapsed_seconds=None, note="该步骤未记录计时。")
                records.append(record)
                known.add((step, requirement_id))
            except (OSError, ValueError, TypeError, KeyError):
                continue
        _emit("步骤耗时汇总（北京时间；Agent 执行时间与步骤总历时分别统计）：")
        if not records:
            _emit("  尚无计时记录。")
        for record in records:
            _emit(
                f"  {_label(record)} · {record['status'] or '尚未完成'}"
                f" · Claude Code 累计 {format_duration(record['agent_elapsed_seconds'])}"
                f"；总历时 {format_duration(record['wall_elapsed_seconds'])}"
                f"；执行区间 {len(record['agent_executions'])} 个"
            )
            if record.get("note"):
                _emit(f"    提示：{record['note']}")
        if (run_dir / "timings.json").is_file():
            _emit(f"计时记录：{run_dir / 'timings.json'}")
    except Exception:  # noqa: BLE001 - 旁路汇总不可覆盖业务退出结果。
        _emit("警告：计时汇总不可读取；业务状态与退出码不受影响。")
