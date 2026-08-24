# 第 11 步：拆分 Backlog

本步骤在项目初始化结束后，基于已经确认的产品、工程和体验事实生成正式 Backlog；不选择需求、不创建需求分支、不形成 TRD，也不实施任何需求。

## 运行

在 `pcm-demo/` 目录执行：

```bash
uv run python run_step.py --step 11 --run-id <run-id>
```

定向自动化测试：

```bash
uv run python -m unittest \
  steps.step_11_requirement_breakdown.test_step \
  steps.step_11_requirement_breakdown.test_cli -v
```

## 输入与前置条件

fresh 入口的状态必须是 `project:11_requirement_breakdown`，产品工作区必须是状态中独立工作区根下的非符号链接目录。第 8 步确定的每个权威仓库均须是自身 Git top-level、位于 `main`。

固定交接依次为：

- 第 2 步结果引用的两份非空产品定义；
- 第 5 步固定项目准备清单；
- 第 7 步固定总体技术方案；
- 第 8 步 result/state 完全一致的有序权威仓库清单和 clean 交接；
- 第 9 步严格 success 的唯一工程架构文档 `docs/design/工程架构设计.md`；
- 第 10 步严格 success 结果：`applicable: true` 时读取唯一 `docs/ui-ux/framework.md`；`applicable: false` 时必须为 `outputs: []`，不读取或扫描该文档。

程序不从固定前后端目录、历史文字或 Agent 回复补充仓库和交接对象。

## Agent、决策与 Backlog 边界

步骤只使用一个领域键和 Claude session：`requirement_breakdown`。初始提示首行固定为 `/requirement-breakdown`，单次调用上限为 48 turns、`$16`；同一历史最多 8 轮 `AgentDecision(completed/continue/blocked)` 决定。

Agent 只允许创建或更新唯一固定产物：

```text
docs/backlog/backlog.md
```

Backlog 必须基于权威输入和实际工程形成可独立交付、可验证、顺序合理的正式需求，说明范围、目标、验收要点、依赖与风险。它不记录“待开发”“开发中”“已完成”“阻塞”等需求开发状态；活动需求、完成情况与恢复位置由调用方的外部结构化运行状态管理。业务对象或业务流程自身的状态仍可作为需求内容。

Agent 不得实施需求，或修改代码、测试、配置、项目规则、其它文档；初始工作不得执行 Git 写操作。负责人 `completed` 后，verifier 才进行完成核验；`continue` 继续原 session，`blocked` 仅用于当前环境无法取得的不可替代外部资源。

## 工作树、提交与恢复

运行期间，所有权威仓库必须保持自身 top-level、`main`；子仓始终 clean，产品根只允许固定 Backlog 文档产生变更。Python 只读 Git，只核验 top-level、分支、全仓和固定文档状态及文档是否 tracked。

`completed` 后，缺失或空 Backlog 先由同一 session 接收固定 repair prompt。文档存在后，无论相对提交是否有 diff，都必须在同一 session 精确发送一次 `/commit-changes`。成功要求该 exact prompt、其紧邻的非空 Agent `user` 回复和原 session 构成有效执行锚点；最终文档必须为非空、非符号链接普通文件、已被根仓跟踪，且全部权威仓库 clean。

- **fresh**：全仓必须 clean，并拒绝既有 `requirement_breakdown` session、conversation 引用、私有状态或历史文件。
- **resume**：必须具有原 session、conversation 引用和非符号链接历史；缺失或不一致不得静默新建会话。conversation 父目录、叶文件和 Backlog 路径均拒绝符号链接。
- **blocked**：保存当前第 11 步、原因、所需外部输入及可用 Backlog 输出；补齐资源后从原 session 恢复。若现场已经满足成功条件，正常归一化成功。
- **failed**：输入、状态、文件、Git、SDK 或决定错误保留现场并停留在第 11 步，修复后重跑；不以历史文字替代现场核验。
- **success**：`steps/11.json` 严格为 `applicable: true` 和唯一输出 `docs/backlog/backlog.md`。状态进入 `phase_1_requirement_development` / `phase_1:initialize_requirement_registry`，`step` 与 `current_step` 均为 12，`active_requirement`、`requirement_cycle` 均为 `null`；本步骤不新增 `completed_requirements` 或 `phase_two`。

result/state 写入中断可由完整 success 结果、固定文档、提交锚点和全仓 clean 恢复；幂等重跑会重新核验现场而不重复调用。`run_step.py` 仅保护 schema 完整的第 8～12 步 success，残缺 success 不受保护。第 8～11 步的 Git 与提交合同保持各步骤局部实现，不修改 `common/`，不抽取 Git DSL。

## 自动化与真实验证

自动化已通过第 11 步本体 9 项与 CLI 6 项，共 15 项；第 12 步本体 11 项与 CLI 6 项，共 17 项；两步定向共 32 项、全量递归 `unittest` 194 项均通过。`compileall`、`git diff --check` 通过；IDE 对第 12 步 `step.py`、`test_step.py`、`test_cli.py` 及 `run_step.py` 无诊断，独立只读审查最终没有高、中置信发现。Ruff 未安装，未执行 Ruff。

真实 run 为 `pcm-demo/runs/step01-mendmark`，产品工作区为 `/Users/zhou/resource/fireworks/ANDRSZAN/pcm-products/mendmark`，权威仓库为 `root/frontend/backend`。运行前，旧 Skill 已精确同步并由真实 `/commit-changes` 单独提交 `9263d28`；该提交只修改 Skill、未 push，且三仓 clean，是使用新 Backlog 合同的测试前置，不是第 11 步输出。

唯一 session 为 `af7d198c-b090-44d8-9d92-ae0738150854`。init 确认 Skill/slash command、产品根 cwd、Fable 5、Claude Code 2.1.233 和 `bypassPermissions`。fresh 调用的内置 Explore 子代理曾给出未识别模型 `gpt-5.6-terra[1m]` 警告，但主 Agent 同次正常 success；首次生成 Result 为 15 turns、`$5.789825`。Agent 生成约 59,140 字节、约 1,110 行 Backlog，包含 14 项 BR 需求：完整覆盖 E.1，未自动纳入 E.2/E.3，首条验证切片由完整的 BR-001～BR-006 组成；文档不含需求开发状态列或字段，保留业务状态内容。

负责人 Responses 决策曾三次在正常 run 后瞬时写入 failed（前两次在生成回复后，第三次在提交回复后）。两次独立同上下文只读诊断均得到合法 `completed`，但未注入正式 conversation；最终依靠正常原节点重跑恢复，未添加自定义 HTTP 重试或修改生产 prompt。最终 conversation 共 7 条：`system → assistant 初始 → user 生成回复 → assistant completed → assistant exact commit prompt → user 提交回复 → assistant completed`；exact commit 恰好一次且使用同一 session。

产品根创建未 push 提交 `2aaa743a97d96fe93deaaaaa13a94e4c414369a2`，message 为 `docs: 建立 MendMark 首版正式 Backlog`，仅新增 `docs/backlog/backlog.md`；frontend/backend SHA 不变，三仓均为 `main`、clean 且各自 top-level。该历史 `steps/11.json` success 当时进入旧 `phase_1:select_requirement` / step 12 占位入口。第 12 步真实运行前严格核验该旧 state：第 11 步 strict success、`active_requirement` 与 `requirement_cycle` 均为 `null`、无注册表、无 `12.json`，root/frontend/backend 均为自身 `main`、clean；仅 run-local 将 `current_node` 规范化为 `phase_1:initialize_requirement_registry`，state SHA-256 从 `c153ec8c9d39d82806009c7052988695fe10d3a384566f00f852c2c8b4b02ee8` 变为 `eecf476c3b6c401c9db6a41f9f3ca398056eb509de956c93b0f9fae55f0ec170`。生产代码不接受旧 `select_requirement` / step 12 入口，也未添加 legacy 兼容。

规范化后第 12 步已在同一真实 run 成功完成，state 进入第 13 步 `phase_1:select_requirement`，并初始化全部 `pending`、`completion: null` 的 14 项 BR 注册表；该结果及幂等重跑的具体来源指纹、产品 SHA 与零模型调用证据见[第 12 步说明](../step_12_initialize_requirement_registry/README.md)。
