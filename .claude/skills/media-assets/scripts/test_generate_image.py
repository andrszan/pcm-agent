from __future__ import annotations

import base64
import io
import json
import os
import struct
import tempfile
import unittest
import zlib
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from openai import APIStatusError

import generate_image


def png(width=1024, height=1024):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress((b"\x00" + b"\x80" * width * 3) * height))
        + chunk(b"IEND", b"")
    )


class GenerateImageTest(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[4] / ".test-screenshots"
        root.mkdir(exist_ok=True)
        self.directory = tempfile.TemporaryDirectory(prefix="image-unit-", dir=root)
        self.addCleanup(self.directory.cleanup)
        self.output = Path(self.directory.name) / "out.png"
        self.stdout, self.stderr = io.StringIO(), io.StringIO()
        env = patch.dict(os.environ, {"OPENAI_BASE_URL": "https://image.example/v1", "OPENAI_API_KEY": "test-only-secret"}, clear=True)
        env.start()
        self.addCleanup(env.stop)
        dotenv = patch.object(generate_image, "load_dotenv")
        self.load_env = dotenv.start()
        self.addCleanup(dotenv.stop)
        factory = patch.object(generate_image, "OpenAI")
        self.factory = factory.start()
        self.addCleanup(factory.stop)
        self.client = self.factory.return_value.__enter__.return_value
        self.raw = png()
        self.client.images.generate.return_value = SimpleNamespace(data=[SimpleNamespace(b64_json=base64.b64encode(self.raw).decode(), url=None)])

    def run_cli(self, *args, prompt=True):
        argv = (["-p", "右侧帐篷，左侧留白，无文字"] if prompt else []) + ["-f", str(self.output), *args]
        with redirect_stdout(self.stdout), redirect_stderr(self.stderr):
            return generate_image.main(argv)

    def test_single_png_and_defaults(self):
        self.assertEqual(self.run_cli(), 0)
        self.assertEqual(self.output.read_bytes(), self.raw)
        self.assertEqual(self.factory.call_args.kwargs["max_retries"], 0)
        params = self.client.images.generate.call_args.kwargs
        self.assertEqual((params["model"], params["size"], params["quality"], params["n"], params["output_format"]), ("gpt-image-2", "1024x1024", "medium", 1, "png"))
        self.client.images.generate.assert_called_once()
        self.load_env.assert_called_once_with(Path.cwd() / ".env", override=False)
        self.assertEqual(json.loads(self.stdout.getvalue())["width"], 1024)
        self.assertNotIn("test-only-secret", self.stdout.getvalue() + self.stderr.getvalue())

    def test_prompt_file_and_explicit_parameters(self):
        prompt = self.output.with_suffix(".txt")
        prompt.write_text("自然晨光，帐篷完整入画")
        self.assertEqual(self.run_cli("--prompt-file", str(prompt), "--quality", "high", "--model", "configured-image-model", prompt=False), 0)
        params = self.client.images.generate.call_args.kwargs
        self.assertEqual(params["prompt"], prompt.read_text())
        self.assertEqual(params["quality"], "high")
        self.assertEqual(params["model"], "configured-image-model")

    def test_preflight_failure_never_calls_api(self):
        for key in ("OPENAI_BASE_URL", "OPENAI_API_KEY"):
            with self.subTest(key=key), patch.dict(os.environ, {key: ""}):
                self.assertEqual(self.run_cli(), 2)
        self.assertEqual(self.run_cli("-p", " "), 2)
        self.assertEqual(self.run_cli("--size", "landscape"), 2)
        self.assertEqual(self.run_cli("--prompt-file", str(self.output.with_suffix(".missing")), prompt=False), 2)
        self.factory.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_existing_output_is_not_overwritten(self):
        self.output.write_bytes(b"existing")
        self.assertEqual(self.run_cli(), 2)
        self.factory.assert_not_called()
        self.assertEqual(self.output.read_bytes(), b"existing")

    def test_response_shape_png_and_size_failures(self):
        invalid = [[], [SimpleNamespace(b64_json=None, url=None)], [SimpleNamespace(b64_json=base64.b64encode(b"not png").decode(), url=None)], [SimpleNamespace(b64_json=base64.b64encode(png(1, 1)).decode(), url=None)]]
        for data in invalid:
            with self.subTest(data_length=len(data)):
                self.client.images.generate.return_value = SimpleNamespace(data=data)
                self.assertEqual(self.run_cli(), 1)
                self.assertFalse(self.output.exists())

    def test_http_url_download_and_non_http_rejected(self):
        self.client.images.generate.return_value = SimpleNamespace(data=[SimpleNamespace(b64_json=None, url="https://image.example/result.png")])
        with patch.object(generate_image.urllib.request, "urlopen", return_value=io.BytesIO(self.raw)) as download:
            self.assertEqual(self.run_cli(), 0)
            download.assert_called_once_with("https://image.example/result.png", timeout=60)
        self.output.unlink()
        self.client.images.generate.return_value.data[0].url = "file:///private/secret.png"
        with patch.object(generate_image.urllib.request, "urlopen") as download:
            self.assertEqual(self.run_cli(), 1)
            download.assert_not_called()

    def test_same_target_in_flight_does_not_call_api_again(self):
        response = self.client.images.generate.return_value
        def generate(**kwargs):
            self.assertTrue(self.output.exists())
            self.assertEqual(self.run_cli(), 2)
            return response
        self.client.images.generate.side_effect = generate
        self.assertEqual(self.run_cli(), 0)
        self.client.images.generate.assert_called_once()
        self.assertEqual(self.output.read_bytes(), self.raw)

    def test_failed_write_removes_own_partial_file(self):
        original_open = Path.open
        class FailedWrite:
            def __init__(self, stream): self.stream = stream
            def __enter__(self): return self
            def __exit__(self, *args): self.stream.close()
            def fileno(self): return self.stream.fileno()
            def write(self, data):
                self.stream.write(data[:16])
                raise OSError("simulated disk error")
        def open_file(path, mode="r", *args, **kwargs):
            stream = original_open(path, mode, *args, **kwargs)
            return FailedWrite(stream) if mode == "xb" else stream
        with patch.object(Path, "open", open_file):
            self.assertEqual(self.run_cli(), 1)
        self.assertFalse(self.output.exists())

    def test_api_error_is_redacted_without_retry(self):
        request = httpx.Request("POST", "https://image.example/v1/images/generations")
        self.client.images.generate.side_effect = APIStatusError("bad test-only-secret", response=httpx.Response(401, request=request), body={"api_key": "test-only-secret"})
        self.assertEqual(self.run_cli(), 1)
        self.client.images.generate.assert_called_once()
        self.assertIn("HTTP 401", self.stderr.getvalue())
        self.assertNotIn("test-only-secret", self.stderr.getvalue())
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
