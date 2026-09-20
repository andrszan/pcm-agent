from __future__ import annotations

import os
from pathlib import Path

from dotenv import dotenv_values

DEFAULT_ENV_FILE = Path(__file__).with_name(".env")
PROVIDER_ENV = "PCM_PROVIDER"
PROVIDERS_DIR_NAME = ".env.d"


def _env_file_provider(env_file: Path) -> str | None:
    if not env_file.is_file():
        return None
    value = dotenv_values(env_file).get(PROVIDER_ENV)
    if not isinstance(value, str) or not value.strip():
        return None
    return value


def normalize_provider_name(raw: str) -> str | None:
    name = raw.strip()
    if not name:
        return None
    if "/" in name or "\\" in name or name in {".", ".."} or name != Path(name).name:
        raise ValueError(f"{PROVIDER_ENV} 名称无效：{raw!r}")
    return name


def resolve_provider_name(env_file: Path | None = None) -> str | None:
    # 进程环境优先于 env 文件；空值视为未配置并回落到 env 文件。
    raw = os.environ.get(PROVIDER_ENV)
    if raw is None or not raw.strip():
        raw = _env_file_provider(env_file or DEFAULT_ENV_FILE)
    return normalize_provider_name(raw) if raw is not None else None


def resolve_env_files(env_file: Path | None = None) -> tuple[Path, ...]:
    base = (env_file or DEFAULT_ENV_FILE).expanduser()
    name = resolve_provider_name(base)
    if name is None:
        return (base,)
    provider_file = base.parent / PROVIDERS_DIR_NAME / f"{name}.env"
    if not provider_file.is_file():
        raise ValueError(f"{PROVIDER_ENV}={name} 的提供商配置不存在：{provider_file}")
    return (base, provider_file)
