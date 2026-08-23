# PCM 程序化调度的 AI Agent 产品开发流程

> 本文是 [`AI Agent开发流程设计.md`](./AI%20Agent开发流程设计.md) 的 PCM 自动化版本。
>
> 人工版由人负责选择能力、传递上下文、判断结果和推进步骤；PCM 版由 Python 程序完成这些调度工作。两者使用相同的项目规则、Skills、Git 边界和完成标准，不重新定义各 Skill 的职责。
>
> 本文先服务于 PCM 前置 Demo。正式 PCM 系统可以基于 Demo 的真实结果重新设计状态、持久化、权限、调度和产品界面，不要求直接沿用 Demo 的代码结构。

## 一、目标

PCM 自动化流程接收一份产品初稿；资料不足时先形成产品初稿，然后自动完成：

```text
产品初稿
→ 建立产品项目工作区
→ 产品定义
→ 基础工程选型
→ 基础工程组装
→ 项目准备核验
→ 基础工程项目化
→ 总体技术方案
→ 首次提交适用仓库
→ 工程架构和 UI/UX 框架
→ Backlog 拆分
→ 阶段一：逐需求形成 TRD、实现、验证、状态收尾、复盘和合并
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
- `trd-design` 与 `dev-workflow` 共同保证单个正式需求的产品体验设计、真实运行、浏览器交互和真实渲染结果验收；阶段一不调用 `product-experience-audit`；
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

不单独建设复杂的回退、补偿或状态转移模型。步骤内部可以循环调用、修正和重新验证，但对外只暴露上述结果。审计 Skill 回复中的“已完成”“部分完成且有覆盖缺口”或“不适用”是审计内容，不会成为外层第四种 `status`。

### 4. AI 负责全部可完成的语义决策，程序负责确定性操作

AI 决策能力代替人工调度者处理流程中所有能够基于当前输入、项目事实、可用工具和已提供资源完成的产品、技术、文档、流程及执行取舍，例如：

- 从产品初稿提取当前选题名和项目文件夹名；初稿未明确文件夹名时，根据选题生成稳定的小写 kebab-case 名称；
- 回答 Skill 或 Agent 提出的澄清、确认和方案选择问题；
- 判断文档是否满足当前步骤完成条件并批准定稿；
- 选择产品范围、技术方案、实现方式和非阻断建议的处理结果；
- 判断是否继续当前会话、修正当前步骤产物或结束当前步骤；
- 从 Backlog 选择下一个满足依赖的需求。

存在多个合理方案、资料歧义或重大取舍时，AI 仍应选择并记录理由，不因需要判断而转交开发者。只有缺少当前资源清单之外、模型与当前环境无法取得的不可替代外部资源时才返回 `blocked`，例如第三方账号、付费服务、客户私有数据、专用设备、外部授权或线下动作。输入不完整、状态冲突或本地现场无法确定性继续属于 `failed`，修复输入或现场后重试当前步骤。

Python 程序直接负责：

- 校验项目文件夹名为单段小写 kebab-case，并根据配置的产品工作区根目录计算最终路径；
- 对配置的模板仓库执行 Git 浅克隆、记录分支和 commit、清理上游 Git 历史、初始化产品文档目录并原子发布工作区；
- 读写运行状态；
- 创建和检查目录；
- 调用 Claude Agent SDK；
- 执行 Git、测试、构建和启动命令；
- 保存步骤输出和会话 ID；
- 判断命令退出码、文件存在性和仓库状态；
- 在阻塞或失败时停止流程。

AI 不能用口头结论代替真实文件、Git、测试、构建、服务或浏览器证据。

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

PCM Demo 只保存支持继续运行所必需的状态：

```json
{
  "run_id": "20260816-153000",
  "status": "running",
  "input": {
    "type": "product_draft",
    "source_path": "/absolute/path/to/产品初稿.md",
    "source_sha256": "<sha256>",
    "content": "<完整 UTF-8 初稿内容>",
    "published_path": "/products/family-meal-planner/docs/产品初稿.md"
  },
  "project": {
    "topic_name": "家庭食材管理与一周膳食计划系统",
    "project_directory_name": "family-meal-planner",
    "extraction": {
      "directory_name_source": "generated",
      "reason": "初稿未提供仓库名，根据选题生成"
    }
  },
  "workspace": {
    "root": "/products",
    "root_source": "PCM_WORKSPACE_ROOT",
    "staging_path": "/products/family-meal-planner.pcm-tmp-20260816-153000",
    "final_path": "/products/family-meal-planner"
  },
  "template": {
    "repository": "<configured-template-repository>",
    "remote_url": "<configured-template-repository>",
    "default_branch": "main",
    "actual_branch": "main",
    "commit_sha": "<sha>"
  },
  "publication_phase": "git_initialized",
  "initialization_evidence": {
    "template_capabilities_present": true,
    "upstream_git_removed": true,
    "docs_reinitialized": true,
    "draft_hash_matches": true,
    "source_draft_unchanged": true,
    "renamed_to_final_path": true,
    "root_git_initialized": true,
    "root_git_is_final_path": true,
    "root_git_initially_had_no_commits": true
  },
  "applicable_repositories": ["root", "frontend", "backend"],
  "repositories": {
    "root": {
      "path": "/products/family-meal-planner",
      "branch": "feat/req-002",
      "worktree_clean": true
    },
    "frontend": {
      "path": "/products/family-meal-planner/frontend",
      "branch": "main",
      "worktree_clean": true
    },
    "backend": {
      "path": "/products/family-meal-planner/backend",
      "branch": "main",
      "worktree_clean": true
    }
  },
  "phase": "phase_1_requirement_development",
  "current_node": "requirement:19_merge_root",
  "active_requirement": "REQ-002",
  "completed_requirements": ["REQ-001"],
  "requirement_cycle": {
    "root_requirement_branch": "feat/req-002",
    "development_session": "session-id",
    "step_17_commit": "<step-17-root-commit-sha>",
    "step_18": {
      "outcome": "no_change",
      "commit": null
    },
    "step_19_merge_evidence": null,
    "return_node_after_completion": "phase_1:select_requirement"
  },
  "claude_sessions": {
    "project_intake": "session-id",
    "REQ-002:trd": "session-id"
  },
  "phase_two": null,
  "decision_conversations": {
    "project_intake": {
      "path": "conversations/project_intake.json",
      "turn": 3
    }
  },
  "blocked": null
}
```

上例是第 18 步已经得到 `no_change`、准备执行第 19 步的阶段一快照；初始化证据只记录首次发布事实，`repositories` 始终反映恢复时重新核验的当前仓库状态。未进入阶段二时 `phase_two` 必须为 `null`。

在阶段二审计和候选分流节点中，`requirement_cycle` 为 `null`；阶段二只保存当前审计轮和候选处理所需的最小状态：

```json
{
  "phase": "phase_2_full_product_audit",
  "current_node": "phase_2:route_candidates",
  "applicable_repositories": ["root", "frontend", "backend"],
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

上例是全项目审计已成功并原子推进到候选分流节点的阶段二快照，因此审计结果已经存在，而 `candidate_routing` 和 `pooling_evidence` 仍为 `null`；它们只在各自节点成功后写入并推进到下一节点。

不适用的交付单元不进入 `applicable_repositories`，并在对应步骤结果中显式记录 `not-applicable`；后续版本指纹、分支、验证和工作树检查只遍历该列表。阶段二处理已入池需求时临时使用 `phase: phase_2_requirement_remediation` 和 `requirement_cycle`，并将 `return_node_after_completion` 记录为 `phase_2:regress_and_reaudit`；第 19 步完成后返回阶段二，而不是重新进入阶段一选取普通需求。

恢复与幂等规则：

1. 每个节点开始前保存 `phase`、`current_node` 和已核验输入；节点成功后原子保存输出、事实证据和下一节点；阻塞或失败时保存原因并退出。
2. 使用 `--resume <run-id>` 加载原工作区和状态；恢复时只重跑当前节点，先重新核验文件、分支、提交、工作树和外部条件，不依据历史文字直接跳过。
3. 已有 Claude Agent SDK session 时优先恢复：第 13 步恢复 TRD session，第 15 步和第 18 步恢复同一 `development_session`。第 18 步恢复前必须确认根仓库仍是同一需求分支，且 diff 仅允许位于 `.claude/rules/`。
4. 第 17 步以根需求分支上的状态同步提交为幂等锚点；第 18 步只接受 `no_change` 或 `committed` 两种结果：前者不提交，后者记录精确提交；两者成功时都原子推进 `current_node` 到第 19 步。第 19 步以根 `main` 合并提交和根仓库及适用交付单元的分支、提交、工作树检查作为合并证据。已存在且与记录一致的事实可确认成功，冲突或归属不明则返回 `failed` 并保留现场。
5. 阶段二每轮审计先记录 `applicable_repositories` 中各仓库 `main` 的版本指纹和独立 SDK session。相同且工作树清楚的指纹恢复原审计或读取已持久化结果，不重复制造候选；修复合并后版本指纹变化，才建立新的全项目复审轮次。
6. 候选分流和入池均保存证据引用。恢复时按候选的稳定事实、已有归属和正式 ID 检查，已入池的候选不得再次分配 ID；入池分支、提交或合并证据冲突时返回 `failed`，不猜测补写 Backlog。
7. Claude Agent SDK 的多轮上下文由其 session 保存，状态只记录稳定的领域键和 session ID；AI-compatible 决策接口按领域键将完整、脱敏的编排消息历史原子写入 `runs/<run-id>/conversations/<key>.json`，每轮携带该历史继续调用。不同阶段和活动需求使用独立历史，`state.json` 只记录文件引用和当前轮次。
8. 每一步的实际输入和产物交接从前一步 `steps/<step>.json` 的 `outputs` 读取并核验，不从固定路径猜测；完整编排历史只保存当前流程所需的脱敏内容，不保存密钥、完整环境变量或无关工具日志；首轮不建设数据库、向量记忆或摘要系统。
9. 第 1 步恢复时重新核对产品初稿哈希、项目目录名、独立工作区根、配置的模板来源、临时和最终目录以及根仓库事实；只有临时目录能由状态证明属于同一 run 且 clone 完整，或最终目录能由发布证据证明属于同一 run 时才允许续接。
10. 第 1 步最终目录、发布证据和零提交根仓库证据一致时可确认既有成功；最终目录已发布但根 `.git/` 缺失时续接 `git init -b main`；根仓库已有 commit、临时和最终目录同时存在、目录归属不明或证据冲突时返回 `failed` 并保留现场。

## 五、项目初始化流程

### 第 0 步：形成产品初稿

- 能力：`pcm-product-factory`，或直接使用用户提供的完整初稿。
- 输入：项目选题、目标市场和已有资料。
- 输出：可供 `project-intake` 使用的产品初稿。
- 完成条件：产品方向明确，初稿包含基本目标用户、核心价值和功能轮廓。
- 自动化说明：只有一个简短选题时执行；输入已经足够完整时可无副作用跳过。

### 第 1 步：建立项目工作区

- 输入：产品初稿；运行 ID；产品工作区根目录；从配置读取的模板仓库。Demo 通过 `--workspace-root`、进程环境或 `pcm-demo/.env` 的 `PCM_WORKSPACE_ROOT` 取得根目录，优先级依次降低；模板仓库由 `PCM_TEMPLATE_REPOSITORY` 读取，单次运行不能覆盖。
- AI 输出：从初稿提取 `topic_name` 和 `project_directory_name`。后者必须是单段小写 kebab-case；初稿没有明确名称时允许根据选题生成，并记录生成理由。
- 模板：使用 `PCM_TEMPLATE_REPOSITORY` 配置的模板仓库默认分支最新内容，不由 AI 或单次运行更换来源。
- 执行动作：
  1. 在产品工作区根目录中计算最终路径 `<root>/<project_directory_name>` 和同级临时路径 `<root>/<project_directory_name>.pcm-tmp-<run-id>`；
  2. 使用 `git clone --depth 1` 将配置的模板克隆到临时路径，记录默认分支、实际分支和 commit SHA；
  3. 核验模板关键能力存在后，删除临时目录中的上游 `.git/`，清空并保留 `docs/`，将输入初稿按原始字节写为 `docs/产品初稿.md`；
  4. 核验上游 `.git/` 已删除、`docs/` 只包含产品初稿、初稿哈希一致、源初稿未改变且模板关键能力仍存在；
  5. 全部发布核验通过后，将同级临时目录原子重命名为最终路径；
  6. 在最终项目根执行 `git init -b main`，只建立根仓库边界，不执行 `git add`、`git commit` 或 push；
  7. 核验最终目录的 Git 根就是自身、当前分支为 `main`、尚无 commit，并记录根仓库初始化证据。
- 输出：产品项目根由 `state.workspace.final_path` 记录；步骤结果 `outputs` 记录相对于该根的 `docs/产品初稿.md`。
- 完成条件：最终目录独立、可操作，位于配置的独立产品工作区根中；模板来源和 commit 可追溯且未误带上游 Git 历史；最终项目根已经初始化为 `main` 分支的独立 Git 仓库但尚无 commit；初始化后的 `docs/` 只含当前产品初稿，状态和文件事实一致。
- 自动化说明：AI-compatible 调用使用 Responses API 的严格 JSON Schema；第 1 步 prompt 明确只允许 `topic_name`、`project_directory_name`、`directory_name_source`、`reason`、`blocked_reason` 五个字段，并禁止 Markdown、代码围栏、YAML 或 JSON 之外的文本。服务不支持该协议或结构不符时明确失败，不回退到 Chat Completions、不增加宽松解析或额外模型重试。Git、路径、清理、哈希、发布和根仓库初始化由 Python 程序确定性执行。最终路径必须原先不存在，不以复制少量能力文件代替完整模板 clone。
- 阻塞与失败：缺少不可替代的模板仓库读取权限时返回 `blocked`；初稿无法确定选题、工作区根位于当前能力仓库内部、目录归属不明、AI API、结构解析、Git 工具、网络、clone、清理、写入、核验、rename 或根仓库初始化错误返回 `failed`。失败时保留现场；若原子发布后 `git init` 中断，仅在最终目录与当前 run 发布证据一致时续接根仓库初始化，不自动删除或覆盖。

### 第 2 步：项目需求与产品定义

- 能力：`project-intake`。
- 输入：第 1 步发布的项目工作区、工作区中的产品初稿、项目规则与配置，以及当前可用外部资源清单。
- 执行动作：
  1. 在项目工作区中通过 Claude Agent SDK 显式调用 `project-intake`；
  2. 不在步骤代码中重复设置 `permission_mode`、`tools`、`allowed_tools` 或 `disallowed_tools`，由项目 `.claude/settings.json` 及 Claude Code 默认设置加载语义统一决定权限和工具行为；
  3. Agent 提出问题、确认或取舍时，PCM 将 Claude Agent SDK 返回的本轮完整回答原样作为决策历史中的 `user` 内容交给 AI-compatible 决策模型，不再拼接步骤元数据、完成条件、项目文件全文、产物状态或其它程序内部上下文；只有当前回答未包含且决策确实依赖的流程外事实，才补充该项最小必要事实。决策模型处理所有能基于当前输入、工作区、工具和资源完成的决定，并把结果作为原人工调度者的等效授权返回原 Agent session，包括满足 Skill 对“开发者明确同意”的确认要求；
  4. 持续对话直至 Skill 完成产品定义产物，或因不可替代外部资源缺失而阻塞；
  5. 程序核验 Skill 规定的输出文件真实存在且可读。
- 输出：`project-intake` 生成的项目需求说明和产品功能说明，明确最终产品范围、非目标、用户语言、首次成功结果、复杂度取舍和需要尽早验证的高风险假设；同时保存 Claude Agent session ID、完整编排历史及步骤结果。
- 完成条件：目标 Skill 已加载并显式调用；目标用户、最终产品范围、核心流程、关键约束和待确认事项已经收敛；规定产物真实存在且可读；Claude session、完整编排历史和步骤结果均已持久化；没有外部资源阻塞。
- 自动化说明：第 2 步只负责产品定义，不决定具体开发排期。AI 可以提出合并或删除不必要复杂度，但不能因实现困难静默缩小最终范围，也不提前处理技术方案、Backlog 或实现逻辑。
- 阻塞与失败：只有缺少模型和当前环境无法取得的不可替代外部资源时返回 `blocked`；SDK、模型、Skill 加载、结构解析、文件读写、状态或对话历史持久化失败时返回 `failed`。
- 恢复：重新核验工作区输入和输出事实，优先恢复 `project_intake` Claude session，并加载同一领域键下的完整决策历史继续当前步骤；不把历史文字结论代替当前文件事实。

### 第 3 步：基础工程选型

- 执行方式：Python 将产品定义和 catalog 候选构造成 Pydantic 输入模型，使用代码内的 system prompt 调用 OpenAI Python SDK `responses.parse(..., text_format=FoundationSelectionResult)`，取得 Pydantic 输出后直接保存；不调用 `foundation-selection` Skill 或 Claude Agent SDK。
- 输入：第 2 步结果中记录的项目需求说明、产品功能说明，以及本次 `catalog.json` 中的前端和后端候选。system prompt 只描述选型功能、输入、输出和约束，不包含步骤编号、PCM、Skill 或其它外层编排背景，并要求严格 JSON、禁止 Markdown、代码围栏、YAML 或 JSON 之外的文本。
- 输出：Pydantic `FoundationSelectionResult`，其中 `frontend`、`backend` 分别为完整模板选择或 `null`；每个选择直接包含 `id`、`git_url`、`default_branch`、`path` 和 `reason`。程序使用 `model_dump()` 将该结果写入 `steps/03.json.template_selection`。
- 完成条件：SDK 成功返回 `output_parsed`，步骤结果已经写入，状态推进到 `project:04_assemble_foundation`。本步骤不获取、复制或组装模板，不初始化前后端仓库。
- 失败与恢复：输入文件、catalog、Pydantic 解析或 Responses API 调用失败时保存简短脱敏错误并停留在当前步骤；已有成功结果且状态已推进到第 4 步时直接复用，不建立模型 session 或额外恢复状态机。

### 第 4 步：组装基础工程

- 输入：只读取第 3 步成功结果 `steps/03.json`，以既有 `FoundationSelectionResult` / `TemplateSelection` 校验 `template_selection`；不读取 catalog、产品文档，不调用模型、Skill 或 Agent。状态必须位于 `project:04_assemble_foundation`，`workspace.final_path`、state 的根 Git 证据和现场必须一致，产品根仍为零提交 `main`。
- 执行动作：目标固定为 `frontend/`、`backend/`。每个目标只能不存在，或是非符号链接且唯一内容为普通 `.gitkeep` 的目录；空目录、额外内容、符号链接和既有工程一律拒绝。对唯一 `(git_url, default_branch)` 执行一次 `git clone --depth 1 --branch <branch> --single-branch`，核验 origin、分支和 HEAD SHA；选中的相对模板路径不得为空、绝对、含 `..`、逃出 clone 或指向符号链接，子树不得包含上游 `.git` 或任何符号链接。每个适用 payload 复制到同级 run-owned 临时根后，在 payload 内执行 `git init -b main`，核验 Git top-level 就是 payload 自身、分支为 `main`、HEAD 为 unborn、index 为空，并且至少存在一个不被自身 ignore 的可提交文件；所有 payload 均合格后才移除经核验的占位目录并以 `os.rename()` 发布。第 4 步不执行 `git add`、`git commit` 或 push。
- 临时与恢复：临时根固定为产品目录同级 `<project>.pcm-assemble-<run-id>`，只以 run ID、产品路径和步骤号的 marker 证明归属。仅当路径、marker 完全匹配且两端仍是占位或不存在时，才删除失败残留并 fresh 重试；未知残留和部分发布现场均保留并 `failed`。`null` 端只删除严格占位目录，原本不存在则无副作用。成功后核验每个适用端自身 top-level、`main`、unborn HEAD、空 index，不适用端不存在，核验 marker 后清理临时根；已有成功结果且状态已到第 5 步时，最小现场核验来源记录、上述仓库边界、目标和临时根后幂等复用，不重新 clone。
- 输出：`steps/04.json` 记录 `applicable`、实际 `outputs` 和 `assembly.frontend/backend`；每个适用端保存 `target`、`id`、`git_url`、`default_branch`、`path`、实际 `origin`、`branch`、`commit_sha`，不适用端为 `null`。成功推进 `phase: project_initialization`、`current_node: project:05_verify_readiness`、`step/current_step: 5`。
- 阻塞与失败：明确的模板仓库认证或读取权限缺失为 `blocked`；状态、目录、Git、来源、路径、复制、发布、清理和核验错误为 `failed`。步骤自行保存 result/state；入口只输出结果路径与退出码，不重复写第 4 步结果。
- 已验证：修迹 run 使用 GitLab SSH 模板成功组装前端 `vite-react-shadcn-spa`（`main` SHA `a31db6deb85ab29f2d2253413dd362293a96325f`）和后端 `fastapi-sqlalchemy-postgresql-async-api`（`main` SHA `49ff842fcd330387f2fbdd1e9a43884e05894697`）；两端均为自身 top-level 的 `main`、unborn HEAD、空 index 独立仓，产品根仍为零提交 `main`。首次 HTTPS 来源错误按 `failed` 保存且未覆盖 `.gitkeep`、保留临时现场；修正为 SSH 后同 run 核验 marker、安全清理并 fresh clone 成功。重复执行在 0.809 秒内幂等复用。

### 第 5 步：核验项目准备状态

- 能力：`project-readiness`。
- 输入：产品定义、基础工程选型结论、已组装工程和当前资源。
- 输出：项目准备清单。
- 完成条件：当前开发必需项均为 `ready` 或 `not-applicable`。
- 自动化说明：缺少可由本机生成的配置时在本步骤补齐；缺少不可替代外部资源时返回 `blocked`。

### 第 6 步：项目化基础工程

- 能力：`project-bootstrap`。
- 输入：基础工程、产品定义、基础工程选型结论和准备清单；已有项目可另外提供既有技术方案。
- 输出：完成项目身份、基础配置、文档和最小联调的工程。用户可见项目只落实已经确认的品牌、视觉和交互事实；尚无产品级体验方向时保持中性、可替换的基础样式，不把模板默认配色、字体、首页或组件外观认定为产品设计。
- 完成条件：适用安装、构建、测试、启动和基础联调通过，留下待提交变更。
- 自动化说明：发现模板残留或局部配置问题时在本步骤内继续修正和验证。

### 第 7 步：总体技术方案

- 能力：`solution-design`。
- 输入：产品定义、已组装并完成项目化的当前工程事实、开发约束和第 3 步已确认的基础工程选型。
- 输出：总体技术方案文件、Claude Agent session ID、完整编排历史及步骤结果。
- 完成条件：方案 Markdown 存在且可读，系统边界、主要技术选择、交付单元、跨单元协作、关键风险和未决事项已经确认，并与当前工程事实一致。
- 自动化说明：本步骤基于已组装和项目化后的工程事实进行总体设计，不重新进行模板选型或组装；文档、模型、文件或状态问题在本步骤失败，外部不可替代资源缺失时返回 `blocked`。

### 第 8 步：首次提交适用仓库

- 能力：这是第一次全仓提交检查和干净基线节点。Python 只执行确定性输入、状态及 Git 只读核验；存在未提交变更时，才在产品根创建一个 Claude Agent SDK session，显式调用 `commit-changes`。
- 输入：权威有序仓库严格为 `['root', *steps/04.json.outputs]`；每个权威路径必须是自身 top-level、`main` 的独立 Git 仓库。不从固定前后端目录、历史状态或 Agent 回复扩充该清单。
- 执行动作：Python 对每仓只执行 `git rev-parse --show-toplevel`、`git branch --show-current`、`git status --porcelain`。若全部干净，在创建 conversation/session 或写入 `running` 前零 Agent、零决策模型调用，直接成功并记录全仓干净基线。任一仓 dirty 时，初始 prompt 首行是 `/commit-changes`，只给仓库清单及边界；Agent 负责必要 Git 写操作，Python 不逐仓派发、不 `add`、不 `commit`、不 `reset`、`amend` 或 `rebase`。Agent 不得切换分支、改写历史或 push。
- 输出：`steps/08.json` 的 `outputs` 固定为空，并保存 `applicable_repositories` 和 `repositories` 列表；每项为相对 `path`、`branch`、`worktree_clean`。状态保存同样事实但路径为绝对路径，成功推进到 `project:09_engineering_architecture`。
- 完成条件：每仓自身 top-level、`main` 且 `status --porcelain` 为空。无需检查 HEAD、提交是否产生、提交数、父提交、SHA、marker、历史替换或根 tree。
- 恢复：`completed` 后 Python 只读复验；仍 dirty 则以固定 repair prompt 继续同一 session。`blocked` 后重读，已全干净直接成功，仍 dirty 才保存 blocked。恢复也先读现场，已全干净直接成功，仍 dirty 才恢复原 session。`failed` / `blocked` 的步骤结果不能当作成功；只有 `status=success` 可幂等复用。成功后的第 9 步状态若权威仓库变 dirty，拒绝复用，避免第 8 步替后续修改提交。
- 自动化说明：决策只有 `completed`、`continue`、`blocked`；不执行 push。第 8 步专属 17 项、公共循环 24 项、第 4/6/7 步回归 31 项、定向 74 项、全量 112 项测试通过；`compileall`、`git diff --check` 通过，IDE 无诊断，独立审查无高、中问题。
- 真实验证：当前合同已在真实 run `pcm-demo/runs/step01-mendmark` 和产品工作区 `/Users/zhou/resource/fireworks/ANDRSZAN/pcm-products/mendmark` 完成验证；run 目录名与 state 内历史 `run_id` 不一致是既有已知事实。权威仓库为 `root/frontend/backend`，第 4 步 `outputs` 为 `frontend/backend`；首次执行前三仓均为自身 top-level、`main`、dirty 且 HEAD 不存在。
- 环境恢复：首次执行只启动 `initialize_repositories` session `f6d42df8-13e5-437b-ada3-eef1015ecc87`。Agent 尝试内置 Explore 时遇到环境未识别模型 `gpt-5.6-sol[1m]`，无 Result、无 Git 变化，挂起进程停止后保存 session、conversation 和 init 证据；这是环境内部子代理问题，不是第 8 步业务或 Git 逻辑失败。仅在 Git 忽略的真实 run 历史中追加普通恢复指令“不要使用子代理/Explore，直接工具完成”，生产 prompt 和代码未改变，并恢复同一 session。
- 提交与决策：Agent 先创建 frontend `dbab574dbe4d83a02323a750afd04de007565ac5`、backend `9682be837759c20f1a9ebbdf8fa2cfc09c2768d4` 两个本地提交；随后针对根仓运行时产物和 `.agents/plugins/superpowers/.git` 请求决策。AI-compatible 负责人返回 `continue`，授权删除 61 个 `.in_use/*`、`.orphaned_at`、`.coverage` 运行时产物、补 `.gitignore`、移除嵌套 `.git`，并将 superpowers 作为普通受控插件快照而非 submodule 提交。root 创建 `02ba4c1`、`ae72c31`、`5eeeacd217bbd27e03483b1b6d32915c721aadd9` 三个本地提交；全程未 push。
- 完成证据：最终 conversation 共 7 条，角色顺序为 `system → assistant 初始 → assistant 恢复 → user → assistant continue → user → assistant completed`；Agent 正常 `success`，26 turns，约 `$1.859406`，session 不变。Python 只读 verifier 写入 `steps/08.json` success，result 保存相对路径、state 保存绝对路径，状态推进至 `project:09_engineering_architecture`。独立 Git 核验确认 root 3 commits、frontend/backend 各 1 commit，三仓均在 `main` 且 clean；当前合同允许每仓 0、1 或多个提交，不要求唯一无父提交。同 run 重跑直接 clean 幂等成功，conversation 仍为 7 条，未再次调用 Agent 或决策模型，SHA 不变。
- 证据边界：backend 提交摘要中的 Ruff、格式、build 通过和 `pytest` 14 passed、1 skipped（数据库集成测试需显式 `DB_*`）是 Agent 报告，不是 Python verifier 条件，也不改变第 6 步历史项目化验证。`step08-real-20260823-a/b` 继续仅是旧“唯一初始提交证明”合同历史；当前首次成功包含 run-local 恢复指令，不能宣称环境内部子代理问题已解决或无需恢复。

### 第 9 步：工程架构设计（按需）

- 能力：`engineering-architecture`。
- 适用：当前工程惯例不足以判断文件和依赖归属，存在跨模块、跨交付单元或共享边界不确定性，或已有结构明显漂移时。简单项目能够由现有结构稳定指导后续开发时，可以无副作用跳过，待真实需求暴露变化点后再执行。
- 输入：产品定义、总体技术方案和当前工程事实。
- 输出：工程架构文档。
- 完成条件：分层、模块边界、目录职责、依赖方向和演进条件能够指导后续实现。
- 自动化说明：文档在本步骤内持续修正；完成后对根仓库调用 `commit-changes`。

### 第 10 步：产品级 UI/UX 框架

- 能力：`ui-ux-framework`。
- 适用：项目尚无能够指导后续需求的产品级框架，现有框架明显失真，或当前问题会改变产品表面、主导航、Shell、全局视觉语义、共享组件语义或客户定制边界。
- 输入：产品定义、总体技术方案、工程事实和调用方提供的相关设计资料。
- 输出：按项目文档约定维护的产品级 UI/UX 框架，或明确的不适用结论。
- 完成条件：产品表面、信息架构、Shell、导航和跨需求体验约束已经确认；高影响决定已经取得确认；没有把单需求设计或页面实现混入框架。
- 自动化说明：这是按需的项目级能力，不是每个需求的固定前置步骤；适用文档完成后提交根仓库。

### 第 11 步：拆分 Backlog

- 能力：`requirement-breakdown`。
- 输入：产品定义、总体方案、适用的工程架构和 UI/UX 框架结论，以及当前工程事实。
- 输出：完整覆盖最终产品范围的 Backlog 总览和需求详情卡，以及由一个或多个完整正式需求组成的首条验证切片。
- 完成条件：需求具有明确产品结果、范围、依赖、验收方向和建议顺序；已检查可以合并、删除或推迟确认的复杂度；首条验证切片能够尽早验证关键假设，并明确尚未覆盖的最终范围。它不是 MVP、半完成需求、Mock 演示或范围缩减。
- 自动化说明：完成后提交根仓库，进入阶段一；首条验证切片只是 Backlog 的建议顺序，不触发产品体验审计。

## 六、阶段一：逐需求开发

阶段一只执行第 12～19 步。`trd-design` 与 `dev-workflow` 对每个正式需求完成需求级体验设计、实现和真实验收；不调用 `product-experience-audit`。首条验证切片、局部改动、单页面、单需求、内测或发布前这些局部时点均不单独触发审计。只有当前已知正式范围内全部需求完成第 19 步后，才进入阶段二。

### 第 12 步：选择需求并建立根仓库需求分支

- 输入：根仓库 `main` 的 Backlog、`applicable_repositories` 中各仓库的 `main` 基线和已完成需求。
- 输出：唯一活动需求、根仓库需求分支和开始前仓库事实。
- 完成条件：依赖满足、需求范围明确，根仓库从最新 `main` 建立正确分支。
- 自动化说明：AI 选择满足依赖且建议顺序最靠前的需求；Git 脚本记录 `root_requirement_branch`。

### 第 13 步：形成最终活动 TRD

- 能力：`trd-design`。
- 输入：活动需求、产品资料、总体方案、适用的工程架构和 UI/UX 框架结论、当前代码事实，以及其它相关产品或设计资料。
- 输出：可直接指导实现的最终活动 TRD 和 TRD session。
- 完成条件：范围、行为、技术方案、验证场景和需求级用户体验设计已经收敛；用户可见需求已检查能否删除或合并步骤、字段、决策和跳转，并明确用户术语、内容主次、主要行动、关键文案意图、状态与恢复。
- 自动化说明：`trd-design` 独立完成单需求体验设计。核心任务、信息架构、状态表达或视觉方向存在多个实质方案，且实现后返工成本明显时，外层允许在本步骤取得任务流、关键状态草图、可抛弃原型或真实项目窄范围预览等最低成本证据；不固定工具或过程产物。若 TRD 暴露跨需求产品体验骨架问题，外层可以在本步骤处理 `ui-ux-framework`，但不拆出审计步骤。活动 TRD 可在本步骤内修正，完成后精确提交根仓库需求分支。

### 第 14 步：建立代码仓库需求分支

- 输入：最终 TRD 和代码仓库 `main` 状态。
- 输出：所有受影响代码仓库的功能分支。
- 完成条件：受影响仓库从最新 `main` 建立正确功能分支；不受影响仓库不机械建分支。
- 自动化说明：脚本依据 TRD 和仓库事实执行，并记录各仓分支基线。

### 第 15 步：实现与验证

- 能力：`dev-workflow` 和按仓库调用的 `commit-changes`。
- 输入：最终活动 TRD、受影响仓库和当前开发环境。
- 输出：实现代码、测试、真实验证证据、代码仓本地提交和 `development_session`。
- 完成条件：`dev-workflow` 完成适用测试、构建、运行、联调、浏览器交互、实际读取的真实渲染结果验收及独立审查；受影响仓库变更已精确提交。
- 自动化说明：实现和验证问题在本步骤内持续修复。涉及 UI 时必须实际读取代表性截图判断任务简化、文案和视觉层级，不能以 DOM、组件代码或操作成功代替；无适用 UI 变化时不机械执行视觉检查。不可替代资源缺失时阻塞并保存开发 session。

### 第 16 步：合并代码仓库并在 `main` 最终验证

- 输入：受影响代码仓库的功能分支和验证证据。
- 输出：代码仓库 `main` 上的合并结果和最终验证结果。
- 完成条件：功能分支提交完整，合并成功，相关测试和检查在 `main` 上通过。
- 自动化说明：按仓库顺序执行；冲突、验证失败或仓库事实不清楚时停留在本步骤修复或返回 `failed`，不进入状态收尾。

### 第 17 步：同步需求最终状态并提交根需求分支

- 能力：负责活动文档维护的 Agent 和 `commit-changes`。
- 输入：代码仓库 `main` 的真实合并和验证结果。
- 输出：更新后的活动 TRD、Backlog 总览和需求详情卡，以及根需求分支提交。
- 完成条件：文档状态、代码结果和验证证据一致；状态同步变更已经精确提交到 `root_requirement_branch`，并记录 `step_17_commit`。
- 自动化说明：未完成或仍有阻塞时不得标记完成。当前需求若使首条验证切片闭环，本步骤同时只基于切片内各需求的 `dev-workflow` 证据记录已验证假设、实际结果、仍未验证范围及对后续产品定义、UI/UX 框架、Backlog 或顺序的影响；不调用 `product-experience-audit`，也不把切片结论表述为全产品结论。第 17 步提交是第 18、19 步恢复的固定锚点。

### 第 18 步：在原开发 session 复盘执行规则

- 能力：`session-rule-retrospective`、显式 Git 脚本和适用的 `commit-changes`。
- 输入：同一需求的 `development_session`、失败记录、修复过程、AI 决策记录和已核验的纠正证据。
- 执行动作：确认根仓库仍位于同一 `root_requirement_branch` 后，恢复原 `dev-workflow` Claude Agent SDK session 执行 `session-rule-retrospective`；程序只允许该次调用修改根仓库 `.claude/rules/`。
- 输出：必要的规则增量，或 `no_change`；有增量时输出同一根需求分支上的精确提交。
- 完成条件：复盘结果已通过 Skill 的准入和去重标准；无规则变更时记录 `step_18.outcome: no_change` 并成功结束且不提交；有规则变更时仅提交 `.claude/rules/`，记录 `step_18.outcome: committed` 和提交 SHA。
- 自动化说明：不创建复盘分支，不修改代码、Backlog、TRD 或其它文件。任何越界 diff、session 不可恢复或根分支事实冲突都返回 `failed`，不以新会话或新分支替代原会话。

### 第 19 步：最后合并根仓库并检查适用仓库

- 输入：已完成第 17、18 步的根仓库需求分支，以及 `applicable_repositories` 中各仓库的当前事实。
- 输出：根仓库 `main` 合并结果和全部适用仓库的全局状态检查证据。
- 完成条件：根需求分支最后合并到根仓库 `main`；根仓库及各适用交付单元的分支、提交和工作树均符合预期，并已保存 `step_19_merge_evidence`。
- 自动化说明：根仓库最后合并，确保最终文档和规则都建立在代码已合并且已验证的事实之上。成功后清理活动需求状态；尚有可开发正式需求时继续阶段一。

## 七、阶段二：全项目级集成产品体验审计与迭代

### 1. 进入条件、范围和运行条件

阶段一完成当前已知正式范围内全部需求的第 12～19 步后，才可进入阶段二。进入前重新核验根仓库及 `applicable_repositories` 中各适用交付单元均在清楚的 `main` 事实，且产品是完整可集成运行的版本。

外层编排器从产品定义、正式 Backlog、已完成 TRD、当前代码、路由、测试和可运行行为建立审计范围，至少包含：当前正式范围内全部主要用户任务、主要用户角色和跨页面闭环；多个真实产品表面或模块；可访问环境、虚构测试身份、可复位数据和清理方式；代表性桌面及窄屏和适用辅助技术路径；允许写入及禁止资金、外发、生产数据和其它高影响副作用；已有验收、UI/UX 框架和限制。

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

符合准入条件的候选在根仓库最新 `main` 上通过一次短期入池分支写入正式 Backlog：创建分支，新增 ID、总览项和详情卡，检查依赖和顺序，调用 `commit-changes` 精确提交，再显式合并回根 `main`。外层保存入池分支、提交、合并和工作树检查作为 `pooling_evidence`。入池仅创建后续可选择的需求，不创建活动 TRD、代码分支或完成状态。

### 4. 复用需求循环、针对原发现回归和完整复审

每个已入池的正式需求都从根仓库最新 `main` 完整复用第 12～19 步：新建活动 TRD、开发、代码合并、状态同步、原 session 规则复盘和最后根仓库合并。该复用期间仍不调用 `product-experience-audit`，也不回写已归档的历史需求。

每个修复完成后，外层针对原候选执行回归：重走原复现任务、受影响状态及相邻跨页面路径，核验原障碍已消失且未引入新的任务断点。该回归证据保存至对应候选分流记录；已有单元测试、单需求验收或实现者结论不能替代它。

一批已入池需求完成及其原发现回归后，使用修复后 `applicable_repositories` 中各仓库的 `main` 版本指纹开启下一审计轮，在新的独立 SDK session 再次执行完整产品审计，覆盖最初全部主要任务和本轮受影响任务。新出现且符合政策的候选继续分流、入池和开发；重复项、不纳入项或不阻断完成的设计机会不触发无穷循环。新发现关键覆盖缺口必须补验，不能复用旧版本证据。

### 5. 阶段二完成条件

阶段二只有同时满足以下条件才成功结束：

1. 最新完整审计版本来自 `applicable_repositories` 中各仓库清楚的 `main` 事实，并已覆盖当前正式范围内全部主要用户任务以及多个产品表面/模块；
2. 适用动态任务已在真实浏览器和真实开发/测试服务执行，主要界面和关键状态有实际读取的代表性截图和相称动态证据；
3. 经核验候选、重复项、未纳入项、覆盖缺口和高影响边界均已保存并完成分流；
4. 所有自动入池的正式需求均完成第 12～19 步，并通过针对原发现的体验回归；
5. 最后一轮完整复审没有新增符合需求化政策的候选，也没有未处理的高信心阻断或高优先级问题；
6. 与主要任务有关的环境、角色、数据、视口、辅助技术和动态证据覆盖缺口已经关闭；
7. `applicable_repositories` 中各仓库均位于预期 `main`，工作树无意外变更，最终结果和仍适用的限制已经汇总。

阶段二完成只表示当前正式范围内的完整集成体验已按当前事实收束，不代表产品永远没有新的改进机会，也不以未来人工反馈降低本阶段标准。

## 八、循环、结束和运行方式

PCM 先完成阶段一，再运行阶段二；阶段二新入池需求仍复用第 12～19 步，而非在审计 Skill 中直接修复：

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
            pooled_requirements = require_success(
                productize_and_pool_eligible_candidates(routed)
            )

            for requirement in pooled_requirements:
                require_success(run_requirement_cycle_steps_12_to_19(requirement))
                require_success(regress_original_audit_finding(requirement))

            if phase_two_completion_conditions_met(
                audit, routed, pooled_requirements
            ):
                return success_result()

    except StopRun as stopped:
        return stopped.result
```

所有节点统一返回 `success`、`blocked` 或 `failed`。`require_success()` 先原子持久化当前结果；任何非 `success` 立即停止外层运行，不继续候选分流、Backlog 入池、需求开发或回归，也不以循环重试掩盖阻塞和失败。

项目最终结束的最低条件是阶段一和阶段二均完成：不存在仍应开发的正式需求；所有纳入范围的需求状态与代码事实一致；`applicable_repositories` 中各仓库均在预期 `main` 且工作树清楚；适用的最终安装、构建、测试、启动和真实联调通过；关键用户流程浏览器验收及阶段二最终完整审计通过；最终结果和未解决限制已汇总。项目最终检查属于总流程收口，不新增复杂业务步骤编号。

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

## 九、停止条件

出现以下情况时保存 `phase`、`current_node`、已完成范围、证据和继续命令并停止：

- 缺少模型和当前环境无法取得的不可替代外部资源、账号、服务、设备、授权或数据：返回 `blocked`；
- Git 分支、提交、合并、工作树、版本指纹、候选归属或入池证据冲突或不清楚；
- 测试、构建、真实联调、浏览器验收、审计回归或完整复审仍失败；
- 主要任务缺少真实环境、测试身份、可复位数据、真实浏览器或安全边界，且不能补齐；
- 模型、Claude Agent SDK、子进程、必要工具、状态持久化或结构化输出持续执行失败；
- 当前节点无法在已有事实内安全完成。

除不可替代外部资源外，上述情况返回 `failed`，修复现场后重试当前节点。高影响取舍、候选分流和产品化由 AI 决策模型依照事实完成，不作为 `blocked` 或人工审批节点。停止结果必须说明当前阶段和节点、已完成范围、阻塞或错误、已尝试动作、保留现场、证据缺口和继续命令。
