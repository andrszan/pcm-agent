# 第 2 步：项目需求与产品定义

在第 1 步发布并初始化为零提交根 Git 仓库的独立产品工作区中，显式调用 `project-intake`，形成两份正式产品定义文档。写入 Claude Code trust 前，会重新核验最终路径、根 Git、`main` 分支、空 `HEAD`、初稿哈希和第 1 步发布证据。

## 输入与提示

只使用：

- `steps/01.json` 引用的 `docs/产品初稿.md`；
- `CLAUDE.md`、`AGENTS.md`、`.claude/settings.json` 和锁定 plugins；
- 当前 `project-intake` session 及该 Skill 生成的产物。

技术方案、Backlog、TRD、代码和其它无关文档不进入当前产品定义判断，也不构成阻塞。首条提示第一行固定为 `/project-intake @./docs/产品初稿.md`；正文只说明产品定义的权威输入、两份目标文档和“不处理后续工程实现”的边界，不包含步骤号、PCM 节点或外层编排语义。

步骤使用默认 Claude Code 用户配置目录，不设置 `CLAUDE_CONFIG_DIR`、`permission_mode`、`tools`、`allowed_tools`、`disallowed_tools` 或 `setting_sources`。项目 `.claude/settings.json` 和 Claude Code 默认加载语义是权限与工具配置的权威来源。

## 统一决策循环

本步骤通过 `common/agent_decision_loop.py` 运行与恢复：每次 Agent 调用先持久化 session、终止摘要和**完整真实回复**，再将回复作为决策历史的 `user` 消息交给 `AgentDecision` 裁决。

- 决定只有 `completed`、`continue`、`blocked`；`continue.answer` 原样恢复同一 session，`blocked` 只表示不可替代的外部资源缺失。
- `completed` 不直接推进步骤。程序重新核验两份目标文档均为非空普通文件；缺失或为空时，向同一 session 追加固定修复提示并继续。路径、交接或核验冲突为 `failed`。
- 正常 `success`、`error_max_turns` 和 `error_max_budget_usd` 只是在进入裁决前的 SDK 终止结果；后两者必须同时具有 session 与非空回复，且后续必须取得正常 `success` 才能最终完成。API 400/429/500、连接或 CLI/进程错误、无 `ResultMessage` 和其它 SDK 错误均为 `failed`，不在外层自定义 HTTP 重试。
- 对话文件的尾部是恢复和调度事实：`user` 尾部先裁决，`continue` 尾部发送其 `answer`，`completed` 尾部先核验，`blocked` 尾部终止；只有显式从 `blocked` 重跑时才在原 session 重新核验。旧 `action` 与旧完成 sentinel 仅只读兼容，旧记录不会转换回写。

## 输出与状态

- `docs/requirements/项目需求说明.md`
- `docs/requirements/产品功能说明.md`
- `state.json` 中的 `claude_sessions.project_intake`
- `runs/<run-id>/conversations/project_intake.json`

恢复所需状态只保留 session、对话文件路径引用、最后一次 Agent 终止摘要和短暂的待写入 Agent 原文；不再写入 `pending_agent_prompt`、决策轮次或 Python 完成声明。`blocked` 仅表示缺少不可替代外部资源；输入、状态、SDK、模型、文件或恢复错误均返回 `failed`。步骤结果格式与 `run_step.py` 的 `success` / `blocked` / `failed` 三态保持不变。

## 运行

```bash
cd /Users/zhou/resource/fireworks/ANDRSZAN/pcm-agent-skills/pcm-demo
uv run python run_step.py --step 2 --run-id <run-id>
```

重复使用同一 run ID 时会恢复历史并重新核验当前文件事实。