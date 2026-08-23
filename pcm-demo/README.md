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

每个步骤的业务代码、测试和详细运行说明都在对应步骤目录中。根 README 只提供导航。

## 统一测试

在 `pcm-demo/` 目录执行：

```bash
uv sync
uv run python -m unittest discover -s . -t . -p 'test*.py' -v
```

该入口从 `pcm-demo/` 根递归发现 `common/` 与 `steps/` 测试。当前第 9 步专属 29 项、公共循环 24 项、第 7 步 8 项、第 8 步 17 项，相关定向 78 项及全量 141 项均已通过；`compileall`、`git diff --check` 通过，IDE 对第 9 步无诊断。本轮文档更新后的最终审查由主代理执行。

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

独立核验确认 root/frontend/backend 均为自身 top-level、`main`、clean，固定文档 tracked。同 run 幂等重跑后 conversation 仍为 11 条，session 和 root HEAD 不变，没有再次调用 Agent、决策服务或产生新提交。`run_step.py` 只对 schema 完整的第 8、9 步 success 保护既有 result 和已推进 state；后续重跑失败不会覆盖 success 或回退节点，残缺 success 不保护，其它步骤保持原行为。第 10 步仍按需，当前进入其合同讨论。

Git 忽略 run `prompt-role-replay-20260823` 保留旧四段 XML prompt 的历史交接回放；它不是现行五段 prompt 的证据。现行 `role/project_context/responsibility/completion/output` 合同已由第 9 步 fresh 真实运行验证。
