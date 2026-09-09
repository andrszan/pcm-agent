from __future__ import annotations

import os
from pathlib import Path
from stat import S_ISREG

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_ENV_FILE = Path(__file__).with_name(".env")
CAPABILITY_REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CLAUDE_CODE_AUTO_COMPACT_WINDOW = 500000


class Settings(BaseSettings):
    llm_base_url: str | None = Field(default=None, validation_alias="LLM_BASE_URL")
    llm_api_key: SecretStr | None = Field(default=None, validation_alias="LLM_API_KEY", repr=False)
    llm_model: str | None = Field(default=None, validation_alias="LLM_MODEL")
    llm_model_effort: str | None = Field(default=None, validation_alias="LLM_MODEL_EFFORT")
    pcm_agent_base_url: str | None = Field(default=None, validation_alias="PCM_AGENT_BASE_URL")
    pcm_agent_auth_token: SecretStr | None = Field(
        default=None, validation_alias="PCM_AGENT_AUTH_TOKEN", repr=False
    )
    claude_code_auto_compact_window: int = Field(
        default=DEFAULT_CLAUDE_CODE_AUTO_COMPACT_WINDOW,
        validation_alias="CLAUDE_CODE_AUTO_COMPACT_WINDOW",
        ge=1,
    )
    pcm_workspace_root: Path | None = Field(default=None, validation_alias="PCM_WORKSPACE_ROOT")
    pcm_max_concurrent_projects: int = Field(
        default=2, validation_alias="PCM_MAX_CONCURRENT_PROJECTS", ge=1
    )
    pcm_template_catalog: Path | None = Field(default=None, validation_alias="PCM_TEMPLATE_CATALOG")
    pcm_template_repository: str | None = Field(default=None, validation_alias="PCM_TEMPLATE_REPOSITORY")
    pcm_agent_workspace_env_file: Path | None = Field(
        default=None, validation_alias="PCM_AGENT_WORKSPACE_ENV_FILE"
    )
    pcm_dev_resource_list: Path | None = Field(default=None, validation_alias="PCM_DEV_RESOURCE_LIST")

    model_config = SettingsConfigDict(
        env_file=DEFAULT_ENV_FILE,
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        env_prefix="",
        extra="ignore",
        populate_by_name=True,
        cli_parse_args=False,
    )


class AgentConfig:
    def __init__(
        self,
        base_url: str,
        auth_token: SecretStr,
        auto_compact_window: int = DEFAULT_CLAUDE_CODE_AUTO_COMPACT_WINDOW,
    ) -> None:
        if (
            not isinstance(auto_compact_window, int)
            or isinstance(auto_compact_window, bool)
            or auto_compact_window <= 0
        ):
            raise ValueError("CLAUDE_CODE_AUTO_COMPACT_WINDOW 必须是正整数")
        self.base_url = base_url.rstrip("/")
        self.auth_token = auth_token
        self.auto_compact_window = auto_compact_window

    def __repr__(self) -> str:
        return (
            f"AgentConfig(base_url={self.base_url!r}, auth_token=SecretStr('**********'), "
            f"auto_compact_window={self.auto_compact_window!r})"
        )

    @classmethod
    def load(cls, env_file: Path | None = None) -> "AgentConfig":
        settings = load_settings(env_file)
        values = {
            "PCM_AGENT_BASE_URL": settings.pcm_agent_base_url,
            "PCM_AGENT_AUTH_TOKEN": settings.pcm_agent_auth_token,
        }
        missing = [name for name, value in values.items() if value is None]
        if missing:
            raise ValueError(f"缺少 Agent 配置：{', '.join(missing)}")
        base_url = settings.pcm_agent_base_url.rstrip("/")
        if base_url.endswith("/v1"):
            raise ValueError("PCM_AGENT_BASE_URL 不得包含 /v1")
        return cls(
            base_url,
            settings.pcm_agent_auth_token,
            settings.claude_code_auto_compact_window,
        )


class LLMConfig:
    def __init__(
        self,
        base_url: str,
        api_key: SecretStr,
        model: str,
        effort: str | None = None,
    ) -> None:
        self.base_url = base_url
        self.api_key = api_key
        self.model = model
        self.effort = (effort.strip() or None) if effort is not None else None

    def __repr__(self) -> str:
        return (
            f"LLMConfig(base_url={self.base_url!r}, api_key=SecretStr('**********'), "
            f"model={self.model!r}, effort={self.effort!r})"
        )

    @classmethod
    def load(cls, env_file: Path | None = None) -> "LLMConfig":
        settings = load_settings(env_file)
        missing = [
            name
            for name, value in {
                "LLM_BASE_URL": settings.llm_base_url,
                "LLM_API_KEY": settings.llm_api_key,
                "LLM_MODEL": settings.llm_model,
            }.items()
            if value is None
        ]
        if missing:
            raise ValueError(f"缺少 LLM 配置：{', '.join(missing)}")
        return cls(
            settings.llm_base_url,
            settings.llm_api_key,
            settings.llm_model,
            settings.llm_model_effort,
        )


def load_settings(env_file: Path | None = None, **overrides: object) -> Settings:
    kwargs: dict[str, object] = dict(overrides)
    if env_file is not None:
        kwargs["_env_file"] = env_file
    try:
        return Settings(**kwargs)
    except ValueError as error:
        raise ValueError(f"配置无效：{error}") from error


def validate_workspace_root(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    if resolved == CAPABILITY_REPOSITORY_ROOT or resolved.is_relative_to(
        CAPABILITY_REPOSITORY_ROOT
    ):
        raise ValueError("PCM_WORKSPACE_ROOT 必须位于当前能力仓库之外")
    return resolved


def load_workspace_root(
    override: Path | None = None, env_file: Path | None = None
) -> tuple[Path, str]:
    if override is not None:
        return validate_workspace_root(override), "cli"
    settings = load_settings(env_file)
    source = "environment" if os.environ.get("PCM_WORKSPACE_ROOT") else "env_file"
    if settings.pcm_workspace_root is None:
        raise ValueError("缺少配置：PCM_WORKSPACE_ROOT")
    return validate_workspace_root(settings.pcm_workspace_root), source


def load_template_catalog(
    override: Path | None = None, env_file: Path | None = None
) -> tuple[Path, str]:
    if override is not None:
        return override.expanduser().resolve(), "cli"
    settings = load_settings(env_file)
    source = "environment" if os.environ.get("PCM_TEMPLATE_CATALOG") else "env_file"
    if settings.pcm_template_catalog is None:
        raise ValueError("缺少配置：PCM_TEMPLATE_CATALOG")
    return settings.pcm_template_catalog.expanduser().resolve(), source


def load_template_repository(env_file: Path | None = None) -> tuple[str, str]:
    settings = load_settings(env_file)
    source = "environment" if os.environ.get("PCM_TEMPLATE_REPOSITORY") else "env_file"
    if settings.pcm_template_repository is None:
        raise ValueError("缺少配置：PCM_TEMPLATE_REPOSITORY")
    return settings.pcm_template_repository, source


def read_agent_workspace_env_file(path: Path) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise ValueError(
            "PCM_AGENT_WORKSPACE_ENV_FILE 必须是可读的普通文件"
        ) from error
    try:
        file_stat = os.fstat(descriptor)
        if not S_ISREG(file_stat.st_mode):
            raise ValueError("PCM_AGENT_WORKSPACE_ENV_FILE 必须是可读的普通文件")
        with os.fdopen(descriptor, "rb") as file:
            descriptor = -1
            content = file.read()
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if not content:
        raise ValueError("PCM_AGENT_WORKSPACE_ENV_FILE 不能为空")
    return content


def load_agent_workspace_env_file(
    env_file: Path | None = None,
) -> tuple[Path, str]:
    settings = load_settings(env_file)
    source = (
        "environment"
        if os.environ.get("PCM_AGENT_WORKSPACE_ENV_FILE")
        else "env_file"
    )
    path = settings.pcm_agent_workspace_env_file
    if path is None:
        raise ValueError("缺少配置：PCM_AGENT_WORKSPACE_ENV_FILE")
    if not path.is_absolute():
        raise ValueError("PCM_AGENT_WORKSPACE_ENV_FILE 必须是绝对路径")
    resolved = path.parent.resolve() / path.name
    if resolved.is_symlink():
        raise ValueError("PCM_AGENT_WORKSPACE_ENV_FILE 不能是符号链接")
    read_agent_workspace_env_file(resolved)
    return resolved, source


def load_dev_resource_list(env_file: Path | None = None) -> tuple[Path, str]:
    settings = load_settings(env_file)
    source = "environment" if os.environ.get("PCM_DEV_RESOURCE_LIST") else "env_file"
    path = settings.pcm_dev_resource_list
    if path is None:
        raise ValueError("缺少配置：PCM_DEV_RESOURCE_LIST")
    if not path.is_absolute():
        raise ValueError("PCM_DEV_RESOURCE_LIST 必须是绝对路径")
    if path.is_symlink():
        raise ValueError("PCM_DEV_RESOURCE_LIST 不能是符号链接")
    resolved = path.resolve()
    if not resolved.is_file() or resolved.is_symlink() or not os.access(resolved, os.R_OK):
        raise ValueError("PCM_DEV_RESOURCE_LIST 必须是可读的普通文件")
    return resolved, source
