#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["python-dotenv==1.2.3"]
# ///

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from dotenv import load_dotenv

CACHE_DIR = Path.home() / ".cache" / "media-assets" / "pixabay"
CACHE_SECONDS = 24 * 60 * 60
USER_AGENT = "media-assets/1.0"
MAX_DOWNLOAD = 128 * 1024 * 1024
VARIANTS = {"image": ("preview", "web", "large"), "video": ("tiny", "small", "medium", "large")}
EXTENSIONS = {"image/jpeg": (".jpg", ".jpeg"), "image/png": (".png",), "image/webp": (".webp",), "image/gif": (".gif",), "video/mp4": (".mp4",)}


class MediaError(ValueError):
    pass


def http_url(value: str) -> str:
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise MediaError("仅允许不含内嵌凭据的 HTTP(S) 地址")
    return value


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Pixabay 有限候选检索与选中资源下载，不自动翻页或重试。")
    commands = parser.add_subparsers(dest="action", required=True)
    search = commands.add_parser("search", help="搜索少量候选，不下载原图或视频")
    search.add_argument("-q", "--query", required=True)
    search.add_argument("--media", choices=VARIANTS, default="image")
    search.add_argument("--limit", type=int, choices=range(3, 11), default=5)
    search.add_argument("--image-type", choices=("all", "photo", "illustration", "vector"), default="photo")
    search.add_argument("--orientation", choices=("all", "horizontal", "vertical"), default="all")
    download = commands.add_parser("download", help="按选中的资源 ID 下载一个文件")
    download.add_argument("--id", type=int, required=True)
    download.add_argument("--media", choices=VARIANTS, default="image")
    download.add_argument("--variant", choices=("preview", "web", "large", "tiny", "small", "medium"))
    download.add_argument("-f", "--file", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.action == "search":
        args.query = args.query.strip()
        if not 1 <= len(args.query) <= 100:
            parser.error("查询词应为 1～100 个字符")
        if args.media == "video" and (args.image_type != "photo" or args.orientation != "all"):
            parser.error("视频检索不接受图片类型或方向筛选")
    else:
        if args.id <= 0:
            parser.error("资源 ID 必须为正整数")
        args.variant = args.variant or ("large" if args.media == "image" else "medium")
        if args.variant not in VARIANTS[args.media]:
            parser.error("所选档位不适用于该媒体类型")
    return args


def normalize(hit: dict, media: str) -> dict:
    if not isinstance(hit.get("id"), int) or hit["id"] <= 0:
        raise MediaError("API 返回了无效资源 ID")
    item = {
        "id": hit["id"], "media": media, "type": hit.get("type"),
        "tags": hit.get("tags", ""), "author": hit.get("user", ""),
        "page_url": http_url(hit["pageURL"]), "variants": {},
    }
    if media == "image":
        item.update(original_width=hit.get("imageWidth"), original_height=hit.get("imageHeight"))
        for variant, prefix in (("preview", "preview"), ("web", "webformat"), ("large", "largeImage")):
            if hit.get(prefix + "URL"):
                item["variants"][variant] = {"url": http_url(hit[prefix + "URL"])}
                if variant != "large":
                    item["variants"][variant].update(width=hit.get(prefix + "Width"), height=hit.get(prefix + "Height"))
        item["preview_url"] = item["variants"].get("preview", {}).get("url")
    else:
        item["duration"] = hit.get("duration")
        videos = hit.get("videos") or {}
        for variant in VARIANTS[media]:
            video = videos.get(variant) or {}
            if video.get("url"):
                item["variants"][variant] = {
                    "url": http_url(video["url"]), "width": video.get("width"),
                    "height": video.get("height"), "bytes": video.get("size"),
                }
                if not item.get("preview_url") and video.get("thumbnail"):
                    item["preview_url"] = http_url(video["thumbnail"])
    return item


def api_results(base: str, key: str, media: str, params: dict) -> tuple[list[dict], bool]:
    endpoint = base.rstrip("/") + ("/videos/" if media == "video" else "/")
    identity = json.dumps([endpoint, key, params], sort_keys=True).encode()
    cache = CACHE_DIR / (hashlib.sha256(identity).hexdigest() + ".json")
    now = time.time()
    if cache.is_file():
        cached = json.loads(cache.read_text(encoding="utf-8"))
        if 0 <= now - cached["created_at"] < CACHE_SECONDS:
            if key in json.dumps(cached["items"]):
                raise MediaError("缓存包含凭据，拒绝输出")
            return cached["items"], True
    url = endpoint + "?" + urllib.parse.urlencode({**params, "key": key, "safesearch": "true"})
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read(2 * 1024 * 1024 + 1)
    except urllib.error.HTTPError as error:
        raise MediaError(f"查询接口返回 HTTP {error.code}；未自动重试") from None
    if len(raw) > 2 * 1024 * 1024:
        raise MediaError("API 响应超出有限候选的大小范围")
    payload = json.loads(raw)
    if not isinstance(payload, dict) or not isinstance(payload.get("hits"), list):
        raise MediaError("API 响应缺少候选列表")
    items = [normalize(hit, media) for hit in payload["hits"][:params["per_page"]]]
    encoded = json.dumps({"created_at": now, "items": items}, ensure_ascii=False)
    if key in encoded:
        raise MediaError("API 响应包含凭据，拒绝输出或缓存")
    CACHE_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=CACHE_DIR, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(encoded)
        temporary.replace(cache)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return items, False


def sniff_mime(data: bytes) -> str:
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[4:8] == b"ftyp" and data[8:12] in {b"isom", b"iso2", b"iso3", b"iso4", b"iso5", b"iso6", b"iso7", b"iso8", b"iso9", b"mp41", b"mp42", b"avc1", b"M4V ", b"dash"}:
        return "video/mp4"
    raise MediaError("下载内容不是受支持的图片或 MP4 文件签名")


def download_file(args, base: str, key: str) -> dict:
    output = args.file.expanduser()
    suffixes = (".mp4",) if args.media == "video" else (".jpg", ".jpeg", ".png", ".webp", ".gif")
    if output.suffix.lower() not in suffixes or output.exists() or output.is_symlink():
        raise MediaError("输出扩展名不适用或文件已存在，不会覆盖")
    claimed = None
    complete = False
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("xb") as stream:
            claimed = os.fstat(stream.fileno())
            items, _ = api_results(base, key, args.media, {"id": args.id, "per_page": 3})
            item = next((item for item in items if item["id"] == args.id), None)
            if item is None or args.variant not in item["variants"]:
                raise MediaError("指定资源或档位不可用，不自动替换")
            url = http_url(item["variants"][args.variant]["url"])
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=60) as response:
                first = response.read(64)
                mime = sniff_mime(first)
                if not mime.startswith(args.media + "/") or output.suffix.lower() not in EXTENSIONS[mime]:
                    raise MediaError("实际媒体格式与类型或输出扩展名不一致")
                total = len(first)
                stream.write(first)
                while block := response.read(64 * 1024):
                    total += len(block)
                    if total > MAX_DOWNLOAD:
                        raise MediaError("单个文件超过 128 MiB 开发期下载上限")
                    stream.write(block)
                expected = response.headers.get("Content-Length")
                if expected is not None and total != int(expected):
                    raise MediaError("下载字节数与响应长度不一致")
        complete = True
    finally:
        if claimed is not None and not complete:
            try:
                if os.path.samestat(output.lstat(), claimed):
                    output.unlink()
            except FileNotFoundError:
                pass
    return {"file": str(output.resolve()), "provider": "pixabay", "id": args.id, "media": args.media, "variant": args.variant, "mime": mime, "bytes": total, "author": item["author"], "page_url": item["page_url"]}


def main(argv=None) -> int:
    args = parse_args(argv)
    load_dotenv(Path.cwd() / ".env", override=False)
    key = os.environ.get("PIXABAY_API_KEY", "").strip()
    if not key:
        print("缺少工作区配置：PIXABAY_API_KEY", file=sys.stderr)
        return 2
    try:
        base = http_url(os.environ.get("PIXABAY_API_BASE_URL", "https://pixabay.com/api/").strip())
        if urllib.parse.urlsplit(base).query or urllib.parse.urlsplit(base).fragment:
            raise MediaError("API 基地址不能包含查询参数或片段")
        if args.action == "search":
            params = {"q": args.query, "per_page": args.limit}
            if args.media == "image":
                params.update(image_type=args.image_type, orientation=args.orientation)
            items, cached = api_results(base, key, args.media, params)
            candidates = [{**{k: v for k, v in item.items() if k != "variants"}, "variants": {name: {k: v for k, v in variant.items() if k != "url"} for name, variant in item["variants"].items()}} for item in items]
            result = {"provider": "pixabay", "media": args.media, "cached": cached, "count": len(candidates), "candidates": candidates}
        else:
            result = download_file(args, base, key)
    except urllib.error.HTTPError as error:
        print(f"Pixabay 文件下载失败：HTTP {error.code}；未自动重试", file=sys.stderr)
        return 1
    except urllib.error.URLError as error:
        reason = type(error.reason).__name__ if isinstance(error.reason, BaseException) else "连接失败"
        print(f"Pixabay 网络请求失败：{reason}；未自动重试", file=sys.stderr)
        return 1
    except MediaError as error:
        print(f"Pixabay 处理失败：{error}", file=sys.stderr)
        return 1
    except (OSError, ValueError, KeyError, TypeError, AttributeError, http.client.HTTPException) as error:
        print(f"Pixabay 请求、缓存或文件处理失败：{type(error).__name__}；未自动重试", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
