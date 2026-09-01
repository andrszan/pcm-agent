# 第 17 步：统一提交需求变更

## 职责

本步骤在产品根使用一个 requirement-scoped Claude session 调用 `commit-changes`，并通过公共 Agent 决策循环处理纯 Git 提交动作中的确认和阻塞：

- 当前需求的实现、适用测试、真实验证、审查与规则复盘，均作为不可在提交任务中重新打开的权威完成事实；
- 仓库集合只来自有序 `applicable_repositories` 白名单；
- `commit-changes` 只负责读取 Git 状态和候选 diff、规划提交、精确暂存、创建本地提交及提交后 Git 核验；
- AI-compatible 负责人只能返回纯 Git 提交范围内的 `completed / continue / blocked`，不得授权重新开发、测试、构建、浏览器验收或审查；
- `continue`、blocked 解除和 completed 后 repair 都恢复同一 Claude session；
- Python 最终只核验仓库边界和 clean 状态，并记录每仓 `tip_sha`；
- 不修改、删除、格式化、忽略或清理文件，不 merge、不删除分支、不 push，也不把需求标记为 `completed`。

Python 不重复实现工作树 fingerprint、blob/tree hashing、Git attributes、merge commit、空提交或净零差异取证；这些提交语义由 `commit-changes` 负责。

## 输入与最小 Git 边界

步骤接受：

- `phase_1_requirement_development` / `requirement:17_commit` / step 17；
- 唯一 active requirement、对应 cycle 和完整 scoped `16.json` success；
- 统一 `req/<lowercase-id>` 分支；
- 有序仓库白名单及每仓 `base_sha`。

Python只检查：

- 仓库路径不是符号链接，且是该仓自身 Git top-level；
- 当前分支是统一需求分支；
- local `main == base_sha`；
- `HEAD` 等于需求分支 ref；
- fresh 时 `HEAD == base_sha`；
- clean 使用 `git status --porcelain=v1 --untracked-files=all`。

## Agent 决策循环

conversation key 和 session key 均为：

```text
requirement_commit_<ID>
```

有 dirty 仓时，公共循环创建：

```text
conversations/requirement_commit_<ID>.json
```

完整历史形态为：

```text
system
→ assistant: /commit-changes 初始指令
→ user: Agent 完整回复
→ assistant: AgentDecision
→ ...
```

单次 Agent 调用上限为 48 turns，不配置金额预算；负责人决策最多 3 轮，只用于正常提交、一次纯 Git retry/repair 和 blocked 恢复。

负责人语义：

- `completed`：只根据 Git 提交结果判断；已有变更均已提交或原本无变更，全部仓库仍在统一需求分支且 clean；
- `continue`：只允许读取 Git 状态和 diff、确认范围、精确暂存、创建本地提交及提交后核验，不得要求修改文件内容；
- `blocked`：用于 Git 作者身份、强制签名、外部授权，或真实秘密、范围冲突等导致现有内容无法原样安全提交的情况；需要修改实现、文档、测试或生成物时，要求交由实现与验证任务处理。

负责人不得授权重新实现或修复功能、修改文档、格式化、补充或执行测试、运行 lint/build、启动服务、浏览器验收、安全审查或代码审查，也不得修改 `.gitignore`、删除或清理文件；同时不得扩大白名单、创建或切换分支、merge、rebase、reset、amend、改写历史、绕过检查或 push。

负责人返回 `completed` 后，Python重新读取最小 Git facts：

- 边界正确且全部 clean：成功；
- 只有未提交内容：向同一 session 发送固定 repair prompt；
- 分支、main/base、target/HEAD 或 top-level 冲突：failed 并保留现场。

blocked 会写 scoped `17.json` 和 state；条件解除后，公共循环从同一 conversation 和同一 session 恢复。

## 恢复锚点

已启动的第 17 步通常要求三项一致：

- `claude_sessions.requirement_commit_<ID>`；
- `decision_conversations.requirement_commit_<ID>.path`；
- 非符号链接的 `conversations/requirement_commit_<ID>.json`。

唯一例外是首次 Agent 尚未取得 session 就发生连接或进程错误：此时 conversation 只能包含 `system → 初始 assistant`，且没有 Agent 回复或 session 结果；重试会以 `resume_session_id=None` 重投原始初始指令。其它残缺锚点均拒绝恢复，不能静默创建替代 session 或补造历史。

fresh 全仓 clean 时零 Agent、零负责人决策、零 conversation，直接记录 `tip_sha = base_sha`。

## 完成与交接

成功结果写入：

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

完整 success result 已写但 state 尚未推进时，只按当前 Git facts 补 state。已进入 step 18 后，第 17 步只核验 result/cycle 结构，不读取 Git、session 或 conversation，也不迁移旧历史字段。

## 验证

定向测试覆盖 fresh clean、完整 conversation、纯 Git continue、三轮决策上限、completed repair、blocked 与 blocked resume、首次无 session 失败重试、残缺锚点、未跟踪文件、symlink、result→state、advanced 兼容和 CLI blocked。验证时运行第 17 步本体与 CLI 测试、公共 Agent 决策循环相关测试、`compileall` 和 `git diff --check`。

## 历史事实

BR-001 由旧实现保存了完整四段 conversation。BR-002 在 direct-run 版本期间已经完成第 17/18 步，只有 Claude session，没有 decision reference 或 `requirement_commit_BR-002.json`。该历史缺口不能补造或反向推断；现行合同只保证未来第 17 步运行保存完整 conversation，不回退或修改已完成的 BR-002。
