# 第 13 步：选择需求并建立统一需求分支

本步骤是纯 Python 的确定性节点：不调用 AI、Claude Agent 或 Skill，不修改产品文件，不提交、合并或 push。它直接消费 state 中的有序 `applicable_repositories`、仓库名称与路径，以及当前 `requirement_registry`，不回读历史 `steps/08.json`、`steps/12.json` 或复验 `source`。

注册表是需求生命周期真源。第 12 步负责静态目录的完整校验；本步骤只检查选择与恢复所需的字段、合法且忽略大小写后唯一的需求 ID、可比较的顺序、依赖引用和动态状态，不重跑连续顺序或依赖图校验。仓库描述允许附加字段，历史 `branch`、`worktree_clean` 不作为现场依据；路径边界和真实 Git 预检仍按下文执行。

## 运行

在 `pcm-demo/` 目录执行：

```bash
uv run python run_step.py --step 13 --run-id <run-id>
```

定向自动化测试：

```bash
uv run python -m unittest \
  steps.step_13_select_requirement.test_step \
  steps.step_13_select_requirement.test_cli \
  test_run_all test_run_step_retry -v
```

## 选择、分支与状态

Python 只从 `pending` 中选择全部依赖状态均为 `completed` 且 `order` 最小的需求。分支固定为 `req/<lowercase-id>`，并对第 8 步声明的全部适用仓库（包括 root）统一处理，不扫描目录、不按 TRD 缩小仓库范围、不硬编码三仓。

fresh 路径在任何 state 或 Git 写入前，对全部仓库完成全局预检：state 仓库路径必须精确对应 `workspace` 或 `workspace/<name>`，每仓为自身非符号链接 Git top-level、clean local `main`、有效且等于 local `main` 的 HEAD、没有目标分支，且没有进行中的 merge、rebase、cherry-pick 或 revert。Git 子进程保留普通环境并剔除全部 `GIT_*` 变量。

预检通过后，先原子写入：

- `active_requirement`：仅需求 ID；
- `requirement_cycle`：初始写入 `requirement_id`、`branch`、按仓名映射且每仓写入 `base_sha` 的 `repositories`，以及 `return_node_after_completion: "phase_1:select_requirement"`；后续步骤可以追加自身字段，但不得改变这些选择与基线证据；
- 选中注册表项：`active`，`completion: null`。

随后唯一的 fresh Git 写操作为：

```text
git switch -c <branch> <recorded-base-sha>
```

成功 result 只写入：

```text
steps/requirements/<requirement-id>/13.json
```

其中仓库 `path` 仅为 root 的 `.` 或其它仓库名；`outputs` 固定为空。先写 scoped success result，再将 state 推进到 `requirement:14_trd_design`、`step/current_step: 14`。

没有 `pending` 时，本步骤无副作用失败，阶段二转场留待后续实现；仍有 `pending` 但没有依赖满足候选时是注册表状态错误，也不创建伪需求 result。

## 恢复、保护与边界

intent 已写但只创建部分分支时，已存在目标分支必须精确指向记录 base 且 clean；未建立的仓必须仍为 clean `main`/base，才继续建立。目标分支已存在、当前位于 clean `main` 时，只允许恢复性 `git switch <branch>`。SHA、分支、工作树、进行中 Git 操作、仓库集合或 cycle 冲突均保留现场并失败，不自动回滚或清理。

完整 scoped success 已写但 state 尚未推进时，先只读复验所有仓库均在目标分支、clean，且 HEAD/local `main`/target 均等于记录 base，之后只补 state；`failed`、`blocked` 或残缺 scoped result 不阻断重跑，可由后续成功覆盖。state 已推进到后续节点时，第 13 步只校验自己拥有的活动需求、统一分支、仓库集合、每仓 `base_sha` 和 scoped success，允许第 14、15、17 步追加 `trd_path`、`development_session_id`、`tip_sha`、`merged` 等字段，并保持零 Git 操作。

`run_step.py` 不把第 13 步加入固定 result 成功白名单；它只由当前 `active_requirement`、cycle 的第 13 步核心投影和匹配的 scoped success 保护当前需求，不会保护其它历史需求。只有 state 仍位于 `phase_1:select_requirement` / step 13 时，失败才可写入当前 state 或 scoped result；误调历史步骤不得把后续合法节点降级为 `failed`。intent 后失败写当前需求的 scoped failure 并保留 cycle，intent 前失败不伪造 result。

JSON 结果通过同目录唯一临时文件和原子 replace 写入；固定旧临时文件名的符号链接不会被跟随。

## 自动化与真实验证

第 13 步本体 20 项、CLI 10 项，共 30 项定向测试通过；当前 PCM Demo 全量 288 项 `unittest`、`compileall common steps run_step.py`、`git diff --check` 和相关 IDE diagnostics 通过。测试覆盖确定性选择、全仓预检、intent/partial recovery、scoped result/state 恢复、后续 cycle/注册表字段兼容、历史步骤误调不降级、旧三字段 `source` 不阻断下一需求，以及受控错误原因可见、意外异常继续脱敏。

真实 run `step01-mendmark` 确定性选择 `BR-001`。初次执行记录 root base `0232d813...`；第 14 步前用户将新 TRD 命名规则提交到产品 root，使 root `main` 和旧需求分支前进。经用户明确选择后，先完整归档 run，确认三仓旧需求分支与各自 `main` 无独有提交并安全删除，只重置 BR-001 的第 13 步 cycle/result，再从最新 `main` 重跑。当前 scoped result 为 `steps/requirements/BR-001/13.json`，SHA-256 为 `bf202c6fc568f1b4e82efc7be86a094064fe22d8735eee8c7d6999061127cca1`；bases 为 root `a7d5509df6843a06315aa803d87285569b86e355`、frontend `dbab574dbe4d83a02323a750afd04de007565ac5`、backend `9682be837759c20f1a9ebbdf8fa2cfc09c2768d4`。BR-001 后续已完成第 14～18 步并返回选择节点。

第二轮首次执行暴露历史 `steps/12.json.source` 多出的 `root_main_sha` 被现行第 13 步重复 schema 复验拒绝。删除该跨步依赖后，同一失败现场重跑成功并建立三仓 `req/br-002`。第 14 步随后从负责人裁决失败现场零 Agent 恢复成功；当前流程已进入第 15 步，并因首次 Claude Agent SDK `api_error` 停止。
