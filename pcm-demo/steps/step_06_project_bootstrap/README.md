# 第 6 步：项目化基础工程

## 输入

- 运行状态位于 `project:06_bootstrap_foundation`，产品根仍是零提交、空 index 的 `main`；每个适用基础工程已经是自身 top-level 为目录本身、unborn HEAD、空 index 的 `main` 独立 Git 仓库，不适用端不存在。
- `steps/02.json` 引用两份工作区内非空、非符号链接的产品定义文档。
- `steps/04.json` 提供实际适用工程目录和组装证据；第 3 步选型只用于核验该组装事实。
- `steps/05.json` 成功，且 `docs/requirements/项目准备清单.md` 存在并可读取。
- 适用工程内部的 README、manifest、锁文件、配置、代码和测试由 Agent 按当前现场读取，不由 Python 重复建模。

## 行为

在产品项目根新建或恢复 Claude session，首条提示以 `/project-bootstrap` 开始。正文只描述领域输入、范围、输出和约束：向 Agent 传递产品定义、准备清单、实际适用工程以及白名单化组装事实中的 `target`、模板 ID、分支、相对路径和 commit SHA；不传可能带凭据的 `git_url` 或 `origin`，不包含步骤号、PCM 节点或外层编排背景。

Agent 负责有限范围项目化：项目身份、基础配置、README、必要共享视觉基线、模板测试迁移、经引用检查的误导残留，以及适用的真实安装、检查、测试、构建、启动、浏览器检查和基础联调。完成前必须删除所属仓未忽略的 `.coverage` 覆盖率数据库，或将这类可再生产物加入所属仓 `.gitignore`；根模板以 `**/.coverage` 覆盖该规则。不得实现业务功能、总体技术方案或工程架构，不得改变现有独立 Git 边界、暂存、提交、建分支、合并或推送。Python 核验前序交接、根仓和适用子仓的 `main` / unborn / 空 index 边界，并在完成核验中复查 `.coverage`。

## 统一决策与恢复

本步骤只维护 bootstrap 的 `DECISION_RULES`。新 conversation 的完整 XML system snapshot 由 `common/decision.py` 渲染，严格包含 `<role>`、`<project_context>`、`<responsibility>`、`<require>` 四段：AI-compatible 角色是实际使用 Claude Code Agent 的项目负责人、工程负责人、专业开发者和 Agent 专家；`assistant` 是其此前发给 Agent 的指令或结构化回复，`user` 是 Agent 返回的完整执行结果。项目上下文仅包括两份产品定义原文、项目准备清单原文、适用工程和组装白名单投影。恢复严格使用历史 `messages[0]`，不重渲染或覆盖。

项目上下文只做标准 XML 转义。

每轮完整真实 Agent 回复都会保存为对话的 `user` 消息；完整 XML system prompt 原样传给一次 `responses.parse`，以 Pydantic `AgentDecision` 取得统一结构化结果：

- `continue` 的 `answer` 原样恢复同一 session；`blocked` 仅表示不可替代外部资源；其它决策或运行错误为 `failed`。
- `completed` 表示负责人根据 Agent 执行结果相信任务完成；程序随后重验交接、目录、根仓及适用子仓的 Git 边界（各自 top-level、`main`、unborn HEAD、空 index）、`.coverage` 处理和产品根 README。README 或 `.coverage` 可安全补完时，追加固定修复提示并在同一 session 继续；边界冲突不会修补或覆盖，直接 `failed`。
- 写入 `blocked` 终止前同样重验 Git 边界和 `.coverage`；`error_max_turns`、`error_max_budget_usd` 有 session 和非空回复时可进入裁决，但必须在后续正常 `success` 后才可最终完成。400/429/500、连接、CLI/进程、无 `ResultMessage` 和其它 SDK/API 错误为 `failed`；无外层自定义 HTTP 重试。

对话尾部决定恢复动作：`user` 先裁决，`continue` 执行 answer，`completed` 先核验，`blocked` 停止；从 `blocked` 显式重跑才重新核验。状态仅保存 session、对话路径、最后一次 Agent 终止摘要和短暂待写入原文，不再写 `pending_agent_prompt`、决策轮次或 Python 完成声明。旧 `action` 和旧完成 sentinel 仅保持只读兼容。

## 输出与恢复

成功时 `steps/06.json.outputs` 记录第 4 步实际适用工程目录，先写步骤结果，再推进到 `project:07_solution_design`。如果没有适用基础工程，仍核验根 Git 和暂存区后以 `applicable: false` 无副作用跳过；该语义保持不变。

只有 `status=success` 的既有结果、完成决定或状态推进中断可在重新核验工程、`.coverage` 和 Git 事实后补写或复用成功；`failed` / `blocked` 结果不被当作成功，也不阻止原 session 恢复。完整成功状态不再次调用 Agent 或决策模型。步骤结果格式与 `run_step.py` 的 `success` / `blocked` / `failed` 三态不变。

## 运行

```bash
cd /Users/zhou/resource/fireworks/ANDRSZAN/pcm-agent-skills/pcm-demo
uv run python run_step.py --step 6 --run-id <run-id>
```