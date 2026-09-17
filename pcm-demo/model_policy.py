from __future__ import annotations

import json
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

from provider import resolve_provider_name

ModelEffort = Literal["low", "medium", "high", "xhigh", "max"]

_MODEL_POLICY_PATH = Path(__file__).with_name("model-policy.toml")
_MODEL_POLICY_SNAPSHOT_ENV = "PCM_MODEL_POLICY_SNAPSHOT"
_STEP_TASKS = {
    "2": "project_intake",
    "5": "project_readiness",
    "6.bootstrap": "project_bootstrap",
    "6.theme": "tailwind_theme",
    "6.brand": "brand_assets",
    "7": "solution_design",
    "8": "initialize_repositories",
    "9": "engineering_architecture",
    "10": "ui_ux_framework",
    "11": "requirement_breakdown",
    "14": "trd_design",
    "15": "development",
    "16": "rule_retrospective",
    "17": "requirement_commit",
}
_VALID_EFFORTS = {"low", "medium", "high", "xhigh", "max"}


@dataclass(frozen=True)
class AgentProfile:
    profile: str
    model: str
    effort: ModelEffort


@dataclass(frozen=True)
class _ModelPolicy:
    profiles: dict[str, tuple[str, ModelEffort]]
    steps: dict[str, str]


_cached_policy: _ModelPolicy | None = None


def _require_exact_keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    unknown = sorted(set(value) - expected)
    missing = sorted(expected - set(value))
    if unknown:
        raise ValueError(f"{label} 包含未知键：{', '.join(unknown)}")
    if missing:
        raise ValueError(f"{label} 缺少键：{', '.join(missing)}")


def _parse_model_policy(data: Any) -> _ModelPolicy:
    if not isinstance(data, dict):
        raise ValueError("模型策略顶层必须是 TOML 表")
    _require_exact_keys(data, {"profiles", "steps"}, "模型策略")

    raw_profiles = data["profiles"]
    if not isinstance(raw_profiles, dict) or not raw_profiles:
        raise ValueError("模型策略 profiles 必须是非空表")
    profiles: dict[str, tuple[str, ModelEffort]] = {}
    for name, raw_profile in raw_profiles.items():
        if not isinstance(name, str) or not name.strip() or name != name.strip():
            raise ValueError("模型策略 profile 名称必须是无首尾空白的非空字符串")
        if not isinstance(raw_profile, dict):
            raise ValueError(f"模型策略 profile {name} 必须是表")
        _require_exact_keys(raw_profile, {"model", "effort"}, f"模型策略 profile {name}")
        model = raw_profile["model"]
        effort = raw_profile["effort"]
        if not isinstance(model, str) or not model.strip():
            raise ValueError(f"模型策略 profile {name} 的 model 不能为空")
        if not isinstance(effort, str) or effort not in _VALID_EFFORTS:
            raise ValueError(
                f"模型策略 profile {name} 的 effort 必须是 low、medium、high、xhigh 或 max"
            )
        profiles[name] = (model.strip(), cast(ModelEffort, effort))

    raw_steps = data["steps"]
    if not isinstance(raw_steps, dict):
        raise ValueError("模型策略 steps 必须是表")
    _require_exact_keys(raw_steps, set(_STEP_TASKS), "模型策略 steps")
    steps: dict[str, str] = {}
    for step, profile in raw_steps.items():
        if not isinstance(profile, str) or profile not in profiles:
            raise ValueError(f"模型策略步骤 {step} 引用了无效 profile：{profile!r}")
        steps[step] = profile
    return _ModelPolicy(profiles=profiles, steps=steps)


def _model_policy_path() -> Path:
    provider = resolve_provider_name()
    if provider is None:
        return _MODEL_POLICY_PATH
    provider_path = _MODEL_POLICY_PATH.with_name(f"model-policy.{provider}.toml")
    if not provider_path.is_file():
        raise ValueError(
            f"PCM_PROVIDER={provider} 的模型策略不存在：{provider_path}"
        )
    return provider_path


def _read_model_policy_file() -> _ModelPolicy:
    policy_path = _model_policy_path()
    try:
        with policy_path.open("rb") as file:
            return _parse_model_policy(tomllib.load(file))
    except FileNotFoundError as error:
        raise ValueError(f"模型策略配置不存在：{policy_path}") from error
    except tomllib.TOMLDecodeError as error:
        raise ValueError(f"模型策略 TOML 无效：{error}") from error
    except OSError as error:
        raise ValueError(f"模型策略配置不可读取：{policy_path}") from error


def _read_model_policy_snapshot(snapshot: str) -> _ModelPolicy:
    try:
        return _parse_model_policy(json.loads(snapshot))
    except json.JSONDecodeError as error:
        raise ValueError(f"内部模型策略 snapshot JSON 无效：{error}") from error


def load_model_policy() -> _ModelPolicy:
    global _cached_policy
    if _cached_policy is None:
        snapshot = os.environ.get(_MODEL_POLICY_SNAPSHOT_ENV)
        _cached_policy = (
            _read_model_policy_snapshot(snapshot) if snapshot else _read_model_policy_file()
        )
    return _cached_policy


def _load_model_policy_from_file() -> _ModelPolicy:
    global _cached_policy
    if _cached_policy is None:
        _cached_policy = _read_model_policy_file()
    return _cached_policy


def _model_policy_snapshot(policy: _ModelPolicy) -> str:
    return json.dumps(
        {
            "profiles": {
                name: {"model": model, "effort": effort}
                for name, (model, effort) in policy.profiles.items()
            },
            "steps": policy.steps,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _model_policy_table(policy: _ModelPolicy) -> str:
    rows = [
        (step, policy.steps[step], *policy.profiles[policy.steps[step]])
        for step in _STEP_TASKS
    ]
    widths = [
        max(len(heading), *(len(row[index]) for row in rows))
        for index, heading in enumerate(("step", "profile", "model", "effort"))
    ]
    lines = ["模型策略：", "  ".join(
        heading.ljust(widths[index])
        for index, heading in enumerate(("step", "profile", "model", "effort"))
    )]
    lines.extend(
        "  ".join(value.ljust(widths[index]) for index, value in enumerate(row))
        for row in rows
    )
    return "\n".join(lines)


def get_agent_profile(task: str) -> AgentProfile:
    policy = load_model_policy()
    step = next((step for step, known_task in _STEP_TASKS.items() if known_task == task), None)
    if step is None:
        raise ValueError(f"未知 Agent 任务：{task}")
    profile = policy.steps[step]
    model, effort = policy.profiles[profile]
    return AgentProfile(profile=profile, model=model, effort=effort)
