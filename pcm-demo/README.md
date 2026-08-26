# PCM 自动化流程 Demo

这是 PCM 自动化流程的本地验证工具。

## 当前步骤

- [第 0 步：形成产品初稿](steps/step_00_product_draft/README.md)
- [第 1 步：建立项目工作区](steps/step_01_create_workspace/README.md)
- [第 2 步：项目需求与产品定义](steps/step_02_project_intake/README.md)
- [第 3 步：基础工程选型](steps/step_03_foundation_selection/README.md)
- [第 4 步：组装基础工程](steps/step_04_assemble_foundation/README.md)
- [第 5 步：核验项目准备状态](steps/step_05_project_readiness/README.md)
- [第 6 步：项目化基础工程](steps/step_06_project_bootstrap/README.md)
- [第 7 步：总体技术方案](steps/step_07_solution_design/README.md)
- [第 8 步：首次提交适用仓库](steps/step_08_initialize_repositories/README.md)
- [第 9 步：工程架构设计](steps/step_09_engineering_architecture/README.md)
- [第 10 步：产品级 UI/UX 框架](steps/step_10_ui_ux_framework/README.md)
- [第 11 步：拆分 Backlog](steps/step_11_requirement_breakdown/README.md)
- [第 12 步：解析 Backlog 并初始化需求注册表](steps/step_12_initialize_requirement_registry/README.md)
- [第 13 步：选择需求并建立统一需求分支](steps/step_13_select_requirement/README.md)
- [第 14 步：形成活动 TRD](steps/step_14_trd_design/README.md)
- [第 15 步：实现与验证](steps/step_15_development/README.md)
- [第 16 步：规则复盘](steps/step_16_rule_retrospective/README.md)
- [第 17 步：统一提交需求变更](steps/step_17_commit/README.md)
- [第 18 步：程序化合并并完成需求](steps/step_18_merge/README.md)

每个步骤的业务代码、测试和详细运行说明都在对应步骤目录中。根 README 只提供导航。

## 统一测试

在 `pcm-demo/` 目录执行：

```bash
uv sync
uv run python -m unittest discover -s . -t . -p 'test*.py' -v
```

第 17 步现行精简实现本体 10 项与 CLI 3 项，共 13 项；第 18 步本体 10 项与 CLI 5 项，共 15 项。PCM Demo 全量 294 项 `unittest` 通过，`compileall common steps run_step.py` 与 `git diff --check` 通过。第 17 步直接调用 `run_claude()`，不再使用工作树 fingerprint、Git 内容取证或 AI-compatible 负责人决策；第 18 步只使用确定性 Python/Git 完成 ff-only 合并、恢复、分支清理和需求状态更新。独立只读审查最终无第 14、17 或 18 步高、中置信发现。第 9～11 步现行新合同的真实 Agent 集成仍待后续单独验证，旧真实 run 继续只作为旧合同历史。

## 最近真实验证

第 9～11 步下述 exact commit prompt、conversation 条数、提交和 `commit-changes` 发现文档矛盾的叙述，均是**旧合同下的历史运行事实/当时执行路径**，保留作排障和演进依据，不是当前成功条件。现行新合同以严格 result schema、固定文档和当前 Git 事实判定 success；验证正在进行。

隔离 run `agent-loop-step7-20260822T190149Z` 已真实验证公共循环的第 7 步路径：初次环境内部 Explore 子代理模型错误超时后保留 session 与初始对话；仅在隔离历史追加普通 assistant 提示后从同一 session 恢复，完成正常 `success`、两次 `completed` 裁决和固定方案文档补完核验，最终推进到第 8 步。隔离副本未修改既有 `step01-mendmark`；该测试提示和文档置空 failpoint 均不属于生产代码或生产 prompt。

Probe C 的早期成功证据保留于 `probe-c-20260822T185623Z`，后续格式重试结果均为旧合同历史。现行 `request_decision` 使用五段 XML system prompt、一次 `responses.parse` 和 Pydantic `AgentDecision`，没有公共默认、隐藏追加 prompt 或格式重试；该合同已经由第 9 步 fresh 真实运行和合法最终 JSON decision 验证。

第 8 步首个真实 run `step08-real-20260823-a` 是**旧“唯一初始提交证明”合同**下的失败历史：第 1 步依次出现代码围栏、Responses `incomplete`、自创字段，收紧严格 JSON prompt 后同 run 成功；第 3 步一次 `ValidationError` 后同 run 重试成功；第 7 步 API 500 暴露 failed `07.json` 错误阻断恢复，修正为只有 `status=success` 才复用后同 session 成功。第 8 步因模板快照的 `.coverage` 成为根仓未跟踪垃圾，Agent 未提交，而决策模型重复索取调用方授权并耗尽 8 轮；该 run 未产生任何三仓提交。

`step08-real-20260823-b` 同样是旧合同下的历史成功事实：第 6 步真实清除 `.coverage` 后，session `64aa707c-268c-48c8-bb3f-f67f62abe75e` 以一轮 Agent 回复和一轮 `completed` 裁决产生 root、frontend、backend 三个提交（分别为 `c1eb33dfa5bda91a0d7f9aeeb41d8fefe10a6fca`、`5997213c34c09ea6ba4e740e35f9df77d2d45d82`、`5d8dd95d8c42370697d25e6ecaf400bab42785b3`），并推进到 `project:09_engineering_architecture`。这些 SHA、提交形态和当时重跑事实不再是当前第 8 步完成条件。

第 8 步当前合同已在真实 run `pcm-demo/runs/step01-mendmark` 和产品工作区 `/Users/zhou/resource/fireworks/ANDRSZAN/pcm-products/mendmark` 完成集成验证；run 目录名与 state 内历史 `run_id` 不一致是既有已知事实。权威仓库为 `root/frontend/backend`，第 4 步 `outputs` 为 `frontend/backend`；首次执行前三仓均为自身 top-level、`main`、dirty 且 HEAD 不存在。

首次执行只启动 `initialize_repositories` session `f6d42df8-13e5-437b-ada3-eef1015ecc87`。Agent 尝试内置 Explore 时遇到环境未识别模型 `gpt-5.6-sol[1m]`，无 Result、无 Git 变化，挂起进程停止后保留了 session、conversation 和 init 证据；这是环境内部子代理问题，不是第 8 步业务或 Git 逻辑失败。仅在该 Git 忽略 run 历史中追加普通恢复指令“不要使用子代理/Explore，直接工具完成”，生产 prompt 和代码未改变，并恢复同一 session。

恢复后 Agent 创建 frontend `dbab574dbe4d83a02323a750afd04de007565ac5`、backend `9682be837759c20f1a9ebbdf8fa2cfc09c2768d4` 两个本地提交；随后针对根仓运行时产物和 `.agents/plugins/superpowers/.git` 请求决策。AI-compatible 负责人返回 `continue`，授权删除 61 个 `.in_use/*`、`.orphaned_at`、`.coverage` 运行时产物、补 `.gitignore`、移除嵌套 `.git` 并将 superpowers 作为普通受控插件快照而非 submodule 提交。root 最终创建 `02ba4c1`、`ae72c31`、`5eeeacd217bbd27e03483b1b6d32915c721aadd9` 三个本地提交；全程未 push。

最终 conversation 共 7 条：`system → assistant 初始 → assistant 恢复 → user → assistant continue → user → assistant completed`。Agent 正常 `success`，26 turns，约 `$1.859406`，session 不变。Python 只读 verifier 写入 `steps/08.json` success，以 result 相对路径、state 绝对路径保存 `root/frontend/backend` 并推进到 `project:09_engineering_architecture`。独立 Git 核验确认 root 为 3 commits、frontend/backend 各 1 commit，三仓均在 `main` 且 clean；当前合同因此允许每仓 0、1 或多个提交，不要求唯一无父提交。同 run 重跑直接 clean 幂等成功，conversation 仍为 7 条，未再次调用 Agent 或决策模型，SHA 不变。

backend 提交摘要中的 Ruff、格式、build 通过和 `pytest` 14 passed、1 skipped（数据库集成测试需显式 `DB_*`）是 Agent 报告，不是本次 Python verifier 条件，也不改变第 6 步历史项目化验证。`step08-real-20260823-a/b` 继续仅作为旧“唯一初始提交证明”合同历史，不再用于说明当前合同尚未真实联调；本次首次成功包含 run-local 恢复指令，不能宣称环境内部子代理问题已经解决或无需恢复。

第 9 步以下代码、自动化和真实验收均为旧合同下的历史事实。旧失败历史包括账号 free quota / `use free tier only` 导致的 HTTP 403、服务恢复后返回非 JSON 普通文本，以及 `completed` 携带非空 `answer`；最终根因定位为旧 `render_decision_system_prompt` 将步骤规则混入 responsibility、硬编码并重复 completion 语义且缺少独立 output。用户将公共 prompt 重构为 `role/project_context/responsibility/completion/output` 五段，补齐 f-string JSON 花括号转义和 `AgentDecision` 字段组合约束，并同步 common 与第 2/5/6/7/9 步测试。

按用户要求两次清理第 9 步局部 result、conversation、session、private state 和失败生成的未跟踪架构文档后，保留第 0～8 步历史与三仓提交并执行 fresh 运行。最终唯一 session 为 `f41fc439-4c46-434f-b3e9-d15c18c89601`，conversation 共 11 条：`system → assistant 初始 → user → assistant continue → user → assistant completed → assistant commit prompt → user → assistant continue → user → assistant completed`。首轮 Agent 请求确认后，负责人合法 `continue` 要求创建固定文档；Agent 创建约 32 KB 文档，只有根仓固定文档 dirty；负责人 `completed` 后 verifier 同 session 发送固定 `/commit-changes`。

commit-changes 执行轮发现文档中的 frontend Git 事实矛盾，严格未修改、未暂存、未提交并报告。外层负责人随后通过普通 `continue` 授权通用 Claude Agent 仅修正固定文档并提交；Agent 精确完成。产品根提交为 `ead14dffe19bc6417634c24c7bb1103602c3b772`，message `docs: 新增工程架构设计`，仅新增 `docs/design/工程架构设计.md`，376 行、32928 字节；未 push，frontend/backend 无变化。最终严格 JSON decision 为 `completed`，`steps/09.json` 为 success，state 推进到 `project:10_ui_ux_framework`。

独立核验确认 root/frontend/backend 均为自身 top-level、`main`、clean，固定文档 tracked。同 run 幂等重跑后 conversation 仍为 11 条，session 和 root HEAD 不变，没有再次调用 Agent、决策服务或产生新提交。`run_step.py` 对第 8～12 步 schema 完整 success 保持固定保护；第 13 步只保护当前 active/cycle 的完整 scoped success，失败或残缺 scoped result 可以重跑恢复。

第 10 步以下代码、自动化和真实验收均为旧合同下的历史事实。`step01-mendmark` 的第 8 步权威仓库为 `root/frontend/backend`，故适用；session `2d052d9a-b9fd-4fcd-b5f9-ff724f25dbc1` 正常完成（5 turns、`$3.207112`、7 条 conversation、固定 commit prompt 恰好一次）。fresh 调用中内置 Explore 子代理曾输出未识别模型 `gpt-5.6-terra[1m]` 警告，但主 Agent 同一次调用继续并 success，未追加人工或 run-history 恢复提示。产品根提交 `0ceee1bb8b5836f64112ded0c8fd3cf7fbd1f29c` 仅新增 206 行、25580 字节的 `docs/ui-ux/framework.md`，未 push；root/frontend/backend 均为自身 top-level、`main`、clean。`steps/10.json` 是 `applicable: true` 的唯一固定输出 success；其后第 11 步已经消费该严格交接。幂等重跑不增加 conversation、提交或 Agent/决策调用，session、root HEAD 与前后端 SHA 均不变；不适用路径仅有自动化覆盖。

第 11 步以下同一真实 run 与产品工作区验证为旧合同下的历史事实。运行前旧 `requirement-breakdown` Skill 已按新合同精确同步，并以真实 `/commit-changes` 单独提交 `9263d28`（只改 Skill、未 push、三仓 clean）；它是测试前置，不是步骤输出。session `af7d198c-b090-44d8-9d92-ae0738150854` 的 init 确认 Skill/slash command、产品根 cwd、Fable 5、Claude Code 2.1.233 和 `bypassPermissions`。fresh 调用的内置 Explore 子代理有未识别模型 `gpt-5.6-terra[1m]` 警告，但主 Agent 同次 success；首次生成 Result 为 15 turns、`$5.789825`。生成的 `docs/backlog/backlog.md` 约 59,140 字节、约 1,110 行，含 14 项 BR 需求，完整覆盖 E.1、未自动纳入 E.2/E.3，首条验证切片为完整的 BR-001～BR-006；文档没有需求开发状态列或字段，业务状态保留。

负责人 Responses 决策曾三次在正常 run 后瞬时写入 failed；两次独立同上下文只读诊断虽得到合法 `completed`，均未注入正式 conversation。依靠正常原节点重跑恢复，未添加自定义 HTTP 重试或修改生产 prompt。最终 conversation 为 7 条：`system → assistant 初始 → user 生成回复 → assistant completed → assistant exact commit prompt → user 提交回复 → assistant completed`，exact commit 恰好一次且使用同一 session。产品根未 push 提交 `2aaa743a97d96fe93deaaaaa13a94e4c414369a2`（`docs: 建立 MendMark 首版正式 Backlog`）仅新增 Backlog，frontend/backend SHA 不变；三仓均在 `main` 且 clean。该历史 `steps/11.json` success 当时进入旧 `phase_1:select_requirement` / step 12 占位入口。

第 12 步旧合同真实运行前曾严格核验旧 state：第 11 步 strict success、`active_requirement` 与 `requirement_cycle` 均为 `null`、无 `requirement_registry`、无 `steps/12.json`，root/frontend/backend 均为自身 top-level、`main`、clean。仅在 run-local 将 `current_node` 从旧入口规范化为 `phase_1:initialize_requirement_registry`；生产代码未添加 legacy 兼容。该现场、旧三字段 `source` 与 root `main` SHA 仅作为历史证据保留。

第 12 步现行合同不解析 Markdown 总览、表格、详情卡或标题层级，也不读取 Git。它将整份自由格式 Backlog 交给 Responses/Pydantic 作为唯一语义提取路径；Python 只校验非空 catalog、合法且忽略大小写唯一的 ID、数组物理顺序对应连续 `order`、依赖存在/不重复/不自依赖/无环，并以 Backlog `path + sha256` 作为来源。模型调用前后的 SHA 漂移、result→state 恢复和 pending 注册表保持确定性。

新合同真实隔离 run `step12-ai-only-20260826` 使用无 Git 工作区和没有总览表、详情卡或固定标题层级的自然语言 Backlog。真实 Responses 准确提取 `BR-AI-001`～`BR-AI-003`，标题、顺序和显式依赖均正确，并排除 `NOTE-001` 示例和在线支付未来设想；注册表全部为 `pending`、`completion: null`，source 仅含路径与 SHA-256。以不可连接的 LLM 配置幂等重跑仍 success，result/state 字节不变。第 12 步 16 项、第 12～14 步定向 61 项、全量 282 项 `unittest`、`compileall` 与目标 IDE diagnostics 均通过。

第 13 步初次真实运行以零 AI、零 Agent、零 Skill 的确定性路径选择 `BR-001` 并建立三仓 `req/br-001`。第 14 步开始前，用户将新的 TRD 命名规则提交到产品 root，使 root `main` 和旧需求分支前进到 `a7d5509df6843a06315aa803d87285569b86e355`。经用户明确选择，先完整归档旧 run 现场，确认三仓旧需求分支均无独有提交后安全删除，只重置 BR-001 的第 13 步 cycle/result 并从最新 `main` 重跑。当前 cycle bases 为 root `a7d5509df6843a06315aa803d87285569b86e355`、frontend `dbab574dbe4d83a02323a750afd04de007565ac5`、backend `9682be837759c20f1a9ebbdf8fa2cfc09c2768d4`；三仓随后进入 clean `req/br-001`，没有需求实现提交、merge 或 push。

第 14 步现行实现采用与第 15 步一致的薄编排：只消费当前 active requirement、cycle 和 workspace，首次持久化唯一 `trd_path`，再通过 requirement-scoped 公共循环显式调用或恢复 `/trd-design`。Agent 按需读取项目资料和代码，Python只核验指定 TRD 非空；不读取 Git，不重复复验第 2～13 步结果、上游文档 tracked 状态、分支/base 或公共 conversation 内部结构。success 先写 scoped `14.json`，再推进 `requirement:15_development`。

第 14 步已在同一真实 run 完成。Python 在首次 Agent 调用前持久化 `docs/trd/2026-08-25-BR-001-身份、角色访问与站内消息入口.md`，并把同一路径放入 `/trd-design` 初始 prompt。唯一 Claude session 为 `b9ed4756-0acf-4666-b3f9-c8f3628c03f1`；首次负责人错误接受实现门槛后，同一 session 收敛 8 项决定。第二次 Agent success 后负责人服务因 free quota HTTP 403 保留 conversation 尾部 Agent 回复；额度恢复后原节点裁决为合法 `completed`。最终 conversation 为 7 条且没有 `/commit-changes`。当时 root 只有唯一未跟踪 TRD、frontend/backend clean、三仓 refs 等于 base，是旧实现结束时的历史现场，不再是现行 success 条件，也不会由现行代码重复核验；既有活动 TRD、result、state、conversation 和产品 Git 现场保持不变。

第 15 步已在同一真实 run 完成。它只消费当前 active requirement/cycle/workspace、当前需求 scoped 第 14 步 success 和非空活动 TRD，不读取第 2/5/7/8/9/10/11/13 步文档，不执行 Git 或 Git verifier。`development_<ID>` 复用公共 Agent 决策循环；prompt 只给 `/dev-workflow`、需求 ID/标题和活动 TRD 路径，Agent 按需读取项目现场并可同步稳定 TRD 偏差，但不得修改 `.claude/rules/` 或执行 stage/commit/branch/merge/push。负责人最终 `completed` 即领域完成，success result 写入 `steps/requirements/BR-001/15.json`（`outputs: []`，保存需求、TRD 与 development session），并推进 `requirement:16_rule_retrospective` / step 16；BR-001 仍为 active/completion null。

唯一 development session 为 `e6bd1b82-39f9-41b2-9cc9-a69b281015dc`，Fable 5、Claude Code 2.1.233、`bypassPermissions`，最终正常 success 为 23 turns、约 `$9.784016`。首次调用在 init/session 已保存后暴露 `claude-agent-sdk` 0.2.139 单条 CLI stdout JSON 默认 1 MiB 缓冲的 `JSON message exceeded maximum buffer size`；公共 `ClaudeAgentOptions` 固定增至 10 MiB 后从同一 session 恢复，保留已有产品改动且不影响 resume。自定义 dev/reviewer 子代理曾有未识别 model 警告和一个子进程退出，但主 Agent 继续完成，生产 prompt 未改。最终 conversation 9 条，负责人先要求补齐 Firefox/WebKit 验证后最终 completed。Agent 报告后端 Ruff/format/build、pytest 16 passed 1 skipped、真实 PostgreSQL 与 Alembic 往返迁移；前端 lint/type-check/build、Vitest 15 passed；Chromium/Firefox/WebKit Playwright 矩阵 3 passed，以及真实 FastAPI/PostgreSQL/Vite 浏览器联调、截图读取和独立审查。Windows NVDA 和 macOS VoiceOver 人工路径 deferred，负责人判为非阻断。root 保留活动 TRD和代表性截图未跟踪，frontend/backend 保留实现、测试、迁移与配置的未提交变更；三仓均为 `req/br-001`、index clean，无 commit、merge 或 push。不可用 LLM 配置幂等重跑仍 success，state/result/conversation 字节不变，SHA-256 分别为 `069b50dc583d8472683eded457bdb954265e37000b78c59860986bc8ea15bf72`、`033585fb8c7b2a43937dd67082aec8a179cc368ede869c460df4300a438487a2`、`431972a5bb43f90af90adf557bc1b92adab3599a5adb11a5696f57167a100e19`。第 16～18 步随后均已完成实现与适用真实验证。
Git 忽略 run `prompt-role-replay-20260823` 保留旧四段 XML prompt 的历史交接回放；它不是现行五段 prompt 的证据。现行 `role/project_context/responsibility/completion/output` 合同已由第 9 步 fresh 真实运行验证。

## 第 16 步真实验证

`step01-mendmark` 的首次第 16 步调用在 baseline、session alias 和 Agent 前失败：root、frontend、backend 的 `req/br-001` 分别已有提前提交 `8e44a6ebefda27fbdf1c79a4a53817918c3c3c95`、`4ea14479455cc137815356edfb985680d2973f82`、`1236b9cb533259eaecb23e6d0345d0a9797f8444`，与 cycle bases `a7d5509df6843a06315aa803d87285569b86e355`、`dbab574dbe4d83a02323a750afd04de007565ac5`、`9682be837759c20f1a9ebbdf8fa2cfc09c2768d4` 冲突。每仓 `main..branch` 恰有一个 commit，无反向分叉或远端包含；没有 retrospective conversation 或产品变化。

用户明确选择按合同将三仓 `git reset --mixed <cycle base>`，保留完整工作树且 index clean，并独立核验工作树与旧 tip 文件树一致；这是 run-local 现场恢复，不是生产代码对提前提交的兼容。恢复后第 16 步复用 development session `e6bd1b82-39f9-41b2-9cc9-a69b281015dc`，以同 ID 预注册 retrospective alias，Agent normal success（8 turns、`$6.9324520000000005`、`terminal_reason=completed`），conversation 为 `system → assistant 初始 → user Agent 回复 → assistant completed`。唯一规则增量为 root `.claude/rules/frontend-playwright-container.md`：官方 Playwright 容器绑定 frontend 时使用临时 `node_modules` volume 和临时 `.pnpm-store`，结束后不留 `.pnpm-store` 或测试缓存。

最终 `16.json` success、`outputs: []`，state 进入 `phase_1_requirement_development` / `requirement:17_commit` / step 17；BR-001 仍 active/completion null。root 保留 TRD、截图和规则未提交，frontend/backend 保留实现未提交，三仓均在 `req/br-001`、`HEAD`/`main`/target 等于 base、index clean。不可用 LLM 配置的幂等重跑仍 success，未调用模型或 Agent，关键 state、result、conversation 和规则文件字节不变；详细合同和 SHA-256 见[第 16 步 README](steps/step_16_rule_retrospective/README.md)。

## 第 17 步历史真实验证与现行兼容

历史真实 run 曾使用 session `a00760f3-1760-4e2c-a985-477831a9277f` 创建 root 2 个、frontend 1 个、backend 1 个本地提交，并推进到 `requirement:18_merge` / step 18。提交 SHA、session、四条 decision conversation 和当时的 fingerprint 字段是旧实现的历史执行事实，不再是现行精简合同的完成条件。

现行实现只保留仓库白名单、统一需求分支、local main/base、最终 clean、单一 direct session 和 base/tip 持久化；每次运行最多调用一次 Agent，不调用负责人模型或自动 repair。当前真实 run 没有回退重跑 fresh 提交，只执行 advanced 幂等兼容验证：使用不可用 LLM 配置运行第 17 步时不调用 Agent，state、`17.json` 和旧 conversation SHA-256 分别保持 `aa591d02093ec29d9b4ec2b7d06dfd4e1aac22a2097a19d864fb07e47a15512e`、`2f76b43287404bc828e1dfbe9df52a90fd53b3a388eaf36f3e7c54cc82fb8439`、`93978ff7dcdfa3479d094f0085807bae2166b3dbaffdf1c69c3973d096fc9d87`。详细合同见[第 17 步 README](steps/step_17_commit/README.md)。

## 第 18 步真实验证

`step01-mendmark` 以纯 Python/Git 执行非 root 在前、root 最后的 ff-only 合并。frontend、backend、root 的 local `main` 分别前进到 `65764dee0b2655f1c674ec36fee527861ea5043c`、`0e0bf9bb37e2abcf8c923c0fa4611c671da87640`、`62ac0aea0a69ea95d6382adfc276adce808be964`；三仓当前均在 `main`、工作树/index clean、`req/br-001` 已删除，`base..tip` 无 merge commit且未 push。

scoped `18.json` 保存与第 17 步一致的 root-first base/tip 结果；BR-001 已更新为 `completed`、`completion: {"step": 18}`，`active_requirement` 与 `requirement_cycle` 均已清空，state 返回 `phase_1:select_requirement` / step 13。详细合同见[第 18 步 README](steps/step_18_merge/README.md)。
