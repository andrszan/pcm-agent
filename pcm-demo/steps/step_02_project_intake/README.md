# 第 2 步：项目需求与产品定义

在第 1 步发布并初始化为零提交根 Git 仓库的独立产品工作区中显式调用 `project-intake`，由 AI-compatible 决策模型处理 Agent 的多轮问题和定稿授权。第 2 步在写入 trust 前重新核验最终路径、根 Git、`main` 分支、空 `HEAD`、初稿哈希和第 1 步证据。

## 输入边界

只使用：

- `docs/产品初稿.md`
- `CLAUDE.md`
- `AGENTS.md`
- `.claude/settings.json`
- 当前 `project-intake` 对话和该 Skill 已生成的默认产物

技术方案、Backlog、TRD、代码和其它文档不进入决策上下文，其存在不构成阻塞。

## 权限

第 2 步使用默认 Claude Code 用户配置目录，因此共享本机认证、已安装插件、marketplace、Skill 和 session。步骤不设置 `CLAUDE_CONFIG_DIR`，也不复制默认用户配置。

步骤不传 `permission_mode`、`tools`、`allowed_tools` 或 `disallowed_tools`，也不主动设置 `CLAUDE_CONFIG_DIR` 或 `setting_sources`，使用项目 `.claude/settings.json` 和 Claude Code 默认加载语义。

## 输出

- `docs/requirements/项目需求说明.md`
- `docs/requirements/产品功能说明.md`
- `state.json` 中的 `claude_sessions.project_intake`
- `runs/<run-id>/conversations/project_intake.json`

`blocked` 仅表示缺少不可替代外部资源。输入、状态、SDK、模型、文件或恢复错误返回 `failed`。

## 运行

```bash
uv run python run_step.py --step 2 --run-id <run-id>
```

重复使用同一 run ID 时恢复原 Claude session 和决策历史；当前文件事实仍会重新核验。
