# 第 6 步：项目化基础工程

## 输入

- 运行状态位于 `project:06_bootstrap_foundation`，产品根仍是零提交 `main`。
- `steps/02.json` 引用两份工作区内非空、非符号链接的产品定义文档。
- `steps/04.json` 提供实际适用工程目录和组装证据；第 3 步选型只用于核验该组装事实。
- `steps/05.json` 成功，且 `docs/requirements/项目准备清单.md` 存在并可读取。
- 适用工程内部的 README、manifest、锁文件、配置、代码和测试由 Agent 按当前现场读取，不由 Python 重复建模。

## 行为

在产品项目根新建或恢复 Claude session，首条提示以 `/project-bootstrap` 开始。正文只描述领域输入、范围、输出和约束：向 Agent 传递产品定义、准备清单、实际适用工程以及白名单化组装事实中的 `target`、模板 ID、分支、相对路径和 commit SHA；不传可能带凭据的 `git_url` 或 `origin`，不包含步骤号、PCM 节点或外层编排背景。

Agent 负责有限范围项目化：项目身份、基础配置、README、必要共享视觉基线、模板测试迁移、经引用检查的误导残留，以及适用的真实安装、检查、测试、构建、启动、浏览器检查和基础联调。不得实现业务功能、总体技术方案或工程架构，不得初始化独立 Git 仓库、暂存、提交、建分支、合并或推送。Python 只核验前序交接、根仓零提交 `main`、暂存区为空及适用工程没有提前出现 `.git`。

## 统一决策与恢复

每轮完整真实 Agent 回复都会保存为对话的 `user` 消息，并由步骤专属精简 decision system prompt 产生统一 `AgentDecision`：

- `continue` 的 `answer` 原样恢复同一 session；`blocked` 仅表示不可替代外部资源；其它决策或运行错误为 `failed`。
- `completed` 后仍由程序重验交接、目录和 Git 边界，并核验产品根 README。README 缺失或为空时，追加固定修复提示并在同一 session 继续；边界冲突不会修补或覆盖，直接 `failed`。
- `error_max_turns`、`error_max_budget_usd` 有 session 和非空回复时可进入裁决，但必须在后续正常 `success` 后才可最终完成。400/429/500、连接、CLI/进程、无 `ResultMessage` 和其它 SDK/API 错误为 `failed`；无外层自定义 HTTP 重试。

对话尾部决定恢复动作：`user` 先裁决，`continue` 执行 answer，`completed` 先核验，`blocked` 停止；从 `blocked` 显式重跑才重新核验。状态仅保存 session、对话路径、最后一次 Agent 终止摘要和短暂待写入原文，不再写 `pending_agent_prompt`、决策轮次或 Python 完成声明。旧 `action` 和旧完成 sentinel 仅保持只读兼容。

## 输出与恢复

成功时 `steps/06.json.outputs` 记录第 4 步实际适用工程目录，先写步骤结果，再推进到 `project:07_solution_design`。如果没有适用基础工程，仍核验根 Git 和暂存区后以 `applicable: false` 无副作用跳过；该语义保持不变。

已有成功结果、完成决定或状态推进中断时，先重验工程和 Git 事实再补写或复用成功；完整成功状态不再次调用 Agent 或决策模型。步骤结果格式与 `run_step.py` 的 `success` / `blocked` / `failed` 三态不变。

## 运行

```bash
cd /Users/zhou/resource/fireworks/ANDRSZAN/pcm-agent-skills/pcm-demo
uv run python run_step.py --step 6 --run-id <run-id>
```