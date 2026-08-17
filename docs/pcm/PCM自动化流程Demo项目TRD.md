# PCM 自动化流程 Demo 项目 TRD

> 本文是 PCM 自动化流程 Demo 的轻量活动技术设计，服务于分阶段实现和逐步验证。它不重复定义业务流程，也不提前设计正式 PCM。
>
> 上位文档：
>
> - [`PCM 自动化流程 Demo 项目设计`](./PCM自动化流程Demo项目设计.md)：定义 Demo 的目标、范围、黄金输入和最终完成标准；
> - [`PCM 程序化调度的 AI Agent 产品开发流程`](../../.claude/PCM版AI%20Agent自动化流程设计.md)：定义第 0～19 步的流程语义、职责边界和停止条件。
>
> 本文在 Demo 完成前保持活动状态。只有经过真实探针或步骤运行验证的事实才写为已确认结论；尚未验证的 SDK 行为、权限效果和步骤策略必须保留为待验证项。

## 一、目标与适用范围

本 TRD 先指导两个近期阶段：

1. **阶段 0：技术探针**——证明 Claude Agent SDK、项目 Skills、权限策略、会话恢复和 AI-compatible 结构化决策能够在本机真实工作；
2. **阶段 1：最小骨架与第 0～2 步**——建立可运行的公共封装，打通从 PRD 输入到 `project-intake` 收敛产品定义的第一个纵向切片。

后续第 3～19 步只在本文中保留阶段边界和进入条件。前一阶段真实验收通过后，再根据运行事实增量补充下一阶段设计，不提前规定尚未验证的内部实现。

### 本阶段不做

- 不一次创建第 0～19 步的空壳脚本；
- 不建设数据库、工作流 DSL、事件总线或通用状态机；
- 不设计正式 PCM 的多用户、权限、审计、计费、部署和运维体系；
- 不为未来步骤预建抽象基类、插件框架或通用重试框架；
- 不用 Stub、固定 JSON 或口头结论伪造步骤成功；
- 不自动 push、部署或操作生产环境；
- 不修改能力仓库中的黄金 PRD 原文件。

## 二、当前已确认的技术事实

### 1. Demo 运行边界

- Demo 工具代码位于当前能力仓库的 `pcm-demo/`；
- 每次运行使用独立工作区 `pcm-demo/workspace/<run-id>/`；
- 源 PRD 复制进工作区后，后续步骤只操作副本；
- 运行状态和步骤结果位于 `pcm-demo/runs/<run-id>/`；
- Demo 默认只操作本地文件、本地服务和本地 Git，不 push；
- 文件、Git、测试、服务和浏览器事实优先于 Agent 的文字结论。

### 2. 两类模型调用职责不同

**AI-compatible 模型**只负责受限语义决策，例如回答 Skill 提出的问题、批准低影响文档定稿、判断是否继续当前会话或识别真实阻塞。它不直接获得工作区文件和 Shell 操作权限。

**Claude Agent SDK**负责运行具备文件、命令和项目能力上下文的 coding agent，调用项目 Skills、修改工作区文件、执行验证，并返回会话结果和 session ID。

Python 编排器负责确定性操作和最终步骤状态，不把任何模型的单次文字输出直接视为完成证据。

### 3. Claude Agent SDK 当前约束

首轮实现基于 Python 包 `claude-agent-sdk`，最低 Python 版本按 SDK 当前要求使用 Python 3.10+。探针 A 的真实运行环境为 Python 3.13.14、`claude-agent-sdk` 0.2.139 和 SDK 捆绑的 Claude Code 2.1.233；宿主机另有 Claude Code 2.1.223，但本次未使用它作为后备路径。

每次项目 Agent 调用必须显式设置：

- `cwd`：本次运行的独立项目工作区根目录；
- `system_prompt`：使用 `claude_code` preset，不能依赖 SDK 的最小默认 prompt；
- `setting_sources=["project"]`：只加载工作区中的项目设置和项目能力，避免首轮 Demo 隐式依赖个人用户配置；
- `skills`：按当前步骤启用明确的 Skill，或在能力探针中使用 `"all"` 核对发现结果；
- `permission_mode`：由 Demo 显式设置，不继承项目设置中的宽泛默认模式；
- `max_turns` 和 `max_budget_usd`：探针与步骤分别设置有限上限，防止开放式任务无界运行；
- `resume`：需要继续特定历史会话时使用已保存的 session ID。

项目 Skills 来自工作区 `.claude/skills/`。当前核心流程 Skills 多数设置了 `disable-model-invocation: true`，因此步骤脚本应显式调用目标 Skill，不能只依赖模型自主选择。探针 A 已确认 `/project-intake` 可以显式调用，且目标 Skill 同时出现在 init 消息的 `skills` 和 `slash_commands` 中。

探针 A 还确认：`setting_sources=["project"]` 和 `skills=["project-intake"]` 不构成完全隔离。init 消息仍显示父项目的其它 Skills、内建能力和项目设置启用的 `context7` 插件。因此后续步骤必须核验目标能力已加载，并通过 `tools`、`allowed_tools`、`disallowed_tools` 和权限模式控制可执行工具；不能根据 init 列表推断其它能力均已隐藏。

SDK 不自动读取 Demo 的 `.env`。配置模块必须在创建 Agent SDK 或 AI-compatible 客户端前加载 `.env`，且不得把密钥写入状态或日志。

### 4. Agent 运行成功与步骤成功相互独立

`ResultMessage.subtype == "success"` 只说明 Agent loop 正常结束，不说明 PCM 步骤完成。Agent 可能正常结束于提问、请求确认或仅给出建议。

步骤是否成功必须由步骤脚本综合判断：

- 目标文件和目录是否真实存在；
- 文档是否满足本步骤完成条件；
- 命令、测试、构建、服务或浏览器证据是否通过；
- Git 分支、提交和工作树事实是否符合预期；
- 是否仍存在 Agent 提问、未决事项或外部资源缺口。

### 5. Session 只保存对话，不保存文件快照

SDK session 保存 Agent 对话、工具调用和结果；工作区文件与 Git 仍是独立事实。恢复会话时必须先重新核验当前文件和 Git 状态。

首轮 Demo 只承诺同一台机器、稳定工作区路径下的 session 恢复。跨机器、临时容器和正式共享存储不属于当前范围。

## 三、总体执行架构

```text
命令行入口
  ├── 运行状态与步骤调度
  ├── 确定性文件、命令和 Git 操作
  ├── AI-compatible 决策调用
  └── Claude Agent SDK 调用
          ├── 项目 CLAUDE.md / AGENTS.md
          ├── 项目 Skills 与 Subagents
          ├── 文件与命令工具
          └── 本地 session 持久化
```

### 1. 命令行入口

- `run_step.py`：运行一个已经实现的步骤；
- `run_all.py`：按顺序运行已纳入当前阶段的步骤；
- 未实现步骤必须明确返回“步骤尚未实现”的程序错误，不得返回业务 `success`；
- 单步、区间和完整运行复用相同步骤函数。

### 2. 公共封装

首轮只实现以下公共模块：

```text
pcm-demo/
├── common/
│   ├── config.py
│   ├── ai_chat.py
│   ├── claude_agent.py
│   ├── command.py
│   ├── files.py
│   └── state.py
├── prompts/
├── steps/
├── run_step.py
└── run_all.py
```

只有出现真实复用时才合并或新增模块，不为保持目录图而创建空文件。

### 3. 状态事实来源

- `state.json` 只保存支持恢复所必需的当前状态；
- `steps/<step>.json` 保存该步骤最近一次详细结果；
- `logs/` 保存脱敏运行日志；
- 工作区文件和 Git 仓库保存实际交付事实；
- Claude session 保存 Agent 对话上下文；
- 不把完整历史事件重复写入 `state.json`。

## 四、公共技术合同

### 1. 步骤结果

每个步骤只向外返回以下三种业务状态：

- `success`：完成条件已满足，或已确认不适用并无副作用跳过；
- `blocked`：缺少不可替代资源、重大决定或安全继续条件；
- `failed`：程序、SDK、命令、解析或执行发生错误。

最小结构：

```json
{
  "step": 2,
  "name": "项目需求与产品定义",
  "status": "success",
  "summary": "产品定义已经在工作区副本中收敛",
  "applicable": true,
  "outputs": [
    "docs/requirements/项目需求说明.md",
    "docs/requirements/产品功能说明.md"
  ],
  "blocked": null,
  "error": null
}
```

`blocked` 至少包含：

```json
{
  "reason": "缺少不可替代的外部输入",
  "required_inputs": ["输入名称"],
  "resume_step": 2
}
```

`error` 至少包含稳定错误类型和脱敏消息，不保存密钥、完整环境变量或不必要的模型原始响应。

### 2. Agent SDK 运行结果

公共封装必须保留 SDK 原始终止语义，不将其压缩成一个含混的布尔值：

```text
result_subtype
stop_reason
result
session_id
num_turns
total_cost_usd
exception
```

处理规则：

- 只有 `result_subtype == "success"` 时读取最终 `result`；
- `error_max_turns` 和 `error_max_budget_usd` 记录 session ID，供步骤判断继续、失败或阻塞；
- `error_during_execution` 视为 SDK 执行错误；
- 单次 `query()` 在产生错误结果后仍可能抛异常，封装必须保留此前已经收到的 ResultMessage；
- 连接或子进程在 ResultMessage 之前失败时，session ID 可以为空；
- 收到 ResultMessage 后仍继续消费消息流至结束，避免漏掉尾随系统事件。

### 3. AI-compatible 决策结果

首轮只支持一个最小结构：

```json
{
  "action": "answer",
  "answer": "采用推荐的低影响默认方案，并允许写入当前工作区文档",
  "reason": "源 PRD 已明确首版范围，当前决定不扩大产品边界",
  "required_inputs": []
}
```

`action` 只允许：

- `answer`：回答 Agent 提出的产品或技术问题；
- `approve`：在完成条件已满足时，批准当前文档写入或定稿；
- `continue`：要求原 session 根据已有事实继续完成尚未完成的同一步骤；
- `blocked`：当前问题超出自动决策边界或缺少不可替代输入。

结构化响应解析失败时可以进行少量重试；持续失败则当前步骤返回 `failed`，不能猜测决策。

### 4. 命令结果

命令封装返回：

```text
command
cwd
exit_code
stdout
stderr
duration
```

日志和结果中的命令输出必须脱敏。步骤完成判断使用真实退出码和输出，不根据 Agent 对命令结果的复述判断。

## 五、Claude Agent SDK 调用约定

### 1. 初始化核验

每次新 session 开始时，从 `SystemMessage` 的 `init` 数据中至少记录并核对：

- session ID；
- 实际工作目录；
- 已加载 Skills；
- 已加载 slash commands；
- 已加载 plugins；
- 实际模型；
- 可用工具或其它能够证明运行配置的初始化信息。

目标 Skill 未加载时，当前调用直接失败，不让模型在缺少目标能力时自行模拟该 Skill。

### 2. Skill 调用

步骤脚本显式指定目标 Skill 和参数，例如项目内 Skill 使用其实际可调用名称，插件 Skill 使用带 namespace 的名称。具体 prompt 形态由阶段 0 探针确认后固化。

同一步骤的后续回答、批准、继续或修复优先恢复原 session，不创建新的无上下文会话。需要独立审查视角的步骤按流程要求新建 session。

### 3. 权限档位

首轮采用“明确批准 + 其余拒绝”的无人值守策略，不使用 `bypassPermissions`。

#### `read_only`

用于能力发现、输入核验和只读分析：

- 权限模式：`dontAsk`；
- 允许：`Read`、`Glob`、`Grep`、目标 Skill 所需的只读能力；
- 禁止文件写入和 Bash 修改操作。

#### `document_write`

用于第 2 步产品文档收敛：

- 权限模式：`dontAsk`；
- 允许：`Read`、`Glob`、`Grep`、`Write`、`Edit`、目标 Skill；
- Bash 默认不批准；只有探针证明目标 Skill 必须执行某个确定性只读命令时，才添加精确规则。

#### `development`

第 14 步前不展开具体命令清单。它必须在可丢弃工作区内另行设计，并满足：

- 不使用 `bypassPermissions` 代替权限设计；
- Git push、部署、生产操作和工作区外写入保持禁止；
- Git 建分支、合并和提交继续由对应显式步骤或 `commit-changes` 负责；
- 每类新增命令权限都由真实步骤需要证明。

项目 `.claude/settings.json` 中的 allow、ask、deny 规则仍可能参与权限判断。探针 A 已确认 `permission_mode="dontAsk"` 配合显式 `tools` 和路径级 `disallowed_tools`，可以在当前项目默认 `bypassPermissions` 配置下拒绝目标 Write：SDK 产生了错误 ToolResult，目标文件没有创建，基线文件哈希保持不变。当前 SDK 没有把该拒绝汇总到 `ResultMessage.permission_denials`，因此实现必须同时观察中间 ToolResult 和最终文件事实。

### 4. Session 保存与恢复

- 每个需要继续的领域步骤使用稳定键保存 session ID，例如 `project_intake`、`REQ-003:development`；
- 第一次收到 init 或最终 ResultMessage 时更新 session ID；
- 阻塞、turn 上限或预算上限发生时仍保存已取得的 session ID；
- `--resume` 重新读取 `state.json`、原工作区和当前步骤，再通过 `resume=<session-id>` 继续；
- 恢复后先要求 Agent 重新核验相关文件和 Git 事实；
- session 文件缺失或无法恢复时，不静默新建会话冒充恢复成功。步骤应记录恢复失败，并根据可用文件事实决定返回 `failed` 或显式开启新的恢复策略；首轮不自动实现后者。

## 六、程序化决策循环

### 1. 基本流程

```text
显式调用目标 Skill
→ 消费 Agent 消息和工具结果
→ 检查 ResultMessage 与工作区事实
→ 若步骤完成：执行完成条件核验
→ 若 Agent 提问或请求确认：调用 AI-compatible 决策模型
→ 将结构化决策作为下一条用户消息恢复原 session
→ 重复，直到 success、blocked 或 failed
```

外层步骤编号在循环中保持不变。

### 2. 自动决策边界

AI-compatible 模型可以决定：

- PRD 已经明确、不会扩大首版范围的低影响产品细节；
- 可逆、局部且不改变跨模块边界的文档组织方式；
- 在完成条件满足后批准工作区文档写入；
- 要求 Agent 根据已有事实继续完成当前步骤；
- 将非阻断建议排除出当前 Demo 范围。

以下情况必须返回 `blocked`，不能由决策模型静默决定：

- 改变 PRD 的目标用户、核心业务闭环或 E.1 首版范围；
- 新增真实外部服务、账号、付费资源或不可替代依赖；
- 重大架构、安全、权限、兼容性或不可逆数据决定；
- 使用 Mock、假凭据或降低验收标准来绕过缺失条件；
- 当前资料相互冲突且不同选择会实质改变交付结果；
- 任何必须由人授权、审批或线下完成的动作。

### 3. 决策上下文

发送给 AI-compatible 模型的上下文只包含当前决策所需的最小信息：

- 当前步骤及完成条件；
- 黄金 PRD 或工作区权威文档的相关摘录；
- Agent 当前问题、建议和理由；
- 已确认决定；
- 明确的自动决策边界；
- 当前文件、命令或 Git 的必要事实摘要。

不发送密钥、完整 `.env`、无关仓库内容或可由程序直接判断的原始大段日志。

## 七、阶段实施与验收

### 阶段 0：技术探针

阶段 0 不是第 0 个业务步骤，不写入正式步骤状态。探针代码可以在骨架稳定后保留为集成测试或诊断命令。

#### 探针 A：Agent SDK 与项目能力加载

验证：

1. SDK 可以在指定可丢弃工作区启动；
2. `claude_code` preset 生效；
3. 只启用 `project` setting source 时，项目 `CLAUDE.md` 和核心 Skills 可加载；
4. init 消息包含预期 Skill 和命令；
5. 可以显式调用一个无破坏性的项目 Skill；
6. 可以取得 ResultMessage、session ID、turn 数和成本；
7. 未授权写入或命令在 `dontAsk` 下被拒绝。

通过标准：上述事实均由实际 SDK 消息、工作区变化和拒绝结果证明，不依赖 Agent 自述。

#### 探针 B：跨进程 session 恢复

验证：

1. 第一次进程创建 session，并让 Agent 读取一个固定工作区事实；
2. 将 session ID 保存到临时状态；
3. 结束第一次进程；
4. 第二次进程使用该 ID 恢复；
5. Agent 能基于前次对话回答问题，同时重新读取已变化的文件事实；
6. 证明 session 恢复没有替代文件事实核验。

#### 探针 C：AI-compatible 结构化决策

验证：

1. 能读取 Demo 自己加载的配置；
2. 能返回符合约定的 JSON；
3. 无效 JSON 会被检测和有限重试；
4. 自动决策边界外的问题返回 `blocked`；
5. 日志和状态中不出现 API Key。

#### 阶段 0 完成条件

- 三个探针均真实通过；
- 已记录实际 SDK 版本、模型和关键初始化事实；
- 已确认项目 Skill 的显式调用格式；
- 已确认权限档位能覆盖项目设置中的宽泛默认权限；
- 已确认同机跨进程 session 恢复可行；
- 所有与本 TRD 不一致的实测结果已经先更新本文，再进入阶段 1。

### 阶段 1：最小骨架与第 0～2 步

#### 实现范围

- 建立最小 `pcm-demo/` 工程和配置；
- 实现文件、状态、命令、AI-compatible 和 Agent SDK 公共封装；
- 实现统一步骤结果；
- 实现 `run_step.py` 和只覆盖第 0～2 步的 `run_all.py`；
- 实现第 0 步完整 PRD 无副作用跳过；
- 实现第 1 步工作区创建、PRD 复制和 SHA-256 记录；
- 实现第 2 步 `project-intake` 多轮决策与 session 恢复；
- 验证能力仓库中的源 PRD 哈希不变。

#### 第 0 步完成条件

- 能判断黄金输入已经是完整产品初稿；
- 返回 `success` 且 `applicable: false`；
- 不创建或修改产品文档；
- 不修改源 PRD；
- 跳过依据写入步骤结果。

#### 第 1 步完成条件

- 创建唯一 run ID、运行目录和独立工作区；
- PRD 副本位于工作区预期路径；
- `state.json` 记录源绝对路径或可解析路径、源 SHA-256、工作区副本路径和工作区根目录；
- 重复执行不会静默覆盖归属不明的已有工作区；
- 源 PRD 哈希保持不变。

#### 第 2 步完成条件

- 目标 `project-intake` Skill 已从 init 消息确认加载；
- Agent 只操作工作区副本；
- Agent 的问题和定稿确认经过受限决策循环处理；
- 产品定义输出真实存在且内容满足上位流程完成条件；
- SDK success、步骤 completion judge 和文件事实三者分别记录；
- 需要继续时可以恢复原 `project_intake` session；
- 自动决策边界外的问题会阻塞，而不是由模型擅自扩大或缩小范围。

#### 阶段 1 完成条件

- 第 0、1、2 步均能单独运行；
- 第 0～2 步可以串联运行；
- 进程中断后可以从当前步骤继续；
- 步骤结果、状态、日志和工作区事实一致；
- 源 PRD 前后哈希一致；
- 没有以 Stub 或固定结果代替真实 Agent 与文件行为。

### 后续阶段边界

后续设计在进入对应阶段前增量补充：

1. **阶段 2：第 3～10 步**——初始化流程、项目工程、架构、UI/UX 框架和 Backlog；
2. **阶段 3：第 11～19 步单需求循环**——先完整跑通一个需求，验证多仓库 Git、开发、审查、修复、合并和状态同步；
3. **阶段 4：Backlog 循环与最终验收**——至少两个需求、测试阻塞恢复、最终项目检查以及 Demo 结论。

进入下一阶段前，前一阶段必须通过，且本文已根据真实运行结果更新相关技术合同。

## 八、测试与验证策略

首轮测试只覆盖当前阶段的真实风险：

- 配置和敏感信息不泄露；
- JSON、Markdown、状态和 SHA-256 读写；
- 步骤状态转换；
- Agent SDK 初始化消息与 ResultMessage 解析；
- 权限拒绝；
- session ID 保存与恢复；
- PRD 复制和源文件不变；
- 第 0～2 步单独运行及串联运行。

SDK 和模型调用使用真实服务完成至少一次集成验证。纯解析和状态逻辑可以使用固定本地样例做单元测试，但不得用 Mock 的模型成功响应替代阶段验收。

验证记录优先保存在自动化测试输出、步骤结果和脱敏日志中，不为每次探针另建过程报告。

## 九、错误、阻塞与恢复

### 返回 `failed`

- 配置缺失或格式错误；
- SDK、AI-compatible API 或子进程执行错误；
- 结构化响应持续解析失败；
- 目标 Skill 未加载；
- session ID 存在但恢复失败；
- 文件、状态或哈希操作失败；
- 步骤完成条件未满足且属于可修复实现错误。

### 返回 `blocked`

- 缺少不可替代账号、凭据、服务、设备、素材、数据或审批；
- 重大产品、架构、安全、兼容性或不可逆决定超出自动决策边界；
- 工作区存在归属不明或冲突修改，无法安全继续；
- 当前事实相互冲突且不同选择会实质改变交付结果。

### 恢复原则

- 恢复当前步骤，不直接跳到下一步；
- 重新读取状态、文件和 Git 事实；
- 原 session 可用时优先恢复；
- 已存在的局部产物先核验再继续，不自动删除或覆盖；
- 阻塞解除后重新执行当前步骤的完成条件检查。

## 十、配置与敏感信息

首轮配置至少包含：

```text
AI_BASE_URL=
AI_API_KEY=
AI_MODEL=
ANTHROPIC_API_KEY=
CLAUDE_MODEL=
```

具体键名在实现前与现有环境统一，避免同时支持没有真实需要的别名。实际 `.env` 必须 Git 忽略；`.env.example` 只保存键、公开默认值和安全占位说明。

日志不得记录：

- API Key、token、密码或完整认证头；
- `.env` 具体值；
- 含秘密的命令行和工具输入；
- 无助于恢复的完整模型上下文。

## 十一、当前未决事项

以下事项必须由探针或后续阶段事实解决，暂不在本 TRD 中假定答案：

1. 阶段 0 后续运行中 Agent SDK、捆绑 Claude Code 或模型版本发生变化时，需重新记录并复核探针结果；
2. 项目 Skill 的显式调用已由探针 A 确认为 `/project-intake <参数>`，其它 Skill 在进入对应步骤前按相同方式逐个验证；
3. 探针 A 已确认只设置 `project` source 不会隐藏父项目其它 Skills、内建能力和项目设置启用的插件；如后续需要更强隔离，应另行设计独立配置目录或显式本地插件方案；
4. 探针 A 已确认当前权限组合可以拒绝路径级 Write，但其它写入工具和 Bash 命令仍需在对应权限档位引入时逐项验证；
5. AI-compatible 服务是否稳定支持当前 JSON 结构，是否需要单独的 schema 约束能力；
6. 第 2 步 completion judge 应由同一个 AI-compatible 模型完成，还是先使用确定性文件检查加单次语义核验；
7. 第 3 步需要的基础工程来源；当前能力仓库尚未把模板资产入口作为已确认事实；
8. 后续开发步骤所需浏览器通道、外部审查能力和命令权限清单。

这些事项不妨碍阶段 0 开始，但对应探针未通过前不得进入依赖它的业务步骤。
