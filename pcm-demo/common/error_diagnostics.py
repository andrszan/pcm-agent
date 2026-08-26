from __future__ import annotations

import hashlib
import re
import traceback
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import quote, quote_plus, urlsplit, urlunsplit

from common.files import write_json

SCHEMA_VERSION = 1
_TEXT_LIMIT = 4_000
_LIST_LIMIT = 32
_TRACEBACK_LIMIT = 24
_SAFE_LOG_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\.json\Z")
_SENSITIVE_KEY = r"(?:[A-Za-z][A-Za-z0-9]*[_-])*(?:api[_-]?key|access[_-]?token|refresh[_-]?token|client[_-]?secret|password|secret)|(?:proxy-)?authorization|(?:set-)?cookie"
_QUOTED_VALUE = re.compile(
    rf"(?P<key>\b(?:{_SENSITIVE_KEY})\b)(?P<key_quote>[\"']?)(?P<separator>\s*[:=]\s*)(?P<quote>[\"'])(?P<value>.*?)(?P=quote)",
    re.IGNORECASE,
)
_PLAIN_VALUE = re.compile(
    rf"(?P<key>\b{_SENSITIVE_KEY}\b)(?P<separator>\s*[:=]\s*)(?P<value>[^\s,;}}&#]+)",
    re.IGNORECASE,
)
_AUTH_VALUE = re.compile(
    r"(?P<key>\b(?:proxy-)?authorization\b)(?P<separator>\s*[:=]\s*)(?P<value>(?:Bearer\s+)?[^\s,;}\]]+)",
    re.IGNORECASE,
)
_COOKIE_VALUE = re.compile(
    r"(?P<key>\b(?:set-)?cookie\b)(?P<separator>\s*[:=]\s*)(?P<value>[^\r\n]+)",
    re.IGNORECASE,
)
_URL = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://[^\s'\"<>]+")
_QUERY_VALUE = re.compile(rf"(?P<key>{_SENSITIVE_KEY})(?P<separator>=)(?P<value>[^&#]*)", re.IGNORECASE)


def truncate_text(value: str, limit: int = _TEXT_LIMIT) -> str:
    """截断不受控错误文本，同时保留首尾诊断线索。"""
    if len(value) <= limit:
        return value
    head = max(1, limit * 2 // 3)
    tail = max(1, limit - head)
    return f"{value[:head]}[truncated]{value[-tail:]}"


def _known_forms(known_secrets: Sequence[str] | None) -> list[str]:
    forms: set[str] = set()
    for secret in known_secrets or ():
        if isinstance(secret, str) and secret:
            forms.update((secret, quote(secret, safe=""), quote_plus(secret, safe="")))
    return sorted(forms, key=len, reverse=True)


def _redact_url(match: re.Match[str]) -> str:
    raw = match.group(0)
    trailing = ""
    while raw and raw[-1] in ".,);":
        trailing = raw[-1] + trailing
        raw = raw[:-1]
    try:
        parsed = urlsplit(raw)
        netloc = parsed.netloc
        if "@" in netloc:
            userinfo, host = netloc.rsplit("@", 1)
            if ":" in userinfo:
                username, _password = userinfo.split(":", 1)
                netloc = f"{username}:[REDACTED]@{host}"
        query = _QUERY_VALUE.sub(
            lambda item: f"{item.group('key')}=[REDACTED]", parsed.query
        )
        return urlunsplit(parsed._replace(netloc=netloc, query=query)) + trailing
    except ValueError:
        return raw + trailing


def redact_text(value: object, *, known_secrets: Sequence[str] | None = None) -> str:
    """只遮盖确定的凭据，保留其余错误上下文。"""
    text = value if isinstance(value, str) else str(value)
    for secret in _known_forms(known_secrets):
        text = text.replace(secret, "[REDACTED]")
    text = _URL.sub(_redact_url, text)
    text = _QUOTED_VALUE.sub(
        lambda item: f"{item.group('key')}{item.group('key_quote')}{item.group('separator')}{item.group('quote')}[REDACTED]{item.group('quote')}",
        text,
    )
    text = _COOKIE_VALUE.sub(
        lambda item: f"{item.group('key')}{item.group('separator')}[REDACTED]", text
    )
    text = _AUTH_VALUE.sub(
        lambda item: f"{item.group('key')}{item.group('separator')}[REDACTED]", text
    )
    text = _PLAIN_VALUE.sub(
        lambda item: f"{item.group('key')}{item.group('separator')}[REDACTED]", text
    )
    return truncate_text(text)


def sanitize_value(
    value: Any,
    *,
    known_secrets: Sequence[str] | None = None,
    text_limit: int = _TEXT_LIMIT,
    list_limit: int = _LIST_LIMIT,
) -> Any:
    """将诊断字段限制为可安全写入 JSON 的短值。"""
    if isinstance(value, str):
        return truncate_text(redact_text(value, known_secrets=known_secrets), text_limit)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, Mapping):
        items = list(value.items())
        sanitized = {
            redact_text(str(key), known_secrets=known_secrets): sanitize_value(
                item,
                known_secrets=known_secrets,
                text_limit=text_limit,
                list_limit=list_limit,
            )
            for key, item in items[:list_limit]
        }
        if len(items) > list_limit:
            sanitized["[truncated]"] = f"{len(items) - list_limit} items omitted"
        return sanitized
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        result = [
            sanitize_value(
                item,
                known_secrets=known_secrets,
                text_limit=text_limit,
                list_limit=list_limit,
            )
            for item in value[:list_limit]
        ]
        if len(value) > list_limit:
            result.append("[truncated]")
        return result
    return truncate_text(redact_text(repr(value), known_secrets=known_secrets), text_limit)


def exception_diagnostics(
    error: BaseException,
    *,
    known_secrets: Sequence[str] | None = None,
) -> dict[str, Any]:
    """提取异常正文、最多三层异常链和无源码 traceback 位置。"""
    chain: list[dict[str, str]] = []
    seen = {id(error)}
    current = error
    for _ in range(3):
        next_error = current.__cause__ or current.__context__
        if next_error is None or id(next_error) in seen:
            break
        relation = "cause" if current.__cause__ is next_error else "context"
        chain.append(
            {
                "relation": relation,
                "type": type(next_error).__name__,
                "message": redact_text(str(next_error), known_secrets=known_secrets),
            }
        )
        seen.add(id(next_error))
        current = next_error
    frames = traceback.extract_tb(error.__traceback__)
    frame_data = [
        {
            "file": redact_text(frame.filename, known_secrets=known_secrets),
            "line": frame.lineno,
            "function": redact_text(frame.name, known_secrets=known_secrets),
        }
        for frame in frames[-_TRACEBACK_LIMIT:]
    ]
    if len(frames) > _TRACEBACK_LIMIT:
        frame_data.insert(0, {"file": "[truncated]", "line": 0, "function": "[truncated]"})
    return {
        "type": type(error).__name__,
        "message": redact_text(str(error), known_secrets=known_secrets),
        "chain": chain,
        "traceback": frame_data,
    }


def exception_projection(
    error: BaseException,
    *,
    diagnostic_path: str | None = None,
    known_secrets: Sequence[str] | None = None,
) -> dict[str, str]:
    projection = {
        "type": type(error).__name__,
        "message": redact_text(str(error), known_secrets=known_secrets),
    }
    if diagnostic_path is not None:
        projection["diagnostic_path"] = diagnostic_path
    return projection


def safe_diagnostic_filename(filename: str) -> str:
    """将领域诊断名规范为安全、稳定且有界的 JSON 文件名。"""
    if (
        not isinstance(filename, str)
        or not filename.endswith(".json")
        or not filename[:-5]
        or "/" in filename
        or "\\" in filename
        or Path(filename).name != filename
    ):
        raise ValueError("诊断日志文件名不安全")
    if _SAFE_LOG_NAME.fullmatch(filename):
        return filename
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "-", filename[:-5]).strip("._-")
    prefix = (stem or "diagnostic")[:96]
    digest = hashlib.sha256(filename.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}-{digest}.json"


def _safe_log_path(run_dir: Path, filename: str) -> tuple[Path, str]:
    filename = safe_diagnostic_filename(filename)
    if run_dir.is_symlink() or not run_dir.is_dir():
        raise ValueError("运行目录不能是符号链接且必须存在")
    logs = run_dir / "logs"
    if logs.exists() and (logs.is_symlink() or not logs.is_dir()):
        raise ValueError("诊断日志目录不能是符号链接且必须是目录")
    logs.mkdir(exist_ok=True)
    if logs.is_symlink() or logs.resolve().parent != run_dir.resolve():
        raise ValueError("诊断日志目录超出运行目录")
    target = logs / filename
    if target.is_symlink():
        raise ValueError("诊断日志文件不能是符号链接")
    return target, (Path("logs") / filename).as_posix()


def write_diagnostic(
    run_dir: Path,
    filename: str,
    *,
    source: str,
    kind: str | None = None,
    context: Mapping[str, Any] | None = None,
    details: Mapping[str, Any] | None = None,
    error: BaseException | None = None,
    exception: Mapping[str, Any] | None = None,
    known_secrets: Sequence[str] | None = None,
) -> str:
    """原子覆盖当前故障快照，并返回 state/result 可保存的相对路径。"""
    target, relative_path = _safe_log_path(run_dir, filename)
    if exception is not None:
        exception_data = sanitize_value(exception, known_secrets=known_secrets)
    elif error is not None and isinstance(
        (safe_exception := getattr(error, "exception_details", None)), Mapping
    ):
        exception_data = sanitize_value(safe_exception, known_secrets=known_secrets)
    elif error is not None:
        exception_data = exception_diagnostics(error, known_secrets=known_secrets)
    else:
        exception_data = {"type": None, "message": None, "chain": [], "traceback": []}
    document = {
        "schema_version": SCHEMA_VERSION,
        "context": sanitize_value(context or {}, known_secrets=known_secrets),
        "source": redact_text(source, known_secrets=known_secrets),
        "kind": redact_text(kind, known_secrets=known_secrets) if kind else None,
        "exception": exception_data,
        "details": sanitize_value(details or {}, known_secrets=known_secrets),
    }
    write_json(target, document)
    return relative_path
