# PCM 自动化流程 Demo 项目 TRD

> 本文是 PCM 自动化流程 Demo 的轻量活动技术设计，服务于分阶段实现和逐步验证。它不重复定义业务流程，也不提前设计正式 PCM。
>
> 上位文档：
>
> - [`PCM 自动化流程 Demo 项目设计`](./PCM自动化流程Demo项目设计.md)：定义 Demo 的目标、范围、黄金输入和最终完成标准；
> - [`PCM 程序化调度的 AI Agent 产品开发流程`](../../.claude/PCM版AI%20Agent自动化流程设计.md)：定义第 0～18 步、阶段一、阶段二的流程语义、职责边界和停止条件。
>
> 本轮已建立待决策事项的自包含交接与多轮 `continue` 兜底：模板根 `AGENTS.md` 约束 Agent 在确实请求负责人决定时完整说明准确问题、已核验事实与约束、实质可行选项、主要影响及推荐理由，引用只辅助定位；`common/decision.py` 的统一负责人职责在新 conversation 中发现 Agent 已提出待决策事项但只给引用或缺少必要详情时，要求原 Claude session 重新读取并补齐，不在缺少关键信息时猜测决定，也不把交接信息不足本身判为 `blocked`。各步骤既有 `completed/continue/blocked` 判断规则、公共循环、`AgentDecision`、conversation/state、completion verifier、项目上下文范围、历史 run 和外部产品工作区均未修改，也未引入产物全文注入、动态快照、文件读取工具或自然语言解析。fresh Probe C 一次确认引用式待决策交接为 `continue`，一次确认自包含不可替代外部资源缺口为 `blocked`。新规则不迁移既有 decision conversation，Agent 侧模板规则只随未来新建工作区生效。
>
> 本轮 Claude Agent 模型分级已落实：PCM 从自身 `.env` 显式加载 Anthropic Messages 网关、受保护 API Key 和低/中/高真实模型映射；13 条 Agent 执行路径固定 model/effort，子代理默认模型与主模型同步，resume 重传相同 profile。配置、公共循环与固定 profile 定向 49 项、模型 profile 与需求循环定向 101 项、当前工作树全量 367 项 `unittest` 通过（49.802 秒），`compileall` 与 `git diff --check` 通过；中模型 + `high` effort 的公共 runner 首轮与同 session resume 真实成功。未配置 `max_budget_usd`，领域 prompt 和步骤业务语义未变。
>
> 本轮已完成第 9、14、15 步的工程架构约束传递修正：第 9 步明确稳定业务 owner、目录/包/模块边界、公开出口、私有禁区和依赖方向不可被巨型路由/页面、通用收纳目录或同名平铺文件静默替代；第 14 步按每个受影响交付单元把适用工程归属合同和架构 delta 写入活动 TRD；第 15 步负责人要求“架构约束/模块归属→改动位置与依赖关系→diff/导入/调用证据→实际结果”映射。边界内部文件粒度仍可按真实职责调整。第 9/14/15 步本体 35 项、公共循环与三步 CLI 相关回归 91 项、当前工作树全量 367 项 `unittest`（49.013 秒）通过；完整 `compileall`、修改 Python 文件 IDE diagnostics、两个 eval JSON 解析和 `git diff --check` 通过。第 14/15 步负责人上下文仍分别只增加完整 Backlog 与活动 TRD，没有新增工程架构全文注入、Markdown 解析、JSON 架构 DSL、Git verifier、公共循环或状态字段。真实 Agent 集成留给 BR-003 的第 14/15 步自然验证及下一 fresh 项目的第 9 步验证。
公共错误诊断保留经精确凭据遮盖的 Claude Agent SDK `errors`、异常链和 traceback 位置，以及 AI-compatible provider 的 code/type/message/request ID/HTTP status；完整有界快照写入 Git 忽略的 `logs/`，state/result/stderr 保存具体安全原因和引用。真实 `step01-mendmark` 已连续完成 BR-001 与 BR-002；BR-002 在旧“任意非 `success` 均重试”策略下前两次因负责人代码围栏 JSON 失败、第三次成功，第 16～18 步随后完成。该历史不定义现行重试范围。

## 一、目标、当前范围与状态

### 1. Demo 技术实施阶段

Demo 继续采用增量实施，不一次创建完整流程空壳：

1. **技术阶段 0：能力探针**——已完成。验证 Claude Agent SDK、项目 Skills、权限策略、session 恢复和 AI-compatible 结构化决策在本机真实可用；
2. **技术阶段 1：最小骨架与第 0～2 步**——业务步骤已实现。打通完整初稿输入、独立产品项目工作区发布和 `project-intake` 产品定义；
3. **技术阶段 2：第 3～11 步**——第 3～8 步已实现并真实验证；第 9 步当前 prompt 语义合同已经完成代码与自动化，Python 的 Git verifier、result schema、session/恢复/提交/状态逻辑不变；第 10、11 步业务合同不因本轮统计同步而改变。第 9 步新版 prompt 尚待后续安全 fresh 真实 Agent、负责人和 `/commit-changes` 集成验证。按新版顺序覆盖基础工程选型、组装、准备核验、项目化、总体技术方案、仓库首次提交、必要工程架构、按需 UI/UX 框架和 Backlog；
4. **技术阶段 3：循环前第 12 步与阶段一第 13～18 步**——第 12～18 步代码、自动化和适用真实验证已完成；BR-001 已完整跑通需求循环；
5. **技术阶段 4：阶段二完整审计与最终收口**——待逐步讨论和实现。验证全项目体验审计、候选分流、需求化入池、修复回归、完整复审和最终验收。

这里的“技术阶段”只表示 Demo 的实现顺序；上位产品开发流程中的“阶段一”和“阶段二”仍分别指逐需求开发和全项目级集成产品体验审计。

### 2. 当前已实现范围

当前代码已经实现：

- `run_step.py` 的第 0～18 步单步入口；只有本次失败显式携带运行时重试请求时，CLI 才以相同参数按 10 秒、30 秒间隔重新执行当前步骤，最多三次总执行。当前请求只由 Claude Agent SDK 通道的任意 API 状态、明确 `api_error` 终止、连接失败和未取得 Result 的 CLI 进程失败产生；业务 `blocked`、普通 `failed`、AI-compatible 裁决失败、本地合同错误、参数解析失败、未实现步骤和主动取消不重试。请求不写入 state/result/diagnostic/conversation，每次仍重新读取最新现场；第 8～12 步保留固定 result success 保护，第 13～18 步以 current `active_requirement`/cycle 定位并保护 scoped success；
- 第 0 步完整产品初稿无副作用跳过；
- 第 1 步项目身份提取、固定模板浅克隆、模板 `.env` 拒绝与忽略规则核验、受保护根 `.env` 安装、原子发布和零提交根仓库初始化；
- 第 2 步 `project-intake`、第 5 步 `project-readiness`、第 6 步顺序执行的 `project-bootstrap`/条件性 `tailwind-theme` 与第 7 步 `solution-design` 的领域输入、产物、三态结果及幂等边界；
- 第 3 步 Pydantic 输入建模、代码内 system prompt、`responses.parse` 结构化输出和结果保存；
- 第 4 步选型交接校验、run-owned 临时目录、模板 shallow clone 与来源核验、拒绝上游 `.git`/符号链接、适用 payload 的 `git init -b main` 与 top-level / `main` / unborn / 空 index 核验、原子发布、结果和状态持久化、失败恢复与幂等复用；
- 第 5～7 步接受适用子仓边界，在 `completed` 与 `blocked` 终止前复核；只有 `status=success` 的步骤结果可复用，`failed` / `blocked` 结果不阻断原 session 恢复；
- 第 8 步严格使用 `['root', *steps/04.json.outputs]` 权威仓库清单，并只读核验每仓自身 top-level、`main` 与 `status --porcelain`；全部干净时零 Agent、零决策调用直接成功，dirty 时才由一个产品根 `commit-changes` session 处理必要提交，结果/state 支持幂等恢复；
- 第 9 步始终 `applicable: true`，固定读取第 2 步两份产品定义、第 5 步准备清单、第 7 步总体技术方案和第 8 步严格 success 的空 `outputs`、result/state 一致的合法有序 `applicable_repositories`，在单一 `engineering_architecture` session 中形成单份根仓 `docs/design/工程架构设计.md`。Agent 必须以 `[当前]`、`[目标]`、`[按需]`、`[迁移]` 为每个包含业务代码且相关的适用交付单元分别建立有限地图，并以有证据的架构决策矩阵收敛职责、语义所有权、公开/私有边界、依赖与共享准入、代表性文件放置、最小迁移、可观察演进和当前下游所需的高影响决定：前端闭合装配/路由页面、功能、远程/局部/跨页状态、模型映射和共享 UI；后端闭合入口、编排规则、持久化适配、事务、授权、错误与副作用恢复；每单元至少一个文件放置演练。稳定业务 owner、目录/包/模块边界、公开出口、私有禁区和依赖方向属于约束，代表性文件只验证归属，边界内部文件粒度可按真实职责调整；前端不得把稳定职责静默打平到巨型路由/页面或通用收纳目录，后端不得把稳定业务包静默降级为同名平铺文件，跨所有者合并、出口绕过和私有路径引用等 Current 偏差须设计最小迁移。不得固定框架目录、以行数阈值拆分，或为 MVC、分层、六边形或 DDD 预建无当前消费者的层、服务、队列、接口或共享结构。repair 后仅在根仓存在且仅存在固定文档未提交变化时才在原 session 调用 `/commit-changes`，否则已 tracked 且全仓 clean 即完成。Python 仍不解析这些 Markdown 语义，只核验该固定文档与当前 Git 边界；
- 第 10 步仅以第 8 步严格交接的 `applicable_repositories` 是否含 `frontend` 判断 Demo v1 适用性；不适用时按执行产物存在性拒绝并保持零执行副作用，适用时在单一 `ui_ux_framework` session 中生成 `docs/ui-ux/framework.md`，按与第 9 步相同的按需提交条件核验。负责人按新版框架合同要求适用的 App Shell Contract 闭合，区分 Current、已确认 Target、带依据和重议条件的默认 Target、具体待确认、偏差与非目标，不接受整份框架泛化待确认；
- 第 11 步严格读取第 2/5/7/8/9/10 步交接，在单一 `requirement_breakdown` session 中生成唯一 `docs/backlog/backlog.md`；负责人只在已确认 Target 的迁移同时满足既有表面演进、独立可观察用户结果和严格开始前条件时创建迁移 BR/依赖，默认 Target 只进入相关 BR 的体验约束并保留依据/重议条件；repair 后仅在固定 Backlog 是唯一根仓未提交变化时调用 `/commit-changes`。Backlog 不记录需求开发状态，Python 只读 Git，success 进入第 12 步初始化入口；
- 第 12 步严格消费第 11 步完整 success；Responses/Pydantic 是自由格式 Backlog 的唯一语义提取路径，只输出 `id`、`title`、`order`、`depends_on`；Python 不解析 Markdown 排版，只校验非空 catalog、合法且忽略大小写唯一的 ID、数组物理顺序对应连续 `order`、依赖存在/不重复/不自依赖/无环，从同一字节快照记录 Backlog SHA 并在模型调用后检查漂移，再先写 result、后写全 pending 注册表；不调用 Claude Agent、`AgentDecision` 或 Skill，不写产品或执行 Git；
- 第 13 步消费第 8 步仓库交接和当前 `state.requirement_registry`，零 AI/Agent/Skill 确定性选择 ready pending 需求；不读取或按现行第 12 步 schema 复验历史 `steps/12.json` / `source`。fresh 全局预检后先写 active intent/cycle，再仅以 `git switch -c` 在全部适用仓建立 `req/<lowercase-id>`，写 scoped result 并推进第 14 步；
- 第 14 步采用与第 15 步一致的薄编排，只消费 current active/cycle/workspace 和需求注册表已记录的 canonical Backlog 来源，首次持久化 exact `trd_path`，再通过 requirement-scoped 公共循环显式调用或恢复 `/trd-design`；Python 读取完整 Backlog 正文放入负责人的 `<project_context>`，不加入尚未生成的 TRD 正文、工程架构全文或其它上游文档；Agent 按需读取其它项目事实、本需求适用的体验决定和可核验工程架构资料。TRD 按每个受影响交付单元记录稳定 owner、目录/包/模块边界、公开/私有边界、允许/禁止依赖和预期改动归属；边界内部文件粒度可调整，跨所有者合并、边界打平、出口绕过、私有路径引用或以巨型入口/页面、通用收纳目录、同名平铺文件替代已确认边界时，须作为架构 delta 记录影响、理由和最小迁移。体验决定仍记录来源、范围、Current/Target、遵循或改变关系，默认 Target 还记录依据和重议条件；Python只核验指定 TRD 非空，不读取 Git或重复复验前序步骤，success 推进第 15 步；
- 第 15 步只消费当前 active requirement/cycle/workspace、当前 requirement 的第 14 步 scoped success 与非空活动 TRD，在 `development_<ID>` session 中调用 `/dev-workflow`；Python 将完整活动 TRD 正文放入负责人的 `<project_context>`，不重复加入 Backlog、工程架构全文或其它上游文档；Agent 按活动 TRD 与适用工程架构约束实施。有适用工程架构约束时，完成报告按每个受影响交付单元建立“架构约束/模块归属→改动位置与依赖关系→diff/导入/调用证据→实际结果”映射，稳定边界不得被巨型路由/页面、通用收纳目录、同名平铺文件、跨所有者合并或私有路径穿透静默弱化，必要架构 delta 同步活动 TRD；适用体验决定仍映射到可观察结果、实现位置、真实浏览器和实际读取截图证据及实际结果，截图不替代动态行为验证；负责人 completed 后写 scoped result、同步 `development_session_id` 并推进第 16 步；
- 第 16 步采用薄编排，只消费当前 active requirement/cycle/workspace 与 `development_session_id`，建立 `rule_retrospective_<ID>` 独立负责人 conversation、预注册原 development session alias并调用 `/session-rule-retrospective`；允许规则变化或 no-change，success 写 scoped result、`outputs: []` 并推进第 17 步，不读取 Git或建立 baseline；
- 第 17 步只消费当前 active requirement/cycle/workspace、完整 scoped 第 16 步 success、统一需求分支与各仓 base，在产品根通过公共 Agent 决策循环调用 `/commit-changes`；保存完整 conversation，负责人处理 `continue/blocked/completed`，Python只核验白名单、分支、main/base、最终 clean 和 tips并推进第 18 步；
- 第 18 步只读取当前 active requirement/cycle、权威仓库路径和 scoped 第 17 步 success 的必要字段；以确定性 Python/Git 按非 root 在前、root 最后的顺序执行或恢复 ff-only，逐仓持久化 merged，全仓到 tip 后统一安全删除需求分支，写 scoped `18.json` 并完成注册表生命周期；
- `common/agent_decision_loop.py`：多个 Agent 领域步骤共用的 session、完整对话、`AgentDecision`、尾部恢复、SDK 终止分类和完成核验循环；
- 第 7 步固定方案文档、完整原文的 Git 忽略 run 历史和无全仓扫描要求；
- 公共 OpenAI Responses 封装已经统一为 Pydantic `input_model`、`output_model` 和 `output_parsed`，通用决策入口允许步骤传入专属 system prompt 和输出模型；

当前尚未实现：

- 阶段二全项目体验审计、候选分流、入池、回归和复审节点。`run_all.py` 已实现第 0～18 步的阶段一串联与恢复，当前正式需求全部完成后停止。

第 9 步当前 prompt 合同已完成代码与自动化，但尚未执行安全的 fresh 真实 Claude Agent、AI-compatible 负责人或 `/commit-changes` 集成；第 10、11、14、15 步已按新版 UI/UX 决定传递合同同步 Prompt、负责人完成规则与定向自动化，尚未据此改写旧合同真实运行事实。第 0～8、12～18 步已完成代码、自动化和适用真实验证；未实现能力必须返回明确程序错误，不得以空脚本、固定 JSON、旧实现或口头结论冒充成功。

### 3. 本轮实现与同步边界

本轮按照“先代码与自动化测试，再补真实集成验证和文档事实”的顺序完成：

- 第 8 步的权威多仓只读 Git 核验与干净基线、第 9～11 步的固定文档边界、tracked 核验和按需提交均保持步骤私有，不扩展为公共 Git DSL、commit 事件、持久布尔标记或旧 prompt 兼容列表，也不抽取通用 commit 能力；
- 统一完整 Agent 原文 → 负责人返回的 `AgentDecision(completed/continue/blocked)` → 步骤程序完成核验的顺序；新 conversation 保存动态 system snapshot，删除新协议中的待发送 prompt、决策轮次和 Python 完成声明；
- 第 7 步不再对回复做脱敏替换；新 run 的完整回复、pending 文本和决策输入均保存在 Git 忽略 run 目录，Agent 仍不得主动披露秘密；
- 第 9 步更新后的 prompt 合同及第 9～11 步相关自动化已完成本轮验证：第 9 步定向 18 项通过（5.498 秒）；第 9～11 步本体合计 51 项（18+18+15）通过；公共循环加第 9～11 步本体及第 10/11 步 CLI 的相关回归 97 项通过（20.800 秒）；当前工作树全量 351 项 `unittest` 通过（61.878 秒）；`compileall common steps run_step.py run_all.py test_run_step_retry.py test_run_all.py` 与本次目标 `git diff --check` 通过。当前工作树还包含其它公共循环/CLI 的未提交修改，故全量结果是当前工作树验证，不能全部归因于第 9 步。第 9 步新版 prompt 合同尚未执行安全的 fresh 真实 Claude Agent、AI-compatible 负责人或 `/commit-changes` 集成；`step01-mendmark` 已推进到第 13 步并保留旧第 9 步 success/session/conversation，旧真实 run 仅为旧合同历史。
- Probe C 的格式重试和 `probe-c-20260822T200038Z` 结果均保留为旧合同历史。现行 `common/decision.py` 要求步骤显式传入完整 XML system prompt，将其原样传给一次 `responses.parse` 并以 Pydantic `AgentDecision` 取得结构化输出；没有公共默认或隐藏追加 prompt，也没有格式重试。第 9、10 步 fresh 运行仅是该 prompt 的旧合同历史证据，不替代新成功条件验证；
- 隔离 run `agent-loop-step7-20260822T190149Z` 已在新 `solution_design` session 中真实验证公共循环的第 7 步错误保留、同 session 恢复、completed 后固定 repair 与最终成功推进；其中旧格式重试决定不作为现行 XML prompt 证据；
- 第 8 步 run `step08-real-20260823-a/b` 保留第 1 步代码围栏/Responses `incomplete`/自创字段、第 3 步 `ValidationError`、第 7 步 API 500 与 failed 结果误复用、`.coverage` 授权循环、SHA 和重跑事实；它们都是旧“唯一初始提交证明”合同历史，不是当前完成条件。当前合同已由真实 run `step01-mendmark` 完成 Agent 集成验证；
- 第 9 步旧失败依次暴露 HTTP 403、非 JSON 普通文本和非法 `completed` 字段组合；其后第 9～11 步 fresh 运行的固定文档、exact commit、状态推进、Git 核验与幂等重跑，均为旧合同下的历史执行路径，不构成新合同成功条件。第 12 步对该历史 Backlog 的真实 Responses 注册、状态推进与零模型幂等重跑事实保持不变；
- Git 忽略 run `prompt-role-replay-20260823` 保留旧四段 XML prompt 的历史回放，不再作为现行 prompt 证据；第 9 步 fresh 运行的五段 prompt 也仅为旧合同历史证据；
- 第 9 步更新后的 prompt 合同及第 9～11 步相关自动化已完成本轮验证：第 9 步定向 18 项通过（5.498 秒）；第 9～11 步本体合计 51 项（18+18+15）通过；公共循环加第 9～11 步本体及第 10/11 步 CLI 的相关回归 97 项通过（20.800 秒）；当前工作树全量 351 项 `unittest` 通过（61.878 秒）；`compileall common steps run_step.py run_all.py test_run_step_retry.py test_run_all.py` 与本次目标 `git diff --check` 通过。当前工作树还包含其它公共循环/CLI 的未提交修改，故全量结果是当前工作树验证，不能全部归因于第 9 步。第 9 步新版 prompt 合同尚未执行安全的 fresh 真实 Claude Agent、AI-compatible 负责人或 `/commit-changes` 集成；`step01-mendmark` 已推进到第 13 步并保留旧第 9 步 success/session/conversation，旧真实 run 仅为旧合同历史。

### 4. 本阶段继续不做

- 不一次创建第 12～18 步或阶段二节点的空壳脚本；
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
- 根仓库在第 1 步初始化为零提交 `main`；第 4 步对每个适用子仓建立 `main` / unborn / 空 index 边界；第 8 步只读取并检查这些既有仓库是否形成干净基线，不重复初始化；
- 第 8 步已经生成 `applicable_repositories`，后续不固定遍历不存在或不适用的 `frontend/`、`backend/`。

### 2. 两类模型调用职责不同

**AI-compatible 模型**是实际使用 Claude Code Agent 的项目负责人、工程负责人和 Agent 专家，处理所有能够基于当前输入、项目事实、可用工具和已提供资源完成的产品、技术、文档、流程及执行决策。它读取完整 conversation：`assistant` 是负责人发给 Agent 的初始、继续或修复指令，或负责人每轮返回的 `AgentDecision` JSON；`user` 是 Agent 完整真实回复。它不直接获得工作区文件和 Shell 操作权限，由 PCM 提供当前决定所需的最小事实。Agent 请求负责人决定时，项目规则要求其自包含准确问题、已核验事实与约束、当前约束下实质可行选项、各选项主要影响及推荐理由，文件引用只作辅助；只给路径、章节、提交、代码符号或行号，或缺少可靠决定所需内容时，负责人必须 `continue` 要求原 session 重新读取并补齐，不得猜测、`completed` 或把信息不足判为 `blocked`。只有模型和当前环境无法取得的不可替代外部资源时才返回 `blocked`；输入、结构或本地状态错误返回 `failed`。

**Claude Agent SDK**负责运行具备文件、命令和项目能力上下文的 coding agent，调用项目 Skills、修改工作区文件、执行验证，并返回 session 结果。Agent 能依据当前事实安全决定的普通事项自行处理，不机械上抛；确需决定时按项目规则完成自包含交接。

Python 编排器负责确定性操作、两类会话衔接和最终步骤状态，不把任何模型的单次文字输出直接视为完成证据，也不为该交接合同解析回复、读取产物全文或扩展公共状态机。

### 3. Claude Agent SDK 当前约束

首轮实现基于 Python 包 `claude-agent-sdk`，最低 Python 版本按 SDK 当前要求使用 Python 3.10+。探针 A 的真实运行环境为 Python 3.13.14、`claude-agent-sdk` 0.2.139 和 SDK 捆绑的 Claude Code 2.1.233；宿主机另有 Claude Code 2.1.223，但本次未使用它作为后备路径。

每次项目 Agent 调用必须显式设置或保证：

- `cwd`：本次运行的独立项目工作区根目录；
- `system_prompt`：使用 `claude_code` preset，不能依赖 SDK 的最小默认 prompt；
- Skills 和 plugins：按项目配置与锁定事实加载，并从 init 消息核验目标能力；
- `model` 与 `effort`：每次首次调用和 resume 都显式传入固定任务 profile；不依赖宿主默认模型；
- `max_turns`：保留步骤级有限上限；不配置 `max_budget_usd`，避免金额上限在任务仍可完成时截断服务；
- `max_buffer_size`：公共 `ClaudeAgentOptions` 固定为 10 MiB，修复 SDK 0.2.139 单条 CLI stdout JSON 默认 1 MiB 上限；不增加配置且不影响 `resume`；
- `resume`：需要继续特定历史会话时使用已保存的 session ID。

固定 profile 为：第 2、5、7、9、10、11 步高模型 + `high`；第 6 步 bootstrap/theme、第 14、15 步中模型 + `high`；第 8、16、17 步中模型 + `medium`。第 15～17 步保持同一中模型。每次首次调用和 resume 都重新传入 model 与 effort；当前不为 Agent 步骤使用低模型，不配置 fallback model 或 `max_budget_usd`。

正式步骤不传入 `permission_mode`、`tools`、`allowed_tools` 或 `disallowed_tools`，也不为每一步重新定义权限档位。项目 `.claude/settings.json` 及 Claude Code 默认设置加载语义是统一权威来源。若未来某一步确有覆盖项目配置的特殊理由，必须先在该步合同中说明并单独确认，不能沿用探针限制。

第 2 步真实运行确认：Claude Code 对未信任的新路径会忽略项目 `permissions.allow`。PCM 采用默认 Claude Code 用户配置目录、认证、插件、Skill 和 session；在 `~/.claude.json` 中为已由第 1 步发布证据确认的最终产品路径写入 `hasTrustDialogAccepted: true`，使项目 settings 生效。该用户级配置共享所有 PCM run，符合单租户本地 Demo 的预期；不得把 run-local `CLAUDE_CONFIG_DIR` 作为默认隔离层。

普通终端执行第 0→2 步时，默认用户级 Claude 配置、认证、项目 plugins/Skills 和 session 均可用；第 2 步完成后 run 目录不创建 `claude-config/`，同一 run 重跑第 2 步可以恢复原会话或幂等确认成功。

项目 Skills 来自工作区 `.claude/skills/` 和项目锁定 plugins。核心流程 Skills 多数设置了 `disable-model-invocation: true`，因此步骤脚本应显式调用目标 Skill，不能只依赖模型自主选择。探针 A 已确认 `/project-intake` 可以显式调用，且目标 Skill 同时出现在 init 消息的 `skills` 和 `slash_commands` 中。

探针 A 使用显式权限覆盖验证了 SDK 的限制能力，也确认 Skills、plugins 和项目设置的实际加载结果需要从 init 消息核验。这些探针配置只证明 SDK 行为，不作为正式步骤的默认权限合同。

### 4. AI-compatible 配置与调用

`LLMConfig` 从 `pcm-demo/.env` 加载 `LLM_BASE_URL`、`LLM_API_KEY` 和 `LLM_MODEL`；`AgentConfig` 独立加载 `PCM_AGENT_BASE_URL`、`PCM_AGENT_API_KEY` 与低、中、高三级真实模型名，同名进程环境变量优先。实际 `.env` 由 Git 忽略，配置对象的 `repr` 不包含凭据；`.env.example` 只保存公开占位说明。Python 将 Agent 配置显式转换为 Claude Code 子进程的 `ANTHROPIC_BASE_URL`、`ANTHROPIC_API_KEY`，并同步子代理默认模型；两类模型配置不混用或相互回退。

SDK 不自动读取 Demo 的 `.env`。配置模块必须在创建 Agent SDK 或 OpenAI-compatible 客户端前显式加载配置，且不得把密钥写入状态或日志。探针 C 运行时发现宿主环境配置了 SOCKS 代理，但当前 OpenAI SDK 环境没有 SOCKS 依赖；探针通过 SDK 的 `DefaultAsyncHttpxClient(trust_env=False)` 明确禁用环境代理，未修改宿主代理配置，也未增加无关依赖。

项目身份、AI-compatible 决策和基础工程选型统一调用 OpenAI Python SDK `responses.parse`。调用方将输入构造成 Pydantic `BaseModel`，将输出模型类型传给 `text_format`，并直接使用 `response.output_parsed`；公共封装不再接收手写 JSON Schema，也不返回待 `json.loads()` 的原始字符串。第 3 步 system prompt 直接定义在 Python 代码中，只描述领域任务，不包含步骤编号或编排背景。

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

- `run_step.py`：当前运行已经实现的第 0～18 步；实际命令和配置说明以 `pcm-demo/README.md` 及各步骤 README 为准；
- `run_all.py`：已实现阶段一串联与恢复，每轮根据 state 启动新的 `run_step.py` 子进程；阶段一全部正式需求完成或子步骤非零退出时停止，并显示独立计时汇总；
- 未实现步骤必须明确返回“步骤尚未实现”的程序错误，不得返回业务 `success`；
- 单步、区间、完整运行和恢复最终必须复用相同步骤或节点函数；
- 阶段二使用 `--from-node phase_2:*` 一类具名入口，不新增虚假业务步骤编号。

### 2. 当前公共模块

```text
pcm-demo/
├── config.py
├── common/
│   ├── agent_decision_loop.py
│   ├── claude_agent.py
│   ├── decision.py
│   ├── files.py
│   ├── openai_responses.py
│   ├── state.py
│   └── timing.py
├── probes/
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
├── run_step.py
└── run_all.py
```

只有出现两个及以上步骤的真实复用时才合并或新增公共模块，不为保持目录图创建空文件。

### 3. 状态事实来源

- `state.json` 只保存支持恢复所必需的当前状态；
- `steps/<step>.json` 保存业务步骤最近一次详细结果；
- 阶段二节点结果保存于明确的节点结果或状态引用中，具体目录在阶段二实现前确认；
- `logs/` 覆盖保存当前失败的完整有界诊断快照：经精确凭据遮盖的 SDK/provider 错误、异常链和 traceback 位置；不建设追加式日志平台；
- `conversations/` 保存完整、可恢复的编排历史；新 run 原文位于 Git 忽略目录，Agent 仍不得主动披露秘密；
- 工作区文件和 Git 仓库保存实际交付事实；
- Claude session 保存 Agent 对话上下文；
- 不把完整历史事件重复写入 `state.json`。
- `timings.json` 独立保存命令执行计时，不参与任何业务成功、失败、恢复或生命周期裁决。

### 4. 步骤计时合同

统一计时由 `common/timing.py` 实现，`run_step.retrying_main()` 外层持有一个计时对象，首个合法步骤 attempt 开始时读取单调时钟并保存 UTC 起点，所有自动重试和 10/30 秒等待结束后才结束本次计时。`main()` 仅把已经得到的 run 目录、业务结果和需求归属传给观测对象，不增加结果字段或改变现有三态、完成条件、模型 prompt、session、Git 与重试合同。开始/结束信息使用 stderr，原 stdout 结果路径保持不变；`run_all.py` 不重复计时，只在阶段一完成或停止时读取并展示汇总。

独立文件为 `runs/<run-id>/timings.json`，顶层为 `schema_version: 1` 与 `executions` 数组。每次命令调用保存 `step`、`name`、可空的 `requirement_id`、`started_at`、可空的 `finished_at` / `elapsed_seconds`、`attempt_count`、可空的业务 `status`、`applicable`、`reused_success` 与 `history_missing`。状态为空表示计时尚未收口或执行被中断，不是新增业务状态。JSON 沿用同目录临时文件加原子 replace；计时数据损坏或读写失败时保留已有记录、警告并停用本次持久化，不改变业务退出码，不复制业务输入、模型回复、错误详情或凭据。

计时归属与汇总规则：

- 第 0～12 步归属项目；第 13～18 步以需求 ID 和步骤编号区分。开始时从已有 active 捕获归属，第 13 步可在实际选择后从结果或当前 state 补充；选择前失败保留空归属。第 18 步不能仅凭结束后的 active/cycle 判断归属，因为业务完成会清空它们。
- 同次自动重试只有一条计时记录，尝试次数累计，耗时包含等待。failed/blocked 正常退出关闭本次计时；显式恢复新增记录，累计运行耗时为达到首次 success 前各次已测执行之和，不包括进程退出后的等待间隔。
- 执行前已有同作用域成功结果且本次业务调用仍返回 success 时，单独标记 `reused_success`；不以完整 JSON 或摘要相等判断复用，结果是否可复用仍由原步骤负责。保留复用检查耗时但不计入原始完成耗时；达到首次成功后的累计运行和完成时间保持不变。不适用跳过保留真实检查耗时并明确标识。
- 完整总历时为首次开始至首次成功结束的 UTC 时间差，仅在起点与各段记录完整、时间差非负时展示。系统时钟回拨不改变单调时钟测出的运行耗时，总历时无法可信计算时显示未记录。
- 开始记录在已存在的 run 目录内先落盘；新 run 仍由业务逻辑创建目录，计时不提前创建目录。目录尚未建立时只有内存起点，进程在此期间终止可能没有持久化记录。已建立目录的强杀或未执行收口会留下空结束字段；不把下次恢复时间写成该次结束时间，也不补算未知时长。正常取消能测得的时段保留，但总体标记不完整。
- 旧结果没有计时则展示未记录，不用 run ID、文件 mtime 或 SDK 单次 duration 推算。中途接入旧运行或已有未闭合记录时，只汇总已知时段并标记不完整，不生成完整总历时。当前已启动进程不热加载，新启动的子步骤自然加载新计时代码。

本功能不增加预计剩余时间、超时策略、定时心跳、模型耗时拆分、成本统计或外部监控服务。

本轮验证：计时与入口定向 54 项通过，PCM Demo 全量 401 项 `unittest` 通过（57.350 秒），`compileall` 与 `git diff --check` 通过。覆盖实际第 12 步的零模型成功复用与摘要变化、异常累计数值不改变退出码、自动重试等待、失败/阻塞恢复累计、需求归属、幂等冻结、旧历史缺失、真实临时子进程第 0 步及仅针对测试子进程的 SIGTERM。另以黄金初稿执行独立真实 CLI run `timing-smoke-20260905` 的第 0 步，无副作用跳过并记录 0.012473792 秒，实际读取计时文件与终端汇总，确认运行数据被 Git 忽略。本次未调用外部模型或重跑真实产品的完整阶段一，未中断、迁移或修改已有运行数据；Ruff 与 Pyright 未安装，未执行这些检查。

## 四、公共技术合同

### 1. 步骤与节点结果

每个步骤或阶段二节点只向外返回以下三种业务状态：

- `success`：完成条件已满足，或已确认不适用并无副作用跳过；
- `blocked`：缺少模型和当前环境无法取得的不可替代外部资源；
- `failed`：程序、SDK、模型、命令、解析、文件、Git、验证或状态发生错误。

第 0～12 步结果继续使用统一步骤字段；第 13～17 步 result 按需求 ID 隔离于 `steps/requirements/<ID>/<step>.json`。第 17 步 success 除公共字段外严格保存 requirement ID、统一分支和按适用仓顺序的 `name/path/base_sha/tip_sha`，`outputs` 固定为空；cycle 同步保存 `{base_sha, tip_sha, merged:false}`。`phase/current_node` 作为运行状态中的恢复位置，不重复写入每个步骤结果。

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

`blocked` 至少包含：

```json
{
  "reason": "缺少不可替代的外部输入",
  "required_inputs": ["输入名称"],
  "resume_phase": "project_initialization",
  "resume_node": "project:03_foundation_selection"
}
```

业务步骤继续保留 `current_step` 兼容信息；第 3 步成功时同时在状态中写入 `phase: project_initialization`、`current_node: project:04_assemble_foundation` 和 `step: 4`。阶段二恢复不能只依赖数字步骤。

`error` 至少包含稳定错误类型、经精确凭据遮盖的具体原因和适用时的 `diagnostic_path`。state 与步骤结果不复制完整 traceback；完整有界诊断写入 Git 忽略的 `logs/`。不得保存 API Key、完整认证字段、环境字典、请求/响应 body、prompt 或 `.env` 具体值。

### 2. 输出路径与交接

- 业务文档与工程产物的 `outputs` 统一记录相对于产品项目根 `state.workspace.final_path` 的非空相对路径；
- 下游必须以产品项目根解析并核验，拒绝绝对路径、越出根目录的 `..` 路径和符号链接；
- 运行控制数据可以保存在步骤结果的稳定字段中，例如第 3 步 `steps/03.json.template_selection`，不强制伪装成项目文件产物；
- 下一步从前一步结果读取实际交接对象，不从固定路径、技术文档、Agent 自然语言或会话历史重新推断；
- 阶段二审计原始结果、候选分流、入池和回归证据通过稳定引用保存，不能只留在 session 中。

### 3. 第 1 步工作区发布合同

第 1 步使用 AI-compatible 模型从产品初稿提取严格 JSON。prompt 只允许 `topic_name`、`project_directory_name`、`directory_name_source`、`reason`、`blocked_reason` 五个字段，并禁止 Markdown、代码围栏、YAML 或 JSON 之外的文本：

```json
{
  "topic_name": "基于 Web 的社区物品维修预约与维修进度协作系统",
  "project_directory_name": "mendmark"
}
```

`topic_name` 必须明确表达当前产品选题。`project_directory_name` 必须是单段小写 kebab-case；初稿已经给出仓库名或英文代号时优先提取，未给出时允许模型根据选题生成，并把来源和生成理由写入提取证据。初稿无法确定产品选题、API 或结构解析失败、有限重试耗尽时返回 `failed`，不能猜测字段。

产品工作区根目录的优先级为 CLI `--workspace-root`、进程环境 `PCM_WORKSPACE_ROOT`、`pcm-demo/.env` 中的同名配置，并且必须位于当前能力仓库之外。模板仓库从进程环境或 `pcm-demo/.env` 的 `PCM_TEMPLATE_REPOSITORY` 读取，AI Agent 工作区受保护工具配置源从 `PCM_AGENT_WORKSPACE_ENV_FILE` 读取，后二者都不能由单次 CLI 覆盖。配置源必须是绝对、可读、非符号链接、非空普通文件；其原始内容只写入新工作区根 `.env`，不解析、不导出，也不属于目标产品资源。最终项目路径为 `<root>/<project_directory_name>`。

确定性发布顺序为：

1. 保存源产品初稿的绝对路径、完整 UTF-8 内容和 SHA-256；
2. 在最终目录同级计算 `<project_directory_name>.pcm-tmp-<run-id>` 临时路径；
3. 先用 Git 核验已配置模板仓库默认分支和读取权限，再执行 `git clone --depth 1`；
4. 记录模板默认分支、实际分支、commit SHA 和 remote URL，核验 `CLAUDE.md`、`AGENTS.md`、`project-intake` Skill、`frontend/` 与 `backend/` 等关键能力，拒绝任何形态的模板 `.env`，并使用禁用用户级 global excludes 的实际 Git 规则确认模板根忽略 `.env`；
5. 只在临时目录已证明属于当前 run 后删除其中的上游 `.git/`，删除原 `docs/` 内容后重建空 `docs/`，按原始字节写入 `docs/产品初稿.md`，并将工作区配置源原始字节独占写为根 `.env`、设置精确 `0600`；
6. 核验上游 `.git/` 已删除、`docs/` 只含产品初稿、源和目标初稿哈希一致、源文件未变化、模板能力仍存在，以及根 `.env` 内容和权限与当前配置源一致；
7. 所有发布核验通过后，将同文件系统中的临时目录原子重命名为最终项目路径；
8. 在最终项目根执行 `git init -b main`，不执行 `git add`、`git commit` 或 push；
9. 核验 `git rev-parse --show-toplevel` 等于最终项目根、当前分支为 `main`、`HEAD` 尚不存在，并再次确认根 Git 忽略 `.env`，记录根仓库初始化证据。

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
    "agent_workspace_env_file": "/protected/agent-workspace.env",
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

失败时保留现场。恢复只续接状态能证明属于同一 run、同一模板、同一工作区环境源路径和同一目标的完整 clone、prepared 临时目录或已发布最终目录；每次都以当前配置源原始字节复核根 `.env`，不在状态、结果或日志保存其内容、值或摘要。不完整 clone、环境源路径/内容漂移、根 `.env` 权限或忽略规则漂移、临时与最终目录同时存在、目录归属不明或证据冲突时不自动删除、覆盖或修补。最终目录已发布但根 `git init` 中断时，只有发布证据和根 `.env` 一致、根 `.git/` 不存在或仍是零提交 `main` 仓库，才允许续接或幂等确认根仓库初始化；已有 commit、Git 根指向其它目录或分支不一致时返回 `failed` 并保留现场。已经推进到第 2 步及之后的旧 run 不回退，也不由后续步骤补写。

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
api_error_status
terminal_reason
errors
exception
```

处理规则：

- `success` 的完整回复进入结构化裁决，不能直接代表步骤成功；
- `error_max_turns` 与 `error_max_budget_usd` 只有保存了 session 且回复非空时才可进入裁决；即使裁决为 `completed`，也必须在同一 session 后续取得正常 `success`，才能最终完成；
- API 400/429/500、连接、Claude CLI 或子进程错误、无 `ResultMessage`、缺少完整回复、session/cwd/Skill/slash command 不一致、`terminal_reason` 为 `aborted_streaming` 或 `aborted_tools`，以及 `success` 下未知终止原因都在请求决策前返回 `failed`；
- 单次 `query()` 在出现 ResultMessage 后仍可能抛异常；公共封装保留 `ResultMessage.errors`、HTTP status、terminal reason、经精确凭据遮盖的异常正文、异常链与 traceback 位置，并由公共循环写入 Git 忽略诊断快照；
- state、步骤结果和 stderr 只保存具体安全原因与 `diagnostic_path`，不复制完整 traceback；
- 收到 ResultMessage 后继续消费消息流至结束，避免漏掉尾随系统事件；
- SDK 正常结束后仍必须执行统一裁决和步骤自己的完成条件核验；
- 不在公共循环外增加自定义 HTTP 重试。

### 5. AI-compatible 决策结果

决策模型使用以下最小结构：

```json
{
  "verdict": "continue",
  "answer": "采用当前输入和项目事实支持的方案，并继续完成当前工作。",
  "reason": "该决定可由现有资料和工具完成，不依赖额外外部资源。",
  "required_inputs": []
}
```

`verdict` 只允许：

- `completed`：负责人根据 Agent 执行结果相信当前任务已完成；仍须通过步骤程序的完成核验，`answer` 与 `required_inputs` 均为空；
- `continue`：向原 session 发送非空的明确指令，`required_inputs` 为空；Agent 请求决定但只给路径、章节、提交、代码符号或行号，或缺少准确问题、已核验事实与约束、实质可行选项、主要影响、推荐与理由时，只能使用该 verdict 要求原 session 重新读取并补齐；
- `blocked`：缺少当前环境不可取得的真实外部资源，`answer` 为空且 `required_inputs` 非空；信息不足或引用式交接不构成阻塞。

决策负责人拥有原人工调度者在同等输入和工具条件下可完成的全部决策权。交接完整且现有事实足够时直接选择合理方案，不继续上抛；交接不完整时不得猜测、不得 `completed`。步骤仅维护领域 `DECISION_RULES`；公共渲染器分别生成 `<role>`、`<project_context>`、`<responsibility>`、`<completion>`、`<output>`。统一 responsibility 承担交接充分性兜底，步骤规则只进入 completion；output 约束 `completed/continue/blocked` 的 `answer`、`required_inputs` 组合并要求 `reason` 非空。`request_decision` 原样调用一次 `responses.parse`，以 Pydantic `AgentDecision` 取得结构化输出；没有手写解析、决定注入、隐藏 prompt、产物全文注入或格式重试。

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
- AI-compatible 接口不依赖服务端 conversation 或 response ID；PCM 按领域键把完整编排消息历史原子写入 `runs/<run-id>/conversations/<key>.json`，每次调用携带该历史；
- 新协议历史保留 system、发给 Agent 的初始/继续/修复指令、每轮 Agent 完整真实回复与每次完整结构化决定；不再新写 Python 完成标记；
- 不同步骤、不同正式需求和不同阶段二审计轮使用独立领域键，避免上下文污染；
- 恢复状态的核心仅为 session、历史 `path` 引用、最后 Agent 终止摘要和短暂 `pending_agent_text`。历史尾部决定下一动作，不保存 `pending_agent_prompt` 或决策轮次；
- 旧 `action: blocked` 读取时映射为 `blocked`；其余旧 `action` 映射为 `continue`。若非 blocked 旧记录的 `answer` 为空，则使用固定安全兼容 continue 提示，绝不把旧控制 JSON 发送给 Agent；旧完成 sentinel 只读后再核验，旧消息不转换回写；
- 编排历史位于 Git 忽略的 run 目录，保存实际交互原文；Agent 仍须遵守项目规则，不主动在回复中展示无关秘密或完整环境变量。首轮不建设数据库、向量记忆或摘要系统。

## 六、程序化决策循环

### 1. 基本流程

```text
显式调用目标 Skill
→ 保存完整 Agent 回复并写为 user 消息
→ 请求统一 AgentDecision
→ completed 后运行步骤完成核验
→ 通过则 success；可安全补完则追加固定修复提示并恢复同一 session
→ continue 在循环内恢复；blocked 或 failed 立即停止
```

外层步骤或节点在循环中保持不变。

### 2. 自动决策权限与阻塞边界

AI-compatible 模型可以决定所有能够基于当前输入、项目事实、可用工具和已提供资源完成的事项，包括：

- 产品范围、业务规则、文档内容和组织方式；
- 技术方案、架构、安全、权限、兼容性和不可逆设计取舍；
- Agent 提出的澄清、确认、继续和定稿请求；
- 多个合理方案或相互冲突资料之间的选择；
- 非阻断建议是否纳入当前范围；
- 阶段二候选分流、需求化、合并、拆分和排序。

阶段一需求选择不属于上述语义决策。第 12 步建立合法需求注册表后，Python 根据依赖完成事实和 `order` 确定性选择下一条需求；没有可选项但仍存在 pending 需求时按依赖或状态错误处理，不请求模型自由选择。

模型作出决定时记录选择及理由，不把“需要判断”当作 `blocked`。只有缺少模型和当前环境无法取得的不可替代外部资源时才返回 `blocked`，例如：

- 输入或资源清单之外的真实外部服务、账号、付费资源或凭据；
- 客户专属素材、私有数据或专用设备；
- 必须由外部人员完成的授权、审批或线下动作；
- 阶段二主要任务不可替代的真实环境、身份、数据或浏览器能力。

模型不得用 Mock、假凭据、虚构资源或降低验收标准来伪造资源已经具备。

### 3. 决策上下文与历史

发送给 AI-compatible 负责人的历史由完整 XML system snapshot 与既有对话组成。新 conversation 创建前，`common/decision.py` 将负责人角色、项目上下文、统一职责、步骤完成条件和 Pydantic 输出合同分别渲染为 `<role>`、`<project_context>`、`<responsibility>`、`<completion>`、`<output>` 并首次保存为 system。统一职责先检查 Agent 的决策交接是否自包含；不完整时通过 `continue` 要求同一 Agent session 重新读取并补齐。恢复严格使用历史 `messages[0]`，不重渲染、覆盖或迁移；因此新职责只作用于新建 decision conversation，既有 conversation 不补造为新合同证据。完整 Agent 原文用于连续裁决，不能重新包装为步骤元数据或伪 `user` 消息。

项目上下文范围固定为：第 2 步初稿原文和目标路径；第 5 步产品定义原文、适用工程、选型白名单投影以及资源清单的绝对路径/可读性；第 6 步 `project_bootstrap` 使用产品定义原文、已完成准备清单原文、配置迁移与既有资源边界、适用工程和组装白名单投影，`tailwind_theme` 使用产品定义原文、实际 frontend 和主题颜色边界；第 7 步产品定义原文、准备清单原文、适用工程和组装白名单投影；第 8 步有序权威仓库相对路径和干净基线说明；第 9 步两份产品定义原文、准备清单原文、总体技术方案原文、有序权威工程和固定输出路径；第 10 步适用时还包括固定工程架构文档与实际 `frontend`；第 11 步包括第 2/5/7 步文档、第 8 步权威工程、第 9 步工程架构和严格第 10 步交接，仅在第 10 步 true 时读取 UI/UX 框架。资源清单正文和 `.env` 因输入来源边界不读取或内联到项目上下文；第 6、7、9、10、11 步在消费准备清单前均严格核对当前清单和两份产品定义与 `readiness_baseline` 一致；第 8～11 步其它只读 Git 核验和 verifier 仍由步骤私有实现。

选型和组装投影不含 `git_url`、`origin`、`remote`。渲染器仅对项目上下文做标准 XML 转义。`request_decision` 显式接收 XML prompt，原样传给一次 `responses.parse`，并以 Pydantic `AgentDecision` 取得结构化输出；没有公共默认、隐藏追加 prompt 或格式重试。

PCM 在请求前读取该领域完整编排历史。首次保存动态 `system` 和已发送给 Claude Agent 的初始 `assistant` 指令；每次 Agent 完整真实回复先作为 `user` 追加，再调用 `request_decision` 并把负责人完整 `AgentDecision` JSON 作为 `assistant` 保存。`completed` 表示负责人根据 Agent 执行结果相信任务已完成，步骤程序仍执行现有完成核验；对话尾部是唯一调度真相：`user` 先裁决，决策交接不完整时 `continue` 要求原 session 补齐，交接完整后的 `continue` 恢复 answer，`completed` 先核验，`blocked` 终止；只有 state 已标记 blocked 的显式重跑才发送固定重新核验提示。公共循环不解析文件引用或 Agent 自然语言，也不向 Agent prompt 追加隐藏交接尾注。Agent initial prompt、conversation schema、公共循环状态机、repair/session、错误分类均保持不变，未引入 `task_contract`、动态产物快照或结构化决策工具。

不发送密钥、完整 `.env`、资源清单正文、无关仓库内容或可由程序直接判断的原始大段日志。Agent 侧自包含交接由产品工作区项目规则约束；模板根 `AGENTS.md` 的新规则只随未来新建工作区生效，本轮不复制到既有外部产品工作区，也不修改既有 Claude session。当前已有工作区的新 decision conversation 仍可由负责人侧 `continue` 兜底。

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
4. 重构前普通定稿决定可返回 `approve`；该旧 `action` 记录仅供兼容读取；
5. Probe C 的早期 `AgentDecision` verdict 与格式重试结果保留为旧合同历史。现行实现要求显式完整 XML system prompt，并将其原样传给一次 `responses.parse`，以 Pydantic `AgentDecision` 取得结构化输出；没有公共默认、隐藏追加 prompt、产物全文注入或格式重试。
6. fresh run `probe-c-decision-handoff-20260905` 使用当前配置 AI-compatible 模型完成两次一次调用裁决：只引用活动 TRD 路径和行号、未说明五项详细问题的交接严格返回 `continue`、非空 `answer` 和空 `required_inputs`；自包含说明真实支付商户账号与生产密钥不可替代、当前环境无法取得且 Mock 不可用的交接返回 `blocked` 和非空 `required_inputs`。该探针只证明本次新 system prompt 对这两个输入的真实结果，不证明所有表达形式重复稳定，也不改写旧 conversation。
7. 日志和状态中不出现 API Key。

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
- 模板默认分支、实际分支、commit SHA 和 remote URL 已记录，模板不包含 `.env` 且根 Git 规则实际忽略 `.env`；
- `PCM_AGENT_WORKSPACE_ENV_FILE` 的原始字节已经写入最终工作区根 `.env`，文件为非符号链接普通文件、权限 `0600`，最终根 Git 仍实际忽略；
- 最终目录不含上游模板 Git 历史，模板关键能力仍存在，`docs/` 只包含 `产品初稿.md`；
- 最终项目根已经初始化为 `main` 分支的独立 Git 仓库，且尚无 commit；
- 状态记录源初稿、项目身份、临时与最终路径、模板证据、发布阶段和根仓库事实；
- 项目内初稿与源初稿 SHA-256 一致，源初稿未变化；
- 重复执行、归属不明目录、残留临时 clone、clone/rename/Git 初始化中断不会覆盖现场或误报成功。

当前状态：原有工作区发布路径已真实验证；本次根 `.env` 工作区工具配置合同已完成代码和自动化验证，尚未重新执行 fresh 外部模板发布，不把旧 run 补造为新合同证据。

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

执行方式：直接调用 OpenAI Python SDK `responses.parse`，不调用 `foundation-selection` Skill 或 Claude Agent SDK。

实现合同：

- `PreviousStepResult`、`TemplateCatalog`、`FoundationSelectionInput` 和 `FoundationSelectionResult` 均为 Pydantic 模型；
- 从 `steps/02.json.outputs` 读取项目需求说明和产品功能说明，从本次 catalog 构造前后端候选列表；
- system prompt 是 `step.py` 中的普通 Python 字符串，只说明模板选型任务、候选限制和输出要求，不包含“第几步”、PCM、Skill、节点或编排历史，并要求严格 JSON、禁止 Markdown、代码围栏、YAML 或 JSON 之外的文本；
- 调用 `responses.parse(model=..., input=[system, user], text_format=FoundationSelectionResult)`；user 内容由 `FoundationSelectionInput.model_dump_json()` 生成；
- SDK 根据 `FoundationSelectionResult` 生成结构化输出格式，并把结果解析到 `response.output_parsed`；
- 程序直接保存 `output_parsed.model_dump()`，不维护手写 JSON Schema、不调用 `json.loads()` 解析模型输出，也不做第二套字段校验；
- `frontend` 和 `backend` 分别是完整的 `TemplateSelection` 或 `null`，每个选择包含 `id`、`git_url`、`default_branch`、`path` 和 `reason`；
- 成功结果写入 `steps/03.json.template_selection`，状态推进到 `project:04_assemble_foundation`；已有成功结果可直接复用；
- 失败时保存异常类型、经精确凭据遮盖的具体原因和 `diagnostic_path`；provider code/type/message/request ID/HTTP status 与异常链写入 Git 忽略诊断快照，不记录 API Key、请求/响应 body 或完整环境；
- 本步骤不获取、复制或组装模板，不初始化前后端仓库。

当前状态：32 项第 0～3 步单元测试与 Python 编译检查通过；真实 Pydantic 基础工程选型 run `step03-pydantic-mendmark` 成功，真实 Pydantic 决策探针 `probe-c-pydantic-20260821-c` 通过。

### 第 4 步：组装基础工程

执行方式：只使用确定性 Python、Git 和文件操作，不调用 AI-compatible 模型、Claude Agent SDK 或 Skill。

实现合同：

- 只读取 `steps/03.json`，要求第 3 步成功，并以既有 `FoundationSelectionResult` / `TemplateSelection` 校验 `template_selection`；不重新读取 catalog、产品定义或选择理由；
- 状态必须位于 `project:04_assemble_foundation`，产品工作区和 state 根目录一致，根仓库仍是零提交、空 index 的 `main`；
- `frontend/`、`backend/` 只允许不存在，或是非符号链接且唯一内容为普通 `.gitkeep` 的严格占位目录；任何其它现场都保留并返回 `failed`；
- 临时根固定为产品目录同级 `<project>.pcm-assemble-<run-id>`，使用 run ID、产品路径和步骤号 marker 证明归属；只有 marker、路径和占位现场完全一致时才清理失败残留并 fresh 重试；
- 对唯一 `(git_url, default_branch)` 执行一次 `git clone --depth 1 --branch <branch> --single-branch`，核验实际 origin、branch 和 HEAD SHA；
- 选中模板路径必须是 clone 内的非符号链接真实目录，子树中禁止上游 `.git` 和任何符号链接；每个适用 payload 使用 `shutil.copytree()` 准备后，在 run-owned 临时根内执行 `git init -b main`，核验 Git top-level 是 payload 自身、分支 `main`、HEAD unborn、index 为空，且至少存在一个不被自身 ignore 的可提交文件；全部 payload 通过后才移除严格占位并以 `os.rename()` 发布；
- `null` 端只删除严格占位目录；成功后每个适用端必须是自身 top-level、`main`、unborn HEAD、空 index 的独立仓，不适用端必须不存在，并在清理临时根后写入成功结果；第 4 步不 `git add`、`git commit` 或 push；
- `steps/04.json` 记录 `applicable`、`outputs` 和每个适用端的 `target`、选择字段、实际 `origin`、`branch`、`commit_sha`，状态推进到 `project:05_verify_readiness`、第 5 步；
- 明确的认证或读取权限缺失返回 `blocked`；仓库或分支不存在、状态冲突、路径、普通 Git、复制、发布、清理和核验错误返回 `failed`；普通 Git 原始错误不写入结果；
- 已有 `status=success` 结果时核验选型、来源字段、目标自身 Git 边界和临时目录后幂等复用，不重新 clone；`failed` / `blocked` 结果不作成功锚点，发布期间形成的部分现场不自动覆盖。

当前状态：较早阶段的第 4 步专属 12 项、当时第 0～4 步 44 项测试及 Python 语法检查、`compileall`、`git diff --check` 均通过；当前全量计数以本轮实际 222 项为准。修迹 run 使用 GitLab SSH 成功组装前端 `vite-react-shadcn-spa`（`main` SHA `a31db6deb85ab29f2d2253413dd362293a96325f`）和后端 `fastapi-sqlalchemy-postgresql-async-api`（`main` SHA `49ff842fcd330387f2fbdd1e9a43884e05894697`），均与远端 `main` 一致；最终目录的适用端各为自身 top-level、`main`、unborn HEAD、空 index，临时目录清理，根仓仍是零提交 `main`，黄金初稿的既有 SHA 事实未变化。首次错误 HTTPS 来源运行返回 `failed` 且未修改目标；修正为 SSH 后同 run 依据 marker 安全恢复成功，再次运行幂等复用。

### 第 5 步：核验项目准备状态

执行方式：在产品项目根通过 Claude Agent SDK 显式调用 `project-readiness`；Python 只负责交接、session、决策循环、产物与状态，不解析开发资源或准备清单条目。

实现合同：

- 状态必须位于 `project:05_verify_readiness`；重新核验根 Git 及每个适用子仓自身 top-level、`main`、unborn HEAD、空 index，并读取成功的 `steps/02.json`、`steps/03.json` 和 `steps/04.json`。第 2 步的两个输出必须是工作区内非空普通文件；第 3 步使用 `FoundationSelectionResult` 校验；第 4 步复用既有来源、目标、Git 边界和临时目录核验；
- `PCM_DEV_RESOURCE_LIST` 必须是可读、非符号链接普通文件的绝对路径。Python 不解析资源内容，只把路径作为可信开发资源引用交给 Agent；完整 Agent/决策交互保存在被 Git 忽略的 run 历史中；
- 初始提示第一行显式调用 `/project-readiness`，正文引用第 2 步实际产品定义、适用组装工程、**最小选型投影**和资源清单路径；两份产品定义是当前最终产品范围的权威来源，选型不传 `git_url` 或 `origin`，也不包含步骤号、PCM 节点或编排背景；
- 调用方已授权为当前自动化开发周期建立唯一资源准备基线并创建 `docs/requirements/项目准备清单.md`。Agent 可以原样读取任意格式的可信开发资源资料，从产品范围推导编码、开发环境联调和开发环境真实验收所需、且必须由调用方提供的外部服务、账号、凭据、授权素材、私有数据或专用设备；匹配候选前先验证受保护实际配置中的非空运行凭据与资源绑定，满足开发合同时原样保留，不用候选池中的维护、共享或更宽权限身份替换，也不把候选凭据探针结果误记为最终项目凭据结果；清单只描述最终选定绑定，不得提及、比较或说明未采用候选，否定表述也不例外；只有绑定缺失、失效或不合格时才使用动态候选池。在授权和配置合同允许时优先创建项目专用开发/测试资源与最小权限运行凭据。服务不支持派生项目身份时，只有调用方明确授权的非管理、非生产共享开发身份，且数据、操作、收件人或其它实际作用范围满足开发合同，才可以兼容使用；共享管理或根凭据、生产身份和可访问合同外资源的身份不得写入应用配置，无法派生合格开发身份时属于第二类阻塞。权限与隔离按最终凭据的实际可见范围和范围外拒绝判断，列表接口只返回获授权项目资源时不因接口成功本身误判越权。每项判为 `ready` 的外部运行资源都必须把最终项目凭据与资源绑定持久化到所属仓库被 Git 忽略的实际 `.env` 或等价受保护配置，后续开发无需重新读取共享资源资料；同步无秘密 `.env.example` 或公开说明，POSIX 上含秘密文件通常为 `0600`，并使用最终项目运行凭据完成最小行为和隔离验证。不得泄露秘密、创建生产或未授权付费资源、改变既有 Git 边界，或执行 Git 暂存、提交、分支、合并、push；
- 只允许两类 `blocked`：开发必需外部资源在候选池中不存在、当前环境无法安全生成且无兼容替代；或已匹配资源真实不可用、凭据无效、权限不足、隔离不合格，或缺少开发所需接口能力、可用配额、回调/白名单、沙箱范围及其它既定能力。项目准备清单只纳入当前编码、开发环境联调或开发环境真实验收所需，且必须由调用方提供或授权的外部资源。依赖安装、构建、测试、migration、Seed、业务实现、项目内测试账号、完整联调和浏览器验收属于后续开发工作；只服务生产部署或生产运行的正式域名、DNS/TLS、生产资源与凭据、生产回调与配额、监控、备份恢复、容量和发布安全属于清单准入范围外。清单正文任何位置都不得列举、命名或汇总这些事项，也不得以“未纳入清单”、范围外、未来事项、非阻塞、无状态或 `not-applicable` 章节保留它们；开发 SMTP TLS、localhost 回调、开发白名单、沙箱范围和开发配额仍按当前开发用途纳入。产品规则和隐私事项同样不写入清单；
- 每轮从 init 核验实际 cwd、`project-readiness` Skill 和 slash command；完整真实回复先保存为 `user`，再由公共渲染器以步骤 `DECISION_RULES` 和项目上下文生成的完整 XML system snapshot 的统一 `AgentDecision` 裁决。`completed` 必须确认清单正文只包含当前开发必需外部资源，这些资源均真实可用，所有 `ready` 外部资源的最终凭据绑定已持久化到项目受保护配置并同步公开键合同，含秘密文件权限安全，且不存在两类开发资源阻塞；清单不能为自身状态作证。正文任何位置仍提及纯生产、非当前必需候选或后续内部工作时必须 `continue` 删除，不能 `completed`，即使这些内容位于“未纳入清单”、范围外说明或无状态汇总中。`completed` 后程序重新核验清单、交接和根/适用子仓 Git 边界；清单缺失或为空时追加固定修复提示，只重建开发资源清单并继续凭据持久化、公开示例、文件权限和最终运行凭据验证；
- `blocked` 终止前也重验上述 Git 边界；只有 `status=success` 的结果可幂等复用，`failed` / `blocked` 结果不阻断原 session 恢复；
- Agent 单次 turn 与同一历史负责人决策轮数沿用步骤代码的有限配置，不设置 `max_budget_usd`。`error_max_turns` 和历史兼容的 `error_max_budget_usd` 必须有 session 和非空回复才可裁决，且后续正常 `success` 前不能最终完成；对话尾部为 Agent `user` 时先裁决，为 `continue` 时恢复原 `answer`，为 `blocked` 时终止，为 `completed` 时先核验；达到上限不得额外调用；
- `blocked` 只来自决策模型确认的不可替代外部资源缺失；其它输入、路径、状态、SDK、Skill、session、文件或决策错误为 `failed`；
- 成功先写 `steps/05.json`，其中 `outputs` 仍只含固定准备清单路径，`readiness_baseline.scope_contract` 固定当前“只允许开发必需外部资源进入清单”的准入合同版本，另外记录当前清单与两份权威产品定义的 SHA-256。合同版本使旧语义 success 不可复用，指纹防止已经完成的基线被静默替换；二者都不证明资源 `ready`，也不记录或哈希 `.env`、凭据和资源资料正文。随后推进到 `project:06_bootstrap_foundation`。若结果已成功而下一节点状态写入中断，重跑以严格成功 schema、当前合同版本、指纹、交接和 Git 边界恢复；缺少合同版本或指纹的旧 success、清单漂移或产品定义漂移均不可复用或自动升级；

输出：

- `docs/requirements/项目准备清单.md`；
- `state.json` 中的 `claude_sessions.project_readiness`；
- `runs/<run-id>/conversations/project_readiness.json`；
- `steps/05.json`。

**当前清单准入合同的真实验证。** run `step05-readiness-v2-20260828-b` 在独立产品工作区复用第 0～4 步现场与既有开发资源完成 fresh 真实调用；此前外部资源已判 `ready` 但凭据未持久化、生产/发布事项误阻塞、内部配置形成第三类 blocked、必要能力遗漏、旧 baseline 无范围合同版本、非必需候选进入清单、范围外事项以“未纳入清单”章节残留、候选池维护身份被误当作最终项目凭据探针，以及未采用候选以否定比较残留在资源匹配字段的现场均已归档。最终 fresh Agent 先验证并原样保留受保护实际配置中的合格项目绑定，只将 PostgreSQL、S3 兼容对象存储和 SMTP 三项当前开发必需外部资源写成 `ready` 章节；生产、后续内部工作、产品规则和其它非必需候选在清单正文任何位置均未出现，禁止词项检查命中数为 0。最终凭据保存在被 Git 忽略且 `0600` 的受保护配置，公开 `.env.example` 无真实秘密，秘密反查命中数为 0；真实探针确认 PostgreSQL 开发/测试库 DDL/DML 成功且额外可连接库为 0，S3 最终项目身份只看见两个授权桶并完成双桶对象读写删除，SMTP 使用明确授权的非管理、非生产共享开发身份完成 TLS、认证和唯一授权测试收件人单封投递。最终 conversation 为 `system → assistant → user → assistant completed`，`steps/05.json` 为严格 success，`readiness_baseline.scope_contract` 为 `development-external-resources-v3`，清单 SHA-256 为 `29a288d45a7c060d51aafdf900d109629acfb40d5baf386e394b39c7c5a8420f`，state 推进 `project:06_bootstrap_foundation`；成功后幂等重跑 1 秒，`05.json`、state 和 conversation 字节均不变。

**重构前真实运行事实。** 第 5 步旧协议的自动化记录为 17 项专属、61 项第 0～5 步全量测试；`compileall` 与 `git diff --check` 通过。修迹真实资源准备已完成 PostgreSQL 项目角色、开发库和测试库、JSONB 读写、MinIO 开发桶和测试桶，以及被 Git 忽略的 `backend/.env` 与 `frontend/.env.local`。修正历史持久化后使用新 `project_readiness` session 重新真实核验，Agent 一轮正常 `success`；生成历史严格为 `system → assistant 初始指令 → user Agent 完整真实回复 → assistant 固定完成声明`，`decision_turn: 0`、完成声明唯一、无占位内容。未完成分支测试验证每轮 Agent 完整回复、`request_decision` 返回的完整结构化 JSON、原样 `answer` 转发及预算/turn 上限同 session 恢复。状态推进到第 6 步，重复执行幂等复用。

**当时自动化事实。** 公共循环 24 项、第 5 步 10 项以及当时全量 194 项测试已经通过；公共循环已在第 7、9、10、11 步取得真实集成证据。上述第 5 步历史仍是旧协议事实，本文不把它改写为第 5 步独立新 session 运行。

### 第 6 步：项目化基础工程与主题配色

执行方式：在产品项目根顺序运行两个独立的公共 Agent 决策循环。`project_bootstrap` session/conversation 先显式调用 `project-bootstrap` 完成项目化修改与真实工程验证；有 frontend 时，通过步骤私有 Tailwind v4 CSS-first gate 后再由独立的 `tailwind_theme` session/conversation 显式调用 `tailwind-theme`。AI-compatible 模型分别以各自 `AgentDecision` 判断下一动作，Python 负责前序交接、两个循环的顺序、目录/Git 边界、Tailwind gate、结果与状态；公共循环、步骤编号和节点不改变。

实现合同：

- 状态必须位于 `project:06_bootstrap_foundation`；重新核验根 Git 和每个适用子仓自身 top-level、`main`、unborn HEAD、空 index、第 2 步两份产品定义、第 3/4 步选型与实际组装一致性，以及第 5 步严格成功结果；当前准备清单和两份产品定义必须与 `readiness_baseline` 指纹一致。适用工程目录只从 `steps/04.json.outputs` 读取，内部 README、manifest、锁文件、配置、代码和测试由各领域 Agent 按现场发现。状态不增加 `6.1` 或活动 capability；两个 spec 分别使用 `project_bootstrap`、`tailwind_theme` key/state_key 保存独立 session、conversation 和私有恢复状态。
- bootstrap 初始 prompt 显式调用 `/project-bootstrap`，引用两份产品定义、已完成准备基线、配置迁移与既有资源边界、实际适用工程和白名单化组装来源。只传递 `target`、模板 ID、分支、相对路径和 commit SHA，不传递可能带凭据的 `git_url` 或 `origin`；正文只描述项目化领域任务，不包含步骤编号、PCM 节点、session 或其它编排背景，并明确只保持可替换主题基础设施、不形成项目专属配色。theme 初始 prompt 独立以 `/tailwind-theme` 开始，只引用两份产品定义和 `@./frontend`，同样不包含外层编排信息或组装远程来源；
- `project-bootstrap` Agent 已获授权直接完成有限项目化：落实产品根 README、各适用工程项目身份、基础配置、模板首页和测试迁移、按引用处理误导残留，并执行适用安装、静态/类型检查、测试、构建、启动、健康检查、真实浏览器和基础联调；保持或建立可替换的 Tailwind 语义颜色结构，但不选择或生成项目专属主题。可以按工程实际加载合同维护被 Git 忽略的实际 `.env` 或等价配置，允许环境变量改名和配置结构迁移并同步无秘密公开示例；迁移必须复用同一既有资源绑定和真实值，保留资源身份、endpoint 与权限范围，不重新选择、创建、派生、轮换或替换外部资源或凭据。完成前必须删除所属仓未忽略的 `.coverage` 或将其加入所属仓 `.gitignore`；不得实现业务功能、总体技术方案或工程架构，不得改变独立 Git 边界或执行 Git 写操作；
- bootstrap completed 后，若 outputs 含 frontend，Python 必须在创建或恢复主题 conversation 前确认 `frontend/package.json` 直接声明唯一且可明确判断为 major 4 的 `tailwindcss`，并从 frontend 自身 Git 可见且未忽略的 CSS 中找到 `@import "tailwindcss"` CSS-first 证据。版本不明确、非 v4 或缺少 CSS-first 证据抛普通本地错误并由 CLI 写为 `failed`，不创建主题 session，不属于 `blocked`；Python 不实现完整 semver、CSS import graph、token parser 或 fingerprint；
- `tailwind-theme` Agent 根据产品定义和当前 frontend 选择经校验的 tweakcn preset 或生成 custom；tweakcn 网络不可用时必须 custom fallback。完整 light/dark 语义颜色必须同时落实；只允许修改颜色值和必要颜色映射，不改变字体、圆角、阴影、间距、tracking、布局、组件、页面、主题切换交互或业务功能，不安装、升级或迁移 Tailwind，不执行 Git 写操作。完成前运行适用前端检查、测试和构建，并在真实浏览器中切换 light/dark、读取代表性渲染和 computed color，检查控制台和失败网络请求；
- 两个领域的每轮完整真实 Agent 回复分别保存到 `conversations/project_bootstrap.json` 与 `conversations/tailwind_theme.json`，并交给各自由公共渲染器生成的 XML system snapshot 与 `AgentDecision` 裁决。bootstrap 工程配置读取、迁移、接线、安装、验证问题属于其 `continue`；theme 方向、light/dark、允许范围修改、构建或真实渲染证据不完整属于 theme `continue`。`blocked` 只允许当前环境无法取得的不可替代外部条件；本地版本、主题入口、dark selector、文件、工作树或状态冲突不得 blocked。两个 `completed` 都必须在自己的 completion verifier 后成立，主题未完成时不得写第 6 步 success；
- 两个 spec 的 AI-compatible 结构化输出都要求 `request_decision` 显式接收各自完整 XML system prompt，原样调用一次 `responses.parse` 并以 Pydantic `AgentDecision` 解析；没有公共默认、隐藏追加 prompt 或格式重试。步骤分别维护 bootstrap 与 theme `DECISION_RULES`，公共循环代码和 schema 不变。持续结构或完成状态失败为 `failed`，新协议不写 Python 固定完成声明；
- bootstrap 与 theme 的单次 Agent turn、各自 conversation 的负责人决策轮数沿用步骤代码的有限配置，且不设置 `max_budget_usd`。各自对话尾部为 `user` 时先裁决，为 `continue` 时恢复本领域原 `answer`，为 `blocked` 时终止，为 `completed` 时先核验。bootstrap completed/theme 未开始或 theme 中断时，重跑先零 Agent 复验 bootstrap，再新建或恢复 theme；theme blocked/failed 不重新执行 bootstrap Agent。turn 上限有 session 和非空回复时可裁决，但必须恢复正常 `success` 才能最终完成；API 400/429/500、连接、CLI/进程、无 Result 或其它 SDK 错误均先形成 `failed`。公共循环自身不做 HTTP 重试；属于 Claude Agent SDK 通道故障的失败仍由外层 `run_step.py` 有界重放，取消和本地合同错误不重放；
- Python 在两个 Agent 前后复用根仓和适用子仓的自身 top-level、`main`、unborn HEAD、空 index 核验，并确认适用目录仍与第 4 步一致且 `.coverage` 已删除或实际被所属仓忽略。bootstrap completion 另核验根 README；theme completion 重验 Tailwind v4 CSS-first gate。Python 不解析实际 `.env`、资源身份、准备清单语义、主题 token 或浏览器语义，不保存秘密映射，不重复执行 Agent 已完成的工程命令；
- 成功先写 `steps/06.json`，再推进到 `project:07_solution_design`。顶层 `applicable` 和 `outputs` 保持原语义，新增真实布尔 `tailwind_theme`，严格满足 `tailwind_theme == ("frontend" in outputs)`；blocked/failed 默认 false，字段缺失、类型错误或不一致的旧 success 不可复用。没有任何适用工程时两个 Agent 都不调用并以 `applicable:false`、空 outputs、false marker 跳过；backend-only 运行 bootstrap、跳过 theme。有 frontend 时只有两个领域都完成才 success。result 已写而状态推进中断时按严格 marker、前序交接、Tailwind gate 和 Git 事实补状态；完整 success 幂等不调用两个 Agent。`failed` / `blocked` 结果不作成功锚点，也不阻止各自原 session 恢复。

输出：

- 已完成项目化和条件性主题配色的 `steps/04.json.outputs` 实际工程目录；
- `state.json` 中的 `claude_sessions.project_bootstrap`，以及 frontend 适用时的 `claude_sessions.tailwind_theme`；
- `runs/<run-id>/conversations/project_bootstrap.json`，以及 frontend 适用时的 `runs/<run-id>/conversations/tailwind_theme.json`；
- 带严格 `tailwind_theme` marker 的 `steps/06.json`。

**重构前真实运行事实。** 第 6 步旧协议的自动化记录为 14 项专属、75 项第 0～6 步全量测试；`compileall`、`git diff --check` 与独立只读复审通过。修迹真实运行使用 session `007e3db5-f777-4aa1-9e49-e8c8cf6bef5d`：首轮 Agent 输出计划；首次裁决因服务返回 YAML 风格文本解析失败，增加限定重试后恢复同一历史并得到 `continue`；执行时一次 SDK 连接中断，决策模型再次要求原 session 继续；第三轮 Agent 完成前后端项目化。完成后补查发现产品根 README 仍为通用能力说明，同一历史追加纠正性 `continue`，原 session 将根 README 收口为 MendMark 项目总说明并验证 5 个本地链接，最终第 5 次裁决为 `completed`。前端安装、lint、type-check、10 项测试、build、1 项 Playwright E2E，后端锁定、安装、Ruff、15 项含 PostgreSQL 集成测试和 build，以及 Uvicorn/Vite、健康与就绪探针、OpenAPI、浏览器真实健康联调、控制台/网络、375px 窄视口均通过。临时服务已停止，`.env` 仍被忽略且权限为 `600`，根仓仍是零提交 `main`、无 staged；该历史现场的前后端尚未建立独立 Git 边界，现行第 4 步已替代该事实。源 PRD 与项目初稿的既有 SHA-256 均为 `d7d9b8054b226ef2abf730cfb29e59b30d5e39d68eb9121ded22a16750414fee`。状态推进到第 7 步，约 1 秒幂等复用不调用 Agent。

**本次重构当时自动化事实。** 第 6 步 9 项与当时全量 194 项测试已经通过；公共循环已在第 7、9、10、11 步取得真实集成证据。第 6 步的真实项目化记录仍属于旧协议，本文不把它改写为第 6 步独立新 session 运行。

**当前双 Skill 合同自动化。** 第 6 步现行 14 项、第 7 步现行 9 项均通过；第 6/7/8/10 步相关回归 58 项、公共循环与 `run_step`/`run_all` 入口回归 64 项通过。全量 351 项 `unittest` 通过（61.878 秒），`compileall common steps run_step.py run_all.py test_run_step_retry.py test_run_all.py` 通过。覆盖 bootstrap/theme 两个独立 spec/session/conversation、各自 repair/blocked 恢复、backend-only 与无工程跳过、Tailwind v4/CSS-first failed gate、严格 `tailwind_theme` marker、旧 success 拒绝、第 7 步消费及第 8/10 步无业务回归。隔离 run `step06-tailwind-theme-20260831` 已确认 bootstrap Skill/slash command、产品 cwd 和原 session 加载；内置 Explore 未识别模型后，run-local 同 session 恢复实际执行 43 turns 并修改工程，但 SDK 以 `result_subtype=success`、`is_error=true`、`terminal_reason=api_error` 结束，没有产生完整 Agent 回复；后续恢复严格拒绝不合法 `pending_agent_text`，因此未进入独立 `tailwind_theme` session。该现场保留为真实通道与恢复失败证据，不能由自动化、工作树改动或旧项目化历史替代 `/tailwind-theme` 和浏览器 light/dark 集成成功。

### 第 7 步：总体技术方案

执行方式：在产品项目根通过 Claude Agent SDK 显式调用 `solution-design`；Agent 按需读取当前工程事实并生成总体技术方案，AI-compatible 模型以统一 `AgentDecision` 判断下一动作，Python 只负责前序交接、公共循环、固定文档和最小 Git 边界核验。

实现合同：

- 状态必须位于 `project:07_solution_design`；重新核验根 Git、每个适用子仓自身 top-level、`main`、unborn HEAD、空 index、第 2 步两份产品定义、第 4 步实际适用工程与白名单组装来源、第 5 步准备清单和第 6 步严格成功结果。第 6 步 `outputs` 必须与第 4 步一致，`tailwind_theme` 必须是真实布尔并严格等于 outputs 是否含 frontend；缺失或不一致的旧 success 不可复用。工程内部 README、manifest、锁文件、配置、代码和测试由 Agent 按支撑方案主张的需要读取，不要求全仓扫描；
- 初始提示第一行显式调用 `/solution-design`，引用产品定义、准备清单、实际适用工程和白名单化组装来源，只授权创建或更新 `docs/design/技术方案.md`；正文不包含步骤编号、PCM 节点或其它外层编排背景，不传递 `git_url` 或 `origin`；
- Agent 必须区分当前事实、已确认决定、目标状态、假设和待确认事项，明确系统边界、主要技术选择、交付单元、跨单元协作、风险和恢复语义；不重新选型、组装模板、实现业务、修改代码或执行 Git 写操作；
- 新 run 的每轮 Agent 完整回复、`pending_agent_text` 和决策输入均保留完整原文于 Git 忽略 run 目录，不再在保存或转发前脱敏替换；回复由公共渲染器以步骤 `DECISION_RULES` 和项目上下文生成的完整 XML system snapshot 的统一 `AgentDecision` 裁决。风险、假设和正常未来待决事项不构成阻塞，且 Agent 必须不主动披露秘密；
- `completed` 后必须重新核验正常 Agent `success`、有效 session ID、固定技术方案文档为非空普通文件、前序交接和根/适用子仓 Git 边界；文档缺失或为空时追加固定修复提示并继续同一 session，交接或 Git 冲突为 `failed`。`blocked` 终止前同样重验 Git 边界；只有 `status=success` 的结果可幂等复用，`failed` / `blocked` 结果不作成功锚点。Python 不解析 Markdown 章节或判断技术结论；
- 结构化输出要求 `request_decision` 接收完整 XML system prompt 并原样调用一次 `responses.parse`，以 Pydantic `AgentDecision` 解析；没有公共默认、隐藏追加 prompt 或格式重试。步骤仅维护领域 `DECISION_RULES`。Agent turn 与同一历史负责人决策轮数沿用步骤代码的有限配置，不设置 `max_budget_usd`。turn 上限有 session 与非空回复时可裁决，但必须恢复正常 `success` 才能完成；400/429/500、连接、CLI/进程、无 Result、`aborted_streaming`/`aborted_tools` 或 `success` 下未知终止原因均在裁决前形成 `failed`。公共循环自身不做 HTTP 重试；只有 Claude Agent SDK 执行通道故障携带瞬时请求并由外层 `run_step.py` 有界重放，aborted 和其它本地合同错误不重放；
- 成功先写 `steps/07.json`，再推进到 `project:08_initialize_repositories`。没有适用基础工程时仍需生成总体技术方案，不无副作用跳过；成功写入或状态推进中断时，按完整文档、session、历史和 Git 事实恢复或幂等复用。

输出：

- `docs/design/技术方案.md`；
- `state.json` 中的 `claude_sessions.solution_design`；
- `runs/<run-id>/conversations/solution_design.json`；
- `steps/07.json`。

**重构前真实运行事实。** 第 7 步旧协议的自动化记录为 11 项专属及当时第 0～7 步全量测试；其后当前全量已更新为本轮实际 222 项。`compileall`、`git diff --check` 和独立只读复审通过。修迹真实运行使用 session `dd29866c-22d7-4a9f-b51b-3f6e1cf10938`；Agent 读取两份产品定义、项目准备清单、前后端工程和脱敏组装 commit 事实，生成 `docs/design/技术方案.md`，专属裁决为 `completed`，状态推进到 `project:08_initialize_repositories`。真实 run 重跑确认成功幂等复用，不再次调用 Agent 或决策模型；根仓仍为零提交 `main`，未执行 Git 写操作。

**重构后第 7 步隔离真实验证。** run `agent-loop-step7-20260822T190149Z` 在外部复制工作区执行，未修改 `step01-mendmark`；session `e8000375-2698-4ccf-9927-ccb9ca627ca2` 的 init 确认 cwd、`solution-design` Skill、slash command 与 Fable 模型。首次 Agent 在尝试内置 Explore 子代理时遇到环境内部未识别模型并超时，无 ResultMessage；循环保留 session 与初始 conversation、未推进成功。仅在隔离验证历史中追加普通 assistant 的“不使用子代理、直接工具完成”提示后，从同一 session 恢复；该提示不在生产 prompt 中，环境问题不归因于公共循环。

恢复后 Agent 正常 `success`（44 turns、约 `$3.800742`）并生成约 44 KB 技术方案。同一真实回复的第一次决策返回 YAML 风格结构；旧合同的格式重试后返回 `completed`。测试包装器仅在隔离副本的首次 completed 后置空方案，verifier 返回固定 `DESIGN_REPAIR_PROMPT`；循环保留首次 completed JSON、追加普通 assistant repair 提示、恢复同一 session，Agent 补回文档后第二次真实决策为 `completed`。最终 `steps/07.json` 为 `success`、状态 `current_node=project:08_initialize_repositories`、conversation 尾部为 `completed`，无旧 completion sentinel 或 `pending_agent_prompt`。文档置空 failpoint 不在生产代码中。

### 第 8～12 步：项目初始化、项目级设计与注册表初始化

| 步骤 | 能力或执行方式 | 输入重点 | 输出与完成边界 |
| --- | --- | --- | --- |
| 7 总体技术方案 | `solution-design` | 产品定义、已组装并项目化的工程事实、开发约束、选型 | 总体技术方案与当前工程一致，不重新选型或组装 |
| 8 首次提交适用仓库 | 首次全仓提交检查与干净基线节点；全干净时零调用，dirty 时一个产品根 Claude Agent SDK session 显式调用 `commit-changes`，Python 不执行 Git 写操作 | 仅 `['root', *steps/04.json.outputs]` 为权威仓库；每仓自身 top-level、`main`、工作树干净，保存 `applicable_repositories` 与仓库事实 |
| 9 工程架构设计 | 必要步骤；单份根仓 `docs/design/工程架构设计.md` 按每个包含业务代码且相关的适用交付单元闭合 Current/Target、职责/边界、依赖和代表性文件归属；`engineering-architecture` repair 后仅在固定文档是唯一根仓未提交变化时调用 `commit-changes` | 第 2 步两份产品定义、第 5 步准备清单、第 7 步总体技术方案和第 8 步严格交接 | 固定文档非空、非符号链接、tracked；全仓当前自身 top-level / `main` / clean；推进第 10 步 |
| 10 产品级 UI/UX 框架（按需） | Demo v1 仅以第 8 步严格交接是否含 `frontend` 判断；适用时 `ui-ux-framework` 形成跨需求框架和闭合的 App Shell Contract，不适用时按执行产物存在性拒绝并零副作用 | 第 2/5/7/8/9 步交接与实际 frontend | 固定框架文档非空、非符号链接、tracked；负责人确认区域、导航、页面模式、滚动/sticky、响应式及 Current/已确认 Target/默认 Target/偏差已收敛；全仓 clean并推进第 11 步 |
| 11 拆分 Backlog | `requirement-breakdown` 将已确认/默认 Target 转成相关 BR 约束或条件性迁移 BR；repair 后仅在固定 Backlog 是唯一根仓未提交变化时调用 `commit-changes` | 第 2/5/7 步文档、第 8 步严格交接、第 9 步工程架构和严格第 10 步交接 | 默认 Target 不制造迁移 BR或严格依赖；已确认迁移仅在独立用户结果和严格前置同时成立时单列；Backlog tracked、全仓 clean并进入 step 12 |
| 12 解析 Backlog 并初始化需求注册表 | Responses/Pydantic 从自由格式 Backlog 唯一提取静态字段；Python 只校验生命周期所需的 ID、数组顺序和依赖图；不调用 Claude Agent、`AgentDecision` 或 Skill | 第 11 步完整 success、工作区内固定非空非符号链接 Backlog 和初始化状态 | result 保存 `{path, sha256}` 来源与静态 catalog，state 初始化全 pending 注册表，推进 `phase_1:select_requirement` / step 13；零产品或 Git 操作 |

#### 第 8 步已实现合同

权威仓库严格是产品根与成功 `steps/04.json.outputs`，而非固定假设的前后端目录。每个权威路径必须是自身 top-level、`main` 的非符号链接 Git 仓库。Python 生产逻辑只执行 `git rev-parse --show-toplevel`、`git branch --show-current`、`git status --porcelain` 三个只读命令，不检查 HEAD、提交数、SHA、历史形态、marker、根 tree、`.gitignore` 或 `.coverage`。

创建 conversation/session 或写入 `running` 前，Python 先读取所有权威仓库；若均 clean，零 Agent、零决策模型调用直接成功，summary 明确已形成全仓干净基线。任一仓 dirty 时才使用公共循环的单一产品根 session（领域键 `initialize_repositories`），首条 prompt 第一行 `/commit-changes`。提示只给有序仓库清单和边界；Agent 负责必要 Git 写操作，Python 不逐仓派发、不 `add`、不 `commit`、不 `reset`、`amend` 或 `rebase`。

`completed` 后 Python 只读复验，每仓 clean 才成功，仍 dirty 则向同一 session 发送固定 repair prompt。`blocked` 后也重读：已 clean 直接成功，仍 dirty 才保存 blocked。恢复同样先读现场；clean 直接成功，dirty 才恢复原 session；已有 Agent 执行事实但 session、conversation 引用或历史文件缺失时返回 `failed`，不得静默新建会话。成功 `steps/08.json` 除统一字段外保存 `applicable_repositories`、`repositories`（相对 `path`、`branch`、`worktree_clean`）及 `outputs=[]`；state 保存同一事实但路径为绝对路径，推进至 `project:09_engineering_architecture`。`failed` / `blocked` 的 `08.json` 不当作成功或阻止 session 恢复；第 9 步状态下权威仓库再次 dirty 会拒绝复用，成功结果写入后状态推进中断时则在 clean 现场归一化并推进。

`step08-real-20260823-a/b` 继续作为**旧“唯一初始提交证明”合同**的运行历史。前者中模板 Plugin 快照遗留 `.coverage`，Agent 没有提交，决策模型反复索取“调用方授权”并耗尽 8 轮；该 run 无三仓提交。后者在第 6 步清除 `.coverage` 后，以 session `64aa707c-268c-48c8-bb3f-f67f62abe75e` 的 `system → assistant → user → assistant` 对话、一次 Agent 回复和一次 `completed` 裁决，产生 root `c1eb33dfa5bda91a0d7f9aeeb41d8fefe10a6fca`、frontend `5997213c34c09ea6ba4e740e35f9df77d2d45d82`、backend `5d8dd95d8c42370697d25e6ecaf400bab42785b3` 并到达第 9 步入口。这些 SHA、提交形态和重跑事实不再是当前合同的完成条件。

当前合同已在真实 run 目录 `pcm-demo/runs/step01-mendmark` 和产品工作区 `/Users/zhou/resource/fireworks/ANDRSZAN/pcm-products/mendmark` 完成验证。run 目录名与 state 内历史 `run_id` 不一致是既有已知事实。权威仓库为 `root/frontend/backend`，第 4 步 `outputs` 为 `frontend/backend`；首次执行前三仓均为自身 top-level、`main`、dirty 且 HEAD 不存在。

首次执行只创建 `initialize_repositories` session `f6d42df8-13e5-437b-ada3-eef1015ecc87`。Agent 尝试内置 Explore 时遇到环境未识别模型 `gpt-5.6-sol[1m]`，无 Result、无 Git 变化，进程挂起后停止；session、conversation 和 init 证据已保存。这是环境内部子代理问题，不是第 8 步业务或 Git 逻辑失败。仅在这个 Git 忽略 run 历史中追加普通恢复指令“不要使用子代理/Explore，直接工具完成”，生产 prompt 和代码未改变；重跑恢复同一 session。

恢复后 Agent 先创建 frontend `dbab574dbe4d83a02323a750afd04de007565ac5` 与 backend `9682be837759c20f1a9ebbdf8fa2cfc09c2768d4` 两个本地提交，未 push；随后对根仓运行时产物和 `.agents/plugins/superpowers/.git` 请求决策。AI-compatible 负责人返回 `continue`：删除 61 个 `.in_use/*`、`.orphaned_at`、`.coverage` 运行时产物、补 `.gitignore`、移除 superpowers 嵌套 `.git` 并按普通受控插件快照提交，不采用 submodule。root 随后创建 `02ba4c1`（产品与技术基线）、`ae72c31`（Agent 规范与 Skills）、`5eeeacd217bbd27e03483b1b6d32915c721aadd9`（插件快照）三个本地提交，未 push。

最终 conversation 共 7 条，角色顺序为 `system → assistant 初始 → assistant 恢复 → user → assistant continue → user → assistant completed`；Agent 正常 `success`，26 turns，约 `$1.859406`，session 不变。Python 只读 verifier 写入 `steps/08.json` success，`applicable_repositories` 为 `root/frontend/backend`，result 使用相对路径，state 使用绝对路径，并推进到 `project:09_engineering_architecture`。独立 Git 核验确认 root HEAD `5eeeacd217bbd27e03483b1b6d32915c721aadd9`、3 commits，frontend HEAD `dbab574dbe4d83a02323a750afd04de007565ac5`、1 commit，backend HEAD `9682be837759c20f1a9ebbdf8fa2cfc09c2768d4`、1 commit；三仓均在 `main` 且 clean。该事实证明当前合同允许每仓 0、1 或多个提交，不要求唯一无父提交。

同 run 重跑第 8 步直接 clean 幂等成功，conversation 仍为 7 条，未再次调用 Agent 或决策模型，SHA 不变。backend 提交阶段 Agent 摘要报告 Ruff、格式、build 通过，`pytest` 14 passed、1 skipped，跳过项需要显式 `DB_*`；这不是本次 Python verifier 条件，也不改变第 6 步历史项目化验证。首次成功包含 run-local 恢复指令，因此不能宣称环境内部子代理问题已经解决或无需恢复。

#### 第 9 步现行新合同与旧合同历史

第 9 步是必要步骤，固定输入为第 2 步两份产品定义、第 5 步准备清单、第 7 步总体技术方案，以及第 8 步 strict success 的空 `outputs`、result/state 一致的合法有序 `applicable_repositories`；不逐项回放旧 `repositories` path、branch、clean 字段。每次实际 Git top-level、`main` 和工作树状态均由当前步骤现场只读核验。

现行 initial prompt 与 `ENGINEERING_ARCHITECTURE_DECISION_RULES` 要求 Agent 在单份根仓固定文档中为每个包含业务代码且相关的适用交付单元给出有限 Current/Target 地图，并以 `[当前]`、`[目标]`、`[按需]`、`[迁移]` 标注。完成裁决必须按每个单元的有证据架构决策矩阵闭合目录/模块职责、语义所有权、稳定公开能力、私有禁区、允许/禁止依赖和共享准入：前端还须覆盖装配/路由页面、功能、远程/局部/跨页状态、模型映射和共享 UI；后端还须覆盖入口、编排规则、持久化适配、事务、授权、错误与副作用恢复；每单元至少一个代表性文件放置演练，并给出最小迁移、可观察演进和当前下游所需的高影响决定。稳定业务 owner、目录/包/模块边界、公开出口、私有禁区和依赖方向属于约束，代表性文件只验证归属，边界内部文件名、数量和等价拆分可按真实职责调整；前端稳定职责不得静默打平到巨型路由/页面或通用收纳目录，后端稳定业务包不得静默降级为同名平铺文件，跨所有者合并、出口绕过和私有路径引用等 Current 偏差须设计最小迁移。不固定框架目录或以行数阈值拆分。MVC、分层、六边形和 DDD 不是互斥四选一，不得为任一范式预建 `domain`、`application`、`infrastructure`、`shared`，或预建没有当前消费者的服务、队列、接口或其它结构。配置、运行、数据、测试和安全只按当前证据展开，禁止虚构 `[当前]`。
领域步骤继续使用公共 `run_agent_decision_loop` 保存、读取和解释完整 conversation，不解析消息 schema、角色顺序、尾部 decision、session/reference 组合或完整 commit prompt，也不把 conversation 当长期成功证据。fresh 仅因本步骤 session、conversation reference、私有状态或 conversation 路径等执行产物存在而拒绝；resume 交由公共循环。run 目录是受控、Git 忽略的本地恢复状态，不建设防篡改日志。

`completed` 后 completion verifier 先 repair 缺失或空文档；只有根仓存在未提交变化且边界确认只有固定文档时，才在原 session 发送 `/commit-changes`。文档已 tracked 且全仓 clean 时直接满足交付条件，不制造无变化调用。success 只要求固定文档非空、非符号链接普通文件、已 tracked，及根和适用子仓当前均为自身 top-level、`main`、clean；不要求 exact commit prompt、紧邻 Agent 回复或历史执行锚点。Python 只核验这些文件和当前 Git-visible 工作树/index，不解析 Markdown 的 Current/Target 地图、决策矩阵、目录归属或架构结论；其语义完成由 Skill、Agent 和 AI-compatible 负责人负责。结果已 success 而 state 推进中断，或完整 success 重跑时，仅按严格 result schema、当前文档/Git事实补状态或确认成功。`blocked` 始终保存并停在当前节点，不因文档 tracked+clean 改判 success。

**证据边界：** Python 只核验当前 Git-visible 工作树和 index；这不是不可绕过的安全隔离，不证明整个 Agent 执行历史未发生 Git 写入，也不覆盖 ignored 文件。本地 Demo 信任项目权限配置和 Agent 遵守领域约束；未来若要求不可绕过隔离，应在项目级权限或沙箱统一实现，而非由领域步骤解析 conversation 或扩展 Git DSL。第 10、11 步沿用该边界。

第 9 步更新后的 prompt 合同及第 9～11 步相关自动化已完成本轮验证：第 9 步定向 18 项通过（5.498 秒）；第 9～11 步本体合计 51 项（18+18+15）通过；公共循环加第 9～11 步本体及第 10/11 步 CLI 的相关回归 97 项通过（20.800 秒）；当前工作树全量 351 项 `unittest` 通过（61.878 秒）；`compileall common steps run_step.py run_all.py test_run_step_retry.py test_run_all.py` 与本次目标 `git diff --check` 通过。当前工作树还包含其它公共循环/CLI 的未提交修改，故全量结果是当前工作树验证，不能全部归因于第 9 步。第 9 步新版 prompt 合同尚未执行安全的 fresh 真实 Claude Agent、AI-compatible 负责人或 `/commit-changes` 集成；`step01-mendmark` 已推进到第 13 步并保留旧第 9 步 success/session/conversation，旧真实 run 仅为旧合同历史。

**旧合同下历史记录（非当前成功条件）**

旧失败包括 HTTP 403、非 JSON 普通文本和非法 `completed` 字段组合。根因是旧 prompt 将步骤规则混入 responsibility、硬编码并重复 completion 语义且缺少 output。用户将其重构为五段，补齐 f-string JSON 花括号转义和字段组合约束，并更新 common 与第 2/5/6/7/9 步测试。

以下 session、11 条 conversation、exact commit prompt、commit-changes 发现文档事实矛盾和提交事实均为旧合同下的历史运行路径，不构成当前成功条件。按用户要求两次清理第 9 步局部 result、conversation、session、private state 和失败生成的未跟踪文档后，保留第 0～8 步历史与三仓提交执行 fresh 运行。最终唯一 session `f41fc439-4c46-434f-b3e9-d15c18c89601`，conversation 11 条：`system → assistant 初始 → user → assistant continue → user → assistant completed → assistant commit prompt → user → assistant continue → user → assistant completed`。

首轮 Agent 请求确认，负责人合法 `continue` 后创建约 32 KB 固定文档；负责人 `completed` 后 verifier 同 session 调用 `/commit-changes`。该 Skill 发现 frontend Git 事实矛盾，严格未修改、未暂存、未提交并报告；外层负责人普通 `continue` 授权通用 Agent 仅修正文档并精确提交。

产品根提交 `ead14dffe19bc6417634c24c7bb1103602c3b772`，message `docs: 新增工程架构设计`，仅新增固定文档，376 行、32928 字节；未 push，frontend/backend 无变化。最终 decision 为合法严格 JSON `completed`，`steps/09.json` 和 state success，推进 `project:10_ui_ux_framework`。

独立核验 root/frontend/backend 均为自身 top-level、`main`、clean，文档 tracked。同 run 幂等重跑后 conversation 仍 11 条，session 和 root HEAD 不变，无 Agent、decision 或新提交调用。这些均为旧合同历史事实；第 10 步的对应历史见下。

#### 第 10 步现行新合同与旧合同历史

当前 Demo v1 的适用性唯一取第 8 步 strict success 的空 `outputs`、result/state 一致的合法有序 `applicable_repositories` 是否含 `frontend`，不扫描目录，也不让 Agent 判断。这是当前前后端交付单元模型的 Demo 简化；通用 `ui-ux-framework` Skill 保持可处理更广既有项目与显式既有路径的语义，不能把当前固定路径泛化为永久限制。

无 `frontend` 时，步骤严格核验第 5 步 `readiness_baseline` 与当前准备清单和两份产品定义一致，再读取第 8 步严格交接和第 9 步严格 success（唯一 `docs/design/工程架构设计.md`）。所有入口按本步骤 session、conversation reference、私有状态或 conversation 路径等执行产物存在性拒绝；否则零 Git、Agent、负责人决策、LLM 配置和 `docs/ui-ux/` 副作用，写入 success、`applicable: false`、`outputs: []` 并推进 `project:11_requirement_breakdown`。此路径由自动化覆盖准备清单和两份产品定义漂移均失败，黄金项目不走此分支。

有 `frontend` 时，单一 key/session 为 `ui_ux_framework`，初始 prompt 首行 `/ui-ux-framework`，只允许创建或更新 `docs/ui-ux/framework.md`。Agent 按需读取 Skill 自带布局参考，但资源不成为项目默认实现；能由项目事实推导的低风险结构形成带依据和重议条件的默认 Target，真正改变跨需求体验骨架的具体分歧由负责人通过 `continue` 决定并要求回写。负责人仅在适用范围的 App Shell Contract 已闭合，产品表面、区域职责、导航层级、页面模式、常规滚动所有者、sticky 基准和窄屏转换可指导后续需求，且 Current、已确认 Target、默认 Target、具体待确认、已知偏差和非目标没有混写时返回 `completed`；不接受整份框架泛化待确认。

`completed` verifier 先 repair 缺失或空文档；只有根仓存在且仅存在固定文档未提交变化时，才在原 session 发送 `/commit-changes`。已 tracked 且全仓 clean 的文档直接满足交付条件，不制造无变化调用。Python仍只核验文档非空、非符号链接普通文件、已 tracked，以及全部权威仓库当前均为自身 top-level、`main`、clean，不解析框架 Markdown 语义；不要求 exact prompt、紧邻 Agent 回复或历史执行锚点。适用路径的 fresh/resume/blocked、result/state 中断和幂等与第 9 步同构：领域步骤不解析 conversation，完整 success 只据严格 result schema、当前文档/Git事实恢复；blocked 始终保存并停在当前节点。合同保持局部实现，不改 `common`，不抽取 Git DSL、commit 事件、持久布尔标记或旧 prompt 兼容列表。

第 9 步更新后的 prompt 合同及第 9～11 步相关自动化已完成本轮验证：第 9 步定向 18 项通过（5.498 秒）；第 9～11 步本体合计 51 项（18+18+15）通过；公共循环加第 9～11 步本体及第 10/11 步 CLI 的相关回归 97 项通过（20.800 秒）；当前工作树全量 351 项 `unittest` 通过（61.878 秒）；`compileall common steps run_step.py run_all.py test_run_step_retry.py test_run_all.py` 与本次目标 `git diff --check` 通过。当前工作树还包含其它公共循环/CLI 的未提交修改，故全量结果是当前工作树验证，不能全部归因于第 9 步。第 9 步新版 prompt 合同尚未执行安全的 fresh 真实 Claude Agent、AI-compatible 负责人或 `/commit-changes` 集成；`step01-mendmark` 已推进到第 13 步并保留旧第 9 步 success/session/conversation，旧真实 run 仅为旧合同历史。

**旧合同下历史记录（非当前成功条件）**

旧合同自动化已通过第 10 步本体 16 项与 CLI 5 项；旧合同同时记录第 16 步本体 19 项与 CLI 4 项、全量 273 项通过。独立审查曾发现无 frontend 的 failed、blocked 或已推进状态遗留执行产物会误报 skip success，现已修正为所有状态统一拒绝并补测试。

以下真实 run 的 session、7 条 conversation、exact commit prompt、提交和幂等重跑均为旧合同下的历史运行路径，不构成当前成功条件。真实 run `pcm-demo/runs/step01-mendmark` 与产品 `/Users/zhou/resource/fireworks/ANDRSZAN/pcm-products/mendmark` 的第 8 步权威仓库为 `root/frontend/backend`，故适用。session `2d052d9a-b9fd-4fcd-b5f9-ff724f25dbc1` 的 init 确认 skill/slash command 已加载，cwd 为产品根，模型 `claude-fable-5[1M]`，Claude Code 2.1.233，permissionMode `bypassPermissions`。最后 Agent success，5 turns，cost `$3.207112`，`terminal_reason=completed`，无错误；fresh 运行内置 Explore 子代理曾输出未识别模型 `gpt-5.6-terra[1m]` 警告，主 Agent 同一次调用继续并 success，未追加人工或 run-history 恢复提示。

conversation 共 7 条：`system → assistant 初始 → user → assistant completed → assistant commit prompt → user → assistant completed`；framework repair 0 次，固定 commit prompt 恰好一次，锚点有效。固定文档已实际读取，为 206 行、25580 字节且没有实现代码。产品根提交 `0ceee1bb8b5836f64112ded0c8fd3cf7fbd1f29c`（父 `ead14dffe19bc6417634c24c7bb1103602c3b772`，message `docs: 建立产品级 UI/UX 框架`）仅新增该文档，未 push；frontend HEAD `dbab574dbe4d83a02323a750afd04de007565ac5`，backend HEAD `9682be837759c20f1a9ebbdf8fa2cfc09c2768d4`，三仓均自身 top-level、`main`、clean。`steps/10.json` success/applicable true/唯一 output，state 为第 11 步 `project:11_requirement_breakdown`。幂等重跑后 session、conversation、root HEAD、总提交与前后端 SHA 均未变化，无新提交。

#### 第 11 步现行新合同与旧合同历史

固定输入严格为第 2 步两份 outputs、第 5 步清单、第 7 步技术方案、第 8 步 strict success 的空 `outputs`、result/state 一致的合法有序 `applicable_repositories`、第 9 步唯一 `docs/design/工程架构设计.md`，以及严格第 10 步 success。第 8 步不逐项回放旧 `repositories` path、branch、clean 字段；实际 Git 状态由本步骤当前现场只读核验。第 10 步 `applicable: true` 时读取唯一 `docs/ui-ux/framework.md`；`applicable: false` 时必须为 `outputs: []`，不读取或扫描该文档。

单一 key/session 为 `requirement_breakdown`，初始 prompt 首行 `/requirement-breakdown`，唯一固定输出为 `docs/backlog/backlog.md`。领域步骤把完整 conversation 交由公共循环保存、读取和解释而不解析。框架中的已确认 Target 只有在要求演进既有产品表面、迁移本身形成独立可观察用户结果且其它需求开始前确实必须完成三项同时成立时，才形成迁移 BR 和严格依赖；不满足时进入相关业务 BR 的体验约束。默认 Target 只进入相关 BR 约束并保留依据与重议条件，不形成迁移 BR或严格依赖；偏离默认 Target或改变跨需求体验骨架时列为待确认。框架文档、Skill、页面、组件、CSS、目录、工程依赖和外部条件不得成为 `depends_on`，严格依赖只指开始前必须完成的正式 BR ID。运行时全部权威仓库当前必须是自身 top-level、`main`；子仓一直 clean，root 只允许固定 Backlog dirty，Python 仅执行 Git 只读核验。

负责人确认上述 Backlog 语义边界后才可 `completed`；随后先 repair 缺失或空文档，仅当 root 有未提交变化且边界确认只有固定 Backlog 时，才在原 session 调用 `/commit-changes`。文档已 tracked 且全仓 clean 时直接满足交付条件。Python仍只核验最终文件非空、非符号链接、tracked 和全仓 clean，不解析 Markdown 语义；不要求 exact prompt、紧邻 Agent 回复或历史锚点。fresh 仅按执行产物存在性拒绝，resume 由公共循环恢复；blocked 始终保存并停在当前节点，failed 保留现场，完整 success 仅按严格 result schema、当前文档/Git事实恢复。第 8～11 步的 Git/提交合同都保持局部实现，不改 `common`，不抽 Git DSL、commit 事件、持久布尔标记或旧 prompt 兼容列表。

第 9 步更新后的 prompt 合同及第 9～11 步相关自动化已完成本轮验证：第 9 步定向 18 项通过（5.498 秒）；第 9～11 步本体合计 51 项（18+18+15）通过；公共循环加第 9～11 步本体及第 10/11 步 CLI 的相关回归 97 项通过（20.800 秒）；当前工作树全量 351 项 `unittest` 通过（61.878 秒）；`compileall common steps run_step.py run_all.py test_run_step_retry.py test_run_all.py` 与本次目标 `git diff --check` 通过。当前工作树还包含其它公共循环/CLI 的未提交修改，故全量结果是当前工作树验证，不能全部归因于第 9 步。第 9 步新版 prompt 合同尚未执行安全的 fresh 真实 Claude Agent、AI-compatible 负责人或 `/commit-changes` 集成；`step01-mendmark` 已推进到第 13 步并保留旧第 9 步 success/session/conversation，旧真实 run 仅为旧合同历史。

**旧合同下历史记录（非当前成功条件）**

历史 `step01-mendmark` 第 11 步 success 当时确实进入旧 `phase_1:select_requirement` / step 12 占位入口。第 12 步真实运行前严格核验该 state 的第 11 步完整 success、空 `active_requirement`/`requirement_cycle`、无注册表、无 `12.json` 与三仓 `main`/clean；仅 run-local 将 `current_node` 规范化为 `phase_1:initialize_requirement_registry`，state SHA-256 从 `c153ec8c9d39d82806009c7052988695fe10d3a384566f00f852c2c8b4b02ee8` 变为 `eecf476c3b6c401c9db6a41f9f3ca398056eb509de956c93b0f9fae55f0ec170`。生产代码不接受旧入口，也未添加 legacy 兼容；规范化后真实第 12 步已成功完成。

旧合同自动化通过第 16 步本体 19 项与 CLI 4 项、全量 273 项；`compileall`、`git diff --check` 通过；Pyright langserver 未安装，未执行 IDE/LSP 诊断，独立只读审查修复后最终无高、中置信缺陷。Ruff 未安装，未执行 Ruff。

以下真实 run 的 exact commit、conversation、提交和幂等重跑均为旧合同下的历史运行路径，不构成当前成功条件。真实 run 为 `pcm-demo/runs/step01-mendmark`，产品为 `/Users/zhou/resource/fireworks/ANDRSZAN/pcm-products/mendmark`，权威仓库 `root/frontend/backend`。运行前旧 Skill 已由真实 `/commit-changes` 单独提交 `9263d28`（只改 Skill、未 push、三仓 clean）；这是采用新合同的测试前置，并非第 11 步输出。session `af7d198c-b090-44d8-9d92-ae0738150854` 的 init 确认 skill/slash command、产品根 cwd、Fable 5、Claude Code 2.1.233 和 `bypassPermissions`。fresh 调用内置 Explore 子代理曾报未识别模型 `gpt-5.6-terra[1m]`，主 Agent 同次仍 success；首次生成 Result 为 15 turns、`$5.789825`。

实际 Backlog 约 59,140 字节、约 1,110 行，含 14 项 BR 需求，完整覆盖 E.1，未自动纳入 E.2/E.3，首条验证切片为完整 BR-001～BR-006；没有需求开发状态列/字段，业务状态保留。负责人 Responses 决策曾三次在正常 run 后瞬时写入 failed；两次同上下文只读诊断的合法 `completed` 均未注入正式 conversation，靠正常原节点重跑恢复，未添加 HTTP 重试或修改生产 prompt。最终 conversation 为 7 条：`system → assistant 初始 → user 生成回复 → assistant completed → assistant exact commit prompt → user 提交回复 → assistant completed`，exact commit 一次且为同一 session。根仓未 push 提交 `2aaa743a97d96fe93deaaaaa13a94e4c414369a2`（`docs: 建立 MendMark 首版正式 Backlog`）仅新增 Backlog，frontend/backend SHA 不变，三仓 `main`/clean；幂等重跑无新调用或提交。


### 阶段一：已实现第 12～18 步

第 12 步位于需求循环之外；第 13～18 步已完成 BR-001。第二轮已完成 BR-002 的第 13、14 步；第 14 步负责人裁决失败现场通过同一 conversation 零 Agent 恢复。`step01-mendmark` 当前保留在 `requirement:15_development` / step 15，development session 已保存但首次 Agent 调用以 `api_error` 结束，未产生 Agent 回复或产品实现。

#### 第 12 步已实现合同与真实运行

- **执行方式**：直接调用 OpenAI Python SDK `responses.parse`，以 Pydantic 输入输出；不调用 Claude Agent SDK、`AgentDecision` 循环或 Skill。Responses/Pydantic 是自由格式 Backlog 的唯一语义提取器。
- **权威输入与 prompt**：只接受第 11 步完整 success、产品工作区内固定的非空 UTF-8 非符号链接 `docs/backlog/backlog.md` 和当前运行状态。模型每项仅允许 `id`、`title`、`order`、`depends_on`；system prompt 明确 Backlog 排版自由，要求全部且仅提取正式需求、同一需求只输出一次、忠实保留 canonical ID/标题/正式顺序/显式依赖，排除背景、说明、示例、候选、非目标、历史与未来设想，并禁止根据正文关联、出现先后或业务常识猜测依赖。prompt 不包含步骤编号、PCM、session 或 Skill 编排背景。
- **Python 校验**：Python 不解析 Markdown 标题、表格、详情卡或依赖章节，也不与第二套语义结果比对。它只要求 catalog 非空，ID 与依赖 ID 符合 `[A-Za-z0-9][A-Za-z0-9_-]*`，ID 忽略大小写唯一，数组物理顺序严格对应 `order=1..N`，依赖存在且不重复、不自依赖、无环。
- **现场与副作用边界**：程序从同一次 `read_bytes()` 生成模型输入文本和 SHA-256，模型完成后重新读取并拒绝 Backlog 内容漂移；不选择活动需求、不创建分支、不修改产品项目，也不读取或写入 Git。
- **结果、状态与恢复**：成功 result 保存 Backlog `{path, sha256}` 来源与仅静态字段的 catalog，`outputs: []`；先写 result，后写 `schema_version: 1` 注册表，全部需求由 Python 初始化 `pending`、`completion: null`，然后进入 `phase_1:select_requirement` / step 13。JSON 以同目录唯一临时文件原子 replace 写入。result 已写而 state 未推进时从 result 恢复；完整 success 重跑要求当前来源、catalog、注册表完全一致并零模型调用，任一漂移或冲突 `failed` 且不覆盖。旧 `{path, sha256, root_main_sha}` source 不兼容、不迁移，只作为旧合同历史。
- **真实运行**：隔离 run `step12-ai-only-20260826` 使用无 Git 工作区和没有总览表、详情卡或固定标题层级的自然语言 Backlog。真实 Responses 准确注册 `BR-AI-001`～`BR-AI-003`，标题、order 1～3 和显式依赖均正确，并排除 `NOTE-001` 示例和在线支付未来设想；全部 `pending`、`completion: null`。Backlog SHA-256 为 `c8fb63f1e403fcf36c302f77511dfb7ea29a305a345f6bf125c9c101801f8f76`。以不可连接的 LLM 配置运行 CLI 仍 success，`steps/12.json` 与 state 字节不变，最终 SHA-256 分别为 `047e6b8e615471ecb930709f942b62cffc29b57a9013815cc5ab97ed617e321f`、`9871652c38042459827724fab5559df5492ec5377e356fac23bc189487e76472`。历史 `step01-mendmark` 的 14 项提取、root SHA 与三字段 source 继续仅为旧合同证据。
- **自动化**：第 12 步本体 10 项、CLI 6 项，共 16 项；第 12～14 步定向回归 61 项；PCM Demo 全量 282 项 `unittest`、`compileall common steps run_step.py` 和目标 IDE diagnostics 通过。

#### 第 13～18 步循环

| 步骤 | 名称 | 核心边界与成功锚点 |
| --- | --- | --- |
| 13 | 选择需求并建立统一需求分支（已实现） | Python 从 ready pending 中选 `order` 最小需求；fresh 全局预检全部适用仓后先持久化 `active_requirement`（仅 ID）和 cycle（`req/<lowercase-id>`、按仓名 `base_sha`、返回节点），再以 `git switch -c` 建立同名分支。Git 子进程过滤 `GIT_*`。success 只写 `steps/requirements/<ID>/13.json` 并推进 `requirement:14_trd_design`；后续保护只验证第 13 步拥有的核心投影，允许其它步骤追加 cycle 字段；无 pending 的阶段二转场当前延期，有 pending 无候选失败 |
| 14 | 形成活动 TRD（已实现） | 只消费当前 active requirement、cycle、workspace 和注册表已记录的 canonical Backlog 来源，首次持久化 `docs/trd/<YYYY-MM-DD>-<ID>-<标题>.md`；完整 Backlog 正文进入负责人 `<project_context>`，再通过 requirement-scoped 公共循环显式调用或恢复 `/trd-design`；Agent 按需承接本需求适用的体验决定和每个受影响交付单元的稳定工程 owner/边界/依赖/预期改动归属，跨边界变化显式记录架构 delta；Python只核验指定 TRD 非空，不读取 Git或重复复验前序步骤 |
| 15 | 实现与验证（已实现） | 调用 `dev-workflow` 完成实现、测试、构建、运行、联调、真实浏览器与渲染验收和独立审查；完整活动 TRD 正文进入负责人 `<project_context>`，不重复加入 Backlog 或工程架构全文；完成报告按每个受影响交付单元提供架构归属→改动/依赖→diff/导入/调用证据→结果映射，并保留适用体验决定的浏览器/截图和动态证据；稳定边界与体验决定均不得静默偏离，保存 `development_session_id`，不提交、不合并 |
| 16 | 原开发 session 规则复盘（已实现） | 只消费 active requirement/cycle/workspace 与 `development_session_id`；以独立 `rule_retrospective_<ID>` conversation 预注册 alias 后恢复原 session，允许规则变化或 no-change，不读取 Git或限制规则文件结构，`outputs: []`，不提交 |
| 17 | 统一提交需求变更（已实现） | 在产品根 direct `run_claude()` session 中调用 `commit-changes`，仅处理有序 `applicable_repositories` 白名单；Python 只核验分支、main/base、最终 clean 和 tips；不合并、不标记完成 |
| 18 | 程序化合并并完成需求（已实现） | 只使用 Python/Git；非 root 代码仓先、root 最后执行或恢复 `git merge --ff-only`。逐仓保存 merged，全仓 `main==tip` 后统一安全删除需求分支，先写 scoped `18.json` 再由 Python 写 `completed` |

#### 第 14 步实现与真实运行

第 14 步采用与第 15 步一致的薄编排，只消费当前 state 的 active requirement、注册表唯一 active 项、cycle、workspace 和注册表已记录的 canonical Backlog 来源。严格串行流程中的前序 success 与产物被视为可信交接；第 14 步不重新读取或精确复验第 2/5/7/8/9/10/11/12/13 步结果、其它固定文档、仓库 descriptor 或 Git 基线。Python 从 `requirement_registry.source.path` 读取完整 Backlog 正文并放入负责人的 `<project_context>`，使负责人理解当前需求在全部需求中的位置、依赖和关系；Agent 在 `/trd-design` 中按需读取其它当前项目资料和代码。

Python 使用首次本地日期、ID 和标题生成 exact `trd_path`，对直接用于文件名的标题做最小合法性检查，并在首次 Agent 调用前写入 cycle intent；后续恢复只沿用该值。Agent/session/conversation key 为 `trd_design_<ID>`。步骤直接复用公共 `run_agent_decision_loop` 保存和恢复 session、conversation 与待裁决回复，不解析公共 conversation 内部结构，也不覆盖 `permission_mode`、`tools`、`allowed_tools`、`disallowed_tools` 或增加私有 tool hook。

负责人规则要求范围、关键行为、技术方案、验证、需求级体验、适用工程归属合同和阻碍实现的决定已经收敛，不能把“实现前必须确认”列表误作完成。存在本需求真正适用的已确认 Target 或有依据的默认 Target 时，TRD 须记录其来源、适用范围、经核验 Current、Target 以及本需求遵循或改变的关系；默认 Target 还须记录依据和重议条件，偏离时说明理由，改变跨需求体验骨架时由负责人决定。存在可核验且适用的工程架构资料时，TRD 还须按每个受影响交付单元记录稳定 owner、目录/包/模块边界、公开/私有边界、允许/禁止依赖和预期改动归属；边界内部文件粒度可调整，跨所有者合并、边界打平、出口绕过、私有路径引用或用巨型入口/页面、通用收纳目录、同名平铺文件替代已确认边界时，须作为架构 delta 记录影响、理由和最小迁移。没有适用决定或工程约束时不虚构、不阻塞，也不固定要求 `docs/ui-ux/framework.md`、`docs/design/工程架构设计.md`、对应 Skill 或任何技术栈。Python completion verifier 只核验指定活动 TRD 是产品工作区内的非空文件；缺失或为空时同 session repair，不调用 `/commit-changes`。success 先写 `steps/requirements/<ID>/14.json`，再推进 `requirement:15_development`；blocked 保留路径和同一 session，result→state 中断只补状态，推进后不再读取文件或调用 Agent。第 14 步不读取 Git，不重复检查第 13 步建立的分支/base，也不监管第 17、18 步负责的提交和合并。

真实 run 中，第 14 步使用 session `b9ed4756-0acf-4666-b3f9-c8f3628c03f1` 生成 `docs/trd/2026-08-25-BR-001-身份、角色访问与站内消息入口.md`。首次负责人错误接受 8 项实现门槛，随后在同一 session 收敛决定；负责人服务 free quota 403 后也从原 conversation 尾部恢复完成。最终 conversation 7 条且无 `/commit-changes`。当时 root 只有唯一未跟踪 TRD、frontend/backend clean、三仓无 staged、提交、merge 或 push，是旧实现结束时的历史现场，不再是现行 success 条件，也不会由现行代码重复核验；既有产物、session、result、state 和 Git 现场不因本次精简而改写。

#### 第 15 步已实现合同与真实验证

第 15 步只消费当前 state 的 active requirement/cycle/workspace、当前需求 scoped 第 14 步 `success` 和非空活动 TRD；不读取第 2/5/7/8/9/10/11/13 步文档，不执行 Git 命令或 Git verifier。requirement-scoped key 为 `development_<ID>`，复用公共 `run_agent_decision_loop`。初始 Agent prompt 只包含 `/dev-workflow`、需求 ID/标题和活动 TRD 路径，负责人的 `<project_context>` 包含同一路径和完整活动 TRD 正文，不重复加入 Backlog、工程架构全文或其它上游文档。Agent 按需自行读取项目资料、代码、配置、测试和环境，按活动 TRD 中的适用体验决定与工程架构约束实施，必要稳定设计偏差和架构 delta 同步活动 TRD。有适用工程架构约束时，负责人只在 Agent 已按每个受影响交付单元建立“架构约束/模块归属→改动位置与依赖关系→diff/导入/调用证据→实际结果”映射，且稳定业务 owner、目录/包/模块边界、公开出口、私有禁区和依赖方向没有被巨型路由/页面、通用收纳目录、同名平铺文件、跨所有者合并或私有路径穿透静默弱化后返回 `completed`。活动 TRD 存在适用的已确认 Target 或默认 Target 时，负责人还要求 Agent 建立“体验决定（默认 Target 含依据与重议条件）→可观察结果→实现位置→真实浏览器和实际读取截图证据→实际结果”映射、没有静默偏离且截图未替代动态交互、权限、失败恢复和持久化验证。Agent 不得修改 `.claude/rules/`，也不得 stage、commit、创建或切换分支、merge 或 push。

completion verifier 保持为空，架构归属、体验决定与其它实现语义由 Skill、Agent 和负责人裁决；`continue` 和 `blocked` 沿用公共语义。首次从 Agent 取得 session 后立即同步 `requirement_cycle.development_session_id`。success scoped result 写入 `steps/requirements/<ID>/15.json`，`outputs: []`，保存 requirement ID、TRD 路径和 development session ID，随后推进 `requirement:16_rule_retrospective` / step 16；blocked 保留 step 15 和同一 session。success result→state 中断恢复及推进后幂等已实现，CLI 只保护当前活动需求完整 scoped success。

真实 run 为 `pcm-demo/runs/step01-mendmark`，产品为 `/Users/zhou/resource/fireworks/ANDRSZAN/pcm-products/mendmark`。development session `e6bd1b82-39f9-41b2-9cc9-a69b281015dc` 的 init 确认 Fable 5、Claude Code 2.1.233、`bypassPermissions`，最终 normal success 23 turns、约 `$9.784016`。首次调用在 init/session 保存后因 `claude-agent-sdk` 0.2.139 默认单条 CLI stdout JSON 1 MiB 缓冲出现 `JSON message exceeded maximum buffer size`；仅将公共 `ClaudeAgentOptions.max_buffer_size` 固定为 `10 * 1024 * 1024`，不增配置、不影响 resume，随后恢复同一 session 并保留既有产品改动。自定义 dev/reviewer 子代理出现未识别 model 警告和一个子进程退出，但主 Agent 继续完成，生产 prompt 未改。

conversation 最终 9 条：`system → assistant 初始 → user 首轮回复 → assistant completed → assistant 正常结束要求 → user 已实现但未完全验证 → assistant continue 补 Firefox/WebKit → user 三浏览器结果 → assistant 最终 completed`。Agent 报告后端 Ruff/format/build、pytest 16 passed 1 skipped、真实 PostgreSQL、Alembic upgrade-downgrade-upgrade；前端 lint/type-check/build、Vitest 15 passed；Chromium/Firefox/WebKit Playwright 矩阵 3 passed；真实 FastAPI/PostgreSQL/Vite 浏览器联调、代表性截图读取和独立审查完成。负责人最终 completed，state 进入 step 16，BR-001 仍 active/completion null。root 保留活动 TRD和代表性截图未跟踪，frontend/backend 保留实现、测试、迁移与配置未提交变更；三仓均为 `req/br-001`、index clean、无 commit/merge/push。不可用 LLM 配置幂等重跑仍 success，state/result/conversation 字节不变，SHA-256 分别为 `069b50dc583d8472683eded457bdb954265e37000b78c59860986bc8ea15bf72`、`033585fb8c7b2a43937dd67082aec8a179cc368ede869c460df4300a438487a2`、`432072a5bb43f90af90adf557bc1b92adab3599a5adb11a5696f57167a100e19`。第 15 步本体 6 项、CLI 4 项和其历史全量 252 项验证保持不变；第 16 步旧实现本体 19 项、CLI 4 项、全量 273 项 `unittest`、`compileall`、`git diff --check` 均通过。Pyright langserver 未安装，未执行 IDE/LSP diagnostics；独立只读审查修复后最终无高、中置信缺陷；Ruff 未安装，未执行。第 16～18 步随后均已完成实现与适用真实验证。

#### 第 16 步已实现合同与真实验证

第 16 步采用与第 15 步一致的薄编排，只消费当前 active requirement、cycle、workspace 和一致的 `development_session_id`；不重新读取或精确复验第 15 步 result、TRD、仓库、分支或工作树。

步骤以 `rule_retrospective_<ID>` 建立独立负责人 conversation，首次 Agent 调用前将该 key 的 Claude session alias 绑定为同一 `development_session_id`，公共 `run_agent_decision_loop` 因而恢复原开发 session。初始 prompt 首行固定 `/session-rule-retrospective 本次开发会话`；`completed` 允许规则变化或 no-change，`continue`、`blocked` 沿用公共语义。

success 先写 `steps/requirements/<ID>/16.json`，`outputs: []`，再推进 `requirement:17_commit` / step 17；blocked 保留当前节点、原 session alias 和独立 conversation。result→state 中断只补状态，推进后不需要工作区、Git、Agent 或模型。第 16 步不建立 Git baseline、不检查规则目录结构，也不限制 Skill 的输出文件；第 17 步负责读取实际未提交变更并提交。

现行本体 7 项、CLI 4 项，共 11 项；相关定向 51 项和全量 282 项 `unittest`、`compileall`、`git diff --check` 通过。真实 `step01-mendmark` 曾复用 development session `e6bd1b82-39f9-41b2-9cc9-a69b281015dc` 完成规则复盘并新增 `.claude/rules/frontend-playwright-container.md`。旧实现的三仓提前提交失败、`git reset --mixed` 现场恢复和 Git-visible baseline 是历史事实，不再是现行 success 条件，也不会由现行代码重复核验；既有规则、result、state 和 conversation 不因本次精简而改写。

#### 第 17 步已实现合同与真实验证

第 17 步只消费 active requirement/cycle/workspace、完整 scoped `16.json` success、统一需求分支、`applicable_repositories` 有序白名单和每仓 `base_sha`。Python只核验非符号链接仓库路径、自身 Git top-level、统一分支、`main==base`、`HEAD==target` 和包含未跟踪文件的最终 clean。

fresh 全仓 clean 时零 Agent、零负责人决策和零 conversation。存在 dirty 仓或合法恢复现场时，在产品根使用 `requirement_commit_<ID>` 公共 Agent 决策循环：初始 `/commit-changes` 一次，保存完整 conversation；负责人可返回 `continue/blocked/completed`，continue、blocked resume和completed后repair均恢复同一 Claude session。首次 Agent 在取得session前失败时，仅允许严格的 `system → 初始 assistant` conversation 以无session重投原prompt；其它残缺锚点拒绝恢复。

完整 diff、提交分组、精确暂存、空提交和提交历史由 `commit-changes` 负责。Python不制作 fingerprint、不读取 blob/tree、不判断 merge commit或验证首次内容等价。success只写 scoped `17.json` 的 `name/path/base_sha/tip_sha`，cycle写 `{base_sha,tip_sha,merged:false}` 并推进step18；result→state和advanced幂等保留。

现行实现本体 9 项、CLI 4 项；公共循环与第 17 步定向 43 项通过。当前工作树全量 351 项 `unittest` 通过（61.878 秒），`compileall common steps run_step.py run_all.py test_run_step_retry.py test_run_all.py` 与本次目标 `git diff --check` 通过；当前工作树还包含其它公共循环/CLI 的未提交修改，故全量结果不能全部归因于第 9 步。独立只读审查无高、中置信发现。BR-001 旧运行有完整四段 conversation；BR-002 在 direct-run 版本期间只有 Claude session、没有 decision reference 或 conversation 文件，该历史缺口不补造，未来需求按现行合同保存完整历史。

#### 第 18 步已实现合同与真实验证

第 18 步只读取当前 active requirement/cycle、`applicable_repositories`、工作区仓库路径和 scoped `17.json` success 中 requirement、branch、仓库 base/tip 等必要字段；前序交接和 cycle 可以增加无关字段。步骤不调用 Agent、Skill、LLM、session 或 conversation，不读取业务文档、完整 diff、commit message 或提交历史。

Git 子进程统一过滤 `GIT_*`。仓库按非 root 原顺序、root 最后的顺序处理；`main==tip` 表示已合并并补写 `merged:true`，`main==base` 且未合并时执行必要的 `switch main` 和 `merge --ff-only`，`base==tip` 是 no-op。每仓完成后立即原子保存 merged；只有全部仓 main 到 tip 后才统一安全 `branch -d`。partial merge、merge 后 state 中断、partial cleanup 和 `18.json` 已写但 state 未完成均按当前 Git 事实恢复，不回滚已成功仓库。

最终每仓必须在 main、`HEAD==main==tip`、clean、无进行中操作且需求分支不存在。步骤先写 root-first scoped `18.json`，再将注册表项写为 `completed` / `completion:{"step":18}`，清空 active requirement/cycle 并返回记录节点。完整 success 保护只服务 state 尚未推进的恢复窗口；完成后误调不会降级或覆盖状态。

第 18 步本体 10 项、CLI 5 项，共 15 项；全量 282 项、`compileall`、`git diff --check` 通过，独立只读审查无高、中置信发现。真实 `step01-mendmark` 已将 frontend/backend/root 的 main 分别 ff-only 到 `65764dee0b2655f1c674ec36fee527861ea5043c`、`0e0bf9bb37e2abcf8c923c0fa4611c671da87640`、`62ac0aea0a69ea95d6382adfc276adce808be964`；三仓均在 main、clean、`req/br-001` 已删除、无 merge commit且未 push，BR-001 已完成，state 返回 step 13。

#### 生命周期、提交与恢复边界

- 需求注册表是开发生命周期唯一真源；Backlog 和活动 TRD 不记录 pending、active、completed、blocked 或恢复位置。
- 持久化生命周期只需要 `pending / active / completed`；具体进度由 `phase/current_node` 和活动 `requirement_cycle` 表达，blocked 与生命周期正交。
- 第 14～16 步全部保留未提交变更；第 17 步是整个需求的唯一提交阶段，第 18 步是唯一合并阶段。
- 所有适用仓库使用相同需求分支名并统一建立分支；不按 TRD 推断受影响仓库，不硬编码 root/frontend/backend。
- 第 13 步部分建分支后恢复时，分支存在且仍指向记录基线则复用；指向其它 SHA、未知 dirty 或归属不明时失败。
- 第 17 步恢复以各仓实际 clean 状态、需求分支和 tip SHA 为依据；提交能力不得修改工作树内容来让检查通过。
- 第 18 步恢复时，某仓 `main == tip` 表示已合并，`main == base` 表示尚待 ff-only 合并；其它 SHA、非 fast-forward、冲突、dirty 或分支证据不一致均保留现场并失败。
- 合并后的文件树与第 15 步已验证、第 17 步已提交的分支一致时，不机械重跑完整业务验证；但分支、SHA、clean 和 Git 历史状态核验不可省略。
- 只有全部仓库合并、核验和分支清理成功后才能写 `completed`；随后按 `return_node_after_completion` 回第 13 步或返回阶段二修复节点。

### 阶段二：全项目级集成产品体验审计与迭代

#### 1. 入口与范围

进入条件：

- 第 12 步需求注册表已经初始化，且当前正式范围内全部需求已完成第 13～18 步；
- 所有 `applicable_repositories`（其中包含 root）均位于清楚的 `main`；
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
- 合格候选通过根仓库最新 `main` 上的短期入池分支写入正式 Backlog，调用 `commit-changes` 精确提交，再显式合并回 `main`；外层保存“正式需求 ID → 原审计候选”映射；
- 入池只创建后续可选择的需求，不创建活动 TRD、代码分支或完成状态。

#### 4. 修复、原发现回归与完整复审

- 一批已入池需求先按第 12 步相同的静态解析、哈希和 Python 动态状态语义原子增量加入既有需求注册表，保留所有既有状态；随后需求循环不接收指定需求参数，每次由第 13 步从注册表确定性选择下一项。第 18 步完成后，外层按实际完成的正式需求 ID 查询入池候选映射，再执行对应原发现回归。该协调和映射边界在阶段二实现时落实，不提前创建公共协调器；
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
6. 所有自动入池需求均已增量加入需求注册表、完成第 13～18 步，并通过原发现回归；
7. 最后一轮完整复审没有新增符合需求化政策的候选，也没有未处理的高信心阻断或高优先级问题；
8. 与主要任务有关的环境、角色、数据、视口、辅助技术和动态证据覆盖缺口已经关闭；
9. 所有适用仓库位于预期 `main`，工作树无意外变更，结果与仍适用限制已经汇总。

## 九、状态演进与恢复目标

### 1. 当前状态事实

第 0～18 步同时使用 `current_step` 和必要的 `phase/current_node`。第 9～11 步 success 只以必要文档和当前 Git 事实为准；`run_step.py` 对第 8～12 步 success 保持固定保护，第 13～18 步按当前 active/cycle 保护 scoped result/state。前序步骤只校验自己拥有的核心投影，允许后续步骤追加自身字段；历史步骤的异常仅能在 state 仍位于该步骤锚点时持久化，不能改写已推进节点。

当前真实 state 位于 `phase_1_requirement_development` / `phase_1:select_requirement`、`step/current_step: 13`。`BR-001` 与 `BR-002` completed，其余 12 项 pending；`active_requirement` 与 `requirement_cycle` 均为 null。BR-002 root/frontend/backend main tips 分别为 `2f39fbe7e26d6e4905142925ae149ba83d9e70fe`、`f290ff85ed779a1f100eeded7eedfcfb0376b826`、`204a7a6b48c43a80f573dc9e70acedddb59bbe4f`；三仓 clean、`req/br-002` 已删除且未 push。

已确认但尚未实现的流程是：

- 不带数字步骤的阶段二审计、分流、入池、回归和复审节点。

因此只使用 `current_step` 已不足以表达完整恢复位置；需求生命周期由注册表管理，具体执行进度由 `phase/current_node` 和活动 `requirement_cycle` 管理。

### 2. 目标恢复锚点

第 3 步成功后已经使用以下恢复锚点：

```json
{
  "phase": "project_initialization",
  "current_node": "project:04_assemble_foundation",
  "step": 4,
  "current_step": 4
}
```

第 4 步成功后已经推进到：

```json
{
  "phase": "project_initialization",
  "current_node": "project:05_verify_readiness",
  "step": 5,
  "current_step": 5
}
```

第 5 步成功后已经推进到：

```json
{
  "phase": "project_initialization",
  "current_node": "project:06_bootstrap_foundation",
  "step": 6,
  "current_step": 6
}
```

第 6 步成功后已经推进到：

```json
{
  "phase": "project_initialization",
  "current_node": "project:07_solution_design",
  "step": 7,
  "current_step": 7
}
```

第 7 步成功后已经推进到：

```json
{
  "phase": "project_initialization",
  "current_node": "project:08_initialize_repositories",
  "step": 8,
  "current_step": 8
}
```

第 8 步成功后已经推进到：

```json
{
  "phase": "project_initialization",
  "current_node": "project:09_engineering_architecture",
  "step": 9,
  "current_step": 9,
  "applicable_repositories": ["root", "frontend", "backend"],
  "repositories": [
    {
      "name": "root",
      "path": "/products/mendmark",
      "branch": "main",
      "worktree_clean": true
    },
    {
      "name": "frontend",
      "path": "/products/mendmark/frontend",
      "branch": "main",
      "worktree_clean": true
    },
    {
      "name": "backend",
      "path": "/products/mendmark/backend",
      "branch": "main",
      "worktree_clean": true
    }
  ]
}
```

上述字段只列出实际适用仓；示例中的前后端不表示固定要求。

第 11 步历史 success 当时的恢复锚点为：

```json
{
  "phase": "phase_1_requirement_development",
  "current_node": "phase_1:select_requirement",
  "step": 12,
  "current_step": 12,
  "active_requirement": null,
  "requirement_cycle": null
}
```

这是真实 run 当时尚未实现第 12 步的旧占位状态。第 12 步真实运行前严格核验其完整第 11 步 result、无注册表、无 `12.json` 和产品三仓 `main`/clean，仅 run-local 将 `current_node` 规范化为 `phase_1:initialize_requirement_registry`；这一历史处理不进入生产入口兼容。

第 12 步现行合同 success 后、第 13 步执行前的真实隔离恢复锚点为：

```json
{
  "phase": "phase_1_requirement_development",
  "current_node": "phase_1:select_requirement",
  "step": 13,
  "current_step": 13,
  "requirement_registry": {
    "schema_version": 1,
    "source": {
      "path": "docs/backlog/backlog.md",
      "sha256": "c8fb63f1e403fcf36c302f77511dfb7ea29a305a345f6bf125c9c101801f8f76"
    },
    "requirements": [
      {
        "id": "BR-AI-001",
        "title": "访客预约入口",
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

实际隔离注册表包含 `BR-AI-001`～`BR-AI-003` 共 3 项；上述只展示首项结构。完整 success 的 result 先于 state 写入，result 已写而 state 未推进时可无模型调用恢复；完成后完整 success、当前 Backlog 路径/SHA-256、静态 catalog 和全 pending 注册表必须严格一致，否则失败且不覆盖。历史 `step01-mendmark` 的 14 项三字段 source 不作为现行 schema 示例。

第 17 步提交完成、等待第 18 步合并时，目标活动 cycle 至少记录统一分支、同一开发 session 和逐仓证据：

```json
{
  "current_node": "requirement:18_merge",
  "active_requirement": "BR-001",
  "requirement_cycle": {
    "requirement_id": "BR-001",
    "branch": "req/br-001",
    "development_session_id": "session-id",
    "repositories": {
      "root": {
        "base_sha": "<base-sha>",
        "tip_sha": "<tip-sha>",
        "merged": false
      },
      "frontend": {
        "base_sha": "<base-sha>",
        "tip_sha": "<tip-sha>",
        "merged": false
      }
    },
    "retrospective": {
      "outcome": "no_change"
    },
    "return_node_after_completion": "phase_1:select_requirement"
  }
}
```

示例中的仓库只表示实际 `applicable_repositories`；不固定要求 frontend 或 backend。第 13 步已固定需求分支命名为 `req/<lowercase-id>`，同一需求在全部适用仓库使用同名分支。

阶段二目标状态至少需要：

```json
{
  "phase": "phase_2_full_product_audit",
  "current_node": "phase_2:route_candidates",
  "requirement_registry": {
    "source": {
      "path": "docs/backlog/backlog.md",
      "sha256": "<backlog-sha256>"
    },
    "requirements": [
      {
        "id": "BR-001",
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

上述仓库字段只遍历实际 `applicable_repositories`；示例中的前后端不表示固定要求。为简洁只展示注册表项的 ID 和生命周期，实际 `title`、`order`、`depends_on` 等静态字段继续保留。`requirement_registry` 在阶段二始终保留，作为既有和新入池需求生命周期的唯一真源；阶段二节点不得用仅含审计状态的新对象替换它。

### 3. 恢复与幂等规则

1. 每个节点开始前保存 `phase/current_node` 和已核验输入；成功时先写当前步骤结果，再推进下一节点状态；
2. `--resume <run-id>` 只重跑当前节点，并按该节点合同重新核验它自己拥有的 intent、session、输出、版本指纹或外部条件；不跨节点重复核验前序步骤已经完成的文件、分支、提交或工作树事实；
3. 已有 Claude session 时优先恢复；session 不可恢复时返回 `failed`，不静默新建；
4. 第 5 步若 `steps/05.json` 已成功而状态仍停留第 5 步，必须核验严格成功 schema、准备清单和两份产品定义与 `readiness_baseline` 指纹一致，再恢复推进到第 6 步；缺少指纹的旧 success、清单漂移或产品范围漂移均失败且不自动升级。预算或 turn 上限恢复同一 session，完整成功现场不再次调用 Agent 或重复资源副作用；
5. 第 6 步先按 `project_bootstrap` conversation 尾部恢复项目化领域：Agent 回复先裁决、`continue` 原样恢复、`blocked` 终止、`completed` 先核验 README/`.coverage`/Git。bootstrap 完成且有 frontend 时，再按独立 `tailwind_theme` conversation 尾部以相同规则恢复主题领域；theme blocked/failed 不重新执行 bootstrap Agent。Tailwind v4 CSS-first gate 失败属于 failed；两个领域都 completed 前不写 success。预算/turn 上限可裁决但正常 `success` 前不能完成；
6. 第 7 步对话尾部为 Agent 回复、`continue`、`blocked` 或 `completed` 时，分别先裁决、原样 `answer`、终止或先完成核验；固定文档可补完时追加修复提示，成功及 blocked 终止前均需核验文档、session、根/适用子仓 Git 边界；
7. 第 8 步恢复先重读权威仓库现场：已全干净直接成功，仍 dirty 时恢复原 session；已有 Agent 执行事实但 session、conversation 引用或历史文件缺失时返回 `failed`，不得静默新建会话。`completed` 后仍 dirty 则用固定 repair prompt 继续，`blocked` 后仍 dirty 才保存 blocked。成功结果写入后 state 推进中断时以 `status=success` 结果为唯一锚点重验并推进，`failed` / `blocked` 结果不当作成功或阻止恢复；
8. 第 9 步 fresh 入口必须全仓 clean，且仅按本步骤 session、conversation reference、私有状态或 conversation 路径等执行产物存在性拒绝；resume 由公共循环恢复原 session。文档补全后，只有根仓存在且仅存在固定文档未提交变化时才调用 `/commit-changes`；文档已 tracked 且全仓 clean 时不制造无变化调用。成功写入中断和完整 success 重跑仅按严格 result schema、当前固定文档和 Git事实恢复，不依赖 conversation；
9. 第 10 步先以第 8 步 strict success 的空 `outputs`、result/state 一致的合法有序 `applicable_repositories` 判断是否有 `frontend`。不适用时按执行产物存在性拒绝，严格第 9 步 success 后以 `applicable: false`、空 outputs 推进第 11 步且保持零 Git、Agent、负责人决策、LLM 配置和文档副作用；适用 fresh 入口要求全仓 clean。固定文档缺失/空先 repair，只有唯一根仓固定文档未提交变化时才调用 `/commit-changes`；文档 tracked 与全仓 clean 即满足交付。适用与不适用写入中断均仅按严格 success result、当前文档和 Git事实恢复，残缺 success 不保护；
10. 第 11 步 fresh 入口要求全仓 clean，且仅按执行产物存在性拒绝；resume 由公共循环恢复。缺失或空 Backlog 先 repair，随后只有唯一根仓固定 Backlog 未提交变化时才在原 session 调用 `/commit-changes`；文件 tracked 与全仓 clean 直接构成交付事实，不依赖 prompt 或回复锚点。完整 success 可仅按严格 result schema、当前文档/Git事实从 result/state 中断恢复，残缺 success 不保护；
11. 第 12 步以完整 success result、当前 Backlog 路径/SHA-256、静态 catalog 和一致的全 pending 注册表为幂等锚点；模型调用期间重新读取 SHA 并拒绝内容漂移，旧三字段 source 不兼容或迁移。第 13～16 步按各自既有 intent、session 与 scoped result 恢复；第 17 步只保存唯一产品根 session，失败后每次恢复同一 session 一次，最终以白名单仓库的分支、main/base、clean 和 `tip_sha` 为锚点；完整 success 写入中断时按 result 与 Git 事实补 state，推进第 18 步后不再读取 Git；第 18 步按 `main == tip` 或 `main == base` 识别已合并或待合并仓库，非 fast-forward、其它 SHA、dirty 或证据冲突均失败，全部仓库核验和分支清理完成前不得写 `completed`；
12. 阶段二每轮审计、候选分流、入池和修复返回的恢复证据在进入阶段二实现前确认；已入池候选不得重复分配 ID，路径、目录、分支、提交、合并、版本指纹、候选归属或入池证据冲突时保留现场并返回 `failed`。

第 3～8 步的历史和真实验证事实保持不变。第 9～11 步旧真实路径仍只作为旧合同历史；第 12 步现行合同已用无 Git、自由格式 Backlog 的隔离 run 完成真实 Responses 提取和零模型幂等重跑，历史 `step01-mendmark` 的 14 项注册属于旧三字段 source 合同；第 13～18 步已完成 BR-001 的选择、设计、实现验证、规则复盘、提交、ff-only 合并、分支清理和生命周期完成。

## 十、测试与验证策略

### 1. 已完成范围

当前测试和真实验证覆盖：

- 配置和敏感信息不泄露；
- JSON、Markdown、状态和 SHA-256 读写；
- 第 0～8、12～18 步状态转换；
- 本轮待决策事项交接合同由统一负责人 XML prompt、同 session `continue.answer` 恢复测试和 fresh Probe C 覆盖；只给活动 TRD 路径与行号、未说明详细待决策问题的交接返回 `continue`，自包含的不可替代外部资源缺口返回 `blocked`。各步骤原有 `completed/continue/blocked` 判断规则保持不变，本轮不把第 15 步完成声明或未复述内容设为新闸门；
- 第 5 步本体 15 项、第 6/7/9/10/11 步下游 readiness 交接 68 项，合计 83 项；第 13 步本体 20 项与 CLI 10 项、显式 SDK 通道重试 7 项均保留其专属验证语境。本轮当前工作树全量 351 项 `unittest` 通过（61.878 秒），`compileall common steps run_step.py run_all.py test_run_step_retry.py test_run_all.py` 与本次目标 `git diff --check` 通过。当前工作树还包含其它公共循环/CLI 的未提交修改，故全量结果不能全部归因于第 9 步；
- 本次第 1 步根 `.env` 工作区工具配置合同安全定向 24 项通过；当前工作树全量 359 项 `unittest` 通过（53.340 秒），相关 IDE diagnostics 与 `compileall common steps run_step.py run_all.py test_run_step_retry.py test_run_all.py` 通过。覆盖 `O_NOFOLLOW` 普通文件读取、创建即 `0600`、PCM 源路径控制键不传入 Agent SDK等安全边界；未调用外部模板仓库、AI-compatible 服务或 Claude Agent SDK 重新制造 fresh 发布证据。当前工作树还包含未纳入本议题的其它步骤运行参数与测试改动，因此全量结果不能全部归因于本次修改；
- 重试定向覆盖任意 API 状态、明确 `api_error`、SDK 连接/进程异常、普通失败、取消、本地合同错误、内部退出码耗尽归一和瞬时标志不落盘；本次未调用真实外部服务制造故障；
- 第 5 步自动化覆盖当前开发资源 Prompt/决策规则、严格两类 blocked、必要能力/配额/回调/白名单、纯生产与后续内部工作不进入清单、`scope_contract` 拒绝旧语义 success、清单和产品定义漂移及幂等复用；当前真实 run `step05-readiness-v2-20260828-b` 只保留 PostgreSQL/MinIO/SMTP 三项 `ready` 开发资源，完成最终凭据持久化和真实探针、负责人 `completed`、success baseline、状态推进与字节级幂等验证；
- 公共错误诊断覆盖精确凭据遮盖、普通 token 语义保留、异常链与 traceback 位置、稳定有界日志名、OpenAI-compatible provider code/type/message/request ID/HTTP status、Claude Agent SDK `ResultMessage.errors`、BR-002 `api_error` 结果形态，以及第 12～18 步 scoped/protected-success 失败持久化边界；
- 第 18 步覆盖动态仓库白名单、非 root 在前/root 最后、base/tip no-op、部分 merge、逐仓 merged state、全局 cleanup 前置、partial cleanup、result→state、上游增量字段兼容、真实 CLI、失败脱敏、完成状态防降级和 `GIT_*` 过滤；
- 第 17 步现行实现覆盖动态多仓白名单、公共 Agent 决策conversation、`continue/blocked/completed`、同session repair与blocked resume、首次无session失败重投、残缺锚点拒绝、symlink、未跟踪文件、result→state、advanced兼容和CLI blocked/success保护；
- BR-002在旧direct-run路径中缺少decision conversation，该历史不补造；未来第17步运行按现行合同保存完整历史。
- 第 9 步定向 18 项通过（5.498 秒）；第 9～11 步本体共 51 项（18+18+15）通过，公共循环加第 9～11 步本体及第 10/11 步 CLI 的相关回归共 97 项通过（20.800 秒），覆盖完整 conversation 交由公共循环、执行产物 fresh 拒绝、当前 Git 现场核验、blocked 保持 blocked、按需 `/commit-changes`、无 exact prompt/相邻回复成功锚点、result→state 恢复与完整 success 重跑，以及第 10 步无 frontend 的零副作用路径；
- Agent SDK 初始化消息与 ResultMessage 解析；
- 探针权限拒绝；
- Claude session ID 和 AI-compatible 决策历史分别保存与恢复；
- 产品初稿身份提取、模板分支和 SHA 记录、固定模板浅克隆、同级临时目录、原子发布与根仓库零提交初始化；
- 上游 `.git/` 清理、`docs/` 重置、项目内初稿写入和源文件不变；
- 第 1 步配置优先级与路径拒绝、模板已有 `.env`/未忽略拒绝、用户级 global excludes 隔离、任意原始字节写入、`0600`、内容/权限漂移拒绝，以及 clone、prepared、发布或根仓库初始化中断后的现场保留、归属核验和安全恢复；
- 第 2 步目标 Skill、plugins、trust、输入边界、决策循环、产物和恢复；
- 第 3 步 Pydantic 输入输出、`responses.parse` 调用参数、结构化结果直接保存、脱敏失败、真实 API 选型和成功结果复用；
- 第 4 步严格占位保护、run-owned marker、唯一仓库浅 clone、来源 SHA、路径与符号链接边界、无可提交文件拒绝、payload 后发布、`null` 端、失败现场保留、安全重试、部分发布拒绝覆盖、成功幂等复用和普通 Git 错误脱敏；
- 第 4 步专属 12 项与真实 GitLab SSH 组装、远端 `main` SHA 比对、无嵌套 `.git`、临时目录清理、零提交根仓库和黄金初稿哈希不变；
- 第 12 步本体 10 项与 CLI 6 项：自由格式 Backlog prompt 与 Pydantic 字段限制、合法 ID/依赖 ID 及忽略大小写唯一、数组物理顺序对应连续 order、未知/重复/自依赖和环拒绝、非 Git 工作区成功、路径与父级符号链接保护、模型调用期间 SHA 漂移、result→state 中断恢复、两字段 source/catalog/注册表漂移拒绝、旧三字段 source 不受成功保护、失败重跑和失败脱敏；
- 第 13 步本体 20 项与 CLI 10 项：确定性选择、workspace descriptor、fresh 全局预检、intent/partial recovery、scoped result/state 恢复、`GIT_*` 隔离与危险 Git 写操作拒绝、进行中历史拒绝、后续 cycle/注册表字段兼容、旧三字段 `source` 不阻断下一需求、受控错误可见、意外异常脱敏、advanced state 误调不降级、scoped CLI success/failure 保护、原子 JSON 临时文件符号链接边界及真实 Git 仓库分支验证；
- Probe C 和旧四段 XML 回放只作为历史；第 9～11 步旧 fresh 真实运行的五段 prompt、conversation、exact commit 和提交事实也只作为旧合同下的历史路径，不作为新合同验证；
- 第 9～11 步现行新合同尚未按新合同重新执行真实 Claude Agent、负责人 LLM 或 `/commit-changes` 集成；旧真实 run 不构成该集成验证。
- 第 13 步真实 run 已覆盖 BR-001 的确定性选择、scoped result、intent 先写、三仓 clean `req/br-001`、HEAD/main/target 等于记录 base、零产品文件改动/commit/merge/push，以及幂等重跑的 result/state/ref 不变；


### 2. 后续增量风险

进入对应步骤后再增加最小真实验证：

- 第 18 步及后续需求循环复用：代码仓先于 root 的 ff-only 合并、拒绝非 fast-forward、部分合并恢复、分支清理和 completed 时序；第 17 步公共决策conversation、白名单、base/tip、最终clean与恢复边界已完成自动化验证；
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

配置职责：

- `LLM_*` 用于 OpenAI-compatible Responses API，包括 AI-compatible 决策调用和第 12 步 Backlog 静态字段结构化提取；
- `PCM_AGENT_BASE_URL`、`PCM_AGENT_API_KEY` 用于 Claude Agent SDK 的 Anthropic Messages 网关和受保护认证；Base URL 不包含 `/v1`；
- `PCM_AGENT_MODEL_LOW`、`PCM_AGENT_MODEL_MEDIUM`、`PCM_AGENT_MODEL_HIGH` 将代码中的低、中、高档位映射为网关真实模型名；
- `PCM_WORKSPACE_ROOT` 是独立产品项目父目录；
- `PCM_TEMPLATE_REPOSITORY` 只用于第 1 步开发管理模板；
- `PCM_AGENT_WORKSPACE_ENV_FILE` 只用于第 1 步安装 AI Agent 工作区固定工具的受保护根 `.env`；Python 以 `O_NOFOLLOW` 和同一文件描述符读取原始字节，目标从创建时即为 `0600` 并核验 Git 忽略，不解析、导出、记录或传给第 5 步；该 PCM 控制键从 Claude Agent SDK 子进程环境移除；
- `PCM_TEMPLATE_CATALOG` 只用于第 3 步基础工程候选；
- `PCM_DEV_RESOURCE_LIST` 只用于第 5 步可信开发资源清单，必须是可读普通文件的绝对路径；Python 不读取资源内容，Agent 可按项目规则原样使用；
- Claude Agent SDK 每次调用显式使用 `AgentConfig` 解析后的网关、API Key、模型和 effort；冲突的宿主认证被压住，`CLAUDE_CODE_SUBAGENT_MODEL` 与主模型同步，不再依赖既有登录态选择模型或网关。

优先级：

- `--workspace-root` 可覆盖 `PCM_WORKSPACE_ROOT`；
- 第 3 步未来的 `--catalog-path` 可覆盖 `PCM_TEMPLATE_CATALOG`；
- 两者优先级均为 CLI、进程环境、`pcm-demo/.env`；
- `PCM_DEV_RESOURCE_LIST` 由进程环境或 `pcm-demo/.env` 提供，不设置单次 CLI 覆盖；
- `PCM_AGENT_WORKSPACE_ENV_FILE` 由进程环境或 `pcm-demo/.env` 提供，必须是绝对、可读、非符号链接、非空普通文件，不设置单次 CLI 覆盖；
- `PCM_TEMPLATE_REPOSITORY` 单次运行不可覆盖。

`pcm-demo/.env` 是编排器自身配置；产品工作区内的实际 `.env` 或等价配置由项目准备和项目化合同维护。两类实际配置都必须被所属仓库 Git 忽略；对应 `.env.example` 或公开示例只保存配置键、公开默认值、安全占位和不含秘密的用法说明。产品工程在项目化中允许环境变量改名和配置结构迁移，但必须保持同一资源身份、endpoint、权限范围和秘密值。

日志不得记录：

- API Key、token、密码或完整认证头；
- `.env` 具体值；
- 含秘密的命令行和工具输入；
- 无助于恢复的完整模型上下文；
- 客户私有数据、生产数据或不必要的真实身份信息。

## 十三、当前未决事项

以下事项在进入对应步骤前解决，暂不臆定答案：

1. Agent SDK、捆绑 Claude Code 或模型版本变化时，需重新记录并复核相关探针；
2. `/project-intake`、`/project-readiness`、`/project-bootstrap` 和 `/solution-design` 已有真实调用证据；第 6 步新增的独立 `/tailwind-theme` session、init 发现、真实 light/dark 修改和浏览器验证仍需在隔离 fresh run 中验证；其它目标 Skill 的实际调用名、参数、plugin namespace 和 init 发现结果继续逐步验证；
3. 阶段二具名节点如何增量接入已实现的 `run_all.py` 阶段一入口；
4. 第二个真实需求复用第 13～18 步时是否暴露新的最小恢复边界；
5. 阶段二真实浏览器通道、测试身份、可复位数据、截图读取、辅助技术路径和外部审查能力；
6. 阶段二审计结果、候选分流、入池和原发现回归证据的最小持久化格式；
7. 相同 `version_fingerprint` 的恢复、不同指纹的完整复审以及避免无穷循环的确定性边界。

这些未决事项不改变第 0～18 步已经完成的真实事实，也不重新打开本轮已实现的第 12～18 步合同。后续需求继续以当前流程设计、当前活动 TRD、对应实现和测试事实确认实现级输入、输出、失败、阻塞和恢复细节，随后先实现代码并通过测试和真实验证，再将实际实现同步到设计文档并提交。
