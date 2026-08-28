# 第 6 步：项目化基础工程

## 输入

- 运行状态位于 `project:06_bootstrap_foundation`，产品根仍是零提交、空 index 的 `main`；每个适用基础工程已经是自身 top-level 为目录本身、unborn HEAD、空 index 的 `main` 独立 Git 仓库，不适用端不存在。
- `steps/02.json` 引用两份工作区内非空、非符号链接的产品定义文档。
- `steps/04.json` 提供实际适用工程目录和组装证据；第 3 步选型只用于核验该组装事实。
- `steps/05.json` 是严格成功结果，包含当前 `docs/requirements/项目准备清单.md` 和两份产品定义的无秘密 `readiness_baseline` 指纹；当前文件必须与该指纹一致。
- 适用工程内部的 README、manifest、锁文件、配置、代码和测试由 Agent 按当前现场读取，不由 Python 重复建模。

## 行为

在产品项目根新建或恢复 Claude session，首条提示以 `/project-bootstrap` 开始。正文只描述领域输入、范围、输出和约束：向 Agent 传递产品定义、已完成的准备基线、实际适用工程以及白名单化组装事实中的 `target`、模板 ID、分支、相对路径和 commit SHA；不传可能带凭据的 `git_url` 或 `origin`，不包含步骤号、PCM 节点、session 或外层编排背景。

Agent 负责有限范围项目化：项目身份、基础配置、README、必要共享视觉基线、模板测试迁移、经引用检查的误导残留，以及适用的真实安装、检查、测试、构建、启动、浏览器检查和基础联调。完成前必须删除所属仓未忽略的 `.coverage` 覆盖率数据库，或将这类可再生产物加入所属仓 `.gitignore`；根模板以 `**/.coverage` 覆盖该规则。

准备基线、受保护运行配置和资源身份是项目化的既定输入。Agent 可以按工程实际加载合同维护被 Git 忽略的实际 `.env` 或等价本地配置及对应 `.env.example` 或既有公开示例，包括环境变量改名和配置结构迁移；迁移必须复用同一既有资源绑定和真实值，保留资源身份、endpoint 与权限范围。不得重新选择、创建、派生、轮换或替换外部资源或凭据，公开示例不得包含秘密。

真实工程命令失败时，先修复项目化范围内的配置读取、变量迁移、脚本、代码、代理、服务启动、健康入口、前后端连接、测试或浏览器入口问题并重跑。只有确认工程接线无法继续修复且既有外部条件本身不可用时，才报告具体失败入口、影响、未验证范围和补验条件并阻塞；不得用替代资源或新凭据规避。

不得修改权威产品定义或项目准备清单，不得实现业务功能、总体技术方案或工程架构，不得改变现有独立 Git 边界、暂存、提交、建分支、合并或推送。Python 只核验前序交接、根仓和适用子仓的 `main` / unborn / 空 index 边界，并在完成核验中复查根 README 和 `.coverage`；不解析实际 `.env`、准备清单语义或外部资源身份，也不重复执行 Agent 已完成的工程命令。

## 统一决策与恢复

本步骤只维护 bootstrap 的 `DECISION_RULES`。新 conversation 的完整 XML system snapshot 由 `common/decision.py` 渲染，严格包含 `<role>`、`<project_context>`、`<responsibility>`、`<completion>`、`<output>` 五段。项目上下文包括两份产品定义原文、已完成的项目准备基线、配置迁移与既有资源边界、适用工程和组装白名单投影；不包含资源清单正文、真实 `.env` 值、`git_url` 或 `origin`。恢复严格使用历史 `messages[0]`，不重渲染或覆盖。

每轮完整真实 Agent 回复都会保存为对话的 `user` 消息；完整 XML system prompt 原样传给一次 `responses.parse`，以 Pydantic `AgentDecision` 取得统一结构化结果：

- `continue` 表示项目化修改、配置读取或迁移、工程接线、安装、检查、测试、构建、启动、健康检查、联调、浏览器验证或完成证据尚不完整，但可在既有准备事实和工程范围内继续修复并重跑。
- `completed` 表示负责人相信项目化和全部适用工程验证已经完成；允许配置键名与结构迁移，但资源绑定、endpoint、权限范围和秘密值保持不变，没有重新选择、创建、派生、轮换或替换资源或凭据。程序随后重验交接、目录、根仓及适用子仓 Git 边界、`.coverage` 处理和产品根 README。
- `blocked` 仅在已经使用既有配置排除工程接线问题后，当前环境无法恢复的既有外部账号、授权、凭据、服务、数据、设备、付费条件或线下动作本身不可用时成立；必须说明真实失败入口和补验条件，不能通过替代资源或新凭据消除阻塞。
- README 或 `.coverage` 可安全补完时，程序追加固定修复提示并在同一 session 继续；边界冲突直接 `failed`。写入 `blocked` 前同样重验 Git 边界和 `.coverage`。
- `error_max_turns`、`error_max_budget_usd` 有 session 和非空回复时可进入裁决，但必须在后续正常 `success` 后才可最终完成。400/429/500、连接、CLI/进程、无 `ResultMessage` 和其它 SDK/API 错误为 `failed`；不增加外层自定义 HTTP 重试。

对话尾部决定恢复动作：`user` 先裁决，`continue` 执行 answer，`completed` 先核验，`blocked` 停止；从 `blocked` 显式重跑才重新核验。状态仅保存 session、对话路径、最后一次 Agent 终止摘要和短暂待写入原文，不写 `pending_agent_prompt`、决策轮次或 Python 完成声明。

## 输出与恢复

成功时 `steps/06.json.outputs` 记录第 4 步实际适用工程目录，先写步骤结果，再推进到 `project:07_solution_design`。如果没有适用基础工程，仍核验根 Git 和暂存区后以 `applicable: false` 无副作用跳过；该语义保持不变。

只有 `status=success` 的既有结果、完成决定或状态推进中断可在重新核验 readiness 指纹、工程、README、`.coverage` 和 Git 事实后补写或复用成功；`failed` / `blocked` 结果不被当作成功，也不阻止原 session 恢复。完整成功状态不再次调用 Agent 或决策模型。步骤结果格式与 `run_step.py` 的 `success` / `blocked` / `failed` 三态不变。

## 运行

```bash
cd /Users/zhou/resource/fireworks/ANDRSZAN/pcm-agent-skills/pcm-demo
uv run python run_step.py --step 6 --run-id <run-id>
```
