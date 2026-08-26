# 第 17 步：统一提交需求变更

## 职责

本步骤只负责调度 `commit-changes` 并记录提交结果：

- 仓库集合只来自运行状态中的有序 `applicable_repositories` 白名单；
- 有待提交变更时，在产品根调用一次 Claude Agent；
- 每个仓库由 `commit-changes` 自行检查完整 diff、规划提交、精确暂存并创建本地提交；
- Python 最终只核验仓库边界和工作树是否 clean，并记录各仓 `tip_sha`；
- 不 merge、不删除分支、不 push，也不把需求标记为 `completed`。

提交内容完整性、提交分组、空提交、提交消息和 Git 历史操作属于 `commit-changes` 的职责。Python 不再重复实现工作树 fingerprint、blob/tree hashing、merge commit 或净零提交取证。

## 输入与最小前置检查

步骤接受：

- `phase_1_requirement_development` / `requirement:17_commit` / step 17；
- 唯一 active requirement、对应 requirement cycle 和完整 scoped `16.json` success；
- 统一 `req/<lowercase-id>` 分支；
- 有序仓库白名单及每仓 `base_sha`。

Agent 调用前，Python 对每个白名单仓库只检查：

- 路径不是符号链接，且是该仓自身 Git top-level；
- 当前分支是统一需求分支；
- local `main == base_sha`；
- `HEAD` 等于需求分支 ref；
- fresh 且尚无 commit session 时，`HEAD == base_sha`。

clean 判断固定使用：

```text
git status --porcelain=v1 --untracked-files=all
```

因此不受仓库本地 `status.showUntrackedFiles` 配置影响。

## 单一 direct session

全仓 fresh clean 时直接记录 `tip_sha = base_sha`，零 Agent 调用，不制造空提交。

存在 dirty 仓时，步骤直接调用 `common.claude_agent.run_claude()`：

- 首次 prompt 首行是 `/commit-changes`，并列出不可扩大的仓库白名单；
- 不调用 AI-compatible 负责人模型，不创建 decision conversation；
- 每次 `run()` 最多调用一次 Agent，不在同次执行中自动 repair 或 continue；
- init 更新一取得 session ID 就写入 `state.claude_sessions.requirement_commit_<ID>`；
- 调用异常或正常返回后仍 dirty 时，保留 session 和现场并返回 failed；
- 下次运行只恢复同一 session 一次，恢复提示不再包含 slash command；
- 已有 session 时，即使仓库已经 clean，也必须先取得一次正常 Agent 结束结果，不能用 clean 现场掩盖异常终止。

Agent 结果必须是正常 `ClaudeRunResult.success`，且没有 API、exception、error 或异常终止；最终完成仍以白名单仓库真实 Git facts 为准，不解析 Agent 自然语言回复。

## 完成与恢复

完成时每仓必须满足：

- 仍位于统一需求分支；
- local `main == base_sha`；
- `HEAD` 等于需求分支 ref；
- `git status --porcelain=v1 --untracked-files=all` 为空。

成功先写：

```text
steps/requirements/<ID>/17.json
```

每仓只记录：

```json
{
  "name": "root",
  "path": ".",
  "base_sha": "<base>",
  "tip_sha": "<tip>"
}
```

随后 cycle 写入 `{base_sha, tip_sha, merged: false}`，并推进 `requirement:18_merge` / step 18。需求仍为 active，`completion` 仍为 `null`。

完整 success result 已写但 state 尚未推进时，只按当前 Git facts 补 state，不调用 Agent。已进入 step 18 后，第 17 步只核验 result/cycle 结构，不读取工作区或 Git，也不迁移、清理旧实现留下的 fingerprint、conversation 或 session 字段。

## 运行

```bash
uv run python run_step.py --step 17 --run-id <run-id>
```

## 验证

现行精简实现包含第 17 步本体 10 项、CLI 3 项，共 13 项测试，覆盖：

- 动态多仓白名单和全 clean 零 Agent；
- 产品根一次 direct Agent 调用和 session 即时保存；
- init 后异常、正常返回仍 dirty、非正常但已 clean 的同 session 单次恢复；
- symlink 仓库拒绝和未跟踪文件 clean 判断；
- 分支/main/target 边界；
- result→state 恢复和 step18 旧字段兼容；
- CLI 脱敏 failed 与完整 success 保护。

PCM Demo 全量 282 项 `unittest`、`compileall common steps run_step.py` 与 `git diff --check` 通过。独立只读审查最终无高、中置信发现。

历史真实 run `step01-mendmark` 曾由旧实现创建 root 2 个、frontend 1 个、backend 1 个本地提交，并推进到 `requirement:18_merge`。这些提交 SHA、session 与 conversation 是历史执行事实，但旧 fingerprint、负责人 `completed` 和 decision conversation 不再是现行合同条件。

当前真实 run 已在 step 18，没有回退或重跑 fresh 提交。现行精简代码已完成 advanced 幂等兼容验证：使用不可用 LLM 配置执行第 17 步时不调用 Agent，state、`17.json` 和旧 conversation 的 SHA-256 均保持不变。
