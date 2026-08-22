# PCM 自动化流程 Demo 项目设计

> 本文定义正式 PCM 开发前的轻量 Python 验证项目。Demo 的目的不是提前实现正式 PCM，而是用可独立运行、可串联的一组脚本，真实验证 [`PCM 程序化调度的 AI Agent 产品开发流程`](../../.claude/PCM版AI%20Agent自动化流程设计.md)。
>
> 重构前，阶段 0 技术探针以及业务第 0～7 步已真实运行：第 3 步以 Pydantic `responses.parse` 完成基础工程选型，第 4 步以确定性 Git 和文件操作组装工程，第 5 步完成资源准备，第 6 步完成真实安装、构建、测试、启动、浏览器和最小联调，第 7 步生成固定总体技术方案，并已推进至第 8 步待讨论的“初始化并提交适用仓库”合同。本次第 2/5/6/7 步改接薄公共 Agent 决策循环后，隔离 run `agent-loop-step7-20260822T190149Z` 已以新的 `solution_design` session 真实验证公共循环的第 7 步：保留无 Result 环境错误并同 session 恢复、正常结果裁决、结构化格式重试、完成核验修复和状态推进均已通过；隔离副本未修改既有 `step01-mendmark`。该新证据只覆盖重构后第 7 步，不把旧 run 或未重跑步骤误记为新循环的真实证据。

## 一、验证目标

给定一份现有产品初稿，Demo 最终验证以下完整流程：

```text
产品初稿
→ 建立独立产品项目工作区
→ 产品定义
→ 基础工程选型
→ 基础工程组装
→ 项目准备核验
→ 基础工程项目化
→ 总体技术方案
→ 初始化并首次提交适用仓库
→ 按需建立工程架构和产品级 UI/UX 框架
→ 拆分 Backlog
→ 阶段一：逐需求设计、实现、验证、状态收尾、规则复盘和合并
→ 阶段二：全项目级集成产品体验审计、候选分流、需求化、修复回归和完整复审
→ 项目最终收口
```

最终命令形态：

```bash
python run_all.py \
  --product-draft "../docs/prd/修迹-产品需求文档-v1.md" \
  --workspace-root "/path/to/products"
```

完整流程正常运行时不需要人逐步调度。产品、技术、文档、流程和执行取舍由 AI-compatible 决策模型基于当前事实完成；只有缺少模型和当前环境无法取得的不可替代外部资源时，才保存进度并返回 `blocked`，待资源补齐后从原节点继续。

## 二、当前进度与变更边界

### 1. 已完成基线

当前已经完成：

- 阶段 0 三个技术探针：Claude Agent SDK 与项目能力加载、同机跨进程 session 恢复、OpenAI-compatible 结构化决策；
- 第 0 步：黄金输入已经是完整产品初稿时，无副作用跳过；
- 第 1 步：从固定开发管理模板发布独立产品项目工作区，并初始化零提交根 Git 仓库；
- 第 2 步：显式调用 `project-intake`，通过公共 `AgentDecision` 循环收敛产品定义，并保存 Claude session 与完整决策历史；
- 第 3 步：将产品定义和 catalog 构造成 Pydantic 输入，使用代码内 system prompt 调用 `responses.parse`，将 `output_parsed` 直接保存为稳定选型结果；
- 第 4 步：只读取第 3 步结果，以浅 clone、来源核验、临时 payload 和原子 rename 组装选中的模板目录，保存实际来源证据并推进到第 5 步；
- 第 5 步：显式调用 `project-readiness`，把第 2 步产品定义、最小选型投影、当前已组装工程和 `PCM_DEV_RESOURCE_LIST` 指向的可信开发资源交给 Agent；Agent 补齐被忽略配置、执行真实资源核验并生成准备清单；
- 第 6 步：显式调用 `project-bootstrap`，把产品定义、第 4 步实际组装工程和第 5 步准备清单交给 Agent；Agent 负责项目身份、基础配置、模板残留和真实工程验证，Python 核验目录与 Git 边界；
- 第 7 步：显式调用 `solution-design`，把产品定义、项目准备清单和实际适用工程交给 Agent；Agent 生成总体技术方案，Python 核验固定非空文档和前序交接；第 7 步回复及新 run 的决策输入保留完整原文于 Git 忽略的 run 目录；
- 第 2/5/6/7 步共用薄公共循环：每轮完整真实 Agent 回复均先进入 `AgentDecision(completed/continue/blocked)`，`completed` 后才由步骤程序核验。
- `run_step.py` 对第 0～7 步提供单步运行入口。

“已完成至第 7 步”不自动声明完整初始化阶段完成。当前代码接受第 0～7 步；第 8 步及以后仍明确返回“步骤尚未实现”。

### 2. 从第 3 步起的重大变化

旧设计把第 3 步定义为“总体技术方案兼基础模板选型”，并把单需求循环放在第 11～19 步。新版流程已经整体重排：

- 第 3 步只负责基础工程选型，直接调用 AI-compatible Responses API，不调用 `foundation-selection` Skill；
- 第 4～6 步依次完成基础工程组装、项目准备核验和基础工程项目化；
- 第 7 步才调用 `solution-design` 形成总体技术方案；
- 第 8 步初始化适用交付单元仓库，并为根仓库和各适用仓库创建首次本地提交；
- 第 9、10 步分别是按需工程架构和按需产品级 UI/UX 框架；
- 第 11 步拆分 Backlog；
- 阶段一单需求循环改为第 12～19 步；
- 所有当前正式需求完成后，不直接结束，而是进入新增的阶段二全项目级集成产品体验审计与修复闭环。

旧第 3 步的自然语言选型汇报、二次 Responses API 抽取、总体技术方案产物和相关实现均不沿用；新版第 3 步已经按 Pydantic `responses.parse` 重写。第 4～7 步已按各自确认合同实现；第 8 步及以后继续按新编号和职责逐步讨论，不根据旧实现做兼容性补丁。

### 3. 开发协作边界

“PCM 运行时自动决策”和“Demo 新步骤开发前确认合同”是两个不同层次：

- PCM 运行时不增加逐步人工审批；所有可由当前输入、事实、工具和资源完成的决策由 AI-compatible 模型处理；
- Demo 开发时，先对照原手稿、当前流程设计和活动 TRD，与开发者确认该步的输入、输出、前置条件、操作、完成条件及失败、阻塞和恢复边界；
- 合同确认后先实现代码并通过测试和真实验证，再将实际实现同步到设计文档并提交；
- 当前已完成到第 7 步；第 8 步及以后仍须在实现前确认合同，不提前实现能力。

## 三、明确不做

Demo 不建设：

- Web 管理界面；
- 数据库或正式状态存储；
- 工作流引擎或 DSL；
- 复杂状态机和外层步骤回退；
- 分布式队列、并发任务或多机调度；
- 多用户、多租户和多项目管理；
- 容器调度和正式安全隔离；
- 向量记忆、知识库或复杂上下文压缩；
- 通用多模型框架；
- 自动 push、部署或生产操作；
- 正式 PCM 的权限、审计、计费和运维体系；
- 为尚未实现的步骤提前创建空壳模块、抽象基类或通用插件框架。

Demo 只保留跑通完整流程必需的步骤代码、薄封装、JSON 状态、脱敏日志和真实验证证据。

## 四、黄金项目输入

第一轮端到端验收继续使用现有完整产品初稿：

```text
docs/prd/修迹-产品需求文档-v1.md
```

对应项目为“修迹 MendMark——基于 Web 的社区物品维修预约与维修进度协作系统”。该项目使用正常 PCM 流程，不使用专用步骤或硬编码结果。选择它是因为：

- PRD 已明确产品目标、用户角色、业务闭环、范围边界、数据要求和验收标准；
- 可以覆盖前端、后端、数据库和多个业务角色；
- 可以拆出多个有依赖关系的正式需求，验证阶段一循环；
- 问题描述引导卡、维修进度时间轴和维修档案册具有明确的 UI/UX 验证价值；
- 首版核心流程可以使用本地数据库、站内通知、样例图片和初始化数据完成；
- 首版不依赖真实支付、地图、物流、即时聊天或自动诊断服务；
- 可以通过本地测试、真实服务和浏览器完成阶段一验收及阶段二完整审计。

完整 Demo 默认只承诺实现 PRD 中“E.1 当前必须实现”的首版范围。“E.2 重要增强”和“E.3 未来扩展”不得自动进入首轮 Backlog，除非它们是完成 E.1 闭环不可缺少的条件。

修迹项目跑通后，可以换第二份符合 PCM 准入条件的 PRD 直接运行，用于发现脚本和提示词中的项目、品牌或文件名硬编码，但不属于第一轮完成条件。

## 五、项目位置与仓库边界

Demo 工具代码位于当前能力仓库：

```text
pcm-demo/
```

运行状态、步骤结果和日志位于被 Git 忽略的：

```text
pcm-demo/runs/<run-id>/
```

实际被开发的产品项目必须位于当前能力仓库之外：

```text
<PCM_WORKSPACE_ROOT>/<project_directory_name>/
```

边界规则：

- `PCM_WORKSPACE_ROOT` 是专门承载产品项目的独立父目录，不能是当前能力仓库或其内部目录；
- 第 1 步在最终目录同级使用 `<project_directory_name>.pcm-tmp-<run-id>` 临时 clone；
- 全部发布核验通过后原子发布到最终路径，再在最终项目根执行 `git init -b main`；
- 第 1 步只建立根仓库边界，不暂存、不提交、不 push；
- 第 8 步核验根仓库仍符合前置事实，为适用的独立交付单元建立仓库，并分别创建首次本地提交；
- 后续仓库遍历只使用第 8 步确认的 `applicable_repositories`，不固定假设 `frontend/`、`backend/` 一定都适用；
- Demo 不在当前能力仓库中执行产品项目的功能分支、代码合并或最终验收；
- 对产品工作区执行 clone、清理、删除、Git 或覆盖操作前，必须用当前 run 的状态和现场事实证明目标归属。

## 六、当前最小实现结构

截至第 7 步，已跟踪结构为：

```text
pcm-demo/
├── pyproject.toml
├── uv.lock
├── .env.example
├── .gitignore
├── README.md
├── config.py
├── common/
│   ├── agent_decision_loop.py
│   ├── claude_agent.py
│   ├── decision.py
│   ├── files.py
│   ├── openai_responses.py
│   └── state.py
├── probes/
│   ├── probe_a_agent.py
│   ├── probe_b_session.py
│   └── probe_c_decision.py
├── steps/
│   ├── step_00_product_draft/
│   ├── step_01_create_workspace/
│   ├── step_02_project_intake/
│   ├── step_03_foundation_selection/
│   ├── step_04_assemble_foundation/
│   ├── step_05_project_readiness/
│   ├── step_06_project_bootstrap/
│   └── step_07_solution_design/
└── run_step.py
```

后续原则：

- 已实现步骤的业务代码、测试和详细说明同置于 `steps/step_xx_<name>/`；
- `common/` 只放两个及以上步骤已经出现的真实复用能力；
- `run_all.py` 在需要串联多个已实现步骤时再建立，不为目录图提前创建；
- 阶段二使用具名节点，但不强行伪装成新的业务步骤编号；
- 目录可以按实际代码量合并，不为未来步骤创建空模块。

统一测试入口从 `pcm-demo/` 根递归发现公共循环和步骤测试：

```bash
uv run python -m unittest discover -s . -t . -p 'test*.py' -v
```

当前全量为 83 项，其中公共循环为 23 项。

## 七、执行架构与职责

```text
命令行入口
  ├── 步骤或节点调度
  ├── 状态、结果和脱敏日志
  ├── 确定性文件、命令和 Git 操作
  ├── AI-compatible 决策调用
  └── Claude Agent SDK 调用
          ├── 项目 CLAUDE.md / AGENTS.md
          ├── 项目 Skills 与 Subagents
          ├── 项目 settings 与 plugins
          ├── 文件、命令、服务和浏览器工具
          └── 本机 session 持久化
```

### 1. AI-compatible 决策模型

AI-compatible 模型代表原人工调度者，负责所有可基于当前输入、项目事实、工具和已提供资源完成的产品、技术、文档、流程与执行决策，包括回答、批准、继续、方案选择、候选分流和需求化取舍。

它不直接获得整个工作区和 Shell 权限。Python 编排器只提供当前决定所需的最小事实，并按领域键持久化完整编排历史。run 目录受 Git 忽略保护；Agent 仍不得主动披露秘密。只有不可替代外部资源缺失时才返回 `blocked`；输入、结构、状态或调用错误返回 `failed`。

第 1 步项目身份提取、AI-compatible 决策和第 3 步选型统一使用 OpenAI Python SDK `responses.parse`。每个调用将权威输入构造成 Pydantic 模型，将 Pydantic 输出类型传给 `text_format`，直接使用 `response.output_parsed`，不手写 JSON Schema、不解析原始 JSON 字符串。第 3 步使用代码内 system prompt，不调用 Skill 或 Claude Agent SDK。

### 2. Claude Agent SDK

Claude Agent SDK 负责在产品项目工作区中加载项目规则、Skills、plugins 和工具，修改文件、执行命令与验证，并返回 session 结果。

公共结果必须保留 SDK 原始终止语义，至少包括：

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

不能把 SDK 结果压缩为一个 `success: bool`。`ResultMessage.subtype == "success"` 只说明 Agent loop 正常结束，步骤是否成功仍由文件、Git、命令、测试、服务、浏览器和未决事项共同判断。

正式步骤继续遵循：

- `cwd` 指向产品项目根；
- 使用 `claude_code` system prompt preset；
- 设置有限 `max_turns` 和 `max_budget_usd`；
- 需要继续时恢复原 session；
- 不在步骤代码中重复覆盖 `permission_mode`、`tools`、`allowed_tools` 或 `disallowed_tools`；
- 项目 `.claude/settings.json` 和 Claude Code 默认加载语义是权限与工具配置的权威来源；
- 从 init 消息核验实际 cwd、模型、Skills、slash commands、plugins、工具和权限模式；
- 工作区文件与 Git 事实在恢复时重新读取，不能由 session 文字替代。

### 3. Python 编排器

Python 负责确定性操作和最终状态裁决：

- 解析配置和 CLI 优先级；
- 校验路径、JSON、哈希和 schema；
- 读写状态、步骤结果、审计结果引用和决策历史；
- 执行安全文件操作、Git、测试、构建、服务和浏览器命令；
- 保存 Claude session ID 和领域对话历史；
- 根据真实退出码、文件、仓库、服务和浏览器证据判断完成条件；
- 在任一节点返回 `blocked` 或 `failed` 时立即停止；
- 不根据 Agent 的口头结论补选模板、伪造文件、提交、测试或审计事实。

## 八、步骤与阶段地图

### 项目初始化与项目级设计：第 0～11 步

| 步骤 | 名称 | 核心职责 | 主要输出 |
| --- | --- | --- | --- |
| 0 | 形成产品初稿 | 简短选题时形成初稿；完整初稿无副作用跳过 | 产品初稿或跳过证据 |
| 1 | 建立项目工作区 | 固定模板浅克隆、清理、发布、根仓库零提交初始化 | 独立产品工作区、`docs/产品初稿.md` |
| 2 | 项目需求与产品定义 | 显式调用 `project-intake` 收敛最终产品范围 | 产品定义文档、session 与决策历史 |
| 3 | 基础工程选型 | 使用 Pydantic 输入输出和 `responses.parse` 从本次 catalog 选择适用模板 | `steps/03.json.template_selection` |
| 4 | 组装基础工程 | 只消费第 3 步稳定选型，确定性获取和组装模板 | 适用前后端基础工程 |
| 5 | 核验项目准备状态 | 调用 `project-readiness` 补齐可生成条件并核验资源 | 准备清单 |
| 6 | 项目化基础工程 | 调用 `project-bootstrap` 落实项目身份、配置和最小联调 | 可安装、构建、测试和启动的工程 |
| 7 | 总体技术方案 | 调用 `solution-design`，基于已组装并项目化的工程事实设计 | 总体技术方案 |
| 8 | 初始化并提交适用仓库 | 初始化适用交付单元仓库，分别创建首次本地提交 | `applicable_repositories` 与初始提交 |
| 9 | 工程架构设计（按需） | 在现有结构不足以指导实现时调用 `engineering-architecture` | 适用时形成工程架构文档并通过 `commit-changes` 提交根仓库；否则记录不适用证据 |
| 10 | 产品级 UI/UX 框架（按需） | 调用 `ui-ux-framework` 建立跨需求稳定体验框架 | 适用时形成 UI/UX 框架并通过 `commit-changes` 提交根仓库；否则记录不适用证据 |
| 11 | 拆分 Backlog | 调用 `requirement-breakdown` 覆盖最终产品范围 | Backlog 总览、详情卡、首条验证切片，并通过 `commit-changes` 提交根仓库后进入阶段一 |

第 3 步已经按以下边界实现并验证：

- 输入只包括第 2 步结果引用的两份产品定义和本次 `catalog.json`；
- Python 使用 Pydantic 模型读取产品资料、catalog 仓库和候选模板；
- system prompt 直接定义在步骤代码中，只描述基础工程选型任务，不包含步骤编号、PCM、Skill 或编排背景；
- 调用 OpenAI Python SDK `responses.parse`，以 `FoundationSelectionResult` 作为 `text_format`；
- 模型直接返回完整的前端和后端选择，包括 `id`、`git_url`、`default_branch`、`path` 和 `reason`，不适用的一端为 `null`；
- 程序直接保存 `response.output_parsed.model_dump()`，不手写 JSON Schema、不执行 `json.loads()` 或第二套字段校验；
- 本步骤不调用或修改 `foundation-selection` Skill，不创建 Claude session，不获取或组装模板；
- 第 4 步只读取 `steps/03.json`，以第 3 步 `FoundationSelectionResult` / `TemplateSelection` 校验交接；不读 catalog 或产品文档，不调用模型、Skill 或 Agent。

第 4 步固定映射 `frontend`、`backend` 目标，只接受不存在或严格唯一普通 `.gitkeep` 的真实目录；对唯一 `(git_url, default_branch)` 一次 shallow clone，核验 origin、branch、HEAD SHA，校验选中相对路径并拒绝模板树中的 `.git` 和任何符号链接，再复制到同级 run-owned 临时根。全部 payload 合格后才用 `os.rename()` 发布；`null` 端只删除严格占位目录。成功结果 `steps/04.json` 记录 `applicable`、`outputs` 和每端的选择、实际 origin/branch/commit SHA，状态推进至 `project:05_verify_readiness`、第 5 步。认证或读取权限缺失为 `blocked`，其它现场或操作错误为 `failed`；合法 marker 残留可在目标仍为占位或不存在时 fresh 重试，未知残留与部分发布不覆盖；成功现场最小复核后幂等复用而不 clone。

修迹真实验证使用 GitLab SSH 来源：前端 `vite-react-shadcn-spa` 的 `main` SHA 为 `a31db6deb85ab29f2d2253413dd362293a96325f`，后端 `fastapi-sqlalchemy-postgresql-async-api` 的 `main` SHA 为 `49ff842fcd330387f2fbdd1e9a43884e05894697`，均与 `ls-remote` 一致。两端完整、无嵌套 `.git` 和临时目录，根仓库仍零提交 `main`，源 PRD 和项目内初稿 SHA-256 均为 `d7d9b8054b226ef2abf730cfb29e59b30d5e39d68eb9121ded22a16750414fee`。首次 HTTPS 来源错误为 `failed`，目标未覆盖且临时现场保留；改为 SSH 后同 run 依据 marker 安全清理并成功，第二次执行 0.809 秒幂等复用。

第 5 步只确定性核验第 2、3、4 步交接、产品根 Git、组装现场和 `PCM_DEV_RESOURCE_LIST` 路径，再在产品项目根显式调用 `/project-readiness`。初始提示以 slash command 开始，正文只描述准备核验领域：两份产品定义是当前范围权威输入，实际工程和**最小选型投影**是技术事实（不传 `git_url`、`origin`），可信资源清单可由 Agent 原样读取；后续依赖安装、构建、测试、启动、独立 Git 初始化、业务实现和完整验收不作为当前准备阻塞。公共循环保存完整 Agent 原文并统一裁决，完成后才核验非空清单。

**重构前真实运行事实。** 修迹项目曾完成 PostgreSQL、MinIO 与本地配置准备，并在旧 session 语义下推进到第 6 步；该业务事实保留。旧历史中的固定完成声明和 `decision_turn` 属于旧协议，不是新循环会写入的状态。

第 6 步只从前序结果读取两份产品定义、第 4 步实际适用工程与白名单化组装来源、第 5 步准备清单；工程内部事实由 Agent 按现场读取。初始提示以 `/project-bootstrap` 开始，正文不包含步骤编号、PCM 节点或其它外层编排背景，也不向 Agent 或决策模型传递可能带凭据的 `git_url`、`origin`。Agent 负责有限项目化和真实工程验证；Python 只核验前序交接、根仓零提交 `main`、暂存区和嵌套 Git 边界。没有适用工程时的无副作用跳过保持不变。

**重构前真实运行事实。** 修迹项目曾完成前后端项目化、安装、检查、测试、构建、真实启动、浏览器检查和基础联调，并推进到第 7 步；根 README 收口、根仓零提交、无 staged、适用工程无 `.git` 均为历史交付证据。旧专属裁决、格式重试和连接恢复的叙述不代表本次公共循环已被真实新 session 验证。

修迹真实项目化将产品根 README 收口为 MendMark 项目总说明，将前端收口为 `mendmark-web`、后端收口为 `mendmark-api`，同步公开配置、基础页面、健康检查与模板测试，保留有效基础设施并未实现业务功能。前端 `pnpm install --frozen-lockfile`、lint、type-check、10 项测试、build 和 1 项 Playwright E2E 通过；后端锁定、`uv sync --locked`、Ruff、15 项含 PostgreSQL `SELECT 1` 的测试和 `uv build` 通过；真实 Uvicorn/Vite、`/health`、`/ready`、OpenAPI、浏览器健康联调、375px 窄视口、控制台和网络检查通过。临时服务已停止，实际 `.env` 仍被忽略且权限为 `600`，根仓仍为零提交 `main`、无 staged，前后端无 `.git`。状态推进到 `project:07_solution_design`，成功复用耗时约 1 秒且不再调用 Agent。

第 7 步只从前序结果读取两份产品定义、第 5 步项目准备清单、第 4 步实际适用工程和白名单组装来源，以及第 6 步成功结果；工程内部事实由 Agent 按需读取，**不要求全仓扫描**。初始提示以 `/solution-design` 开始，只授权创建或更新 `docs/design/技术方案.md`，不包含步骤编号、PCM 节点或其它编排背景，不传递 `git_url` 或 `origin`。Agent 不重新选型、组装模板、实现业务、修改业务代码或执行 Git 写操作。新 run 的完整回复、pending 文本与决策输入保留原文于 Git 忽略目录；仍禁止 Agent 主动披露秘密。

公共循环使第 2/5/6/7 步共享 `AgentDecision(completed/continue/blocked)`、对话尾部恢复与 SDK 错误边界：`completed` 后才执行步骤核验，若固定产物可安全补完则追加普通修复提示并继续同一 session，否则失败；`continue` 留在内部，`blocked` 或失败终止。`error_max_turns` / `error_max_budget_usd` 有 session 与非空回复时可裁决，但必须在正常 `success` 后才可最终完成；400/429/500、连接/CLI/进程、无 Result、`terminal_reason` 为 `aborted_streaming`/`aborted_tools`，以及 `success` 下未知终止原因均在裁决前失败，且无外层自定义 HTTP 重试。旧 `action` 非 `blocked` 映射为 `continue`；若旧 `answer` 为空则使用固定安全兼容 continue 提示，绝不将旧控制 JSON 转发给 Agent。

**重构后第 7 步隔离真实验证。** 新 run `agent-loop-step7-20260822T190149Z` 在外部复制工作区运行，未修改既有 `step01-mendmark`；session `e8000375-2698-4ccf-9927-ccb9ca627ca2` 的 init 确认 cwd、`solution-design` Skill、slash command 和 Fable 模型。首次 Agent 尝试内置 Explore 子代理时发生环境内部未识别模型并超时，未返回 ResultMessage；循环保存 session 与初始 conversation、未推进成功。仅在隔离验证历史中追加普通 assistant 的“不使用子代理、直接工具完成”提示后，从同一 session 恢复。该测试提示不进入生产 prompt，环境内部子代理错误也不是公共循环缺陷。

恢复后 Agent 正常 `success`（44 turns，约 `$3.800742`），生成约 44 KB 技术方案。AI-compatible 服务对同一真实回复首返 YAML 风格结构，当时唯一格式重试提示要求花括号、双引号并禁止 YAML，第二次返回严格 JSON `completed`。测试包装器只在隔离副本首次 completed 后将技术方案置空，verifier 返回固定 `DESIGN_REPAIR_PROMPT`；公共循环保留真实 completed JSON、追加普通 assistant repair 提示、恢复同一已保存 session，Agent 补回非空文档，第二次真实裁决再次 `completed`。最终 `steps/07.json` 为 `success`，状态为 `project:08_initialize_repositories`，conversation 尾部为 `completed`，无旧 completion sentinel 或 `pending_agent_prompt`。公共循环 23 项、第 2/5/6/7 步 6/8/5/5 项、全量 83 项测试已通过。

Probe C 的早期成功证据为 `probe-c-20260822T185623Z`：普通 `continue`（attempts=2）、外部支付 `blocked`（attempts=1）；后续最终验证连续两次失败：普通决定在唯一重试后仍返回带“验证：”前缀的非 JSON `ValidationError`，以及普通成功后 boundary 返回 Responses `status=incomplete`；代码均按合同 `failed`，未增加第三次重试或手写解析。随后 `common/decision.py` 使首次请求与唯一格式重试都附加相同的严格 JSON、首尾花括号、双引号、禁止 YAML 约束，步骤 system prompt 保持只负责领域条件。更新后真实复跑 `probe-c-20260822T200038Z` 通过：ordinary `continue`（attempts=1）、boundary `blocked`（attempts=1）。该前置约束后的单次成功确认能力可用，但不消除服务格式/完成状态波动，重复稳定性仍是验证缺口。

### 阶段一：第 12～19 步逐需求开发

阶段一处理当前已知正式 Backlog。每个需求使用相同循环：

| 步骤 | 名称 | 核心职责 |
| --- | --- | --- |
| 12 | 选择需求并建立根仓库需求分支 | 从根仓库最新 `main` 选择依赖满足的需求，建立唯一活动根分支 |
| 13 | 形成最终活动 TRD | 调用 `trd-design` 收敛范围、行为、技术方案、验证和需求级体验设计，并提交根需求分支 |
| 14 | 建立代码仓库需求分支 | 只为受影响的适用代码仓库从最新 `main` 建分支 |
| 15 | 实现与验证 | 调用 `dev-workflow`，完成实现、测试、构建、运行、联调、浏览器验收和独立审查，并按仓库精确提交 |
| 16 | 合并代码仓库并在 `main` 最终验证 | 合并受影响代码仓库，重新执行相关验证 |
| 17 | 同步需求最终状态并提交根需求分支 | 基于真实代码和验证结果更新活动 TRD、Backlog 和详情卡 |
| 18 | 在原开发 session 复盘执行规则 | 调用 `session-rule-retrospective`，只允许修改根仓库 `.claude/rules/`，记录 `no_change` 或精确提交 |
| 19 | 最后合并根仓库并检查适用仓库 | 将根需求分支最后合并到 `main`，核验所有适用仓库分支、提交和工作树 |

阶段一约束：

- 不在单需求、单页面、首条验证切片或局部 UI 改动后调用 `product-experience-audit`；
- `trd-design` 与 `dev-workflow` 共同完成需求级体验设计、真实运行和验收；
- 当前步骤发现可修正问题时在本步骤内部修正并重新核验，外层编号不回退；
- `commit-changes` 是唯一负责精确暂存和本地提交的 Skill；建分支、切换和合并由显式 Git 脚本执行；
- 当前正式范围内全部需求完成第 19 步后，才进入阶段二。

### 阶段二：全项目级集成产品体验审计与迭代

阶段二不新增业务步骤编号，使用具名节点表达完整审计闭环：

```text
phase_2:audit
→ phase_2:route_candidates
→ phase_2:resolve_coverage_gaps
→ phase_2:pool_requirements
→ 对入池需求复用第 12～19 步
→ phase_2:regress_and_reaudit
→ 完整复审，直到满足阶段二完成条件
```

阶段二入口：

- 当前正式范围内全部需求已经完成第 12～19 步；
- 根仓库和所有 `applicable_repositories` 均处于清楚的 `main` 事实；
- 产品能够作为完整集成版本真实运行；
- 主要任务所需环境、角色、可复位数据、浏览器和安全边界已经具备，或能够在当前节点补齐。

完整审计：

- 外层在独立 Claude Agent SDK session 中显式调用一次 `product-experience-audit`；
- 以所有适用仓库 `main` commit SHA 共同形成 `version_fingerprint`；
- 覆盖当前正式范围内全部主要用户任务、角色、跨页面闭环和多个产品表面或模块；
- 使用真实开发或测试服务、真实浏览器、代表性桌面与窄屏、适用辅助技术路径和实际读取的截图；
- 审计 Skill 只返回经核验候选、重复或未纳入项、覆盖缺口和高影响边界；
- 审计 Skill 不修改代码、产品定义、TRD 或 canonical Backlog，不创建正式 ID，不暂存、提交或自动串联开发能力。

候选分流与入池：

- 外层基于审计证据、已有 Backlog 和产品事实逐项分流；
- 已有需求、共同用户障碍或共同根因已有归属时不重复建项；
- 误判、纯偏好或价值不足的候选记录不纳入理由；
- 证据不足或覆盖缺口先补齐动态证据，不直接写入 Backlog；
- 合格候选才需求化；需要合并、拆分、排序或重算依赖时显式调用 `requirement-breakdown`，需要更新权威产品定义时显式调用 `project-intake`；
- 正式候选通过根仓库最新 `main` 上的短期入池分支写入 Backlog，精确提交并合并回 `main`；
- 入池只创建可选择的正式需求，不提前创建活动 TRD、代码分支或完成状态。

修复与复审：

- 每个入池需求从根仓库最新 `main` 完整复用第 12～19 步；
- 每个修复完成后重走原复现任务、受影响状态和相邻路径，保存针对原发现的体验回归证据；
- 修复使 `version_fingerprint` 变化后，开启新的独立完整审计轮；
- 最后一轮完整复审没有新增符合需求化政策的候选、未处理高信心阻断或高优先级问题，且主要任务覆盖缺口已经关闭，阶段二才成功。

## 九、状态、结果与恢复

### 1. 三态结果

每个步骤或阶段二节点对外只返回：

- `success`：完成条件满足，或确认不适用且无副作用跳过；
- `blocked`：缺少模型和当前环境无法取得的不可替代外部资源；
- `failed`：输入、程序、SDK、模型、命令、Git、解析、文件、验证或状态发生错误。

步骤结果保存当前步骤的业务结果；阶段和下一节点保存在运行状态中。第 3 步成功结果示例：

```json
{
  "step": 3,
  "name": "基础工程选型",
  "status": "success",
  "summary": "基础工程模板选择已完成。",
  "applicable": true,
  "outputs": [],
  "blocked": null,
  "error": null,
  "template_selection": {
    "frontend": {},
    "backend": {}
  }
}
```

不适用时仍返回 `success`，并记录 `applicable: false` 和跳过依据。审计内容中的“部分完成”“覆盖缺口”不成为第四种外层状态。

### 2. 状态演进

第 0～2 步继续使用 `current_step`。第 3 步成功时在状态中同时写入 `phase: project_initialization`、`current_node: project:04_assemble_foundation`、`step: 4` 和兼容字段 `current_step: 4`。阶段一循环和阶段二具名节点所需的完整恢复协议仍在进入对应阶段时增量实现：

- `applicable_repositories` 和各仓库当前事实；
- 阶段一 `requirement_cycle`，包括根需求分支、开发 session、第 17～19 步提交与合并证据；
- 阶段二 `phase_two`，包括审计版本指纹、独立 session、审计结果、候选分流和入池证据；
- 阶段二修复需求的 `return_node_after_completion`，确保第 19 步后返回 `phase_2:regress_and_reaudit`，而不是阶段一普通需求选择。

状态只保存支持恢复所需的当前事实和引用，不复制完整历史事件。工作区文件和 Git 仓库仍是实际交付事实；Claude session 保存 Agent 对话；`conversations/` 保存 AI-compatible 完整编排历史。第 2/5/6/7 步的恢复核心是 session、`{path}` 引用、最后 Agent 终止摘要和短暂 `pending_agent_text`，不再新写 `pending_agent_prompt`、决策轮次或 Python 完成声明。

### 3. 恢复原则

- 每个节点开始前保存当前 `phase/current_node` 和已核验输入；成功后原子保存输出、证据和下一节点；
- `blocked` 或 `failed` 时立即停止，不继续后续节点；
- `--resume <run-id>` 只恢复当前节点，先重新核验文件、分支、提交、工作树、服务和外部条件；
- 原 Claude session 可用时优先恢复，session 缺失或不一致时不得静默新建会话冒充恢复；
- 已存在产物先核验再继续，不自动删除、覆盖或重复入池；
- 相同且工作树清楚的阶段二 `version_fingerprint` 不重复制造审计候选；
- 阶段二修复期间临时复用需求循环，完成后必须返回原阶段二节点；
- 任何归属、分支、提交、合并、候选或入池证据冲突均保留现场并返回 `failed`。

## 十、配置与敏感信息

`.env.example` 继续维护最小配置：

```text
LLM_BASE_URL=
LLM_API_KEY=
LLM_MODEL=
PCM_WORKSPACE_ROOT=
PCM_TEMPLATE_CATALOG=
PCM_TEMPLATE_REPOSITORY=
PCM_DEV_RESOURCE_LIST=
```

职责分工：

- `LLM_*`：AI-compatible Responses API；
- `PCM_WORKSPACE_ROOT`：所有产品项目的独立父目录；
- `PCM_TEMPLATE_REPOSITORY`：第 1 步发布开发管理模板；
- `PCM_TEMPLATE_CATALOG`：第 3 步基础工程候选目录；
- `PCM_DEV_RESOURCE_LIST`：第 5 步可信开发资源清单的绝对路径；Python 只核验路径并交给 Agent，不解析资源内容；完整 Agent/决策交互保存在被 Git 忽略的 run 历史中；
- Claude Agent SDK 的模型和认证继续使用 SDK/Claude Code 自身支持的环境或既有登录态，不与 `LLM_*` 混用。

优先级：

- 工作区根：CLI `--workspace-root`、进程环境、`pcm-demo/.env`；
- catalog：CLI `--catalog-path`、进程环境、`pcm-demo/.env`；
- `PCM_DEV_RESOURCE_LIST`：进程环境、`pcm-demo/.env`；必须是可读普通文件的绝对路径，不提供单次 CLI 覆盖；
- `PCM_TEMPLATE_REPOSITORY` 单次运行不可覆盖。

安全规则：

- 实际 `.env` 保持 Git 忽略；
- `.env.example` 只保存键、公开默认值和安全占位；
- 日志、状态、提交和回复不展示 API Key、token、密码、完整认证头或 `.env` 具体值；
- 不伪造外部账号、凭据、授权、服务、设备或客户数据；
- 默认只操作本地文件、本地服务和本地 Git，不 push、不部署、不操作生产环境。

## 十一、运行方式

当前已实现单步入口：

```bash
uv run python run_step.py --step 7 --run-id <run-id>
```

目标运行入口在对应能力实现后逐步补齐：

```bash
# 从产品初稿完整运行
python run_all.py \
  --product-draft "../docs/prd/修迹-产品需求文档-v1.md" \
  --workspace-root "/path/to/products"

# 从阻塞或失败节点恢复
python run_all.py --resume <run-id>

# 调试业务步骤区间
python run_all.py --run-id <run-id> --from-step 3 --to-step 7

# 调试阶段二具名节点
python run_all.py --run-id <run-id> --from-node phase_2:audit
```

单步、区间、完整运行和恢复必须复用相同节点函数，不维护两套流程语义。

## 十二、后续实现顺序

1. 保持第 0～7 步已确认的业务边界不变；
2. 公共循环 23 项以及第 2/5/6/7 步 6/8/5/5 项、全量 83 项自动化测试已通过；隔离新 session 已真实验证第 7 步的错误保留、同 session 恢复、格式重试、completed 后 repair 和成功推进，后续仅在需要第 2/5/6 步独立新 session 证据时再补记；
3. 下一次先讨论第 8 步初始化并提交适用仓库合同；
4. 合同确认后先实现代码并通过测试和真实验证，再同步设计文档并提交；
5. 不提前实现第 8～19 步或阶段二空壳；
6. 每个阶段只根据真实运行发现补充最小公共能力；
7. 阶段一先完整跑通一个正式需求，再验证至少第二个真实需求；
8. 阶段二先在完整集成版本上跑通一次审计、分流、入池、修复回归和完整复审；
9. 最后使用《修迹》产品初稿执行完整端到端运行，并确认源初稿哈希未变化。

## 十三、完成标准

Demo 完成需要同时满足：

1. 第 0～19 步以及阶段二必需节点均已实现，并可由统一入口单独或串联运行；
2. 每个步骤至少真实成功验证一次，或明确证明在修迹项目中不适用；
3. 第 0 步已验证完整初稿的无副作用跳过；
4. 第 1 步真实完成项目身份提取、固定模板浅克隆、模板证据记录、上游 `.git/` 清除、`docs/产品初稿.md` 写入、原子发布和零提交根仓库初始化；
5. AI-compatible 模型能够完成流程所需语义决策，只在不可替代外部资源缺失时阻塞；
6. Claude Agent SDK 能在指定项目工作区加载目标 Skills、plugins 和项目配置，修改文件、执行验证并恢复原 session；
7. 每一步的真实输出由下一步从步骤结果中读取和核验，不从固定路径或历史文字猜测；
8. 第 3～11 步按新版顺序完成，且 `applicable_repositories` 成为后续仓库遍历的单一事实源；
9. 当前正式范围内全部需求完成阶段一第 12～19 步；黄金项目至少有两个真实正式需求经过该循环，除非最终产品范围事实证明只有一个内聚需求，不能为满足数量伪造拆分；
10. 实现、测试、构建、启动、联调、浏览器验收和独立审查使用真实项目与真实工具，不以 Stub 或模型口头结论替代；
11. 阶段二完整覆盖全部主要任务和多个产品表面，保存实际读取的代表性截图和相称动态证据；
12. 阶段二所有候选完成分流，所有入池需求完成第 12～19 步并通过原发现回归；
13. 最后一轮完整复审没有新增符合需求化政策的候选、未处理高信心阻断或高优先级问题，主要任务覆盖缺口已经关闭；
14. 至少验证一次 `blocked` 解除后的 `--resume`，以及一次进程失败后的原节点恢复；
15. 根仓库和所有 `applicable_repositories` 最终位于预期 `main`，提交、合并和工作树事实清楚；
16. 适用的最终安装、构建、测试、启动、真实联调和浏览器验收通过；
17. 当前能力仓库中的黄金源 PRD 前后 SHA-256 不变，产品项目内初稿与源初稿哈希一致；
18. 输出简短 Demo 结论，记录可行能力、失败点、成本、耗时、阻塞类型和正式 PCM 的设计输入。

## 十四、Demo 结论应回答的问题

完整运行后至少回答：

- Claude Agent SDK 加载当前项目能力是否稳定；
- Skills 在程序化调用下与人工会话有何差异；
- 哪些节点最需要 AI 决策，哪些应保持确定性脚本；
- 跨步骤、需求循环和阶段二需要保存哪些最小状态；
- Claude session 和 AI-compatible 决策历史能否分别可靠恢复；
- `phase/current_node` 是否足以表达业务步骤和阶段二具名节点；
- 多仓库分支、提交、合并和版本指纹是否可以可靠自动化；
- 真实浏览器、测试身份、可复位数据和安全边界能否支撑完整产品审计；
- 审计候选分流、需求化、入池、回归和完整复审是否能够避免重复项和无穷循环；
- 哪些外部资源会成为真实阻塞；
- 一次完整项目开发的模型成本和运行时间；
- 正式 PCM 最优先需要重新设计的模块是什么。

这些真实结论是 Demo 的主要价值，不要求 Demo 代码直接演进为正式 PCM。