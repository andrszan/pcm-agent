# 第 7 步：总体技术方案

## 输入

- 运行状态位于 `project:07_solution_design`，产品根仍是第 1 步初始化的零提交、空 index 独立 Git `main` 仓库；每个适用基础工程已在第 4 步建立自身 top-level 为目录本身、unborn HEAD、空 index 的 `main` Git 边界，不适用端不存在。
- `steps/02.json` 引用两份工作区内非空、非符号链接的产品定义文档。
- `steps/04.json` 提供实际适用工程、模板 ID、路径、分支、commit SHA 和组装证据；用于提示的白名单投影不含 `git_url` 或 `origin`。Agent 另接收 `steps/03.json` 中各适用端已保存的选型理由，作为承接既有选择的依据，不重做模板选型或补写历史比较。
- `steps/05.json` 是严格成功结果，当前项目准备清单和两份产品定义与其无秘密 `readiness_baseline` 指纹一致。
- `steps/06.json` 成功，其 `outputs` 与第 4 步实际适用工程一致，且专属布尔 `tailwind_theme` 严格等于 outputs 是否含 `frontend`；字段缺失、非布尔或不一致的旧成功不可复用。

适用工程内部的 README、manifest、锁文件、配置、代码和测试由 Agent 为支撑方案主张按需读取；本步骤不要求或假定全仓扫描。

## 行为

在产品项目根新建或恢复 Claude session，首条提示第一行固定为 `/solution-design`。正文只描述授权范围、权威产品定义、准备清单、实际工程、白名单组装事实、产物和约束，不包含步骤号、PCM 节点或外层编排语义。步骤只传稳定任务标识 `solution_design`，实际 model 与 effort 由 `model-policy.toml` 解析并按本次进程启动时加载的策略固定。

Agent 创建或更新唯一固定产物 `docs/design/技术方案.md`，并区分当前工程事实、已确认决定、目标状态、假设和待确认事项；说明系统边界、交付单元、数据所有权、依赖方向、跨单元协作、主要技术取舍、风险和恢复语义。不得重新选择或组装模板，不得实施业务功能、修改业务代码、工程配置、迁移或基础设施，也不得执行 Git 写操作或改变现有 Git 边界。风险、假设和正常的未来待决事项可以保留，不因此阻塞完成。

完整 Agent 回复、待裁决文本和新 run 的决策输入均按原文保存在 Git 忽略的 run 目录；不再对第 7 步回复做脱敏替换。Agent 仍必须遵守项目规则，不得主动披露秘密、完整 `.env` 或无关认证信息。

## 统一决策与恢复

本步骤只维护 solution-design 的 `DECISION_RULES`。新 conversation 的完整 XML system snapshot 由 `common/decision.py` 渲染，严格包含 `<role>`、`<project_context>`、`<responsibility>`、`<completion>`、`<output>` 五段：AI-compatible 角色是实际使用 Claude Code Agent 的项目负责人、工程负责人、专业开发者和 Agent 专家；`assistant` 是其此前发给 Agent 的指令或结构化回复，`user` 是 Agent 返回的完整执行结果。项目上下文仅包括两份产品定义原文、项目准备清单原文、适用工程和组装白名单投影。恢复严格使用历史 `messages[0]`，不重渲染或覆盖。

项目上下文只做标准 XML 转义。

完整真实 Agent 回复先保存为对话 `user` 消息；完整 XML system prompt 原样传给一次 `responses.parse`，以 Pydantic `AgentDecision` 取得统一结构化结果：

- `continue` 的 `answer` 原样恢复同一 session；`blocked` 只用于当前环境无法取得的不可替代外部资源。
- `completed` 表示负责人根据 Agent 执行结果相信任务完成；程序随后重验前序交接、session/cwd/Skill 边界、产品根和适用子仓的 Git 边界（各自 top-level、`main`、unborn HEAD、空 index），并确认固定方案文件为非空普通文件。文档缺失或为空时，会追加固定文档修复提示并继续同一 session；交接或 Git 边界冲突为 `failed`。
- `blocked` 终止前也复核上述 Git 边界；`error_max_turns` 与 `error_max_budget_usd` 在拥有 session 和非空回复时可裁决，但必须恢复一次正常 `success` 才能最终完成。400/429/500、连接、CLI/进程、无 `ResultMessage`、`terminal_reason` 为 `aborted_streaming` 或 `aborted_tools`，以及 `success` 下未知终止原因均在裁决前为 `failed`；其它 SDK/API 错误同样失败，不使用外层自定义 HTTP 重试。

`conversations/solution_design.json` 的尾部是调度真相：`user` 尾部先裁决，`continue` 尾部执行 answer，`completed` 尾部先核验，`blocked` 尾部停止；显式从 `blocked` 重跑才重新核验。状态只保留 session、对话路径、最后一次 Agent 终止摘要和短暂待写入原文；不再写 `pending_agent_prompt`、决策轮次或 Python 完成声明。旧 `action` 与旧完成 sentinel 只读兼容，旧记录不会转换回写；旧 `action` 非 `blocked` 时映射为 `continue`，若其 `answer` 为空则使用固定安全兼容 continue 提示，绝不将旧控制 JSON 发给 Agent。

## 输出与恢复

成功时：

- `steps/07.json.outputs` 固定为 `docs/design/技术方案.md`；
- 保存 `claude_sessions.solution_design`；
- 保存完整的 `conversations/solution_design.json`；
- 先写步骤结果，再将状态推进到 `project:08_initialize_repositories`。

即使没有适用基础工程，仍需生成总体技术方案，不无副作用跳过。只有 `status=success` 的既有结果、完成决定或状态推进中断可在重新核验文档、交接和 Git 边界后补写或复用成功；`failed` / `blocked` 结果不视为成功，也不阻止原 session 恢复。完整成功状态不再次调用 Agent 或决策模型。步骤结果和 `run_step.py` 三态保持不变。

## 隔离真实验证

新 run `agent-loop-step7-20260822T190149Z` 在外部复制工作区执行，未修改既有 `step01-mendmark`。新 `solution_design` session `e8000375-2698-4ccf-9927-ccb9ca627ca2` 的 init 已确认产品根 cwd、`solution-design` Skill、slash command 和 Fable 模型。

首次调用因 Agent 尝试内置 Explore 子代理而遇到环境内部未识别模型并超时，未产生 `ResultMessage`；公共循环按错误边界保留 session 与初始 conversation，未推进步骤。随后仅在隔离 run 的历史中追加“不使用子代理、直接使用工具完成”的普通 assistant 提示，并从同一 session 恢复。该提示不在生产初始 prompt 中，也不表示公共循环缺陷。

恢复后 Agent 正常 `success`（44 turns，约 `$3.800742`），生成约 44 KB 的技术方案。AI-compatible 决策对同一真实回复首次返回 YAML 风格结构；旧合同随后进行格式重试并返回 `completed`。测试包装器随后只对隔离副本将技术方案置空，验证程序返回固定 `DESIGN_REPAIR_PROMPT`：公共循环保留首次真实 `completed` JSON、追加普通 assistant repair 提示并恢复同一已保存 session；Agent 补回非空文档，第二次真实决策再次为 `completed`。

最终 `steps/07.json` 为 `success`，状态推进到 `project:08_initialize_repositories`，对话尾部为 `completed`，无旧 completion sentinel 或 `pending_agent_prompt`。文档置空 failpoint 仅用于本次 repair 验证，不在生产代码中。

Probe C 的格式重试和 `probe-c-20260822T200038Z` 结果均保留为旧合同历史。现行公共决策层要求步骤显式传入完整 XML system prompt，并原样调用一次 `responses.parse`，以 Pydantic `AgentDecision` 取得结构化输出；没有公共默认或隐藏追加 prompt，也没有格式重试。现行 XML prompt 已以真实 `solution_design` Agent 对话完成一次交接事实回放并返回 `completed`；Probe C 尚未按新合同单独重跑，服务重复稳定性仍待验证。

## 运行

```bash
cd /Users/zhou/resource/fireworks/ANDRSZAN/pcm-agent-skills/pcm-demo
uv run python run_step.py --step 7 --run-id <run-id>
```