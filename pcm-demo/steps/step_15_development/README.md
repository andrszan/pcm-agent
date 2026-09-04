# 第 15 步：实现与验证

## 输入与前置条件

第 15 步只消费当前 state 的活动需求、活动 cycle 与产品工作区，以及当前需求的第 14 步 scoped `success` 和非空活动 TRD。Python 在现有普通文件与非空校验中读取活动 TRD 完整正文并放入负责人的 `<project_context>`；它不读取第 2/5/7/8/9/10/11/13 步文档，不重复加入 Backlog、产品定义、技术方案、工程架构或 UI/UX 文档，不执行 Git 命令，也没有 Git completion verifier。

## Agent、session 与边界

Claude Agent 在产品根以 requirement-scoped key `development_<requirement-id>` 复用公共 `run_agent_decision_loop` 调用，显式使用中模型和 `high` effort。初始 Agent prompt 首行固定为 `/dev-workflow`，正文包含需求 ID/标题、活动 TRD 路径、实现边界，以及最终回复必须给出的开发验收数据基线四态报告；负责人的项目上下文包含同一路径和完整活动 TRD 正文。Agent 按活动 TRD 中适用的体验决定执行，并按需自行读取项目资料、代码、配置、测试和运行环境，不要求固定上游资料。稳定设计偏差可同步至活动 TRD。prompt 正文不包含步骤号、PCM、阶段、节点、session 或 Skill 编排等外层背景。

Agent 不得修改 `.claude/rules/`，也不得 stage、commit、创建或切换分支、merge 或 push。Python completion verifier 继续为空；不解析 Manifest、Markdown 或四态报告，也不增加公共 helper 或状态字段。负责人保持薄裁决：除开发验收数据基线适用性与四态报告外，不要求 Agent 逐项复述其它证据。最新回复缺少基线报告且当前环境可继续时，`continue` 要求核验并补充；报告“有缺口”时按现有语义在可继续处理时 `continue`，只有缺少不可替代外部条件时 `blocked`。只有最新回复明确报告基线适用性，四态为“已建立”“已更新”或“不适用”，且未自报其它缺口、未完成项或阻断时，才可 `completed`。

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

不得静默偏离适用决定；稳定偏差必须同步活动 TRD。截图只是其中一项证据，不能替代动态交互、权限、失败恢复和持久化的真实验证。

## 开发验收数据基线报告

最终完整回复必须以 `开发验收数据基线：已建立/已更新/不适用/有缺口` 四态之一报告当前需求的实际结果，明确当前需求是否适用，并给出依据、项目实际支持的恢复方式、交付文档位置和实际验证摘要：

- **已建立**：此前没有适用基线，本需求首次建立自主验收受影响主要任务所需的角色、参考数据、代表性对象/状态/关系、适用对象资源及恢复/核验与交付说明；
- **已更新**：已有适用基线，本需求新增或改变上述内容、时间语义、恢复/核验或交付说明，或既有基线已不足以自主体验受影响主要任务，并已完成对应增量；
- **不适用**：本需求不引入上述基线变化，且既有基线仍足以从正常入口自主体验受影响主要任务；
- **有缺口**：适用基线或增量、恢复能力、交付文档或实际验证仍有未完成项。

恢复方式按项目事实选择，可以是幂等重跑或补齐等非破坏方式、定向重置或可重建开发环境；不强制 destructive reset，也不得声称项目支持尚未实现的恢复方式。Python 不对这段自然语言做确定性解析，适用性与四态由负责人基于 Agent 最新完整回复判断。

## 真实验证

真实 run 为 `pcm-demo/runs/step01-mendmark`，产品位于 `/Users/zhou/resource/fireworks/ANDRSZAN/pcm-products/mendmark`。development session 为 `e6bd1b82-39f9-41b2-9cc9-a69b281015dc`，init 确认 Fable 5、Claude Code 2.1.233 和 `bypassPermissions`；最终正常 success 为 23 turns、约 `$9.784016`。

首次调用已保存 init/session 后，`claude-agent-sdk` 0.2.139 的单条 CLI stdout JSON 默认 1 MiB 缓冲触发 `JSON message exceeded maximum buffer size`。公共 runner 将 `ClaudeAgentOptions.max_buffer_size` 固定为 10 MiB 后，从同一 session 恢复成功并保留已有产品改动；没有新增配置，也不影响 resume。自定义 dev/reviewer 子代理曾出现未识别 model 警告和一个子进程退出，但主 Agent 继续完成，生产 prompt 未改动。

最终 conversation 共 9 条：`system → assistant 初始 → user 首轮回复 → assistant completed → assistant 正常结束要求 → user 已实现但未完全验证 → assistant continue 补 Firefox/WebKit → user 三浏览器结果 → assistant 最终 completed`。负责人最终 `completed`，`BR-001` 仍为 `active`、`completion: null`，state 已进入 step 16；root 保留活动 TRD 和代表性截图未跟踪，frontend/backend 保留实现、测试、迁移与配置的未提交变更。三仓均在 `req/br-001`，index clean，无 commit、merge 或 push。

Agent 报告后端 Ruff/format/build、pytest 16 passed 1 skipped、真实 PostgreSQL 与 Alembic upgrade-downgrade-upgrade；前端 lint/type-check/build、Vitest 15 passed；Chromium/Firefox/WebKit Playwright 矩阵 3 passed；真实 FastAPI/PostgreSQL/Vite 浏览器联调、代表性截图读取和独立审查完成。不可用 LLM 配置的幂等重跑仍 success，state/result/conversation 字节不变。

## 自动化与运行

第 14、15 步本体和 CLI 定向 29 项通过；PCM Demo 全量 359 项 `unittest` 通过（50.534 秒），`compileall common steps run_step.py run_all.py test_run_step_retry.py test_run_all.py`、相关 IDE diagnostics 与 `git diff --check` 通过。未运行新的真实 Claude Agent、AI-compatible 负责人或产品浏览器流程；本轮只补充第 14、15 步负责人直接权威上下文和相应自动化。第 8、17、18 步既有代码与验证事实保持不变。

```bash
cd /Users/zhou/resource/fireworks/ANDRSZAN/pcm-agent-skills/pcm-demo
uv run python run_step.py --step 15 --run-id <run-id>
uv run python -m unittest steps.step_15_development.test_step steps.step_15_development.test_cli -v
```
