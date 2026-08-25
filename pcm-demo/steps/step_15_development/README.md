# 第 15 步：实现与验证

## 输入与前置条件

第 15 步只消费当前 state 的活动需求、活动 cycle 与产品工作区，以及当前需求的第 14 步 scoped `success` 和非空活动 TRD。它不读取第 2/5/7/8/9/10/11/13 步文档，不执行 Git 命令，也没有 Git completion verifier。

## Agent、session 与边界

Claude Agent 在产品根以 requirement-scoped key `development_<requirement-id>` 复用公共 `run_agent_decision_loop` 调用。初始 prompt 只包含 `/dev-workflow`、需求 ID/标题和活动 TRD 路径；Agent 按需自行读取项目资料、代码、配置、测试和运行环境。稳定设计偏差可同步至活动 TRD。

Agent 不得修改 `.claude/rules/`，也不得 stage、commit、创建或切换分支、merge 或 push。完成 verifier 为空；负责人 `AgentDecision.completed` 即为本步骤领域完成，`continue` 和 `blocked` 沿用公共循环语义。

首次从 Agent 取得 session 后，程序立即同步 `requirement_cycle.development_session_id`。success result 写入：

```text
steps/requirements/<requirement-id>/15.json
```

其 `outputs` 固定为空，并保存 `requirement_id`、`trd_path` 和 `development_session_id`。success 推进至 `requirement:16_rule_retrospective` / step 16；blocked 保留 step 15 与同一 session。success result 已写而 state 尚未推进时可恢复推进；推进后及 CLI 幂等保护只核验当前活动需求的完整 scoped success。

## 真实验证

真实 run 为 `pcm-demo/runs/step01-mendmark`，产品位于 `/Users/zhou/resource/fireworks/ANDRSZAN/pcm-products/mendmark`。development session 为 `e6bd1b82-39f9-41b2-9cc9-a69b281015dc`，init 确认 Fable 5、Claude Code 2.1.233 和 `bypassPermissions`；最终正常 success 为 23 turns、约 `$9.784016`。

首次调用已保存 init/session 后，`claude-agent-sdk` 0.2.139 的单条 CLI stdout JSON 默认 1 MiB 缓冲触发 `JSON message exceeded maximum buffer size`。公共 runner 将 `ClaudeAgentOptions.max_buffer_size` 固定为 10 MiB 后，从同一 session 恢复成功并保留已有产品改动；没有新增配置，也不影响 resume。自定义 dev/reviewer 子代理曾出现未识别 model 警告和一个子进程退出，但主 Agent 继续完成，生产 prompt 未改动。

最终 conversation 共 9 条：`system → assistant 初始 → user 首轮回复 → assistant completed → assistant 正常结束要求 → user 已实现但未完全验证 → assistant continue 补 Firefox/WebKit → user 三浏览器结果 → assistant 最终 completed`。负责人最终 `completed`，`BR-001` 仍为 `active`、`completion: null`，state 已进入 step 16；root 保留活动 TRD 和代表性截图未跟踪，frontend/backend 保留实现、测试、迁移与配置的未提交变更。三仓均在 `req/br-001`，index clean，无 commit、merge 或 push。

Agent 报告后端 Ruff/format/build、pytest 16 passed 1 skipped、真实 PostgreSQL 与 Alembic upgrade-downgrade-upgrade；前端 lint/type-check/build、Vitest 15 passed；Chromium/Firefox/WebKit Playwright 矩阵 3 passed；真实 FastAPI/PostgreSQL/Vite 浏览器联调、代表性截图读取和独立审查完成。Windows NVDA 与 macOS VoiceOver 人工路径 deferred，负责人判定为非阻断。不可用 LLM 配置的幂等重跑仍 success，state/result/conversation 字节不变。

## 自动化与运行

第 15 步本体 6 项、CLI 4 项，共 10 项；全量 252 项 `unittest`、`compileall`、`git diff --check` 和全工作区 IDE diagnostics 均已通过，独立只读审查无高、中置信发现。能力仓未安装 Ruff，未执行 Ruff。

```bash
cd /Users/zhou/resource/fireworks/ANDRSZAN/pcm-agent-skills/pcm-demo
uv run python run_step.py --step 15 --run-id <run-id>
uv run python -m unittest steps.step_15_development.test_step steps.step_15_development.test_cli -v
```
