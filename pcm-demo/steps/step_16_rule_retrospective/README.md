# 第 16 步：规则复盘

## 输入与前置条件

第 16 步只消费当前活动需求、cycle、产品工作区、当前需求 scoped `15.json` 的 `success`，以及一致的 `development_session_id`；不重新读取产品、设计或业务验证资料。活动 requirement 必须是注册表唯一 `active` 项且 `completion: null`。

fresh 入口逐一核验 `applicable_repositories`、`repositories` 和 `requirement_cycle.repositories` 中全部权威仓库：路径为自身 Git top-level、位于 cycle 需求分支、`HEAD`/local `main`/目标分支均等于记录的 `base_sha`、index clean，且没有进行中的 merge、rebase、cherry-pick、revert 或 bisect。已有未提交工作树变更允许保留。

## Agent、session 与状态

步骤以 `rule_retrospective_<requirement-id>` 建立独立负责人 conversation；首次调用前，`claude_sessions` 先将该 key 预注册为第 15 步的同一 `development_session_id`，Claude Agent SDK 因而恢复原开发会话，而非新建替代 session。初始 prompt 的首行固定为：

```text
/session-rule-retrospective 本次开发会话
```

正文只要求根据该会话真实发生的开发、验证、修复和审查事实复盘；没有满足沉淀门槛的候选时，不修改文件并明确报告也是成功结果。步骤复用公共 `AgentDecision` 循环，`completed` 可以对应 `rules_changed` 或 no-change，`continue` 和 `blocked` 沿用公共语义。

首次调用前原子持久化 Git-visible baseline 与 session alias；恢复只使用已保存 baseline，绝不重采样。baseline 覆盖 porcelain dirty 节点的类型、mode 与内容哈希、全部 refs 及 symref、常见 pseudo-ref、index 语义指纹、Git-visible 外部符号链接、规则目录符号链接与 hard link，以及未知嵌套 Git 仓。已登记子仓若在 root 可见，由其自身仓库 baseline 核验。

每次 Agent 返回、负责人决策、异常和完成前后均比对 baseline：非 root 仓必须完全不变；root 仅 `.claude/rules/**/*.md` 下的普通、非 hard link 文件可相对 baseline 新增或修改。规则删除、重命名、复制、符号链接、hard link、非 Markdown 文件、暂存、提交、分支或 refs/pseudo-ref 漂移均失败并保留现场；Git-visible 符号链接不得指向适用仓库外。ignored 文件不在此证明范围内。

## 结果、推进与恢复

success scoped result 写入：

```text
steps/requirements/<requirement-id>/16.json
```

`outputs` 固定为空，只保存统一字段、`requirement_id` 和 `development_session_id`。success 先写 result，再推进 `requirement:17_commit` / step 17；BR 仍为 `active`、`completion: null`。blocked 保留 step 16、原开发 session、alias、baseline 和独立决策历史；result 已写而 state 未推进时可在边界核验后恢复推进，推进后的幂等重跑不再调用 Agent 或读取 Git。

## 自动化验证

第 16 步本体 19 项与 CLI 4 项，共 23 项；从 `pcm-demo/` 根递归发现的全量 273 项 `unittest` 已通过，`compileall` 与 `git diff --check` 通过。Pyright langserver 未安装，未执行 IDE/LSP 诊断；Ruff 未安装，未执行 Ruff。独立只读审查在修复发现的问题后最终无高、中置信缺陷。

## 真实验证

真实 run 为 `pcm-demo/runs/step01-mendmark`，产品位于 `/Users/zhou/resource/fireworks/ANDRSZAN/pcm-products/mendmark`，需求为 `BR-001`。

首次调用前，三仓 `req/br-001` 均已各自提前存在一个本地需求提交，与 cycle base 冲突；步骤依合同在 baseline、session alias 和 Agent 调用前 failed，没有 retrospective conversation 或产品变化。root 提前提交为 `8e44a6ebefda27fbdf1c79a4a53817918c3c3c95`（父/base `a7d5509df6843a06315aa803d87285569b86e355`），frontend 为 `4ea14479455cc137815356edfb985680d2973f82`（base `dbab574dbe4d83a02323a750afd04de007565ac5`），backend 为 `1236b9cb533259eaecb23e6d0345d0a9797f8444`（base `9682be837759c20f1a9ebbdf8fa2cfc09c2768d4`）。每仓 `main..branch` 恰好一个 commit，无反向分叉或远端包含。

用户明确选择按合同恢复后，三仓分别执行 `git reset --mixed <cycle base>`，保留完整工作树、使 index clean，旧 tip 对象仍可读；独立核验工作树与旧 tip 文件树一致。这是本次 run 的现场恢复，不是生产代码对提前提交的兼容。

恢复后第 16 步正常 success，复用 development session `e6bd1b82-39f9-41b2-9cc9-a69b281015dc`，retrospective alias 同为该 ID。init 确认 cwd 为产品 root、Fable 5、Claude Code 2.1.233 与 `bypassPermissions`；Agent normal success，8 turns，cost `$6.9324520000000005`，`terminal_reason=completed`。conversation 共 4 条：`system → assistant 初始 → user Agent 回复 → assistant completed`，没有 `continue` 或 `blocked`。

唯一规则增量为产品 root `.claude/rules/frontend-playwright-container.md`，其 paths 限定 `frontend/playwright.config.ts`、`frontend/tests/e2e/**`、`frontend/README.md`、`frontend/package.json`、`frontend/pnpm-lock.yaml`；规则要求使用官方 Playwright 容器绑定 frontend 时，将 `node_modules` 与 `.pnpm-store` 挂入临时 volume/临时 store，结束后确认仓库不留 `.pnpm-store` 或测试缓存。

最终 `steps/requirements/BR-001/16.json` 为 success、`outputs: []`；state 位于 `phase_1_requirement_development` / `requirement:17_commit` / step 17，BR-001 仍 active/completion null。root 保留 TRD、截图和规则未提交，frontend/backend 保留实现未提交；三仓均在 `req/br-001`，`HEAD`/`main`/target 等于 base，index clean。不可用 LLM 配置的幂等重跑仍 success，证明没有调用模型或 Agent；关键文件字节不变：state SHA-256 `5f088ca5b3119026046103dff3592a314383e5ff550bcdc6b76d64702bf365c4`，16 result `591b7310eceafc7c526750ae7b06688acc6625ffcbc5ec5d2b66ca6d4b25f5f6`，conversation `3786e7039e4b2d2ba4dfe1b0b68f409fb47504e66ac830f18147a59619d7a90b`，rule `8a5eebbdc2a47ff58c035c61874f784b2e12048ee26100127b69e48821a0ac64`。

## 运行

```bash
cd /Users/zhou/resource/fireworks/ANDRSZAN/pcm-agent-skills/pcm-demo
uv run python run_step.py --step 16 --run-id <run-id>
uv run python -m unittest steps.step_16_rule_retrospective.test_step steps.step_16_rule_retrospective.test_cli -v
```
