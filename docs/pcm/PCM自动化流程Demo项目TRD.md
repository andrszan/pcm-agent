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
2. **阶段 1：最小骨架与第 0～2 步**——建立可运行的公共封装，打通从产品初稿输入、发布独立产品项目工作区到 `project-intake` 收敛产品定义的第一个纵向切片。

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
- 运行状态和步骤结果位于被 Git 忽略的 `pcm-demo/runs/<run-id>/`；该目录只保存本地恢复数据和脱敏日志，不得提交实际 run 内容；
- 产品项目工作区位于实际采用的 `PCM_WORKSPACE_ROOT/<project_directory_name>/`，不以 run ID 作为最终项目目录名；
- 第 1 步将源产品初稿写入产品项目的 `docs/产品初稿.md`，后续步骤只操作项目内文件；
- 源产品初稿路径、完整 UTF-8 内容和 SHA-256 保存在运行状态中，源文件不得修改；
- Demo 默认只操作本地文件、本地服务和本地 Git，不 push；
- 文件、Git、测试、服务和浏览器事实优先于 Agent 的文字结论。

### 2. 两类模型调用职责不同

**AI-compatible 模型**代表自动化流程中的人工调度者，处理所有能够基于当前输入、项目事实、可用工具和已提供资源完成的产品、技术、文档、流程及执行决策。它不直接获得工作区文件和 Shell 操作权限，由 PCM 提供当前决策所需的最小事实。只有模型和当前环境无法取得的不可替代外部资源时才返回 `blocked`；输入或本地状态错误返回 `failed`。

**Claude Agent SDK**负责运行具备文件、命令和项目能力上下文的 coding agent，调用项目 Skills、修改工作区文件、执行验证，并返回会话结果和 session ID。

Python 编排器负责确定性操作、两类会话的衔接和最终步骤状态，不把任何模型的单次文字输出直接视为完成证据。

### 3. Claude Agent SDK 当前约束

首轮实现基于 Python 包 `claude-agent-sdk`，最低 Python 版本按 SDK 当前要求使用 Python 3.10+。探针 A 的真实运行环境为 Python 3.13.14、`claude-agent-sdk` 0.2.139 和 SDK 捆绑的 Claude Code 2.1.233；宿主机另有 Claude Code 2.1.223，但本次未使用它作为后备路径。

每次项目 Agent 调用必须显式设置：

- `cwd`：本次运行的独立项目工作区根目录；
- `system_prompt`：使用 `claude_code` preset，不能依赖 SDK 的最小默认 prompt；
- `skills`：按当前步骤启用明确的 Skill，或在能力探针中使用 `"all"` 核对发现结果；
- `max_turns` 和 `max_budget_usd`：探针与步骤分别设置有限上限，防止开放式任务无界运行；第 2 步 `project-intake` 和第 3 步 `solution-design` 当前单次调用预算均为 `$4`；
- `resume`：需要继续特定历史会话时使用已保存的 session ID。

正式步骤不传入 `permission_mode`、`tools`、`allowed_tools` 或 `disallowed_tools`，也不为每一步重新定义权限档位。`setting_sources` 保持 SDK/Claude Code 默认加载语义，使项目 `.claude/settings.json` 中的 `permissions.defaultMode`、`allow`、`ask`、`deny` 及插件配置作为统一项目配置生效。若未来某一步确有覆盖项目配置的特殊理由，必须先在该步合同中说明并单独确认，不能沿用探针限制。

第 2 步真实运行确认：Claude Code 对未信任的新路径会忽略项目 `permissions.allow`。PCM 采用默认 Claude Code 用户配置目录、认证、插件、Skill 和 session；在 `~/.claude.json` 中为已由第 1 步发布证据确认的最终产品路径写入 `hasTrustDialogAccepted: true`，使项目 settings 生效。该用户级配置共享所有 PCM run，符合单租户本地 Demo 的预期；不得把 run-local `CLAUDE_CONFIG_DIR` 作为默认隔离层。

方案 A 真实验收已确认：普通终端执行第 0→2 步时，默认用户级 Claude 配置、认证、项目插件/Skill 和 session 均可用；第 2 步完成后 run 目录不创建 `claude-config/`，同一 run 重跑第 2 步可以幂等确认成功。

项目 Skills 来自工作区 `.claude/skills/`。当前核心流程 Skills 多数设置了 `disable-model-invocation: true`，因此步骤脚本应显式调用目标 Skill，不能只依赖模型自主选择。探针 A 已确认 `/project-intake` 可以显式调用，且目标 Skill 同时出现在 init 消息的 `skills` 和 `slash_commands` 中。

探针 A 使用显式权限覆盖验证了 SDK 的限制能力，也确认 Skills、插件和项目设置的实际加载结果需要从 init 消息核验。这些探针配置只证明 SDK 行为，不作为正式步骤的默认权限合同。

`LLMConfig` 从 `pcm-demo/.env` 加载 `LLM_BASE_URL`、`LLM_API_KEY` 和 `LLM_MODEL`，同名进程环境变量优先。实际 `.env` 由 Git 忽略，配置对象的 `repr` 不包含字段值；`.env.example` 只保存公开占位说明。Claude Agent SDK 仍使用自身的 Anthropic 认证配置，两类模型配置不混用。

SDK 不自动读取 Demo 的 `.env`。配置模块必须在创建 Agent SDK 或 OpenAI-compatible 客户端前显式加载配置，且不得把密钥写入状态或日志。探针 C 运行时发现宿主环境配置了 SOCKS 代理，但当前 OpenAI SDK 环境没有 SOCKS 依赖；探针通过 SDK 的 `DefaultAsyncHttpxClient(trust_env=False)` 明确禁用环境代理，未修改宿主代理配置，也未增加无关依赖。

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

首轮 Demo 只承诺同一台机器、稳定工作区路径下的 session 恢复。探针 B 已使用三个独立 Python 进程验证：第一进程创建 session 并读取旧文件值，第二进程确定性修改文件，第三进程通过原 session ID 先在无工具 turn 中复述旧值，再恢复同一 session 并重新调用 `Read` 取得新值；三个阶段的 session ID 保持一致。跨机器、临时容器和正式共享存储不属于当前范围。

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

- `run_step.py`：运行一个已经实现的步骤；当前第 0、1 步的实际命令和配置说明以 `pcm-demo/README.md` 为准；
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
- `blocked`：缺少模型和当前环境无法取得的不可替代外部资源；
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

### 2. 第 1 步工作区发布合同

第 1 步使用 AI-compatible 模型从产品初稿提取严格 JSON：

```json
{
  "topic_name": "基于 Web 的社区物品维修预约与维修进度协作系统",
  "project_directory_name": "mendmark"
}
```

`topic_name` 必须明确表达当前产品选题。`project_directory_name` 必须是单段小写 kebab-case；初稿已经给出仓库名或英文代号时优先提取，未给出时允许模型根据选题生成，并把来源和生成理由写入提取证据。初稿无法确定产品选题、API、结构解析或有限重试耗尽时返回 `failed`，不能猜测字段。

产品工作区根目录的优先级为 CLI `--workspace-root`、进程环境 `PCM_WORKSPACE_ROOT`、`pcm-demo/.env` 中的同名配置，并且必须位于当前能力仓库之外，作为专门承载产品项目的独立父目录。模板仓库从进程环境或 `pcm-demo/.env` 的 `PCM_TEMPLATE_REPOSITORY` 读取，单次运行不能覆盖。最终项目路径为 `<root>/<project_directory_name>`，调用方不直接传入最终项目路径。第 1 步 AI-compatible 调用使用 Responses API 的 `instructions`、`input` 和 `text.format` strict JSON Schema；服务不支持 `/responses` 或该 Schema 时返回 `failed`，不回退到 Chat Completions。

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

步骤结果中的 `outputs` 统一记录相对于产品项目根 `state.workspace.final_path` 的非空相对路径；下游步骤必须以该根目录解析并核验，拒绝绝对路径、越出根目录的 `..` 路径和符号链接。第 1 步对下游公开的 `outputs` 为 `docs/产品初稿.md`；工作区根和发布副本的绝对路径仍分别保存在 `state.workspace.final_path` 与 `state.input.published_path` 中。根 `.git/` 是第 1 步建立的项目边界，不作为文档产物。第 1 步成功时 `state.json` 至少保存以下统一结构；完整命令结果放在步骤结果或脱敏日志中：

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
    "repository": "git@gitlab.com:baiyiyu/andrszan/pcm-agent-skills.git",
    "remote_url": "git@gitlab.com:baiyiyu/andrszan/pcm-agent-skills.git",
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

### 3. Agent SDK 运行结果

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
- `error_max_turns` 和 `error_max_budget_usd` 记录 session ID，供步骤恢复原 session 继续；即使 SDK 在产生该 ResultMessage 后又抛出异常，也以已取得的可恢复 subtype 为准，不把它误判为普通执行失败；
- `error_during_execution` 视为 SDK 执行错误；
- 单次 `query()` 在产生错误结果后仍可能抛异常，封装必须保留此前已经收到的 ResultMessage；
- 连接或子进程在 ResultMessage 之前失败时，session ID 可以为空；
- 收到 ResultMessage 后仍继续消费消息流至结束，避免漏掉尾随系统事件。

### 4. AI-compatible 决策结果

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
- `approve`：以原人工调度者的等效授权批准当前产物写入或定稿，满足 Skill 对“开发者明确同意”的确认要求；
- `continue`：要求原 session 根据已有事实继续完成尚未完成的同一步骤；
- `blocked`：缺少模型和当前环境无法取得的不可替代外部资源。

决策模型拥有原人工调度者在同等输入和工具条件下可完成的全部决策权。存在多个合理方案、资料歧义、重大取舍或不可逆设计决定时，模型应选择并记录理由，不因需要判断而返回 `blocked`。结构化响应解析失败时可以进行少量重试；持续失败则当前步骤返回 `failed`，不能猜测决策。

### 5. 命令结果

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

### 3. 项目配置与权限

正式步骤把项目 `.claude/settings.json` 作为权限和插件配置的权威来源。步骤代码不重复设置 `permission_mode`、`tools`、`allowed_tools` 或 `disallowed_tools`，不按文档、开发等步骤类型另建权限档位，也不默认禁止 Bash。这样人工 Claude Code 与 PCM SDK 运行使用同一套 `permissions.defaultMode`、`allow`、`ask`、`deny` 和插件配置。

能力探针可以为验证某个 SDK 行为显式覆盖权限，但覆盖只属于该探针。正式步骤若确需偏离项目配置，必须有该步骤独有且已确认的理由，并在合同中明确覆盖范围；不得把探针策略复用为通用限制。

步骤仍需从 init 消息记录实际工作目录、Skill、命令、插件、模型和可用工具，并以真实工具结果判断配置是否生效。项目 `deny` 规则仍按项目配置执行，PCM 不删除或绕过。

### 4. 两类会话保存与恢复

Claude Agent SDK 与 AI-compatible 决策模型使用不同的历史机制：

- 每个需要继续的领域步骤使用稳定键保存 Claude session ID，例如 `project_intake`、`REQ-003:development`；
- 第一次收到 init 或最终 ResultMessage 时更新 session ID；阻塞、turn 上限或预算上限发生时仍保存已取得的 session ID；
- `--resume` 重新读取 `state.json`、原工作区和当前步骤，再通过 `resume=<session-id>` 继续；恢复后先要求 Agent 重新核验相关文件和 Git 事实；
- 探针 B 已确认同一台机器上可由新进程使用原 session ID 恢复完整对话；恢复不会冻结文件内容，重新调用 `Read` 会得到工作区当前值；第 2 步使用默认 Claude Code 用户配置目录恢复 session 和插件状态；
- session 文件缺失或无法恢复时，不静默新建会话冒充恢复成功，当前步骤返回 `failed`；
- AI-compatible 接口不依赖服务端 conversation 或 response ID。PCM 按领域键把完整、脱敏的编排消息历史原子写入 `runs/<run-id>/conversations/<key>.json`，每次调用携带该历史；历史至少保留初始发给 Claude Agent SDK 的指令、每轮 Agent 的结果、决策模型收到的当前事实、完整结构化决策、转发给 Agent 的指令以及完成标记，确保恢复和审计时能够还原流程起点与每次取舍；
- 不同步骤和不同活动需求使用独立领域键，避免上下文污染；`state.json` 只保存历史文件引用和当前轮次，不复制完整消息；每一步的实际输入和产物交接从前一步 `steps/<step>.json` 的 `outputs` 读取并核验，不从固定路径猜测上一步结果；
- 完整编排历史只保存当前流程所需的脱敏内容，不保存密钥、完整环境变量或无关工具日志；首轮不建设数据库、向量记忆或摘要系统。

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

### 2. 自动决策权限与阻塞边界

AI-compatible 模型可以决定所有能够基于当前输入、项目事实、可用工具和已提供资源完成的事项，包括：

- 产品范围、业务规则、文档内容和组织方式；
- 技术方案、架构、安全、权限、兼容性和不可逆设计取舍；
- Agent 提出的澄清、确认、继续和定稿请求；
- 多个合理方案或相互冲突资料之间的选择；
- 非阻断建议是否纳入当前范围。

模型作出决定时记录选择及理由，不把“需要判断”当作 `blocked`。只有缺少模型和当前环境无法取得的不可替代外部资源时才返回 `blocked`，例如：

- 输入或资源清单之外的真实外部服务、账号、付费资源或凭据；
- 客户专属素材、私有数据或专用设备；
- 必须由外部人员完成的授权、审批或线下动作。

模型不得用 Mock、假凭据、虚构资源或降低验收标准来伪造资源已经具备。

### 3. 决策上下文与历史

发送给 AI-compatible 模型的每一轮消息包含当前决策所需的最小信息：

- 当前步骤及完成条件；
- 第 2 步的权威输入仅包括第 1 步发布的产品初稿、项目规则与配置、当前 `project-intake` 对话和该 Skill 已生成的产品定义产物；工作区中的技术方案、Backlog、TRD、代码和其它无关文档不作为本步骤决策输入，其存在也不构成阻塞；
- Agent 当前问题、建议和理由；
- 该领域历史中已经作出的决定；
- 当前可用资源清单；
- 当前文件、命令或 Git 的必要事实摘要。

PCM 在请求前读取该领域完整编排历史，保留此前的 Agent 指令、Agent 结果和已作出的决定，再追加当前 `user` 决策上下文；收到结构化响应后，将完整原始 JSON 作为 `assistant` 消息原子保存，并把其中的 `answer` 作为下一条用户指令发送给原 Claude session。`answer` 已经包含实际转发内容，不在同一历史消息中重复拼接一份 Agent 指令。不得只保存最后一个 `action`，也不得丢失初始任务和 Agent 当前问题；Agent 的完整流程消息可以作为交接记录保存，但发送给决策模型的本轮上下文仍只包含当前决策所需的最小事实，不发送无关 transcript。

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

1. 第一进程创建 session，让 Agent 使用 `Read` 获取随机旧值，并把 session ID 保存到工作区外的临时状态；
2. 第一进程结束后，第二进程确定性修改文件并记录新 SHA-256；
3. 第三进程使用原 session ID 恢复，在无工具的 turn 中复述旧值，证明前次对话可用；
4. 第三进程再次恢复同一 session，显式调用 `Read` 获取随机新值；
5. 三个进程 ID 互不相同，所有恢复结果的 session ID 与原值一致；
6. 新值、当前文件 SHA-256 和实际 `Read` 工具事件共同证明 session 恢复没有替代文件事实核验。

#### 探针 C：OpenAI-compatible 结构化决策

探针 C 已使用 `LLM_MODEL` 配置的真实 Responses API 服务验证：普通文档定稿一次返回 `approve`；需要真实支付账号与密钥的建议在一次结构化修复重试后返回 `blocked` 且包含解除条件；解析器另以一次人为非法 JSON 加一次合法 JSON 验证有限重试。上述本地注入只覆盖解析分支，不计作模型成功。该探针证明结构化决定和外部资源阻塞可用，不限制正式决策模型只能处理低影响事项。

验证：

1. 能读取 Demo 自己加载的配置；
2. 能返回符合约定的 JSON；
3. 无效 JSON 会被检测和有限重试；
4. 自动决策模型能够处理现有输入和工具可支持的全部取舍，只在模型和当前环境无法取得不可替代外部资源时返回 `blocked`；
5. 日志和状态中不出现 API Key。

#### 阶段 0 完成条件

- 三个探针均真实通过；
- 已记录实际 SDK 版本、模型和关键初始化事实；
- 已确认项目 Skill 的显式调用格式；
- 已确认探针可以通过程序化权限覆盖验证 SDK 的拒绝行为，且该覆盖不作为正式步骤配置；
- 已确认同机跨进程 session 恢复可行；
- 所有与本 TRD 不一致的实测结果已经先更新本文，再进入阶段 1。

### 阶段 1：最小骨架与第 0～2 步

#### 实现范围

- 步骤目录按业务自包含：已实现步骤的业务代码、测试和详细说明放在 `steps/step_xx_<name>/`；`common/` 只放两个及以上步骤真实复用的公共能力；
- 实现文件、状态、命令、AI-compatible 和 Agent SDK 公共封装；
- 实现统一步骤结果；
- 实现 `run_step.py` 和只覆盖第 0～2 步的 `run_all.py`；
- 实现第 0 步完整 PRD 无副作用跳过；
- 实现第 1 步项目身份提取、固定模板浅克隆、初始化清理、产品初稿写入、原子发布、根仓库 `git init -b main` 和安全恢复；
- 实现第 2 步 `project-intake` 多轮决策与 session 恢复；
- 验证能力仓库中的源 PRD 哈希不变。

#### 第 0 步完成条件

- 能判断黄金输入已经是完整产品初稿；
- 返回 `success` 且 `applicable: false`；
- 不创建或修改产品文档；
- 不修改源 PRD；
- 跳过依据写入步骤结果。

#### 第 1 步完成条件

- AI-compatible 模型从真实产品初稿取得明确的 `topic_name` 和合法的 `project_directory_name`；目录名为单段小写 kebab-case，提取或生成依据已记录；
- 实际产品工作区根目录按 `--workspace-root`、进程环境、Demo `.env` 的优先级解析并记录来源，且位于当前能力仓库之外；
- 固定模板仓库通过 `git clone --depth 1` 克隆到最终目录同级临时路径，实际默认分支、当前分支和 commit SHA 已记录；
- 最终项目路径为 `<root>/<project_directory_name>`，由临时目录在全部核验通过后原子重命名生成；
- 最终目录不含上游模板 Git 历史，模板关键能力仍存在，`docs/` 只包含 `产品初稿.md`；最终项目根已初始化为 `main` 分支的独立 Git 仓库且尚无 commit；
- `state.json` 记录源初稿绝对路径、完整内容和 SHA-256、项目属性、临时和最终路径、模板证据、根仓库路径/分支/空 HEAD、当前发布阶段及核验结果；
- 项目内 `docs/产品初稿.md` 与源初稿 SHA-256 一致，源初稿哈希保持不变；
- 重复执行、归属不明目录、残留临时 clone、clone 或 rename 中断不会导致覆盖或误报成功，并可按已确认事实安全续接或明确阻塞。

#### 第 2 步完成条件

- 目标 `project-intake` Skill 已从 init 消息确认加载；
- 第 2 步只使用产品初稿、项目规则与配置、当前 `project-intake` 对话和该 Skill 已生成的产品定义产物；技术方案、Backlog、TRD、代码及其它无关文档不进入决策上下文，其存在不构成阻塞；
- Agent 的问题和定稿确认经过完整决策循环处理；
- AI-compatible 决策模型的完整消息历史按领域键持久化，进程恢复后能够继续；
- 产品定义输出真实存在且可读取；
- SDK success、步骤完成判断和文件事实三者分别记录；
- 需要继续时可以恢复原 `project_intake` session；
- 只有模型和当前环境无法取得不可替代外部资源时返回 `blocked`，其余取舍由决策模型完成；
- 步骤代码未覆盖项目 `.claude/settings.json` 的权限和工具配置。

#### 阶段 1 完成条件

- 第 0、1、2 步均能单独运行；
- 第 0～2 步可以串联运行；
- 进程中断后可以从当前步骤继续；
- 步骤结果、状态、日志和工作区事实一致；
- 源 PRD 前后哈希一致；
- 没有以 Stub 或固定结果代替真实 Agent 与文件行为。

### 后续阶段边界

后续设计在进入对应阶段前增量补充：

1. **阶段 2：第 3～10 步**——初始化流程、项目工程、架构、UI/UX 框架和 Backlog；第 3 步先使用第 2 步产品定义、当前工程事实、`catalog.json` 和开发约束调用 `solution-design`，输出总体技术方案，并把经 Responses API 提取和程序校验的前后端模板选择写入 `steps/03.json.template_selection`；模板内容的获取和组装由第 4 步负责，且第 4 步只读取该稳定交接对象，不从技术方案或会话历史重新推断；其中第 7 步必须核验第 1 步已初始化且尚无 commit 的根仓库，不重复初始化根仓库，只为适用的 `frontend/`、`backend/` 建立各自 `main` 仓库，并在根 `.gitignore` 排除两者后分别完成三个仓库的首次本地提交；
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
- Claude session ID 和 AI-compatible 决策历史分别保存与恢复；
- 产品初稿身份提取、模板分支和 SHA 记录、固定模板浅克隆、同级临时目录、原子发布与根仓库零提交初始化；
- 上游 `.git/` 清理、`docs/` 重置、项目内初稿写入、最终根 `.git/` 初始化以及源文件不变；
- 第 1 步 clone、发布或根仓库初始化中断后的现场保留、归属核验和安全恢复；
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
- 第 1 步的项目身份结构化响应持续无效、产品初稿无法确定选题、工作区根位于当前能力仓库内部、工作区根配置无效、目录归属不明、恢复证据冲突、Git 工具或临时网络异常、模板 clone、清理、初稿写入、核验、原子 rename、根仓库初始化或证据持久化失败；
- 文件、状态或哈希操作失败；
- 步骤完成条件未满足且属于可修复实现错误。

### 返回 `blocked`

- 缺少模型和当前环境无法取得的不可替代账号、凭据、服务、付费资源、设备、素材、私有数据、授权、审批或线下动作，包括固定模板仓库所需的 SSH 凭据或读取权限。

输入不完整、状态证据冲突、目录归属不明或本地现场无法确定性继续属于 `failed`，保留现场并在修复后重试当前步骤。

产品、技术、架构、安全、权限、兼容性、不可逆设计和资料冲突本身不构成阻塞，由决策模型选择并记录理由。

### 恢复原则

- 恢复当前步骤，不直接跳到下一步；
- 重新读取状态、文件和 Git 事实；
- 原 session 可用时优先恢复；
- 已存在的局部产物先核验再继续，不自动删除或覆盖；
- 阻塞解除后重新执行当前步骤的完成条件检查。
- 第 1 步最终目录、发布证据和根仓库证据均匹配时确认既有成功；仅有归属明确且 clone 完整的临时目录时从最后可核验阶段续接；最终目录已发布但根 `.git/` 缺失时续接 `git init -b main`；根仓库已有 commit、临时和最终目录同时存在、归属不明或证据冲突时保留现场并返回 `failed`。

## 十、配置与敏感信息

首轮配置至少包含：

```text
LLM_BASE_URL=
LLM_API_KEY=
LLM_MODEL=
PCM_WORKSPACE_ROOT=
PCM_TEMPLATE_CATALOG=
PCM_TEMPLATE_REPOSITORY=
```

具体键名与现有环境统一，不同时支持没有真实需要的别名。`--workspace-root` 可以覆盖 `PCM_WORKSPACE_ROOT`；第 3 步的 `--catalog-path` 可以覆盖 `PCM_TEMPLATE_CATALOG`，两者实际采用的路径及其来源都必须写入运行状态。`PCM_TEMPLATE_REPOSITORY` 只用于第 1 步发布开发管理模板，与第 3 步的模板候选 catalog 分工独立。Claude Agent SDK 的模型和认证继续使用 SDK/Claude Code 自身支持的进程环境或既有登录态，不由 Demo `.env` 另设 `CLAUDE_MODEL`；实际 `.env` 必须 Git 忽略，`.env.example` 只保存键、公开默认值和安全占位说明。

日志不得记录：

- API Key、token、密码或完整认证头；
- `.env` 具体值；
- 含秘密的命令行和工具输入；
- 无助于恢复的完整模型上下文。

## 十一、当前未决事项

以下事项必须由探针或后续阶段事实解决，暂不在本 TRD 中假定答案：

1. 阶段 0 后续运行中 Agent SDK、捆绑 Claude Code 或模型版本发生变化时，需重新记录并复核探针结果；
2. 项目 Skill 的显式调用已由探针 A 确认为 `/project-intake <参数>`，其它 Skill 在进入对应步骤前按相同方式逐个验证；
3. 探针 A 已确认项目设置、其它 Skills、内建能力和插件会按实际设置源加载；正式步骤统一使用项目配置，不追求按步骤隔离这些能力；
4. 探针 A 的显式权限覆盖只用于验证 SDK 拒绝行为，不作为正式步骤合同；正式步骤不传权限和工具覆盖项；
5. 探针 B 已确认同机、稳定工作区路径下的跨进程 session 恢复；跨机器或工作区迁移仍不属于首轮范围；
6. 探针 C 已确认当前 OpenAI-compatible 服务支持约定 JSON 结构、普通决策和外部资源阻塞；模型或服务变化时需重新运行探针；
7. 第 2 步只在确定性文件检查后，把 Skill 运行产生的当前问题和最小必要事实交给决策模型，不增加独立 completion judge；步骤成功以 Agent 正常完成和 Skill 规定产物真实存在为准；
8. 第 3 步的 `catalog.json` 是必需输入，路径优先级、身份记录、Agent 自然语言选型汇报、Responses API 结构化裁决、Python 引用校验和 `steps/03.json.template_selection` 交接合同已经确认；第 4 步负责模板内容的获取与组装，尚未实现；
9. 后续开发步骤所需浏览器通道和外部审查能力。

这些事项不妨碍阶段 0 开始，但对应探针未通过前不得进入依赖它的业务步骤。每个新步骤实现前还必须先对照原手稿和当前流程设计，与开发者确认详细合同并同步本文；文档未一致前不得开始实现。
