# 第 18 步：程序化合并并完成需求

## 职责

本步骤只执行本地 Python 与 Git 同步，不调用 Agent、Skill、LLM、session 或 conversation。

它读取当前活动需求的第 17 步 scoped success、需求 cycle、适用仓库白名单与工作区仓库描述，对全部权威仓库按“非 root 原顺序、最后 root”的顺序执行安全的 fast-forward 合并和需求分支清理。前序交接允许增加与本步骤无关的字段；本步骤只读取 requirement、branch、仓库路径和 base/tip 等执行所需事实。

## Git 边界

每次读取均过滤全部 `GIT_*` 环境变量，并核验仓库自身 top-level、当前分支、HEAD、local `main`、需求分支、完整 porcelain 工作树与进行中的 merge、rebase、cherry-pick、revert、bisect 操作。

- 只接受当前 checkout 为 `main` 或活动需求分支；
- 合并阶段要求需求分支存在且等于记录的 `tip_sha`；
- `main == tip_sha` 表示已经合并；若 cycle 尚未标记，原子补写 `merged: true`，不重复 merge；
- `base_sha == tip_sha` 是合法 no-op；
- 只有 `main == base_sha` 且 `merged == false` 时才允许 `git switch main` 与 `git merge --ff-only <branch>`；
- 需求分支初始必须 clean；切回旧 `main` 后仅允许因需求分支新增忽略规则而暂时显现的纯 untracked 路径，合并完成后仍必须恢复为完全 clean；
- `main` 位于其它 SHA、已标记 merged 却仍在 base，或任何 Git 事实不一致时失败并保留现场；
- 所有仓库已合并后才清理分支。partial cleanup 恢复仅在所有仓库均已合并时允许某仓需求分支已不存在；
- 写命令白名单仅包含 `git switch main`、`git merge --ff-only <branch>` 与 `git branch -d <branch>`，不执行 reset、rebase、push、强制删除、自动解冲突或回滚。

## 完成与恢复

每仓完成后都要求 `main == HEAD == tip_sha`、工作树 clean、没有进行中的操作且需求分支已删除。

成功时先原子写入：

```text
steps/requirements/<ID>/18.json
```

结果使用公共 envelope，并以 root-first 顺序记录每仓：

```json
{
  "name": "root",
  "path": ".",
  "base_sha": "<base>",
  "tip_sha": "<tip>"
}
```

之后才把活动注册表项设为 `completed`、写入精确 completion `{ "step": 18 }`，清空 `active_requirement` 与 `requirement_cycle`，并返回 `phase_1:select_requirement` / step 13。

若完整 `18.json` 已写而 state 仍停在第 18 步，步骤只读核验最终 Git 事实并补写 state，不再执行 Git 写操作或覆盖 result。failed 或不完整的旧 result 不阻断重跑。

## 运行

```bash
uv run python run_step.py --step 18 --run-id <run-id>
```

## 验证

`test_step.py` 使用临时真实 Git 仓覆盖动态多仓顺序、base/tip no-op、部分 merge、partial cleanup、result→state 恢复、旧失败 result 重跑、上游增量字段、dirty/操作中/detached/non-fast-forward 拒绝，以及 `GIT_*` 过滤和 Git 写命令白名单。`test_cli.py` 覆盖同步调度、真实临时仓 CLI、scoped 结果路径、失败脱敏、完成状态防降级和完整 success 保护。

第 18 步本体 10 项、CLI 5 项，共 15 项；PCM Demo 全量 294 项 `unittest`、`compileall common steps run_step.py` 和 `git diff --check` 通过。独立只读审查最终无高、中置信发现。

真实 `step01-mendmark` 已将 frontend、backend、root 的 local main 分别 ff-only 到 `65764dee0b2655f1c674ec36fee527861ea5043c`、`0e0bf9bb37e2abcf8c923c0fa4611c671da87640`、`62ac0aea0a69ea95d6382adfc276adce808be964`。三仓当前均在 main、clean、`req/br-001` 已删除、无 merge commit且未 push；BR-001 已写为 completed，state 返回 step 13。
