#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["openai==3.1.0", "python-dotenv==1.2.3"]
# ///

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import struct
import sys
import urllib.parse
import urllib.request
from pathlib import Path

from dotenv import load_dotenv
from openai import APIError, APIStatusError, OpenAI


class ImageResponseError(ValueError):
    pass


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="使用工作区配置生成一张 PNG 图片，不自动重试。")
    prompt = parser.add_mutually_exclusive_group(required=True)
    prompt.add_argument("-p", "--prompt", help="已经收敛的视觉描述")
    prompt.add_argument("--prompt-file", type=Path, help="可选的 UTF-8 提示词文件")
    parser.add_argument("-f", "--file", required=True, type=Path, help="明确的输出 PNG 路径，不覆盖已有文件")
    parser.add_argument("--model", default="gpt-image-2")
    parser.add_argument("--size", default="1024x1024", help="宽x高，例如 1536x1024")
    parser.add_argument("--quality", choices=("low", "medium", "high", "auto"), default="medium")
    return parser.parse_args(argv)


def image_bytes(response) -> tuple[bytes, int, int]:
    if not response.data or len(response.data) != 1:
        raise ImageResponseError("服务未返回单张图片")
    image = response.data[0]
    if image.b64_json:
        data = base64.b64decode(image.b64_json, validate=True)
    elif image.url:
        if urllib.parse.urlsplit(image.url).scheme not in {"http", "https"}:
            raise ImageResponseError("图片下载地址不是 HTTP(S)")
        with urllib.request.urlopen(image.url, timeout=60) as stream:
            data = stream.read()
    else:
        raise ImageResponseError("响应缺少图片数据")
    if (
        len(data) < 45
        or data[:16] != b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
        or data[-12:] != b"\x00\x00\x00\x00IEND\xaeB`\x82"
    ):
        raise ImageResponseError("响应缺少 PNG 文件头或结束标记")
    width, height = struct.unpack(">II", data[16:24])
    if not width or not height:
        raise ImageResponseError("图片尺寸无效")
    return data, width, height


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    output = args.file.expanduser()
    try:
        prompt = args.prompt if args.prompt is not None else args.prompt_file.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        print(f"无法读取提示词文件：{type(error).__name__}", file=sys.stderr)
        return 2
    if not prompt.strip():
        print("提示词不能为空", file=sys.stderr)
        return 2
    if not re.fullmatch(r"[1-9][0-9]*x[1-9][0-9]*", args.size):
        print("尺寸应为正整数宽x高，例如 1536x1024", file=sys.stderr)
        return 2
    if output.suffix.lower() != ".png" or output.exists() or output.is_symlink():
        print("输出必须是尚不存在的 .png 文件", file=sys.stderr)
        return 2
    load_dotenv(Path.cwd() / ".env", override=False)
    missing = [key for key in ("OPENAI_BASE_URL", "OPENAI_API_KEY") if not os.environ.get(key, "").strip()]
    if missing:
        print("缺少工作区配置：" + ", ".join(missing), file=sys.stderr)
        return 2
    claimed = None
    complete = False
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        # 先独占目标，避免并发任务为同一文件重复付费。
        with output.open("xb") as stream:
            claimed = os.fstat(stream.fileno())
            with OpenAI(
                base_url=os.environ["OPENAI_BASE_URL"],
                api_key=os.environ["OPENAI_API_KEY"],
                max_retries=0,
                timeout=300,
            ) as client:
                response = client.images.generate(
                    model=args.model,
                    prompt=prompt.strip(),
                    size=args.size,
                    quality=args.quality,
                    n=1,
                    output_format="png",
                )
            data, width, height = image_bytes(response)
            if (width, height) != tuple(map(int, args.size.split("x"))):
                raise ImageResponseError("返回图片尺寸与请求不一致")
            stream.write(data)
        complete = True
    except APIStatusError as error:
        reason = {
            400: "请求参数不兼容", 401: "鉴权失败", 403: "权限不足",
            404: "端点或模型不存在", 429: "限流或额度不足",
        }.get(error.status_code, "图片服务请求失败")
        print(f"{reason}：HTTP {error.status_code}；未自动重试", file=sys.stderr)
        return 1
    except APIError as error:
        print(f"图片服务调用失败：{type(error).__name__}；未自动重试", file=sys.stderr)
        return 1
    except ImageResponseError as error:
        print(f"图片响应不符合要求：{error}；未自动重试", file=sys.stderr)
        return 1
    except (OSError, ValueError) as error:
        print(f"图片获取或写入失败：{type(error).__name__}；未自动重试", file=sys.stderr)
        return 1
    finally:
        if claimed is not None and not complete:
            try:
                if os.path.samestat(output.lstat(), claimed):
                    output.unlink()
            except FileNotFoundError:
                pass
            except OSError as error:
                print(f"未完成文件清理失败：{type(error).__name__}", file=sys.stderr)
    print(json.dumps({
        "file": str(output.resolve()), "model": args.model,
        "mime": "image/png", "width": width, "height": height, "bytes": len(data),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
