# 第 17 步：统一提交需求变更

## 职责

本步骤在产品项目根创建一个 requirement-scoped Claude Agent session，并在初始提示中显式调用一次 `/commit-changes`。Agent 只处理运行状态中有序 `applicable_repositories` 白名单内的仓库，对每个仓库独立检查和提交：dirty 仓可按功能结果创建一个或多个本地提交，clean 仓不制造空提交。

本步骤不实现或修复产品内容，不创建或切换分支，不 merge、rebase、reset、amend、改写历史或 push，也不把需求标记为 `completed`。第 18 步负责后续 ff-only 合并和生命周期完成。

## 输入与前置条件

步骤只接受：

- `phase_1_requirement_development` / `requirement:17_commit` / step 17；
- 唯一 active requirement、对应 requirement cycle 和完整 scoped `16.json` success；
- state 中有序、非空且以 root 开头的 `applicable_repositories` 与仓库绝对路径；
- 每仓 cycle `base_sha` 和统一 `req/<lowercase-id>` 分支。

fresh 时 Python 逐仓只读核验：

- 路径是该仓自身 Git top-level；
- 当前分支是统一需求分支；
- `HEAD`、local `main`、需求分支 ref 均等于 `base_sha`；
- index clean，且没有 merge、rebase、cherry-pick、revert 或 bisect；
- 工作树可以 dirty。

Python 不扫描白名单外 Git 仓库，不硬编码 frontend/backend，不读取完整 diff 或规划提交。

## 单 session 与内容保护

只要存在 dirty 仓，步骤就在产品根使用单一 `requirement_commit_<ID>` session。一个 session 不等于一次 SDK turn：负责人 `continue`、完成 repair、blocked 解除和进程中断都恢复同一 session；初始 `/commit-changes` 只出现一次。

首次 Agent 调用前，state 为每仓保存：

- 是否 dirty；
- 一个 Git-visible 工作树 tree fingerprint。

fingerprint 由 index、unstaged 和未跟踪非 ignored 内容共同构成；普通文件使用 `git hash-object --path=<relative> --stdin`，遵循 `.gitattributes` clean filter、`working-tree-encoding` 和 EOL 规范化。恢复和完成时重新比对该 fingerprint，防止提交过程中修改、替换或丢弃已经验证的内容。最终还要求 `base..tip` 中没有 merge commit。

## 完成条件与结果

所有仓库必须同时满足：

- 仍在统一需求分支，local `main == base_sha`，`HEAD` 等于需求分支 ref；
- 工作树和 index clean，无进行中的 Git 历史操作；
- 初始 dirty 仓的 tip 是 base 的严格后代、文件树与 base 不同，且最终 HEAD tree 等于首次工作树 fingerprint；
- 初始 clean 仓保持 `tip_sha == base_sha`。

成功结果写入：

```text
steps/requirements/<ID>/17.json
```

`outputs` 恒为 `[]`，每仓只保存：

```json
{
  "name": "root",
  "path": ".",
  "base_sha": "<base>",
  "tip_sha": "<tip>"
}
```

随后 cycle 每仓写入 `{base_sha, tip_sha, merged: false}`，状态推进至 `requirement:18_merge` / step 18；active requirement 和 `completion: null` 保持不变。

完整 success result 已写而 state 尚未推进时，重跑按 result 与当前 Git 事实补 state，不再次调用 Agent。推进到第 18 步后，第 17 步幂等重跑只验证 result/state 结构，不读取 Git 或调用模型，避免与第 18 步后续合法 ref 变化冲突。

## 运行

```bash
uv run python run_step.py --step 17 --run-id <run-id>
```

## 自动化与真实验证

第 17 步本体 11 项、CLI 4 项，共 15 项测试通过，覆盖：

- 动态多仓白名单和单产品根 session；
- clean/dirty 混合、无空提交和多提交；
- 同 session repair、partial multi-repository commit 恢复；
- 首次内容替换/丢失、merge commit、空或净零差异提交拒绝；
- `.gitattributes` clean filter 正常提交；
- result→state 中断恢复、推进后幂等和 CLI success 保护。

PCM Demo 全量 283 项 `unittest`、`compileall common steps run_step.py` 与 `git diff --check` 通过。独立只读审查修复了首次内容完整性、完成后 merge commit 和 Git attributes 规范化问题，最终无高、中置信发现。

真实 run `step01-mendmark` 使用 session `a00760f3-1760-4e2c-a985-477831a9277f`：conversation 为 `system → assistant 初始 → user Agent 回复 → assistant completed`，初始 `/commit-changes` 恰好一次；Agent normal success，58 turns，`$4.334054`。

实际提交结果：

- root：base `a7d5509df6843a06315aa803d87285569b86e355` → tip `62ac0aea0a69ea95d6382adfc276adce808be964`，2 个提交；
- frontend：base `dbab574dbe4d83a02323a750afd04de007565ac5` → tip `65764dee0b2655f1c674ec36fee527861ea5043c`，1 个提交；
- backend：base `9682be837759c20f1a9ebbdf8fa2cfc09c2768d4` → tip `0e0bf9bb37e2abcf8c923c0fa4611c671da87640`，1 个提交。

三仓均仍在 `req/br-001`，local `main` 未移动，工作树/index clean，无 merge commit、merge 或 push。BR-001 仍 active/completion null，state 位于 `requirement:18_merge`。以不可用 LLM 配置幂等重跑后，state/result/conversation SHA-256 分别保持：

- `aa591d02093ec29d9b4ec2b7d06dfd4e1aac22a2097a19d864fb07e47a15512e`；
- `2f76b43287404bc828e1dfbe9df52a90fd53b3a388eaf36f3e7c54cc82fb8439`；
- `93978ff7dcdfa3479d094f0085807bae2166b3dbaffdf1c69c3973d096fc9d87`。
