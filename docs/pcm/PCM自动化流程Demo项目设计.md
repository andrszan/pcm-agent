# PCM 自动化流程 Demo 项目设计

> 本文定义正式 PCM 开发前的轻量 Python 验证项目。Demo 的目的不是提前实现正式 PCM，而是用可独立运行、可串联的一组脚本，真实验证 [`PCM 程序化调度的 AI Agent 产品开发流程`](../../.claude/PCM版AI%20Agent自动化流程设计.md)。
>
> 本轮已完成 Claude Agent 显式网关、三级模型映射、固定 model/effort profile、子代理模型同步和 resume 传递：配置、公共循环与固定 profile 定向 49 项、模型 profile 与需求循环定向 101 项、当前工作树全量 367 项 `unittest` 通过（49.802 秒），`compileall` 与 `git diff --check` 通过；中模型 + `high` effort 的公共 `run_claude()` 首轮和同 session resume 真实成功，init 均返回配置模型。未配置 `max_budget_usd`，未修改领域 prompt、步骤业务合同或历史 run。
>
> 第 14、15 步负责人上下文合同定向本体与 CLI 共 29 项通过；PCM Demo 当时工作树全量 359 项 `unittest` 通过（50.534 秒），`compileall common steps run_step.py run_all.py test_run_step_retry.py test_run_all.py`、相关 IDE diagnostics 与 `git diff --check` 通过。第 14 步只将注册表交接的完整 canonical Backlog 正文加入负责人 `<project_context>`，第 15 步只加入完整活动 TRD 正文；第 8、17 步和公共决策循环未修改。第 17 步继续通过公共 Agent 决策循环保存完整 conversation、处理 continue/blocked/completed和同session repair，同时不做 fingerprint 或 Git 内容取证。`run_step.py` 只对 Claude Agent SDK 执行通道故障产生的运行时请求按 10 秒、30 秒重跑当前步骤两次；任意 API 状态均可请求重试，业务 `blocked`、普通 `failed`、本地合同错误和取消不重试，且该请求不持久化。真实 `step01-mendmark` 已完成 BR-001 与 BR-002；BR-002 在旧 direct-run 期间缺少 decision conversation，该历史不能补造，未来需求按现行合同保存完整历史。
> 第 0～18 步均已完成代码与自动化；第 0～8、12～18 步已有适用的真实验证。第 9 步当前新版 prompt 合同仅完成自动化，尚未进行安全的 fresh 真实 Agent、负责人或 `/commit-changes` 集成；`step01-mendmark` 中保留的第 9～11 步 session、commit 与成功状态均属旧合同历史。第 12 步现行合同已用自由格式 Backlog 真实提取 `BR-AI-001`～`BR-AI-003` 并完成零模型幂等重跑；历史 `step01-mendmark` 的 14 项 BR 注册表属于旧三字段 source 合同。第 13～17 步完成 BR-001 的统一分支、活动 TRD、实现验证、规则复盘和提交；第 18 步已将 root/frontend/backend ff-only 到记录 tip、删除需求分支并把 BR-001 标记为 completed。旧 403、非 JSON、非法 completed 和旧 prompt 设计只保留为已修复的根因历史；`step08-real-20260823-a/b` 的 prompt、API、`.coverage`、授权循环和提交事实继续仅属于旧“唯一初始提交证明”合同的历史运行。

## 一、验证目标

给定一份现有产品初稿，Demo 最终验证以下完整流程：

```text
产品初稿
→ 建立独立产品项目工作区
→ 产品定义
→ 基础工程选型
→ 基础工程组装
→ 项目准备核验
→ 基础工程项目化与项目专属主题配色
→ 总体技术方案
→ 初始化并首次提交适用仓库
→ 必要的工程架构设计
→ 按需建立产品级 UI/UX 框架
→ 拆分 Backlog
→ 解析 Backlog 并初始化需求注册表
→ 阶段一：逐需求统一建分支、设计、实现、验证、规则复盘、提交和合并
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
- 第 1 步：从固定开发管理模板发布独立产品项目工作区，安装 Git 忽略且 `0600` 的根 `.env` 工作区工具配置，并初始化零提交根 Git 仓库；
- 第 2 步：显式调用 `project-intake`，通过公共 `AgentDecision` 循环收敛产品定义，并保存 Claude session 与完整决策历史；
- 第 3 步：将产品定义和 catalog 构造成 Pydantic 输入，使用代码内 system prompt 调用 `responses.parse`，将 `output_parsed` 直接保存为稳定选型结果；
- 第 4 步：只读取第 3 步结果，以浅 clone、来源核验、run-owned 临时 payload、拒绝上游 `.git`/符号链接、对每个适用 payload 执行 `git init -b main` 并核验自身 top-level、`main`、unborn HEAD、空 index、至少一个不被自身 ignore 的可提交文件后原子 `os.rename` 组装工程，保存实际来源和 Git 边界证据并推进到第 5 步；
- 第 5～7 步：接受上述适用子仓边界，持续在 `completed` 和 `blocked` 终止前复核 `main` / unborn / 空 index；只有 `status=success` 的结果可幂等复用，`failed` / `blocked` 结果不会阻断恢复；
- 第 8 步：先以 `['root', *steps/04.json.outputs]` 作为唯一权威仓库清单，只读核验每仓自身 top-level、`main` 和工作树；全部干净时零 Agent、零决策调用直接形成干净基线，存在未提交变更时才在一个产品根 Claude Agent SDK session 中显式调用 `commit-changes`，Python 不执行 Git 写操作，保存 `applicable_repositories` 和仓库干净事实；
- 第 2/5/6/7/8/9/10/11/14 步共用薄公共循环：每轮完整真实 Agent 回复均先进入负责人返回的 `AgentDecision(completed/continue/blocked)`，负责人相信 `completed` 后仍由步骤程序核验；新 conversation 保存动态 system snapshot，各步骤的 Git、输出与提交合同不进入公共循环；
- 第 9 步：必要的工程架构步骤，在单份根仓 `docs/design/工程架构设计.md` 中按每个包含业务代码且相关的适用交付单元分别闭合 Current/Target、职责/边界、依赖和代表性文件归属；严格消费第 8 步空 `outputs`、result/state 一致的合法有序 `applicable_repositories`，并在当前现场只读核验权威仓库；`completed` 后先 repair 固定文档，只有根仓存在且仅存在固定文档未提交变化时才在原 session 调用 `/commit-changes`。固定文档已 tracked 且全仓 clean 时直接完成，不制造无变化调用；
- 第 10 步：仅以第 8 步严格交接的 `applicable_repositories` 是否含 `frontend` 作为 Demo v1 适用性；不适用时按执行产物存在性拒绝并保持零 Git、Agent、负责人决策、LLM 配置和文档副作用。适用时按与第 9 步相同的按需 repair/提交条件处理唯一固定文档；负责人按新版 `ui-ux-framework` 合同要求适用的 App Shell Contract 闭合，区分 Current、已确认 Target、带依据和重议条件的默认 Target、具体待确认、偏差与非目标，不接受整份框架泛化待确认；
- 第 11 步：严格读取第 2/5/7/8/9/10 步交接，在单一 `requirement_breakdown` session 中以 `/requirement-breakdown` 生成唯一 `docs/backlog/backlog.md`；按需 repair 后只在固定文档造成唯一根仓未提交变化时调用 `/commit-changes`。负责人按体验决定状态区分相关 BR 约束与条件性迁移 BR：只有已确认 Target 的迁移同时具备既有表面演进、独立可观察用户结果和严格开始前条件时才创建迁移 BR/依赖，默认 Target 不单列迁移 BR或严格依赖。成功由严格 result schema、tracked 固定文档和当前全仓 Git 事实决定；Backlog 不写需求开发状态，成功进入第 12 步注册表初始化入口；
- 第 12 步：严格消费第 11 步完整 success，把自由格式 Backlog 交给 Responses/Pydantic 作为唯一语义提取路径，只输出 `id`、`title`、`order`、`depends_on`；Python 不解析 Markdown 排版，只校验非空 catalog、合法且忽略大小写唯一的 ID、数组物理顺序对应连续 `order`、依赖存在/不重复/不自依赖/无环，并以 Backlog 路径/SHA-256 初始化唯一需求注册表；不调用 Claude Agent、`AgentDecision` 或 Skill，不修改产品项目或执行 Git；
- 第 13 步：零 AI/Agent/Skill 的确定性选择，消费第 8 步仓库交接与当前 `state.requirement_registry`；不读取或按现行第 12 步 schema 复验历史 `steps/12.json` / `source`。fresh 全局预检后先写 active intent/cycle，再为全部适用仓建立 `req/<lowercase-id>`；success 只写 `steps/requirements/<ID>/13.json` 并推进 `requirement:14_trd_design`。后续节点保护只校验第 13 步拥有的活动需求、统一分支、仓库集合和每仓 `base_sha`，允许后续步骤在 cycle 追加自身证据；
- 第 14 步：采用与第 15 步一致的薄编排，只消费当前活动需求、cycle、workspace 和需求注册表已记录的 canonical Backlog 来源，首次持久化 `trd_path`，再通过 requirement-scoped `trd_design_<ID>` 公共循环显式调用或恢复 `/trd-design`；Python 读取完整 Backlog 正文放入负责人的 `<project_context>`，使其理解当前需求在全部需求中的位置、依赖和关系，不加入尚未生成的 TRD 正文或其它上游文档；Agent 按需读取其它项目事实和本需求真正适用的任意来源体验决定，在 TRD 中记录来源、范围、Current/Target、遵循或改变关系，默认 Target 还记录依据和重议条件；Python只核验指定 TRD 非空，不读取 Git或重复复验前序步骤，success 写 `steps/requirements/<ID>/14.json` 并推进 `requirement:15_development`；
- 第 15 步：只消费当前 active requirement/cycle/workspace、当前 requirement 的第 14 步 scoped success 与非空活动 TRD，在 `development_<ID>` session 中调用 `/dev-workflow`；Python 将活动 TRD 完整正文放入负责人的 `<project_context>`，不重复加入 Backlog 或其它上游文档；适用体验决定须映射到可观察结果、实现位置、真实浏览器与实际读取截图证据及实际结果，稳定偏差同步活动 TRD，截图不替代动态行为验证；负责人 completed 后 success 写 `steps/requirements/<ID>/15.json`、同步 `development_session_id` 并推进第 16 步；
- 第 16 步：采用薄编排，只消费当前 active requirement/cycle/workspace 与 `development_session_id`，以 `rule_retrospective_<ID>` 建独立负责人 conversation、预注册原 development session alias并调用 `/session-rule-retrospective`；允许规则变化或 no-change，success 写 `steps/requirements/<ID>/16.json`（`outputs: []`）并推进第 17 步，不读取 Git或建立 baseline；
- 第 17 步：只消费当前 active requirement/cycle/workspace、完整 scoped 第 16 步 success、统一需求分支和各仓 base，在产品根通过公共 Agent 决策循环调用 `/commit-changes`；保存完整 conversation，负责人处理 `continue/blocked/completed`，Python只核验白名单、分支、main/base、最终 clean 和 tips，写 scoped `17.json` 并推进第 18 步；
- 第 18 步：只读取当前 active requirement/cycle、权威仓库路径和 scoped 第 17 步 success 的必要字段；以确定性 Python/Git 按非 root 在前、root 最后的顺序执行或恢复 ff-only 合并，逐仓保存 `merged:true`，全仓到 tip 后统一安全删除需求分支，先写 scoped `18.json` 再完成注册表生命周期；
- `run_step.py` 对第 0～18 步提供单步运行入口；只有本次失败显式携带运行时重试请求时，才以相同 CLI 参数分别等待 10 秒和 30 秒重新运行当前步骤，最多三次总执行。当前请求只由 Claude Agent SDK 实际执行通道故障产生，任意 API 状态码、明确 `api_error` 终止、连接失败和未取得 Result 的 CLI 进程失败均可重试；业务 `blocked`、普通 `failed`、AI-compatible 裁决失败、本地合同错误、参数解析失败、未实现步骤和主动取消不重试。请求不写入 state/result/diagnostic/conversation，每次仍由步骤重新读取最新现场；第 13～18 步继续按当前 active/cycle 保护 scoped success，失败只有在 state 位于自身锚点时才能持久化，不得降级已推进状态。

当前代码已实现第 0～18 步；第 0～8、12～18 步已有适用的真实成功验证。第 9 步当前新版 prompt 合同尚未有安全的 fresh 真实集成，`step01-mendmark` 保留的第 9 步 success/session/conversation 仅是旧合同历史。BR-001 与 BR-002 均已完成第 13～18 步。BR-002 第 15 步先后暴露流断开、HTTP 500 和两次代码围栏 JSON；在当时旧的“任意非 `success` 均重试”策略下，CLI 以相同参数重新进入当前步骤并在第三次取得合法负责人 `completed`。该事实只记录旧策略下的运行结果，不定义现行重试范围。第 16 步复用 development session 完成规则复盘，第 17 步提交 root/frontend/backend，第 18 步 ff-only 合并并清理 `req/br-002`，state 返回 `phase_1:select_requirement` / step 13。

### 2. 从第 3 步起的重大变化

旧设计把第 3 步定义为“总体技术方案兼基础模板选型”，并把单需求循环放在第 11～19 步。新版流程已经整体重排：

- 第 3 步只负责基础工程选型，直接调用 AI-compatible Responses API，不调用 `foundation-selection` Skill；
- 第 4～6 步依次完成基础工程组装、项目准备核验和基础工程项目化；
- 第 7 步才调用 `solution-design` 形成总体技术方案；
- 第 8 步是根仓及适用仓的首次全仓提交检查与干净基线节点：仅根仓和成功 `steps/04.json.outputs` 是权威仓库；Python 只读核验，已全干净时不调用 Agent，存在未提交变更时由一个 `commit-changes` session 负责必要提交；Python 不初始化子仓、暂存或提交；
- 第 9 步是必要工程架构步骤，在单份根仓 `docs/design/工程架构设计.md` 中按每个包含业务代码且相关的适用交付单元分别闭合 Current/Target、职责/边界、依赖和代表性文件归属；第 10 步按当前 Demo v1 合同按需建立产品级 UI/UX 框架。第 9～11 步在固定文档产生唯一根仓未提交变化时才调用 `commit-changes`，已 tracked 且全仓 clean 时不制造无变化调用；
- 第 11 步拆分 Backlog；
- 第 12 步位于需求循环之前，使用 Responses API 和 Pydantic 初始化需求注册表；阶段一单需求循环为第 13～18 步；
- 所有当前正式需求完成后，不直接结束，而是进入新增的阶段二全项目级集成产品体验审计与修复闭环。

旧第 3 步的自然语言选型汇报、二次 Responses API 抽取、总体技术方案产物和相关实现均不沿用；新版第 3 步已经按 Pydantic `responses.parse` 重写。第 4～18 步已按各自确认合同实现；第 9 步当前新版 prompt 合同仍待安全 fresh 真实集成验证，不根据旧实现做兼容性补丁。

### 3. 开发协作边界

“PCM 运行时自动决策”和“Demo 新步骤开发前确认合同”是两个不同层次：

- PCM 运行时不增加逐步人工审批；所有可由当前输入、事实、工具和资源完成的决策由 AI-compatible 模型处理；
- Demo 开发时，以当前流程设计、当前活动 TRD、对应步骤实现和测试事实为准，与开发者确认该步的输入、输出、前置条件、操作、完成条件及失败、阻塞和恢复边界；
- 合同确认后先实现代码并通过测试和真实验证，再将实际实现同步到设计文档并提交；
- 当前已实现第 0～18 步；第 0～8、12～18 步已有适用真实验证。第 9 步新版 prompt 合同已经通过本轮自动化，但尚未安全 fresh 运行真实 Claude Agent、AI-compatible 负责人或 `/commit-changes` 集成；
- 第 18 步已按确认合同完成代码、自动化和真实 ff-only 合并验证；没有引入 Agent、Skill、负责人模型或公共 Git DSL。

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
- 第 1 步在最终目录同级使用 `<project_directory_name>.pcm-tmp-<run-id>` 临时 clone；拒绝模板已有 `.env` 并确认模板根 Git 忽略该路径后，才把 `PCM_AGENT_WORKSPACE_ENV_FILE` 原始字节写入临时根 `.env`、设置 `0600` 并随工作区原子发布；
- 全部发布核验通过后原子发布到最终路径，再在最终项目根执行 `git init -b main`；
- 第 4 步在 run-owned 临时 payload 中拒绝上游 `.git` 和符号链接，并只为适用端建立独立 `main` / unborn / 空 index Git 边界后原子发布；第 4 步不暂存、提交或 push；
- 第 8 步只读取已建立的根仓和适用子仓并形成干净基线，不初始化子仓；后续仓库遍历只使用其确认的 `applicable_repositories`，不固定假设 `frontend/`、`backend/` 一定都适用；
- Demo 不在当前能力仓库中执行产品项目的功能分支、代码合并或最终验收；
- 对产品工作区执行 clone、清理、删除、Git 或覆盖操作前，必须用当前 run 的状态和现场事实证明目标归属。

## 六、当前最小实现结构

截至第 18 步代码实现，已跟踪结构为：

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
│   ├── step_09_engineering_architecture/
│   ├── step_10_ui_ux_framework/
│   ├── step_11_requirement_breakdown/
│   ├── step_12_initialize_requirement_registry/
│   ├── step_13_select_requirement/
│   ├── step_14_trd_design/
│   ├── step_15_development/
│   ├── step_16_rule_retrospective/
│   ├── step_17_commit/
│   └── step_18_merge/
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

本次 project-readiness 修正验证包含第 5 步 15 项、第 6/7/9/10/11 步下游交接 68 项，合计 83 项；此前第 13 步 30 项和显式 SDK 通道重试 7 项保留其原验证语境。本轮当前工作树全量 351 项 `unittest` 通过（61.878 秒），`compileall common steps run_step.py run_all.py test_run_step_retry.py test_run_all.py` 与本次目标 `git diff --check` 通过；当前工作树还包含其它公共循环/CLI 的未提交修改，故全量结果不能全部归因于第 9 步。重试定向还由公共 Agent 循环测试覆盖任意 API 状态、连接/进程异常、取消、本地合同错误和瞬时标志不落盘；本次未调用真实外部服务制造故障。第 5 步新增准备清单与两份产品定义指纹、旧成功拒绝、清单漂移和产品范围漂移覆盖；第 6 步新增配置迁移与既有资源边界的 Prompt/决策覆盖。真实 BR-002 既有验证事实保持不变。Ruff 未安装，未执行 Ruff。

## 七、执行架构与职责

```text
命令行入口
  ├── 步骤或节点调度
  ├── 状态、结果和精确脱敏诊断
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
api_error_status
terminal_reason
errors
exception
```

不能把 SDK 结果压缩为一个 `success: bool`。`ResultMessage.subtype == "success"` 只说明 Agent loop 正常结束，步骤是否成功仍由文件、Git、命令、测试、服务、浏览器和未决事项共同判断。SDK `errors`、异常链和 traceback 位置在精确凭据遮盖后进入 Git 忽略的当前诊断快照；state、步骤结果和 stderr 只保存具体安全原因与 `diagnostic_path`。AI-compatible Responses 同样保留 provider code/type/message/request ID/HTTP status，但不保存完整 headers、请求/响应 body、prompt、环境字典或 `.env` 具体值。

正式步骤继续遵循：

- `cwd` 指向产品项目根；
- 使用 `claude_code` system prompt preset；
- 设置有限 `max_turns`，不配置 `max_budget_usd`；
- 需要继续时恢复原 session；
- 不在步骤代码中重复覆盖 `permission_mode`、`tools`、`allowed_tools` 或 `disallowed_tools`；
- 项目 `.claude/settings.json` 和 Claude Code 默认加载语义是权限与工具配置的权威来源；
- 从 init 消息核验实际 cwd、模型、Skills、slash commands、plugins、工具和权限模式；
- 工作区文件与 Git 事实在恢复时重新读取，不能由 session 文字替代。

Agent profile 固定为：第 2、5、7、9、10、11 步使用高模型和 `high` effort；第 6 步 bootstrap/theme、第 14、15 步使用中模型和 `high` effort；第 8、16、17 步使用中模型和 `medium` effort。第 15～17 步恢复同一 development session 时保持同一个中模型。每次首次调用和 resume 都重新显式传入 model 与 effort；当前 0～18 步不使用低模型 Agent，不配置 fallback model 或 `max_budget_usd`，也不改变既有最大 turn 和负责人决策轮数。

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

### 已实现流程：第 0～18 步

| 步骤 | 名称 | 核心职责 | 主要输出 |
| --- | --- | --- | --- |
| 0 | 形成产品初稿 | 简短选题时形成初稿；完整初稿无副作用跳过 | 产品初稿或跳过证据 |
| 1 | 建立项目工作区 | 固定模板浅克隆、拒绝模板 `.env` 并核验忽略规则、安装受保护根 `.env`、清理、原子发布、根仓库零提交初始化 | 独立产品工作区、Git 忽略且 `0600` 的工作区工具配置、`docs/产品初稿.md` |
| 2 | 项目需求与产品定义 | 显式调用 `project-intake` 收敛最终产品范围 | 产品定义文档、session 与决策历史 |
| 3 | 基础工程选型 | 使用 Pydantic 输入输出和 `responses.parse` 从本次 catalog 选择适用模板 | `steps/03.json.template_selection` |
| 4 | 组装基础工程 | 在 run-owned payload 中拒绝上游 `.git`/符号链接，建立适用子仓 `main` / unborn / 空 index 边界后原子发布 | 适用前后端独立基础工程仓 |
| 5 | 核验项目准备状态 | 调用 `project-readiness` 建立当前自动化开发周期唯一的开发资源准备基线，实际准备资源、运行配置并使用最终运行凭据核验 | 准备清单、受保护本地配置、公开示例与无秘密基线指纹 |
| 6 | 项目化基础工程与主题配色 | 先调用 `project-bootstrap` 收口项目身份和工程接线，允许在保持既有资源绑定的前提下迁移配置结构并完成真实工程验证；有 frontend 时再以独立 session/conversation 调用 `tailwind-theme`，落实并验证项目专属 light/dark 语义颜色 | 可安装、构建、测试、启动和基础联调的工程；`steps/06.json.tailwind_theme` 严格等于 outputs 是否含 frontend |
| 7 | 总体技术方案 | 调用 `solution-design`，基于已组装并项目化的工程事实设计 | 总体技术方案 |
| 8 | 首次提交适用仓库 | 以固定权威仓库清单执行首次全仓提交检查；全干净零调用直接成功，dirty 时一个 `commit-changes` session 处理必要提交，Python 只读复验 | `applicable_repositories` 与仓库干净事实 |
| 9 | 工程架构设计 | 必要步骤；单份根仓文档按每个包含业务代码且相关的适用交付单元闭合 Current/Target、职责/边界、依赖和代表性文件归属；repair 后仅在其为唯一根仓未提交变化时调用 `commit-changes` | `docs/design/工程架构设计.md` 非空、非符号链接、tracked，当前全仓 clean 并推进第 10 步 |
| 10 | 产品级 UI/UX 框架（按需） | Demo v1 仅以第 8 步严格交接的 `applicable_repositories` 是否含 `frontend` 判断；适用时调用 `ui-ux-framework` 形成跨需求框架和适用的 App Shell Contract | 适用时 `docs/ui-ux/framework.md` 闭合区域、导航、页面模式、滚动/sticky、响应式及 Current/已确认 Target/默认 Target/偏差，文件非空、非符号链接、tracked，当前全仓 clean并推进第 11 步；不适用时零副作用 |
| 11 | 拆分 Backlog | 严格消费第 2/5/7/8/9/10 步交接，以 Target 状态决定相关 BR 体验约束或条件性迁移 BR，不把框架资料或实现层当依赖 | `docs/backlog/backlog.md` 非空、非符号链接、tracked、当前全仓 clean；默认 Target 不制造迁移 BR/严格依赖，已确认迁移仅在独立用户结果和严格前置同时成立时单列；success 进入 step 12 |
| 12 | 解析 Backlog 并初始化需求注册表 | Responses/Pydantic 从自由格式 Backlog 唯一提取静态字段；Python 只校验可驱动生命周期的 ID、物理顺序和依赖图，并初始化 pending 注册表 | `steps/12.json` 保存 `{path, sha256}` 来源与静态 catalog，state 注册表已初始化并推进 `phase_1:select_requirement` / step 13；零 Claude Agent、零 Git 操作 |
| 13 | 选择需求并建立统一需求分支 | 确定性选择 ready pending 需求，fresh 全局预检后先写 active intent/cycle，再在全部适用仓建立 `req/<lowercase-id>` | scoped `steps/requirements/<ID>/13.json` success，state 推进 `requirement:14_trd_design` / step 14；零 AI/Agent/Skill、零产品文件改动、零提交/合并/push |
| 14 | 形成活动 TRD | requirement-scoped `/trd-design` 形成活动 TRD，按需引用本需求适用的已确认/默认 Target 并记录来源、范围、Current/Target、遵循或改变关系；保留待提交变更 | scoped `14.json` success，state 推进 step 15；不固定要求 UI 框架路径或资料来源 |
| 15 | 实现与验证 | requirement-scoped `/dev-workflow` 完成实现、真实验证和独立审查；适用体验决定映射到可观察结果、实现位置、浏览器/截图和动态证据，稳定偏差同步 TRD | scoped `15.json` success、`outputs: []`，cycle 保存 development session，state 推进 step 16；不提交/合并/push |
| 16 | 规则复盘 | 在原 development session 中以独立负责人 conversation 调用 `/session-rule-retrospective`，允许规则变化或 no-change，不读取 Git或限制规则文件结构 | scoped `steps/requirements/<ID>/16.json` success、`outputs: []`，session alias 已持久化，state 推进 `requirement:17_commit` / step 17；不提交/合并/push |
| 17 | 统一提交需求变更 | 在产品根 direct `run_claude()` session 中调用 `/commit-changes` 处理有序权威仓库白名单；Python 只核验分支、main/base、最终 clean 和 tips | scoped `steps/requirements/<ID>/17.json` success、`outputs: []`，cycle 保存各仓 `base_sha/tip_sha/merged:false`，state 推进 `requirement:18_merge` / step 18；不合并/push/标记完成 |
| 18 | 程序化合并并完成需求 | 纯 Python/Git 按非 root 在前、root 最后的顺序执行或恢复 `git merge --ff-only`，全部仓到 tip 后统一安全删除需求分支 | scoped `steps/requirements/<ID>/18.json` success，注册表项写为 `completed` / `completion:{"step":18}`，清空 active requirement/cycle 并返回记录节点；不调用 Agent、不 push |

本次第 1 步根 `.env` 工作区工具配置合同安全定向 24 项及当前工作树全量 359 项 `unittest`（53.340 秒），相关 IDE diagnostics 和 `compileall common steps run_step.py run_all.py test_run_step_retry.py test_run_all.py` 通过。自动化覆盖配置优先级/路径拒绝、`O_NOFOLLOW` 普通文件读取、模板已有 `.env` 或未忽略拒绝、用户级 global excludes 隔离、创建即 `0600` 的原始字节写入、内容/权限漂移，以及 PCM 源路径控制键不传入 Agent SDK；未重新调用外部模板仓库、AI-compatible 服务或 Claude Agent SDK，原有真实第 1 步运行不补造为新合同证据。当前工作树还包含未纳入本议题的其它步骤运行参数与测试改动，因此全量结果不能全部归因于本次修改。

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

第 5 步只确定性核验第 2、3、4 步交接、产品根 Git、适用子仓 `main` / unborn / 空 index、组装现场和 `PCM_DEV_RESOURCE_LIST` 路径，再在产品项目根显式调用 `/project-readiness`。初始提示以 slash command 开始，正文只描述开发资源准备领域：两份产品定义用于识别当前编码、开发环境联调和开发环境真实验收所需外部资源；实际工程和**最小选型投影**是技术事实（不传 `git_url`、`origin`）；可信资源资料是任意格式动态候选池且只由 Agent 原样读取。Agent 建立当前自动化开发周期唯一的资源准备基线，匹配候选前先验证受保护实际配置中的非空运行凭据与资源绑定，满足开发合同时原样保留，不用候选池中的维护、共享或更宽权限身份替换，也不把候选凭据探针结果误记为最终项目凭据结果；清单只描述最终选定绑定，不得提及、比较或说明未采用候选，否定表述也不例外；只有绑定缺失、失效或不合格时才使用动态候选池。在授权范围内优先准备项目专用开发/测试资源与最小权限运行凭据；服务不支持派生项目身份时，只有调用方明确授权的非管理、非生产共享开发身份，且实际作用范围满足开发合同，才可以兼容使用；共享管理或根凭据、生产身份和可访问合同外资源的身份不得写入应用配置，无法派生合格开发身份时属于第二类阻塞。权限与隔离按最终凭据的实际可见范围和范围外拒绝判断，列表接口只返回获授权项目资源时不因接口成功本身误判越权；每项判为 `ready` 的外部运行资源都必须把最终项目凭据绑定持久化到所属仓库被忽略的实际 `.env` 或等价配置，确保后续开发无需重新读取共享资源资料；同步无秘密公开示例及说明，含秘密文件在 POSIX 上通常使用 `0600`，并使用最终运行凭据完成最小行为和隔离验证。只允许两类阻塞：开发必需外部资源在候选池中缺失、当前环境无法安全生成且无兼容替代；已匹配资源真实不可用、凭据无效、权限不足、隔离不合格，或缺少开发所需接口能力、可用配额、回调/白名单及其它既定能力。依赖安装、migration、Seed、业务实现、项目内测试账号、完整联调和浏览器验收由后续开发完成；只服务生产部署或生产运行的正式域名、DNS/TLS、生产资源与凭据、生产回调与配额、监控、备份恢复、容量和发布安全属于开发及清单准入范围外。项目准备清单正文任何位置都不得列举、命名或汇总这些事项，也不得以“未纳入清单”、范围外、未来事项、非阻塞、无状态或 `not-applicable` 章节保留它们；开发 SMTP TLS、localhost 回调、开发白名单、沙箱范围和开发配额仍按当前开发用途纳入。产品规则和隐私事项同样不写入清单。Python 不解析资源资料或清单语义；成功 `steps/05.json` 以 `readiness_baseline.scope_contract` 固定“只允许开发必需外部资源进入清单”的准入合同版本，并绑定当前清单和两份产品定义 SHA-256。缺少或不匹配合同版本的旧 success 不可复用；`completed` 与 `blocked` 终止前均重新核验 Git 边界；只有结构完整、合同版本和指纹一致的 `status=success` 结果可幂等复用。

**当前清单准入合同的真实验证。** run `step05-readiness-v2-20260828-b` 复用独立产品工作区与既有开发资源完成 fresh 真实执行；此前凭据未持久化、生产范围误阻塞、内部配置形成第三类 blocked、必要能力遗漏、旧 baseline 无范围版本、非必需候选进入清单、范围外事项以“未纳入清单”章节残留、候选池维护身份被误当作最终项目凭据探针，以及未采用候选以否定比较残留在资源匹配字段的现场均已归档。最终 fresh Agent 原样保留受保护配置中已验证合格的项目绑定，只把 PostgreSQL、S3 兼容对象存储和 SMTP 三项当前开发必需外部资源写成 `ready` 章节；生产、后续内部工作、产品规则和其它非必需候选在清单正文任何位置均未出现，禁止词项检查命中数为 0。最终凭据保存在被忽略且 `0600` 的受保护配置，公开示例无秘密，秘密反查命中数为 0；真实探针确认 PostgreSQL 开发/测试库 DDL/DML 成功且额外可连接库为 0，S3 最终项目身份只看见两个授权桶并完成双桶对象读写删除，SMTP 使用明确授权的非管理、非生产共享开发身份完成 TLS、认证和唯一测试收件人单封投递。`steps/05.json` 为严格 success，`readiness_baseline.scope_contract` 为 `development-external-resources-v3`，清单 SHA-256 为 `29a288d45a7c060d51aafdf900d109629acfb40d5baf386e394b39c7c5a8420f`；state 推进 `project:06_bootstrap_foundation`，conversation 为 `system → assistant → user → assistant completed`。成功后幂等重跑 1 秒，`05.json`、state 和 conversation 字节均不变。

**重构前真实运行事实。** 修迹项目曾完成 PostgreSQL、MinIO 与本地配置准备，并在旧 session 语义下推进到第 6 步；该业务事实保留。旧历史中的固定完成声明和 `decision_turn` 属于旧协议，不是新循环会写入的状态。

第 6 步只从前序结果读取两份产品定义、第 4 步实际适用工程与白名单化组装来源，以及经过严格指纹核验的第 5 步准备基线；工程内部事实由 Agent 按现场读取。步骤在同一个数字节点内顺序运行两个独立公共循环实例：`project_bootstrap` session/conversation 的初始提示以 `/project-bootstrap` 开始，负责有限项目化、配置迁移、真实工程验证和可替换主题基础设施，但不选择项目专属配色；该领域 completed 并通过 README、`.coverage`、Git 等现有 verifier 后，有 `frontend` 时先由 Python 核验 `frontend/package.json` 中唯一且明确 major 4 的直接 `tailwindcss` 声明，并在 frontend 自身 Git 可见且未忽略的 CSS 中确认 `@import "tailwindcss"` CSS-first 证据，再新建或恢复独立的 `tailwind_theme` session/conversation，初始提示以 `/tailwind-theme` 开始，只引用产品定义和实际 frontend，完成项目专属 light/dark 语义颜色及前端构建、真实浏览器两种模式渲染验证。无 frontend 时只运行 bootstrap 并记录 `tailwind_theme:false`；存在 frontend 但版本或 CSS-first 合同不成立时为 `failed`，不创建主题 session。两个 prompt 都不包含步骤编号、PCM 节点、session 或其它编排背景，也不传 `git_url`、`origin`。两个领域完成后才写 success `steps/06.json` 并推进第 7 步；`outputs` 和顶层 `applicable` 保持原语义，新增真实布尔 `tailwind_theme == ("frontend" in outputs)`，旧 success 缺失或不一致 marker 不可复用。项目化与主题均不得执行 Git 写操作；主题网络来源不可用时生成 custom，不改变字体、圆角、阴影、间距、布局、组件或业务。Python 不解析实际 `.env`、资源身份、主题 token 或渲染语义，也不重复运行 Agent 已完成的工程命令。没有适用工程时的无副作用跳过保持不变，只有完整 `status=success` 可复用。

**重构前真实运行事实。** 修迹项目曾完成前后端项目化、安装、检查、测试、构建、真实启动、浏览器检查和基础联调，并推进到第 7 步；根 README 收口、根仓零提交和无 staged 是历史交付证据。当时适用工程尚未建立独立 Git 边界；第 4 步现行实现已替代该旧现场。旧专属裁决、格式重试和连接恢复的叙述不代表本次公共循环已被真实新 session 验证。

修迹真实项目化将产品根 README 收口为 MendMark 项目总说明，将前端收口为 `mendmark-web`、后端收口为 `mendmark-api`，同步公开配置、基础页面、健康检查与模板测试，保留有效基础设施并未实现业务功能。前端 `pnpm install --frozen-lockfile`、lint、type-check、10 项测试、build 和 1 项 Playwright E2E 通过；后端锁定、`uv sync --locked`、Ruff、15 项含 PostgreSQL `SELECT 1` 的测试和 `uv build` 通过；真实 Uvicorn/Vite、`/health`、`/ready`、OpenAPI、浏览器健康联调、375px 窄视口、控制台和网络检查通过。临时服务已停止，实际 `.env` 仍被忽略且权限为 `600`；根仓及适用子仓保持 `main`、unborn HEAD、空 index。源 PRD 与项目初稿的既有 SHA-256 事实均为 `d7d9b8054b226ef2abf730cfb29e59b30d5e39d68eb9121ded22a16750414fee`，状态推进到 `project:07_solution_design`，成功复用耗时约 1 秒且不再调用 Agent。

上述真实运行只证明旧版单 `project-bootstrap` 合同。当前第 6 步双 Skill 实现已由 14 项第 6 步、9 项第 7 步、58 项相邻步骤和 351 项全量自动化覆盖，确认两个独立 session/conversation、Tailwind v4 CSS-first gate、严格 marker 与恢复边界。隔离 run `step06-tailwind-theme-20260831` 确认 bootstrap Skill/slash command、产品 cwd 和原 session 加载；内置 Explore 未识别模型后，run-local 同 session 恢复实际执行 43 turns 并形成项目改动，但 SDK 最终 `terminal_reason=api_error` 且没有完整 Agent 回复，后续恢复因不合法 `pending_agent_text` 被严格拒绝，主题 session 从未创建。旧修迹运行和该失败现场都不能补造为新双 Skill 集成成功证据。

第 7 步只从前序结果读取两份产品定义、第 5 步项目准备清单、第 4 步实际适用工程和白名单组装来源，以及第 6 步严格成功结果；第 6 步 `outputs` 必须与第 4 步一致，且 `tailwind_theme` 必须是真实布尔并严格等于 outputs 是否含 frontend。工程内部事实由 Agent 按需读取，**不要求全仓扫描**。初始提示以 `/solution-design` 开始，只授权创建或更新 `docs/design/技术方案.md`，不包含步骤编号、PCM 节点或其它编排背景，不传递 `git_url` 或 `origin`。Agent 不重新选型、组装模板、实现业务、修改业务代码或执行 Git 写操作。`completed` 和 `blocked` 终止前都复核根仓及适用子仓的 `main` / unborn / 空 index；只有 `status=success` 的结果可幂等复用。新 run 的完整回复、pending 文本与决策输入保留原文于 Git 忽略目录；仍禁止 Agent 主动披露秘密。

公共循环使第 2/5/6/7/8/9/10/11 步共享 `AgentDecision(completed/continue/blocked)`、完整 conversation 的保存、读取、解释、恢复与 SDK 错误边界：`completed` 后才执行步骤核验，若固定产物可安全补完则追加普通修复提示并继续同一 session，`continue` 留在内部，`blocked` 或失败终止。第 6 步只是在同一数字步骤内顺序实例化 `project_bootstrap` 和 `tailwind_theme` 两个现有公共循环 spec，各自拥有独立 key、session、conversation、system snapshot 和私有状态；公共循环本身不增加多阶段抽象。第 9～11 步不解析 conversation 消息 schema、角色顺序、尾部 decision、session/reference 组合或完整 commit prompt，也不把 conversation 当长期成功证据；fresh 只按本步骤 session/reference/private state/conversation 路径等执行产物存在性拒绝，resume 交给公共循环。第 8 步的多仓只读 Git 核验和干净基线逻辑、第 9～11 步的固定文档工作树边界、tracked 核验和按需提交仍由步骤自身负责，公共循环不成为 Git DSL，也不抽取通用 commit 能力。第 10 步不适用路径在调用公共循环前以确定性规则结束，按执行产物存在性拒绝且零调用。`error_max_turns` / `error_max_budget_usd` 有 session 与非空回复时可裁决，但必须在正常 `success` 后才可最终完成；400/429/500、连接/CLI/进程、无 Result、`terminal_reason` 为 `aborted_streaming`/`aborted_tools`，以及 `success` 下未知终止原因均在裁决前失败。公共循环自身不做 HTTP 重试；只有其中属于 Claude Agent SDK 执行通道故障的失败才携带瞬时请求，由外层 `run_step.py` 有界重放，取消和本地合同错误不重放。run 目录是受控、Git 忽略的本地恢复状态，不建设防篡改日志。

### 4. 动态决策 XML system snapshot 与项目上下文

第 2、5、6、7、8、9 步各自只维护领域 `DECISION_RULES`。每次新 conversation 创建前，`common/decision.py` 将统一负责人角色、项目上下文、统一职责、步骤完成条件和输出合同分别渲染为 `<role>`、`<project_context>`、`<responsibility>`、`<completion>`、`<output>`。步骤规则只进入 completion；output 约束 `completed/continue/blocked` 的 `answer`、`required_inputs` 组合并要求 `reason` 非空。公共循环首次保存该 snapshot，恢复既有 conversation 时严格使用历史 `messages[0]`。

项目上下文范围固定为：第 2 步初稿原文和目标路径；第 5 步产品定义原文、适用工程、选型白名单投影和资源清单的绝对路径/可读性（不读或内联资源清单正文）；第 6 步 `project_bootstrap` 上下文包含产品定义原文、已完成准备清单原文、配置迁移与既有资源边界、适用工程和组装白名单投影，`tailwind_theme` 上下文只包含产品定义原文、实际 frontend 和主题颜色边界；两个 context 分别渲染和保存；第 7 步产品定义原文、准备清单原文、适用工程和组装白名单投影；第 8 步合法有序的 `applicable_repositories`；第 9 步两份产品定义、准备清单、总体技术方案、有序权威工程和固定输出路径；第 10 步适用时还包括第 9 步固定工程架构文档与实际 `frontend`；第 11 步则读取第 2/5/7 步文档、第 8 步权威工程、第 9 步工程架构及严格第 10 步交接，且仅在第 10 步 true 时包含 UI/UX 框架文档。第 6、7、9、10、11 步读取第 5 步结果前均核对当前准备清单和两份产品定义与 `readiness_baseline` 一致；第 8～11 步实际 top-level、`main` 和工作树的只读 Git 核验及 verifier 继续由步骤私有逻辑处理。

选型和组装投影不含 `git_url`、`origin`、`remote`，`.env` 与资源清单正文因输入来源边界不进入项目上下文。渲染器仅对项目上下文做标准 XML 转义。`request_decision` 要求显式传入该完整 XML prompt，将其原样传给一次 `responses.parse`，并以 Pydantic `AgentDecision` 取得结构化输出；没有公共默认或隐藏追加 prompt，也没有格式重试。Agent initial prompt、conversation schema、公共循环状态机、repair/session/错误分类和第 8 步 Git 逻辑均不变，未引入 `task_contract`。

**重构后第 7 步隔离真实验证。** 新 run `agent-loop-step7-20260822T190149Z` 在外部复制工作区运行，未修改既有 `step01-mendmark`；session `e8000375-2698-4ccf-9927-ccb9ca627ca2` 的 init 确认 cwd、`solution-design` Skill、slash command 和 Fable 模型。首次 Agent 尝试内置 Explore 子代理时发生环境内部未识别模型并超时，未返回 ResultMessage；循环保存 session 与初始 conversation、未推进成功。仅在隔离验证历史中追加普通 assistant 的“不使用子代理、直接工具完成”提示后，从同一 session 恢复。该测试提示不进入生产 prompt，环境内部子代理错误也不是公共循环缺陷。

恢复后 Agent 正常 `success`（44 turns，约 `$3.800742`），生成约 44 KB 技术方案。AI-compatible 服务对同一真实回复首返 YAML 风格结构；当时旧合同执行格式重试后返回 `completed`。测试包装器只在隔离副本首次 completed 后将技术方案置空，verifier 返回固定 `DESIGN_REPAIR_PROMPT`；公共循环保留真实 completed JSON、追加普通 assistant repair 提示、恢复同一已保存 session，Agent 补回非空文档，第二次真实裁决再次 `completed`。最终 `steps/07.json` 为 `success`，状态为 `project:08_initialize_repositories`，conversation 尾部为 `completed`，无旧 completion sentinel 或 `pending_agent_prompt`。该真实决定是旧 prompt 合同下的历史证据；本次自动化计数以本轮执行记录为准。

Probe C 的早期成功和格式重试结果均为旧合同历史。现行公共决策层使用五段 XML system prompt、一次 `responses.parse` 和 Pydantic `AgentDecision`，不追加公共默认或隐藏格式 prompt，也不做格式重试；旧第 9 步 fresh 运行只验证当时的五段 prompt 合同。当前第 9 步新增的工程架构语义 prompt 合同尚未执行安全 fresh 真实运行。

**第 8 步旧合同真实运行。** `step08-real-20260823-a` 必须保留为旧“唯一初始提交证明”合同下的失败事实：第 1 步真实服务依次返回代码围栏、Responses `incomplete` 和自创字段；收紧为严格 JSON、禁止代码围栏并列明五个唯一字段后同 run 成功。第 3 步首次 `ValidationError` 后同 run 重试成功。第 7 步 API 500 后，failed `07.json` 曾被误作成功锚点而阻断恢复；改为仅 `status=success` 可复用后，同一 session 成功。第 8 步因管理模板 Plugin 快照包含已跟踪 `.coverage`，它成为产品根未跟踪垃圾；Agent 按单仓合同未提交，但决策模型多轮追问“调用方授权”并耗尽 8 轮。该失败 run 未产生任何根、前端或后端提交。

`step08-real-20260823-b` 是旧合同下的历史成功：第 0～5 步一次通过，第 6 步真实清除 `.coverage`，第 7 步成功；session `64aa707c-268c-48c8-bb3f-f67f62abe75e` 的 conversation 为 `system → assistant → user → assistant`，一次 Agent 回复、一次 `completed` 裁决后产生 root `c1eb33dfa5bda91a0d7f9aeeb41d8fefe10a6fca`、frontend `5997213c34c09ea6ba4e740e35f9df77d2d45d82`、backend `5d8dd95d8c42370697d25e6ecaf400bab42785b3` 并推进到 `project:09_engineering_architecture`。这些提交 SHA、提交形态和当时重跑事实不再是当前合同的完成条件。

**第 8 步当前合同真实验证。** 真实 run 目录为 `pcm-demo/runs/step01-mendmark`，state 内历史 `run_id` 与目录名不一致是既有已知事实；产品工作区为 `/Users/zhou/resource/fireworks/ANDRSZAN/pcm-products/mendmark`。权威仓库为 `root/frontend/backend`，第 4 步 `outputs` 为 `frontend/backend`；首次执行前三仓均为自身 top-level、`main`、dirty 且 HEAD 不存在。

首次执行只创建 `initialize_repositories` session `f6d42df8-13e5-437b-ada3-eef1015ecc87`。Agent 尝试内置 Explore 时遇到环境未识别模型 `gpt-5.6-sol[1m]`，无 Result、无 Git 变化，进程挂起后停止；session、conversation 和 init 证据已保存。这是环境内部子代理问题，不是第 8 步业务或 Git 逻辑失败。仅在该 Git 忽略 run 历史中追加普通恢复指令“不要使用子代理/Explore，直接工具完成”，生产 prompt 和代码未改变；重跑恢复同一 session。

恢复后 Agent 先创建 frontend `dbab574dbe4d83a02323a750afd04de007565ac5` 与 backend `9682be837759c20f1a9ebbdf8fa2cfc09c2768d4` 两个本地提交，未 push；随后对根仓运行时产物和 `.agents/plugins/superpowers/.git` 请求决策。AI-compatible 负责人返回 `continue`，授权删除 61 个 `.in_use/*`、`.orphaned_at`、`.coverage` 运行时产物、补 `.gitignore`、移除嵌套 `.git`，并将 superpowers 作为普通受控插件快照而非 submodule 提交。同一 session 继续后，root 创建 `02ba4c1`（产品与技术基线）、`ae72c31`（Agent 规范与 Skills）、`5eeeacd217bbd27e03483b1b6d32915c721aadd9`（插件快照）三个本地提交，未 push。

最终 conversation 共 7 条，角色顺序为 `system → assistant 初始 → assistant 恢复 → user → assistant continue → user → assistant completed`；Agent 正常 `success`，26 turns，约 `$1.859406`，session 不变。Python 只读 verifier 写入 `steps/08.json` success：`applicable_repositories` 为 `root/frontend/backend`，result 保存相对路径，state 保存绝对路径，并推进到 `project:09_engineering_architecture`。独立 Git 核验确认 root HEAD `5eeeacd217bbd27e03483b1b6d32915c721aadd9`、3 commits，frontend HEAD `dbab574dbe4d83a02323a750afd04de007565ac5`、1 commit，backend HEAD `9682be837759c20f1a9ebbdf8fa2cfc09c2768d4`、1 commit；三仓均在 `main` 且 `status --porcelain` 为空。这证明当前合同允许每仓产生 0、1 或多个提交，不要求唯一无父提交。

同 run 重跑第 8 步直接以 clean 现场幂等成功，conversation 仍为 7 条，未再次调用 Agent 或决策模型，三仓 SHA 不变。backend 提交阶段的 Agent 摘要报告 Ruff、格式、build 通过，`pytest` 14 passed、1 skipped，跳过项为需要显式 `DB_*` 的数据库集成测试；这不是本次 Python verifier 条件，也不改变第 6 步既有项目化验证。当前合同因此已完成真实联调，但首次成功包含 run-local 恢复指令，不能宣称环境内部子代理问题已经解决或无需恢复。

### 第 9 步现行新合同与旧合同历史

第 9 步固定输入为第 2 步两份产品定义、第 5 步项目准备清单、第 7 步总体技术方案，以及第 8 步严格 success 的空 `outputs`、result/state 一致的合法有序 `applicable_repositories`。它始终 `applicable: true`，固定输出为 `docs/design/工程架构设计.md`，成功后推进到仍按需的 `project:10_ui_ux_framework`。第 8 步不逐项回放旧 `repositories` path、branch、clean 字段；每次实际 Git top-level、`main` 和工作树状态仍由当前步骤现场只读核验。

现行初始 prompt 要求 Agent 在单份根仓固定文档中为每个包含业务代码且相关的适用交付单元形成有限的 Current/Target 地图，以 `[当前]`、`[目标]`、`[按需]`、`[迁移]` 标注事实、目标、条件性内容与最小过渡：前端分别闭合装配/路由页面、功能、远程/局部/跨页状态、模型映射和共享 UI；后端分别闭合入口、编排规则、持久化适配、事务、授权、错误与副作用恢复；每单元至少一个代表性文件放置演练。以有证据的架构决策矩阵说明目录/模块职责、语义所有权、稳定公开能力、私有禁区、允许/禁止依赖和共享准入，并给出最小迁移、可观察演进以及当前下游实际需要的高影响决定。不固定框架目录，也不以行数阈值拆分；MVC、分层、六边形和 DDD 不属于互斥四选一；不得为了范式预建 `domain`、`application`、`infrastructure`、`shared`，或预建没有消费者的服务、队列、接口或其它结构。配置、运行、数据、测试和安全只按实际证据展开，不得虚构 Current。
步骤只使用一个 `engineering_architecture` conversation/session。领域步骤继续使用公共 `run_agent_decision_loop` 保存、读取并解释完整 conversation，但不解析消息 schema、角色顺序、尾部 decision、session/reference 组合或完整 commit prompt，也不把 conversation 当长期成功证据。fresh 入口要求全仓 clean，并仅因本步骤 session、conversation reference、私有状态或 conversation 路径等执行产物存在而拒绝；resume 交给公共循环恢复原 session。执行期间子仓必须保持 clean，根仓只允许固定文档 dirty；每次决定前复验。run 目录是受控、Git 忽略的本地恢复状态，不建设防篡改日志。

负责人 `completed` 后，completion verifier 先 repair 缺失或空文档。文档有效后，只有根仓存在未提交变化且边界确认只有固定文档时，才在同一 session 发送 `/commit-changes`；固定文档已 tracked 且全仓 clean 时直接满足提交交付条件，不制造无变化调用。最终以文档非空、非符号链接普通文件且 tracked、全体仓库在当前现场为自身 top-level / `main` / clean 判定 success，不要求 exact commit prompt、紧邻 Agent 回复或历史执行锚点。Python 只核验这些固定文件和 Git 事实，不解析 Markdown 的 Current/Target 地图、决策矩阵、模块语义或架构结论；语义完成由 Skill、Agent 和 AI-compatible 负责人负责。严格 result schema 已 success 而 state 推进中断，或完整 success 重跑时，仅据当前文档/Git事实补状态或确认成功。负责人 `blocked` 始终保存 blocked 并停在当前节点，不因本地文档 tracked+clean 改判 success。

**证据边界：** Python 只核验当前 Git-visible 工作树和 index；这不是不可绕过的安全隔离，不证明整个 Agent 执行历史未发生 Git 写入，也不覆盖 ignored 文件。本地 Demo 信任项目权限配置和 Agent 遵守领域约束；未来若要求不可绕过隔离，应在项目级权限或沙箱统一实现，而非由领域步骤解析 conversation 或扩展 Git DSL。第 10、11 步沿用该边界。

第 9 步更新后的 prompt 合同及第 9～11 步相关自动化已完成本轮验证：第 9 步定向 18 项通过（5.498 秒）；第 9～11 步本体合计 51 项（18+18+15）通过；公共循环加第 9～11 步本体及第 10/11 步 CLI 的相关回归 97 项通过（20.800 秒）；当前工作树全量 351 项 `unittest` 通过（61.878 秒）；`compileall common steps run_step.py run_all.py test_run_step_retry.py test_run_all.py` 与本次目标 `git diff --check` 通过。当前工作树还包含其它公共循环/CLI 的未提交修改，故全量结果是当前工作树验证，不能全部归因于第 9 步。第 9 步新版 prompt 合同尚未执行安全的 fresh 真实 Claude Agent、AI-compatible 负责人或 `/commit-changes` 集成；`step01-mendmark` 已推进到第 13 步并保留旧第 9 步 success/session/conversation，旧真实 run 仅为旧合同历史。

旧失败依次暴露 HTTP 403、非 JSON 普通文本和 `completed` 非空 `answer`。根因是旧 prompt 把步骤规则混入 responsibility、硬编码并重复 completion 语义且缺少 output。用户将其重构为 `role/project_context/responsibility/completion/output` 五段，补齐 f-string JSON 花括号转义和字段组合约束，并同步 common 与第 2/5/6/7/9 步测试。

以下第 9 步 session、11 条 conversation、exact commit prompt、commit-changes 发现文档事实矛盾和提交事实，均为旧合同下的历史运行路径，不构成当前成功条件。按用户要求两次清理第 9 步局部执行数据和失败生成的未跟踪文档后，保留第 0～8 步历史与三仓提交执行 fresh 运行。最终唯一 session `f41fc439-4c46-434f-b3e9-d15c18c89601`，conversation 11 条：`system → assistant 初始 → user → assistant continue → user → assistant completed → assistant commit prompt → user → assistant continue → user → assistant completed`。

首轮 Agent 请求确认，负责人合法 `continue` 后创建约 32 KB 固定文档；负责人 `completed` 后 verifier 同 session 调用 `/commit-changes`。该 Skill 发现 frontend Git 事实矛盾，严格未修改、未暂存、未提交并报告；外层负责人普通 `continue` 授权通用 Agent 仅修正文档并精确提交。

产品根提交 `ead14dffe19bc6417634c24c7bb1103602c3b772`，message `docs: 新增工程架构设计`，仅新增固定文档，376 行、32928 字节；未 push，frontend/backend 无变化。最终 decision 为合法严格 JSON `completed`，`steps/09.json` 和 state 均为 success，状态推进到 `project:10_ui_ux_framework`。

独立核验 root/frontend/backend 均为自身 top-level、`main`、clean，固定文档 tracked。同 run 幂等重跑后 conversation 仍 11 条，session 和 root HEAD 不变，没有 Agent、decision 或新提交调用。

### 第 10 步现行新合同与旧合同历史

第 10 步是按需的项目级能力。当前 Demo v1 不把通用 Skill 的适用性判断交给 Agent：唯一规则是第 8 步严格 success 的空 `outputs`、result/state 一致的合法有序 `applicable_repositories` 是否包含 `frontend`，不扫描目录。该规则仅适配当前前后端交付单元模型；已有项目接入与显式既有框架路径是未来扩展，通用 Skill 不因此被永久限制为固定路径。

无 `frontend` 时，严格核验第 5 步 `readiness_baseline` 与当前准备清单和两份产品定义一致，再读取第 8 步严格交接和严格第 9 步 success（唯一 `docs/design/工程架构设计.md`）。所有入口均按本步骤 session、conversation reference、私有状态或 conversation 路径等执行产物存在性拒绝；否则保持零 Git、Agent、负责人决策、LLM 配置和 `docs/ui-ux/` 副作用，成功写入 `applicable: false`、`outputs: []`，推进 `project:11_requirement_breakdown`。此路径只经自动化覆盖，黄金项目不走该分支。

有 `frontend` 时，严格输入为第 2 步两份 outputs、第 5 步清单、第 7 步技术方案、第 9 步唯一工程架构文档、第 8 步权威仓库及实际 `frontend`。单一 key/session 为 `ui_ux_framework`，初始提示首行 `/ui-ux-framework` 并明确 `bootstrap`，只允许创建或更新 `docs/ui-ux/framework.md`。文档须区分工程事实、已确认决定、目标状态、假设和待确认事项；禁止单需求设计、代码、配置、项目规则和 Git 写操作。

`completed` verifier 先 repair 缺失或空文档；只有根仓存在且仅存在固定文档未提交变化时，才在原 session 发送 `/commit-changes`。已 tracked 且全仓 clean 的文档直接满足交付条件，不制造无变化调用。最终 success 只要求文档非空、非符号链接普通文件、已 tracked，全部权威仓库当前均为自身 top-level、`main`、clean；不要求 exact prompt、紧邻 Agent 回复或历史执行锚点。适用路径的 fresh/resume/blocked、result/state 中断和幂等与第 9 步同构：领域步骤不解析 conversation，完整 success 只据严格 result schema、当前文档/Git事实恢复；blocked 始终保存并停在当前节点。合同保持局部实现，不改 `common`，不抽取 Git DSL、commit 事件、持久布尔标记或旧 prompt 兼容列表。

第 9 步更新后的 prompt 合同及第 9～11 步相关自动化已完成本轮验证：第 9 步定向 18 项通过（5.498 秒）；第 9～11 步本体合计 51 项（18+18+15）通过；公共循环加第 9～11 步本体及第 10/11 步 CLI 的相关回归 97 项通过（20.800 秒）；当前工作树全量 351 项 `unittest` 通过（61.878 秒）；`compileall common steps run_step.py run_all.py test_run_step_retry.py test_run_all.py` 与本次目标 `git diff --check` 通过。当前工作树还包含其它公共循环/CLI 的未提交修改，故全量结果是当前工作树验证，不能全部归因于第 9 步。第 9 步新版 prompt 合同尚未执行安全的 fresh 真实 Claude Agent、AI-compatible 负责人或 `/commit-changes` 集成；`step01-mendmark` 已推进到第 13 步并保留旧第 9 步 success/session/conversation，旧真实 run 仅为旧合同历史。 以下真实 run 为旧合同下的历史执行路径。

真实 run `pcm-demo/runs/step01-mendmark` 的权威仓库为 `root/frontend/backend`，因此适用。session `2d052d9a-b9fd-4fcd-b5f9-ff724f25dbc1` 的 init 确认 skill/slash command 已加载、cwd 为产品根、模型 `claude-fable-5[1M]`、Claude Code 2.1.233、permissionMode `bypassPermissions`；最终 Agent success，5 turns，cost `$3.207112`，`terminal_reason=completed`，无错误。fresh 调用的内置 Explore 子代理曾输出未识别模型 `gpt-5.6-terra[1m]` 警告，但主 Agent 同次调用继续并 success，未追加人工或 run-history 恢复提示。

conversation 共 7 条：`system → assistant 初始 → user → assistant completed → assistant commit prompt → user → assistant completed`；framework repair 为 0，固定 commit prompt 恰好一次且锚点有效。已实际读取 206 行、25580 字节的固定文档，内容不含实现代码。产品根本地提交 `0ceee1bb8b5836f64112ded0c8fd3cf7fbd1f29c`（父 `ead14dffe19bc6417634c24c7bb1103602c3b772`，`docs: 建立产品级 UI/UX 框架`）仅新增该文档，未 push；frontend/backend SHA 不变，三仓均为自身 top-level、`main`、clean。`steps/10.json` success 且唯一固定输出，state 位于 `project:11_requirement_breakdown`。幂等重跑后 session、7 条 conversation、root HEAD、总提交数与前后端 SHA 均不变，无新提交。第 11 步已严格消费该交接并完成真实验证。

### 第 11 步现行新合同与旧合同历史

第 11 步固定输入为第 2 步两份 outputs、第 5 步清单、第 7 步技术方案、第 8 步严格 success 的空 `outputs`、result/state 一致的合法有序 `applicable_repositories`、第 9 步唯一工程架构，以及严格第 10 步 success。第 8 步不逐项回放旧 `repositories` path、branch、clean 字段，实际 Git 状态由本步骤当前现场只读核验。第 10 步 true 时读取唯一 `docs/ui-ux/framework.md`；false 时只能是空 outputs，既不读取也不扫描该文档。单一 key/session 是 `requirement_breakdown`，首行 `/requirement-breakdown`，Agent turn 与负责人决策轮数沿用步骤代码的有限配置且不设置 `max_budget_usd`；固定唯一输出是 `docs/backlog/backlog.md`。

Agent 只可生成或更新该 Backlog，不能实施需求或修改代码、测试、配置、项目规则和其它文档，初始工作不执行 Git 写操作。Backlog 说明正式需求的范围、目标、验收要点、依赖和风险，但不包含待开发、开发中、已完成、阻塞等需求开发状态；这些状态由调用方外部结构化运行状态管理，业务对象或业务流程状态仍可作为需求内容。`completed` 后先 repair 空文档，只有根仓存在且仅存在固定 Backlog 未提交变化时，才在同一 session 调用 `/commit-changes`；已 tracked 且全仓 clean 时直接满足交付条件。运行期间 root 只允许固定 Backlog dirty、子仓持续 clean；完成时固定文件非空、非符号链接、tracked 且全仓当前 `main`/clean，Python 只读 Git。不要求 exact prompt、紧邻 Agent 回复或其它历史执行锚点。

领域步骤使用公共循环保存、读取、解释完整 conversation，但不解析其 schema、角色顺序、尾部 decision、session/reference 组合或完整 commit prompt。fresh 仅因既有执行产物存在性拒绝，resume 由公共循环恢复；blocked 始终保存并停在当前节点，failed 保留现场。完整 success 的 result/state 中断恢复与幂等复验仅按当前步骤必要事实恢复。当前 `run_step.py` 已支持第 0～18 步：完整第 8～12 步 fixed success 与当前 active requirement 的第 13～18 步 scoped success 分别受保护。

第 9 步更新后的 prompt 合同及第 9～11 步相关自动化已完成本轮验证：第 9 步定向 18 项通过（5.498 秒）；第 9～11 步本体合计 51 项（18+18+15）通过；公共循环加第 9～11 步本体及第 10/11 步 CLI 的相关回归 97 项通过（20.800 秒）；当前工作树全量 351 项 `unittest` 通过（61.878 秒）；`compileall common steps run_step.py run_all.py test_run_step_retry.py test_run_all.py` 与本次目标 `git diff --check` 通过。当前工作树还包含其它公共循环/CLI 的未提交修改，故全量结果是当前工作树验证，不能全部归因于第 9 步。第 9 步新版 prompt 合同尚未执行安全的 fresh 真实 Claude Agent、AI-compatible 负责人或 `/commit-changes` 集成；`step01-mendmark` 已推进到第 13 步并保留旧第 9 步 success/session/conversation，旧真实 run 仅为旧合同历史。 以下 `step01-mendmark` 事实为旧合同下的历史运行路径。真实 `step01-mendmark` run 前，旧 Skill 已单独由真实 `/commit-changes` 提交 `9263d28`（只改 Skill、未 push、三仓 clean），这是新合同测试前置而非步骤输出。session `af7d198c-b090-44d8-9d92-ae0738150854` 生成约 59,140 字节、约 1,110 行 Backlog：14 项 BR 完整覆盖 E.1，未自动纳入 E.2/E.3，首条验证切片为完整 BR-001～BR-006。负责人瞬时 failed 依靠正常原节点重跑恢复，未注入 conversation 的只读诊断不作为正式决定；未增加 HTTP 重试或修改生产 prompt。最终 exact commit 一次，根仓本地提交 `2aaa743a97d96fe93deaaaaa13a94e4c414369a2`（`docs: 建立 MendMark 首版正式 Backlog`）仅新增 Backlog，三仓 `main`/clean；历史第 11 步 success 当时进入旧 `phase_1:select_requirement` / step 12 占位入口。


### 第 12 步已实现合同与真实验证

第 12 步只接受第 11 步完整 success 与 `phase_1:initialize_requirement_registry` / step 12 状态；旧 `phase_1:select_requirement` / step 12 入口不兼容。它不调用 Claude Agent、`AgentDecision` 或 Skill，只用 Responses/Pydantic 从自由格式 Backlog 提取每项 `id`、`title`、`order`、`depends_on`。system prompt 要求覆盖全部且仅有的正式需求，忠实保留 canonical ID、标题、明确顺序和显式依赖，排除说明、示例、候选、非目标、历史与未来设想，不得根据正文关联或业务常识猜测依赖。

Python 不解析 Markdown 标题、表格、详情卡或依赖章节，也不与第二套语义结果比对。它只校验 catalog 非空、ID 与依赖 ID 符合 `[A-Za-z0-9][A-Za-z0-9_-]*`、ID 忽略大小写唯一、数组物理顺序严格对应 `order=1..N`、依赖存在且不重复、不自依赖、无环。Backlog 必须是工作区内非空 UTF-8 非符号链接普通文件；本步骤不读取 Git。程序从同一字节快照生成模型输入和 SHA-256，模型返回后重新读取并拒绝调用期间漂移。

成功 result 只保存 Backlog `{path, sha256}` 来源与静态 catalog，`outputs` 为空；随后 state 写入 `schema_version: 1` 注册表，所有项为 `pending`、`completion: null`，并推进 `phase_1:select_requirement` / step 13。result 已写而 state 未推进时可从 result 恢复；完整 success 重跑严格核对当前来源、catalog 与注册表，完全一致才零模型调用，任一漂移失败且不覆盖。旧 `{path, sha256, root_main_sha}` source 不兼容或迁移，只保留为旧合同历史。

新合同真实隔离 run `step12-ai-only-20260826` 使用无 Git 工作区和没有总览表、详情卡或固定标题层级的自然语言 Backlog。实际 Responses 准确注册 `BR-AI-001`～`BR-AI-003`，标题、order 1～3 和显式依赖均正确，并排除 `NOTE-001` 示例和在线支付未来设想；全部为 `pending`、`completion: null`。来源 SHA-256 为 `c8fb63f1e403fcf36c302f77511dfb7ea29a305a345f6bf125c9c101801f8f76`。以不可连接的 LLM 配置幂等重跑仍 success，result/state 字节不变；第 12 步 16 项、第 12～14 步定向 61 项、全量 282 项 `unittest`、`compileall` 与目标 IDE diagnostics 均通过。历史 `step01-mendmark` 的 14 项提取、root SHA 与旧三字段 source 继续仅为旧合同证据。

第 13 步初次真实运行选择 `BR-001` 并建立三仓 `req/br-001`。第 14 步前的授权 Skill 提交使 root 基线前进；归档旧 run、确认旧分支无独有提交并安全重跑第 13 步后，当前 cycle bases 为 root `a7d5509df6843a06315aa803d87285569b86e355`、frontend `dbab574dbe4d83a02323a750afd04de007565ac5`、backend `9682be837759c20f1a9ebbdf8fa2cfc09c2768d4`。第 14 步随后形成唯一未提交活动 TRD并推进 `requirement:15_development` / step 15；BR-001 仍为 active，三仓没有需求实现提交、merge 或 push。

### 动态 prompt 交接事实回放

Git 忽略 run `prompt-role-replay-20260823` 保留旧四段 XML prompt 的历史交接回放；它不是新五段 prompt 的证据。旧第 9 步 final fresh 运行及其 Pydantic `AgentDecision` 同样只属于当时合同历史；当前第 9 步工程架构语义 prompt 合同尚未安全 fresh 验证。

### 阶段一：需求注册与第 13～18 步逐需求开发

第 12 步只在初始 Backlog 完成后执行一次，位于需求循环之外；第 13～18 步处理当前已知正式 Backlog 中的每个需求。

| 步骤 | 名称 | 核心职责 |
| --- | --- | --- |
| 12 | 解析 Backlog 并初始化需求注册表 | 使用 OpenAI Responses API 和 Pydantic 从自由格式 Backlog 唯一提取 `id`、`title`、`order`、`depends_on`；Python 只校验生命周期所需的 ID、数组顺序和依赖图，记录 Backlog 指纹并初始化动态状态。不调用 Claude Agent，不选择需求、不建分支、不修改产品项目、不执行 Git |
| 13 | 选择需求并建立统一需求分支 | Python 确定性选择依赖均完成且 `order` 最靠前的 pending 需求；为全部 `applicable_repositories`（包含 root）从各自 clean local `main` 建立同名分支并记录基线 |
| 14 | 形成活动 TRD（已实现） | 只消费当前活动需求、cycle、workspace 和注册表已记录的 canonical Backlog 来源，首次持久化 `docs/trd/<YYYY-MM-DD>-<ID>-<标题>.md`；完整 Backlog 正文进入负责人 `<project_context>`，Agent 再通过 requirement-scoped 公共循环显式调用或恢复 `/trd-design`，按需记录本需求适用体验决定的来源、范围、Current/Target、遵循/改变关系及默认 Target 的依据/重议条件；Python只核验指定 TRD 非空，不读取 Git或重复复验前序步骤 |
| 15 | 实现与验证（已实现） | 调用 `dev-workflow` 完成实现、测试、构建、运行、联调、浏览器验收和独立审查；活动 TRD 完整正文进入负责人 `<project_context>`，不重复加入 Backlog 或其它上游文档；适用体验决定映射到可观察结果、实现位置、浏览器/截图和动态证据，稳定偏差同步活动 TRD并保存 `development_session_id`；不提交 |
| 16 | 在原开发 session 复盘规则（已实现） | 建立独立 `rule_retrospective_<ID>` 负责人 conversation，首次调用前预注册同一 `development_session_id` alias并恢复原 session；允许规则变化或 no-change，不读取 Git或限制规则文件结构，`outputs: []`，success 推进第 17 步，不提交 |
| 17 | 统一提交需求变更（已实现） | 在产品根一个 requirement-scoped session 中调用一次 `commit-changes`，只处理 `applicable_repositories` 白名单；dirty 仓分别提交、clean 仓不造空提交，记录每仓需求分支 `tip_sha`，不合并、不标记完成 |
| 18 | 程序化合并并完成需求 | Python 先合并非 root 代码仓、最后合并 root；只使用 `git merge --ff-only`，核验 `main`、SHA、clean 并清理分支，全部成功后才将需求标记 `completed` |

阶段一约束：

- `trd-design` 与 `dev-workflow` 共同完成需求级体验设计、真实运行和验收；
- 需求注册表是开发生命周期唯一真源，Backlog 不记录 pending、active、completed 或 blocked；
- 第 14～16 步均不提交，第 17 步是唯一提交阶段，第 18 步是唯一合并阶段；
- 所有仓库遍历只使用第 8 步确认的 `applicable_repositories`，不硬编码三个仓库，也不按 TRD 推断是否建立分支；
- 当前步骤发现可修正问题时在本步骤内部修正并重新核验，外层编号不回退；
- 第 18 步合并后的文件树与第 15 步已验证、第 17 步已提交的需求分支一致时，不机械重跑全部业务测试，但 Git 事实核验不可省略；
- 当前正式范围内全部需求完成第 13～18 步后，才进入阶段二。

### 第 14 步已实现合同与真实验证

第 14 步采用与第 15 步一致的薄编排，只消费当前 state 的 active requirement、注册表唯一 active 项、cycle、workspace 和注册表已记录的 canonical Backlog 来源。它信任严格串行流程的前序 success，不重新读取或精确复验第 2/5/7/8/9/10/11/12/13 步结果、其它固定文档、仓库 descriptor 或 Git 基线；这些事实由前序步骤负责。Python 从 `requirement_registry.source.path` 读取完整 Backlog 正文并放入负责人的 `<project_context>`，使负责人理解当前需求在全部需求中的位置、依赖和关系；Agent 在 `/trd-design` 中按需读取其它当前项目资料和代码。

Python 使用首次本地日期、requirement ID 和注册表标题形成 `docs/trd/<YYYY-MM-DD>-<ID>-<标题>.md`，对直接用于文件名的标题做最小合法性检查，并在首次 Agent 调用前把 exact `trd_path` 写入 cycle。恢复只沿用该值。Agent/session/conversation key 为 `trd_design_<ID>`，步骤直接复用公共 `run_agent_decision_loop` 保存和恢复 session、conversation 与待裁决回复，不解析公共对话内部结构，也不覆盖 `permission_mode`、`tools`、`allowed_tools`、`disallowed_tools` 或增加私有 tool hook。

负责人只有在范围、关键行为、技术方案、验证、需求级体验和阻碍实现的决定均已收敛时才可返回 `completed`；不能把“已列出实现门槛”误作完成。存在本需求真正适用的已确认 Target 或有依据的默认 Target 时，TRD 须记录其来源、适用范围、经核验 Current、Target 和本需求遵循或改变的关系；默认 Target 还记录依据与重议条件，偏离不得静默发生。没有适用决定时不虚构、不阻塞，也不固定要求 `docs/ui-ux/framework.md`、`ui-ux-framework` 或某种 UI 技术栈。Python completion verifier 只核验指定活动 TRD 是产品工作区内的非空文件；缺失或为空时同 session repair，不调用 `/commit-changes`。success 先写 `steps/requirements/<ID>/14.json`，再进入 `requirement:15_development`；blocked 保留路径和同一 session，result→state 中断只补状态，推进后不再读取文件或调用 Agent。第 14 步不读取 Git，不重复检查第 13 步建立的分支/base，也不监管第 17、18 步负责的提交和合并。

真实 `step01-mendmark` 使用 session `b9ed4756-0acf-4666-b3f9-c8f3628c03f1` 生成 `docs/trd/2026-08-25-BR-001-身份、角色访问与站内消息入口.md`。首次负责人错误接受 8 项实现门槛后，同一 session 收敛决定；负责人服务 free quota HTTP 403 后也从原 conversation 尾部恢复完成。最终 conversation 7 条且无 `/commit-changes`。当时 root 只有唯一未跟踪 TRD、frontend/backend clean、三仓无 staged、提交、merge 或 push，是旧实现结束时的历史现场，不再是现行 success 条件，也不会由现行代码重复核验；既有 TRD/result/state/conversation/Git 现场不因本次精简而改写。

### 第 15 步已实现合同与真实验证

第 15 步只消费当前 state 的 active requirement/cycle/workspace、当前需求 scoped 第 14 步 `success` 和非空活动 TRD；不读取第 2/5/7/8/9/10/11/13 步文档，不执行 Git 命令或 Git verifier。它以 `development_<ID>` 复用公共 `run_agent_decision_loop`，初始 Agent prompt 只有 `/dev-workflow`、需求 ID/标题和活动 TRD 路径，负责人的 `<project_context>` 则包含该路径和完整活动 TRD 正文，不重复加入 Backlog 或其它上游文档。Agent 按需自行读取项目资料、代码、配置、测试和环境；稳定设计偏差可同步活动 TRD，但不得修改 `.claude/rules/`，也不得 stage、commit、创建或切换分支、merge 或 push。活动 TRD 存在适用的已确认 Target 或默认 Target 时，负责人只在 Agent 已建立“体验决定（默认 Target 含依据与重议条件）→可观察结果→实现位置→真实浏览器和实际读取截图证据→实际结果”映射、没有静默偏离且截图未替代动态交互、权限、失败恢复和持久化验证后返回 `completed`。

completion verifier 保持为空，体验决定与其它实现语义由 Skill、Agent 和负责人裁决；`continue` 和 `blocked` 沿用公共语义。首次取得 session 即同步到 `requirement_cycle.development_session_id`。success scoped result 是 `steps/requirements/<ID>/15.json`，`outputs: []`，保存 requirement ID、TRD 路径和 development session；success 推进 `requirement:16_rule_retrospective` / step 16。blocked 保留同一 session 和 step 15；success result 已写但 state 未推进时可恢复，推进后和 CLI 幂等只保护当前活动需求完整 scoped success。

真实 run 为 `pcm-demo/runs/step01-mendmark`，产品工作区为 `/Users/zhou/resource/fireworks/ANDRSZAN/pcm-products/mendmark`。development session `e6bd1b82-39f9-41b2-9cc9-a69b281015dc` 的 init 确认 Fable 5、Claude Code 2.1.233、`bypassPermissions`，最终 normal success 为 23 turns、约 `$9.784016`。首次调用在 init/session 已保存后，`claude-agent-sdk` 0.2.139 默认单条 CLI stdout JSON 1 MiB 缓冲触发 `JSON message exceeded maximum buffer size`；仅在公共 `ClaudeAgentOptions` 增加 `max_buffer_size=10 * 1024 * 1024`，无新配置且不影响 resume，随后从同一 session 恢复并保留既有产品改动。自定义 dev/reviewer 子代理曾出现未识别 model 警告和一个子进程退出，但主 Agent 继续完成，生产 prompt 未改。

最终 conversation 共 9 条：`system → assistant 初始 → user 首轮回复 → assistant completed → assistant 正常结束要求 → user 已实现但未完全验证 → assistant continue 补 Firefox/WebKit → user 三浏览器结果 → assistant 最终 completed`。Agent 报告后端 Ruff/format/build、pytest 16 passed 1 skipped、真实 PostgreSQL、Alembic upgrade-downgrade-upgrade；前端 lint/type-check/build、Vitest 15 passed；Chromium/Firefox/WebKit Playwright 矩阵 3 passed；并完成真实 FastAPI/PostgreSQL/Vite 浏览器联调、代表性截图读取和独立审查。BR-001 仍 active/completion null；root 保留活动 TRD和代表性截图未跟踪，frontend/backend 保留实现、测试、迁移与配置未提交变更；三仓均为 `req/br-001`、index clean、无 commit/merge/push。不可用 LLM 配置幂等重跑仍 success，state/result/conversation 字节不变，SHA-256 分别为 `069b50dc583d8472683eded457bdb954265e37000b78c59860986bc8ea15bf72`、`033585fb8c7b2a43937dd67082aec8a179cc368ede869c460df4300a438487a2`、`432072a5bb43f90af90adf557bc1b92adab3599a5adb11a5696f57167a100e19`。第 15 步本体 6 项与 CLI 4 项的历史验证保持不变；第 16 步旧实现本体 19 项与 CLI 4 项、全量 273 项 `unittest`、`compileall`、`git diff --check` 均通过。Pyright langserver 未安装，未执行 IDE/LSP diagnostics；独立只读审查修复后最终无高、中置信缺陷；Ruff 未安装，未执行。第 16～18 步随后均已完成实现与适用真实验证。

### 第 16 步已实现合同与真实验证

第 16 步采用与第 15 步一致的薄编排，只消费当前 active requirement、cycle、workspace 和一致的 `development_session_id`；不重新读取或精确复验第 15 步 result、TRD、仓库、分支或工作树。

步骤以 `rule_retrospective_<ID>` 建立独立负责人 conversation，首次 Agent 调用前将该 key 的 Claude session alias 绑定为同一 `development_session_id`，公共 `run_agent_decision_loop` 因而恢复原开发 session。初始 prompt 首行固定 `/session-rule-retrospective 本次开发会话`；`completed` 允许规则变化或 no-change，`continue`、`blocked` 沿用公共语义。

success 先写 `steps/requirements/<ID>/16.json`，`outputs: []`，再推进 `requirement:17_commit` / step 17；blocked 保留当前节点、原 session alias 和独立 conversation。result→state 中断只补状态，推进后不需要工作区、Git、Agent 或模型。第 16 步不建立 Git baseline、不检查规则目录结构，也不限制 Skill 的输出文件；第 17 步负责读取实际未提交变更并提交。

现行本体 7 项、CLI 4 项，共 11 项；相关定向 51 项和全量 282 项 `unittest`、`compileall`、`git diff --check` 通过。真实 `step01-mendmark` 曾复用 development session `e6bd1b82-39f9-41b2-9cc9-a69b281015dc` 完成规则复盘并新增 `.claude/rules/frontend-playwright-container.md`。旧实现的三仓提前提交失败、`git reset --mixed` 现场恢复和 Git-visible baseline 是历史事实，不再是现行 success 条件，也不会由现行代码重复核验；既有规则、result、state 和 conversation 不因本次精简而改写。

### 第 17 步已实现合同与真实验证

第 17 步只消费当前 active requirement/cycle/workspace、完整 scoped 第 16 步 success、统一需求分支、`applicable_repositories` 有序白名单和各仓 `base_sha`。Python 只核验仓库路径不越界且是自身 Git top-level、当前分支正确、`main==base`、`HEAD==target`，以及包含未跟踪文件的最终 `status --porcelain` 为空。

fresh 全仓 clean 时零 Agent，直接记录 `tip=base`。存在 dirty 仓时，步骤在产品根直接调用一次 `run_claude()`；初始 prompt 只调用一次 `/commit-changes`。init 后立即持久化 `requirement_commit_<ID>` session；异常或最终仍 dirty 时 failed，下次运行只恢复同一 session 一次，不使用负责人模型、decision conversation或同次多轮 repair。

完整 diff、提交分组、精确暂存、空提交和提交历史由 `commit-changes` 自己负责。Python 不再制作工作树 fingerprint，不读取 blob/tree，不校验 merge commit、净零提交或首次内容等价。success 只保存各仓 `name/path/base_sha/tip_sha`，再将 cycle 写为 `{base_sha,tip_sha,merged:false}` 并推进 step 18；result→state 和 advanced 幂等保持不变，旧真实 run 的 fingerprint/conversation 遗留字段不迁移、不清理。

现行实现第 17 步本体 9 项、CLI 4 项，共 13 项；公共循环与第 17 步定向 43 项通过。当前工作树全量 351 项 `unittest` 通过（61.878 秒），`compileall common steps run_step.py run_all.py test_run_step_retry.py test_run_all.py` 与本次目标 `git diff --check` 通过；当前工作树还包含其它公共循环/CLI 的未提交修改，故全量结果不能全部归因于第 9 步。独立只读审查无高、中置信发现。现行第 17 步恢复完整 conversation、负责人决策、同 session continue/blocked resume/completed repair，同时继续不做 fingerprint、blob/tree、merge或空提交取证。BR-002 在旧 direct-run 版本期间只有 Claude session、没有 conversation；该历史缺口不补造，后续需求按现行合同保存完整历史。

### 第 18 步已实现合同与真实验证

第 18 步只读取当前 active requirement/cycle、`applicable_repositories`、工作区仓库路径和 scoped 第 17 步 success 的必要字段；前序交接可以增加与本步骤无关的字段。步骤不调用 Claude Agent、Skill、LLM、session 或 conversation，也不重新读取业务文档、diff、commit message、提交历史或第 15 步验证内容。

Python 过滤 Git 子进程的 `GIT_*` 环境变量，按非 root 原顺序、root 最后的顺序处理仓库。`main==tip` 时确认已合并并补写 `merged:true`；`main==base` 且未合并时才执行必要的 `git switch main` 和 `git merge --ff-only <branch>`；`base==tip` 为 no-op。每仓到 tip 后原子保存 merged；全部仓到 tip 后才统一使用 `git branch -d` 清理需求分支。部分 merge、merge 后 state 中断、部分 cleanup 和 `18.json` 已写但 state 未完成均按 Git 事实恢复，不回滚已成功仓库。

最终所有仓库必须位于 main、`HEAD==main==tip`、clean、无进行中 Git 操作且需求分支不存在。步骤先写 root-first 的 scoped `18.json`，再把当前注册表项更新为 `completed` / `completion:{"step":18}`，清空 active requirement/cycle 并返回 cycle 记录节点。第 18 步本体 10 项、CLI 5 项，共 15 项；全量 282 项、`compileall`、`git diff --check` 通过，独立只读审查无高、中置信发现。

真实 `step01-mendmark` 已完成 BR-001 与 BR-002。BR-002 root/frontend/backend 的 local main 分别为 `2f39fbe7e26d6e4905142925ae149ba83d9e70fe`、`f290ff85ed779a1f100eeded7eedfcfb0376b826`、`204a7a6b48c43a80f573dc9e70acedddb59bbe4f`；三仓 clean、`req/br-002` 已删除且未 push。BR-002 scoped `15.json`～`18.json` 均为 success，注册表项为 completed，活动 requirement/cycle 已清空。

### 阶段二：全项目级集成产品体验审计与迭代

阶段二不新增业务步骤编号，使用具名节点表达完整审计闭环：

```text
phase_2:audit
→ phase_2:route_candidates
→ phase_2:resolve_coverage_gaps
→ phase_2:pool_requirements
→ 对入池需求先增量协调需求注册表，再复用第 13～18 步
→ phase_2:regress_and_reaudit
→ 完整复审，直到满足阶段二完成条件
```

阶段二入口：

- 第 12 步需求注册表已经初始化，且当前正式范围内全部需求已经完成第 13～18 步；
- 顶层 `requirement_registry` 在阶段二继续保留，作为既有和后续入池需求生命周期的唯一真源；
- 所有 `applicable_repositories`（其中包含 root）均处于清楚的 `main` 事实；
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
- 正式候选通过根仓库最新 `main` 上的短期入池分支写入 Backlog，精确提交并合并回 `main`；外层同时保存“正式需求 ID → 原审计候选”映射；
- 入池只创建可选择的正式需求，不提前创建活动 TRD、代码分支或完成状态。

修复与复审：

- 一批入池需求先按第 12 步相同的静态解析、哈希和 Python 状态语义原子增量加入既有需求注册表，保留所有既有动态状态；随后循环不接收调用方指定需求，而是每次由第 13 步确定性选择下一项；第 18 步完成后按实际完成的正式需求 ID 查询候选映射并执行对应原发现回归。该协调边界在阶段二实现时落实，不在当前提前创建公共抽象；
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

第 0～2 步继续使用 `current_step`。第 3 步成功时在状态中同时写入 `phase: project_initialization`、`current_node: project:04_assemble_foundation`、`step: 4` 和兼容字段 `current_step: 4`。第 11 步成功时写入 `phase: phase_1_requirement_development`、`current_node: phase_1:initialize_requirement_registry`、`step/current_step: 12`、`active_requirement: null` 与 `requirement_cycle: null`，不新增需求注册表。第 12 步已经实现：它以 Responses/Pydantic 从自由格式 Backlog 唯一提取 `id`、`title`、`order`、`depends_on`，由 Python 校验生命周期结构后初始化需求注册表，success 状态进入 `phase_1:select_requirement` / step 13；注册表保存 Backlog 路径、SHA-256 和每条需求的最小 `pending / active / completed` 生命周期，具体进度由 `phase/current_node` 与活动 cycle 表达，分支、`development_session_id`、逐仓 base/tip/merge 证据和阻塞信息均由 Python 管理。

第 12 步完整 success 的 result、来源、catalog 与 pending 注册表一致时幂等零模型复用；第 13～16 步已实现各自 scoped result、session 和恢复锚点；第 17 步已实现公共 Agent 决策循环、多仓白名单提交、完整 conversation和 base/tip 持久化；第 18 步已实现逐仓 ff-only/`merged` 恢复、统一分支清理、scoped `18.json` 和 completed 生命周期写入。

```json
{
  "phase": "phase_1_requirement_development",
  "current_node": "phase_1:select_requirement",
  "step": 13,
  "requirement_registry": {
    "source": {
      "path": "docs/backlog/backlog.md",
      "sha256": "<backlog-sha256>"
    },
    "requirements": [
      {
        "id": "BR-001",
        "title": "身份、角色访问与站内消息入口",
        "order": 1,
        "depends_on": [],
        "status": "pending",
        "completion": null
      }
    ]
  },
  "active_requirement": null,
  "requirement_cycle": null
}
```

第 18 步结果 schema、合并恢复和生命周期持久化均已实现并完成真实验证。状态只保存支持恢复所需的当前事实和引用，不复制完整历史事件；工作区文件和 Git 仓库仍是实际交付事实，Claude session 保存 Agent 对话，`conversations/` 保存 AI-compatible 完整编排历史。第 2/5/6/7/8/9/10/11/12/13/14/15/16/17/18 步的既有恢复、提交和合并边界保持各自局部合同。

### 3. 恢复原则

- 每个节点开始前保存当前 `phase/current_node` 和已核验输入；成功后原子保存输出、证据和下一节点；
- `blocked` 或 `failed` 时先保留当前现场并停止；只有本次失败携带 Claude Agent SDK 通道的瞬时重试请求时，单步入口才按 10 秒、30 秒有界重跑当前节点两次。普通 `blocked`、确定性 `failed`、AI-compatible 裁决失败、本地合同错误和取消等待显式恢复或修复，不自动重跑；第三次仍请求重试时停止且不继续后续节点；
- `--resume <run-id>` 只恢复当前节点，先重新核验文件、分支、提交、工作树、服务和外部条件；
- 原 Claude session 可用时优先恢复，session 缺失或不一致时不得静默新建会话冒充恢复；
- 已存在产物先核验再继续，不自动删除、覆盖或重复入池；
- 相同且工作树清楚的阶段二 `version_fingerprint` 不重复制造审计候选；
- 阶段二修复期间临时复用需求循环，完成后必须返回原阶段二节点；
- 第 12 步恢复锚点是完整 success result、Backlog 路径/SHA-256、静态 catalog 和一致的 pending 注册表；模型调用期间重新读取 SHA 并拒绝内容漂移，旧三字段 source 不兼容或迁移。result 已写但 state 未推进时从 result 恢复，任一来源、catalog 或注册表漂移均失败。第 13 步是活动需求、统一分支计划和各仓 `main` 基线；第 15、16 步必须保存并恢复同一 `development_session_id`；第 17 步记录每个 dirty 仓的分支 tip；第 18 步按逐仓 `main == tip` 或 `main == base` 恢复 ff-only 合并；
- 第 14～16 步允许合法未提交变更；第 16 步只恢复原 development session并完成复盘，不比较工作树增量，实际变更由第 17 步统一读取并提交；第 18 步全部仓库核验和分支清理成功前不得写 `completed`；
- 任何归属、分支、提交、合并、需求注册表、候选或入池证据冲突均保留现场并返回 `failed`。

## 十、配置与敏感信息

`.env.example` 继续维护最小配置：

```text
LLM_BASE_URL=
LLM_API_KEY=
LLM_MODEL=
PCM_AGENT_BASE_URL=
PCM_AGENT_API_KEY=
PCM_AGENT_MODEL_LOW=
PCM_AGENT_MODEL_MEDIUM=
PCM_AGENT_MODEL_HIGH=
PCM_WORKSPACE_ROOT=
PCM_TEMPLATE_CATALOG=
PCM_TEMPLATE_REPOSITORY=
PCM_AGENT_WORKSPACE_ENV_FILE=
PCM_DEV_RESOURCE_LIST=
```

职责分工：

- `LLM_*`：AI-compatible Responses API；
- `PCM_AGENT_BASE_URL`、`PCM_AGENT_API_KEY`：Claude Agent SDK 使用的 Anthropic Messages 网关和受保护 API Key；Base URL 是紧邻 `/v1/messages` 之前的 API 根，不包含 `/v1`；
- `PCM_AGENT_MODEL_LOW`、`PCM_AGENT_MODEL_MEDIUM`、`PCM_AGENT_MODEL_HIGH`：代码中低、中、高语义档位对应的网关真实模型名；
- `PCM_WORKSPACE_ROOT`：所有产品项目的独立父目录；
- `PCM_TEMPLATE_REPOSITORY`：第 1 步发布开发管理模板；
- `PCM_AGENT_WORKSPACE_ENV_FILE`：第 1 步使用的 AI Agent 工作区受保护工具配置源绝对路径；Python 只通过 `O_NOFOLLOW` 文件描述符读取原始字节并写为新工作区根 `.env`、从创建时即限制为 `0600`、核验 Git 忽略，不解析或导出变量，不进入步骤 outputs、目标产品配置或第 5 步资源清单；该 PCM 控制键从 Claude Agent SDK 子进程环境移除，Agent 只读取已安装的工作区根 `.env`；
- `PCM_TEMPLATE_CATALOG`：第 3 步基础工程候选目录；
- `PCM_DEV_RESOURCE_LIST`：第 5 步可信开发资源清单的绝对路径；Python 只核验路径并交给 Agent，不解析资源内容；完整 Agent/决策交互保存在被 Git 忽略的 run 历史中；
- Claude Agent SDK 不再依赖宿主默认网关或认证：Python 将 `PCM_AGENT_BASE_URL`、`PCM_AGENT_API_KEY` 转为 `ANTHROPIC_BASE_URL`、`ANTHROPIC_API_KEY`，清除冲突认证，并把 `CLAUDE_CODE_SUBAGENT_MODEL` 同步为当前主模型；这些配置与 `LLM_*` 保持独立；

优先级：

- 工作区根：CLI `--workspace-root`、进程环境、`pcm-demo/.env`；
- catalog：CLI `--catalog-path`、进程环境、`pcm-demo/.env`；
- `PCM_DEV_RESOURCE_LIST`：进程环境、`pcm-demo/.env`；必须是可读普通文件的绝对路径，不提供单次 CLI 覆盖；
- `PCM_AGENT_WORKSPACE_ENV_FILE`：进程环境、`pcm-demo/.env`；必须是绝对、可读、非符号链接、非空普通文件，不提供单次 CLI 覆盖；
- `PCM_TEMPLATE_REPOSITORY` 单次运行不可覆盖。

安全规则：

- 实际 `.env` 保持 Git 忽略；
- `.env.example` 只保存键、公开默认值和安全占位；
- 日志、状态、提交和回复不展示 API Key、token、密码、完整认证头或 `.env` 具体值；
- 不伪造外部账号、凭据、授权、服务、设备或客户数据；
- 默认只操作本地文件、本地服务和本地 Git，不 push、不部署、不操作生产环境。

## 十一、运行方式

当前已实现单步入口（第 0～18 步均适用）：

```bash
uv run python run_step.py --step 18 --run-id <run-id>
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

1. 保持第 0～18 步已确认并真实验证的业务边界不变；
2. 第 18 步本体 10 项、CLI 5 项、全量 282 项自动化测试均已通过；真实 `step01-mendmark` 已完成 BR-001 三仓 ff-only 合并、分支清理、scoped `18.json` 和 completed 生命周期更新；
3. 下一项验证继续复用第 13～18 步处理第二个真实需求；
4. 每个步骤只根据真实运行发现补充最小公共能力；
5. 不提前实现阶段二空壳；
6. 每个阶段只根据真实运行发现补充最小公共能力；
7. 阶段一先完整跑通一个正式需求，再验证至少第二个真实需求；
8. 阶段二先在完整集成版本上跑通一次审计、分流、入池、修复回归和完整复审；
9. 最后使用《修迹》产品初稿执行完整端到端运行，并确认源初稿哈希未变化。

## 十三、完成标准

Demo 完成需要同时满足：

1. 第 0～18 步以及阶段二必需节点均已实现，并可由统一入口单独或串联运行；
2. 每个步骤至少真实成功验证一次，或明确证明在修迹项目中不适用；
3. 第 0 步已验证完整初稿的无副作用跳过；
4. 第 1 步真实完成项目身份提取、固定模板浅克隆、模板证据记录、模板 `.env` 拒绝与忽略规则核验、上游 `.git/` 清除、受保护根 `.env` 原字节写入/`0600`/最终 Git 忽略核验、`docs/产品初稿.md` 写入、原子发布和零提交根仓库初始化；
5. AI-compatible 模型能够完成流程所需语义决策，只在不可替代外部资源缺失时阻塞；
6. Claude Agent SDK 能在指定项目工作区加载目标 Skills、plugins 和项目配置，修改文件、执行验证并恢复原 session；
7. 每一步的真实输出由下一步从步骤结果中读取和核验，不从固定路径或历史文字猜测；
8. 第 3～11 步按新版顺序完成，且 `applicable_repositories` 成为后续仓库遍历的单一事实源；
9. 第 12 步已经从正式 Backlog 初始化合法需求注册表；当前正式范围内全部需求均完成阶段一第 13～18 步。黄金项目至少有两个真实正式需求经过该循环，除非最终产品范围事实证明只有一个内聚需求，不能为满足数量伪造拆分；
10. 实现、测试、构建、启动、联调、浏览器验收和独立审查使用真实项目与真实工具，不以 Stub 或模型口头结论替代；
11. 阶段二完整覆盖全部主要任务和多个产品表面，保存实际读取的代表性截图和相称动态证据；
12. 阶段二所有候选完成分流，所有入池需求已增量加入需求注册表、完成第 13～18 步并通过原发现回归；
13. 最后一轮完整复审没有新增符合需求化政策的候选、未处理高信心阻断或高优先级问题，主要任务覆盖缺口已经关闭；
14. 至少验证一次 `blocked` 解除后的 `--resume`，以及一次进程失败后的原节点恢复；
15. 所有 `applicable_repositories`（其中包含 root）最终位于预期 `main`，提交、合并和工作树事实清楚；
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