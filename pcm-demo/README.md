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

每个步骤的业务代码、测试和详细运行说明都在对应步骤目录中。根 README 只提供导航。

## 统一测试

在 `pcm-demo/` 目录执行：

```bash
uv sync
uv run python -m unittest discover -s . -t . -p 'test*.py' -v
```

该入口从 `pcm-demo/` 根递归发现 `common/` 与 `steps/` 测试。第 12 步本体 11 项与 CLI 6 项，共 17 项；第 13 步本体 19 项与 CLI 9 项，共 28 项；两步定向共 45 项、全量 222 项均已通过。`compileall`、`git diff --check` 通过；IDE 对第 12、13 步和 `run_step.py` 无诊断，独立审查的 3 项中置信问题已修复，复核无高、中置信发现。Ruff 未安装，未执行 Ruff。

## 最近真实验证

隔离 run `agent-loop-step7-20260822T190149Z` 已真实验证公共循环的第 7 步路径：初次环境内部 Explore 子代理模型错误超时后保留 session 与初始对话；仅在隔离历史追加普通 assistant 提示后从同一 session 恢复，完成正常 `success`、两次 `completed` 裁决和固定方案文档补完核验，最终推进到第 8 步。隔离副本未修改既有 `step01-mendmark`；该测试提示和文档置空 failpoint 均不属于生产代码或生产 prompt。

Probe C 的早期成功证据保留于 `probe-c-20260822T185623Z`，后续格式重试结果均为旧合同历史。现行 `request_decision` 使用五段 XML system prompt、一次 `responses.parse` 和 Pydantic `AgentDecision`，没有公共默认、隐藏追加 prompt 或格式重试；该合同已经由第 9 步 fresh 真实运行和合法最终 JSON decision 验证。

第 8 步首个真实 run `step08-real-20260823-a` 是**旧“唯一初始提交证明”合同**下的失败历史：第 1 步依次出现代码围栏、Responses `incomplete`、自创字段，收紧严格 JSON prompt 后同 run 成功；第 3 步一次 `ValidationError` 后同 run 重试成功；第 7 步 API 500 暴露 failed `07.json` 错误阻断恢复，修正为只有 `status=success` 才复用后同 session 成功。第 8 步因模板快照的 `.coverage` 成为根仓未跟踪垃圾，Agent 未提交，而决策模型重复索取调用方授权并耗尽 8 轮；该 run 未产生任何三仓提交。

`step08-real-20260823-b` 同样是旧合同下的历史成功事实：第 6 步真实清除 `.coverage` 后，session `64aa707c-268c-48c8-bb3f-f67f62abe75e` 以一轮 Agent 回复和一轮 `completed` 裁决产生 root、frontend、backend 三个提交（分别为 `c1eb33dfa5bda91a0d7f9aeeb41d8fefe10a6fca`、`5997213c34c09ea6ba4e740e35f9df77d2d45d82`、`5d8dd95d8c42370697d25e6ecaf400bab42785b3`），并推进到 `project:09_engineering_architecture`。这些 SHA、提交形态和当时重跑事实不再是当前第 8 步完成条件。

第 8 步当前合同已在真实 run `pcm-demo/runs/step01-mendmark` 和产品工作区 `/Users/zhou/resource/fireworks/ANDRSZAN/pcm-products/mendmark` 完成集成验证；run 目录名与 state 内历史 `run_id` 不一致是既有已知事实。权威仓库为 `root/frontend/backend`，第 4 步 `outputs` 为 `frontend/backend`；首次执行前三仓均为自身 top-level、`main`、dirty 且 HEAD 不存在。

首次执行只启动 `initialize_repositories` session `f6d42df8-13e5-437b-ada3-eef1015ecc87`。Agent 尝试内置 Explore 时遇到环境未识别模型 `gpt-5.6-sol[1m]`，无 Result、无 Git 变化，挂起进程停止后保留了 session、conversation 和 init 证据；这是环境内部子代理问题，不是第 8 步业务或 Git 逻辑失败。仅在该 Git 忽略 run 历史中追加普通恢复指令“不要使用子代理/Explore，直接工具完成”，生产 prompt 和代码未改变，并恢复同一 session。

恢复后 Agent 创建 frontend `dbab574dbe4d83a02323a750afd04de007565ac5`、backend `9682be837759c20f1a9ebbdf8fa2cfc09c2768d4` 两个本地提交；随后针对根仓运行时产物和 `.agents/plugins/superpowers/.git` 请求决策。AI-compatible 负责人返回 `continue`，授权删除 61 个 `.in_use/*`、`.orphaned_at`、`.coverage` 运行时产物、补 `.gitignore`、移除嵌套 `.git` 并将 superpowers 作为普通受控插件快照而非 submodule 提交。root 最终创建 `02ba4c1`、`ae72c31`、`5eeeacd217bbd27e03483b1b6d32915c721aadd9` 三个本地提交；全程未 push。

最终 conversation 共 7 条：`system → assistant 初始 → assistant 恢复 → user → assistant continue → user → assistant completed`。Agent 正常 `success`，26 turns，约 `$1.859406`，session 不变。Python 只读 verifier 写入 `steps/08.json` success，以 result 相对路径、state 绝对路径保存 `root/frontend/backend` 并推进到 `project:09_engineering_architecture`。独立 Git 核验确认 root 为 3 commits、frontend/backend 各 1 commit，三仓均在 `main` 且 clean；当前合同因此允许每仓 0、1 或多个提交，不要求唯一无父提交。同 run 重跑直接 clean 幂等成功，conversation 仍为 7 条，未再次调用 Agent 或决策模型，SHA 不变。

backend 提交摘要中的 Ruff、格式、build 通过和 `pytest` 14 passed、1 skipped（数据库集成测试需显式 `DB_*`）是 Agent 报告，不是本次 Python verifier 条件，也不改变第 6 步历史项目化验证。`step08-real-20260823-a/b` 继续仅作为旧“唯一初始提交证明”合同历史，不再用于说明当前合同尚未真实联调；本次首次成功包含 run-local 恢复指令，不能宣称环境内部子代理问题已经解决或无需恢复。

第 9 步代码、自动化和真实验收均已完成。旧失败历史包括账号 free quota / `use free tier only` 导致的 HTTP 403、服务恢复后返回非 JSON 普通文本，以及 `completed` 携带非空 `answer`；最终根因定位为旧 `render_decision_system_prompt` 将步骤规则混入 responsibility、硬编码并重复 completion 语义且缺少独立 output。用户将公共 prompt 重构为 `role/project_context/responsibility/completion/output` 五段，补齐 f-string JSON 花括号转义和 `AgentDecision` 字段组合约束，并同步 common 与第 2/5/6/7/9 步测试。

按用户要求两次清理第 9 步局部 result、conversation、session、private state 和失败生成的未跟踪架构文档后，保留第 0～8 步历史与三仓提交并执行 fresh 运行。最终唯一 session 为 `f41fc439-4c46-434f-b3e9-d15c18c89601`，conversation 共 11 条：`system → assistant 初始 → user → assistant continue → user → assistant completed → assistant commit prompt → user → assistant continue → user → assistant completed`。首轮 Agent 请求确认后，负责人合法 `continue` 要求创建固定文档；Agent 创建约 32 KB 文档，只有根仓固定文档 dirty；负责人 `completed` 后 verifier 同 session 发送固定 `/commit-changes`。

commit-changes 执行轮发现文档中的 frontend Git 事实矛盾，严格未修改、未暂存、未提交并报告。外层负责人随后通过普通 `continue` 授权通用 Claude Agent 仅修正固定文档并提交；Agent 精确完成。产品根提交为 `ead14dffe19bc6417634c24c7bb1103602c3b772`，message `docs: 新增工程架构设计`，仅新增 `docs/design/工程架构设计.md`，376 行、32928 字节；未 push，frontend/backend 无变化。最终严格 JSON decision 为 `completed`，`steps/09.json` 为 success，state 推进到 `project:10_ui_ux_framework`。

独立核验确认 root/frontend/backend 均为自身 top-level、`main`、clean，固定文档 tracked。同 run 幂等重跑后 conversation 仍为 11 条，session 和 root HEAD 不变，没有再次调用 Agent、决策服务或产生新提交。`run_step.py` 对第 8～12 步 schema 完整 success 保持固定保护；第 13 步只保护当前 active/cycle 的完整 scoped success，失败或残缺 scoped result 可以重跑恢复。

第 10 步代码、自动化和真实验收已完成。`step01-mendmark` 的第 8 步权威仓库为 `root/frontend/backend`，故适用；session `2d052d9a-b9fd-4fcd-b5f9-ff724f25dbc1` 正常完成（5 turns、`$3.207112`、7 条 conversation、固定 commit prompt 恰好一次）。fresh 调用中内置 Explore 子代理曾输出未识别模型 `gpt-5.6-terra[1m]` 警告，但主 Agent 同一次调用继续并 success，未追加人工或 run-history 恢复提示。产品根提交 `0ceee1bb8b5836f64112ded0c8fd3cf7fbd1f29c` 仅新增 206 行、25580 字节的 `docs/ui-ux/framework.md`，未 push；root/frontend/backend 均为自身 top-level、`main`、clean。`steps/10.json` 是 `applicable: true` 的唯一固定输出 success；其后第 11 步已经消费该严格交接。幂等重跑不增加 conversation、提交或 Agent/决策调用，session、root HEAD 与前后端 SHA 均不变；不适用路径仅有自动化覆盖。

第 11 步已在同一真实 run 与产品工作区完成验证。运行前旧 `requirement-breakdown` Skill 已按新合同精确同步，并以真实 `/commit-changes` 单独提交 `9263d28`（只改 Skill、未 push、三仓 clean）；它是测试前置，不是步骤输出。session `af7d198c-b090-44d8-9d92-ae0738150854` 的 init 确认 Skill/slash command、产品根 cwd、Fable 5、Claude Code 2.1.233 和 `bypassPermissions`。fresh 调用的内置 Explore 子代理有未识别模型 `gpt-5.6-terra[1m]` 警告，但主 Agent 同次 success；首次生成 Result 为 15 turns、`$5.789825`。生成的 `docs/backlog/backlog.md` 约 59,140 字节、约 1,110 行，含 14 项 BR 需求，完整覆盖 E.1、未自动纳入 E.2/E.3，首条验证切片为完整的 BR-001～BR-006；文档没有需求开发状态列或字段，业务状态保留。

负责人 Responses 决策曾三次在正常 run 后瞬时写入 failed；两次独立同上下文只读诊断虽得到合法 `completed`，均未注入正式 conversation。依靠正常原节点重跑恢复，未添加自定义 HTTP 重试或修改生产 prompt。最终 conversation 为 7 条：`system → assistant 初始 → user 生成回复 → assistant completed → assistant exact commit prompt → user 提交回复 → assistant completed`，exact commit 恰好一次且使用同一 session。产品根未 push 提交 `2aaa743a97d96fe93deaaaaa13a94e4c414369a2`（`docs: 建立 MendMark 首版正式 Backlog`）仅新增 Backlog，frontend/backend SHA 不变；三仓均在 `main` 且 clean。该历史 `steps/11.json` success 当时进入旧 `phase_1:select_requirement` / step 12 占位入口。

第 12 步真实运行前严格核验旧 state：第 11 步 strict success、`active_requirement` 与 `requirement_cycle` 均为 `null`、无 `requirement_registry`、无 `steps/12.json`，root/frontend/backend 均为自身 top-level、`main`、clean。仅在 run-local 将 `current_node` 从旧入口规范化为 `phase_1:initialize_requirement_registry`；state SHA-256 从 `c153ec8c9d39d82806009c7052988695fe10d3a384566f00f852c2c8b4b02ee8` 变为 `eecf476c3b6c401c9db6a41f9f3ca398056eb509de956c93b0f9fae55f0ec170`。生产代码未添加 legacy 兼容。

真实 Responses 成功提取 BR-001～BR-014 共 14 条，标题、连续 `order` 1～14 和依赖均与 Backlog 总览和详情卡一致；注册表全部为 `pending`、`completion: null`。来源 Backlog SHA-256 为 `707c4b91924542e9cbd282fba53cc8857b8ea1fcbdfb7a820c208d0573d759bb`，root `main` SHA 为 `0232d8136c075cb61a6617a95e1504b67bd9acd1`。state 已进入第 13 步 `phase_1:select_requirement`，`active_requirement`、`requirement_cycle` 均为 `null`，未新增 `completed_requirements` 或 `phase_two`，也没有新 Claude session 或负责人决策 conversation。产品 root/frontend/backend 分别为 `0232d8136c075cb61a6617a95e1504b67bd9acd1`、`dbab574dbe4d83a02323a750afd04de007565ac5`、`9682be837759c20f1a9ebbdf8fa2cfc09c2768d4`，三仓仍为 `main`、clean。

幂等真实重跑使用不可用模型配置仍 success，证明未加载模型；`steps/12.json` 与 state 字节不变，最终 result SHA-256 为 `8f829cb3d4935a9dcd07bea2dd8f0df2a22369c433ba4320938e2a9461f41fb0`，state SHA-256 为 `73fd0cb99c39f64f9ef210a171799f79baaee87a417a18f5db74f5b5374470f7`。

第 13 步随后以零 AI、零 Agent、零 Skill 的确定性路径选择 `BR-001`，先保存仅含 ID 的 `active_requirement` 与含 `branch: req/br-001`、各仓 `base_sha`、`return_node_after_completion` 的 cycle，再仅建立三仓同名本地分支。success 仅写入 `steps/requirements/BR-001/13.json`，state 进入 `phase_1_requirement_development` / `requirement:14_trd_design`、`step/current_step: 14`；注册表为 13 pending、0 completed，`BR-001` 为 active。scoped result SHA-256 为 `d37d9dfdaa6ba5c885842f0f6fc6046b027bd11454441182093a185f7fdaacab`，state SHA-256 为 `a6fc435c28010061ca3dd369b571221193b6a534e0d977158cdce215a8f2bc48`。root/frontend/backend 均为 clean `req/br-001`，记录 base 分别为 `0232d8136c075cb61a6617a95e1504b67bd9acd1`、`dbab574dbe4d83a02323a750afd04de007565ac5`、`9682be837759c20f1a9ebbdf8fa2cfc09c2768d4`，各仓 HEAD、local `main` 与 target 均相等，ahead/behind 均为 0；无产品文件改动、commit、merge 或 push。幂等重跑后 scoped result、state 和三仓 ref 字节/事实不变。第 14 步尚未实现；第 14～18 步和阶段二仍是后续工作。
Git 忽略 run `prompt-role-replay-20260823` 保留旧四段 XML prompt 的历史交接回放；它不是现行五段 prompt 的证据。现行 `role/project_context/responsibility/completion/output` 合同已由第 9 步 fresh 真实运行验证。
