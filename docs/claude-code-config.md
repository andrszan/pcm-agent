# Claude Code `/config` 配置速查

> 适用于 Claude Code 2.1.220。预览功能和可选值可能随版本、账户及组织策略变化。

## 会话与模型

- **Auto-compact**：接近上下文上限时自动总结旧对话。
- **Switch models when a message is flagged**：消息被实时防护标记时，允许切换到其他受支持模型继续处理。
- **Thinking mode**：允许支持的模型使用自适应思考。
- **Prompt suggestions**：回答后显示下一步提示建议。
- **Session recap**：离开会话后返回时显示进展摘要。
- **Model**：设置默认 Claude 模型。

## 代码与工作流

- **Rewind code (checkpoints)**：保存 Claude 文件编辑前的快照，供 `/rewind` 恢复；不替代 Git。
- **Dynamic workflows**：允许通过工作流编排多个子代理。
- **Ultracode keyword trigger**：提示中出现 `ultracode` 时允许触发动态工作流。
- **Dynamic workflow size**：设置工作流的建议规模；不是硬性 Agent 或费用上限。
- **Open agents view by default**：启动时默认打开 Agents 视图。
- **← opens agents**：左方向键打开 Agents 视图。

## 权限与 Git

- **Default permission mode**：设置新会话的默认工具权限模式。
- **Use auto mode during plan**：Plan 阶段使用 Auto 权限处理方式。
- **Worktree base ref**：
  - `fresh`：从远程默认分支创建 worktree。
  - `head`：从当前本地 `HEAD` 创建 worktree。
- **Respect `.gitignore` in file picker**：文件选择器隐藏 Git 忽略文件。
- **Show PR status footer**：底部显示当前 Pull Request 状态。
- **Diff tool**：自动或强制在终端中显示 diff。

## 终端与显示

- **Show tips**：等待时显示使用技巧。
- **Reduce motion**：减少动画效果。
- **Verbose output**：显示完整工具输出。
- **Terminal progress bar**：向支持的终端发送进度状态。
- **Show turn duration**：显示每轮耗时。
- **Auto-scroll**：自动滚动到最新输出。
- **Theme**：设置终端主题。
- **Output style**：设置 Claude 的回答风格。
- **Language**：设置 Claude 的默认回答语言。
- **Editor mode**：选择普通或 Vim 输入模式。

## 复制与编辑

- **Skip the `/copy` picker**：执行 `/copy` 时直接复制完整回答。
- **Copy on select**：选中文字时自动复制。
- **Show last response in external editor**：外部编辑器中包含上一条 Claude 回答。
- **Question auto-continue timeout**：问题等待多久后自动使用已选答案继续；`never` 表示始终等待。

## 更新与集成

- **Auto-update channel**：选择更新通道或禁用自动更新。
- **Local notifications**：选择桌面或终端通知方式。
- **Auto-install IDE extension**：在支持的 IDE 中自动安装 Claude Code 扩展。
- **Claude in Chrome enabled by default**：新会话默认启用或禁用 Chrome 集成。

## 安全建议

`Bypass Permissions` 会跳过大部分工具确认，只应在可信、隔离的环境中使用。

动态工作流可能并行启动多个 Agent；`Dynamic workflow size` 是规模建议，不是费用上限。

Checkpoints 只保护 Claude 管理的文件编辑，不能替代 Git，也不能撤销任意 Bash、数据库或外部 API 副作用。

## 官方资料

- [Claude Code Settings](https://code.claude.com/docs/en/settings)
- [Claude Code Interactive Mode](https://code.claude.com/docs/en/interactive-mode)
- [Claude Code Permissions](https://code.claude.com/docs/en/permissions)
- [Claude Code Worktrees](https://code.claude.com/docs/en/worktrees)
- [Claude Code IDE Integrations](https://code.claude.com/docs/en/ide-integrations)
- [Claude Code Chrome Integration](https://code.claude.com/docs/en/chrome)
- [Claude 实时安全防护说明](https://support.claude.com/en/articles/14604842-real-time-cyber-safeguards-on-claude)
