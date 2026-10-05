import os


def git_environment() -> dict[str, str]:
    """隔离仓库、索引与命令级配置重定向，保留实际提交身份及用户配置来源。"""
    preserved = {
        "GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_AUTHOR_DATE",
        "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL", "GIT_COMMITTER_DATE",
        "GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM", "GIT_CONFIG_NOSYSTEM",
    }
    return {
        key: value for key, value in os.environ.items()
        if not key.startswith("GIT_") or key in preserved
    }
