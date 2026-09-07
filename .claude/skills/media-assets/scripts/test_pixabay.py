from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
import urllib.error
import urllib.parse
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

import pixabay


KEY = "test-only-pixabay-key"
PNG = b"\x89PNG\r\n\x1a\n" + b"unit-test-data" * 12
MP4 = b"\x00\x00\x00\x20ftypisom" + b"unit-test-data" * 12


def response(data):
    stream = io.BytesIO(data)
    stream.headers = {"Content-Length": str(len(data))}
    stream.status = 200
    return stream


def hit(media="image"):
    data = {"id": 17, "pageURL": "https://pixabay.com/photos/id-17/", "type": "photo", "tags": "forest, camping", "user": "fixture-author"}
    if media == "image":
        data.update(imageWidth=2000, imageHeight=1200, previewURL="https://cdn.example/preview.png", previewWidth=150, previewHeight=90, webformatURL="https://cdn.example/web.png", webformatWidth=640, webformatHeight=384, largeImageURL="https://cdn.example/large.png")
    else:
        data.update(type="film", pageURL="https://pixabay.com/videos/id-17/", duration=8, videos={"medium": {"url": "https://cdn.example/medium.mp4", "width": 1280, "height": 720, "size": len(MP4), "thumbnail": "https://cdn.example/preview.jpg"}})
    return data


def api_response(media="image"):
    return response(json.dumps({"hits": [hit(media)], "total": 100, "totalHits": 100}).encode())


class PixabayTest(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[4] / ".test-screenshots"
        root.mkdir(exist_ok=True)
        temporary = tempfile.TemporaryDirectory(prefix="pixabay-unit-", dir=root)
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.output = self.root / "asset.png"
        self.stdout, self.stderr = io.StringIO(), io.StringIO()
        for target in (
            patch.dict(os.environ, {"PIXABAY_API_KEY": KEY}, clear=True),
            patch.object(pixabay, "CACHE_DIR", self.root / "cache"),
            patch.object(pixabay, "load_dotenv"),
        ):
            target.start()
            self.addCleanup(target.stop)
        network = patch.object(pixabay.urllib.request, "urlopen")
        self.network = network.start()
        self.addCleanup(network.stop)

    def run_cli(self, *args):
        self.stdout.seek(0)
        self.stdout.truncate()
        with redirect_stdout(self.stdout), redirect_stderr(self.stderr):
            return pixabay.main(list(args))

    def test_search_is_bounded_safe_and_cached(self):
        self.network.return_value = api_response()
        with patch.object(pixabay.time, "time", return_value=1000):
            self.assertEqual(self.run_cli("search", "-q", "camping forest", "--limit", "5"), 0)
            self.assertFalse(json.loads(self.stdout.getvalue())["cached"])
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.network.call_args.args[0].full_url).query)
        self.assertEqual(query["key"], [KEY])
        self.assertEqual(query["safesearch"], ["true"])
        self.assertEqual(query["per_page"], ["5"])
        self.assertNotIn("page", query)
        with patch.object(pixabay.time, "time", return_value=2000):
            self.assertEqual(self.run_cli("search", "-q", "camping forest", "--limit", "5"), 0)
        self.assertTrue(json.loads(self.stdout.getvalue())["cached"])
        self.network.assert_called_once()
        self.assertNotIn(KEY, self.stdout.getvalue())
        cached = next((self.root / "cache").glob("*.json")).read_text()
        self.assertNotIn(KEY, cached)
        self.assertNotIn('"totalHits"', cached)
        self.assertNotIn("large.png", self.stdout.getvalue())

    def test_expired_cache_refreshes(self):
        self.network.side_effect = [api_response(), api_response()]
        for timestamp in (1000, 1000 + pixabay.CACHE_SECONDS):
            with patch.object(pixabay.time, "time", return_value=timestamp):
                self.assertEqual(self.run_cli("search", "-q", "forest"), 0)
        self.assertEqual(self.network.call_count, 2)

    def test_cache_separates_credentials_and_video_endpoint(self):
        self.network.side_effect = [api_response("video"), api_response("video")]
        self.assertEqual(self.run_cli("search", "-q", "forest", "--media", "video"), 0)
        self.assertIn("/api/videos/?", self.network.call_args.args[0].full_url)
        result = json.loads(self.stdout.getvalue())["candidates"][0]
        self.assertEqual(result["variants"]["medium"]["width"], 1280)
        with patch.dict(os.environ, {"PIXABAY_API_KEY": "another-test-key"}):
            self.assertEqual(self.run_cli("search", "-q", "forest", "--media", "video"), 0)
        self.assertEqual(self.network.call_count, 2)

    def test_missing_key_and_invalid_query_do_not_request(self):
        with patch.dict(os.environ, {"PIXABAY_API_KEY": ""}):
            self.assertEqual(self.run_cli("search", "-q", "forest"), 2)
        for args in (("search", "-q", " "), ("search", "-q", "x" * 101), ("search", "-q", "forest", "--limit", "11"), ("download", "--id", "0", "-f", str(self.output))):
            with self.subTest(args=args), self.assertRaises(SystemExit) as error:
                self.run_cli(*args)
            self.assertEqual(error.exception.code, 2)
        self.network.assert_not_called()

    def test_download_image_and_video(self):
        for media, data, extension in (("image", PNG, ".png"), ("video", MP4, ".mp4")):
            with self.subTest(media=media):
                output = self.output.with_suffix(extension)
                self.network.side_effect = [api_response(media), response(data)]
                self.assertEqual(self.run_cli("download", "--media", media, "--id", "17", "-f", str(output)), 0)
                self.assertEqual(output.read_bytes(), data)
                self.assertNotIn(KEY, self.stdout.getvalue())
                self.assertNotIn("cdn.example", self.stdout.getvalue())
                request = self.network.call_args.args[0]
                self.assertEqual(request.get_header("User-agent"), "media-assets/1.0")
                self.assertNotIn(KEY, request.full_url + str(request.headers))

    def test_common_mp4_brands(self):
        for brand in (b"isom", b"iso2", b"iso6", b"dash"):
            with self.subTest(brand=brand):
                self.assertEqual(pixabay.sniff_mime(b"\x00\x00\x00\x20ftyp" + brand + b"\x00" * 20), "video/mp4")

    def test_existing_file_does_not_trigger_request(self):
        self.output.write_bytes(b"existing")
        self.assertEqual(self.run_cli("download", "--id", "17", "-f", str(self.output)), 1)
        self.network.assert_not_called()
        self.assertEqual(self.output.read_bytes(), b"existing")

    def test_bad_download_is_cleaned_up(self):
        for index, data in enumerate((b"<html>not an image</html>", b"\xff\xd8\xffjpeg-with-wrong-extension")):
            with self.subTest(index=index):
                self.network.side_effect = [api_response(), response(data)] if index == 0 else [response(data)]
                self.assertEqual(self.run_cli("download", "--id", "17", "-f", str(self.output)), 1)
                self.assertFalse(self.output.exists())

    def test_short_or_oversized_download_is_rejected(self):
        incomplete = response(PNG)
        incomplete.headers["Content-Length"] = str(len(PNG) + 10)
        self.network.side_effect = [api_response(), incomplete]
        self.assertEqual(self.run_cli("download", "--id", "17", "-f", str(self.output)), 1)
        self.assertFalse(self.output.exists())
        self.network.side_effect = [response(PNG)]
        with patch.object(pixabay, "MAX_DOWNLOAD", 70):
            self.assertEqual(self.run_cli("download", "--id", "17", "-f", str(self.output)), 1)
        self.assertFalse(self.output.exists())

    def test_rate_limit_and_response_errors_do_not_leak_key(self):
        self.network.side_effect = urllib.error.HTTPError("https://pixabay.com/api/?key=" + KEY, 429, "limit " + KEY, {}, None)
        self.assertEqual(self.run_cli("search", "-q", "forest"), 1)
        self.network.assert_called_once()
        self.assertIn("HTTP 429", self.stderr.getvalue())
        self.assertNotIn(KEY, self.stdout.getvalue() + self.stderr.getvalue())

    def test_success_diagnostics_and_cache_do_not_add_requests(self):
        value = api_response()
        value.headers.update({"X-RateLimit-Limit": "100", "X-RateLimit-Remaining": "99", "X-RateLimit-Reset": "60", "Server": "cloudflare", "Set-Cookie": "session=hidden-cookie"})
        self.network.return_value = value
        self.assertEqual(self.run_cli("search", "-q", "forest", "--diagnostics"), 0)
        event = json.loads(self.stderr.getvalue().splitlines()[0])
        self.assertEqual(event["stage"], "api_query")
        self.assertEqual(event["status"], 200)
        self.assertEqual(event["headers"]["X-RateLimit-Remaining"], 99)
        self.assertNotIn("hidden-cookie", self.stderr.getvalue())
        self.stderr.seek(0)
        self.stderr.truncate()
        self.assertEqual(self.run_cli("search", "-q", "forest", "--diagnostics"), 0)
        self.network.assert_called_once()
        event = json.loads(self.stderr.getvalue().splitlines()[0])
        self.assertEqual(event["event"], "pixabay_cache")
        self.assertFalse(event["network_request"])
        self.assertNotIn("headers", event)

    def test_api_429_diagnostics_redact_body_and_headers(self):
        query = "private client"
        body = ("API rate limit exceeded; " + KEY + " https://pixabay.com/api/?key=" + KEY + " q=" + query + " Authorization: Bearer hidden-bearer; token=hidden-token; key=other-key; Basic hidden-basic; 203.0.113.8 2001:db8::1 ::1 admin@example.com").encode()
        headers = {"Content-Type": "text/plain", "X-RateLimit-Limit": "100", "X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "57", "Retry-After": "57", "Set-Cookie": "hidden-cookie"}
        self.network.side_effect = urllib.error.HTTPError("https://pixabay.com/api/?key=" + KEY, 429, "error", headers, io.BytesIO(body))
        self.assertEqual(self.run_cli("search", "-q", query), 1)
        self.network.assert_called_once()
        text = self.stderr.getvalue()
        event = json.loads(text.splitlines()[0])
        self.assertEqual(event["stage"], "api_query")
        self.assertTrue(event["api_rate_limit_message_detected"])
        self.assertEqual(event["headers"]["Retry-After"], 57)
        for secret in (KEY, query, "hidden-bearer", "hidden-token", "hidden-cookie", "other-key", "hidden-basic", "203.0.113.8", "2001:db8::1", "::1", "admin@example.com", "https://pixabay.com/api/"):
            self.assertNotIn(secret, text)

    def test_media_429_html_diagnostics_preserve_code_not_page(self):
        token = "private-signed-file-" + "a" * 40
        url = "https://pixabay.com/get/" + token
        body = ("<html><title>Too many requests</title><body>" + "private-page-data " * 80 + " error code: 1015</body></html>").encode()
        error = urllib.error.HTTPError(url, 429, "error", {"Content-Type": "text/html", "Server": "cloudflare", "Retry-After": "Wed, 09 Sep 2026 00:00:00 GMT"}, io.BytesIO(body))
        self.network.side_effect = [api_response(), error]
        self.assertEqual(self.run_cli("download", "--id", "17", "-f", str(self.output)), 1)
        event = json.loads(self.stderr.getvalue().splitlines()[0])
        self.assertEqual(event["stage"], "media_download")
        self.assertEqual(event["service_error_code"], "1015")
        self.assertFalse(event["api_rate_limit_message_detected"])
        self.assertEqual(event["error_summary"], "服务返回四位错误码")
        self.assertEqual(event["headers"]["Retry-After"], "2026-09-09T00:00:00+00:00")
        self.assertNotIn(token, self.stderr.getvalue())
        self.assertNotIn("private-page-data", self.stderr.getvalue())
        self.assertFalse(self.output.exists())
        self.assertEqual(self.network.call_count, 2)

    def test_diagnostics_do_not_log_changed_or_encoded_user_data(self):
        key, query = "secret+key/with?symbols", "private client"
        value = urllib.parse.quote("https://private.example/api/?key=" + key) + " q=" + urllib.parse.quote_plus(query) + ' {"access_token":"other-hidden-token"} PRIVATE CLIENT private_client PRIVATE\\tCLIENT'
        for body in (value, "<html><title>PRIVATE CLIENT</title><body>" + value + "</body></html>"):
            with self.subTest(body_type=body[:5]):
                self.stderr.seek(0)
                self.stderr.truncate()
                error = urllib.error.HTTPError("https://private.example/api/?key=" + key, 429, "error", {"Server": "PRIVATE CLIENT", "Content-Type": "private/client", "Retry-After": query}, io.BytesIO(body.encode()))
                with redirect_stderr(self.stderr):
                    pixabay.http_diagnostic("api_query", error, error.url, failed=True)
                text = self.stderr.getvalue()
                for secret in (key, query, query.upper(), "private_client", "PRIVATE\\tCLIENT", urllib.parse.quote_plus(query), "other-hidden-token", "https://", "private.example"):
                    self.assertNotIn(secret, text)
                event = json.loads(text)
                self.assertEqual(event["host"], "[configured-host]")
                self.assertEqual(event["headers"]["Server"], "other")
                self.assertEqual(event["headers"]["Content-Type"], "other")
                self.assertNotIn("Retry-After", event["headers"])

    def test_unreadable_error_body_keeps_http_status(self):
        class BrokenBody(io.BytesIO):
            def read(self, *args): raise OSError("hidden-body-detail")
        self.network.side_effect = urllib.error.HTTPError("https://pixabay.com/api/", 429, "error", {}, BrokenBody())
        self.assertEqual(self.run_cli("search", "-q", "forest"), 1)
        event = json.loads(self.stderr.getvalue().splitlines()[0])
        self.assertEqual(event["status"], 429)
        self.assertEqual(event["error_body_read_error"], "OSError")
        self.assertNotIn("hidden-body-detail", self.stderr.getvalue())
        self.network.assert_called_once()

    def test_empty_results_do_not_download_or_expand(self):
        self.network.return_value = response(b'{"hits":[]}')
        self.assertEqual(self.run_cli("search", "-q", "forest"), 0)
        self.assertEqual(json.loads(self.stdout.getvalue())["count"], 0)
        self.network.assert_called_once()

    def test_unsafe_urls_and_missing_variant_fail_closed(self):
        unsafe = hit()
        unsafe["largeImageURL"] = "file:///private/secret"
        self.network.return_value = response(json.dumps({"hits": [unsafe]}).encode())
        self.assertEqual(self.run_cli("download", "--id", "17", "-f", str(self.output)), 1)
        self.network.assert_called_once()
        self.assertFalse(self.output.exists())
        self.network.reset_mock()
        self.network.return_value = api_response("video")
        output = self.output.with_suffix(".mp4")
        self.assertEqual(self.run_cli("download", "--media", "video", "--variant", "large", "--id", "17", "-f", str(output)), 1)
        self.network.assert_called_once()
        self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
