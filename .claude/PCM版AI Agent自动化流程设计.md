# PCM 程序化调度的 AI Agent 产品开发流程

> 本文是 [`AI Agent开发流程设计.md`](./AI%20Agent开发流程设计.md) 的 PCM 自动化版本。
>
> 人工版由人负责选择能力、传递上下文、判断结果和推进步骤；PCM 版由 Python 程序完成这些调度工作。两者使用相同的项目规则、Skills、Git 边界和完成标准，不重新定义各 Skill 的职责。
>
> 本文先服务于 PCM 前置 Demo。正式 PCM 系统可以基于 Demo 的真实结果重新设计状态、持久化、权限、调度和产品界面，不要求直接沿用 Demo 的代码结构。

## 一、目标

PCM 自动化流程接收产品想法或初稿及可选的客户初始资料；产品输入可以只有一句话，具体需求在产品定义沟通中收敛，然后自动完成：

```text
产品初稿
→ 建立产品项目工作区
→ 产品定义
→ 基础工程选型
→ 基础工程组装
→ 项目准备核验
→ 基础工程项目化、项目风格定制与基础品牌资产准备
→ 总体技术方案
→ 首次提交适用仓库
→ 必要的工程架构设计和按需 UI/UX 框架
→ Backlog 拆分
→ 解析 Backlog 并初始化需求注册表
→ 阶段一：逐需求建立统一分支、形成 TRD、实现验证、规则复盘、统一提交和合并
→ 阶段二：全项目级集成产品体验审计、候选分流、修复回归和完整复审
→ 项目最终验收
```

最终目标是通过一条命令从 0 到 1 完成一个项目开发。流程正常运行时不需要人逐步调度；缺少不可替代的外部资源时允许阻塞，待人补齐资源后从原进度继续。

## 二、自动化原则

### 1. 外层流程只前进，不回退步骤

PCM 编排器按既定顺序执行步骤，不把“返回第 N 步”设计成流程状态。

当前步骤发现可修正问题时，由当前步骤在内部完成处理并重新核验，例如：

- 文档内容不足：继续调用负责该文档的 Skill 补充；
- 实现未通过审查：恢复原开发会话修复并重新审查；
- 活动 TRD 存在局部问题：在当前步骤内调用负责设计的能力更新活动 TRD，再继续实现或核验；
- Git 或文件状态已经部分存在：先核验事实，再完成尚未完成的动作。

只有当前步骤达到完成条件后，外层流程才进入下一步。

### 2. Skill 保持原有职责边界

PCM 步骤可以顺序调用多个 Skill，但不改变 Skill 自身职责。例如：

- `ui-ux-framework` 只负责建立、校正或演进跨需求稳定的产品级 UI/UX 框架，不负责单需求设计或开发后验收；
- `trd-design` 与 `dev-workflow` 共同保证单个正式需求的产品体验设计、真实运行、浏览器交互和真实渲染结果验收；
- `product-experience-audit` 只在阶段二的完整审计轮次由外层显式调度；它只返回候选、重复项、覆盖缺口和高影响边界，不创建或修改 canonical Backlog、正式需求或 TRD，不分配正式 ID，也不自动调用需求化、开发、提交或其它能力；
- `session-rule-retrospective` 只在原开发 session 中增量修改 `.claude/rules/`，不暂存、提交、建分支或合并；
- 需要更新活动 TRD 时，步骤编排器调用负责设计或维护活动 TRD 的能力；
- `commit-changes` 仍是唯一负责精确暂存和本地提交的 Skill；
- 建分支、切换分支和合并仍由 PCM 的显式 Git 脚本执行。

“当前步骤内部完成修正”不等于让某个 Skill 越过其职责边界。

### 3. 每一步只返回三类结果

| 结果 | 含义 | 外层行为 |
| --- | --- | --- |
| `success` | 步骤完成，或确认不适用并无副作用跳过 | 进入下一步 |
| `blocked` | 缺少模型和当前环境无法取得的不可替代外部资源 | 保存进度并停止，等待外部资源补齐 |
| `failed` | 程序、SDK、命令或执行发生错误 | 保存错误并停止，修复后重试当前步骤 |

不单独建设复杂的回退、补偿或状态转移模型。步骤内部可以循环调用、修正和重新验证，但对外只暴露上述结果。`run_step.py` 只对本次失败显式携带的运行时重试请求按 10 秒、30 秒间隔重新运行当前步骤两次；当前仅 Claude Agent SDK 实际执行通道故障设置该请求，任意 API 状态码、明确 `api_error` 终止、连接失败和未取得 Result 的 CLI 进程失败均可重试。每次重试重新读取最新 state、result、session 和工作区事实；重试请求不持久化，第三次仍请求重试时对外返回 `failed` 对应退出码 `1`。业务 `blocked`、普通 `failed`、AI-compatible 裁决失败、本地合同错误、CLI 参数错误、未实现步骤和主动取消不进入自动重试。审计 Skill 回复中的“已完成”“部分完成且有覆盖缺口”或“不适用”是审计内容，不会成为外层第四种 `status`。

### 4. AI 负责全部可完成的语义决策，程序负责确定性操作

AI 决策能力代替人工调度者处理流程中所有能够基于当前输入、项目事实、可用工具和已提供资源完成的产品、技术、文档、流程及执行取舍，例如：

- 从产品初稿提取当前选题名和项目文件夹名；初稿未明确文件夹名时，根据选题生成稳定的小写 kebab-case 名称；
- 回答 Skill 或 Agent 提出的澄清、确认和方案选择问题；
- 判断文档是否满足当前步骤完成条件并批准定稿；
- 选择产品范围、技术方案、实现方式和非阻断建议的处理结果；
- 判断是否继续当前会话、修正当前步骤产物或结束当前步骤。

Agent 确实需要负责人决定时，必须在本轮回复中自包含准确问题、已核验事实与约束、当前约束下实质可行选项、各选项主要影响及推荐理由；路径、章节、提交、代码符号和行号只能辅助定位。AI-compatible 负责人收到只给引用或缺少可靠决定所需内容的交接时，不读取或猜测未提供的项目文件，而是返回 `continue`，要求原 Claude session 重新读取并补齐；信息不足本身既不构成 `completed`，也不构成 `blocked`。交接完整且现有事实足够时，负责人直接决定，不把普通判断继续上抛。公共循环只负责原样传递、保存和恢复，不解析引用或追加隐藏 Agent prompt。统一负责人职责只进入新建 decision conversation，既有 conversation 继续使用历史 system snapshot；模板 Agent 规则只随未来新建工作区生效，不由本轮迁移现有产品工作区。

需求注册表初始化后的需求选择是确定性调度，不属于 AI 语义决策：Python 根据注册表中的依赖完成事实和 `order`，选择顺序最靠前的可开发需求。

存在多个合理方案、资料歧义或重大取舍时，AI 仍应选择并记录理由，不因需要判断而转交开发者。只有缺少当前资源清单之外、模型与当前环境无法取得的不可替代外部资源时才返回 `blocked`，例如第三方账号、付费服务、客户私有数据、专用设备、外部授权或线下动作。输入不完整、状态冲突或本地现场无法确定性继续属于 `failed`，修复输入或现场后重试当前步骤。

Python 程序直接负责：

- 校验项目文件夹名为单段小写 kebab-case，并根据配置的产品工作区根目录计算最终路径；
- 对配置的模板仓库执行 Git 浅克隆、记录分支和 commit、清理上游 Git 历史、初始化产品文档目录并原子发布工作区；
- 读写运行状态；
- 使用 OpenAI Responses API 和 Pydantic 从正式 Backlog 提取需求静态字段，并校验 ID、顺序和依赖图；
- 根据需求注册表确定性选择下一条可开发需求，并维护活动需求、分支、session、提交、合并和完成状态；
- 创建和检查目录；
- 调用 Claude Agent SDK；
- 执行 Git、测试、构建和启动命令；
- 保存步骤输出和会话 ID；
- 判断命令退出码、文件存在性和仓库状态；
- 在阻塞或失败时停止流程。

AI 不能用口头结论代替真实文件、Git、测试、构建、服务或浏览器证据。

PCM 为 Claude Agent SDK 显式配置独立 Anthropic Messages 网关与受保护 Bearer token；Agent 的真实模型名和 `effort` 只由 `pcm-demo/model-policy.toml` 的组合预设与步骤分配决定，不再使用 `.env` 的低/中/高模型映射。第 6 步 bootstrap/theme/brand 可分别配置；Agent effort 支持 `low/medium/high/xhigh/max`，实际有效档位受 CLI、网关和目标模型能力约束，PCM 不自行降档或兜底。`run_all` 启动或恢复时读取一次策略并向所有步骤子进程传递，运行中修改文件不生效；独立步骤入口按本次进程加载，调整策略需主动停止后重新执行。启动打印最终分配表，不引入热更新、持久化策略快照或多层覆盖。第 15～17 步仍恢复同一 development session，但允许各步使用不同真实模型和 effort。

公共 runner 只加载 `project/local` settings，置空继承的模型别名、显示元数据与冲突认证；标准模型别名通过会话级 `modelOverrides` 统一注册为本次选定模型，子代理默认模型同步为主模型，不再要求维护独立三档映射。每次首次调用和 resume 都显式传入本次启动已确定的 model/effort，不配置 fallback model 或 `max_budget_usd`，既有最大 turn、负责人决策轮数、三态、重试和完成规则保持不变。模型策略属于外层配置，不进入领域 prompt。AI-compatible 继续共用 `LLM_BASE_URL/LLM_API_KEY/LLM_MODEL`，新增可选 `LLM_MODEL_EFFORT`；非空时全部主请求与 JSON 修复请求显式发送 `reasoning.effort`，留空则不传，不与 Agent 的五档配置混用。

### 5. 活动内容允许直接修正，历史内容保持不可变

当前项目定义、活动方案、活动 TRD 和尚未完成的 Backlog 可以在负责它们的步骤中持续修正，直到满足完成条件。

已经完成并归档的需求和 TRD 不回写。后续变化建立新需求和新 TRD，继续遵守人工版流程的历史不可变原则。

### 6. 外部资源缺失时真实阻塞

`blocked` 只表示缺少模型和当前环境无法取得的不可替代外部资源，而不是存在需要判断的问题、输入错误或本地状态冲突。产品、技术、文档、流程和执行取舍由 AI 决策能力完成；资料存在多个合理解释时由 AI 选择并记录理由。

以下条件不能由 AI 伪造：

- 第三方账号、API Key、商户或企业认证；
- 客户专属素材、设备或私有数据；
- 必须由人完成的授权、审批或线下操作；
- 当前运行环境无法提供的不可替代服务。

发现这类问题时保存阻塞原因、所需输入和当前步骤，停止流程。人补齐资源后重新执行当前步骤，确认阻塞已经解除，再继续后续流程。

### 7. 默认只操作本地环境

Demo 和默认 PCM 流程只进行本地文件修改、测试、构建、服务运行、本地 Git 提交和本地分支合并，不自动 push、部署或操作生产环境。

## 三、最小步骤协议

每个 PCM 步骤都应说明：

```text
步骤编号和名称
输入
执行动作
输出
完成条件
可能的阻塞
```

脚本对外返回最小结果：

```json
{
  "phase": "project_initialization",
  "current_node": "project:02_intake",
  "step": 2,
  "name": "项目需求与产品定义",
  "status": "success",
  "summary": "产品范围和核心流程已经收敛",
  "outputs": [
    "docs/product/产品需求与功能定义.md"
  ],
  "blocked": null,
  "error": null
}
```

确认不适用时也返回 `success`，并在结果中记录 `applicable: false` 和跳过依据。

## 四、运行上下文与恢复

第 17、18 步的当前合同与验证入口见各步骤说明。本轮 Agent 模型分级完成后，PCM Demo 当前工作树全量 367 项 `unittest`、`compileall` 与 `git diff --check` 通过（全量耗时 49.802 秒），中模型 + `high` effort 的公共 runner 首轮与同 session resume 真实成功；其余第 17、18 步既有事实保持不变。当前工作树还包含其它公共循环/CLI 的未提交修改，故该全量结果不能全部归因于第 9 步。`run_step.py` 只对 Claude Agent SDK 执行通道故障产生的瞬时请求有界重跑两次；任意 API 状态均可请求重试，业务 `blocked`、普通失败、AI-compatible 裁决失败、本地合同错误和取消不重试，且请求不写入 state/result/diagnostic/conversation。公共错误诊断保留经精确凭据遮盖的 Claude Agent SDK `errors`、异常链和 traceback 位置，以及 AI-compatible provider 的 code/type/message/request ID/HTTP status；完整有界快照写入 Git 忽略的 `logs/`，state/result/stderr 保存具体安全原因和引用。第 13 步直接消费当前需求注册表；第 17 步通过公共 Agent 决策循环运行 `commit-changes`；第 18 步只使用确定性 Python/Git。真实 `step01-mendmark` 已连续完成 BR-001 与 BR-002 两个需求循环。BR-002 在旧 direct-run 第 17 步期间只保存了 Claude session，没有 decision conversation；该历史不能补造，现行合同保证后续需求保存完整 conversation。root/frontend/backend 的 local main tips 分别为 `2f39fbe7e26d6e4905142925ae149ba83d9e70fe`、`f290ff85ed779a1f100eeded7eedfcfb0376b826`、`204a7a6b48c43a80f573dc9e70acedddb59bbe4f`，三仓 clean、`req/br-002` 已删除且未 push。

本轮第 9、14、15 步工程架构约束传递修正已完成：第 9 步区分稳定 owner、目录/包/模块边界与边界内部文件粒度，并对前端巨型路由/页面或通用收纳、后端同名平铺文件及跨所有者穿透给出一致合同；第 14 步按每个受影响交付单元把适用工程归属和架构 delta 写入活动 TRD；第 15 步负责人补齐架构约束/模块归属到改动、依赖、diff/导入/调用证据和实际结果的完成映射。第 9/14/15 步本体 35 项、公共循环与三步 CLI 相关回归 91 项、当前工作树全量 367 项 `unittest`（49.013 秒）通过；完整 `compileall`、修改 Python 文件 IDE diagnostics、两个 eval JSON 解析和 `git diff --check` 通过。第 14/15 步负责人上下文仍分别只增加完整 Backlog 与活动 TRD，没有新增工程架构全文注入、Markdown 解析、JSON 架构 DSL、Git verifier、公共循环或状态字段；第 14/15 步真实集成留给 BR-003 自然验证，第 9 步等待下一 fresh 项目。

```json
{
  "run_id": "20260816-153000",
  "status": "success",
  "workspace": {
    "root": "/products",
    "final_path": "/products/family-meal-planner"
  },
  "applicable_repositories": ["root", "frontend", "backend"],
  "phase": "phase_1_requirement_development",
  "current_node": "requirement:17_commit",
  "step": 17,
  "current_step": 17,
  "requirement_registry": {
    "schema_version": 1,
    "source": {
      "path": "docs/backlog/backlog.md",
      "sha256": "<backlog-sha256>"
    },
    "requirements": [
      {
        "id": "REQ-001",
        "title": "身份与访问",
        "order": 1,
        "depends_on": [],
        "status": "active",
        "completion": null
      }
    ]
  },
  "active_requirement": "REQ-001",
  "requirement_cycle": {
    "requirement_id": "REQ-001",
    "branch": "req/req-001",
    "repositories": {
      "root": {"base_sha": "<root-base-sha>"},
      "frontend": {"base_sha": "<frontend-base-sha>"},
      "backend": {"base_sha": "<backend-base-sha>"}
    },
    "trd_path": "docs/trd/<YYYY-MM-DD>-REQ-001-身份与访问.md",
    "development_session_id": "<development-session-id>",
    "return_node_after_completion": "phase_1:select_requirement"
  },
  "blocked": null
}
```

需求静态字段 `id`、`title`、`order` 和 `depends_on` 由第 12 步使用 Responses/Pydantic 从自由格式 Backlog 进行唯一语义提取；`id` 与依赖 ID 必须符合 `[A-Za-z0-9][A-Za-z0-9_-]*`，并在忽略大小写后唯一。`status`、`completion`、活动需求、分支、session、提交、合并和恢复位置只由 Python 根据真实执行事实维护。Python 不解析 Markdown 标题、表格或详情卡，只校验 catalog 非空、数组物理顺序对应连续 `order`、依赖引用存在且不重复、不自依赖、依赖图无环。已有合法注册表且 Backlog SHA-256 未变化时直接复用，不重新调用模型或重置动态状态；阶段一期间出现未知 Backlog 变化时返回 `failed`，不得静默覆盖注册表。JSON 结果使用同目录唯一临时文件原子 replace；第 13 步 Git 子进程剔除 `GIT_*` 环境变量，避免外部 Git 路径重定向。

第 17 步已经完成统一提交、准备执行第 18 步合并时，活动需求快照至少包含：

```json
{
  "phase": "phase_1_requirement_development",
  "current_node": "requirement:18_merge",
  "active_requirement": "REQ-002",
  "requirement_registry": {
    "requirements": [
      {
        "id": "REQ-001",
        "status": "completed"
      },
      {
        "id": "REQ-002",
        "status": "active"
      }
    ]
  },
  "requirement_cycle": {
    "requirement_id": "REQ-002",
    "branch": "req/req-002",
    "development_session_id": "session-id",
    "repositories": {
      "root": {
        "base_sha": "<root-base-sha>",
        "tip_sha": "<root-tip-sha>",
        "merged": false
      },
      "frontend": {
        "base_sha": "<frontend-base-sha>",
        "tip_sha": "<frontend-tip-sha>",
        "merged": false
      },
      "backend": {
        "base_sha": "<backend-base-sha>",
        "tip_sha": "<backend-tip-sha>",
        "merged": false
      }
    },
    "retrospective": {
      "outcome": "no_change"
    },
    "return_node_after_completion": "phase_1:select_requirement"
  },
  "blocked": null
}
```

需求只使用 `pending`、`active` 和 `completed` 三种持久化生命周期；具体进度由 `phase/current_node` 和 `requirement_cycle` 表达，阻塞信息与生命周期正交。只有第 18 步完成所有适用仓库的 `--ff-only` 合并、SHA 与 clean 核验以及分支清理后，Python 才把活动需求改为 `completed` 并清空 `active_requirement` 与 `requirement_cycle`。

在阶段二审计和候选分流节点中，`requirement_cycle` 为 `null`；顶层 `requirement_registry` 始终保留，继续作为需求生命周期唯一真源，阶段二只在此基础上增加当前审计轮和候选处理所需的最小状态：

```json
{
  "phase": "phase_2_full_product_audit",
  "current_node": "phase_2:route_candidates",
  "applicable_repositories": ["root", "frontend", "backend"],
  "requirement_registry": {
    "source": {
      "path": "docs/backlog/backlog.md",
      "sha256": "<backlog-sha256>"
    },
    "requirements": [
      {
        "id": "REQ-001",
        "status": "completed"
      },
      {
        "id": "REQ-002",
        "status": "completed"
      }
    ]
  },
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

上例是全项目审计已成功并原子推进到候选分流节点的阶段二快照；为简洁只展示注册表项的 ID 和生命周期，实际静态字段继续保留。需求注册表保存全部既有动态状态，审计结果已经存在，而 `candidate_routing` 和 `pooling_evidence` 仍为 `null`；它们只在各自节点成功后写入并推进到下一节点。

不适用的交付单元不进入 `applicable_repositories`，并在对应步骤结果中显式记录 `not-applicable`；后续版本指纹、分支、验证和工作树检查只遍历该列表。阶段二处理已入池需求时临时使用 `phase: phase_2_requirement_remediation` 和 `requirement_cycle`，并将 `return_node_after_completion` 记录为 `phase_2:regress_and_reaudit`；第 18 步完成后返回阶段二，而不是重新进入阶段一选取普通需求。

恢复与幂等规则：

1. 每个节点开始前保存 `phase`、`current_node` 和已核验输入；节点成功后原子保存输出、事实证据和下一节点；阻塞或失败时保存原因并退出。
2. 使用 `--resume <run-id>` 加载原工作区和状态；恢复时只重跑当前节点，并按该节点合同重新核验它自己拥有的 intent、session、输出和外部条件，不跨节点重复核验前序步骤已经完成的文件、Git 或其它交接事实，也不依据历史文字直接跳过当前节点。
3. 已有 Claude Agent SDK session 时优先恢复：第 14 步恢复 TRD session，第 15、16 步恢复同一 `development_session_id`。第 16 步只负责原 session 复盘和结果推进，不比较工作树增量；实际变更由第 17 步统一读取并提交。
4. 第 12 步以合法需求注册表和 Backlog 指纹为幂等锚点；第 13 步以活动需求、统一分支计划和各仓 `main` 基线为恢复锚点；第 17 步以各仓最终分支 tip SHA 为提交锚点。第 18 步按非 root 代码仓先、root 最后的固定顺序合并到保存的 tip；在祖先关系、工作树和引用等 Git 安全边界成立时，依据实际 main 确认已合并或继续 fast-forward，不要求 main 仍等于原始 base。全部仓库核验和分支清理成功后才写入 `completed`。
5. 阶段二每轮审计先记录 `applicable_repositories` 中各仓库 `main` 的版本指纹和独立 SDK session。相同且工作树清楚的指纹恢复原审计或读取已持久化结果，不重复制造候选；修复合并后版本指纹变化，才建立新的全项目复审轮次。
6. 候选分流和入池均保存证据引用。恢复时按候选的稳定事实、已有归属和正式 ID 检查，已入池的候选不得再次分配 ID；入池分支、提交或合并证据冲突时返回 `failed`，不猜测补写 Backlog。
7. Claude Agent SDK 的多轮上下文由其 session 保存；第 9～11 步的公共循环按领域键保存、读取和解释完整 conversation，`state.json` 只记录恢复所需的 session/reference/private state。领域步骤不解析 conversation 的 schema、角色顺序、尾部 decision、session/reference 组合或完整 commit prompt，也不把它当长期成功证据。
8. 需要显式产物交接的步骤按各自合同从前序 result 的 `outputs` 或稳定字段读取所需事实；以当前 state/cycle 为交接的薄编排步骤只读取自身运行所需的最小状态，不重复审计前序结果或固定路径。第 9～11 步对第 8 步仅接受空 `outputs`、result/state 一致的合法有序 `applicable_repositories`，并按各自现行合同核验当前现场；第 14 步只消费 active requirement、cycle、workspace 和需求注册表已记录的 canonical Backlog 来源，读取完整 Backlog 正文供负责人理解当前需求在全部需求中的位置与关系，其它项目资料由 Agent 按需读取。run 目录是受控、Git 忽略的本地恢复状态，不建设防篡改日志、数据库、向量记忆或摘要系统。
9. 第 1 步恢复时重新核对产品初稿哈希、项目目录名、独立工作区根、配置的模板来源、`PCM_AGENT_WORKSPACE_ENV_FILE` 绝对源路径和当前原始字节、临时与最终目录以及根仓库事实；只有临时目录能由状态证明属于同一 run 且 clone 完整，或最终目录能由发布证据证明属于同一 run 时才允许续接。
10. 第 1 步最终目录、发布证据、根 `.env` 内容/`0600`/Git 忽略事实和零提交根仓库证据一致时可确认既有成功；最终目录已发布但根 `.git/` 缺失时续接 `git init -b main`；根环境源路径或内容漂移、根仓库已有 commit、临时和最终目录同时存在、目录归属不明或证据冲突时返回 `failed` 并保留现场。已进入第 2 步及之后的旧 run 不回退补写。

## 五、项目初始化流程

### 流程输入与可选构思

产品想法或已有资料可以只有一句话，不要求完整 PRD 或固定章节。需要先构思时，可在流程外使用 `pcm-product-factory`，但它不是入口前提。

Demo 从第 1 步开始，通过 `--product-draft` 接收 UTF-8 文本文件路径，不限制扩展名。第 1 步在创建 run 和调用 AI 前核验输入可读且非空白，不判断方案完整度；随后建立工作区并原样发布初稿，第 2 步通过沟通形成正式产品文档。

### 第 1 步：建立项目工作区

- 输入：产品初稿；运行 ID；产品工作区根目录；从配置读取的模板仓库和 AI Agent 工作区受保护环境文件。Demo 通过 `--workspace-root`、进程环境或 `pcm-demo/.env` 的 `PCM_WORKSPACE_ROOT` 取得根目录，优先级依次降低；模板仓库由 `PCM_TEMPLATE_REPOSITORY` 读取，工作区环境源由 `PCM_AGENT_WORKSPACE_ENV_FILE` 读取，后二者都不提供单次运行覆盖。环境源必须是绝对、可读、非符号链接、非空普通文件，只作为工作区固定开发工具配置，不属于目标产品资源；源文件使用不跟随符号链接的同一文件描述符读取，目标从创建时即为 `0600`，该 PCM 控制键不传入 Claude Agent SDK 子进程环境。
- 初始资料：新运行可通过 `--initial-resources <文件或目录>` 提供一个可选路径，相对路径按启动命令的工作目录解析并保存。工作区根使用非隐藏的固定目录 `initial-resources/`，资料复制为 `initial-resources/<源名称>`，保留原名和内部结构，不移动源、不使用软链接、不自动解压。无输入时不创建空资料目录，旧 run 不回退补装。资料不替代 `PCM_DEV_RESOURCE_LIST`，也不属于工作区工具 `.env`。
- 资料复制与恢复：使用第 1 步已有临时工作区，在发布前完成复制；源及递归内容仅接受普通文件和目录，拒绝符号链接、特殊文件及会递归包含临时或最终工作区的输入。半复制不视为成功，不覆盖未知目录；失败保留现场。复制完成并发布后的恢复只使用工作区副本，不重新读取或同步客户源目录，不新增全量内容哈希、资源清单、大小配额或上传机制。
- 资料 Git 边界：模板维护者在工作区 `.gitignore` 中声明 `initial-resources/`。有资料输入时，Python 只核验最终根仓库的实际 Git 忽略事实，不编辑或补写 `.gitignore`；规则缺失或目标资料目录冲突时返回 `failed`，保留现场。忽略只保护原始资料的常规入库边界，不代表可以公开秘密或个人数据。
- AI 输出：从初稿提取 `topic_name` 和 `project_directory_name`。后者必须是单段小写 kebab-case；初稿没有明确名称时允许根据选题生成，并记录生成理由。
- 模板：使用 `PCM_TEMPLATE_REPOSITORY` 配置的模板仓库默认分支最新内容，不由 AI 或单次运行更换来源。
- 执行动作：
  1. 在产品工作区根目录中计算最终路径 `<root>/<project_directory_name>` 和同级临时路径 `<root>/<project_directory_name>.pcm-tmp-<run-id>`；
  2. 使用 `git clone --depth 1` 将配置的模板克隆到临时路径，记录默认分支、实际分支和 commit SHA；
  3. 核验模板关键能力存在、模板不包含任何形态的 `.env`，并以禁用用户级全局 excludes 的实际 Git 规则确认模板根忽略 `.env`；
  4. 删除临时目录中的上游 `.git/`，清空并保留 `docs/`，将输入初稿按原始字节写为 `docs/产品初稿.md`，同时把配置源原始字节独占写为根 `.env` 并设置 `0600`；有初始资料输入时将其复制到独占的 `initial-resources/<源名称>`；
  5. 核验上游 `.git/` 已删除、`docs/` 只包含产品初稿、初稿哈希一致、源初稿未改变、模板能力仍存在，以及根 `.env` 内容和权限符合当前配置源；
  6. 全部发布核验通过后，将同级临时目录原子重命名为最终路径；
  7. 在最终项目根执行 `git init -b main`，只建立根仓库边界，不执行 `git add`、`git commit` 或 push；
  8. 核验最终目录的 Git 根就是自身、当前分支为 `main`、尚无 commit，并再次确认根 Git 忽略 `.env`，记录根仓库初始化证据。
- 输出：产品项目根由 `state.workspace.final_path` 记录；步骤结果 `outputs` 仍只记录相对于该根的 `docs/产品初稿.md`。根 `.env` 是 Git 忽略的受保护工作区配置，不进入 outputs、步骤结果、日志或后续项目资源交接。
- 完成条件：最终目录独立、可操作，位于配置的独立产品工作区根中；模板来源和 commit 可追溯且未误带上游 Git 历史；根 `.env` 与当前配置源原始字节一致、权限为 `0600` 且被实际根 Git 忽略；最终项目根已经初始化为 `main` 分支的独立 Git 仓库但尚无 commit；初始化后的 `docs/` 只含当前产品初稿，状态和文件事实一致；有初始资料输入时，工作区副本完整复制且被实际根 Git 忽略。
- 自动化说明：AI-compatible 调用使用 Responses API 的严格 JSON Schema；第 1 步 prompt 明确只允许 `topic_name`、`project_directory_name`、`directory_name_source`、`reason`、`blocked_reason` 五个字段，并禁止 Markdown、代码围栏、YAML 或 JSON 之外的文本。服务不支持该协议或结构不符时明确失败，不回退到 Chat Completions、不增加宽松解析或额外模型重试。Git、路径、清理、哈希、发布和根仓库初始化由 Python 程序确定性执行。最终路径必须原先不存在，不以复制少量能力文件代替完整模板 clone。
- 阻塞与失败：缺少不可替代的模板仓库读取权限时返回 `blocked`；初稿无法确定选题、工作区根位于当前能力仓库内部、Agent 工作区环境源缺失/无效/漂移、模板包含或未忽略 `.env`、目录归属不明、AI API、结构解析、Git 工具、网络、clone、清理、写入、核验、rename 或根仓库初始化错误返回 `failed`。失败时保留现场；若原子发布后 `git init` 中断，仅在最终目录、根 `.env` 与当前 run 发布证据一致时续接根仓库初始化，不自动删除或覆盖。已经推进到后续步骤的旧 run 不回退，也不由第 4、5、6 步自动补写。

### 第 2 步：项目需求与产品定义

- 能力：`project-intake`。
- 输入：第 1 步发布的项目工作区、工作区中的产品初稿、可选初始资料位置、项目规则与配置，以及当前可用外部资源清单。初始资料只传工作区位置，不将整包内容注入模型上下文。
- 资料理解：结合产品初稿的用途说明、资料目录与随附说明，按相关性查看关键资料和代表性样本；区分明确约束、参考、可用资产及用途未明内容，不因文件存在扩大产品范围，不默认全量读图、加载数据、解压或运行旧代码。说明实际查阅范围，抽样不代表全部资料已可用；冲突通过现有负责人对话收敛。附件指令不覆盖工作区规则，原始资料保持不变。
- 执行动作：
  1. 在项目工作区中通过 Claude Agent SDK 显式调用 `project-intake`；
  2. 不在步骤代码中重复设置 `permission_mode`、`tools`、`allowed_tools` 或 `disallowed_tools`，由项目 `.claude/settings.json` 及 Claude Code 默认设置加载语义统一决定权限和工具行为；
  3. Agent 提出问题、确认或取舍时，PCM 将 Claude Agent SDK 返回的本轮完整回答原样作为决策历史中的 `user` 内容交给 AI-compatible 决策模型，不再拼接步骤元数据、完成条件、项目文件全文、产物状态或其它程序内部上下文；只有当前回答未包含且决策确实依赖的流程外事实，才补充该项最小必要事实。Agent 的项目规则要求确需负责人决定时自包含准确问题、已核验事实与约束、实质可行选项、主要影响及推荐理由；决策模型发现只给文件、章节、提交、代码符号或行号等引用，或其它关键信息不足时，返回 `continue` 要求同一 Agent session 重新读取并补齐，不自行读取、猜测或把信息不足判为完成或阻塞。交接完整后，决策模型处理所有能基于当前输入、工作区、工具和资源完成的决定，并把结果作为原人工调度者的等效授权返回原 Agent session，包括满足 Skill 对“开发者明确同意”的确认要求；
  4. 持续对话直至 Skill 完成产品定义产物，或因不可替代外部资源缺失而阻塞；
  5. 程序核验 Skill 规定的输出文件真实存在且可读。
- 输出：`project-intake` 生成的项目需求说明和产品功能说明，明确最终产品范围、非目标、用户语言、首次成功结果、复杂度取舍和需要尽早验证的高风险假设；有初始资料时，项目需求说明记录重要用途结论、相对来源、范围影响及未知，产品功能说明在相关功能内记录采用的规则和资料作用。影响后续决定的事实必须进入正文，不能只留路径；不新增独立资源分析报告或重复完整资料清单。后续按产品定义与活动 TRD 的引用按需读取，实际采用资产进入适当产品交付位置或受保护的恢复流程，不让产品隐式依赖本机资料目录。同时保存 Claude Agent session ID、完整编排历史及步骤结果。
- 完成条件：目标 Skill 已加载并显式调用；目标用户、最终产品范围、核心流程、关键约束和待确认事项已经收敛；规定产物真实存在且可读；Claude session、完整编排历史和步骤结果均已持久化；没有外部资源阻塞。
- 自动化说明：第 2 步只负责产品定义，不决定具体开发排期。AI 可以提出合并或删除不必要复杂度，但不能因实现困难静默缩小最终范围，也不提前处理技术方案、Backlog 或实现逻辑。
- 阻塞与失败：只有缺少模型和当前环境无法取得的不可替代外部资源时返回 `blocked`；SDK、模型、Skill 加载、结构解析、文件读写、状态或对话历史持久化失败时返回 `failed`。
- 恢复：重新核验工作区输入和输出事实，优先恢复 `project_intake` Claude session，并加载同一领域键下的完整决策历史继续当前步骤；不把历史文字结论代替当前文件事实。

### 第 3 步：基础工程选型

- 执行方式：Python 将产品定义和 catalog 候选构造成 Pydantic 输入模型，通过公共 Responses API 调用封装和代码内的 system prompt 获取 `FoundationSelectionDecision`；模型只返回各交付面的 `candidate_id` 与 `reason`，明确不需要的交付面返回 `null`。程序校验候选 ID，并从 catalog 回填仓库地址、默认分支和模板路径，形成完整选型结果。
- 输入：第 2 步结果中记录的项目需求说明、产品功能说明，以及本次 `catalog.json` 中的前端和后端候选。system prompt 只描述选型功能、输入、输出和约束，不包含步骤编号、PCM、Skill 或其它外层编排背景，并要求严格 JSON、禁止 Markdown、代码围栏、YAML 或 JSON 之外的文本。
- 输出：Pydantic `FoundationSelectionResult`，其中 `frontend`、`backend` 分别为完整模板选择或 `null`；每个选择直接包含 `id`、`git_url`、`default_branch`、`path` 和 `reason`。程序使用 `model_dump()` 将该结果写入 `steps/03.json.template_selection`。
- 完成条件：SDK 成功返回 `output_parsed`，步骤结果已经写入，状态推进到 `project:04_assemble_foundation`。本步骤不获取、复制或组装模板，不初始化前后端仓库。
- 失败与恢复：输入文件、catalog、Pydantic 解析或 Responses API 调用失败时保存经精确凭据遮盖的具体原因和 `diagnostic_path`，完整有界 provider/异常诊断写入 Git 忽略的 `logs/`，并停留在当前步骤；已有成功结果且状态已推进到第 4 步时直接复用，不建立模型 session 或额外恢复状态机。

### 第 4 步：组装基础工程

- 输入：只读取第 3 步成功结果 `steps/03.json`，以既有 `FoundationSelectionResult` / `TemplateSelection` 校验 `template_selection`；不读取 catalog、产品文档，不调用模型、Skill 或 Agent。状态必须位于 `project:04_assemble_foundation`，`workspace.final_path`、state 的根 Git 证据和现场必须一致，产品根仍为零提交 `main`。
- 执行动作：目标固定为 `frontend/`、`backend/`。每个目标只能不存在，或是非符号链接且唯一内容为普通 `.gitkeep` 的目录；空目录、额外内容、符号链接和既有工程一律拒绝。对唯一 `(git_url, default_branch)` 执行一次 `git clone --depth 1 --branch <branch> --single-branch`，核验 origin、分支和 HEAD SHA；选中的相对模板路径不得为空、绝对、含 `..`、逃出 clone 或指向符号链接，子树不得包含上游 `.git` 或任何符号链接。每个适用 payload 复制到同级 run-owned 临时根后，在 payload 内执行 `git init -b main`，核验 Git top-level 就是 payload 自身、分支为 `main`、HEAD 为 unborn、index 为空，并且至少存在一个不被自身 ignore 的可提交文件；所有 payload 均合格后才移除经核验的占位目录并以 `os.rename()` 发布。第 4 步不执行 `git add`、`git commit` 或 push。
- Agent 配置：仅对新复制的适用前后端 payload，在初始化 Git 前由 Python 向各自 `.gitignore` 补充缺少的 `.agents/`、`.claude/`、`AGENTS.md`、`CLAUDE.md` 规则，覆盖仓库内各层级；保留原文件内容，重复执行不重复追加。配置文件原样保留供本地开发使用，模板源仓库和产品根工作区不改。初始化后使用不依赖用户全局 ignore 的 Git 候选文件列表核验实际效果；若现有反向规则等导致内部配置仍可提交，则发布前失败并保留现场，不覆盖其它忽略规则。不迁移已组装产品，第 8 步及通用提交 Skill 不重复维护此策略。
- 临时与恢复：临时根固定为产品目录同级 `<project>.pcm-assemble-<run-id>`，只以 run ID、产品路径和步骤号的 marker 证明归属。仅当路径、marker 完全匹配且两端仍是占位或不存在时，才删除失败残留并 fresh 重试；未知残留和部分发布现场均保留并 `failed`。`null` 端只删除严格占位目录，原本不存在则无副作用。成功后核验每个适用端自身 top-level、`main`、unborn HEAD、空 index，不适用端不存在，核验 marker 后清理临时根；已有成功结果且状态已到第 5 步时，最小现场核验来源记录、上述仓库边界、目标和临时根后幂等复用，不重新 clone。
- 输出：`steps/04.json` 记录 `applicable`、实际 `outputs` 和 `assembly.frontend/backend`；每个适用端保存 `target`、`id`、`git_url`、`default_branch`、`path`、实际 `origin`、`branch`、`commit_sha`，不适用端为 `null`。成功推进 `phase: project_initialization`、`current_node: project:05_verify_readiness`、`step/current_step: 5`。
- 阻塞与失败：明确的模板仓库认证或读取权限缺失为 `blocked`；状态、目录、Git、来源、路径、复制、发布、清理和核验错误为 `failed`。步骤自行保存 result/state；入口只输出结果路径与退出码，不重复写第 4 步结果。
- 已验证：修迹 run 使用 GitLab SSH 模板成功组装前端 `vite-react-shadcn-spa`（`main` SHA `a31db6deb85ab29f2d2253413dd362293a96325f`）和后端 `fastapi-sqlalchemy-postgresql-async-api`（`main` SHA `49ff842fcd330387f2fbdd1e9a43884e05894697`）；两端均为自身 top-level 的 `main`、unborn HEAD、空 index 独立仓，产品根仍为零提交 `main`。首次 HTTPS 来源错误按 `failed` 保存且未覆盖 `.gitkeep`、保留临时现场；修正为 SSH 后同 run 核验 marker、安全清理并 fresh clone 成功。重复执行在 0.809 秒内幂等复用。

### 第 5 步：核验项目准备状态

- 能力：`project-readiness`。
- 输入：当前开发范围、基础工程选型结论、已组装工程，以及调用方本次提供的动态真实开发资源资料。
- 执行动作：建立当前 PCM 自动化开发周期唯一的资源准备基线，识别完成编码、开发环境联调和开发环境真实验收所需、且必须由调用方提供的外部服务、账号、凭据、素材、私有数据或专用设备；匹配候选前先验证受保护实际配置中的非空运行凭据与资源绑定，满足开发合同时原样保留，不用候选池中的维护、共享或更宽权限身份替换，也不把候选凭据探针结果误记为最终项目凭据结果；清单只描述最终选定绑定，不得提及、比较或说明未采用候选，否定表述也不例外；只有绑定缺失、失效或不合格时才使用动态候选池。在授权和配置合同允许时优先准备项目专用开发/测试资源和最小权限运行凭据。资源使用稳定产品级环境身份，不以单个需求编号命名长期数据库或存储作用域；保持既有有效绑定，不为命名偏好擅自重建资源。服务不支持派生项目身份时，只有调用方明确授权的非管理、非生产共享开发身份，且实际作用范围满足开发合同，才可以兼容使用；共享管理或根凭据、生产身份和可访问合同外资源的身份不得写入应用配置，无法派生合格开发身份时属于第二类阻塞。权限与隔离按实际可见范围和范围外拒绝判断，不因“共享”标签或仅返回获授权资源的列表接口成功而误判不可用。每项被判为 `ready` 的外部运行资源都必须把最终项目凭据与资源绑定持久化到所属仓库被忽略的实际 `.env` 或等价受保护配置，确保后续开发无需重新读取共享资源资料；同步无秘密 `.env.example` 或公开说明，含秘密文件在 POSIX 上通常使用 `0600`，并使用最终运行凭据完成最小行为和隔离验证。资源资料不要求固定格式，Python 不读取或解析其正文。
- 输出：项目准备清单，以及实际落地的受保护开发配置、公开配置示例和项目级开发/测试资源。清单按资源类别交接最终绑定、配置落点与实际验证结果，共同事实集中说明，环境差异与真实缺口保持清楚，不机械铺满固定字段；组织与证据表达以 [`project-readiness` Skill](skills/project-readiness/SKILL.md#清单格式) 为准。`steps/05.json` 另外保存固定的清单准入合同版本，以及清单与两份权威产品定义的无秘密 SHA-256 指纹；合同版本使旧语义 success 不可复用，指纹防止完成基线被静默替换，二者都不证明资源 `ready`，也不记录 `.env`、凭据或资源资料正文。
- 完成条件：所有进入项目准备清单的当前开发必需外部资源均真实可用；不存在两类阻塞：开发必需外部资源在候选池中缺失、当前环境无法安全生成且无兼容替代，或已匹配资源真实不可用、凭据无效、权限不足、隔离不合格，或缺少开发所需接口能力、可用配额、回调/白名单及其它既定能力。清单、管理凭据、Mock、截图或 Agent 自述不能单独证明完成。
- 自动化说明：依赖安装、migration、Seed、业务实现、项目内测试账号、完整联调和浏览器验收由后续开发步骤完成。只服务生产部署或生产运行的正式域名、DNS/TLS、生产资源与凭据、生产回调与配额、监控、备份恢复、容量和发布安全属于开发及清单准入范围外。项目准备清单正文任何位置都不得列举、命名或汇总这些事项，也不得以“未纳入清单”、范围外、未来事项、非阻塞、无状态或 `not-applicable` 章节保留它们；开发 SMTP TLS、localhost 回调、开发白名单、沙箱范围和开发配额仍按当前开发用途纳入。产品规则和隐私治理同样不写入清单。已有成功结果只有在当前 `scope_contract`、清单和产品定义指纹一致时才可幂等复用。

### 第 6 步：项目化基础工程、项目风格定制与基础品牌资产

- 能力：同一数字步骤顺序显式调用 `project-bootstrap`；当 `steps/04.json.outputs` 含 `frontend` 时，再依次调用 `tailwind-theme` 和 `media-assets`。三个领域任务 `project_bootstrap`、`tailwind_theme`、`brand_assets` 各自使用独立 Claude session、decision conversation、XML system snapshot 和私有恢复状态，不由 Skill 彼此隐式调用，也不新增步骤编号或内部节点。
- 输入：基础工程、产品定义、基础工程选型结论和经过严格指纹核验的准备基线；已有项目可另外提供既有技术方案。主题调用只引用两份产品定义和实际 frontend，工程事实由 Agent 现场读取，不依赖尚未执行的 UI/UX 框架产物。
- 项目化：`project-bootstrap` 完成项目身份、基础配置、文档和最小联调，保持或建立可替换的 Tailwind 基础主题接线，但不选择或生成项目专属主题，也不把模板默认样式认定为最终产品主题。配置可以为匹配工程实际加载合同迁移键名与结构并同步无秘密公开示例，但必须复用同一既有资源绑定和真实值，保持资源身份、endpoint 与权限范围，不重新选择、创建、派生、轮换或替换外部资源或凭据。
- 主题适用性：无 frontend 时只运行项目化并以 `tailwind_theme:false` 跳过主题。存在 frontend 时，bootstrap 完成后由 Python 确认 `frontend/package.json` 直接声明可明确判断为 major 4 的 `tailwindcss`，并在 frontend 自身 Git 可见且未忽略的 CSS 中找到 `@import "tailwindcss"` CSS-first 证据；版本不明确、非 v4 或缺少 CSS-first 证据属于本地模板合同 `failed`，不创建主题 session，也不作为 `blocked`。
- 主题动作：`tailwind-theme` 初始提示只引用两份产品定义和实际 frontend，并请求依据产品和前端完成风格定制。Agent 可自主选择保留默认、采用全部或部分 preset、适配或 custom，按实际改动执行相称验证并诚实报告；具体规则以 [`tailwind-theme` Skill](skills/tailwind-theme/SKILL.md) 为唯一真源，不在步骤合同重复固定属性范围、选择顺序或全套检查。
- 品牌资产：theme 完成后，Agent 依据产品定义、当前 frontend 和适用运行配置调用 `media-assets`，交付同一视觉身份的页面品牌标识与 favicon，其它资产按需。优先复用，品牌文字保持可编辑，Agent 负责实际看图、质量、派生、接入及验证。整套共享最多 8 次生成调用，仅作为提示约束，继续或恢复不重置，满足用途即停；额度耗尽或生成服务不可用时允许合格简洁 SVG／文字标识兜底。负责人只根据回复防漏，不读文件或复做视觉验收；Python 不增加预算状态、次数核验或图像评分。
- 输出：完成项目化、条件性风格定制与品牌资产准备的工程。`steps/06.json.outputs` 继续等于第 4 步实际适用工程，顶层 `applicable` 语义不变，保留真实布尔 `tailwind_theme`，严格满足 `tailwind_theme == ("frontend" in outputs)`；有 frontend 时 success 摘要的风格定制部分只写“已完成项目风格定制”。字段缺失、类型错误或不一致的旧 success 不可复用。品牌任务不增加 result 必需字段，也不收紧历史 success 准入。
- 完成条件：适用安装、检查、测试、构建、启动、健康检查、真实浏览器检查和基础联调通过；有 frontend 时项目风格定制任务完成，并按实际改动完成相称验证或准确说明未验证范围；品牌资产已交付并完成适用接入，允许合理复用或合格兜底。各独立适用领域 completed 后才写 success 并推进第 7 步，留下待提交变更；负责人不要求逐项完成声明。
- 恢复：仍停留在 `project:06_bootstrap_foundation`。前序任务 completed 后只复验、不重跑 Agent；品牌失败或 blocked 时恢复原品牌会话，人工消息只投递当前 blocked 领域，前序 blocked 不创建后续执行产物。品牌 completed 后推进中断不重复生成；result 已写而 state 未推进时按严格 marker、前序交接、Tailwind gate 和 Git 事实只补状态。已成功历史第 6 步不补跑品牌，也不宣称已补齐；未完成旧 bootstrap/theme 沿用原 snapshot/session，完成后再创建品牌任务。
- 自动化说明：发现模板残留、配置读取、变量迁移、脚本、代码、代理、启动、健康入口、前后端连接或测试入口问题时在项目化领域修正并重跑；主题或验证可继续完成时在主题领域修正并重跑。`blocked` 仍只用于当前环境无法取得的不可替代外部条件；本地版本、文件、主题入口、工作树或状态冲突为 `failed`，不得用替代资源、新凭据或降低验证标准规避。第 8 步自然提交主题与品牌资产变更，第 10 步把已提交主题及品牌资产视为 Current，负责跨页面使用规则，不重新调用主题或生成能力。
- 历史验证（主题任务接入时）：第 6 步 14 项、第 7 步 9 项、相关第 6/7/8/10 步 58 项、公共循环与入口 64 项及全量 351 项自动化通过。隔离 run `step06-tailwind-theme-20260831` 已确认 bootstrap Skill/slash command、产品 cwd 与原 session 加载；内置 Explore 未识别模型后，run-local 同 session 恢复实际执行 43 turns 并修改项目，但 SDK 以 `terminal_reason=api_error` 结束且没有完整 Agent 回复，后续严格拒绝不合法 `pending_agent_text`，未进入独立 theme session。该结果只证明真实通道失败和恢复保护生效，不构成 `/tailwind-theme`、实际 CSS light/dark 修改或浏览器集成成功证据。

- 品牌任务验证（2026-09-10）：最终 PCM Demo 全量 534 项 unittest、compileall、diff 检查及独立审查通过；隔离真实生成与 SVG 兜底／复用场景均经真实负责人判定 completed，并完成 Playwright 图片加载、favicon 引用和页面呈现检查。生成服务曾返回 500／503 和不匹配尺寸，最终显式匹配实际尺寸取得合格 PNG；未放宽 Provider 校验。探针轮数、提示版本、来源与覆盖边界见[基础品牌资产准备 TRD](../pcm-demo/docs/trd/20260910-PCM%20Demo%20基础品牌资产准备%20TRD.md)。

### 第 7 步：总体技术方案

- 能力：`solution-design`。
- 输入：产品定义、已组装并完成项目化的当前工程事实、开发约束和第 3 步已确认的基础工程选型。向设计 Agent 一并交接各适用端已保存的选型理由，承接既有选择及真实依据，不要求重新选型，也不补写未发生的历史比较。
- 输出：总体技术方案文件、Claude Agent session ID、完整编排历史及步骤结果。方案按系统级技术决定组织，集中说明边界、依据、代价和关键失败语义；不重复完整业务规则或追加本轮调查流水，具体写作边界以 [`solution-design`](skills/solution-design/SKILL.md) 为准。
- 完成条件：方案 Markdown 存在且可读，系统边界、主要技术选择、交付单元、跨单元协作、关键风险和未决事项已经确认，并与当前工程事实一致。
- 自动化说明：本步骤基于已组装和项目化后的工程事实进行总体设计，不重新进行模板选型或组装；文档、模型、文件或状态问题在本步骤失败，外部不可替代资源缺失时返回 `blocked`。

### 第 8 步：首次提交适用仓库

- 能力：这是第一次全仓提交检查和干净基线节点。Python 只执行确定性输入、状态及 Git 只读核验；存在未提交变更时，才在产品根创建一个 Claude Agent SDK session，显式调用 `commit-changes`。
- 输入：权威有序仓库严格为 `['root', *steps/04.json.outputs]`；每个权威路径必须是自身 top-level、`main` 的独立 Git 仓库。不从固定前后端目录、历史状态或 Agent 回复扩充该清单。
- 执行动作：Python 对每仓只执行 `git rev-parse --show-toplevel`、`git branch --show-current`、`git status --porcelain`。若全部干净，在创建 conversation/session 或写入 `running` 前零 Agent、零决策模型调用，直接成功并记录全仓干净基线。任一仓 dirty 时，初始 prompt 首行是 `/commit-changes`，只给仓库清单及边界；Agent 负责必要 Git 写操作，Python 不逐仓派发、不 `add`、不 `commit`、不 `reset`、`amend` 或 `rebase`。Agent 不得切换分支、改写历史或 push。
- 输出：`steps/08.json` 的 `outputs` 固定为空，并保存 `applicable_repositories` 和 `repositories` 列表；每项为相对 `path`、`branch`、`worktree_clean`。状态保存同样事实但路径为绝对路径，成功推进到 `project:09_engineering_architecture`。
- 完成条件：每仓自身 top-level、`main` 且 `status --porcelain` 为空。无需检查 HEAD、提交是否产生、提交数、父提交、SHA、marker、历史替换或根 tree。
- 恢复：`completed` 后 Python 只读复验；仍 dirty 则以固定 repair prompt 继续同一 session。`blocked` 后重读，已全干净直接成功，仍 dirty 才保存 blocked。恢复也先读现场，已全干净直接成功，仍 dirty 才恢复原 session。`failed` / `blocked` 的步骤结果不能当作成功；只有 `status=success` 可幂等复用。成功后的第 9 步状态若权威仓库变 dirty，拒绝复用，避免第 8 步替后续修改提交。
- 第 9 步更新后的 prompt 合同及第 9～11 步相关自动化已完成本轮验证：第 9 步定向 18 项通过（5.498 秒）；第 9～11 步本体合计 51 项（18+18+15）通过；公共循环加第 9～11 步本体及第 10/11 步 CLI 的相关回归 97 项通过（20.800 秒）；当前工作树全量 351 项 `unittest` 通过（61.878 秒）；`compileall common steps run_step.py run_all.py test_run_step_retry.py test_run_all.py` 与本次目标 `git diff --check` 通过。当前工作树还包含其它公共循环/CLI 的未提交修改，故全量结果是当前工作树验证，不能全部归因于第 9 步。第 9 步新版 prompt 合同尚未执行安全的 fresh 真实 Claude Agent、AI-compatible 负责人或 `/commit-changes` 集成；`step01-mendmark` 已推进到第 13 步并保留旧第 9 步 success/session/conversation，旧真实 run 仅为旧合同历史。
- 真实验证：当前合同已在真实 run `pcm-demo/runs/step01-mendmark` 和产品工作区 `/Users/zhou/resource/fireworks/ANDRSZAN/pcm-products/mendmark` 完成验证；run 目录名与 state 内历史 `run_id` 不一致是既有已知事实。权威仓库为 `root/frontend/backend`，第 4 步 `outputs` 为 `frontend/backend`；首次执行前三仓均为自身 top-level、`main`、dirty 且 HEAD 不存在。
- 环境恢复：首次执行只启动 `initialize_repositories` session `f6d42df8-13e5-437b-ada3-eef1015ecc87`。Agent 尝试内置 Explore 时遇到环境未识别模型 `gpt-5.6-sol[1m]`，无 Result、无 Git 变化，挂起进程停止后保存 session、conversation 和 init 证据；这是环境内部子代理问题，不是第 8 步业务或 Git 逻辑失败。仅在 Git 忽略的真实 run 历史中追加普通恢复指令“不要使用子代理/Explore，直接工具完成”，生产 prompt 和代码未改变，并恢复同一 session。
- 提交与决策：Agent 先创建 frontend `dbab574dbe4d83a02323a750afd04de007565ac5`、backend `9682be837759c20f1a9ebbdf8fa2cfc09c2768d4` 两个本地提交；随后针对根仓运行时产物和 `.agents/plugins/superpowers/.git` 请求决策。AI-compatible 负责人返回 `continue`，授权删除 61 个 `.in_use/*`、`.orphaned_at`、`.coverage` 运行时产物、补 `.gitignore`、移除嵌套 `.git`，并将 superpowers 作为普通受控插件快照而非 submodule 提交。root 创建 `02ba4c1`、`ae72c31`、`5eeeacd217bbd27e03483b1b6d32915c721aadd9` 三个本地提交；全程未 push。
- 完成证据：最终 conversation 共 7 条，角色顺序为 `system → assistant 初始 → assistant 恢复 → user → assistant continue → user → assistant completed`；Agent 正常 `success`，26 turns，约 `$1.859406`，session 不变。Python 只读 verifier 写入 `steps/08.json` success，result 保存相对路径、state 保存绝对路径，状态推进至 `project:09_engineering_architecture`。独立 Git 核验确认 root 3 commits、frontend/backend 各 1 commit，三仓均在 `main` 且 clean；当前合同允许每仓 0、1 或多个提交，不要求唯一无父提交。同 run 重跑直接 clean 幂等成功，conversation 仍为 7 条，未再次调用 Agent 或决策模型，SHA 不变。
- 证据边界：backend 提交摘要中的 Ruff、格式、build 通过和 `pytest` 14 passed、1 skipped（数据库集成测试需显式 `DB_*`）是 Agent 报告，不是 Python verifier 条件，也不改变第 6 步历史项目化验证。`step08-real-20260823-a/b` 继续仅是旧“唯一初始提交证明”合同历史；当前首次成功包含 run-local 恢复指令，不能宣称环境内部子代理问题已解决或无需恢复。

### 第 9 步：工程架构设计

- 能力：`engineering-architecture`；是否调用 `commit-changes` 仅由当前固定文档的未提交变化决定。
- 适用：必要步骤，始终 `applicable: true`；不因项目简单、现有结构看似清楚或文档无变化而跳过。
- 输入：严格读取第 2 步结果中的两份产品定义、第 5 步固定项目准备清单、第 7 步固定总体技术方案，以及第 8 步严格 success 的空 `outputs`、result/state 一致的合法有序 `applicable_repositories`。不逐项回放旧 `repositories` path、branch、clean 字段；第 8 步交接不能由 Agent 回复替代，实际 Git 状态由当前步骤现场只读核验。
- 执行动作：在产品根使用单一 `engineering_architecture` conversation/session，初始提示第一行调用 `/engineering-architecture`，只允许创建或更新单份根仓 `docs/design/工程架构设计.md`。Agent 必须在其中为每个包含业务代码且相关的适用交付单元分别形成有限的 `[当前]`/`[目标]` 地图，并可用 `[按需]`、`[迁移]` 标示条件性或过渡性内容：前端分别闭合装配/路由页面、功能、远程/局部/跨页状态、模型映射和共享 UI；后端分别闭合入口、编排规则、持久化适配、事务、授权、错误与副作用恢复；每单元至少一个代表性文件放置演练。架构决策矩阵说明证据、目录/模块职责、语义所有权、稳定公开能力、私有禁区、允许/禁止依赖和共享准入，并给出最小迁移、可观察演进和当前下游所需的高影响决定。已确认的稳定业务 owner、目录/包/模块边界、公开出口、私有禁区和依赖方向属于约束；代表性文件只验证归属，边界内部文件名、数量和等价拆分可按真实职责调整。前端不得把稳定职责静默打平到巨型路由/页面或通用 `components`、`hooks`、`services`、`shared` 收纳位置，后端不得把稳定业务包静默降级为同名平铺文件；跨所有者合并、公开出口绕过和私有路径引用等 Current 偏差必须给出最小迁移。不固定框架目录，也不以行数阈值拆分；MVC、分层、六边形、DDD 不是互斥四选一，不得为任一范式预建 `domain`、`application`、`infrastructure`、`shared`，或预建无消费者的服务、队列、接口或其它结构；配置、运行、数据、测试和安全只按当前证据展开。Agent 不修改代码、配置、项目规则或 Git。负责人每次决定前，Python 复核子仓持续 clean，根仓只允许固定文档 dirty。
- 提交核验：负责人 `completed` 后，completion verifier 先补齐非空固定文档；仅在根仓有未提交变化且边界确认只有固定文档时，才向原 session 发送 `/commit-changes`。固定文档已 tracked 且全仓 clean 时直接满足提交交付条件，不制造无变化调用。
- 输出：唯一固定产物 `docs/design/工程架构设计.md`。
- 完成条件：固定文档为非空、非符号链接普通文件且被根仓 Git 跟踪；其语义完成由 Skill、Agent 与 AI-compatible 负责人按上述逐交付单元闭合要求裁决。Python 仍只核验这一单份固定文档和当前 Git 事实：根仓及所有适用子仓在当前现场均为各自自身 top-level、位于 `main` 且 clean；Python 不读取 HEAD、SHA、提交数或历史，不执行 Git 写操作；不要求 exact commit prompt、紧邻 Agent 回复或历史执行锚点。
- 证据边界：Python 只核验当前 Git-visible 工作树和 index；这不是不可绕过的安全隔离，不证明整个 Agent 执行历史未发生 Git 写入，也不覆盖 ignored 文件。本地 Demo 信任项目权限配置和 Agent 遵守领域约束；未来若要求不可绕过隔离，应在项目级权限或沙箱统一实现，而非由领域步骤解析 conversation 或扩展 Git DSL。第 10、11 步沿用该边界。
- 恢复与安全：fresh 入口要求全仓 clean，并仅因本步骤 session、conversation reference、私有状态或 conversation 路径等执行产物存在而拒绝；resume 由公共循环恢复原 session。负责人 `blocked` 时始终保存 blocked 并停在当前节点，不因文档 tracked+clean 改判 success。result 已 success 而 state 推进中断或完整 success 重跑时，只按严格 result schema、当前文档和 Git 事实补状态或确认成功。成功后推进 `project:10_ui_ux_framework`；第 10 步仍按需。
- 第 9 步更新后的 prompt 合同及第 9～11 步相关自动化已完成本轮验证：第 9 步定向 18 项通过（5.498 秒）；第 9～11 步本体合计 51 项（18+18+15）通过；公共循环加第 9～11 步本体及第 10/11 步 CLI 的相关回归 97 项通过（20.800 秒）；当前工作树全量 351 项 `unittest` 通过（61.878 秒）；`compileall common steps run_step.py run_all.py test_run_step_retry.py test_run_all.py` 与本次目标 `git diff --check` 通过。当前工作树还包含其它公共循环/CLI 的未提交修改，故全量结果是当前工作树验证，不能全部归因于第 9 步。第 9 步新版 prompt 合同尚未执行安全的 fresh 真实 Claude Agent、AI-compatible 负责人或 `/commit-changes` 集成；`step01-mendmark` 已推进到第 13 步并保留旧第 9 步 success/session/conversation，旧真实 run 仅为旧合同历史。
- 旧失败与根因：曾依次出现 free quota / `use free tier only` 导致的 HTTP 403、访问恢复后的非 JSON 普通文本，以及 `completed` 携带非空 `answer`。根因是旧 `render_decision_system_prompt` 将步骤规则混入 responsibility、硬编码并重复 completion 语义且缺少 output。用户将公共 prompt 重构为 `role/project_context/responsibility/completion/output` 五段，补齐 f-string JSON 花括号转义和 `AgentDecision` 字段组合约束，并同步 common 与第 2/5/6/7/9 步测试。
- 旧合同下的历史运行：以下第 9 步 fresh session、11 条 conversation、固定 commit 调用、commit-changes 发现事实矛盾与提交事实均不构成当前成功条件。按用户要求两次清理第 9 步局部 result、conversation、session、private state 和失败生成的未跟踪文档，保留第 0～8 步历史与三仓提交。最终唯一 session `f41fc439-4c46-434f-b3e9-d15c18c89601`，conversation 11 条：`system → assistant 初始 → user → assistant continue → user → assistant completed → assistant commit prompt → user → assistant continue → user → assistant completed`。
- 执行事实：首轮 Agent 请求确认，负责人合法 `continue` 后创建约 32 KB 固定文档；负责人 `completed` 后 verifier 同 session 发送 `/commit-changes`。该 Skill 发现 frontend Git 事实矛盾，严格未修改、未暂存、未提交并报告；外层负责人普通 `continue` 授权通用 Agent 仅修正文档并精确提交。
- 完成证据：产品根提交 `ead14dffe19bc6417634c24c7bb1103602c3b772`，message `docs: 新增工程架构设计`，仅新增固定文档，376 行、32928 字节；未 push，frontend/backend 无变化。最终 decision 为合法严格 JSON `completed`，`steps/09.json` success，state success 并推进 `project:10_ui_ux_framework`。
- 幂等证据：独立核验 root/frontend/backend 自身 top-level、`main`、clean，文档 tracked。同 run 幂等重跑后 conversation 仍 11 条，session 和 root HEAD 不变，无 Agent、decision 或新提交调用。第 9 步的历史证据保持不变；现行 `run_step.py` 对 schema 完整的第 8～12 步 success 保持固定结果保护；第 13 步只保护当前 active/cycle 的完整 scoped success，残缺或失败 scoped result 可恢复覆盖。第 10 步真实成功后，第 11 步已严格消费交接、生成并提交固定 Backlog；第 12 步已完成注册表初始化并进入第 13 步状态。

### 第 10 步：产品级 UI/UX 框架

- 能力：`ui-ux-framework`。它仍只建立、校正或演进跨需求稳定的产品级框架，不负责单项需求设计、页面实现或开发验收。
- Demo v1 适用性：仅由第 8 步严格 success 的空 `outputs`、result/state 一致的合法有序 `applicable_repositories` 是否包含 `frontend` 确定；程序不扫描目录，也不让 Agent 判断。该规则是当前前后端交付单元模型的 Demo 简化，不改变通用 Skill 对已有项目和显式既有路径的更广语义。
- 输入：无论适用与否，严格读取第 8 步交接与第 9 步 success 结果（唯一 `docs/design/工程架构设计.md`）；适用时还读取第 2 步两份产品定义输出、第 5 步清单、第 7 步总体技术方案和实际 `frontend/` 工程。第 8 步不逐项回放旧 `repositories` 字段，实际 Git 状态在当前现场只读核验。
- 不适用：只作上述交接核验，按本步骤执行产物存在性拒绝；否则零 Git、Agent、决策、LLM 配置和 `docs/ui-ux/` 副作用，写入 `success`、`applicable: false`、`outputs: []` 并推进第 11 步。此分支由自动化覆盖，黄金项目不走此分支。
- 适用动作与输出：单一键/session 为 `ui_ux_framework`，初始提示首行 `/ui-ux-framework` 并明确 `bootstrap`；只允许创建或更新 `docs/ui-ux/framework.md`，禁止单需求设计、代码、配置、项目规则和 Git。Agent 按需读取 Skill 自带参考资源，但参考资源不是项目默认实现；能由项目事实推导的低风险结构收敛为有依据的目标设计，真正改变跨需求体验骨架的具体分歧交由负责人通过 `continue` 决定并回写。Demo v1 成功结果为 `applicable: true` 与该唯一输出；已有项目接入和显式既有路径属于未来扩展，不能据此把当前固定路径泛化为通用 Skill 的永久限制。
- 完成、恢复与安全：负责人仅在适用范围的 App Shell Contract 已闭合，产品表面、区域职责、导航层级、页面模式、常规滚动所有者、sticky 基准和窄屏转换可指导后续需求，且实现事实、目标设计和未决事项没有混写时返回 `completed`；新项目记录目标、依据与适用范围，不逐项填写状态或重议条件，既有框架调整时再补实际偏差与必要迁移，不能以整份框架泛化待确认替代收敛。`completed` 后先 repair 缺失或空文档；只有根仓存在且仅存在固定文档未提交变化时，才在原 session 调用 `/commit-changes`，文档已 tracked 且全仓 clean 时不制造无变化调用。Python 仍只核验文档非空、非符号链接、已 tracked 和全部权威仓库当前为自身 top-level、`main`、clean，不解析框架 Markdown 语义；不要求 exact prompt、紧邻 Agent 回复或历史锚点。fresh、resume、blocked、写入中断与幂等规则同第 9 步同构且保持步骤私有，blocked 始终保存并停在当前节点，完整 success 只依严格 result schema、当前文档与 Git事实恢复。
- 第 9 步更新后的 prompt 合同及第 9～11 步相关自动化已完成本轮验证：第 9 步定向 18 项通过（5.498 秒）；第 9～11 步本体合计 51 项（18+18+15）通过；公共循环加第 9～11 步本体及第 10/11 步 CLI 的相关回归 97 项通过（20.800 秒）；当前工作树全量 351 项 `unittest` 通过（61.878 秒）；`compileall common steps run_step.py run_all.py test_run_step_retry.py test_run_all.py` 与本次目标 `git diff --check` 通过。当前工作树还包含其它公共循环/CLI 的未提交修改，故全量结果是当前工作树验证，不能全部归因于第 9 步。第 9 步新版 prompt 合同尚未执行安全的 fresh 真实 Claude Agent、AI-compatible 负责人或 `/commit-changes` 集成；`step01-mendmark` 已推进到第 13 步并保留旧第 9 步 success/session/conversation，旧真实 run 仅为旧合同历史。

### 第 11 步：拆分 Backlog

- 能力：`requirement-breakdown`；是否调用 `commit-changes` 仅由当前固定 Backlog 文档的唯一根仓未提交变化决定。
- 输入：严格读取第 2 步两份产品定义、第 5 步准备清单、第 7 步总体技术方案、第 8 步严格 success 的空 `outputs`、result/state 一致的合法有序 `applicable_repositories`、第 9 步工程架构，以及严格第 10 步交接；不逐项回放旧 `repositories` 字段，当前 Git 状态由现场只读核验。
- 输出：唯一固定产物 `docs/backlog/backlog.md`。
- Backlog 边界：记录正式需求的范围、目标、验收要点、依赖和风险，不记录 pending、active、completed、blocked 或恢复位置等需求开发生命周期。框架中的已确认 Target 只有在演进既有产品表面、迁移本身形成独立可观察用户结果且其它需求开始前确实必须完成三项同时成立时，才形成迁移 BR 和严格依赖；不满足时写入相关业务 BR 的体验约束。默认 Target 只作为相关 BR 的体验约束并保留依据与重议条件，不创建迁移 BR 或严格依赖；偏离默认 Target或改变跨需求体验骨架时列为待确认。框架文档、Skill、页面、组件、CSS、目录、工程依赖和外部条件不得作为 `depends_on`，严格依赖只指开始前必须完成的正式 BR ID。
- 数据基线合同：Agent 与负责人按 `requirement-breakdown` 的“项目数据基线与首次交付”明确每个项目的适用事实、承担需求和客户结果。适用项目必须承诺：准备已说明的真实服务后，接手者通过单一初始化入口获得自然、完整、可操作的现场，适用角色可正常登录；受保护的重置入口清空明确目标并恢复同等完整基线，所需对象存储和文件一并恢复。需求包含实际数据范围、删除边界、重复保护、失败恢复与验收，不能仅追加一个排在最后的 Seed 标题。首次身份随业务建立、后续需求持续维护、完整恢复按真实依赖收口；默认只有初始化与重置，不机械增加第三种合并模式或 PCM 节点。
- 完成条件：负责人确认上述体验决定、严格依赖边界与数据基线交付合同已经落实后，Python仍只核验 Backlog 非空、非符号链接、已 tracked，以及全部权威仓库当前为各自自身 top-level、`main`、clean；Python 不解析 Backlog Markdown 语义，不要求提交调用锚点。
- 恢复：领域步骤把完整 conversation 交给公共循环保存、读取和解释，fresh 仅按执行产物存在性拒绝，resume 由公共循环恢复。blocked 始终保存并停在当前节点；success 状态中断和完整重跑仅按严格 result schema、当前文档/Git事实恢复。
- 现行推进：第 11 步只生成和提交 Backlog，success 进入 `phase_1:initialize_requirement_registry` / step 12；第 11 步本身不写注册表。
- 第 9 步更新后的 prompt 合同及第 9～11 步相关自动化已完成本轮验证：第 9 步定向 18 项通过（5.498 秒）；第 9～11 步本体合计 51 项（18+18+15）通过；公共循环加第 9～11 步本体及第 10/11 步 CLI 的相关回归 97 项通过（20.800 秒）；当前工作树全量 351 项 `unittest` 通过（61.878 秒）；`compileall common steps run_step.py run_all.py test_run_step_retry.py test_run_all.py` 与本次目标 `git diff --check` 通过。当前工作树还包含其它公共循环/CLI 的未提交修改，故全量结果是当前工作树验证，不能全部归因于第 9 步。第 9 步新版 prompt 合同尚未执行安全的 fresh 真实 Claude Agent、AI-compatible 负责人或 `/commit-changes` 集成；`step01-mendmark` 已推进到第 13 步并保留旧第 9 步 success/session/conversation，旧真实 run 仅为旧合同历史。

## 六、阶段一：注册需求并逐需求开发

第 12 步位于需求循环之前，只初始化或核验需求注册表。第 13～18 步才是单需求循环；`trd-design` 与 `dev-workflow` 对每个正式需求完成需求级体验设计、实现和真实验收。首条验证切片、局部改动、单页面、单需求、内测或发布前这些局部时点均不单独触发全项目审计。

### 第 12 步：解析 Backlog 并初始化需求注册表

- 执行方式：直接使用 OpenAI Python SDK `responses.parse` 和 Pydantic 输入输出；不调用 Claude Agent SDK、`AgentDecision` 循环或任何 Skill。Responses/Pydantic 是自由格式 Backlog 的唯一语义提取路径。
- 输入与提取：只接受第 11 步完整 success、产品工作区内固定的非空非符号链接 `docs/backlog/backlog.md` 和当前运行状态。模型每条需求仅可输出 `id`、`title`、`order`、`depends_on`；system prompt 要求覆盖全部且仅有的正式需求，忠实保留正式 ID、标题、明确顺序和显式前置依赖，排除说明、示例、候选、非目标、历史和未来设想，不得猜测依赖。
- Python 校验与副作用边界：Python 不解析 Markdown 标题、表格、详情卡或依赖章节，也不建立第二套语义事实源。它只拒绝空 catalog、非法或忽略大小写重复 ID、数组物理顺序不对应连续 `order`、不存在/重复/自依赖依赖和依赖环；不选择需求、不创建分支、不修改产品项目或执行 Git。
- 来源、结果与状态：程序从同一文件字节生成模型输入和 SHA-256，模型返回后重新读取并拒绝调用期间漂移。成功 `steps/12.json` 保存 `{path, sha256}` 来源和仅含静态字段的 catalog，`outputs: []`；先写 result，再写 `schema_version: 1` 注册表，全部项由 Python 初始化为 `pending`、`completion: null`。success 后进入 `phase_1:select_requirement` / step 13，活动需求和 cycle 均为 `null`。
- 恢复：完整 success、当前 Backlog 路径/SHA-256、catalog 和注册表完全一致时零模型调用确认；result 已写而 state 未推进时从 result 恢复全部 pending 注册表；来源、catalog 或注册表漂移均 `failed` 且不覆盖。旧 `{path, sha256, root_main_sha}` source 不兼容、不自动迁移，只作为旧合同历史保留。
- 真实验证：隔离 run `step12-ai-only-20260826` 在无 Git 工作区中使用没有总览表、详情卡或固定标题层级的自然语言 Backlog。真实 Responses 准确提取 `BR-AI-001`～`BR-AI-003`，标题、顺序和显式依赖均正确，并排除 `NOTE-001` 示例和在线支付未来设想；全部注册为 pending/completion null。不可连接的 LLM 配置下幂等重跑仍 success，result/state 字节不变。第 12 步 16 项、第 12～14 步定向 61 项、全量 282 项 `unittest`、`compileall` 与目标 IDE diagnostics 均通过。历史 `step01-mendmark` 的 14 项提取、root SHA 与三字段 source 继续仅为旧合同证据。

### 第 13 步：选择需求并建立统一需求分支

- **已实现范围**：纯 Python 确定性节点，零 AI、Claude Agent、Skill、产品文件改动、提交、合并和 push；`run_step.py` 支持第 1～18 步；第 18 步已实现并真实验证。
- **输入与选择**：直接消费 state 中的有序 `applicable_repositories`、精确对应 workspace 的仓库名称与路径，以及当前 `requirement_registry`；不回读历史 `steps/08.json`、`steps/12.json` 或复验 `source`。注册表是阶段一需求生命周期真源；第 12 步负责完整静态校验，第 13 步只检查选择与恢复所需字段、ID 唯一性、顺序类型、依赖引用和动态状态，不重跑连续顺序或依赖图校验。仓库描述允许附加字段，历史分支与 clean 标记不替代当前 Git 预检。只从 `pending` 中选择依赖均为 `completed` 且 `order` 最小的一项；没有 pending 时当前无副作用失败，阶段二转场延期；有 pending 而无候选是注册表状态错误。
- **fresh 与 intent**：在任何 state/Git 写入前，全局核验全部适用仓为自身非符号链接 top-level、clean local `main`、HEAD/local `main` 相等、目标分支不存在且没有进行中的 merge、rebase、cherry-pick 或 revert。通过后先写 `active_requirement`（仅 ID）及 cycle：`branch: req/<lowercase-id>`、按仓名映射的 `base_sha`、`return_node_after_completion`，再以 `git switch -c <branch> <base>` 建立全部统一分支。第 13 步后续只校验自己拥有的活动需求、统一分支、仓库集合和每仓 `base_sha`；第 14、15、17 步可追加自身字段，但不得改变这些选择与基线证据。
- **结果、恢复与 CLI**：success 仅写 `steps/requirements/<ID>/13.json`，仓库 path 为 `.` 或仓库名，随后推进 `requirement:14_trd_design`。partial 现场按记录 base 恢复；scoped success 已写但 state 未推进时先只读核验 target/base/clean 后补 state；已推进后续节点时不读 Git。CLI 只以当前 active/cycle 的第 13 步核心投影和完整 scoped success 保护当前需求，历史需求 result 不保护当前需求；只有 state 仍位于第 13 步自身锚点时，失败才可持久化，误调历史步骤不得覆盖已推进节点。
- **真实验证**：初次 `step01-mendmark` 运行选择 `BR-001` 并建立三仓 `req/br-001`。第 14 步前用户将新 TRD 命名规则提交到产品 root，导致 root `main` 和旧需求分支从原记录 base 前进；经用户明确选择后，先完整归档 run，确认三仓旧需求分支均无独有提交并安全删除，只重置 BR-001 的第 13 步 cycle/result，再从最新 `main` 重跑。bases 为 root `a7d5509df6843a06315aa803d87285569b86e355`、frontend `dbab574dbe4d83a02323a750afd04de007565ac5`、backend `9682be837759c20f1a9ebbdf8fa2cfc09c2768d4`；第 14、15、17 步随后追加 TRD、development session 和提交证据而未改变这些基线。第 18 步已将三仓 local main ff-only 到记录 tip并删除 `req/br-001`，BR-001 已完成，state 返回 `phase_1:select_requirement` / step 13。
- **自动化与第二轮真实验证**：第 13 步本体 20 项与 CLI 10 项，共 30 项；当时统一步骤重试 5 项；PCM Demo 当时全量 303 项 `unittest`、`compileall` 与 `git diff --check` 通过。真实 `step01-mendmark` 未迁移历史 result/state 即选择 BR-002；第 14 步裁决失败现场零 Agent 恢复成功；第 15 步曾先后暴露 stream disconnect、HTTP 500 和代码围栏 JSON，并在旧“任意非 `success` 均重试”策略下于第三次执行成功收敛。该运行只作为历史事实，不定义现行重试范围。第 16～18 步完成规则复盘、三仓提交、ff-only 合并、分支清理和 `completion:{"step":18}` 生命周期更新。

### 第 14 步：形成活动 TRD

- **已实现能力**：采用与第 15 步一致的薄编排，只消费当前 state 的 active requirement、注册表唯一 active 项、cycle、workspace 和注册表已记录的 canonical Backlog 来源；不重新读取或精确复验第 2/5/7/8/9/10/11/12/13 步结果、其它上游文档或 Git 现场。Python 从 `requirement_registry.source.path` 读取完整 Backlog 正文并放入负责人的 `<project_context>`，使负责人理解当前需求在全部需求中的位置、依赖和关系；Agent 在产品根通过 requirement-scoped `trd_design_<ID>` session 显式调用 `/trd-design`，按需自行读取其它产品资料、实际代码、测试、接口、数据、权限、配置和运行约定。
- **路径 intent**：Python 按 `docs/trd/<YYYY-MM-DD>-<ID>-<标题>.md` 计算唯一路径，对直接用于文件名的标题做最小合法性检查，并在首次 Agent 调用前写入 `requirement_cycle.trd_path`；恢复只使用已持久化值，不根据新日期重算，也不覆盖既有目标。
- **Agent 与决定边界**：步骤直接复用公共 `run_agent_decision_loop` 保存和恢复 session、conversation 与待裁决回复，不解析公共 conversation 内部结构，也不增加步骤私有 tool hook 或 Git 监管。负责人的静态项目上下文只增加完整 canonical Backlog 正文，不包含尚未生成的活动 TRD 正文或其它上游文档；prompt 只允许创建或更新指定 TRD并禁止 Git 写操作；Agent 按需发现本需求真正适用、任意来源的已确认 Target 或有依据的默认 Target；沿用项写清来源、具体要求和适用范围，并保留影响本次选择的前提或例外；存在差异或本次改变时，再说明经核验的 Current/Target、理由、影响和必要迁移。默认选择存在重要假设时保留依据与重议条件，不逐项重填追踪字段。只有实质高影响取舍或改变已确认承诺与边界时才请求负责人决定，不因涉及安全、接口等主题或普通文档落盘重复确认；没有适用决定时不虚构、不阻塞，也不固定要求某份框架文档、资料来源或 UI 技术栈。TRD 同一决定集中说明，各章节只补局部影响；自审后直接修正文档，不默认写自审声明或重复调整清单，活动设计变化原位更新。有可核验且适用的工程架构资料时，Agent 还须按每个受影响交付单元记录稳定业务 owner、目录/包/模块边界、公开/私有边界、允许/禁止依赖和预期改动归属；边界内部文件粒度可调整，跨所有者合并、边界打平、出口绕过、私有路径引用或以巨型入口/页面、通用收纳目录、同名平铺文件替代已确认边界时，须作为架构 delta 说明影响、理由和最小迁移。负责人 `completed` 要求范围、关键行为、技术方案、验证、需求级体验、适用工程归属合同和阻碍实现的决定均已收敛，且适用体验决定和工程边界均无静默偏离，不能仅因实现门槛已被列出就判定完成；缺失或空文档只在原 session repair，不调用 `/commit-changes`。
- **完成、结果与恢复**：Python只核验指定 `trd_path` 是产品工作区内的非空文件。success 先写 `steps/requirements/<ID>/14.json`，再进入 `requirement:15_development` / step 15；blocked 保留路径和同一 session。success result 已写但 state 未推进时确认本步骤输出后只补状态；推进后只校验当前 scoped success，不再读取文件或调用 Agent。第 14 步不读取 Git，不重复检查第 13 步建立的分支/base，也不监管第 17、18 步负责的提交与合并。
- **真实验证历史**：`step01-mendmark` 输出 `docs/trd/2026-08-25-BR-001-身份、角色访问与站内消息入口.md`，session 为 `b9ed4756-0acf-4666-b3f9-c8f3628c03f1`。首次负责人错误接受 8 项实现门槛后，同一 session 收敛决定；负责人服务 free quota HTTP 403 后也从原 conversation 尾部恢复完成。最终 conversation 7 条且无 `/commit-changes`。当时 root 只有唯一未跟踪 TRD、frontend/backend clean、三仓 refs 等于 base，是旧实现结束时的历史现场，不再是现行 success 条件，也不会由现行代码重复核验；既有 TRD/session/result/state 不因本次精简而改写。

### 第 15 步：实现与验证

- **已实现能力**：只消费当前 state 的活动 requirement/cycle/workspace、当前需求 scoped 第 14 步 `success` 和非空活动 TRD；不读取第 2/5/7/8/9/10/11/13 步文档，不执行 Git 命令或 Git verifier。活动 requirement 必须是注册表唯一 `active` 项且 `completion: null`。Python 在现有非空普通文件校验中读取活动 TRD 完整正文，并将其作为负责人的直接权威 `<project_context>`。
- **Agent 与边界**：requirement-scoped key 为 `development_<ID>`，复用公共 `run_agent_decision_loop`。初始 prompt 只含 `/dev-workflow`、需求 ID/标题和活动 TRD 路径；负责人项目上下文只增加该活动 TRD 的路径和完整正文，不重复加入 Backlog、产品定义、技术方案、工程架构或 UI/UX 文档。Agent 按需自行读取项目资料、代码、配置、测试和环境，按活动 TRD 中适用的体验决定与工程架构约束实施；稳定设计偏差和架构 delta 可同步活动 TRD。有适用工程架构约束时，开发 Agent 须按每个受影响交付单元建立“架构约束/模块归属→改动位置与依赖关系→diff/导入/调用证据→实际结果”映射，稳定业务 owner、目录/包/模块边界、公开出口、私有禁区和依赖方向不得被巨型路由/页面、通用收纳目录、同名平铺文件、跨所有者合并或私有路径穿透静默弱化。存在适用的已确认 Target 或默认 Target 时，开发 Agent 须建立“体验决定（来源、具体要求和范围）→本需求可观察结果→实现位置→真实浏览器和实际读取截图证据→实际结果”映射；沿用项不补填逐项 Current/Target 或重议条件，保留影响实现的前提与例外，实际差异或改变再补 Current/Target、理由、影响和迁移，重要假设保留依据与重议条件。不得静默偏离；截图不替代动态交互、权限、失败恢复和持久化验证。禁止修改 `.claude/rules/`，以及 stage、commit、创建或切换分支、merge、push。
- **验证与收敛**：子代理执行局部针对性检查，Leader 在整合版本上统一安排必要构建、跨模块回归和全栈验收；复用仍有效的结果，不因执行者变化或进入收尾重复验证，不把完整风险矩阵在每层机械重跑。普通功能默认一次完整独立审查，专项按具体风险需要增加；修复后只复核原发现及受影响差异，真实新阻断继续处理，等价实现偏好不触发返工。功能、架构和体验证据可合并为简洁摘要，保持可定位，不重复制作多套报告。
- **数据交付判定**：当前需求建立或调整数据基线时，开发 Agent 还须按 `dev-workflow` 的“项目数据基线与交付恢复”实际验证：单入口从空环境恢复当前完整数据，逐角色正常登录与主要任务成立，数据自然且可操作，适用文件／对象存储／处理结果共同可用，重复初始化不改变使用成果，明确重置覆盖约定目标内后续新增数据且范围外不变，失败／中断和文档交接有真实证据。仅有旧开发现场、测试账号或数据库记录不够。该判断属于现有实现与验证职责，不新增 Python Markdown 解析器、节点或 Seed 状态机；后续增量按实际影响维护同一基线。
- **完成、结果与恢复**：completion verifier 为空，开发 Agent 负责完成实现、适用验证及审查，保留功能、架构、体验与数据交付的有效证据。负责人按现行代码的交付结果规则判断：功能已实现、核心路径与适用关键风险已有可信证据、没有已知阻断缺陷或未决重大选择时返回 `completed`，可披露非阻断验证限制；信任已报告结果，不重做验收，也不因未逐项复述完成声明或映射而补问。真实必要缺口可继续解决时只给最小下一步，不重复有效验证或扩大范围。`continue`/`blocked` 沿用公共语义。首次取得 session 即同步 `requirement_cycle.development_session_id`；success scoped result 为 `steps/requirements/<ID>/15.json`、`outputs: []`，保存 requirement ID、TRD 路径和 development session，随后推进 `requirement:16_rule_retrospective` / step 16。blocked 保留 step 15 与同一 session；success result→state 中断恢复及推进后幂等均受支持，CLI 只保护当前活动需求完整 scoped success。
- **真实验证**：`step01-mendmark` 的 development session `e6bd1b82-39f9-41b2-9cc9-a69b281015dc` 确认 Fable 5、Claude Code 2.1.233、`bypassPermissions`，最终 normal success 为 23 turns、约 `$9.784016`。首次调用在 init/session 保存后因 `claude-agent-sdk` 0.2.139 默认单条 CLI stdout JSON 1 MiB 缓冲触发 `JSON message exceeded maximum buffer size`；只在公共 `ClaudeAgentOptions` 固定为 `max_buffer_size=10 * 1024 * 1024`，无新配置，随后同 session 恢复成功并保留既有产品改动。自定义 dev/reviewer 子代理曾有未识别 model 警告和一个子进程退出，主 Agent 仍完成，生产 prompt 未改。
- **完成证据**：conversation 共 9 条，负责人先以 `continue` 要求补 Firefox/WebKit，再最终 `completed`。Agent 报告后端 Ruff/format/build、pytest 16 passed 1 skipped、真实 PostgreSQL 和 Alembic upgrade-downgrade-upgrade；前端 lint/type-check/build、Vitest 15 passed；Chromium/Firefox/WebKit Playwright 矩阵 3 passed，及真实 FastAPI/PostgreSQL/Vite 浏览器联调、截图读取和独立审查。BR-001 仍 active/completion null；root 保留活动 TRD和代表性截图未跟踪，frontend/backend 保留实现、测试、迁移与配置未提交变更；三仓均为 `req/br-001`、index clean，无 commit、merge 或 push。不可用 LLM 配置重跑仍 success，state/result/conversation 字节不变，SHA-256 分别为 `069b50dc583d8472683eded457bdb954265e37000b78c59860986bc8ea15bf72`、`033585fb8c7b2a43937dd67082aec8a179cc368ede869c460df4300a438487a2`、`432072a5bb43f90af90adf557bc1b92adab3599a5adb11a5696f57167a100e19`。
- **自动化**：第 15 步本体 6 项与 CLI 4 项，共 10 项；第 16 步现行本体 7 项与 CLI 4 项，共 11 项。当前全量 282 项、`compileall`、`git diff --check` 通过；第 17、18 步均已完成代码、自动化和适用真实验证。

### 第 16 步：在原开发 session 复盘执行规则

- **已实现范围**：采用与第 15 步一致的薄编排，只消费当前 active requirement、cycle、workspace 和一致的 `development_session_id`；不重新读取或精确复验第 15 步 result、TRD、仓库、分支或工作树。
- **Agent 与 session**：以 `rule_retrospective_<ID>` 建立独立负责人 conversation，首次 Agent 调用前将该 key 的 Claude session alias 绑定为同一 `development_session_id`，公共循环因而恢复原开发 session。初始 prompt 首行是 `/session-rule-retrospective 本次开发会话`；`completed` 允许规则变化或 no-change，`continue`、`blocked` 沿用公共语义。
- **结果与恢复**：`outputs` 恒为 `[]`，success 先写 `steps/requirements/<ID>/16.json`，再推进 `requirement:17_commit` / step 17；blocked 保留当前节点、原 session alias 和独立 conversation。result→state 中断只补状态，推进后不需要工作区、Git、Agent 或模型。第 16 步不建立 Git baseline，也不限制规则文件结构；第 17 步负责读取实际变更并提交。
- **自动化与历史**：现行本体 7 项、CLI 4 项，共 11 项；全量 282 项、`compileall`、`git diff --check` 通过。真实 `step01-mendmark` 曾复用 development session `e6bd1b82-39f9-41b2-9cc9-a69b281015dc` 完成规则复盘并新增 `.claude/rules/frontend-playwright-container.md`。旧实现的三仓提前提交失败、`git reset --mixed` 现场恢复和 Git-visible baseline 是历史事实，不再是现行 success 条件，也不会由现行代码重复核验。
### 第 17 步：统一提交需求变更

- **能力与 session**：在产品根通过公共 `run_agent_decision_loop` 调用 `commit-changes`，使用独立的 `requirement_commit_<ID>` Agent session 和负责人 conversation。初始 prompt 只调用一次 Skill，交付需求标识、标题、有序仓库清单、统一分支和已完成开发验收的事实；不传开发历史或 TRD 全文，也不重新验收。
- **输入与边界**：信任当前提交节点的前序交接，读取 active requirement/cycle、统一需求分支和各仓 `base_sha`，不读取 `16.json` 或复验 development/retrospective alias。cycle 中的 `development_session_id` 用于拒绝提交 alias 错绑开发 session。Python 核验有序仓库白名单、仓库自身 top-level、非符号链接路径、统一分支、`base_sha ≤ local main ≤ HEAD`（祖先或相等）、`HEAD == target`、无进行中的 Git 操作和包含未跟踪文件的 clean 状态。
- **执行与决策**：Agent 负责完整 diff、分组、精确暂存、创建提交及提交后核验；必要的产物准备和纯格式修复受实际授权范围约束。负责人只在这些提交职责内作出 `completed/continue/blocked`，不授权业务语义变更、重新开发验收、扩大范围、改写历史或绕过检查。Python 不读取完整 diff、不制作 fingerprint 或 index 快照，也不执行 Git 写操作；`completed` 后只有 dirty 时向同一 session 发出 repair，Git 边界冲突则保留现场并失败。
- **结果与恢复**：fresh 全仓 clean 时不调用 Agent 或负责人，记录当前 HEAD 为 `tip_sha`。init 后立即保存提交 session，continue、repair、blocked 解除及 retry 均复用该 session；通用 conversation 结构和恢复锚点由公共循环模块统一校验，残缺锚点不可盲目重跑，仅保留初始指令且尚无 session 事实的 init 前失败可以重入。success 写 scoped `17.json` 的 `name/path/base_sha/tip_sha`，cycle 写 `{base_sha,tip_sha,merged:false}` 并推进 step 18；result→state 中断按当前 Git facts 补状态，已推进后的幂等调用不读取 Git 或会话历史。
- **使用与验证入口**：定向测试、恢复合同和历史兼容说明见 [第 17 步说明](../pcm-demo/steps/step_17_commit/README.md)。

### 第 18 步：程序化合并并完成需求

- **执行方式**：已实现为确定性 Python/Git 步骤，不调用 Claude Agent SDK、AI 决策模型、Skill、session 或 conversation。
- **输入**：读取当前 active requirement、cycle、`applicable_repositories`、工作区仓库路径和 scoped `17.json`。保留前序步骤、需求、适用成功状态及无 blocked/error 的检查，统一分支和逐仓名称、路径、base/tip 须与当前 cycle 一致；不校验展示用的 `name/summary/outputs`，允许增加无关元数据。
- **合并与恢复**：全部非 root 仓按权威顺序先处理、root 最后。合并与 no-op 均要求 `base_sha ≤ main ≤ tip_sha`（祖先或相等），原始 base 不改写；`main == tip_sha` 时只补记已合并，否则在未标记 merged 且 Git 边界成立时执行必要的 `git switch main` 和 `git merge --ff-only <tip_sha>`。合并目标使用已保存的 SHA，需求分支须仍指向该提交；分叉、main 超过 tip、引用变化或工作树与进行中操作不满足安全边界时，保留现场并失败。
- **清理与完成**：每仓合并后原子保存 `merged:true`；全部仓均到达保存 tip 且通过核验后，才按同一顺序安全执行 `git branch -d`，支持部分清理恢复。最终各仓须在 main、clean 且需求分支已删除，先写 scoped `18.json`，再把注册表项更新为 `completed`、`completion:{"step":18}`，清空 active requirement/cycle，返回 `phase_1:select_requirement` / step 13。result 已写而 state 未推进时，只读核验最终 Git 事实并补状态。
- **使用与验证入口**：Git 边界、恢复合同和定向测试命令见 [第 18 步说明](../pcm-demo/steps/step_18_merge/README.md)。

## 七、阶段二：全项目级集成产品体验审计与迭代

### 1. 进入条件、范围和运行条件

阶段一完成第 12 步需求注册表初始化，且当前已知正式范围内全部需求均完成第 13～18 步循环后，才可进入阶段二。进入前重新核验所有 `applicable_repositories`（其中包含 root）均处于清楚的 `main` 事实，且产品是完整可集成运行的版本。

外层编排器从产品定义、正式 Backlog、已完成 TRD、当前代码、路由、测试和可运行行为建立审计范围，至少包含：当前正式范围内全部主要用户任务、主要用户角色和跨页面闭环；多个真实产品表面或模块；可访问环境、项目专用且真实可登录的开发账号、可复位开发数据和清理方式；代表性桌面及窄屏和适用辅助技术路径；允许写入及禁止资金、外发、生产数据和其它高影响副作用；已有验收、UI/UX 框架和限制。

范围以用户任务、状态和风险表达，不以单页清单代替。单页面、单需求、首条验证切片或局部改动不满足阶段二入口，不能触发审计。缺少主要任务不可替代的环境、角色、数据、真实浏览器能力或安全边界时，先在当前节点补齐；无法取得时返回 `blocked`，不降级成静态审查。

### 2. 独立 SDK session 执行完整审计

外层在独立的 Claude Agent SDK session 中显式调用一次 `product-experience-audit`，输入上述完整范围、运行条件、`applicable_repositories` 中各仓库的 `main` 版本事实和现有证据。每次审计轮次只针对一个清楚的完整集成版本；这些适用仓库的 `main` commit SHA 共同构成 `version_fingerprint`。

Skill 从真实任务出发执行声明范围内的动态审计，实际读取代表性截图并收集相称的交互、状态、网络或可访问性证据。它只返回经核验候选、重复或未纳入项、覆盖缺口和高影响边界；不修改业务代码、产品定义、TRD 或 canonical Backlog，不创建正式需求或 ID，不暂存、提交或自动串联其它能力。PCM 将原始输出引用、审计 session、版本指纹及四类结果保存到阶段二状态；这是外层运行证据，不要求 Skill 创建过程文档。

完整审计的完成条件是：实际覆盖当前正式范围内全部主要任务和多个产品表面/模块，且能明确区分已覆盖范围、候选、重复项、覆盖缺口和高影响边界。只浏览入口、只看截图、只走 happy path，或仅依据单需求证据均不算完成。

### 3. 外层分流、需求化和入池

审计 Skill 结束后，外层调度会话基于审计证据、已有 Backlog 和产品事实逐项分流，并保存 `candidate_routing`：

- 已有需求、同一用户障碍或共同根因已有归属的，记录重复或向已有活动项补充证据，不新建需求；
- 误判、没有用户影响依据、纯主观偏好、价值或时机不足的，记录不纳入及理由；
- 证据不足或有覆盖缺口的，先补齐环境、身份、数据或动态证据后再判断，不把疑点写入正式 Backlog；
- 能以删除、合并、减少步骤、调整默认值或复用现有模式解决的，优先需求化最小可验证改动；
- 证据充分、用户结果和验收方向清楚的 Bug、可用性缺陷、适配性/可访问性问题和边界明确的改进，进入正式需求化；
- 改变产品目标、核心任务、品牌方向、安全、隐私、不可逆兼容或外部副作用的高影响边界，由 AI 决策模型基于事实决定范围、处理路径或不纳入理由并记录。AI 不能安全决定或资源不足时，只有不可替代外部资源缺失才返回 `blocked`；不新增人工审批节点。

需求化由外层完成，不由审计 Skill完成。单个内聚候选可按既有 Backlog 结构形成正式需求；需要合并、拆分、排序或重算依赖时，外层显式调用 `requirement-breakdown`；需要更新权威产品定义时，外层显式调用 `project-intake`。候选在用户结果、范围、证据、依赖和验收方向齐全前不得获得正式 ID。

符合准入条件的候选在根仓库最新 `main` 上通过一次短期入池分支写入正式 Backlog：创建分支，新增具有稳定 ID、标题、范围、依赖和验收方向的正式需求内容，检查依赖和顺序，调用 `commit-changes` 精确提交，再显式合并回根 `main`。外层保存入池分支、提交、合并和工作树检查，并持久化“正式需求 ID → 原审计候选”映射作为 `pooling_evidence`。入池仅创建后续可选择的需求，不创建活动 TRD、代码分支或完成状态。

### 4. 复用需求循环、针对原发现回归和完整复审

一批已入池的正式需求先按第 12 步同样的静态解析、哈希和 Python 动态状态语义原子增量加入既有需求注册表，保留所有既有需求的动态状态。随后需求循环不接收调用方指定的需求参数，而是每次由第 13 步从注册表确定性选择下一条可开发需求；第 18 步完成后，外层依据实际完成的正式需求 ID 查询 `pooling_evidence` 中的候选映射，再执行对应原发现回归。该增量协调和映射边界在阶段二实现时落实；当前不提前建立公共协调器。修复期间仍不调用 `product-experience-audit`，也不回写已归档的历史需求。

每个修复完成后，外层针对原候选执行回归：重走原复现任务、受影响状态及相邻跨页面路径，核验原障碍已消失且未引入新的任务断点。该回归证据保存至对应候选分流记录；已有单元测试、单需求验收或实现者结论不能替代它。

一批已入池需求完成及其原发现回归后，使用修复后 `applicable_repositories` 中各仓库的 `main` 版本指纹开启下一审计轮，在新的独立 SDK session 再次执行完整产品审计，覆盖最初全部主要任务和本轮受影响任务。新出现且符合政策的候选继续分流、入池和开发；重复项、不纳入项或不阻断完成的设计机会不触发无穷循环。新发现关键覆盖缺口必须补验，不能复用旧版本证据。

### 5. 阶段二完成条件

阶段二只有同时满足以下条件才成功结束：

1. 最新完整审计版本来自 `applicable_repositories` 中各仓库清楚的 `main` 事实，并已覆盖当前正式范围内全部主要用户任务以及多个产品表面/模块；
2. 适用动态任务已在真实浏览器和真实开发/测试服务执行，主要界面和关键状态有实际读取的代表性截图和相称动态证据；
3. 经核验候选、重复项、未纳入项、覆盖缺口和高影响边界均已保存并完成分流；
4. 所有自动入池的正式需求均已增量加入需求注册表并完成第 13～18 步，并通过针对原发现的体验回归；
5. 最后一轮完整复审没有新增符合需求化政策的候选，也没有未处理的高信心阻断或高优先级问题；
6. 与主要任务有关的环境、角色、数据、视口、辅助技术和动态证据覆盖缺口已经关闭；
7. `applicable_repositories` 中各仓库均位于预期 `main`，工作树无意外变更，最终结果和仍适用的限制已经汇总。

阶段二完成只表示当前正式范围内的完整集成体验已按当前事实收束，不代表产品永远没有新的改进机会，也不以未来人工反馈降低本阶段标准。

## 八、循环、结束和运行方式

PCM 先执行一次第 12 步初始化需求注册表，再以第 13～18 步完成阶段一，随后运行阶段二；阶段二新入池需求先增量协调进注册表，再复用第 13～18 步，而非在审计 Skill 中直接修复：

```python
class StopRun(Exception):
    def __init__(self, result):
        self.result = result


def require_success(result):
    persist_node_result(result)
    if result.status != "success":
        raise StopRun(result)
    return result.output


def run_all():
    try:
        require_success(run_phase_one_until_no_known_formal_requirement())
        require_success(enter_phase_two())

        while True:
            audit = require_success(run_full_product_audit_in_independent_session())
            routed = require_success(route_audit_candidates(audit))
            require_success(resolve_required_coverage_gaps(routed))
            pooling = require_success(
                productize_and_pool_eligible_candidates(routed)
            )
            require_success(
                reconcile_pooled_requirements_into_registry(pooling)
            )

            while has_pending_pooled_requirement(pooling):
                completed_requirement_id = require_success(
                    run_next_requirement_cycle_steps_13_to_18()
                )
                require_success(
                    regress_original_audit_finding(
                        pooling.candidate_for(completed_requirement_id)
                    )
                )

            if phase_two_completion_conditions_met(
                audit, routed, pooling
            ):
                return success_result()

    except StopRun as stopped:
        return stopped.result
```

所有节点统一返回 `success`、`blocked` 或 `failed`。单步入口只对显式的运行时重试请求有界重跑当前步骤两次；完整编排复用同一瞬时信号语义，而不把重试意图写入三态结果或持久化 state。当前只有 Claude Agent SDK 执行通道故障设置该请求；业务 `blocked`、普通 `failed`、AI-compatible 裁决失败、本地合同错误和取消直接停止。第三次仍请求重试时，`require_success()` 原子保留最终 `failed` 并停止，不继续候选分流、Backlog 入池、需求开发或回归；重试不放宽任何节点完成条件。

项目最终结束的最低条件是阶段一和阶段二均完成：不存在仍应开发的正式需求；所有纳入范围的需求状态与代码事实一致；`applicable_repositories` 中各仓库均在预期 `main` 且工作树清楚；适用的最终安装、构建、测试、启动和真实联调通过；关键用户流程浏览器验收及阶段二最终完整审计通过；适用数据基线与当前版本一致，接手者能按说明单入口初始化、逐角色登录并完成主要任务，明确重置可恢复完整起点，所需文件与对象存储共同可用，审计修复已同步受影响的恢复证据；最终结果和未解决限制已汇总。项目最终检查属于总流程收口，不新增复杂业务步骤编号。

PCM Demo 支持一键、单步、区间和恢复运行，并复用同一批节点函数：

```bash
# 单独验证步骤节点
python -m steps.step_02_project_intake --run-id <run-id>

# 从产品初稿完整执行阶段一和阶段二
python run_all.py \
  --product-draft "../docs/prd/修迹-产品需求文档-v1.md" \
  --workspace-root "/path/to/products"

# 从阻塞或失败的 phase/current_node 恢复
python run_all.py --resume <run-id>

# 调试阶段一步骤区间，或指定阶段二节点
python run_all.py --run-id <run-id> --from-step 11 --to-step 15
python run_all.py --run-id <run-id> --from-node phase_2:audit
```

### 步骤耗时观测

Demo 将步骤生命周期与 Claude Code 调用计时分开：`agent_elapsed_seconds` 累计各次主调用的已知执行区间，不包含调用外的负责人决策、Python 核验、10/30 秒退避和停机等待；`wall_elapsed_seconds` 持久化步骤首次开始到首次成功结束的自然时间跨度，包含这些等待。第 1～12 步按项目、第 13～18 步按需求 ID 和步骤编号区分；每次真实调用、continue、修复和恢复均保留独立区间，成功复用不新增虚假区间或重置首次完成数据。

计时独立保存在 `runs/<run-id>/timings.json`，程序只读取和写入 `schema_version: 2`，时间戳统一北京时间 `+08:00`。新增 Agent 执行记录保存 `task/model/effort` 与原始 `usage/model_usage/total_cost_usd`；实时结果回调和最终返回更新同一记录，不重复计数。AI-compatible 的主请求与 JSON 修复请求分别写入同一步骤的 `ai_executions`，不计入 Agent 执行时间。当前单输入 `query()` 每次独立计量，`model_usage` 包含子代理、`usage` 只覆盖主循环，不重复相加；Responses 的缓存和推理 token 属于明细，不再加到总数上。缺失或中断未取得的用量保持未知，不根据当前配置补造历史。费用是 SDK 估算，不作为订阅扣费事实。可观测中断记录时刻，不可捕获退出保持未知；缺口仅以步骤级提示说明，不重复业务适用性与复用布尔。程序不转换旧计时文件，不自动迁移、归档或删除旧数据；不在当前 run 计时读写路径上的旧数据原样保留。若旧格式 `timings.json` 实际阻碍所需新版记录，先确认没有旧进程正在写入该 run，再只移除这一份冲突文件，不批量清理，也不动 `state.json`、步骤 result 或 `conversations/`。计时不可用只警告，不改变业务三态、prompt、负责人裁决、恢复和退出码。字段定义与存储策略见 [计时记录与字段说明](../pcm-demo/docs/timing.md)，不新增业务节点或外部监控服务。

## 九、停止条件

出现以下情况时保存 `phase`、`current_node`、已完成范围、证据和继续命令并停止：

- 缺少模型和当前环境无法取得的不可替代外部资源、账号、服务、设备、授权或数据：返回 `blocked`；
- Git 分支、提交、合并、工作树、版本指纹、候选归属或入池证据冲突或不清楚；
- 测试、构建、真实联调、浏览器验收、审计回归或完整复审仍失败；
- 主要任务缺少真实环境、测试身份、可复位数据、真实浏览器或安全边界，且不能补齐；
- 模型、Claude Agent SDK、子进程、必要工具、状态持久化或结构化输出持续执行失败；
- 当前节点无法在已有事实内安全完成。

除不可替代外部资源外，上述情况返回 `failed`，修复现场后重试当前节点。高影响取舍、候选分流和产品化由 AI 决策模型依照事实完成，不作为 `blocked` 或人工审批节点。停止结果必须说明当前阶段和节点、已完成范围、阻塞或错误、已尝试动作、保留现场、证据缺口和继续命令。
