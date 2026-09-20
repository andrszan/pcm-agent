from __future__ import annotations

import unittest

from common.git_identity import parse_git_identity


class GitIdentityTests(unittest.TestCase):
    def test_absent_identity_returns_none(self) -> None:
        self.assertIsNone(parse_git_identity(None, None))

    def test_valid_identity_preserves_chinese_name_and_spaces(self) -> None:
        self.assertEqual(
            parse_git_identity("张 三", "zhang.san@example.com"),
            {"name": "张 三", "email": "zhang.san@example.com"},
        )

    def test_identity_arguments_must_be_paired(self) -> None:
        for name, email in (("PCM", None), (None, "pcm@example.com")):
            with self.subTest(name=name, email=email), self.assertRaisesRegex(
                ValueError, "成对"
            ):
                parse_git_identity(name, email)

    def test_blank_or_git_altered_names_are_rejected(self) -> None:
        for name in ("", " \t", " PCM", "PCM ", "P<CM", "P>CM", "P\nCM", "P\x00CM"):
            with self.subTest(name=repr(name)), self.assertRaises(ValueError):
                parse_git_identity(name, "pcm@example.com")

    def test_invalid_emails_are_rejected(self) -> None:
        for email in (
            "",
            "pcm example.com",
            "pcm.example.com",
            "@example.com",
            "pcm@",
            "pcm@@example.com",
            "pcm<user>@example.com",
            "pcm\n@example.com",
        ):
            with self.subTest(email=repr(email)), self.assertRaises(ValueError):
                parse_git_identity("PCM", email)


if __name__ == "__main__":
    unittest.main()
