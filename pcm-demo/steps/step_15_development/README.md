# 第 15 步：实现与验证

## 输入与前置条件

第 15 步只消费当前 state 的活动需求、活动 cycle 与产品工作区，以及当前需求的第 14 步 scoped `success` 和非空活动 TRD。Python 在现有普通文件与非空校验中读取活动 TRD 完整正文并放入负责人的 `<project_context>`；项目准备清单只传固定相对路径，不读取正文或增加第 5 步上游验证。可信开发资源清单只加载绝对路径和可读性事实，不读取正文或把秘密回注 prompt；配置缺失、路径不可用等明确失败只向 Agent 和负责人交接“不可用”，不前置终止开发。其它第 2/7/8/9/10/11/13 步文档不重复加入，也不执行 Git 命令或 Git completion verifier。

## 前端适用性与两个领域

开发开始前，根据当前需求及完整活动 TRD 作一次严格的 `applicable: bool`、非空 `reason` 判断，先保存到 `state["development_<ID>"]["frontend_applicability"]`。恢复复用这个事实，不从目录或关键词推断；格式错误失败，不默认跳过。适用前端但权威仓库列表没有 frontend、交付目录不可用或工作区缺少受控前端能力时，在 Agent 前准确失败。

顺序复用公共 `run_agent_decision_loop`：

| 领域 key | 入口与责任 |
| --- | --- |
| `frontend_ui_ux_<ID>` | `/frontend-ui-ux`，实际调用 `/ui-ux-pro-max:ui-ux-pro-max`；完成当前需求的正式前端和局部体验验证 |
| `development_<ID>` | `/dev-workflow`；承接前端，完成剩余实现、后端及真实集成与需求交付 |

两域使用独立 session、conversation 和 system snapshot，均使用 `development` 模型策略。不适用时零前端 Agent 调用；纯前端需求仍执行必要集成和交付核验，不为形式增加后端代码。两个领域均接收当前需求相关的质量原发现或反馈原场景、采纳目标。负责人持有完整活动 TRD 与必要非秘密路径事实，不读取截图重做审美验收。

前端继承原型、体验框架和已有正式实现，只读早期 HTML 原型；没有原型的既有产品以当前真实界面为基线。不创建第二套演示应用或提前铺开其它业务页。真实接口可用时复用，缺失部分允许集中、可替换的模拟访问，不要求尚待开发的后端与持久化提前验收。授权内稳定细化可以同步活动 TRD；不得改后端业务、需求生命周期或只读规则。前端正常交接包含入口、行为、真实／模拟边界、验证和待接入内容，保存在 conversation，不另建阶段报告。

进入完整开发领域时重新读取活动 TRD，使用 `agent_conversation_report` 传递有序自然语言交接，而非仅取最新回复。集成需要的局部界面调整由当前开发会话处理，保留已确定设计；涉及用户可见 UI/UX 实施时使用指定前端能力和完整插件入口，纯接口地址或数据映射不重跑设计。两域都保留当前需求分支及待提交变更，不 stage、commit、建分支、merge、push 或修改 `.claude/rules/`。

## 结果、恢复与 CLI 接口

成功必须同时满足前端 completed／不适用与完整开发 completed。前端完成不推进外层节点、不结束需求。`requirement_cycle.development_session_id` 始终只指向后端与集成 session；前端先失败时允许为空。

`steps/requirements/<ID>/15.json` 保留 `outputs: []`、需求 ID、TRD 路径及开发 session，新增必需 `frontend`：

```json
{"applicable": true, "reason": "当前需求包含用户交互", "session_id": "前端 session ID"}
```

不适用时 `session_id` 为 null；分类尚未完成的失败结果不填 frontend。已知适用但前端会话尚未创建时，失败结果允许其 session 为 null。success 推进至 `requirement:16_rule_retrospective`；blocked 保留当前节点。

- 前端失败只恢复前端原会话；前端完成后后端失败，恢复公共 completed 对话并继续原后端会话，不重做前端、不重新分类。
- 恢复消息按目标 key 由公共循环消费一次，后端消息不误投已完成前端。
- completed 对话已保存而 result 未写、result 已写而 state 未推进，都沿用公共记录恢复，不增加完成标记。
- 当前旧 development session／conversation 缺少适用性事实，或当前 success 缺少 frontend 合同，使用 `LegacyFrontendContractError` 只读拒绝；已经越过节点的历史成功不反向套新合同。
- CLI 在通用失败回写之前调用导出的 `validate_existing_contract(run_dir, state)`；`result(frontend=...)`、`DevelopmentBlocked.frontend` 与 `failure_scope()["frontend"]` 用于保留已知交接，未知时不填。`DevelopmentBlocked.development_session_id` 可为空，不能用前端 ID 替代。

## 验证分工与完成判断

开发 Agent 负责实现、适用测试、真实集成、浏览器与截图证据，以及独立审查。子代理做局部针对性检查，Leader 在整合版本上统一安排必要构建、跨模块回归和全栈验收；复用仍有效的结果，只补受影响证据。普通功能默认一次完整独立审查，修复后复核原发现和受影响差异，不机械增加专项审查或反复全面找问题。

适用体验决定保留来源、具体要求和范围，并可与功能、架构证据合并汇报；实际差异再说明 Current/Target、影响和必要迁移，重要前提与例外不丢失。截图不能替代动态交互、权限、失败恢复和持久化验证，不因精简报告降低证据要求。

负责人依当前交付结果判断，信任 Agent 已报告的实现与有效证据，不重做验收，也不因未逐项复述完成声明或映射而补问。真实未完成项需区分必要交付缺口与非阻断的方法限制：前者可继续解决时给出最小下一步，后者如实披露但不自动阻止完成；不能用限制说明掩盖关键失败。具体裁决规则以 `step.py` 的现行定义为准。

## 历史真实验证（原单域流程）

真实 run 为 `pcm-demo/runs/step01-mendmark`，产品位于 `/Users/zhou/resource/fireworks/ANDRSZAN/pcm-products/mendmark`。development session 为 `e6bd1b82-39f9-41b2-9cc9-a69b281015dc`，init 确认 Fable 5、Claude Code 2.1.233 和 `bypassPermissions`；最终正常 success 为 23 turns、约 `$9.784016`。

首次调用已保存 init/session 后，`claude-agent-sdk` 0.2.139 的单条 CLI stdout JSON 默认 1 MiB 缓冲触发 `JSON message exceeded maximum buffer size`。公共 runner 将 `ClaudeAgentOptions.max_buffer_size` 固定为 10 MiB 后，从同一 session 恢复成功并保留已有产品改动；没有新增配置，也不影响 resume。自定义 dev/reviewer 子代理曾出现未识别 model 警告和一个子进程退出，但主 Agent 继续完成，生产 prompt 未改动。

最终 conversation 共 9 条：`system → assistant 初始 → user 首轮回复 → assistant completed → assistant 正常结束要求 → user 已实现但未完全验证 → assistant continue 补 Firefox/WebKit → user 三浏览器结果 → assistant 最终 completed`。负责人最终 `completed`，`BR-001` 仍为 `active`、`completion: null`，state 已进入 step 16；root 保留活动 TRD 和代表性截图未跟踪，frontend/backend 保留实现、测试、迁移与配置的未提交变更。三仓均在 `req/br-001`，index clean，无 commit、merge 或 push。

Agent 报告后端 Ruff/format/build、pytest 16 passed 1 skipped、真实 PostgreSQL 与 Alembic upgrade-downgrade-upgrade；前端 lint/type-check/build、Vitest 15 passed；Chromium/Firefox/WebKit Playwright 矩阵 3 passed；真实 FastAPI/PostgreSQL/Vite 浏览器联调、代表性截图读取和独立审查完成。不可用 LLM 配置的幂等重跑仍 success，state/result/conversation 字节不变。

## 自动化与运行

定向单元测试覆盖一次分类、纯后端跳过、独立前端先行、纯前端集成、完整交接与 TRD 重读、质量／反馈输入、两域失败及消息恢复、成功写入中断、旧合同只读拒绝和 CLI 交接保存。上述历史真实运行不证明新双域流程已完成真实通道或产品浏览器验收。

```bash
cd /Users/zhou/resource/fireworks/ANDRSZAN/pcm-agent-skills/pcm-demo
uv run python run_step.py --step 15 --run-id <run-id>
uv run python -m unittest steps.step_15_development.test_step steps.step_15_development.test_cli -v
```
