# 第 8 步：首次提交适用仓库

## 输入

- 运行状态位于 `project:08_initialize_repositories`，第 4 步结果 `steps/04.json` 为 `status=success`。
- 权威仓库严格且有序地为产品根 `root` 与 `steps/04.json.outputs` 中成功组装的适用仓库；不从固定目录、历史状态或 Agent 回复推断仓库。
- 每个权威路径必须是非符号链接目录，且其自身 Git top-level 与该路径一致、当前分支为 `main`。

## 行为

步骤名仍为“首次提交适用仓库”。它是第一次全仓提交检查和形成干净基线的节点，不再要求仓库处于 unborn HEAD、产生提交或证明提交历史形态。

Python 生产逻辑对每个权威仓库只执行三个只读 Git 命令：`git rev-parse --show-toplevel`、`git branch --show-current` 和 `git status --porcelain`。前两项确认仓库边界和 `main`，最后一项为空即为工作区及暂存区干净。Python 不执行 `add`、`commit`、`reset`、`amend`、`rebase` 或其它 Git 写操作。

创建 conversation/session 或写入 `running` 前，Python 先读取全部权威仓库的事实：若均干净，零 Agent 调用、零决策模型调用，直接写入成功，summary 说明已经形成全仓干净基线。任一仓库 dirty 时，才在产品根创建一个 Claude Agent SDK session，领域键为 `initialize_repositories`，显式使用中模型和 `medium` effort，首条提示第一行调用 `/commit-changes`。提示只给有序权威仓库清单和边界：只处理清单内已有变更、各仓分别完成必要提交、不得创建或切换分支、改写历史或 push，完成后各仓必须仍在 `main` 且干净。产品工作区根的 `.agents/`、`.claude/` 和 `plugins-lock.json` 是仓库组建时从已定稿权威能力模板取得的只读提交输入，只允许读取、核对 Git 状态、精确暂存并原样提交；不得创建、修改、删除、移动、格式化、清理、忽略或重写，也不得因版本、许可证、测试产物判断或权限安全偏好要求修复。全部 Git 写操作均由 Agent 负责。

## 决策、核验与恢复

步骤复用 `common/agent_decision_loop.py`，但多仓现场读取、完成核验、结果与状态推进仍由本步骤私有实现；公共循环不导入步骤代码，也不成为 Git DSL。本步骤仅维护仓库清理的 `DECISION_RULES` 与授权边界。新 conversation 的完整 XML system snapshot 由 `common/decision.py` 渲染；恢复严格读取历史 `messages[0]`，不重渲染或覆盖。

统一决策仍只有 `completed`、`continue`、`blocked`。所有决策轮次和固定 repair prompt 都保留同一能力模板合同：`.agents/`、`.claude/` 和 `plugins-lock.json` 只可原样提交，不得授权 Agent 修改、删除或按版本、许可证、测试产物判断和权限安全偏好进行修复。`completed` 后 Python 重新读取每个权威仓库：全部干净即成功；仍有 dirty 仓库则发送固定 repair prompt，并在同一 session 继续。`blocked` 后也重新读取现场：已经全干净则直接成功，仍 dirty 才保存 `blocked`。恢复先读当前仓库事实；全干净直接成功，仍 dirty 时恢复原 session；若已有 Agent 执行事实但原 session、conversation 引用或历史文件缺失，则返回 `failed` 并保留现场，不能静默建立新会话。`blocked` 只用于不可替代的外部资源、合法 Git 作者身份或强制签名凭据等真实缺口；调用方可依据既有事实授权继续，但不能授权切换分支、改写历史或绕过检查。

只有 `status=success` 是幂等锚点。成功后的状态位于第 9 步入口时，后续出现 dirty 权威仓库会拒绝复用，避免第 8 步替后续步骤提交修改。已有旧 success 在干净现场重跑时按当前 schema 归一化；成功结果已经写入但状态推进中断时，重跑只重验并推进，不再次调用 Agent。

## 输出

成功时 `steps/08.json` 使用统一字段，并额外保存：

- `applicable_repositories`：有序仓库名称列表；
- `repositories`：每仓 `name`、相对路径 `path`、`branch` 与 `worktree_clean`；
- `outputs: []`：本步骤不生成新的项目文件。

状态保存同一仓库事实，但 `path` 为绝对路径，随后推进至 `project:09_engineering_architecture`。本步骤不 push，也不保存 `initial_commits`、`head` 或初始提交证据。

## 已验证事实

第 8 步专属 `unittest` 为 17 项；公共循环为 24 项；第 4、6、7 步相关回归为 31 项；第 2/5/6/7/8 步与公共循环定向测试合计 74 项（6+10+9+8+17+24）；全量 `unittest` 为 112 项。`compileall` 与 `git diff --check` 均已通过；IDE 对本步骤代码和测试无诊断，独立审查无高、中问题。

当前合同已在真实 run 目录 `pcm-demo/runs/step01-mendmark` 和产品工作区 `/Users/zhou/resource/fireworks/ANDRSZAN/pcm-products/mendmark` 完成集成验证。run 目录名与 state 内历史 `run_id` 不一致是既有已知事实，不影响本次按 state、产品路径和现场进行核验。权威仓库为 `root`、`frontend`、`backend`，第 4 步 `outputs` 为 `frontend`、`backend`；首次执行前三仓均为自身 top-level、`main`、dirty 且 HEAD 不存在。

首次执行只创建一个 `initialize_repositories` session：`f6d42df8-13e5-437b-ada3-eef1015ecc87`。Agent 尝试内置 Explore 时遇到环境未识别模型 `gpt-5.6-sol[1m]`，没有 ResultMessage、没有 Git 变化，进程挂起后停止；session、conversation 和 init 证据均已保存。这是环境内部子代理问题，不是第 8 步业务或 Git 逻辑失败。仅在这个 Git 忽略的真实 run 历史中追加普通恢复指令“不要使用子代理/Explore，直接工具完成”，生产 prompt 和代码未改变；重跑恢复同一 session。

恢复后 Agent 先创建 frontend `dbab574dbe4d83a02323a750afd04de007565ac5` 与 backend `9682be837759c20f1a9ebbdf8fa2cfc09c2768d4` 两个本地提交，未 push；随后针对根仓运行时产物和 `.agents/plugins/superpowers/.git` 请求决策。AI-compatible 负责人返回 `continue`：删除 61 个 `.in_use/*`、`.orphaned_at`、`.coverage` 运行时产物，补充 `.gitignore` 规则，移除 superpowers 嵌套 `.git` 并按普通受控插件快照提交，不采用 submodule。同一 session 继续后，root 创建三个本地提交：`02ba4c1`（产品与技术基线）、`ae72c31`（Agent 规范与 Skills）、`5eeeacd217bbd27e03483b1b6d32915c721aadd9`（插件快照），未 push。

最终 conversation 共 7 条，角色顺序为 `system → assistant 初始 → assistant 恢复 → user → assistant continue → user → assistant completed`。Agent 最终正常 `success`，26 turns，约 `$1.859406`，session 未变化。Python 只读 verifier 随后写入 `steps/08.json` 的 `success`：`applicable_repositories` 为 `root/frontend/backend`，result 使用相对路径，state 使用绝对路径，并推进到 `project:09_engineering_architecture`。

独立 Git 核验确认：root HEAD 为 `5eeeacd217bbd27e03483b1b6d32915c721aadd9`、共 3 个提交；frontend HEAD 为 `dbab574dbe4d83a02323a750afd04de007565ac5`、共 1 个提交；backend HEAD 为 `9682be837759c20f1a9ebbdf8fa2cfc09c2768d4`、共 1 个提交；三仓均在 `main` 且 `status --porcelain` 为空。该事实证明当前合同允许每仓产生 0、1 或多个提交，不要求唯一无父提交。同 run 再次执行第 8 步时直接以 clean 现场幂等成功，conversation 仍为 7 条，未再次调用 Agent 或决策模型，三仓 SHA 不变。

backend 提交阶段的 Agent 摘要报告 Ruff、格式和 build 通过，`pytest` 为 14 passed、1 skipped；跳过项是需要显式 `DB_*` 的数据库集成测试。这是 Agent 的提交摘要，不是本次 Python verifier 的完成条件，也不改变第 6 步既有项目化验证事实。

`step08-real-20260823-a` 与 `step08-real-20260823-b` 继续仅作为**旧“唯一初始提交证明”合同下的历史运行事实**。前者因模板快照的 `.coverage` 成为根仓未跟踪垃圾，Agent 未提交，决策模型重复索取调用方授权并耗尽 8 轮，未产生三仓提交；后者使用 session `64aa707c-268c-48c8-bb3f-f67f62abe75e`，曾产生 root `c1eb33dfa5bda91a0d7f9aeeb41d8fefe10a6fca`、frontend `5997213c34c09ea6ba4e740e35f9df77d2d45d82`、backend `5d8dd95d8c42370697d25e6ecaf400bab42785b3` 三个提交并推进到第 9 步入口。当前合同已经由 `step01-mendmark` 真实验证，但首次成功包含 run-local 恢复指令，不能据此宣称环境内部子代理问题已经解决或不再需要恢复。

## 运行

```bash
cd /Users/zhou/resource/fireworks/ANDRSZAN/pcm-agent-skills/pcm-demo
uv run python run_step.py --step 8 --run-id <run-id>
uv run python -m unittest steps.step_08_initialize_repositories.test_step -v
```
