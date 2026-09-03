from __future__ import annotations

import fcntl
import hashlib
import json
import os
import socket
import stat
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TextIO

from common.files import write_json

PORT_SLOTS = range(100, 1000)


@dataclass
class HeldLock:
    name: str
    path: Path
    handle: TextIO

    def close(self) -> None:
        self.handle.close()

    def __enter__(self) -> "HeldLock":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


@dataclass
class ExecutionLocks:
    stack: ExitStack
    run: HeldLock
    capacity: HeldLock
    product: HeldLock | None = None

    def close(self) -> None:
        self.stack.close()

    def __enter__(self) -> "ExecutionLocks":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def file_descriptors(self) -> tuple[int, ...]:
        return tuple(int(item["fd"]) for item in self.descriptors().values())

    def descriptors(self) -> dict[str, dict[str, object]]:
        result = {
            "run": {"fd": self.run.handle.fileno(), "path": str(self.run.path)},
            "capacity": {
                "fd": self.capacity.handle.fileno(),
                "path": str(self.capacity.path),
            },
        }
        if self.product is not None:
            result["product"] = {
                "fd": self.product.handle.fileno(),
                "path": str(self.product.path),
            }
        return result


def coordination_root(demo_root: Path) -> Path:
    return demo_root / "runs" / ".coordination"


def _ensure_directory(path: Path) -> None:
    current = path
    missing: list[Path] = []
    while not current.exists():
        missing.append(current)
        current = current.parent
    if current.is_symlink() or not current.is_dir():
        raise RuntimeError(f"协调目录无效：{current}")
    for directory in reversed(missing):
        directory.mkdir()
        if directory.is_symlink() or not directory.is_dir():
            raise RuntimeError(f"协调目录无效：{directory}")


def _lock_path(root: Path, kind: str, key: str) -> Path:
    path = root / "locks" / kind / f"{key}.lock"
    _ensure_directory(path.parent)
    if path.is_symlink():
        raise RuntimeError(f"锁文件不能是符号链接：{path}")
    return path


def run_lock_path(root: Path, run_id: str) -> Path:
    if Path(run_id).name != run_id or run_id in {"", ".", ".."}:
        raise ValueError(f"无效运行 ID：{run_id}")
    return _lock_path(root, "runs", run_id)


def product_key(product_path: Path) -> tuple[str, Path]:
    canonical = product_path.expanduser().resolve(strict=False)
    key = hashlib.sha256(f"pcm-product-v1\0{canonical}".encode()).hexdigest()
    return key, canonical


def product_lock_path(root: Path, key: str) -> Path:
    if len(key) != 64 or any(character not in "0123456789abcdef" for character in key):
        raise ValueError("无效产品 key")
    return _lock_path(root, "products", key)


def _metadata(run_id: str, kind: str, **extra: object) -> dict[str, object]:
    return {
        "run_id": run_id,
        "kind": kind,
        "pid": os.getpid(),
        "started_at": datetime.now(timezone.utc).isoformat(),
        **extra,
    }


def acquire_lock(path: Path, *, name: str, metadata: dict[str, object]) -> HeldLock:
    _ensure_directory(path.parent)
    if path.is_symlink():
        raise RuntimeError(f"锁文件不能是符号链接：{path}")
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as error:
        raise RuntimeError(f"锁文件无法安全打开：{path}") from error
    handle = os.fdopen(descriptor, "r+", encoding="utf-8")
    if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
        handle.close()
        raise RuntimeError(f"锁路径必须是普通文件：{path}")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.seek(0)
        owner = handle.read().strip()
        handle.close()
        detail = f"：{owner}" if owner else ""
        raise RuntimeError(f"{name}已被占用{detail}") from None
    except BaseException:
        handle.close()
        raise
    handle.seek(0)
    handle.truncate()
    json.dump(metadata, handle, ensure_ascii=False)
    handle.write("\n")
    handle.flush()
    os.fsync(handle.fileno())
    os.set_inheritable(handle.fileno(), False)
    return HeldLock(name, path, handle)


def adopt_lock(fd: int, path: Path, *, name: str) -> HeldLock:
    if fd < 0 or path.is_symlink():
        raise RuntimeError(f"继承的{name}无效")
    descriptor_stat = os.fstat(fd)
    path_stat = path.stat()
    if (descriptor_stat.st_dev, descriptor_stat.st_ino) != (path_stat.st_dev, path_stat.st_ino):
        raise RuntimeError(f"继承的{name}与预期锁文件不一致")
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise RuntimeError(f"继承的{name}未持有预期排他锁") from None
    os.set_inheritable(fd, False)
    return HeldLock(name, path, os.fdopen(fd, "a+", encoding="utf-8", closefd=True))


def lock_status(path: Path) -> tuple[bool, dict[str, Any] | None]:
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as error:
        raise RuntimeError(f"锁文件无法安全打开：{path}") from error
    with os.fdopen(descriptor, "r+", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            held = False
        except BlockingIOError:
            held = True
        handle.seek(0)
        try:
            metadata = json.loads(handle.read())
        except (json.JSONDecodeError, TypeError):
            metadata = None
        if not isinstance(metadata, dict):
            metadata = None
        return held, metadata


def acquire_capacity(root: Path, maximum: int, run_id: str) -> HeldLock:
    if type(maximum) is not int or maximum < 1:
        raise ValueError("PCM_MAX_CONCURRENT_PROJECTS 必须是正整数")
    errors: list[RuntimeError] = []
    for slot in range(maximum):
        path = _lock_path(root, "capacity", str(slot))
        try:
            return acquire_lock(
                path,
                name="宿主机执行名额",
                metadata=_metadata(run_id, "capacity", slot=slot),
            )
        except RuntimeError as error:
            errors.append(error)
    raise RuntimeError(f"宿主机 PCM 并发执行名额已满：{maximum}/{maximum}") from errors[-1]


def acquire_execution_locks(root: Path, run_id: str, maximum: int) -> ExecutionLocks:
    stack = ExitStack()
    try:
        run = stack.enter_context(
            acquire_lock(
                run_lock_path(root, run_id),
                name="运行锁",
                metadata=_metadata(run_id, "run"),
            )
        )
        capacity = stack.enter_context(acquire_capacity(root, maximum, run_id))
        return ExecutionLocks(stack, run, capacity)
    except BaseException:
        stack.close()
        raise


def acquire_product_lock(root: Path, run_id: str, key: str, product_path: Path) -> HeldLock:
    return acquire_lock(
        product_lock_path(root, key),
        name="产品锁",
        metadata=_metadata(run_id, "product", product_key=key, product_path=str(product_path)),
    )


def inherited_lock_argument(locks: ExecutionLocks) -> str:
    return json.dumps(locks.descriptors(), separators=(",", ":"))


def adopt_execution_locks(
    root: Path, run_id: str, serialized: str, maximum: int
) -> ExecutionLocks:
    try:
        values = json.loads(serialized)
    except json.JSONDecodeError as error:
        raise RuntimeError("继承锁参数无效") from error
    if not isinstance(values, dict) or set(values) not in (
        {"run", "capacity"},
        {"run", "capacity", "product"},
    ):
        raise RuntimeError("继承锁参数无效")

    stack = ExitStack()
    try:
        adopted: dict[str, HeldLock] = {}
        for name, value in values.items():
            if (
                not isinstance(value, dict)
                or type(value.get("fd")) is not int
                or not isinstance(value.get("path"), str)
            ):
                raise RuntimeError("继承锁参数无效")
            path = Path(value["path"])
            if name == "run":
                expected = run_lock_path(root, run_id)
            elif name == "capacity":
                expected_parent = root / "locks" / "capacity"
                if (
                    path.parent != expected_parent
                    or not path.stem.isdigit()
                    or int(path.stem) not in range(maximum)
                ):
                    raise RuntimeError("继承的执行名额锁路径无效")
                expected = path
            else:
                expected_parent = root / "locks" / "products"
                if path.parent != expected_parent or len(path.stem) != 64:
                    raise RuntimeError("继承的产品锁路径无效")
                expected = path
            if path != expected:
                raise RuntimeError(f"继承的{name}锁路径不一致")
            os.set_inheritable(value["fd"], False)
            duplicate = os.dup(value["fd"])
            os.set_inheritable(duplicate, False)
            adopted[name] = stack.enter_context(
                adopt_lock(duplicate, expected, name=f"{name}锁")
            )
        return ExecutionLocks(
            stack,
            adopted["run"],
            adopted["capacity"],
            adopted.get("product"),
        )
    except BaseException:
        stack.close()
        raise


def _registry_path(root: Path) -> Path:
    _ensure_directory(root)
    path = root / "products.json"
    if path.is_symlink():
        raise RuntimeError("产品注册表不能是符号链接")
    return path


def _read_registry(root: Path) -> dict[str, Any]:
    path = _registry_path(root)
    if not path.exists():
        return {"schema_version": 1, "products": {}}
    descriptor = -1
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise RuntimeError("产品注册表必须是普通文件")
        with os.fdopen(descriptor, "r", encoding="utf-8") as source:
            descriptor = -1
            registry = json.load(source)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RuntimeError("产品注册表不可读取") from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if (
        not isinstance(registry, dict)
        or registry.get("schema_version") != 1
        or not isinstance(registry.get("products"), dict)
    ):
        raise RuntimeError("产品注册表格式无效")
    return registry


def _ports_for_slot(slot: int) -> dict[str, int]:
    return {"frontend": 3000 + slot, "backend": 8000 + slot}


def _ports_bindable(ports: dict[str, int]) -> bool:
    sockets: list[socket.socket] = []
    try:
        for port in ports.values():
            current = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            current.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
            current.bind(("127.0.0.1", port))
            sockets.append(current)
        return True
    except OSError:
        return False
    finally:
        for current in sockets:
            current.close()


def claim_product(root: Path, run_id: str, key: str, product_path: Path) -> dict[str, Any]:
    canonical_key, canonical_path = product_key(product_path)
    if canonical_key != key:
        raise RuntimeError("产品 key 与最终路径不一致")
    registry_lock = acquire_lock(
        root / "registry.lock",
        name="产品注册表锁",
        metadata=_metadata(run_id, "registry"),
    )
    with registry_lock:
        registry = _read_registry(root)
        products = registry["products"]
        existing = products.get(key)
        if existing is not None:
            if (
                isinstance(existing, dict)
                and existing.get("product_path") == str(canonical_path)
                and existing.get("owner_run_id") == run_id
                and existing.get("lifecycle") == "active"
            ):
                return existing
            owner = existing.get("owner_run_id") if isinstance(existing, dict) else None
            raise RuntimeError(f"产品已由其他运行认领：{owner or '未知'}")

        used = {
            item.get("port_slot")
            for item in products.values()
            if isinstance(item, dict) and item.get("lifecycle") == "active"
        }
        for slot in PORT_SLOTS:
            ports = _ports_for_slot(slot)
            if slot not in used and _ports_bindable(ports):
                record = {
                    "product_path": str(canonical_path),
                    "owner_run_id": run_id,
                    "lifecycle": "active",
                    "port_slot": slot,
                    "ports": ports,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "released_at": None,
                }
                products[key] = record
                write_json(_registry_path(root), registry)
                return record
        raise RuntimeError("没有可用的 PCM 产品端口组")


def get_product(root: Path, key: str) -> dict[str, Any]:
    registry = _read_registry(root)
    record = registry["products"].get(key)
    if not isinstance(record, dict):
        raise RuntimeError("产品注册记录不存在")
    return record


def validate_product_record(
    root: Path, run_id: str, key: str, product_path: Path
) -> dict[str, Any]:
    record = get_product(root, key)
    canonical_key, canonical_path = product_key(product_path)
    if (
        canonical_key != key
        or record.get("product_path") != str(canonical_path)
        or record.get("owner_run_id") != run_id
        or record.get("lifecycle") != "active"
        or record.get("ports") != _ports_for_slot(record.get("port_slot"))
    ):
        raise RuntimeError("产品注册记录与运行状态不一致")
    return record


def runtime_data(key: str, run_id: str, record: dict[str, Any]) -> dict[str, Any]:
    ports = record["ports"]
    return {
        "schema_version": 1,
        "product_key": key,
        "owner_run_id": run_id,
        "host": "127.0.0.1",
        "services": {
            name: {"port": port, "url": f"http://127.0.0.1:{port}"}
            for name, port in ports.items()
        },
    }


def ensure_runtime(workspace: Path, key: str, run_id: str, record: dict[str, Any]) -> Path:
    expected = runtime_data(key, run_id, record)
    directory = workspace / ".pcm"
    if workspace.is_symlink() or directory.is_symlink():
        raise RuntimeError("产品本机运行配置目录不能是符号链接")
    directory.mkdir(exist_ok=True)
    path = directory / "runtime.json"
    if path.is_symlink():
        raise RuntimeError("产品本机运行配置不能是符号链接")
    if path.exists():
        descriptor = -1
        try:
            descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise RuntimeError("产品本机运行配置必须是普通文件")
            with os.fdopen(descriptor, "r", encoding="utf-8") as source:
                descriptor = -1
                current = json.load(source)
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise RuntimeError("产品本机运行配置不可读取") from error
        finally:
            if descriptor >= 0:
                os.close(descriptor)
        if current != expected:
            raise RuntimeError("产品本机运行配置与注册记录不一致")
    else:
        write_json(path, expected)
    git_directory = workspace / ".git"
    ignore = (
        git_directory / "info" / "exclude"
        if git_directory.is_dir() and not git_directory.is_symlink()
        else workspace / ".gitignore"
    )
    ignore.parent.mkdir(parents=True, exist_ok=True)
    existing = ignore.read_text(encoding="utf-8") if ignore.is_file() else ""
    if "/.pcm/" not in existing.splitlines():
        with ignore.open("a", encoding="utf-8") as output:
            if existing and not existing.endswith("\n"):
                output.write("\n")
            output.write("/.pcm/\n")
    return path


def release_product(root: Path, product_path: Path) -> dict[str, Any]:
    key, canonical = product_key(product_path)
    snapshot = get_product(root, key)
    run_id = snapshot.get("owner_run_id")
    if not isinstance(run_id, str) or not run_id:
        raise RuntimeError("产品 owner run 无效")
    with acquire_lock(
        run_lock_path(root, run_id),
        name="运行锁",
        metadata=_metadata(run_id, "release-run"),
    ):
        with acquire_product_lock(root, run_id, key, canonical):
            registry_lock = acquire_lock(
                root / "registry.lock",
                name="产品注册表锁",
                metadata=_metadata(run_id, "release-registry"),
            )
            with registry_lock:
                registry = _read_registry(root)
                record = registry["products"].get(key)
                if record != snapshot or record.get("lifecycle") != "active":
                    raise RuntimeError("产品注册记录在释放前发生变化")
                if not _ports_bindable(record["ports"]):
                    raise RuntimeError("产品端口仍被占用，拒绝释放")
                record["lifecycle"] = "released"
                record["released_at"] = datetime.now(timezone.utc).isoformat()
                write_json(_registry_path(root), registry)
                return record
