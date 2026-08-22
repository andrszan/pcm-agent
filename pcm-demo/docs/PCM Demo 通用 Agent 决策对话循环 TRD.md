# PCM Demo 通用 Agent 决策对话循环 TRD

> 本文记录第 2、5、6、7 步已经实现的公共 Agent 对话循环。业务步骤语义仍以各步骤 README 和活动 TRD 为准。

## 1. 目标与边界

统一以下重复流程：

```text
Claude Agent 执行领域任务
→ 保存完整回复
→ AI-compatible 模型裁决
→ 恢复原 session
→ 完成、阻塞或失败
```

不建设工作流引擎、DSL、数据库、基类体系、领域验证框架或外层无限重试。

## 2. 模块职责

| 模块 | 职责 |
|---|---|
| `common/claude_agent.py` | 调用 Agent SDK，返回 init、回复、session、终止语义和安全错误分类 |
| `common/decision.py` | 定义并请求统一 `AgentDecision` |
| `common/agent_decision_loop.py` | 管理 conversation、session 恢复、Agent/决策交替和轮次上限 |
| 各步骤 `step.py` | 核验领域输入、定义 prompt、完成验证、blocked 映射和状态推进 |

公共循环不导入 `steps.*`，不执行 Git、测试、浏览器或领域文件判断。

## 3. 决策合同

```text
verdict: completed | continue | blocked
answer: string
reason: string
required_inputs: string[]
```

- `completed`：`answer` 和 `required_inputs` 为空；
- `continue`：`answer` 非空，`required_inputs` 为空；
- `blocked`：`answer` 为空，`required_inputs` 非空。

每次调用都附加严格 JSON、双引号和禁止 YAML 约束；结构化失败只重试一次。

## 4. 运行与完成

```text
步骤核验输入
→ Agent 返回完整回复
→ 回复作为 user 消息落盘
→ 决策模型裁决

continue → answer 发回原 session
blocked  → 当前运行停止
completed→ 步骤程序完成验证
             ├─ 通过：写 success 并推进
             ├─ 可补完：追加固定 repair prompt，继续原 session
             └─ 冲突或核验异常：failed
```

最终成功必须同时满足：

1. Agent 正常 `success`；
2. 决策为 `completed`；
3. 程序完成验证通过。

## 5. Conversation 与状态

Conversation 位于：

```text
runs/<run-id>/conversations/<key>.json
```

角色约定：

- `system`：本次 run 实际使用的决策约束；
- `assistant`：Agent 指令、结构化决定或 repair prompt；
- `user`：Agent SDK 返回的完整真实回复。

| 尾部 | 恢复动作 |
|---|---|
| `system` | 写入初始指令并调用 Agent |
| 普通 `assistant` | 将该指令发给 Agent |
| `user` | 请求决策，不重复调用 Agent |
| `continue` | 发送 `answer` |
| `completed` | 重新执行完成验证 |
| `blocked` | 返回 blocked；显式重跑时重新核验外部条件 |

最终成功时尾部就是 `completed`，不再追加 Python 固定完成声明。

状态只保留：

```text
claude_sessions.<key>
decision_conversations.<key>.path
<state_key>.last_agent_result
<state_key>.pending_agent_text
```

`pending_agent_text` 仅覆盖 ResultMessage 已取得但 conversation 尚未写入的窗口。新协议不写 `pending_agent_prompt`、decision turn 或 `COMPLETION_MESSAGE`。

## 6. 错误与阻塞

以下情况直接 `failed`：

- API、连接、CLI、进程或协议错误；
- 无 ResultMessage、session 或完整回复；
- session、cwd、Skill、slash command 不一致；
- 取消或未知正常终止原因；
- 路径、状态、上游交接或 Git 事实冲突；
- 决策在唯一重试后仍不符合结构。

`error_max_turns` 和 `error_max_budget_usd` 只有具备 session 与完整回复时才可继续裁决，并且必须取得后续正常 Agent `success` 才能完成。

`blocked` 只用于当前环境无法取得的不可替代外部资源。`blocked` 和 `failed` 都终止本次运行；`continue` 只在循环内部使用。

## 7. Prompt 与原文

每个步骤分别维护 Agent 初始 prompt、决策 system prompt 和 repair prompt：

- slash command 只保留在首行作为显式调用协议；
- 正文不写步骤编号、PCM 节点、阶段、session、轮次或预算；
- 只写领域任务、权威输入、产物、真实验证和边界；
- 不复制 Skill 的完整流程；
- repair prompt 只描述程序发现的固定缺口。

第 5 步传递最小选型投影；第 6、7 步传递白名单组装事实，不含 `git_url` 或 `origin`。

Agent 完整回复在 `pending_agent_text`、conversation 和决策输入中保持一致，不做后处理脱敏。Agent 仍不得主动输出秘密；SDK/API 异常和对外错误只保存安全分类。

## 8. 步骤适配

| 步骤 | 程序完成验证 |
|---|---|
| 2 `project-intake` | 两份产品定义为非空普通文件 |
| 5 `project-readiness` | 项目准备清单为非空普通文件 |
| 6 `project-bootstrap` | 前序交接、根 README、工程和 Git 边界 |
| 7 `solution-design` | 固定技术方案、前序交接和 Git 边界 |

第 6 步无适用工程时继续无副作用跳过，不进入公共循环。

## 9. 兼容与验证

兼容读取旧 `action`、旧完成 sentinel 和旧 `{path, turn}` 引用；旧非阻塞 action 的空 `answer` 使用固定安全继续提示，旧 conversation 不转换回写。

已验证：

- 公共循环 23 项、全量 83 项测试；
- `compileall`、`git diff --check` 和 IDE 诊断；
- 旧黄金 run 只读兼容；
- 隔离 run `agent-loop-step7-20260822T190149Z` 的同 session 恢复、严格决定、程序 repair 和最终推进；
- Probe C `probe-c-20260822T200038Z` 的普通 `continue` 与外部资源 `blocked`；
- 独立只读审查及修复复核。

AI-compatible 服务曾出现非 JSON 和 `status=incomplete`。当前实现严格失败，不增加第三次重试或手写容错解析；重复调用稳定性继续作为正式 PCM 的验证输入。
