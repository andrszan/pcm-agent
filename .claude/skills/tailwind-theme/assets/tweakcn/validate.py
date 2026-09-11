"""离线校验本目录中的 tweakcn 主题快照。"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
THEMES_DIR = ROOT / "themes"
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
COLOR_RE = re.compile(r"^(?:oklch|hsl|hsla|rgb|rgba)\([^\n]+\)$|^#[0-9a-fA-F]{3,8}$")
NUMBER_RE = re.compile(r"^(?:0(?:\.\d+)?|1(?:\.0+)?)$")
LENGTH_RE = re.compile(r"^-?(?:0|\d+(?:\.\d+)?(?:px|rem|em|%))$")
CALC_TRACKING_RE = re.compile(
    r"^calc\(var\(--tracking-normal\) [+-] \d+(?:\.\d+)?em\)$"
)
FORBIDDEN = ("\n", "\r", ";", "{", "}", "/*", "*/", "@import", "url(", "image-set(", "expression(", "javascript:", "data:")

COLOR_TOKENS = {
    "background", "foreground", "card", "card-foreground", "popover",
    "popover-foreground", "primary", "primary-foreground", "secondary",
    "secondary-foreground", "muted", "muted-foreground", "accent",
    "accent-foreground", "destructive", "destructive-foreground", "border",
    "input", "ring", "chart-1", "chart-2", "chart-3", "chart-4", "chart-5",
    "sidebar", "sidebar-foreground", "sidebar-primary",
    "sidebar-primary-foreground", "sidebar-accent", "sidebar-accent-foreground",
    "sidebar-border", "sidebar-ring", "shadow-color",
}
FONT_TOKENS = {"font-sans", "font-serif", "font-mono"}
LENGTH_TOKENS = {
    "radius", "shadow-blur", "shadow-spread", "shadow-offset-x",
    "shadow-offset-y", "letter-spacing", "spacing", "tracking-normal",
}
SHADOW_TOKENS = {
    "shadow-2xs", "shadow-xs", "shadow-sm", "shadow", "shadow-md",
    "shadow-lg", "shadow-xl", "shadow-2xl",
}
THEME_TOKENS = {
    "font-sans", "font-serif", "font-mono", "radius", "tracking-tighter",
    "tracking-tight", "tracking-wide", "tracking-wider", "tracking-widest",
}
MODE_TOKENS = COLOR_TOKENS | FONT_TOKENS | LENGTH_TOKENS | SHADOW_TOKENS | {"shadow-opacity"}
DARK_MODE_TOKENS = MODE_TOKENS - {"tracking-normal"}


def fail(message: str) -> None:
    raise ValueError(message)


def load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        fail(f"{path}: JSON 无法解析：{error}")
    if not isinstance(value, dict):
        fail(f"{path}: 顶层必须是 object")
    return value


def safe_string(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        fail(f"{where}: 必须是首尾无空白的非空字符串")
    lowered = value.lower()
    if any(part in lowered for part in FORBIDDEN) or any(ord(char) < 32 for char in value):
        fail(f"{where}: 含不允许的 CSS 载荷或控制字符")
    return value


def validate_token(token: str, value: Any, where: str) -> None:
    value = safe_string(value, where)
    if token in COLOR_TOKENS and not COLOR_RE.fullmatch(value):
        fail(f"{where}: 不是支持的颜色值")
    if token in FONT_TOKENS and not re.fullmatch(r"[\w .,'\"-]+", value):
        fail(f"{where}: 不是安全的字体 family 列表")
    if token in LENGTH_TOKENS and not (
        LENGTH_RE.fullmatch(value)
        or (token in {"letter-spacing", "tracking-normal"} and value == "normal")
    ):
        fail(f"{where}: 不是支持的单一长度值")
    if token == "shadow-opacity" and not NUMBER_RE.fullmatch(value):
        fail(f"{where}: 不是 0 到 1 的数值字符串")
    if token in SHADOW_TOKENS:
        if not re.fullmatch(r"[\w\s.,%#()\-/]+", value) or not any(
            marker in value for marker in ("hsl(", "hsla(", "rgb(", "rgba(", "oklch(", "#")
        ):
            fail(f"{where}: 不是支持的安全 shadow 值")


def validate_string_map(value: Any, expected: set[str], where: str) -> None:
    if not isinstance(value, dict):
        fail(f"{where}: 必须是 object")
    if set(value) != expected:
        missing = sorted(expected - set(value))
        extra = sorted(set(value) - expected)
        fail(f"{where}: token 集不完整，missing={missing}, extra={extra}")
    for token, token_value in value.items():
        if not isinstance(token, str):
            fail(f"{where}: token 名必须是字符串")
        validate_token(token, token_value, f"{where}.{token}")


def validate_css(value: Any, where: str) -> None:
    if not isinstance(value, dict) or set(value) != {"@layer base"}:
        fail(f"{where}: 仅允许 @layer base")
    layer = value["@layer base"]
    if not isinstance(layer, dict) or set(layer) != {"body"}:
        fail(f"{where}.@layer base: 仅允许 body")
    body = layer["body"]
    if not isinstance(body, dict) or set(body) != {"letter-spacing"}:
        fail(f"{where}.@layer base.body: 仅允许 letter-spacing")
    if safe_string(body["letter-spacing"], f"{where}.@layer base.body.letter-spacing") != "var(--tracking-normal)":
        fail(f"{where}: body letter-spacing 必须引用 --tracking-normal")


def validate_theme(path: Path) -> tuple[str, str]:
    item = load_object(path)
    required_top = {"name", "type", "title", "description", "css", "cssVars"}
    if set(item) != required_top:
        fail(f"{path}: 顶层字段与快照合同不一致")
    slug = safe_string(item["name"], f"{path}.name")
    if not SLUG_RE.fullmatch(slug) or path.stem != slug:
        fail(f"{path}: name 必须是与文件名一致的 kebab-case slug")
    if item["type"] != "registry:style":
        fail(f"{path}: type 必须是 registry:style")
    title = safe_string(item["title"], f"{path}.title")
    safe_string(item["description"], f"{path}.description")
    validate_css(item["css"], f"{path}.css")
    css_vars = item["cssVars"]
    if not isinstance(css_vars, dict) or set(css_vars) != {"theme", "light", "dark"}:
        fail(f"{path}.cssVars: 必须完整包含 theme/light/dark")
    validate_string_map(css_vars["theme"], THEME_TOKENS, f"{path}.cssVars.theme")
    for token in THEME_TOKENS - FONT_TOKENS - {"radius"}:
        value = safe_string(css_vars["theme"][token], f"{path}.cssVars.theme.{token}")
        if not CALC_TRACKING_RE.fullmatch(value):
            fail(f"{path}.cssVars.theme.{token}: 不是受支持的 tracking calc")
    validate_string_map(css_vars["light"], MODE_TOKENS, f"{path}.cssVars.light")
    validate_string_map(css_vars["dark"], DARK_MODE_TOKENS, f"{path}.cssVars.dark")
    return slug, title


def main() -> int:
    catalog = load_object(ROOT / "catalog.json")
    if set(catalog) != {"themes"} or not isinstance(catalog["themes"], list):
        fail("catalog.json: 顶层必须仅包含 themes 数组")

    entries: dict[str, dict[str, Any]] = {}
    paths: set[str] = set()
    for index, entry in enumerate(catalog["themes"]):
        where = f"catalog.json.themes[{index}]"
        if not isinstance(entry, dict) or set(entry) != {"slug", "name", "path", "features"}:
            fail(f"{where}: 必须仅包含 slug/name/path/features")
        slug = safe_string(entry["slug"], f"{where}.slug")
        name = safe_string(entry["name"], f"{where}.name")
        relative_path = safe_string(entry["path"], f"{where}.path")
        features = safe_string(entry["features"], f"{where}.features")
        if not SLUG_RE.fullmatch(slug) or relative_path != f"themes/{slug}.json":
            fail(f"{where}: slug 或 path 不符合约定")
        if not re.search(r"[一-鿿]", features):
            fail(f"{where}.features: 必须包含中文简短风格特征")
        if slug in entries or relative_path in paths:
            fail(f"{where}: slug 或 path 重复")
        entries[slug] = {"name": name, "path": relative_path}
        paths.add(relative_path)

    files = sorted(THEMES_DIR.glob("*.json"))
    if {path.name for path in files} != {f"{slug}.json" for slug in entries}:
        fail("catalog.json 与 themes/*.json 文件集合不一致")
    for path in files:
        slug, title = validate_theme(path)
        if entries[slug]["name"] != title:
            fail(f"{path}: title 与 catalog name 不一致")

    print(f"验证通过：{len(files)} 个 tweakcn registry:style 主题")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ValueError as error:
        print(f"验证失败：{error}", file=sys.stderr)
        sys.exit(1)
