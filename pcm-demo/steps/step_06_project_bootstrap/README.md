# 第 6 步：项目化基础工程

## 输入

- 运行状态位于 `project:06_bootstrap_foundation`，产品根仍是零提交 `main`。
- `steps/02.json` 引用两份工作区内非空、非符号链接的产品定义文档。
- `steps/04.json` 提供实际适用工程目录、模板来源和组装证据；第 3 步选型只用于核验该组装事实。
- `steps/05.json` 成功，且 `docs/requirements/项目准备清单.md` 存在并可读取。
- 适用工程内部的 README、manifest、锁文件、配置、代码和测试由 Agent 按当前现场读取，不由 Python 重复建模。

## 行为

在产品项目根新建独立 Claude session，显式调用 `/project-bootstrap`。Agent 负责有限范围项目化：落实项目身份、基础配置、README、必要的共享视觉基线和模板测试迁移；经引用检查处理误导性的模板残留；按现有锁文件执行适用安装、检查、测试、构建、启动、真实浏览器检查和基础联调。

本步骤不重选或重新组装模板，不实现业务功能、总体技术方案或工程架构，不初始化前后端独立 Git 仓库，也不暂存、提交、建分支、合并或推送。Python 不重复执行 Agent 的安装、构建和联调逻辑，只核验前序交接、适用目录、根仓库仍为零提交 `main`、没有暂存内容且适用工程没有提前出现 `.git`。

Agent 每轮完整回复都交给 AI-compatible 决策模型。步骤专属结构化决定只允许：

- `completed`：完整回复已证明所有项目化完成条件满足；
- `continue`：保存完整 `answer` 并恢复同一 Claude session 继续；
- `blocked`：只用于当前环境无法取得的不可替代外部资源。

单次 Agent 上限为 48 turns、`$16`，同一历史累计最多 8 轮决定。预算或 turn 上限保存并恢复同一 session。历史保存初始指令、每轮 Agent 完整回复、每次结构化决定和固定完成声明。

## 输出与恢复

成功时 `steps/06.json.outputs` 记录第 4 步实际适用工程目录，先写步骤结果，再推进到 `project:07_solution_design`。如果没有适用基础工程，则无副作用跳过并记录 `applicable: false`。

恢复时：

- 已保存 Agent 回复但未决策：先恢复决策，不重复调用 Agent；
- 已保存 `continue`：原样恢复其 `answer`；
- 已保存 `blocked`：直接恢复阻塞；
- 已保存 `completed` 或固定完成声明但状态推进中断：重新核验目录和 Git 边界后写入或复用成功结果；
- 状态已经推进到下一节点：核验完整成功现场后幂等复用，不再次调用 Agent 或决策模型。

## 运行

```bash
cd /Users/zhou/resource/fireworks/ANDRSZAN/pcm-agent-skills/pcm-demo
uv run python run_step.py --step 6 --run-id <run-id>
```
