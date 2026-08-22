# 第 7 步：总体技术方案

## 输入

- 运行状态位于 `project:07_solution_design`，产品根仍是第 1 步初始化的独立 Git `main` 仓库。
- `steps/02.json` 引用两份工作区内非空、非符号链接的产品定义文档。
- `steps/04.json` 提供实际适用工程、模板 ID、路径、分支、commit SHA 和组装证据；传给 Agent 的来源信息经过脱敏投影。
- `steps/05.json` 成功，且 `docs/requirements/项目准备清单.md` 存在并可读取。
- `steps/06.json` 成功，且其 `outputs` 与第 4 步实际适用工程一致。
- 适用工程内部的 README、manifest、锁文件、配置、代码和测试由 Agent 按当前现场读取，不由 Python 重复建模。

## 行为

在产品项目根新建独立 Claude session，显式调用 `/solution-design`。Agent 负责读取当前工程事实，创建或更新 `docs/design/技术方案.md`，明确系统边界、主要技术选择、交付单元、跨单元协作、关键风险和待确认事项，并区分当前事实、已确认决定、目标状态和假设。

本步骤不重新选择或组装模板，不实现业务功能，不修改业务代码、配置、迁移或基础设施，不设计具体需求或工程目录架构，也不初始化、暂存、提交、建分支、合并或推送 Git。风险、假设和待确认事项可以保留，不因它们存在而阻塞完成。

每轮 Agent 完整回复都交给专属 AI-compatible 决策模型。决策只允许：

- `completed`：固定技术方案文档已真实写入，Agent 回复说明方案已完成并与工程事实核对；
- `continue`：文档、设计内容或事实核对仍有可由当前工程和资料解决的缺口；
- `blocked`：只用于当前环境无法取得的不可替代外部资源。

Python 不解析 Markdown 章节或判断技术方案本身，只核验固定文档是非空普通文件、Agent session/cwd/Skill 边界、前序交接、根仓暂存区为空且适用工程没有新增嵌套 Git；Agent 完整回复在落盘和发送给决策模型前会按敏感信息模式脱敏。

## 输出与恢复

成功时：

- `steps/07.json.outputs` 固定为 `docs/design/技术方案.md`；
- 保存 `claude_sessions.solution_design`；
- 保存 `conversations/solution_design.json` 中的初始指令、Agent 完整回复、结构化决定和固定完成声明；
- 先写步骤结果，再将状态推进到 `project:08_initialize_repositories`。

恢复时：

- 已保存 Agent 回复但未决策：先恢复决策，不重复调用 Agent；
- 已保存 `continue`：将其 `answer` 原样发回同一 session；
- 已保存 `blocked`：直接恢复阻塞；
- 已保存 `completed` 或固定完成声明但状态推进中断：重新核验文档和交接后补写或复用成功结果；
- 状态已经推进到第 8 步节点：核验完整成功现场后幂等复用，不再次调用 Agent 或决策模型。

## 运行

```bash
cd /Users/zhou/resource/fireworks/ANDRSZAN/pcm-agent-skills/pcm-demo
uv run python run_step.py --step 7 --run-id <run-id>
```
