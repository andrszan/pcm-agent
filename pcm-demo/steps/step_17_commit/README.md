# 第 17 步：统一提交需求变更

## 职责

本步骤在产品根为当前需求创建独立 Claude session 调用 `commit-changes`，并使用独立的负责人 conversation 处理提交准备与纯 Git 提交动作中的确认和阻塞：

- 当前需求的实现、适用测试、真实验证、审查与规则复盘，均作为不可在提交任务中重新打开的权威完成事实；
- 仓库集合只来自有序 `applicable_repositories` 白名单；
- `commit-changes` 负责读取 Git 状态和候选 diff、确认提交范围、精确暂存、创建本地提交及提交后 Git 核验；提交准备还可在必要时精确修改 `.gitignore`、核验归属和可再生性后逐路径清理非交付临时产物，或完成 hook 要求的纯格式修复；
- 禁止业务语义变更，禁止删除未知资产、数据、秘密、受保护 tracked 文件或 staged 内容，禁止 `git clean` 和宽泛删除；调用方给出的更窄只读权限、范围和已有 staged 意图始终优先；
- AI-compatible 负责人只能返回上述范围内的 `completed / continue / blocked`，不得授权重新开发或重新验收；
- `continue`、blocked 解除、completed 后 repair 和可重试失败都恢复第 17 步自己的 Claude session；
- Python 最终只核验仓库边界和 clean 状态，并记录每仓 `tip_sha`；
- 不 merge、不删除分支、不 push，也不把需求标记为 `completed`。

Python 不重复实现工作树 fingerprint、blob/tree hashing、Git attributes、merge commit、空提交或净零差异取证；这些提交语义由 `commit-changes` 负责。

## 输入与最小 Git 边界

步骤接受：

- `phase_1_requirement_development` / `requirement:17_commit` / step 17；
- 唯一 active requirement、对应 cycle，以及当前节点已经推进到本步骤的交接事实；
- 统一 `req/<lowercase-id>` 分支；
- 有序仓库白名单及每仓 `base_sha`。

Python只检查：

- 仓库路径不是符号链接，且是该仓自身 Git top-level；
- 当前分支是统一需求分支；
- 对捕获的 SHA 校验 `base_sha ≤ local main ≤ HEAD`，其中 `≤` 表示祖先或相等；
- `HEAD` 等于需求分支 ref；首次也允许已有提交，不要求 HEAD 仍等于 base；
- 不存在进行中的 merge、rebase、cherry-pick、revert 或 bisect；边界检查后复读引用，变化时停止；
- clean 使用 `git status --porcelain=v1 --untracked-files=all`。

## Agent 决策循环

conversation key 为：

```text
requirement_commit_<ID>
```

对应 `claude_sessions.requirement_commit_<ID>` 保存第 17 步自己的 Claude session ID。首次 dirty 调用不预填 alias，也不传 `resume_session_id`；Agent init 一旦返回 session ID，公共循环立即保存，后续 continue、repair、blocked 恢复和 retry 都只复用该提交 session。`requirement_cycle.development_session_id` 仅作为拒绝提交 alias 错绑旧开发 session 的边界；本步骤不重复读取 `16.json`，也不复验 `claude_sessions.development_<ID>` 与 `claude_sessions.rule_retrospective_<ID>`，这些前序事实不因提交步骤而修改。步骤 18 只接收 Git 结果，不绑定提交 session。本步骤只传不含需求 ID 的稳定任务标识 `requirement_commit`，实际 model 与 effort 由 `model-policy.toml` 解析并按本次进程启动时加载的策略固定，每次 resume 显式传入本步骤在本次启动确定的组合。各步骤仍保留独立的负责人 conversation。

有 dirty 仓时，公共循环创建独立的负责人对话：

```text
conversations/requirement_commit_<ID>.json
```

初始 Agent prompt 首行固定为 `/commit-changes`；正文只包含需求标识与标题、有序仓库清单、统一需求分支、已验收交接和提交准备范围。不传开发历史或 TRD 全文，也不要求重新验收。提交准备范围与负责人 decision prompt、completed repair prompt 保持一致：允许必要的精确 `.gitignore` 修改、核验归属和可再生性后的非交付临时产物逐路径清理，以及 hook 要求的纯格式修复；禁止业务语义变更，禁止删除未知资产、数据、秘密、受保护 tracked 文件或 staged 内容，禁止 `git clean` 和宽泛删除；调用方给出的更窄只读权限、范围和已有 staged 意图始终优先。

完整历史形态为：

```text
system
→ assistant: /commit-changes 初始指令
→ user: Agent 完整回复
→ assistant: AgentDecision
→ ...
```

单次 Agent 调用上限为 9999 turns，不配置金额预算；负责人决策最多 32 轮。

负责人语义：

- `completed`：只根据 Git 提交结果判断；已有变更均已提交或原本无变更，全部仓库仍在统一需求分支且 clean；
- `continue`：只允许读取 Git 状态和候选 diff、确认范围、精确暂存、创建本地提交、必要时精确修改 `.gitignore`、核验归属和可再生性后逐路径清理非交付临时产物、hook 要求的纯格式修复，以及提交后核验；
- `blocked`：用于 Git 作者身份、强制签名、外部授权，或在允许范围内无法安全完成提交的情况；需要业务语义变更时，要求交由实现与验证任务处理。

负责人不得授权重新开发或重新验收，也不得删除未知资产、数据、秘密、受保护 tracked 文件或 staged 内容、使用 `git clean` 或宽泛删除；同时不得扩大白名单、创建或切换分支、merge、rebase、reset、amend、改写历史、绕过检查或 push。调用方已给出的更窄只读权限、范围和已有 staged 意图不能被 decision 放宽。

负责人返回 `completed` 后，Python重新读取最小 Git facts：

- 边界正确且全部 clean：成功；
- 只有未提交内容：向同一 session 发送固定 repair prompt；
- 分支、祖先关系、target/HEAD 或 top-level 冲突：failed 并保留现场。

blocked 会写 scoped `17.json` 和 state；条件解除后，公共循环从同一 conversation 和同一 session 恢复。

## 恢复锚点

已取得提交 session 的第 17 步要求三项一致：

- `claude_sessions.requirement_commit_<ID>` 是非空的独立提交 session ID，且不得等于 `requirement_cycle.development_session_id`；
- `decision_conversations.requirement_commit_<ID>.path`；
- 非符号链接的 `conversations/requirement_commit_<ID>.json`。

首次调用在 Agent init 前失败时，允许在没有提交 session alias 的情况下重入，但历史必须只有已保存的 `system` 和非空初始 `assistant` 指令，且不得存在 init、Agent 回复、负责人决定、blocked 状态或其它 session 事实。已有 Agent 回复却没有 alias、已有 alias 却没有完整历史等损坏状态拒绝。conversation 的 schema、角色顺序和引用路径由公共决策循环统一读取和校验，本步骤不再维护一套私有解析；历史 system 和指令不与当前模板逐字比较，也不在恢复时重渲染，避免文案更新破坏合法续接。旧活动失败若 alias 仍等于开发 session，明确拒绝并要求一次性备份迁移，不自动丢弃或继续复用。

fresh 全仓 clean 时零 Agent、零负责人决策、零 conversation，直接记录当前 HEAD 为 `tip_sha`；可以等于 base，也可以是已包含当前 main 的后续提交，原始 `base_sha` 保持不变。

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

定向测试覆盖 fresh clean、当前节点交接不重复复验 `16.json` 和前序 session alias、首次 dirty 独立 session、init 前失败重入、init 后捕获 session 的 retry、独立 conversation、纯提交范围 continue、completed repair、blocked 与 blocked resume、旧开发 alias 的显式迁移拒绝、残缺 session/history、未跟踪文件、symlink、result→state、advanced 兼容和 CLI blocked。验证时运行第 17 步本体与 CLI 测试；需要确认第 18 步兼容时额外运行其定向测试，并执行 `compileall` 和 `git diff --check`。

## 历史事实

BR-001 由旧实现保存了完整四段 conversation。BR-002 在 direct-run 版本期间已经完成第 17/18 步，只有 Claude session，没有 decision reference 或 `requirement_commit_BR-002.json`；该历史缺口不能补造或反向推断。
