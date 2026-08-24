# 第 13 步：选择需求并建立统一需求分支

本步骤是纯 Python 的确定性节点：不调用 AI、Claude Agent 或 Skill，不修改产品文件，不提交、合并或 push。它严格消费第 8 步的有序 `applicable_repositories` 与第 12 步的静态 catalog/注册表；需求 ID 必须符合 `[A-Za-z0-9][A-Za-z0-9_-]*`，且忽略大小写后唯一。

## 运行

在 `pcm-demo/` 目录执行：

```bash
uv run python run_step.py --step 13 --run-id <run-id>
```

定向自动化测试：

```bash
uv run python -m unittest \
  steps.step_12_initialize_requirement_registry.test_step \
  steps.step_12_initialize_requirement_registry.test_cli \
  steps.step_13_select_requirement.test_step \
  steps.step_13_select_requirement.test_cli -v
```

## 选择、分支与状态

Python 只从 `pending` 中选择全部依赖状态均为 `completed` 且 `order` 最小的需求。分支固定为 `req/<lowercase-id>`，并对第 8 步声明的全部适用仓库（包括 root）统一处理，不扫描目录、不按 TRD 缩小仓库范围、不硬编码三仓。

fresh 路径在任何 state 或 Git 写入前，对全部仓库完成全局预检：state 仓库路径必须精确对应 `workspace` 或 `workspace/<name>`，每仓为自身非符号链接 Git top-level、clean local `main`、有效且等于 local `main` 的 HEAD、没有目标分支，且没有进行中的 merge、rebase、cherry-pick 或 revert。Git 子进程保留普通环境并剔除全部 `GIT_*` 变量。

预检通过后，先原子写入：

- `active_requirement`：仅需求 ID；
- `requirement_cycle`：`requirement_id`、`branch`、按仓名映射且只含 `base_sha` 的 `repositories`，以及 `return_node_after_completion: "phase_1:select_requirement"`；
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

完整 scoped success 已写但 state 尚未推进时，先只读复验所有仓库均在目标分支、clean，且 HEAD/local `main`/target 均等于记录 base，之后只补 state；`failed`、`blocked` 或残缺 scoped result 不阻断重跑，可由后续成功覆盖。state 已推进到第 14 步时只核验 current requirement 的 scoped success，零 Git 操作，以免拒绝后续步骤合法产生的 dirty 现场。

`run_step.py` 不把第 13 步加入固定 result 成功白名单；它只由当前 `active_requirement` 和匹配 cycle 定位唯一 scoped success。intent 后失败写当前需求的 scoped failure 并保留 cycle；intent 前失败不伪造 result。完整 scoped success 保护当前 requirement 的 result/state，不会保护其它历史需求。

JSON 结果通过同目录唯一临时文件和原子 replace 写入；固定旧临时文件名的符号链接不会被跟随。

## 自动化与真实验证

第 12 步本体 11 项与 CLI 6 项，共 17 项；第 13 步本体 19 项与 CLI 9 项，共 28 项；两步定向 45 项、全量 222 项 `unittest` 通过。`compileall`、`git diff --check` 与 IDE 诊断通过；独立审查的 3 项中置信问题已修复，复核无高、中置信发现。Ruff 未安装，未执行。

真实 run `step01-mendmark` 确定性选择 `BR-001`。scoped result 为 `steps/requirements/BR-001/13.json`，SHA-256 为 `d37d9dfdaa6ba5c885842f0f6fc6046b027bd11454441182093a185f7fdaacab`；state SHA-256 为 `a6fc435c28010061ca3dd369b571221193b6a534e0d977158cdce215a8f2bc48`，状态为 `phase_1_requirement_development` / `requirement:14_trd_design`、`step/current_step: 14`，`active_requirement: "BR-001"`，注册表为 13 pending、0 completed。root/frontend/backend 均为 clean `req/br-001`，base 分别为 `0232d8136c075cb61a6617a95e1504b67bd9acd1`、`dbab574dbe4d83a02323a750afd04de007565ac5`、`9682be837759c20f1a9ebbdf8fa2cfc09c2768d4`；各仓 HEAD、local `main` 和 target 相等，ahead/behind 均为 0。没有产品文件改动、新 commit、merge、push、session、conversation、模型、Agent 或 Skill 调用；幂等重跑后 result/state 字节和三仓 ref 均不变。第 14 步尚未实现。
