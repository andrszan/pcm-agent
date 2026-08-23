# 第 8 步：首次提交适用仓库

## 输入

- 运行状态位于 `project:08_initialize_repositories`；第 1 步记录的产品根是自身 top-level、`main`、unborn HEAD、空 index 的独立 Git 仓库。
- `steps/03.json`、`steps/04.json`、`steps/05.json`、`steps/06.json` 和 `steps/07.json` 均为 `status=success`，且其交接、组装来源和固定技术方案可重新核验。
- 第 4 步的每个适用 `frontend` / `backend` 已在 run-owned payload 中建立为自身 top-level、`main`、unborn HEAD、空 index 的独立 Git 仓库；不适用端不存在。
- 产品根 `.gitignore` 必须实际忽略每个适用子仓路径；产品根及适用子仓不存在未删除或未忽略的 `.coverage` 覆盖率数据库。

## 行为

步骤复用 `common/agent_decision_loop.py`，但 Git 规则仍由本步骤的 Python verifier 负责，不把公共循环扩展为 Git DSL。它只创建一个产品根 Claude Agent SDK session，领域键为 `initialize_repositories`，首条提示第一行显式调用 `/commit-changes`。

提示向 Agent 给出固定且有序的 `['root', *steps/04.json.outputs]` 权威仓库清单和白名单化组装事实。Agent 在同一任务中对每个彼此独立的仓库分别应用 `commit-changes` 的单仓合同，以 `expected_head=unborn` 核验基线，并将该仓当前全部合法变更创建为唯一初始基线提交。Python 不逐仓派发 Agent、不暂存、不提交。

Agent 不得创建或切换分支、merge、amend、reset、rebase 或 push；根仓不得纳入 `frontend`、`backend` 或 gitlink。最终 Agent 回复的最后一个非空行必须严格为：

```text
INITIAL_COMMITS_JSON={"repositories":[{"name":"root","sha":"完整SHA"},...]}
```

条目集合、顺序和完整 SHA 必须与权威仓库清单一致。

## 决策、核验与恢复

本步骤只维护仓库初始提交的 `DECISION_RULES` 与专属授权边界。新 conversation 的完整 XML system snapshot 由 `common/decision.py` 渲染，严格包含 `<role>`、`<project_context>`、`<responsibility>`、`<require>` 四段：AI-compatible 角色是实际使用 Claude Code Agent 的项目负责人、工程负责人、专业开发者和 Agent 专家；`assistant` 是其此前发给 Agent 的指令或结构化回复，`user` 是 Agent 返回的完整执行结果。项目上下文仅为有序仓库名称及相对路径、组装白名单投影和最小初始基线说明；恢复严格读取历史 `messages[0]`，不重渲染或覆盖。项目上下文只做标准 XML 转义。

第 8 步的 Git、严格 marker、`observed_heads` 与完成 verifier 均保持原有步骤私有逻辑，不进入公共循环。

统一决策仍只有 `completed`、`continue`、`blocked`：`continue` 使用同一 session；`blocked` 只接受不可替代的外部资源、合法 Git 作者身份或强制签名凭据等真实缺口。调用方可基于既有事实授权 Agent 继续，但不会授权修改工作树、改写历史或绕过核验。

`completed` 表示负责人根据 Agent 执行结果相信任务完成；其后 Python 核验每个仓库的 top-level、`main`、存在且干净的 HEAD、恰好一个无父提交，以及不使用 shallow 或 replace 历史；再核对末行 marker SHA。它还核验根提交树不含 `frontend`、`backend` 或 gitlink，根 `.gitignore` 实际忽略所有适用子仓。缺少提交或 marker 不合格时，向同一 session 发送固定 repair prompt；边界冲突直接 `failed`。写入 `blocked` 前也重新核验当前 Git 现场。

恢复状态保存 `initialize_repositories.observed_heads`，只接纳最近一次 Agent 回合观察到的 SHA。部分仓已经提交时，Python 不 reset、amend 或 rebase，而是在同一 session 中继续尚未完成的仓库。`failed` / `blocked` 的 `steps/08.json` 不被当作成功，也不阻止该 session 恢复；只有 `status=success` 才是幂等锚点。成功结果已经写入但 state 推进中断时，重跑只重验并推进，不覆盖成功锚点或再次调用 Agent。

## 输出

成功时 `steps/08.json` 使用统一字段，并额外保存：

- `applicable_repositories`：有序仓库名称列表；
- `initial_commits`：名称到完整 SHA 的映射；
- `repositories`：每仓 `name`、相对路径、`main`、HEAD 和干净工作树事实；
- `outputs: []`：本步骤不生成新的项目文件。

状态保存同名的仓库列表和提交证据，随后推进至 `project:09_engineering_architecture`。本步骤不 push。

## 已验证事实

专属 `unittest` 当前为 14 项，覆盖仅根仓和三仓、单一 Agent 调用、同 session repair、部分提交后 blocked 恢复、blocked 前 Git 复核、最近观察 SHA、防 shallow/replace、根 `.gitignore`、结果/state 写入中断以及 CLI。五步与公共循环定向测试实际为 71 项；全量测试实际输出为 109 项，其中公共循环 24 项、步骤测试 85 项；`compileall` 与 `git diff --check` 结果见本轮验证。

首个真实 run `step08-real-20260823-a` 保留为失败证据：第 1 步先后遇到代码围栏、Responses `incomplete` 和自创字段，收紧严格 JSON prompt 后同 run 成功；第 3 步首次 `ValidationError` 后同 run 重试成功；第 7 步 API 500 暴露 failed `07.json` 错误阻断恢复，修复为仅 `status=success` 可复用后同 session 成功。第 8 步则因管理模板快照的 `.coverage` 成为根仓未跟踪垃圾，Agent 按合同没有提交；决策模型重复要求“调用方授权”并耗尽 8 轮。该 run 未产生任何根、前端或后端提交。

修复后的 `step08-real-20260823-b` 第 0～5 步一次通过；第 6 步真实清除了 `.coverage` 并保持三仓 `main` / unborn / 空 index；第 7 步成功。第 8 步以唯一 session `64aa707c-268c-48c8-bb3f-f67f62abe75e` 完成，conversation 为 `system → assistant → user → assistant`，一次 Agent 回复和一次 `completed` 裁决。根、前端、后端的初始提交依次为 `c1eb33dfa5bda91a0d7f9aeeb41d8fefe10a6fca`、`5997213c34c09ea6ba4e740e35f9df77d2d45d82`、`5d8dd95d8c42370697d25e6ecaf400bab42785b3`；三仓均为 `main`、一个无父提交且工作树干净，根 tree 不含前端或后端，状态推进到 `project:09_engineering_architecture`。同 run 重跑幂等复用，SHA 不变且不再调用 Agent。

## 运行

```bash
cd /Users/zhou/resource/fireworks/ANDRSZAN/pcm-agent-skills/pcm-demo
uv run python run_step.py --step 8 --run-id <run-id>
uv run python -m unittest steps.step_08_initialize_repositories.test_step -v
```
