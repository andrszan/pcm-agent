# 第 14 步：形成活动 TRD

## 输入与前置条件

第 14 步只处理第 13 步已经选择的当前活动需求，不接受额外的需求或分支参数。运行状态必须位于 `requirement:14_trd_design`，且当前 requirement、注册表唯一 active 项、cycle、第 13 步 scoped success、统一需求分支和各仓 `base_sha` 必须一致。

领域输入严格来自既有步骤结果：

- 第 2 步两份产品定义；
- 第 5 步项目准备清单；
- 第 7 步总体技术方案；
- 第 9 步工程架构设计；
- 第 10 步适用时的产品级 UI/UX 框架；
- 第 11 步正式 Backlog 和当前活动需求详情；
- 第 8 步确认的全部适用仓库及其实际代码事实。

全部适用仓库必须位于 cycle 记录的统一需求分支，且 `HEAD`、local `main`、需求分支 ref 均等于各仓记录的 `base_sha`。fresh 入口要求全仓 clean、index clean，并拒绝进行中的 merge、rebase、cherry-pick、revert 或 bisect。

## 路径、Agent 与输出边界

Python 首次执行时按以下格式计算唯一输出路径：

```text
docs/trd/<YYYY-MM-DD>-<requirement-id>-<requirement-title>.md
```

日期只取首次执行日。完成全局只读预检后，程序先将精确 `trd_path` 写入 `requirement_cycle`，再启动 Agent；恢复时只读取该值，不因日期或标题变化重算。目标路径也会原样写入初始 `/trd-design` prompt。已存在的父路径必须是非符号链接目录；路径冲突在 intent 前无副作用失败。

Claude Agent 在产品根运行，conversation、session 和私有执行状态使用 `trd_design_<requirement-id>` 隔离。步骤复用公共 `agent_decision_loop`、默认 `run_claude()` 工具配置和结构化 `AgentDecision`，不设置 `permission_mode`、`tools`、`allowed_tools`、`disallowed_tools` 或步骤私有 tool hook；项目 `.claude/settings.json` 与 Claude Code 默认加载语义继续是权限和工具行为的权威来源。prompt 明确只允许创建指定活动 TRD并禁止 Git 写操作，Python 负责调用前、决定前和完成时的文件、分支、index、ref 与工作树事实核验。

成功 result 只写：

```text
steps/requirements/<requirement-id>/14.json
```

`outputs` 为唯一活动 TRD，result 同时保存 requirement ID、统一分支、`trd_path` 和原 TRD session ID。

## 完成条件与 Git 边界

负责人返回 `completed` 后，Python 只做机械核验，不解析或重复设计 TRD 内容：

- 唯一活动 TRD 为非空、非符号链接普通文件；
- 产品 root 的全量 Git 状态恰好只有该未跟踪 TRD；
- index 为空，没有 staged 内容；
- 其它适用仓库全部 clean；
- 全部仓库仍在统一需求分支，`HEAD/main/target/base` 全部相等；
- 原 requirement-scoped session 和 conversation 锚点完整。

负责人 completion 规则还要求：阻碍实现的高影响决定已经明确采用当前基线；Agent 回复不能仅因“已经列出实现前待确认事项”就被判定完成。文档缺失或为空时只向原 session 发送固定补全提示。任何最终可见的范围外修改、暂存、提交、ref 漂移、分支漂移或进行中的 Git 历史都直接失败并保留现场，不自动 reset、restore 或清理。该核验证明完成现场不存在 Git 写入结果或越界变更，不把最终状态核验夸大为对整个 Agent 执行历史的绝对取证；若未来需要不可绕过的执行隔离，应在项目级权限或沙箱合同中统一设计，而不是由单个领域步骤覆盖工具配置。

成功先写 scoped result，再推进到 `requirement:15_development` / step 15。活动需求仍为 `active`，`completion` 仍为 `null`；第 15 步尚未实现。

## 恢复与幂等

- fresh 预检失败时不写 state 或 scoped result；
- 只有 `trd_path` 的早期中断沿用原路径启动 Agent；
- 已有执行事实时必须恢复原 session 和 conversation，缺少任一锚点都失败；
- conversation 尾部为 Agent 回复时先裁决，不重复 Agent；
- blocked 保存 scoped result、部分 TRD 和同一 session，解除外部条件后恢复；
- failed、blocked 或残缺 success 可由同一 requirement 后续运行覆盖；
- scoped success 已写但 state 未推进时重验完成现场，只补 state；
- state 已进入第 15 步后，重跑只校验当前 requirement 的完整 scoped success 与状态结构，不再读取 Git 或文件，避免拒绝后续合法 dirty；
- 历史 requirement 的 result、session 或 conversation 不保护当前 requirement。

## 自动化验证

已执行并通过：

- 第 14 步本体 13 项；
- 第 14 步 CLI 6 项；
- 公共 Agent 决策循环与 Claude runner 24 项；
- 第 13 步本体与 CLI 28 项；
- 上述定向共 71 项；
- 从 `pcm-demo/` 根递归发现的全量 241 项 `unittest`；
- `compileall`、`git diff --check` 和全工作区 IDE diagnostics。

独立审查发现的 fresh CLI 副作用、bisect 漏检和 TRD 父路径冲突等确定性边界问题均已修复并补测试。为回应“最终 Git 状态不能证明 Agent 从未进行临时写入”的审查意见，曾短暂增加步骤私有工具白名单和 `PreToolUse` hook；用户复核后确认该方案不是领域步骤必要条件，且与项目统一权限设计冲突，现已删除并增加默认 runner 无工具覆盖测试。最终复核无高、中置信问题。Ruff 未安装，未为检查增加依赖。

## 真实验证

真实 run 仍为 `pcm-demo/runs/step01-mendmark`。用户在第 14 步前将新的 TRD 命名规则提交到产品 root，使 root `main` 和旧 `req/br-001` 从第 13 步记录的 `0232d81...` 前进到 `a7d5509...`。在用户明确选择后，先完整归档 run，确认三仓旧需求分支与各自 `main` 无任何独有提交，再使用安全的 `git branch -d` 删除旧分支，只重置 BR-001 的活动 cycle/result，并从最新 `main` 重新执行第 13 步。新的 cycle bases 为：

- root：`a7d5509df6843a06315aa803d87285569b86e355`
- frontend：`dbab574dbe4d83a02323a750afd04de007565ac5`
- backend：`9682be837759c20f1a9ebbdf8fa2cfc09c2768d4`

第 14 步使用唯一 session `b9ed4756-0acf-4666-b3f9-c8f3628c03f1`。首次 Agent 调用生成唯一 TRD 后，负责人错误地把 8 项“实现前必须确认”事项接受为 `completed`；主代理独立读取文档后拒绝该语义完成，收紧生产 completion 规则，并仅在 Git 忽略的正式 conversation 中追加一次普通复核指令，恢复同一 Claude session，将登录标识、单角色、通知语义、会话期限、密码与限制、恢复范围、最小顶部栏和 WCAG 2.2 AA 收敛为当前实现基线。第二次 Agent 调用正常 success；其后负责人服务因 free quota 返回 HTTP 403，conversation 尾部保持 Agent 回复且没有重复 Agent。额度恢复后从原节点完成合法 `completed` 裁决。

最终 conversation 共 7 条：

```text
system
→ assistant 初始 /trd-design
→ user 首次 Agent 回复
→ assistant 首次 completed
→ assistant 语义复核指令
→ user 同 session 修复回复
→ assistant 最终 completed
```

最终事实：

- 活动 TRD：`docs/trd/2026-08-25-BR-001-身份、角色访问与站内消息入口.md`
- scoped result：`steps/requirements/BR-001/14.json`
- state：`phase_1_requirement_development` / `requirement:15_development` / step 15
- result SHA-256：`05eeafaac4acc38873073657caebf9d661f898f4f7e24dc59220f60dcaec28c1`
- state SHA-256：`1f1f7a922ef481d0434be016246f72734fd0e12c9b2079710b5e328b9892cdf3`
- conversation SHA-256：`e43ba42fea08e24a14e67d6f2d0889c16cad1f56e219640f5fe63f36d41f5695`
- TRD SHA-256：`ab17a9f94d85b2b96efa3839f94d6608cad98710f41c41ccb009f71f93d12c1d`

产品 root 恰好只有该 TRD 为未跟踪文件；frontend/backend clean；三仓 index 为空且 `HEAD/main/target` 分别等于记录 base。没有产品提交、merge 或 push，也没有 `/commit-changes`。推进后的幂等重跑不读取 Git、不调用 Agent 或负责人服务，state/result/conversation/TRD 四者字节不变，session 和 Agent 结果不变。

恢复默认工具配置发生在上述真实 Agent 运行完成之后，因此没有为了验证权限参数删除而重跑或改写已成功的 TRD session。当前生产路径直接使用已被第 2/5/6/7/8/9/10/11 步真实运行验证过的公共默认 runner；第 14 步自动化明确断言默认 `agent_runner` 为 `run_claude`，且公共循环调用中不存在 `tools/hooks` 覆盖。活动 TRD、result、state、conversation 和产品 Git 现场均未因此改变。

## 运行

```bash
cd /Users/zhou/resource/fireworks/ANDRSZAN/pcm-agent-skills/pcm-demo
uv run python run_step.py --step 14 --run-id <run-id>
uv run python -m unittest steps.step_14_trd_design.test_step steps.step_14_trd_design.test_cli -v
```
