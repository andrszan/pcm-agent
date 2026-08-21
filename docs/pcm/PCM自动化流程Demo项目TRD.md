# PCM 自动化流程 Demo 项目 TRD

> 本文是 PCM 自动化流程 Demo 的轻量活动技术设计，服务于分阶段实现和逐步验证。它不重复定义业务流程，也不提前设计正式 PCM。
>
> 上位文档：
>
> - [`PCM 自动化流程 Demo 项目设计`](./PCM自动化流程Demo项目设计.md)：定义 Demo 的目标、范围、黄金输入和最终完成标准；
> - [`PCM 程序化调度的 AI Agent 产品开发流程`](../../.claude/PCM版AI%20Agent自动化流程设计.md)：定义第 0～19 步、阶段一、阶段二的流程语义、职责边界和停止条件。
>
> 截至 2026-08-21，技术探针以及业务第 0～2 步已经实现并真实验证。上位流程从第 3 步起发生重大调整，旧第 3 步合同与实现已经回退，不作为当前能力；本文先同步新版阶段边界和已知交接合同，具体代码设计仍从第 3 步开始逐步讨论、确认和增量补充。

## 一、目标、当前范围与状态

### 1. Demo 技术实施阶段

Demo 继续采用增量实施，不一次创建完整流程空壳：

1. **技术阶段 0：能力探针**——已完成。验证 Claude Agent SDK、项目 Skills、权限策略、session 恢复和 AI-compatible 结构化决策在本机真实可用；
2. **技术阶段 1：最小骨架与第 0～2 步**——业务步骤已实现。打通完整初稿输入、独立产品项目工作区发布和 `project-intake` 产品定义；
3. **技术阶段 2：第 3～11 步**——待逐步讨论和实现。按新版顺序完成基础工程选型、组装、准备核验、项目化、总体技术方案、仓库首次提交、按需架构与 UI/UX 框架、Backlog；
4. **技术阶段 3：阶段一第 12～19 步**——待逐步讨论和实现。先完整跑通一个正式需求，再验证第二个真实需求及多仓库循环；
5. **技术阶段 4：阶段二完整审计与最终收口**——待逐步讨论和实现。验证全项目体验审计、候选分流、需求化入池、修复回归、完整复审和最终验收。

这里的“技术阶段”只表示 Demo 的实现顺序；上位产品开发流程中的“阶段一”和“阶段二”仍分别指逐需求开发和全项目级集成产品体验审计。

### 2. 当前已实现范围

当前代码已经实现：

- `run_step.py` 的第 0、1、2 步单步入口；
- 第 0 步完整产品初稿无副作用跳过；
- 第 1 步项目身份提取、固定模板浅克隆、清理、原子发布和零提交根仓库初始化；
- 第 2 步 `project-intake` 多轮决策、项目 trust 处理、Claude session 和 AI-compatible 决策历史恢复；
- 与上述步骤直接相关的配置、文件、状态、Responses API 和 Agent SDK 公共能力；
- 各步骤目录内的测试和说明。

当前尚未实现：

- 第 3 步及以后任何新版步骤；
- `run_all.py` 完整串联入口；
- `phase/current_node` 状态协议；
- `applicable_repositories`、阶段一需求循环状态和阶段二状态。

未实现能力必须返回明确的程序错误，不得以空脚本、固定 JSON、旧第 3 步实现或口头结论冒充成功。

### 3. 本轮文档同步边界

本轮只完成：

- 将步骤编号和职责同步为新版第 0～19 步；
- 删除旧第 3 步“总体技术方案兼模板选型”合同；
- 增加第 3～11 步的新顺序、第 12～19 步阶段一循环和阶段二完整审计边界；
- 明确当前已完成至第 2 步，且已完成代码不受新版流程影响；
- 记录实现第 3 步前必须讨论的状态演进和技术未决项。

本轮不完成第 3 步代码设计、实现、测试或运行状态迁移。

### 4. 本阶段继续不做

- 不一次创建第 3～19 步或阶段二节点的空壳脚本；
- 不建设数据库、工作流 DSL、事件总线或通用状态机；
- 不设计正式 PCM 的多用户、权限、审计、计费、部署和运维体系；
- 不为未来步骤预建抽象基类、插件框架或通用重试框架；
- 不用 Stub、固定 JSON 或模型口头结论伪造步骤成功；
- 不自动 push、部署或操作生产环境；
- 不修改能力仓库中的黄金 PRD 原文件；
- 不把阶段二审计塞入单需求开发、首条验证切片或局部 UI 检查。

## 二、当前已确认的技术事实

### 1. Demo 运行与仓库边界

- Demo 工具代码位于当前能力仓库的 `pcm-demo/`；
- 运行状态和步骤结果位于被 Git 忽略的 `pcm-demo/runs/<run-id>/`；该目录只保存本地恢复数据和脱敏日志，不提交实际 run 内容；
- 产品项目工作区位于实际采用的 `PCM_WORKSPACE_ROOT/<project_directory_name>/`，不以 run ID 作为最终项目目录名；
- 第 1 步将源产品初稿写入产品项目的 `docs/产品初稿.md`，后续步骤只操作项目内文件；
- 源产品初稿路径、完整 UTF-8 内容和 SHA-256 保存在运行状态中，源文件不得修改；
- Demo 默认只操作本地文件、本地服务和本地 Git，不 push；
- 文件、Git、测试、构建、服务和浏览器事实优先于 Agent 的文字结论；
- 根仓库在第 1 步初始化为零提交 `main`；第 8 步只核验并首次提交根仓库，不重复初始化根仓库；
- 第 8 步未来生成 `applicable_repositories`，后续不固定遍历不存在或不适用的 `frontend/`、`backend/`。

### 2. 两类模型调用职责不同

**AI-compatible 模型**代表自动化流程中的人工调度者，处理所有能够基于当前输入、项目事实、可用工具和已提供资源完成的产品、技术、文档、流程及执行决策。它不直接获得工作区文件和 Shell 操作权限，由 PCM 提供当前决策所需的最小事实。只有模型和当前环境无法取得的不可替代外部资源时才返回 `blocked`；输入、结构或本地状态错误返回 `failed`。

**Claude Agent SDK**负责运行具备文件、命令和项目能力上下文的 coding agent，调用项目 Skills、修改工作区文件、执行验证，并返回 session 结果。

Python 编排器负责确定性操作、两类会话衔接和最终步骤状态，不把任何模型的单次文字输出直接视为完成证据。

### 3. Claude Agent SDK 当前约束

首轮实现基于 Python 包 `claude-agent-sdk`，最低 Python 版本按 SDK 当前要求使用 Python 3.10+。探针 A 的真实运行环境为 Python 3.13.14、`claude-agent-sdk` 0.2.139 和 SDK 捆绑的 Claude Code 2.1.233；宿主机另有 Claude Code 2.1.223，但本次未使用它作为后备路径。

每次项目 Agent 调用必须显式设置或保证：

- `cwd`：本次运行的独立项目工作区根目录；
- `system_prompt`：使用 `claude_code` preset，不能依赖 SDK 的最小默认 prompt；
- Skills 和 plugins：按项目配置与锁定事实加载，并从 init 消息核验目标能力；
- `max_turns` 和 `max_budget_usd`：设置有限上限，防止开放式任务无界运行；当前第 2 步单次调用预算为 `$4`，后续步骤预算在各步合同中根据真实任务单独确认；
- `resume`：需要继续特定历史会话时使用已保存的 session ID。

正式步骤不传入 `permission_mode`、`tools`、`allowed_tools` 或 `disallowed_tools`，也不为每一步重新定义权限档位。项目 `.claude/settings.json` 及 Claude Code 默认设置加载语义是统一权威来源。若未来某一步确有覆盖项目配置的特殊理由，必须先在该步合同中说明并单独确认，不能沿用探针限制。

第 2 步真实运行确认：Claude Code 对未信任的新路径会忽略项目 `permissions.allow`。PCM 采用默认 Claude Code 用户配置目录、认证、插件、Skill 和 session；在 `~/.claude.json` 中为已由第 1 步发布证据确认的最终产品路径写入 `hasTrustDialogAccepted: true`，使项目 settings 生效。该用户级配置共享所有 PCM run，符合单租户本地 Demo 的预期；不得把 run-local `CLAUDE_CONFIG_DIR` 作为默认隔离层。

普通终端执行第 0→2 步时，默认用户级 Claude 配置、认证、项目 plugins/Skills 和 session 均可用；第 2 步完成后 run 目录不创建 `claude-config/`，同一 run 重跑第 2 步可以恢复原会话或幂等确认成功。

项目 Skills 来自工作区 `.claude/skills/` 和项目锁定 plugins。核心流程 Skills 多数设置了 `disable-model-invocation: true`，因此步骤脚本应显式调用目标 Skill，不能只依赖模型自主选择。探针 A 已确认 `/project-intake` 可以显式调用，且目标 Skill 同时出现在 init 消息的 `skills` 和 `slash_commands` 中。

探针 A 使用显式权限覆盖验证了 SDK 的限制能力，也确认 Skills、plugins 和项目设置的实际加载结果需要从 init 消息核验。这些探针配置只证明 SDK 行为，不作为正式步骤的默认权限合同。

### 4. AI-compatible 配置与调用

`LLMConfig` 从 `pcm-demo/.env` 加载 `LLM_BASE_URL`、`LLM_API_KEY` 和 `LLM_MODEL`，同名进程环境变量优先。实际 `.env` 由 Git 忽略，配置对象的 `repr` 不包含字段值；`.env.example` 只保存公开占位说明。Claude Agent SDK 仍使用自身的 Anthropic 认证配置，两类模型配置不混用。

SDK 不自动读取 Demo 的 `.env`。配置模块必须在创建 Agent SDK 或 OpenAI-compatible 客户端前显式加载配置，且不得把密钥写入状态或日志。探针 C 运行时发现宿主环境配置了 SOCKS 代理，但当前 OpenAI SDK 环境没有 SOCKS 依赖；探针通过 SDK 的 `DefaultAsyncHttpxClient(trust_env=False)` 明确禁用环境代理，未修改宿主代理配置，也未增加无关依赖。

第 1 步项目身份提取使用 Responses API 的 `instructions`、`input` 和 `text.format` strict JSON Schema。服务不支持 `/responses` 或该 Schema 时返回 `failed`，不回退到 Chat Completions。

第 3 步不再使用旧的“Agent 自然语言选型汇报 → Responses API 二次裁决 → Python 补齐字段”链路。新版第 3 步由 `foundation-selection` Agent 直接返回固定纯 JSON，程序只做确定性校验。

### 5. Agent 运行成功与步骤成功相互独立

`ResultMessage.subtype == "success"` 只说明 Agent loop 正常结束，不说明 PCM 步骤完成。Agent 可能正常结束于提问、请求确认、只给出建议、输出格式错误或产物未落盘。

步骤是否成功必须由步骤脚本综合判断：

- 目标文件和目录是否真实存在；
- 文档是否满足本步骤完成条件；
- JSON 是否满足 schema 和引用身份；
- 命令、测试、构建、服务或浏览器证据是否通过；
- Git 分支、提交、合并和工作树事实是否符合预期；
- 是否仍存在 Agent 提问、未决事项、审计覆盖缺口或外部资源缺口。

### 6. Session 只保存对话，不保存文件快照

SDK session 保存 Agent 对话、工具调用和结果；工作区文件与 Git 仍是独立事实。恢复会话时必须先重新核验当前文件和 Git 状态。

首轮 Demo 只承诺同一台机器、稳定工作区路径下的 session 恢复。探针 B 已使用三个独立 Python 进程验证：第一进程创建 session 并读取旧文件值，第二进程确定性修改文件，第三进程通过原 session ID 先在无工具 turn 中复述旧值，再恢复同一 session 并重新调用 `Read` 取得新值；三个阶段的 session ID 保持一致。跨机器、临时容器和正式共享存储不属于当前范围。

## 三、总体执行架构

```text
命令行入口
  ├── 运行状态与步骤/节点调度
  ├── 确定性文件、命令和 Git 操作
  ├── AI-compatible 决策调用
  └── Claude Agent SDK 调用
          ├── 项目 CLAUDE.md / AGENTS.md
          ├── 项目 Skills 与 Subagents
          ├── 项目 settings 与 plugins
          ├── 文件、命令、服务和浏览器工具
          └── 本地 session 持久化
```

### 1. 命令行入口

- `run_step.py`：当前只运行已经实现的第 0、1、2 步；实际命令和配置说明以 `pcm-demo/README.md` 及各步骤 README 为准；
- `run_all.py`：尚未实现；需要串联已实现步骤和节点时再建立；
- 未实现步骤必须明确返回“步骤尚未实现”的程序错误，不得返回业务 `success`；
- 单步、区间、完整运行和恢复最终必须复用相同步骤或节点函数；
- 阶段二使用 `--from-node phase_2:*` 一类具名入口，不新增虚假业务步骤编号。

### 2. 当前公共模块

```text
pcm-demo/
├── config.py
├── common/
│   ├── claude_agent.py
│   ├── decision.py
│   ├── files.py
│   ├── openai_responses.py
│   └── state.py
├── probes/
├── steps/
│   ├── step_00_product_draft/
│   ├── step_01_create_workspace/
│   └── step_02_project_intake/
└── run_step.py
```

只有出现两个及以上步骤的真实复用时才合并或新增公共模块，不为保持目录图创建空文件。

### 3. 状态事实来源

- `state.json` 只保存支持恢复所必需的当前状态；
- `steps/<step>.json` 保存业务步骤最近一次详细结果；
- 阶段二节点结果保存于明确的节点结果或状态引用中，具体目录在阶段二实现前确认；
- `logs/` 保存脱敏运行日志；
- `conversations/` 保存 AI-compatible 完整、脱敏的编排历史；
- 工作区文件和 Git 仓库保存实际交付事实；
- Claude session 保存 Agent 对话上下文；
- 不把完整历史事件重复写入 `state.json`。

## 四、公共技术合同

### 1. 步骤与节点结果

每个步骤或阶段二节点只向外返回以下三种业务状态：

- `success`：完成条件已满足，或已确认不适用并无副作用跳过；
- `blocked`：缺少模型和当前环境无法取得的不可替代外部资源；
- `failed`：程序、SDK、模型、命令、解析、文件、Git、验证或状态发生错误。

当前第 0～2 步结果尚未包含阶段节点字段。实现第 3 步前，目标结果需要演进为：

```json
{
  "phase": "project_initialization",
  "current_node": "project:03_foundation_selection",
  "step": 3,
  "name": "基础工程选型",
  "status": "success",
  "summary": "基础工程模板选择已经完成并通过 catalog 引用校验",
  "applicable": true,
  "outputs": [],
  "blocked": null,
  "error": null
}
```

`blocked` 至少包含：

```json
{
  "reason": "缺少不可替代的外部输入",
  "required_inputs": ["输入名称"],
  "resume_phase": "project_initialization",
  "resume_node": "project:03_foundation_selection"
}
```

业务步骤可以同时保留 `resume_step` 作为兼容信息，但阶段二恢复不能只依赖数字步骤。确切兼容和迁移方式在第 3 步合同讨论时确认。

`error` 至少包含稳定错误类型和脱敏消息，不保存密钥、完整环境变量或不必要的模型原始响应。

### 2. 输出路径与交接

- 业务文档与工程产物的 `outputs` 统一记录相对于产品项目根 `state.workspace.final_path` 的非空相对路径；
- 下游必须以产品项目根解析并核验，拒绝绝对路径、越出根目录的 `..` 路径和符号链接；
- 运行控制数据可以保存在步骤结果的稳定字段中，例如第 3 步 `steps/03.json.template_selection`，不强制伪装成项目文件产物；
- 下一步从前一步结果读取实际交接对象，不从固定路径、技术文档、Agent 自然语言或会话历史重新推断；
- 阶段二审计原始结果、候选分流、入池和回归证据通过稳定引用保存，不能只留在 session 中。

### 3. 第 1 步工作区发布合同

第 1 步使用 AI-compatible 模型从产品初稿提取严格 JSON：

```json
{
  "topic_name": "基于 Web 的社区物品维修预约与维修进度协作系统",
  "project_directory_name": "mendmark"
}
```

`topic_name` 必须明确表达当前产品选题。`project_directory_name` 必须是单段小写 kebab-case；初稿已经给出仓库名或英文代号时优先提取，未给出时允许模型根据选题生成，并把来源和生成理由写入提取证据。初稿无法确定产品选题、API 或结构解析失败、有限重试耗尽时返回 `failed`，不能猜测字段。

产品工作区根目录的优先级为 CLI `--workspace-root`、进程环境 `PCM_WORKSPACE_ROOT`、`pcm-demo/.env` 中的同名配置，并且必须位于当前能力仓库之外。模板仓库从进程环境或 `pcm-demo/.env` 的 `PCM_TEMPLATE_REPOSITORY` 读取，单次运行不能覆盖。最终项目路径为 `<root>/<project_directory_name>`。

确定性发布顺序为：

1. 保存源产品初稿的绝对路径、完整 UTF-8 内容和 SHA-256；
2. 在最终目录同级计算 `<project_directory_name>.pcm-tmp-<run-id>` 临时路径；
3. 先用 Git 核验已配置模板仓库默认分支和读取权限，再执行 `git clone --depth 1`；
4. 记录模板默认分支、实际分支、commit SHA 和 remote URL，并核验 `CLAUDE.md`、`AGENTS.md`、`project-intake` Skill、`frontend/` 与 `backend/` 等关键能力；
5. 只在临时目录已证明属于当前 run 后删除其中的上游 `.git/`，删除原 `docs/` 内容后重建空 `docs/`，再按原始字节写入 `docs/产品初稿.md`；
6. 核验上游 `.git/` 已删除、`docs/` 只含产品初稿、源和目标初稿哈希一致、源文件未变化且模板能力仍存在；
7. 所有发布核验通过后，将同文件系统中的临时目录原子重命名为最终项目路径；
8. 在最终项目根执行 `git init -b main`，不执行 `git add`、`git commit` 或 push；
9. 核验 `git rev-parse --show-toplevel` 等于最终项目根、当前分支为 `main`、`HEAD` 尚不存在，并记录根仓库初始化证据。

第 1 步成功时 `state.json` 至少保存以下结构；完整命令结果放在步骤结果或脱敏日志中：

```json
{
  "project": {
    "topic_name": "基于 Web 的社区物品维修预约与维修进度协作系统",
    "project_directory_name": "mendmark",
    "extraction": {
      "directory_name_source": "source",
      "reason": "初稿已明确 Git 仓库名"
    }
  },
  "workspace": {
    "root": "/products",
    "root_source": "PCM_WORKSPACE_ROOT",
    "staging_path": "/products/mendmark.pcm-tmp-<run-id>",
    "final_path": "/products/mendmark"
  },
  "template": {
    "repository": "<configured-template-repository>",
    "remote_url": "<configured-template-repository>",
    "default_branch": "main",
    "actual_branch": "main",
    "commit_sha": "<sha>"
  },
  "publication_phase": "git_initialized",
  "root_repository": {
    "path": "/products/mendmark",
    "branch": "main",
    "head": null
  },
  "checks": {
    "template_capabilities_present": true,
    "upstream_git_removed": true,
    "docs_reinitialized": true,
    "draft_hash_matches": true,
    "source_draft_unchanged": true,
    "renamed_to_final_path": true,
    "root_git_initialized": true,
    "root_git_is_final_path": true,
    "root_git_has_no_commits": true
  }
}
```

失败时保留现场。恢复只续接状态能证明属于同一 run、同一模板和同一目标的完整 clone 或已发布最终目录；不完整 clone、临时与最终目录同时存在、目录归属不明或证据冲突时不自动删除或覆盖。最终目录已发布但根 `git init` 中断时，只有发布证据一致、根 `.git/` 不存在或仍是零提交 `main` 仓库，才允许续接或幂等确认根仓库初始化；已有 commit、Git 根指向其它目录或分支不一致时返回 `failed` 并保留现场。

### 4. Agent SDK 运行结果

公共封装保留 SDK 原始终止语义：

```text
init
text/result
result_subtype
is_error
session_id
stop_reason
num_turns
total_cost_usd
exception
```

处理规则：

- 只有 `result_subtype == "success"` 且 `is_error == false` 时，才把最终文本作为正常 Agent 结果读取；
- `error_max_turns` 和 `error_max_budget_usd` 记录 session ID，供步骤恢复原 session 继续；即使 SDK 在产生该 ResultMessage 后又抛出异常，也保留已取得的可恢复 subtype；
- `error_during_execution` 视为 SDK 执行错误；
- 单次 `query()` 在产生错误结果后仍可能抛异常，封装必须保留此前已经收到的 ResultMessage；
- 连接或子进程在 ResultMessage 之前失败时，session ID 可以为空；
- 收到 ResultMessage 后继续消费消息流至结束，避免漏掉尾随系统事件；
- 恢复调用中观察到的 session ID 必须与请求恢复的 ID 一致，否则返回失败；
- SDK 正常结束后仍需执行步骤自己的完成条件检查。

### 5. AI-compatible 决策结果

决策模型使用以下最小结构：

```json
{
  "action": "answer",
  "answer": "采用当前输入和项目事实支持的方案，并继续完成当前步骤。",
  "reason": "该决定可由现有资料和工具完成，不依赖额外外部资源。",
  "required_inputs": []
}
```

`action` 只允许：

- `answer`：回答 Agent 提出的产品、技术、文档、流程或执行问题；
- `approve`：以原人工调度者的等效授权批准当前产物写入或定稿；
- `continue`：要求原 session 根据已有事实继续完成尚未完成的同一步骤；
- `blocked`：缺少模型和当前环境无法取得的不可替代外部资源。

决策模型拥有原人工调度者在同等输入和工具条件下可完成的全部决策权。存在多个合理方案、资料歧义、重大取舍或不可逆设计决定时，模型应选择并记录理由，不因需要判断而返回 `blocked`。结构化响应解析失败时可以少量重试；持续失败则当前步骤返回 `failed`，不能猜测决策。

### 6. 命令结果

命令封装最终统一返回：

```text
command
cwd
exit_code
stdout
stderr
duration
```

日志和结果中的命令输出必须脱敏。步骤完成判断使用真实退出码和输出，不根据 Agent 对命令结果的复述判断。命令封装只在两个及以上后续步骤出现真实复用时建立，不为当前文档结构提前创建。

## 五、Claude Agent SDK 调用约定

### 1. 初始化核验

每次新 session 开始时，从 `SystemMessage` 的 `init` 数据中至少记录并核对：

- session ID；
- 实际工作目录；
- 已加载 Skills；
- 已加载 slash commands；
- 已加载 plugins；
- 实际模型；
- 可用工具；
- 权限模式；
- Claude Code 版本。

目标 Skill 未加载时，当前调用直接失败，不让模型在缺少目标能力时自行模拟该 Skill。

### 2. Skill 调用

步骤脚本显式指定目标 Skill 和参数，例如项目内 Skill 使用其实际可调用名称，plugin Skill 使用带 namespace 的实际名称。每个新 Skill 的显式调用格式在进入对应步骤前真实验证。

同一步骤的后续回答、批准、继续或修复优先恢复原 session，不创建新的无上下文会话。需要独立审查视角的步骤或阶段二完整审计按流程要求新建独立 session。

### 3. 项目配置与权限

正式步骤把项目 `.claude/settings.json` 和锁定 plugins 作为项目能力配置的权威事实。步骤代码不重复设置 `permission_mode`、`tools`、`allowed_tools` 或 `disallowed_tools`，不按文档、开发、审计等步骤类型另建默认权限档位，也不默认禁止 Bash。

能力探针可以为验证某个 SDK 行为显式覆盖权限，但覆盖只属于该探针。正式步骤若确需偏离项目配置，必须有该步骤独有且已确认的理由，并在合同中明确覆盖范围；不得把探针策略复用为通用限制。

步骤仍需从 init 消息记录实际工作目录、Skill、命令、plugin、模型和可用工具，并以真实工具结果判断配置是否生效。项目 `deny` 规则仍按项目配置执行，PCM 不删除或绕过。

### 4. 两类会话保存与恢复

Claude Agent SDK 与 AI-compatible 决策模型使用不同的历史机制：

- 每个需要继续的领域步骤使用稳定键保存 Claude session ID，例如 `project_intake`、`foundation_selection`、`REQ-003:development`、`phase_2:audit:<fingerprint>`；
- 第一次收到 init 或最终 ResultMessage 时更新 session ID；阻塞、turn 上限或预算上限发生时仍保存已取得的 session ID；
- 恢复时重新读取 `state.json`、原工作区和当前节点，再通过 `resume=<session-id>` 继续；恢复后的第一项任务是重新核验相关文件和 Git 事实；
- session 文件缺失或无法恢复时，不静默新建会话冒充恢复成功，当前节点返回 `failed`；
- AI-compatible 接口不依赖服务端 conversation 或 response ID；PCM 按领域键把完整、脱敏的编排消息历史原子写入 `runs/<run-id>/conversations/<key>.json`，每次调用携带该历史；
- 历史至少保留初始 Agent 指令、每轮 Agent 结果、决策模型收到的当前事实、完整结构化决策、转发给 Agent 的指令和完成标记；
- 不同步骤、不同正式需求和不同阶段二审计轮使用独立领域键，避免上下文污染；
- `state.json` 只保存历史文件引用、当前轮次和恢复所需事实，不复制完整消息；
- 完整编排历史只保存当前流程所需的脱敏内容，不保存密钥、完整环境变量或无关工具日志；首轮不建设数据库、向量记忆或摘要系统。

## 六、程序化决策循环

### 1. 基本流程

```text
显式调用目标 Skill
→ 消费 Agent 消息和工具结果
→ 检查 ResultMessage 与工作区事实
→ 若节点完成：执行完成条件核验
→ 若 Agent 提问或请求确认：调用 AI-compatible 决策模型
→ 将结构化决定作为下一条用户消息恢复原 session
→ 重复，直到 success、blocked 或 failed
```

外层步骤或节点在循环中保持不变。

### 2. 自动决策权限与阻塞边界

AI-compatible 模型可以决定所有能够基于当前输入、项目事实、可用工具和已提供资源完成的事项，包括：

- 产品范围、业务规则、文档内容和组织方式；
- 技术方案、架构、安全、权限、兼容性和不可逆设计取舍；
- Agent 提出的澄清、确认、继续和定稿请求；
- 多个合理方案或相互冲突资料之间的选择；
- 非阻断建议是否纳入当前范围；
- 阶段一需求选择；
- 阶段二候选分流、需求化、合并、拆分和排序。

模型作出决定时记录选择及理由，不把“需要判断”当作 `blocked`。只有缺少模型和当前环境无法取得的不可替代外部资源时才返回 `blocked`，例如：

- 输入或资源清单之外的真实外部服务、账号、付费资源或凭据；
- 客户专属素材、私有数据或专用设备；
- 必须由外部人员完成的授权、审批或线下动作；
- 阶段二主要任务不可替代的真实环境、身份、数据或浏览器能力。

模型不得用 Mock、假凭据、虚构资源或降低验收标准来伪造资源已经具备。

### 3. 决策上下文与历史

发送给 AI-compatible 模型的每一轮消息只包含当前决定所需的最小信息：

- 当前 `phase/current_node`、步骤和完成条件；
- 当前步骤的权威输入；
- Agent 当前问题、建议和理由；
- 该领域历史中已经作出的决定；
- 当前可用资源清单；
- 当前文件、命令、Git、服务或浏览器的必要事实摘要。

第 2 步的权威输入仅包括第 1 步发布的产品初稿、项目规则与配置、当前 `project-intake` 对话和该 Skill 已生成的产品定义产物；工作区中的技术方案、Backlog、TRD、代码和其它无关文档不作为本步骤决策输入，其存在也不构成阻塞。

PCM 在请求前读取该领域完整编排历史，追加当前 `user` 决策上下文；收到结构化响应后，将完整原始 JSON 作为 `assistant` 消息原子保存，并把其中的 `answer` 作为下一条用户指令发送给原 Claude session。不得只保存最后一个 `action`，也不得丢失初始任务和 Agent 当前问题。

不发送密钥、完整 `.env`、无关仓库内容或可由程序直接判断的原始大段日志。

## 七、已实现步骤合同与验收状态

### 技术阶段 0：能力探针

技术阶段 0 不是业务第 0 步，不写入正式步骤状态。

#### 探针 A：Agent SDK 与项目能力加载

已真实验证：

1. SDK 可以在指定可丢弃工作区启动；
2. `claude_code` preset 生效；
3. 项目规则、Skills、slash commands 和 plugins 可以从实际初始化消息核验；
4. 可以显式调用 `/project-intake`；
5. 可以取得 ResultMessage、session ID、turn 数和成本；
6. 探针显式权限限制可以拒绝未授权写入或命令；
7. 探针权限覆盖不作为正式步骤默认配置。

#### 探针 B：跨进程 session 恢复

已使用三个独立 Python 进程验证：

1. 第一进程创建 session 并读取随机旧值；
2. 第二进程确定性修改文件并记录新 SHA-256；
3. 第三进程恢复原 session，在无工具 turn 中复述旧值；
4. 第三进程再次恢复同一 session，重新调用 `Read` 取得新值；
5. session ID 始终一致；
6. 当前文件 SHA-256 与实际工具事件证明 session 不替代文件事实核验。

#### 探针 C：OpenAI-compatible 结构化决策

已使用真实 Responses API 服务验证：

1. 能读取 Demo 自己加载的配置；
2. 能返回符合约定的结构化 JSON；
3. 无效 JSON 会被检测和有限重试；
4. 普通定稿决定可以返回 `approve`；
5. 缺少真实支付账号与密钥时返回 `blocked` 并给出解除条件；
6. 日志和状态中不出现 API Key。

### 第 0 步：形成产品初稿

完成条件：

- 黄金输入已经是完整产品初稿；
- 返回 `success` 且 `applicable: false`；
- 不创建或修改产品文档；
- 不修改源 PRD；
- 跳过依据写入步骤结果。

当前状态：已实现并验证。

### 第 1 步：建立项目工作区

完成条件：

- AI-compatible 模型从真实产品初稿取得明确 `topic_name` 和合法 `project_directory_name`；
- 独立工作区根按 CLI、进程环境、Demo `.env` 优先级解析，且位于当前能力仓库之外；
- 固定模板仓库通过 `git clone --depth 1` 克隆到最终目录同级临时路径；
- 模板默认分支、实际分支、commit SHA 和 remote URL 已记录；
- 最终目录不含上游模板 Git 历史，模板关键能力仍存在，`docs/` 只包含 `产品初稿.md`；
- 最终项目根已经初始化为 `main` 分支的独立 Git 仓库，且尚无 commit；
- 状态记录源初稿、项目身份、临时与最终路径、模板证据、发布阶段和根仓库事实；
- 项目内初稿与源初稿 SHA-256 一致，源初稿未变化；
- 重复执行、归属不明目录、残留临时 clone、clone/rename/Git 初始化中断不会覆盖现场或误报成功。

当前状态：已实现并真实验证。

### 第 2 步：项目需求与产品定义

能力：`project-intake`。

输入边界：

- 第 1 步发布的 `docs/产品初稿.md`；
- 产品项目的 `CLAUDE.md`、`AGENTS.md`、`.claude/settings.json` 和锁定 plugins；
- 当前 `project-intake` 对话；
- 该 Skill 已生成的产品定义产物；
- 当前可用外部资源清单。

技术方案、Backlog、TRD、代码和其它无关文档不进入本步骤决策上下文，其存在不构成阻塞。

执行动作：

1. 重新核验第 1 步最终路径、根 Git、`main`、空 `HEAD`、初稿哈希和发布证据；
2. 只对已由第 1 步证据确认的最终产品路径写入 Claude Code trust；
3. 在产品项目根通过 Claude Agent SDK 显式调用 `project-intake`；
4. 从 init 消息核验目标 Skill、slash command、plugins、cwd、模型、工具和权限；
5. Agent 提问、确认或取舍时，调用 AI-compatible 决策模型；
6. 将决定发送回原 Claude session，持续到产品定义完成或真实阻塞；
7. 核验目标文档真实存在且可读；
8. 保存 Claude session ID、完整决策历史、步骤结果和文件事实。

输出：

- `docs/requirements/项目需求说明.md`；
- `docs/requirements/产品功能说明.md`；
- `state.json` 中的 `claude_sessions.project_intake`；
- `runs/<run-id>/conversations/project_intake.json`；
- `steps/02.json`。

完成条件：

- 目标 `project-intake` Skill 已从 init 消息确认加载并显式调用；
- 产品定义只使用规定输入；
- Agent 的问题和定稿确认经过完整决策循环；
- 决策历史按领域键完整持久化并能恢复；
- 产品定义输出真实存在且可读取；
- SDK 结果、步骤完成判断和文件事实分别记录；
- 需要继续时能够恢复原 `project_intake` session；
- 只有不可替代外部资源缺失时返回 `blocked`；
- 步骤代码未覆盖项目权限和工具配置。

当前状态：已实现并真实验证；同一 run 可以恢复原 Claude session 和决策历史，当前文件事实仍会重新核验。

## 八、新版后续流程边界

### 第 3 步：基础工程选型

能力：`foundation-selection`。

已由上位流程确定的合同边界：

- 输入：第 2 步产品定义、开发约束和本次 `catalog.json`；
- catalog 身份：实际路径、来源、SHA-256 和 `schema_version` 必须记录；
- Agent 只读取产品资料与本次 catalog，从 `repositories[*].templates[*]` 中选择适用前端和后端模板；
- 成功结果必须是一个固定结构的纯 JSON 对象，JSON 外不得包含自然语言、Markdown 或代码围栏；
- 每个适用选择直接原样带出模板 `id`、所属仓库 `git_url`、`default_branch`、模板 `path` 和选择 `reason`；
- 项目明确不需要某一端时，对应值为 `null`；
- 资料不可读、候选不匹配或无法安全选择时，只返回 `{"error":"具体原因"}`，不输出部分选型；
- 编排器校验 JSON、schema 以及每个引用与同一 catalog 的一致性，不根据需求或 catalog 替 Agent 补选，不从自然语言提取；
- 成功选择写入 `steps/03.json.template_selection`；
- 第 4 步只读取该稳定对象；
- 本步骤不生成总体技术方案，不获取、复制或组装模板，不初始化前后端仓库。

固定成功结构：

```json
{
  "frontend": {
    "id": "",
    "git_url": "",
    "default_branch": "",
    "path": "",
    "reason": ""
  },
  "backend": {
    "id": "",
    "git_url": "",
    "default_branch": "",
    "path": "",
    "reason": ""
  }
}
```

具体 Demo 代码合同尚未确认，包括 catalog schema 的现有事实、目标 Skill 的实际调用名与参数、预算、JSON 捕获方式、有限重试、步骤状态迁移、恢复幂等和真实验收样例。实现前必须与开发者逐项讨论并先更新本文。

### 第 4～11 步：项目初始化与项目级设计

| 步骤 | 能力或执行方式 | 输入重点 | 输出与完成边界 |
| --- | --- | --- | --- |
| 4 组装基础工程 | 确定性文件和 Git 操作 | 只读 `steps/03.json.template_selection` | 适用工程目录完整、来源明确、无嵌套上游 `.git` 或临时模板目录 |
| 5 核验项目准备状态 | `project-readiness` | 产品定义、选型、已组装工程、当前资源 | 当前开发必需项均为 `ready` 或 `not-applicable`；可生成配置在本步补齐 |
| 6 项目化基础工程 | `project-bootstrap` | 基础工程、产品定义、选型、准备清单 | 项目身份、基础配置、文档、最小联调完成；适用安装、构建、测试和启动通过 |
| 7 总体技术方案 | `solution-design` | 产品定义、已组装并项目化的工程事实、开发约束、选型 | 总体技术方案与当前工程一致，不重新选型或组装 |
| 8 初始化并提交适用仓库 | 显式 Git 脚本、`commit-changes` | 第 1 步零提交根仓库、完成项目化的适用工程 | 根仓库和适用交付单元各有首次本地提交，形成 `applicable_repositories` |
| 9 工程架构设计（按需） | `engineering-architecture` | 产品定义、总体技术方案、当前工程 | 分层、模块、目录和依赖边界可指导实现；适用文档完成后由 `commit-changes` 精确提交根仓库，简单项目可无副作用跳过 |
| 10 产品级 UI/UX 框架（按需） | `ui-ux-framework` | 产品定义、总体方案、工程事实、相关设计资料 | 产品表面、信息架构、Shell、导航和跨需求体验约束已确认并提交根仓库，或明确不适用 |
| 11 拆分 Backlog | `requirement-breakdown` | 产品定义、总体方案、适用架构/UIUX 结论、工程事实 | Backlog 覆盖最终范围，详情卡清楚，首条验证切片由完整正式需求组成；由 `commit-changes` 精确提交根仓库后进入阶段一 |

这些只是上位流程边界。每一步进入实现前，仍需对照原手稿、当前流程和当时工程事实，逐项确认具体输入身份、确定性动作、Agent 提示、输出 schema、完成条件、失败、阻塞、恢复和验证方法。

### 阶段一：第 12～19 步单需求循环

阶段一只执行第 12～19 步，不调用 `product-experience-audit`。

| 步骤 | 名称 | 核心边界 |
| --- | --- | --- |
| 12 | 选择需求并建立根仓库需求分支 | AI 选择依赖满足且顺序靠前的需求；根仓库从最新 `main` 建唯一活动分支 |
| 13 | 形成最终活动 TRD | `trd-design` 收敛范围、行为、技术方案、验证和需求级体验设计；完成后提交根需求分支 |
| 14 | 建立代码仓库需求分支 | 只为受影响代码仓库从最新 `main` 建分支，不受影响仓库不机械创建 |
| 15 | 实现与验证 | `dev-workflow` 完成实现、测试、构建、运行、联调、浏览器交互、真实渲染验收和独立审查；代码仓精确提交 |
| 16 | 合并代码仓库并在 `main` 最终验证 | 合并受影响代码仓并在 `main` 重新执行相关验证 |
| 17 | 同步需求最终状态并提交根需求分支 | 基于真实代码与验证结果更新活动 TRD、Backlog 和详情卡；记录恢复锚点提交 |
| 18 | 在原开发 session 复盘执行规则 | 恢复原 `development_session` 调用 `session-rule-retrospective`；只允许 `.claude/rules/` diff，结果为 `no_change` 或精确提交 |
| 19 | 最后合并根仓库并检查适用仓库 | 最后合并根需求分支到 `main`，检查所有 `applicable_repositories` 的分支、提交和工作树 |

阶段一完成当前正式范围内全部需求后，进入阶段二；首条验证切片、单需求、单页面或局部改动都不触发全项目审计。

### 阶段二：全项目级集成产品体验审计与迭代

#### 1. 入口与范围

进入条件：

- 当前正式范围内全部需求已完成第 12～19 步；
- 根仓库和所有适用交付单元均位于清楚的 `main`；
- 产品是完整可集成运行的版本；
- 审计所需真实环境、测试身份、可复位数据、清理方式、浏览器、视口、安全边界和适用辅助技术路径已经具备或可在当前节点补齐。

审计范围至少覆盖：

- 当前正式范围内全部主要用户任务、主要角色和跨页面闭环；
- 多个真实产品表面或模块；
- 代表性桌面和窄屏；
- 适用辅助技术路径；
- 允许写入及禁止资金、外发、生产数据和其它高影响副作用；
- 现有验收、UI/UX 框架和已知限制。

范围以用户任务、状态和风险表达，不以单页清单、截图浏览或 happy path 代替。

#### 2. 独立完整审计

- 外层在独立 Claude Agent SDK session 中显式调用一次 `product-experience-audit`；
- 所有适用仓库 `main` commit SHA 共同构成 `version_fingerprint`；
- Skill 从真实任务出发执行动态审计，实际读取代表性截图并收集相称的交互、状态、网络或可访问性证据；
- Skill 只返回经核验候选、重复或未纳入项、覆盖缺口和高影响边界；
- Skill 不修改业务代码、产品定义、TRD 或 canonical Backlog，不创建正式需求或 ID，不暂存、提交或自动调用其它能力；
- PCM 保存原始输出引用、审计 session、版本指纹和四类结果。

#### 3. 外层分流、需求化和入池

外层基于审计证据、已有 Backlog 和产品事实逐项分流：

- 已有需求或共同根因已有归属时记录重复，不新建需求；
- 误判、无用户影响依据、纯主观偏好或价值不足时记录不纳入理由；
- 证据不足或存在覆盖缺口时先补齐动态证据；
- 优先需求化删除、合并、减少步骤、调整默认值或复用现有模式的最小可验证改动；
- 证据充分且用户结果、范围、依赖和验收方向清楚的候选才获得正式 ID；
- 需要合并、拆分、排序或重算依赖时显式调用 `requirement-breakdown`；需要更新产品定义时显式调用 `project-intake`；
- 合格候选通过根仓库最新 `main` 上的短期入池分支写入正式 Backlog，调用 `commit-changes` 精确提交，再显式合并回 `main`；
- 入池只创建后续可选择的需求，不创建活动 TRD、代码分支或完成状态。

#### 4. 修复、原发现回归与完整复审

- 每个已入池需求从根仓库最新 `main` 完整复用第 12～19 步；
- 复用期间仍不调用 `product-experience-audit`；
- 每个修复完成后重走原复现任务、受影响状态和相邻路径，保存针对原发现的体验回归证据；
- 一批需求完成后，以新的 `version_fingerprint` 建立独立完整复审轮次；
- 新候选继续分流、入池和开发；重复、不纳入或非阻断机会不触发无穷循环；
- 新发现的关键覆盖缺口必须补验，不能复用旧版本证据。

#### 5. 阶段二完成条件

阶段二只有同时满足以下条件才成功：

1. 最新完整审计来自所有适用仓库清楚的 `main` 版本事实；
2. 已覆盖当前正式范围内全部主要用户任务和多个产品表面或模块；
3. 适用动态任务已在真实浏览器和真实开发/测试服务执行；
4. 主要界面和关键状态具有实际读取的代表性截图和相称动态证据；
5. 候选、重复项、未纳入项、覆盖缺口和高影响边界均已保存并完成分流；
6. 所有自动入池需求均完成第 12～19 步，并通过原发现回归；
7. 最后一轮完整复审没有新增符合需求化政策的候选，也没有未处理的高信心阻断或高优先级问题；
8. 与主要任务有关的环境、角色、数据、视口、辅助技术和动态证据覆盖缺口已经关闭；
9. 所有适用仓库位于预期 `main`，工作树无意外变更，结果与仍适用限制已经汇总。

## 九、状态演进与恢复目标

### 1. 当前状态事实

当前第 0～2 步使用 `current_step`、`status`、`root_repository`、`checks`、`claude_sessions` 和 `decision_conversations` 等字段，能够支持现有单步运行和第 2 步恢复。

新版流程增加：

- 第 3～11 步项目初始化与项目级设计节点；
- 第 12～19 步可重复需求循环；
- 不带数字步骤的阶段二审计、分流、入池、回归和复审节点。

因此只使用 `current_step` 已不足以表达完整恢复位置。

### 2. 目标恢复锚点

实现第 3 步前，需要确认并演进为：

```json
{
  "phase": "project_initialization",
  "current_node": "project:03_foundation_selection",
  "step": 3
}
```

阶段一目标状态至少需要：

```json
{
  "phase": "phase_1_requirement_development",
  "current_node": "requirement:19_merge_root",
  "active_requirement": "REQ-002",
  "requirement_cycle": {
    "root_requirement_branch": "feat/req-002",
    "development_session": "session-id",
    "step_17_commit": "<sha>",
    "step_18": {
      "outcome": "no_change",
      "commit": null
    },
    "step_19_merge_evidence": null,
    "return_node_after_completion": "phase_1:select_requirement"
  }
}
```

阶段二目标状态至少需要：

```json
{
  "phase": "phase_2_full_product_audit",
  "current_node": "phase_2:route_candidates",
  "requirement_cycle": null,
  "phase_two": {
    "audit": {
      "version_fingerprint": {
        "root": "<root-main-sha>",
        "frontend": "<frontend-main-sha>",
        "backend": "<backend-main-sha>"
      },
      "session": "session-id",
      "result": "<完整审计输出引用>",
      "verified_candidates": "<经核验候选引用>",
      "duplicates": "<重复或未纳入项引用>",
      "coverage_gaps": "<覆盖缺口引用>",
      "high_impact_boundaries": "<高影响边界引用>"
    },
    "candidate_routing": null,
    "pooling_evidence": null
  }
}
```

上述仓库字段只遍历实际 `applicable_repositories`；示例中的前后端不表示固定要求。

### 3. 恢复与幂等规则

1. 每个节点开始前保存 `phase/current_node` 和已核验输入；成功后原子保存输出、事实证据和下一节点；
2. `--resume <run-id>` 只重跑当前节点，先重新核验文件、分支、提交、工作树、版本指纹和外部条件；
3. 已有 Claude session 时优先恢复；session 不可恢复时返回 `failed`，不静默新建；
4. 第 17 步状态同步提交是第 18、19 步恢复锚点；
5. 第 18 步只接受 `no_change` 或 `committed`，且只允许根仓库 `.claude/rules/` 变更；
6. 第 19 步以根 `main` 合并提交和所有适用仓库检查作为完成证据；
7. 阶段二每轮审计记录 `version_fingerprint` 和独立 session；相同清楚指纹恢复既有审计，不重复制造候选；
8. 候选分流和入池保存稳定证据；已入池候选不得重复分配 ID；
9. 阶段二修复需求临时使用 `phase_2_requirement_remediation` 和 `requirement_cycle`，并设置 `return_node_after_completion: phase_2:regress_and_reaudit`；
10. 每一步实际输入从前一步结果读取并核验，不从固定路径猜测；
11. 第 1 步继续使用现有发布阶段事实安全恢复；
12. 路径、目录、分支、提交、合并、版本指纹、候选归属或入池证据冲突时保留现场并返回 `failed`。

当前 `current_step` 状态如何迁移到 `phase/current_node`、是否兼容既有本地 run、迁移在第 3 步入口还是独立准备动作执行，均留到第 3 步合同讨论时确认，不在本轮文档中臆定。

## 十、测试与验证策略

### 1. 已完成范围

当前测试和真实验证覆盖：

- 配置和敏感信息不泄露；
- JSON、Markdown、状态和 SHA-256 读写；
- 第 0～2 步状态转换；
- Agent SDK 初始化消息与 ResultMessage 解析；
- 探针权限拒绝；
- Claude session ID 和 AI-compatible 决策历史分别保存与恢复；
- 产品初稿身份提取、模板分支和 SHA 记录、固定模板浅克隆、同级临时目录、原子发布与根仓库零提交初始化；
- 上游 `.git/` 清理、`docs/` 重置、项目内初稿写入和源文件不变；
- 第 1 步 clone、发布或根仓库初始化中断后的现场保留、归属核验和安全恢复；
- 第 2 步目标 Skill、plugins、trust、输入边界、决策循环、产物和恢复。

### 2. 后续增量风险

进入对应步骤后再增加最小真实验证：

- 第 3 步：catalog 身份、固定纯 JSON、schema、引用一致性、`null`、错误对象、恢复与不做二次推断；
- 第 4 步：模板获取、目录组装、来源核验、嵌套 `.git` 与临时目录清理；
- 第 5～8 步：准备清单、安装/构建/测试/启动、最小联调、仓库初始化和首次提交；
- 第 9～11 步：按需判定、项目级文档、Backlog 完整覆盖和提交；
- 第 12～19 步：多仓库分支、提交、合并、开发 session、规则复盘、状态同步和恢复；
- 阶段二：真实完整运行、主要任务覆盖、独立审计 session、版本指纹、候选去重、入池幂等、原发现回归和完整复审。

SDK 和模型调用使用真实服务完成至少一次集成验证。纯解析和状态逻辑可以使用固定本地样例做单元测试，但不得用 Mock 的模型成功响应替代阶段验收。

验证记录优先保存在自动化测试输出、步骤结果和脱敏日志中，不为每次探针或步骤另建冗余过程报告。

## 十一、错误、阻塞与停止

### 返回 `failed`

- 配置缺失、格式错误或身份变化；
- SDK、AI-compatible API、子进程或必要工具执行错误；
- 结构化响应持续解析失败；
- 目标 Skill 或 plugin 未加载；
- session ID 存在但恢复失败或不一致；
- catalog 不可读、schema 无效、引用不一致、Agent 输出不是单一纯 JSON；
- 文件、状态、哈希、路径、目录归属或产物交接错误；
- Git 分支、提交、合并、工作树或版本指纹冲突；
- 测试、构建、启动、联调、浏览器验收、审计回归或完整复审失败；
- 候选归属、正式 ID、入池分支、提交或合并证据冲突；
- 当前节点完成条件未满足且属于可修复实现或现场错误。

### 返回 `blocked`

- 缺少模型和当前环境无法取得的不可替代账号、凭据、服务、付费资源、设备、素材、私有数据、授权、审批或线下动作；
- 缺少固定模板或候选模板仓库不可替代的读取权限；
- 阶段二主要任务缺少不可替代的真实环境、测试身份、可复位数据、真实浏览器或安全边界。

输入不完整、状态证据冲突、目录归属不明、catalog 错误或本地现场无法确定性继续属于 `failed`，不是 `blocked`。

产品、技术、架构、安全、权限、兼容性、不可逆设计、资料冲突、候选分流和需求化本身不构成阻塞，由决策模型选择并记录理由。

### 停止行为

任何步骤或节点返回非 `success` 时：

- 原子保存 `phase/current_node`、已完成范围、证据、阻塞或错误；
- 停止外层运行，不继续后续步骤、候选分流、Backlog 入池、需求开发或复审；
- 保留当前文件、Git 和运行现场；
- 给出已尝试动作、真实缺口和继续命令；
- 条件修复或资源补齐后，只恢复当前节点。

## 十二、配置与敏感信息

当前配置：

```text
LLM_BASE_URL=
LLM_API_KEY=
LLM_MODEL=
PCM_WORKSPACE_ROOT=
PCM_TEMPLATE_CATALOG=
PCM_TEMPLATE_REPOSITORY=
```

配置职责：

- `LLM_*` 只用于 AI-compatible Responses API；
- `PCM_WORKSPACE_ROOT` 是独立产品项目父目录；
- `PCM_TEMPLATE_REPOSITORY` 只用于第 1 步开发管理模板；
- `PCM_TEMPLATE_CATALOG` 只用于第 3 步基础工程候选；
- Claude Agent SDK 模型与认证继续使用 SDK/Claude Code 的环境或既有登录态，不另设 `CLAUDE_MODEL`。

优先级：

- `--workspace-root` 可覆盖 `PCM_WORKSPACE_ROOT`；
- 第 3 步未来的 `--catalog-path` 可覆盖 `PCM_TEMPLATE_CATALOG`；
- 两者优先级均为 CLI、进程环境、`pcm-demo/.env`；
- `PCM_TEMPLATE_REPOSITORY` 单次运行不可覆盖。

实际 `.env` 必须 Git 忽略；`.env.example` 只保存键、公开默认值和安全占位说明。

日志不得记录：

- API Key、token、密码或完整认证头；
- `.env` 具体值；
- 含秘密的命令行和工具输入；
- 无助于恢复的完整模型上下文；
- 客户私有数据、生产数据或不必要的真实身份信息。

## 十三、当前未决事项

以下事项在进入对应步骤前解决，暂不臆定答案：

1. Agent SDK、捆绑 Claude Code 或模型版本变化时，需重新记录并复核相关探针；
2. `/project-intake` 已验证，其它目标 Skill 的实际调用名、参数、plugin namespace 和 init 发现结果需逐步验证；
3. 新版第 3 步所使用 `catalog.json` 的实际 schema、样例、`schema_version`、身份字段和错误边界；
4. `foundation-selection` 的实际调用方式、预算、固定 JSON 捕获、有限重试、错误对象和恢复合同；
5. 现有 `current_step` 状态如何迁移到 `phase/current_node`，是否兼容已有本地 run；
6. `run_all.py` 在何时建立，以及第 0～2 步现有入口如何与新节点协议复用；
7. 第 4 步模板仓库获取、缓存与目录组装的最小安全合同；
8. 第 8 步如何从实际交付单元形成 `applicable_repositories`，以及根仓库忽略规则和各仓首次提交合同；
9. 第 9、10 步按需判定如何基于真实工程事实实现，而不机械生成文档；
10. 阶段一受影响仓库识别、分支命名、合并顺序、主分支最终验证和第 17～19 步幂等锚点；
11. 阶段二真实浏览器通道、测试身份、可复位数据、截图读取、辅助技术路径和外部审查能力；
12. 阶段二审计结果、候选分流、入池和原发现回归证据的最小持久化格式；
13. 相同 `version_fingerprint` 的恢复、不同指纹的完整复审以及避免无穷循环的确定性边界。

这些未决事项不影响已完成第 0～2 步。每个新步骤实现前，必须先对照原手稿、当前流程设计和活动 TRD，与开发者确认详细合同；确认后先更新并提交相关设计文档，再实现和真实验证。该协作要求不改变 PCM 运行时由 AI-compatible 模型完成可决策事项、仅因不可替代外部资源而阻塞的自动化原则。