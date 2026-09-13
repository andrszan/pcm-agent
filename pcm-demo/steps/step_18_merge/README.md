# 第 18 步：程序化合并并完成需求

## 职责

本步骤只执行本地 Python 与 Git 同步，不调用 Agent、Skill、LLM、session 或 conversation。

它读取当前活动需求的第 17 步 scoped success、需求 cycle、适用仓库白名单与工作区仓库描述，对全部权威仓库按“非 root 原顺序、最后 root”的顺序执行安全的 fast-forward 合并和需求分支清理。前序结果须属于第 17 步和当前需求，状态为适用且成功、无 blocked 或 error，统一分支和逐仓名称、路径、base/tip 与 cycle 一致；不要求固定 `name`、非空 `summary` 或空 `outputs`，也不因增加其它元数据阻断合并。

## Git 边界

每次读取均过滤全部 `GIT_*` 环境变量，并核验仓库自身 top-level、当前分支、HEAD、local `main`、需求分支、完整 porcelain 工作树与进行中的 merge、rebase、cherry-pick、revert、bisect 操作。

- 只接受当前 checkout 为 `main` 或活动需求分支；
- 合并阶段要求需求分支存在且等于记录的 `tip_sha`；
- 合并与 no-op 均要求 `base_sha ≤ 当前 main ≤ tip_sha`，其中 `≤` 为对捕获 SHA 验证的祖先或相等关系；原始 base 不改写；
- `main == tip_sha` 表示已经合并；若 cycle 尚未标记，原子补写 `merged: true`，不重复 merge；
- `base_sha == tip_sha` 是合法 no-op；
- `merged == false` 且 main 尚未到达 tip 时允许切换到 main；切换后重读引用，要求 main/HEAD 仍为本次捕获的 main，target 仍为保存 tip，再执行 `git merge --ff-only <tip_sha>`；
- 需求分支初始必须 clean；切回旧 `main` 后仅允许因需求分支新增忽略规则而暂时显现的纯 untracked 路径，合并完成后仍必须恢复为完全 clean；
- main 分叉、领先 tip、未包含原始 base、已标记 merged 却未到达保存 tip，或任何 Git 事实不一致时失败并保留现场；
- 所有仓库已合并后才清理分支。partial cleanup 恢复仅在所有仓库均已合并时允许某仓需求分支已不存在；
- 写命令白名单仅包含 `git switch main`、`git merge --ff-only <tip_sha>` 与 `git branch -d <branch>`，不执行 reset、rebase、push、强制删除、自动解冲突或回滚。

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

`test_step.py` 使用临时真实 Git 仓覆盖动态多仓顺序、base/tip no-op、中间 main 快进到保存 tip、部分 merge、partial cleanup、result→state 恢复、旧失败 result 重跑、上游展示字段变化与增量元数据兼容、成功状态和逐仓合并事实不一致时拒绝写入、dirty/操作中/detached/non-fast-forward 拒绝，以及 `GIT_*` 过滤和 Git 写命令白名单。`test_cli.py` 覆盖同步调度、真实临时仓 CLI、scoped 结果路径、失败脱敏、完成状态防降级和完整 success 保护。

在 `pcm-demo/` 运行：

```bash
uv run python -m unittest steps.step_18_merge.test_step steps.step_18_merge.test_cli -v
```
