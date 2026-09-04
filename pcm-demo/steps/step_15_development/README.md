# 第 15 步：实现与验证

## 输入与前置条件

第 15 步只消费当前 state 的活动需求、活动 cycle 与产品工作区，以及当前需求的第 14 步 scoped `success` 和非空活动 TRD。Python 在现有普通文件与非空校验中读取活动 TRD 完整正文并放入负责人的 `<project_context>`；它不读取第 2/5/7/8/9/10/11/13 步文档，不重复加入 Backlog、产品定义、技术方案、工程架构或 UI/UX 文档，不执行 Git 命令，也没有 Git completion verifier。

## Agent、session 与边界

Claude Agent 在产品根以 requirement-scoped key `development_<requirement-id>` 复用公共 `run_agent_decision_loop` 调用，显式使用中模型和 `high` effort。初始 Agent prompt 只包含 `/dev-workflow`、需求 ID/标题和活动 TRD 路径；负责人的项目上下文包含同一路径和完整活动 TRD 正文。Agent 按活动 TRD 中适用的体验决定执行，并按需自行读取项目资料、代码、配置、测试和运行环境，不要求固定上游资料。稳定设计偏差可同步至活动 TRD。

Agent 不得修改 `.claude/rules/`，也不得 stage、commit、创建或切换分支、merge 或 push。完成 verifier 为空；语义完成由 `dev-workflow`、Agent 和负责人裁决。Agent 最终回复必须明确声明“已完成”“已实现但未完全验证”或“阻塞”之一；只有明确声明已完成，并明确没有剩余工作、失败项、验证缺口或阻断项时，负责人才能返回 `AgentDecision.completed`。未声明结束状态、含糊总结或只引用文件、章节、代码符号和行号的回复必须返回 `continue`，要求原 session 重新读取并补齐；信息不足本身不得判为 `blocked`。

首次从 Agent 取得 session 后，程序立即同步 `requirement_cycle.development_session_id`。success result 写入：

```text
steps/requirements/<requirement-id>/15.json
```

其 `outputs` 固定为空，并保存 `requirement_id`、`trd_path` 和 `development_session_id`。success 推进至 `requirement:16_rule_retrospective` / step 16；blocked 保留 step 15 与同一 session。success result 已写而 state 尚未推进时可恢复推进；推进后及 CLI 幂等保护只核验当前活动需求的完整 scoped success。

## 适用体验决定与完成判断

存在活动 TRD 中适用的已确认 Target 或有依据的默认 Target 时，负责人只在完成报告建立以下可追溯链路后才可返回 `completed`：

```text
决定（默认 Target 含依据与重议条件）→可观察结果→实现位置→真实浏览器和实际读取截图证据→实际结果映射
```

不得静默偏离适用决定；稳定偏差必须同步活动 TRD。截图只是其中一项证据，不能替代动态交互、权限、失败恢复和持久化的真实验证。完成报告可以保持简洁，不要求逐项复制此前已经报告的全部证据，但必须正面声明结束状态；不能以没有主动报告问题反推已经完成。需要负责人决定时，必须自包含准确问题、已核验事实与约束、当前约束下实质可行选项、各选项主要影响及推荐理由，引用只能辅助定位。

## 真实验证

真实 run 为 `pcm-demo/runs/step01-mendmark`，产品位于 `/Users/zhou/resource/fireworks/ANDRSZAN/pcm-products/mendmark`。development session 为 `e6bd1b82-39f9-41b2-9cc9-a69b281015dc`，init 确认 Fable 5、Claude Code 2.1.233 和 `bypassPermissions`；最终正常 success 为 23 turns、约 `$9.784016`。

首次调用已保存 init/session 后，`claude-agent-sdk` 0.2.139 的单条 CLI stdout JSON 默认 1 MiB 缓冲触发 `JSON message exceeded maximum buffer size`。公共 runner 将 `ClaudeAgentOptions.max_buffer_size` 固定为 10 MiB 后，从同一 session 恢复成功并保留已有产品改动；没有新增配置，也不影响 resume。自定义 dev/reviewer 子代理曾出现未识别 model 警告和一个子进程退出，但主 Agent 继续完成，生产 prompt 未改动。

最终 conversation 共 9 条：`system → assistant 初始 → user 首轮回复 → assistant completed → assistant 正常结束要求 → user 已实现但未完全验证 → assistant continue 补 Firefox/WebKit → user 三浏览器结果 → assistant 最终 completed`。负责人最终 `completed`，`BR-001` 仍为 `active`、`completion: null`，state 已进入 step 16；root 保留活动 TRD 和代表性截图未跟踪，frontend/backend 保留实现、测试、迁移与配置的未提交变更。三仓均在 `req/br-001`，index clean，无 commit、merge 或 push。

Agent 报告后端 Ruff/format/build、pytest 16 passed 1 skipped、真实 PostgreSQL 与 Alembic upgrade-downgrade-upgrade；前端 lint/type-check/build、Vitest 15 passed；Chromium/Firefox/WebKit Playwright 矩阵 3 passed；真实 FastAPI/PostgreSQL/Vite 浏览器联调、代表性截图读取和独立审查完成。不可用 LLM 配置的幂等重跑仍 success，state/result/conversation 字节不变。

## 自动化与运行

公共循环与第 15 步定向 57 项通过；PCM Demo 当前工作树全量 369 项中 368 项通过（54.112 秒），唯一失败是本次未修改且当前 `HEAD` 已存在的第 17 步 `MAX_DECISION_ROUNDS=32` 与测试仍期望 16 的基线断言。`compileall common steps probes run_step.py run_all.py test_run_step_retry.py test_run_all.py`、dev-workflow eval JSON 解析与 `git diff --check` 通过。fresh Probe C `probe-c-decision-handoff-20260905` 使用当前配置 AI-compatible 模型一次确认引用式不完整交接为 `continue`，一次确认自包含不可替代外部资源缺口为 `blocked`。本轮未重新执行真实 Claude Agent 产品开发或浏览器流程，也未修改现有产品工作区和历史 conversation；新负责人合同只进入新建 decision conversation，模板 Agent 规则只随未来新建工作区生效。

```bash
cd /Users/zhou/resource/fireworks/ANDRSZAN/pcm-agent-skills/pcm-demo
uv run python run_step.py --step 15 --run-id <run-id>
uv run python -m unittest steps.step_15_development.test_step steps.step_15_development.test_cli -v
```
