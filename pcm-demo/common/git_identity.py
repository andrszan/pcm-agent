from __future__ import annotations

import unicodedata


def _has_forbidden_character(value: str) -> bool:
    return any(
        character in "<>" or unicodedata.category(character) == "Cc"
        for character in value
    )


def parse_git_identity(
    name: str | None, email: str | None
) -> dict[str, str] | None:
    """校验并保留 Git 提交身份；未提供身份时返回 None。"""
    if name is None and email is None:
        return None
    if name is None or email is None:
        raise ValueError("--git-user-name 与 --git-user-email 必须成对提供")
    if not isinstance(name, str) or not isinstance(email, str):
        raise ValueError("Git 提交身份必须是字符串")
    if not name.strip():
        raise ValueError("--git-user-name 不能为空白")
    if name != name.strip():
        raise ValueError("--git-user-name 不能包含首尾空白")
    if _has_forbidden_character(name):
        raise ValueError("--git-user-name 不能包含控制字符或尖括号")
    if not email or any(character.isspace() for character in email):
        raise ValueError("--git-user-email 不能为空且不能包含空白")
    if _has_forbidden_character(email):
        raise ValueError("--git-user-email 不能包含控制字符或尖括号")
    if email.count("@") != 1:
        raise ValueError("--git-user-email 必须包含一个 @")
    local, domain = email.split("@", 1)
    if not local or not domain:
        raise ValueError("--git-user-email 的 @ 前后都必须有内容")
    return {"name": name, "email": email}
