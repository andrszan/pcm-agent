from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, repr=False)
class LLMConfig:
    base_url: str
    api_key: str
    model: str

    @classmethod
    def load(cls, env_file: Path | None = None) -> "LLMConfig":
        values = _read_env(env_file or Path(__file__).with_name(".env"))
        config = {
            name: os.environ.get(name) or values.get(name, "")
            for name in ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL")
        }
        missing = [name for name, value in config.items() if not value]
        if missing:
            raise ValueError(f"缺少 LLM 配置：{', '.join(missing)}")
        return cls(
            base_url=config["LLM_BASE_URL"],
            api_key=config["LLM_API_KEY"],
            model=config["LLM_MODEL"],
        )


def _read_env(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}

    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(path.read_text().splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            raise ValueError(f"无效环境配置行：{path}:{line_number}")
        name, value = line.split("=", 1)
        name = name.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[name] = value
    return values
