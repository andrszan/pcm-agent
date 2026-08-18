from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_ENV_FILE = Path(__file__).with_name(".env")


class Settings(BaseSettings):
    llm_base_url: str | None = Field(default=None, validation_alias="LLM_BASE_URL")
    llm_api_key: SecretStr | None = Field(default=None, validation_alias="LLM_API_KEY", repr=False)
    llm_model: str | None = Field(default=None, validation_alias="LLM_MODEL")
    pcm_workspace_root: Path | None = Field(default=None, validation_alias="PCM_WORKSPACE_ROOT")
    pcm_template_repository: str | None = Field(default=None, validation_alias="PCM_TEMPLATE_REPOSITORY")

    model_config = SettingsConfigDict(
        env_file=DEFAULT_ENV_FILE,
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        env_prefix="",
        extra="ignore",
        populate_by_name=True,
        cli_parse_args=False,
    )


class LLMConfig:
    def __init__(self, base_url: str, api_key: SecretStr, model: str) -> None:
        self.base_url = base_url
        self.api_key = api_key
        self.model = model

    def __repr__(self) -> str:
        return f"LLMConfig(base_url={self.base_url!r}, api_key=SecretStr('**********'), model={self.model!r})"

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
        return cls(settings.llm_base_url, settings.llm_api_key, settings.llm_model)


def load_settings(env_file: Path | None = None, **overrides: object) -> Settings:
    kwargs: dict[str, object] = dict(overrides)
    if env_file is not None:
        kwargs["_env_file"] = env_file
    try:
        return Settings(**kwargs)
    except ValueError as error:
        raise ValueError(f"配置无效：{error}") from error


def load_workspace_root(
    override: Path | None = None, env_file: Path | None = None
) -> tuple[Path, str]:
    if override is not None:
        return override.expanduser().resolve(), "cli"
    settings = load_settings(env_file)
    source = "environment" if os.environ.get("PCM_WORKSPACE_ROOT") else "env_file"
    if settings.pcm_workspace_root is None:
        raise ValueError("缺少配置：PCM_WORKSPACE_ROOT")
    return settings.pcm_workspace_root.expanduser().resolve(), source


def load_template_repository(env_file: Path | None = None) -> tuple[str, str]:
    settings = load_settings(env_file)
    source = "environment" if os.environ.get("PCM_TEMPLATE_REPOSITORY") else "env_file"
    if settings.pcm_template_repository is None:
        raise ValueError("缺少配置：PCM_TEMPLATE_REPOSITORY")
    return settings.pcm_template_repository, source
