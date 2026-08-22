# PCM Demo 通用 Agent 决策对话框架设计议题（旧稿废弃，精简合同）

> 本文替代此前的“大型 Hook / 基类 / 多阶段迁移”草案。旧稿不再是实现依据；当前唯一合同以 `common/agent_decision_loop.py`、第 2/5/6/7 步代码和自动化测试为准。
>
> 本次重构已完成代码、自动化验证和第 7 步的真实新 session 验证。隔离 run `agent-loop-step7-20260822T190149Z` 在外部复制工作区完成，不修改既有 `step01-mendmark`；它证明公共循环可在同一 `solution_design` session 中处理无 Result 的环境错误、正常结果、结构化决定、完成核验修复和最终状态推进。此前第 0～7 步的真实运行仍是业务步骤已推进至第 8 步的历史事实；本次新增证据只覆盖重构后公共循环的第 7 步路径。

## 1. 问题与边界

第 2、5、6、7 步都需要同一类可靠交互：在产品工作区调用领域 Skill，取得 Agent 的完整回复，交由 AI-compatible 模型作结构化裁决，再按决定恢复同一 Agent session。旧实现分别维护历史、待发送 prompt、决策轮次和完成标记，导致恢复语义、错误归类和敏感信息处理分叉。

本次只抽取这段已经重复的薄循环，不建设工作流引擎。步骤仍自行负责：

- 读取和重新核验上游输入、产品工作区和 Git 事实；
- 生成领域初始提示、定义专属 decision system prompt；
- 定义完成后的程序化核验和可安全补完的固定修复提示；
- 生成本步骤结果、推进下一节点、包装既有 `blocked` 异常。

公共循环不认识 `project-intake`、`project-readiness`、`project-bootstrap` 或 `solution-design`，不读取领域文件，不决定下一 PCM 节点，也不替步骤做领域验证。不要恢复大型 hooks、抽象基类、DSL、命令重放器、并发锁或“万能状态机”。

## 2. 统一循环

每个接入步骤提供一个小而不可变的 `AgentDecisionLoopSpec`：稳定键、状态键、所需 Skill、单次 Agent 上限、决策上限、该领域 decision system prompt，以及仅用于读取历史的完成 sentinel。公共循环执行：

```text
发送初始指令或恢复指令给同一 Agent session
→ 立即保存 session、终止摘要和完整真实回复
→ 以回复作为 user 消息请求 AgentDecision
→ completed / continue / blocked 分流
→ completed 后由步骤程序重新核验
→ 成功、继续、阻塞或失败
```

每一轮 Agent **完整真实回复**都会先落盘，后进入统一 Pydantic `AgentDecision`：

```text
verdict: completed | continue | blocked
answer: string
reason: string
required_inputs: string[]
```

`continue` 必须携带非空 `answer`，并在循环内部原样发给同一 session；`completed` 的 `answer` 和 `required_inputs` 必须为空；`blocked` 的 `answer` 必须为空且必须列出解除条件。产品、技术、文档或执行取舍本身不是阻塞理由；只有当前环境无法取得的真实外部账号、凭据、私有数据、授权、专用设备、素材、付费服务或线下动作才可以 `blocked`。

## 3. 以对话尾部恢复和调度

`runs/<run-id>/conversations/<key>.json` 是调度真相，而不是 state 中的轮次计数。消息角色固定：`system` 为步骤专属决策约束，`assistant` 为发往 Agent 的初始/继续/修复指令或结构化决定，`user` 为 Agent 完整真实回复。

| 对话尾部 | 恢复动作 |
| --- | --- |
| `system` | 追加初始 Agent 指令并调用 Agent。 |
| 非结构化 `assistant` | 作为已保存的初始或修复指令调用 Agent。 |
| `user` | 请求一次结构化 `AgentDecision`，不重复调用 Agent。 |
| `assistant` 的 `continue` | 将 `answer` 原样发送给原 session。 |
| `assistant` 的 `completed` | 先执行步骤完成核验。 |
| `assistant` 的 `blocked` | 正常运行终止为 blocked；只有 state 已标记 blocked 的显式重跑，才向原 session 发送固定重新核验提示。 |

`pending_agent_text` 只处理“SDK 回复已持久化、对话尚未来得及写入”的短暂中断。恢复时将该完整文本补为 `user` 消息，再走裁决；不会再次调用 Agent。每次请求决策前都按历史实际可解析的决定数检查上限，达到上限不会额外调用 Agent 或决策模型。

## 4. 完成核验的三分支

Agent 或决策模型不能单独宣布步骤成功。接到 `completed` 后，公共循环调用步骤提供的同步或异步完成核验：

1. **通过**：返回 `completed` 给步骤，步骤写既有格式的 `success` 结果并推进状态；
2. **可安全补完**：核验返回固定普通修复提示。公共循环保留 `completed` 决定，追加该提示并在同一 session 继续，直到新的决定与核验通过；
3. **冲突或核验错误**：路径、文件类型、上游交接、Git 边界或核验执行错误直接 `failed`，保留现场，不猜测修复。

第 2 步核验两份非空正式产品定义；第 5 步核验非空准备清单；第 6 步核验根 README 以及工程/Git 边界；第 7 步核验固定方案文档、前序交接和 Git 边界。第 6 步“没有适用基础工程”的无副作用 `applicable: false` 跳过保留在步骤内，未改变其原有语义。

## 5. 错误、阻塞与 SDK 结果

普通 `success` 只表示 Agent loop 正常结束，随后仍必须裁决并完成程序核验。`error_max_turns` 与 `error_max_budget_usd` 只有同时拥有已保存 session 和非空回复时才可进入裁决；即使裁决为 `completed`，也必须恢复同一 session 并取得后续正常 `success`，才能最终完成。

API 400/429/500、连接错误、Claude CLI 或子进程错误、没有 `ResultMessage`、缺少完整回复、session/cwd/Skill/slash command 不一致，以及其它 SDK 错误都为 `failed`。`terminal_reason` 为 `aborted_streaming` 或 `aborted_tools`，以及 `success` 下未知终止原因同样在请求决策前失败。公共循环不添加外层自定义 HTTP 重试；`common/decision.py` 在首次请求和唯一格式校正重试均附加严格 JSON、首尾花括号、双引号、禁止 YAML 约束，步骤 system prompt 只保留领域条件。持续格式或完成状态失败仍按合同返回 `failed`。所有异常只写安全分类，不将异常正文、密钥或环境变量写入状态。

## 6. Prompt 与敏感信息原则

四个步骤分别拥有精简、领域专属的 decision system prompt。Agent 初始提示第一行必须保留实际 slash command；正文只写领域功能、权威输入、输出和约束，不能写步骤编号、PCM 节点、阶段、循环或 Skill 调度背景。

第 5 步只向提示传递最小选型投影，不含 `git_url`/`origin`。第 6、7 步使用白名单化组装事实，不含这两个字段。第 7 步不要求全仓扫描，而是让 Agent 按支持方案主张所需读取实际工程事实。

新 run 的 Agent 回复、`pending_agent_text` 和决策输入均保留完整原文，尤其第 7 步不再做回复脱敏替换；run 目录受 Git 忽略保护。该存储选择不改变 Agent 的行为约束：不得主动在回复中披露秘密、完整 `.env`、认证头或无关私密数据。对外日志、步骤错误与用户输出继续采用安全分类或脱敏信息。

## 7. 最小状态与兼容

恢复所需的核心 state 只有：`claude_sessions.<key>`、`decision_conversations.<key>.path`、步骤键下的 `last_agent_result` 和短暂 `pending_agent_text`。完整对话保存在引用的 JSON 文件中；不再新写 `pending_agent_prompt`、`decision_turn` 或 Python `COMPLETION_MESSAGE`。历史尾部替代了这些重复状态。

为不破坏既有 run：旧 `action: blocked` 读取时映射为 `blocked`，旧 `action: answer|approve|continue` 映射为 `continue`；非 blocked 旧记录若 `answer` 为空，使用固定安全兼容 continue 提示，绝不将旧控制 JSON 发给 Agent。旧完成 sentinel 仅可被读取后核验。旧对话保留原消息，不转换或覆盖为新结构；陈旧 `pending_agent_prompt` 只会被丢弃，绝不会重新发送。

## 8. 验收与真实验证

已通过的自动化验收包括：公共循环 23 项；第 2、5、6、7 步分别 6、8、5、5 项；从 `pcm-demo/` 根目录发现 `common/` 与 `steps/` 的全量 `unittest` 共 83 项。覆盖完整原文持久化、裁决循环、完成修复、blocked 显式恢复、旧记录兼容、上限、SDK 终止分类、终止原因守卫和安全错误状态。Probe C 的早期成功证据 `probe-c-20260822T185623Z` 已以真实 AI-compatible 服务取得普通 `continue`（attempts=2）、外部支付 `blocked`（attempts=1）与 Pydantic 解析；后续最终验证连续两次依合同 `failed`：唯一重试后仍带“验证：”前缀的非 JSON `ValidationError`，以及 ordinary 成功后 boundary Responses `status=incomplete`。没有第三次重试或手写解析。现行公共格式约束同时覆盖首次与唯一重试；真实复跑 `probe-c-20260822T200038Z` 取得 ordinary `continue`、boundary `blocked`（均 attempts=1）。能力可用，但单次复验不消除重复稳定性观察缺口。

重构后的第 7 步真实验证使用隔离 run `agent-loop-step7-20260822T190149Z` 和 session `e8000375-2698-4ccf-9927-ccb9ca627ca2`。init 核验 cwd、`solution-design` Skill、slash command 与 Fable 模型。首次 Agent 调用在请求内置 Explore 子代理时遭遇环境内部未识别模型并超时，未产生 ResultMessage；循环正确保存 session 和初始对话、未推进成功。仅为隔离测试在历史追加普通 assistant 的“不使用子代理、直接工具完成”提示后，同一 session 正常 `success`（44 turns、约 `$3.800742`）并生成约 44 KB 文档。

同一真实回复的首个决策输出为 YAML 风格，当时触发 `request_decision` 的唯一格式重试；提示要求花括号、双引号并禁止 YAML，第二次返回严格 JSON `completed`。当前该格式约束已同时附加到首次请求和唯一重试，步骤 system prompt 仍只描述领域条件。测试包装器只在隔离副本于首次 completed 后将方案置空，使 verifier 返回固定 `DESIGN_REPAIR_PROMPT`；循环保留首次 completed JSON、追加普通 assistant repair 提示，恢复同一 session 补回文档，第二次真实决策再次 `completed`。最终 `steps/07.json` 为 success、`current_node` 为 `project:08_initialize_repositories`、对话尾部为 completed，且没有旧 completion sentinel 或 `pending_agent_prompt`。

该证据不包含生产 failpoint 或生产 prompt：测试专用“不使用子代理”提示和文档置空只存在于隔离验证。Explore 子代理模型错误属于运行环境内部问题，不是公共循环缺陷。第 8 步仍待先讨论其既有初始化与首次提交合同；第 2/5/6 步若需要声明新公共循环的独立真实证据，应在各自新的真实 session 验证后再补记。
