# PCM 自动化流程 Demo 项目设计

> 本文定义正式 PCM 开发前的轻量 Python 验证项目。Demo 的目的不是提前实现正式 PCM，而是用可独立运行、可串联的一组脚本，真实验证 [`PCM 程序化调度的 AI Agent 产品开发流程`](../../.claude/PCM版AI%20Agent自动化流程设计.md)。
>
> 重构前，阶段 0 技术探针以及业务第 0～7 步已真实运行：第 3 步以 Pydantic `responses.parse` 完成基础工程选型，第 4 步以确定性 Git 和文件操作组装工程，第 5 步完成资源准备，第 6 步完成真实安装、构建、测试、启动、浏览器和最小联调，第 7 步生成固定总体技术方案。第 2/5/6/7 步改接薄公共 Agent 决策循环后，隔离 run `agent-loop-step7-20260822T190149Z` 以新 `solution_design` session 真实验证第 7 步；该新证据不把旧 run 或未重跑步骤误记为公共循环的真实证据。第 8 步现已按“首次全仓提交检查与干净基线”合同实现并通过真实验证。第 9 步代码、自动化和 fresh 真实运行也已完成：最终生成并提交固定工程架构文档，独立核验与幂等重跑通过，state 已推进到第 10 步。旧 403、非 JSON、非法 completed 和旧 prompt 设计只保留为已修复的根因历史。`step08-real-20260823-a/b` 的 prompt、API、`.coverage`、授权循环和提交事实继续仅属于旧“唯一初始提交证明”合同的历史运行。

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
→ 必要的工程架构设计
→ 按需建立产品级 UI/UX 框架
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
- 第 4 步：只读取第 3 步结果，以浅 clone、来源核验、run-owned 临时 payload、拒绝上游 `.git`/符号链接、对每个适用 payload 执行 `git init -b main` 并核验自身 top-level、`main`、unborn HEAD、空 index、至少一个不被自身 ignore 的可提交文件后原子 `os.rename` 组装工程，保存实际来源和 Git 边界证据并推进到第 5 步；
- 第 5～7 步：接受上述适用子仓边界，持续在 `completed` 和 `blocked` 终止前复核 `main` / unborn / 空 index；只有 `status=success` 的结果可幂等复用，`failed` / `blocked` 结果不会阻断恢复；
- 第 8 步：先以 `['root', *steps/04.json.outputs]` 作为唯一权威仓库清单，只读核验每仓自身 top-level、`main` 和工作树；全部干净时零 Agent、零决策调用直接形成干净基线，存在未提交变更时才在一个产品根 Claude Agent SDK session 中显式调用 `commit-changes`，Python 不执行 Git 写操作，保存 `applicable_repositories` 和仓库干净事实；
- 第 2/5/6/7/8/9 步共用薄公共循环：每轮完整真实 Agent 回复均先进入负责人返回的 `AgentDecision(completed/continue/blocked)`，负责人相信 `completed` 后仍由步骤程序核验；新 conversation 保存动态 system snapshot，第 8、9 步的 Git 合同不进入公共循环；
- 第 9 步：必要的工程架构步骤，固定读取第 2 步两份产品定义、第 5 步准备清单、第 7 步总体技术方案和第 8 步权威仓库 clean 交接，在单一 `engineering_architecture` session 中生成固定 `docs/design/工程架构设计.md`，再由 completion verifier 在同 session 固定调用一次 `/commit-changes`；即使文档无变化也调用，Python 只读 Git；
- `run_step.py` 对第 0～9 步提供单步运行入口；只对 schema 完整的第 8、9 步 success 保护既有 result 和已推进 state，后续重跑失败不覆盖 success、不回退节点，残缺 success 不保护，其它步骤保持原行为。

当前代码已实现并真实成功验证第 0～9 步。第 9 步最终 `steps/09.json` 和 state 均为 success，固定工程架构文档已 tracked，root/frontend/backend 为各自自身 top-level、`main`、clean，状态推进到 `project:10_ui_ux_framework`。第 10 步及以后仍未实现，当前进入按需 UI/UX 框架的合同讨论。

### 2. 从第 3 步起的重大变化

旧设计把第 3 步定义为“总体技术方案兼基础模板选型”，并把单需求循环放在第 11～19 步。新版流程已经整体重排：

- 第 3 步只负责基础工程选型，直接调用 AI-compatible Responses API，不调用 `foundation-selection` Skill；
- 第 4～6 步依次完成基础工程组装、项目准备核验和基础工程项目化；
- 第 7 步才调用 `solution-design` 形成总体技术方案；
- 第 8 步是根仓及适用仓的首次全仓提交检查与干净基线节点：仅根仓和成功 `steps/04.json.outputs` 是权威仓库；Python 只读核验，已全干净时不调用 Agent，存在未提交变更时由一个 `commit-changes` session 负责必要提交；Python 不初始化子仓、暂存或提交；
- 第 9 步是必要工程架构步骤，固定产物完成后在同一 session 固定调用一次 `commit-changes` 核验；第 10 步仍是按需产品级 UI/UX 框架；
- 第 11 步拆分 Backlog；
- 阶段一单需求循环改为第 12～19 步；
- 所有当前正式需求完成后，不直接结束，而是进入新增的阶段二全项目级集成产品体验审计与修复闭环。

旧第 3 步的自然语言选型汇报、二次 Responses API 抽取、总体技术方案产物和相关实现均不沿用；新版第 3 步已经按 Pydantic `responses.parse` 重写。第 4～9 步已按各自确认合同实现并真实验证；第 10 步及以后继续按新编号和职责逐步讨论，不根据旧实现做兼容性补丁。

### 3. 开发协作边界

“PCM 运行时自动决策”和“Demo 新步骤开发前确认合同”是两个不同层次：

- PCM 运行时不增加逐步人工审批；所有可由当前输入、事实、工具和资源完成的决策由 AI-compatible 模型处理；
- Demo 开发时，先对照原手稿、当前流程设计和活动 TRD，与开发者确认该步的输入、输出、前置条件、操作、完成条件及失败、阻塞和恢复边界；
- 合同确认后先实现代码并通过测试和真实验证，再将实际实现同步到设计文档并提交；
- 当前已实现并真实成功验证到第 9 步；第 10 步及以后仍须在实现前确认合同，不提前实现能力。

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

Demo 只保留跑通完整流程必需的步骤代码、薄封装、JSON 状态和真实验证证据。

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
- 第 4 步在 run-owned 临时 payload 中拒绝上游 `.git` 和符号链接，并只为适用端建立独立 `main` / unborn / 空 index Git 边界后原子发布；第 4 步不暂存、提交或 push；
- 第 8 步只读取已建立的根仓和适用子仓并形成干净基线，不初始化子仓；后续仓库遍历只使用其确认的 `applicable_repositories`，不固定假设 `frontend/`、`backend/` 一定都适用；
- Demo 不在当前能力仓库中执行产品项目的功能分支、代码合并或最终验收；
- 对产品工作区执行 clone、清理、删除、Git 或覆盖操作前，必须用当前 run 的状态和现场事实证明目标归属。

## 六、当前最小实现结构

截至第 9 步代码实现，已跟踪结构为：

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
│   ├── step_07_solution_design/
│   ├── step_08_initialize_repositories/
│   └── step_09_engineering_architecture/
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

本轮实际验证为第 9 步专属 29 项、公共循环 24 项、第 7 步 8 项、第 8 步 17 项，相关定向 78 项及全量 141 项 `unittest` 通过，`compileall` 与 `git diff --check` 通过；IDE 对第 9 步无诊断。本轮文档更新后的最终审查由主代理执行。

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

AI-compatible 模型是实际使用 Claude Code Agent 的项目负责人、工程负责人和 Agent 专家，负责所有可基于当前输入、项目事实、工具和已提供资源完成的产品、技术、文档、流程与执行决策，包括回答、批准、继续、方案选择、候选分流和需求化取舍。它读取完整 conversation：`assistant` 是负责人发给 Agent 的初始、继续或修复指令，或负责人每轮返回的 `AgentDecision` JSON；`user` 是 Agent 完整真实回复。

它不直接获得整个工作区和 Shell 权限。Python 编排器只提供当前决定所需的最小事实，并按领域键持久化完整编排历史。run 目录受 Git 忽略保护；Agent 仍不得主动披露秘密。只有不可替代外部资源缺失时才返回 `blocked`；输入、结构、状态或调用错误返回 `failed`。

第 1 步项目身份提取、AI-compatible 决策和第 3 步选型统一使用 OpenAI Python SDK `responses.parse`。每个调用将权威输入构造成 Pydantic 模型，将 Pydantic 输出类型传给 `text_format`，直接使用 `response.output_parsed`，不手写 JSON Schema、不解析原始 JSON 字符串。第 1、3 步 prompt 均要求严格 JSON 且禁止代码围栏；第 1 步还明确只允许 `topic_name`、`project_directory_name`、`directory_name_source`、`reason`、`blocked_reason` 五个字段。该约束来自真实服务先后返回代码围栏、`incomplete` 和自创字段的失败；修正后同 run 的第 1 步成功。第 3 步首次 `ValidationError` 后同 run 重试成功，未增加宽松解析或额外模型重试。第 3 步使用代码内 system prompt，不调用 Skill 或 Claude Agent SDK。

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
| 4 | 组装基础工程 | 在 run-owned payload 中拒绝上游 `.git`/符号链接，建立适用子仓 `main` / unborn / 空 index 边界后原子发布 | 适用前后端独立基础工程仓 |
| 5 | 核验项目准备状态 | 调用 `project-readiness` 补齐可生成条件并核验资源 | 准备清单 |
| 6 | 项目化基础工程 | 调用 `project-bootstrap` 落实项目身份、配置和最小联调 | 可安装、构建、测试和启动的工程 |
| 7 | 总体技术方案 | 调用 `solution-design`，基于已组装并项目化的工程事实设计 | 总体技术方案 |
| 8 | 首次提交适用仓库 | 以固定权威仓库清单执行首次全仓提交检查；全干净零调用直接成功，dirty 时一个 `commit-changes` session 处理必要提交，Python 只读复验 | `applicable_repositories` 与仓库干净事实 |
| 9 | 工程架构设计 | 必要步骤；调用 `engineering-architecture` 生成固定文档，并在同一 session 固定调用一次 `commit-changes` 核验 | `docs/design/工程架构设计.md` 已 tracked，全仓 clean，真实成功并推进第 10 步 |
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

第 4 步固定映射 `frontend`、`backend` 目标，只接受不存在或严格唯一普通 `.gitkeep` 的真实目录；对唯一 `(git_url, default_branch)` 一次 shallow clone，核验 origin、branch、HEAD SHA，校验选中相对路径并拒绝上游 `.git` 和任何符号链接，再复制到同级 run-owned 临时根。每个适用 payload 在临时根中执行 `git init -b main` 并核验自身 top-level、`main`、unborn HEAD、空 index、至少一个不被自身 ignore 的可提交文件；全部 payload 合格后才用 `os.rename()` 发布，`null` 端只删除严格占位目录。成功结果 `steps/04.json` 记录 `applicable`、`outputs` 和每端的选择、实际 origin/branch/commit SHA，状态推进至 `project:05_verify_readiness`、第 5 步。认证或读取权限缺失为 `blocked`，其它现场或操作错误为 `failed`；合法 marker 残留可在目标仍为占位或不存在时 fresh 重试，未知残留与部分发布不覆盖；成功现场最小复核后幂等复用而不 clone。第 4 步不暂存、提交或 push。

修迹真实验证使用 GitLab SSH 来源：前端 `vite-react-shadcn-spa` 的 `main` SHA 为 `a31db6deb85ab29f2d2253413dd362293a96325f`，后端 `fastapi-sqlalchemy-postgresql-async-api` 的 `main` SHA 为 `49ff842fcd330387f2fbdd1e9a43884e05894697`，均与 `ls-remote` 一致。两端均为自身 top-level 的 `main`、unborn HEAD、空 index 独立仓，临时目录已清理，根仓仍为零提交 `main`；源 PRD 和项目内初稿 SHA-256 均为 `d7d9b8054b226ef2abf730cfb29e59b30d5e39d68eb9121ded22a16750414fee`。首次 HTTPS 来源错误为 `failed`，目标未覆盖且临时现场保留；改为 SSH 后同 run 依据 marker 安全清理并成功，第二次执行 0.809 秒幂等复用。

第 5 步只确定性核验第 2、3、4 步交接、产品根 Git、适用子仓 `main` / unborn / 空 index、组装现场和 `PCM_DEV_RESOURCE_LIST` 路径，再在产品项目根显式调用 `/project-readiness`。初始提示以 slash command 开始，正文只描述准备核验领域：两份产品定义是当前范围权威输入，实际工程和**最小选型投影**是技术事实（不传 `git_url`、`origin`），可信资源清单可由 Agent 原样读取；后续依赖安装、构建、测试、启动、仓库首次提交、业务实现和完整验收不作为当前准备阻塞。`completed` 与 `blocked` 终止前均重新核验上述 Git 边界，且只有 `status=success` 的既有结果才可幂等复用。

**重构前真实运行事实。** 修迹项目曾完成 PostgreSQL、MinIO 与本地配置准备，并在旧 session 语义下推进到第 6 步；该业务事实保留。旧历史中的固定完成声明和 `decision_turn` 属于旧协议，不是新循环会写入的状态。

第 6 步只从前序结果读取两份产品定义、第 4 步实际适用工程与白名单化组装来源、第 5 步准备清单；工程内部事实由 Agent 按现场读取。初始提示以 `/project-bootstrap` 开始，正文不包含步骤编号、PCM 节点或其它外层编排背景，也不向 Agent 或决策模型传递可能带凭据的 `git_url`、`origin`。Agent 负责有限项目化和真实工程验证，必须删除或在所属仓忽略可再生产的 `.coverage`；根模板 `.gitignore` 的 `**/.coverage` 覆盖该类文件。Python 在 `completed` 与 `blocked` 前核验根仓及适用子仓的 `main` / unborn / 空 index、`.coverage` 和其它交接事实；没有适用工程时的无副作用跳过保持不变，只有 `status=success` 可复用。

**重构前真实运行事实。** 修迹项目曾完成前后端项目化、安装、检查、测试、构建、真实启动、浏览器检查和基础联调，并推进到第 7 步；根 README 收口、根仓零提交和无 staged 是历史交付证据。当时适用工程尚未建立独立 Git 边界；第 4 步现行实现已替代该旧现场。旧专属裁决、格式重试和连接恢复的叙述不代表本次公共循环已被真实新 session 验证。

修迹真实项目化将产品根 README 收口为 MendMark 项目总说明，将前端收口为 `mendmark-web`、后端收口为 `mendmark-api`，同步公开配置、基础页面、健康检查与模板测试，保留有效基础设施并未实现业务功能。前端 `pnpm install --frozen-lockfile`、lint、type-check、10 项测试、build 和 1 项 Playwright E2E 通过；后端锁定、`uv sync --locked`、Ruff、15 项含 PostgreSQL `SELECT 1` 的测试和 `uv build` 通过；真实 Uvicorn/Vite、`/health`、`/ready`、OpenAPI、浏览器健康联调、375px 窄视口、控制台和网络检查通过。临时服务已停止，实际 `.env` 仍被忽略且权限为 `600`；根仓及适用子仓保持 `main`、unborn HEAD、空 index。源 PRD 与项目初稿的既有 SHA-256 事实均为 `d7d9b8054b226ef2abf730cfb29e59b30d5e39d68eb9121ded22a16750414fee`，状态推进到 `project:07_solution_design`，成功复用耗时约 1 秒且不再调用 Agent。

第 7 步只从前序结果读取两份产品定义、第 5 步项目准备清单、第 4 步实际适用工程和白名单组装来源，以及第 6 步成功结果；工程内部事实由 Agent 按需读取，**不要求全仓扫描**。初始提示以 `/solution-design` 开始，只授权创建或更新 `docs/design/技术方案.md`，不包含步骤编号、PCM 节点或其它编排背景，不传递 `git_url` 或 `origin`。Agent 不重新选型、组装模板、实现业务、修改业务代码或执行 Git 写操作。`completed` 和 `blocked` 终止前都复核根仓及适用子仓的 `main` / unborn / 空 index；只有 `status=success` 的结果可幂等复用。新 run 的完整回复、pending 文本与决策输入保留原文于 Git 忽略目录；仍禁止 Agent 主动披露秘密。

公共循环使第 2/5/6/7/8/9 步共享 `AgentDecision(completed/continue/blocked)`、对话尾部恢复与 SDK 错误边界：`completed` 后才执行步骤核验，若固定产物或仍 dirty 的权威仓库可安全补完则追加普通修复提示并继续同一 session，否则失败；`continue` 留在内部，`blocked` 或失败终止。第 8 步的多仓只读 Git 核验和干净基线逻辑、第 9 步的固定文档工作树边界、tracked 核验和提交执行锚点仍由步骤自身负责，公共循环不成为 Git DSL，也不抽取通用 commit 能力。`error_max_turns` / `error_max_budget_usd` 有 session 与非空回复时可裁决，但必须在正常 `success` 后才可最终完成；400/429/500、连接/CLI/进程、无 Result、`terminal_reason` 为 `aborted_streaming`/`aborted_tools`，以及 `success` 下未知终止原因均在裁决前失败，且无外层自定义 HTTP 重试。旧 `action` 非 `blocked` 映射为 `continue`；若旧 `answer` 为空则使用固定安全兼容 continue 提示，绝不将旧控制 JSON 转发给 Agent。

### 4. 动态决策 XML system snapshot 与项目上下文

第 2、5、6、7、8、9 步各自只维护领域 `DECISION_RULES`。每次新 conversation 创建前，`common/decision.py` 将统一负责人角色、项目上下文、统一职责、步骤完成条件和输出合同分别渲染为 `<role>`、`<project_context>`、`<responsibility>`、`<completion>`、`<output>`。步骤规则只进入 completion；output 约束 `completed/continue/blocked` 的 `answer`、`required_inputs` 组合并要求 `reason` 非空。公共循环首次保存该 snapshot，恢复既有 conversation 时严格使用历史 `messages[0]`。

项目上下文范围固定为：第 2 步初稿原文和目标路径；第 5 步产品定义原文、适用工程、选型白名单投影和资源清单的绝对路径/可读性（不读或内联资源清单正文）；第 6、7 步产品定义原文、准备清单原文、适用工程和组装白名单投影；第 8 步有序权威仓库相对路径及干净基线说明；第 9 步两份产品定义、准备清单、总体技术方案、有序权威工程和固定输出路径。第 8、9 步其它只读 Git 核验和 verifier 继续由步骤私有逻辑处理。

选型和组装投影不含 `git_url`、`origin`、`remote`，`.env` 与资源清单正文因输入来源边界不进入项目上下文。渲染器仅对项目上下文做标准 XML 转义。`request_decision` 要求显式传入该完整 XML prompt，将其原样传给一次 `responses.parse`，并以 Pydantic `AgentDecision` 取得结构化输出；没有公共默认或隐藏追加 prompt，也没有格式重试。Agent initial prompt、conversation schema、公共循环状态机、repair/session/错误分类和第 8 步 Git 逻辑均不变，未引入 `task_contract`。

**重构后第 7 步隔离真实验证。** 新 run `agent-loop-step7-20260822T190149Z` 在外部复制工作区运行，未修改既有 `step01-mendmark`；session `e8000375-2698-4ccf-9927-ccb9ca627ca2` 的 init 确认 cwd、`solution-design` Skill、slash command 和 Fable 模型。首次 Agent 尝试内置 Explore 子代理时发生环境内部未识别模型并超时，未返回 ResultMessage；循环保存 session 与初始 conversation、未推进成功。仅在隔离验证历史中追加普通 assistant 的“不使用子代理、直接工具完成”提示后，从同一 session 恢复。该测试提示不进入生产 prompt，环境内部子代理错误也不是公共循环缺陷。

恢复后 Agent 正常 `success`（44 turns，约 `$3.800742`），生成约 44 KB 技术方案。AI-compatible 服务对同一真实回复首返 YAML 风格结构；当时旧合同执行格式重试后返回 `completed`。测试包装器只在隔离副本首次 completed 后将技术方案置空，verifier 返回固定 `DESIGN_REPAIR_PROMPT`；公共循环保留真实 completed JSON、追加普通 assistant repair 提示、恢复同一已保存 session，Agent 补回非空文档，第二次真实裁决再次 `completed`。最终 `steps/07.json` 为 `success`，状态为 `project:08_initialize_repositories`，conversation 尾部为 `completed`，无旧 completion sentinel 或 `pending_agent_prompt`。该真实决定是旧 prompt 合同下的历史证据；本次自动化计数以本轮执行记录为准。

Probe C 的早期成功和格式重试结果均为旧合同历史。现行公共决策层使用五段 XML system prompt、一次 `responses.parse` 和 Pydantic `AgentDecision`，不追加公共默认或隐藏格式 prompt，也不做格式重试；该合同已由第 9 步 fresh 真实运行验证。

**第 8 步旧合同真实运行。** `step08-real-20260823-a` 必须保留为旧“唯一初始提交证明”合同下的失败事实：第 1 步真实服务依次返回代码围栏、Responses `incomplete` 和自创字段；收紧为严格 JSON、禁止代码围栏并列明五个唯一字段后同 run 成功。第 3 步首次 `ValidationError` 后同 run 重试成功。第 7 步 API 500 后，failed `07.json` 曾被误作成功锚点而阻断恢复；改为仅 `status=success` 可复用后，同一 session 成功。第 8 步因管理模板 Plugin 快照包含已跟踪 `.coverage`，它成为产品根未跟踪垃圾；Agent 按单仓合同未提交，但决策模型多轮追问“调用方授权”并耗尽 8 轮。该失败 run 未产生任何根、前端或后端提交。

`step08-real-20260823-b` 是旧合同下的历史成功：第 0～5 步一次通过，第 6 步真实清除 `.coverage`，第 7 步成功；session `64aa707c-268c-48c8-bb3f-f67f62abe75e` 的 conversation 为 `system → assistant → user → assistant`，一次 Agent 回复、一次 `completed` 裁决后产生 root `c1eb33dfa5bda91a0d7f9aeeb41d8fefe10a6fca`、frontend `5997213c34c09ea6ba4e740e35f9df77d2d45d82`、backend `5d8dd95d8c42370697d25e6ecaf400bab42785b3` 并推进到 `project:09_engineering_architecture`。这些提交 SHA、提交形态和当时重跑事实不再是当前合同的完成条件。

**第 8 步当前合同真实验证。** 真实 run 目录为 `pcm-demo/runs/step01-mendmark`，state 内历史 `run_id` 与目录名不一致是既有已知事实；产品工作区为 `/Users/zhou/resource/fireworks/ANDRSZAN/pcm-products/mendmark`。权威仓库为 `root/frontend/backend`，第 4 步 `outputs` 为 `frontend/backend`；首次执行前三仓均为自身 top-level、`main`、dirty 且 HEAD 不存在。

首次执行只创建 `initialize_repositories` session `f6d42df8-13e5-437b-ada3-eef1015ecc87`。Agent 尝试内置 Explore 时遇到环境未识别模型 `gpt-5.6-sol[1m]`，无 Result、无 Git 变化，进程挂起后停止；session、conversation 和 init 证据已保存。这是环境内部子代理问题，不是第 8 步业务或 Git 逻辑失败。仅在该 Git 忽略 run 历史中追加普通恢复指令“不要使用子代理/Explore，直接工具完成”，生产 prompt 和代码未改变；重跑恢复同一 session。

恢复后 Agent 先创建 frontend `dbab574dbe4d83a02323a750afd04de007565ac5` 与 backend `9682be837759c20f1a9ebbdf8fa2cfc09c2768d4` 两个本地提交，未 push；随后对根仓运行时产物和 `.agents/plugins/superpowers/.git` 请求决策。AI-compatible 负责人返回 `continue`，授权删除 61 个 `.in_use/*`、`.orphaned_at`、`.coverage` 运行时产物、补 `.gitignore`、移除嵌套 `.git`，并将 superpowers 作为普通受控插件快照而非 submodule 提交。同一 session 继续后，root 创建 `02ba4c1`（产品与技术基线）、`ae72c31`（Agent 规范与 Skills）、`5eeeacd217bbd27e03483b1b6d32915c721aadd9`（插件快照）三个本地提交，未 push。

最终 conversation 共 7 条，角色顺序为 `system → assistant 初始 → assistant 恢复 → user → assistant continue → user → assistant completed`；Agent 正常 `success`，26 turns，约 `$1.859406`，session 不变。Python 只读 verifier 写入 `steps/08.json` success：`applicable_repositories` 为 `root/frontend/backend`，result 保存相对路径，state 保存绝对路径，并推进到 `project:09_engineering_architecture`。独立 Git 核验确认 root HEAD `5eeeacd217bbd27e03483b1b6d32915c721aadd9`、3 commits，frontend HEAD `dbab574dbe4d83a02323a750afd04de007565ac5`、1 commit，backend HEAD `9682be837759c20f1a9ebbdf8fa2cfc09c2768d4`、1 commit；三仓均在 `main` 且 `status --porcelain` 为空。这证明当前合同允许每仓产生 0、1 或多个提交，不要求唯一无父提交。

同 run 重跑第 8 步直接以 clean 现场幂等成功，conversation 仍为 7 条，未再次调用 Agent 或决策模型，三仓 SHA 不变。backend 提交阶段的 Agent 摘要报告 Ruff、格式、build 通过，`pytest` 14 passed、1 skipped，跳过项为需要显式 `DB_*` 的数据库集成测试；这不是本次 Python verifier 条件，也不改变第 6 步既有项目化验证。当前合同因此已完成真实联调，但首次成功包含 run-local 恢复指令，不能宣称环境内部子代理问题已经解决或无需恢复。

### 第 9 步必要工程架构合同与真实验证

第 9 步固定输入为第 2 步两份产品定义、第 5 步项目准备清单、第 7 步总体技术方案，以及第 8 步结果/state 完全一致的有序权威仓库 clean 交接。它始终 `applicable: true`，固定输出为 `docs/design/工程架构设计.md`，成功后推进到仍按需的 `project:10_ui_ux_framework`。

步骤只使用一个 `engineering_architecture` conversation/session。fresh 入口要求全仓 clean 且拒绝预置历史；执行期间子仓必须保持 clean，根仓只允许固定文档 dirty；每次决定前复验。conversation 叶文件或父目录为符号链接、已有执行事实却缺少原 session/reference/history 时均拒绝。

负责人 `completed` 后，completion verifier 在同一 session 固定发送一次 `/commit-changes`。提交执行锚点接受任意固定 commit prompt 后紧邻非空 Agent 回复，不要求它位于最后一个 user 之前，也不强制领域与提交固定拆轮。commit-changes 发现事实矛盾时可以严格不修改并报告；外层负责人后续可普通 `continue` 限定通用 Agent 只修正固定文档并提交。最终仍以文档非空且 tracked、全体仓库自身 top-level / `main` / clean 兜底。

自动化最终为第 9 步专属 29 项、公共循环 24 项、第 7 步 8 项、第 8 步 17 项、相关定向 78 项和全量 141 项；`compileall`、`git diff --check` 通过，IDE 无诊断。

旧失败依次暴露 HTTP 403、非 JSON 普通文本和 `completed` 非空 `answer`。根因是旧 prompt 把步骤规则混入 responsibility、硬编码并重复 completion 语义且缺少 output。用户将其重构为 `role/project_context/responsibility/completion/output` 五段，补齐 f-string JSON 花括号转义和字段组合约束，并同步 common 与第 2/5/6/7/9 步测试。

按用户要求两次清理第 9 步局部执行数据和失败生成的未跟踪文档后，保留第 0～8 步历史与三仓提交执行 fresh 运行。最终唯一 session `f41fc439-4c46-434f-b3e9-d15c18c89601`，conversation 11 条：`system → assistant 初始 → user → assistant continue → user → assistant completed → assistant commit prompt → user → assistant continue → user → assistant completed`。

首轮 Agent 请求确认，负责人合法 `continue` 后创建约 32 KB 固定文档；负责人 `completed` 后 verifier 同 session 调用 `/commit-changes`。该 Skill 发现 frontend Git 事实矛盾，严格未修改、未暂存、未提交并报告；外层负责人普通 `continue` 授权通用 Agent 仅修正文档并精确提交。

产品根提交 `ead14dffe19bc6417634c24c7bb1103602c3b772`，message `docs: 新增工程架构设计`，仅新增固定文档，376 行、32928 字节；未 push，frontend/backend 无变化。最终 decision 为合法严格 JSON `completed`，`steps/09.json` 和 state 均为 success，状态推进到 `project:10_ui_ux_framework`。

独立核验 root/frontend/backend 均为自身 top-level、`main`、clean，固定文档 tracked。同 run 幂等重跑后 conversation 仍 11 条，session 和 root HEAD 不变，没有 Agent、decision 或新提交调用。

### 动态 prompt 交接事实回放

Git 忽略 run `prompt-role-replay-20260823` 保留旧四段 XML prompt 的历史交接回放；它不是新五段 prompt 的证据。现行五段 prompt 已由第 9 步最终 fresh 运行真实验证，且最终负责人决定满足严格 Pydantic `AgentDecision` 合同。

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

状态只保存支持恢复所需的当前事实和引用，不复制完整历史事件。工作区文件和 Git 仓库仍是实际交付事实；Claude session 保存 Agent 对话；`conversations/` 保存 AI-compatible 完整编排历史。第 2/5/6/7/8/9 步的恢复核心是 session、`{path}` 引用、最后 Agent 终止摘要和短暂 `pending_agent_text`，不再新写 `pending_agent_prompt`、决策轮次或 Python 完成声明；第 8 步保存权威仓库的绝对路径、`main` 与 `worktree_clean` 当前事实，第 9 步还以固定 commit prompt 后紧邻非空 Agent 回复和原 session 作为提交执行锚点。

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
uv run python run_step.py --step 9 --run-id <run-id>
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

1. 保持第 0～9 步已确认并真实验证的业务边界不变；
2. 第 9 步专属 29 项、公共循环 24 项、第 7 步 8 项、第 8 步 17 项、相关定向 78 项及全量 141 项自动化测试已通过；真实 run `step01-mendmark` 已完成第 8、9 步合同验证，第 9 步固定文档、提交、状态推进和幂等重跑证据完整；
3. 第 10 步进入前先确认按需 UI/UX 框架合同；
4. 合同确认后先实现代码并通过测试和真实验证，再同步设计文档并提交；
5. 不提前实现第 10～19 步或阶段二空壳；
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