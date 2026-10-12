# PCM Demo 三阶段审查与整改

本轮按用户批准的总计划，完成七个领域的并行审查、问题收敛、分组修复与独立复核。共纳入 23 项运行／交接缺陷、2 项文档修正，以及回复拼接和正向反馈交接两项有明确收益的优化／澄清，均已完成。最终整合全量 823 项测试全部通过，测试期间 Python 源码指纹保持一致；真实模型与产品运行的验证边界见第 6 节。

本记录是唯一的审查与整改清单，不向流程主文档追加测试流水。表中编号只用于本次审查，不进入产品 Backlog 或领域 Prompt。

## 1. 基线、范围与交付边界

- 日期：2026-10-05。
- 目标：根工作区中的 `pcm-demo`、实际参与的能力正文、规则与流程合同；不全面审查跃动俱乐部业务代码或第三方资源库内部实现。
- 起始分支：`pcm-demo`；起始提交：`65a47716ca30a95fa88f2602fba99eb5f118bf4d`，开始时工作树干净。本轮按当前完整实现审查，不把所有问题归因于最近一次提交。
- 环境：Python 3.13.14、Git 2.48.1、`claude-agent-sdk` 0.2.152、`openai` 3.1.0、`pydantic` 2.13.4、`pydantic-settings` 2.15.0。复用现有 `.venv`，未安装或更新依赖。
- 在当前分支精确创建本地提交，不合并到 `main`、不 push、不切换会话 worktree。临时 Git 仓库中的提交、分支与合并仅用于隔离测试。
- 未启动或改写真实产品现场，未修改三个历史 run，未调用 PCM 配置的真实 Agent／负责人服务或真实产品探针。
- 本机 `.git/info/exclude` 忽略 `pcm-demo/` 下新增文件。本记录与必要新增 Python 文件精确纳入版本控制，忽略政策不变；不纳入 runs、实际 `.env`、凭据或临时日志。

## 2. 审查覆盖

| 领域 | 实际覆盖 | 结果 |
|---|---|---|
| 公共沟通与运行 | 六个公共沟通／状态文件；协调、端口、owner、诊断、计时、配置和模型策略；外层入口接线 | 完成审查，相关缺陷已修复 |
| 初始化 1～6 | 各步骤实现、实际 Prompt、测试和领域说明；工作区、选型、准备、项目化、主题与媒体调用 | 完成审查，相关缺陷已修复 |
| 初始化 7～12 | 方案、首次提交、架构、UI/UX、Backlog、需求注册表和测试 | 完成审查，相关缺陷已修复 |
| 需求循环 13～18 | 选择、TRD、开发、复盘、提交、合并，以及代码／会话／状态交接 | 完成审查，相关缺陷已修复 |
| 质量迭代 | 全部七个命名节点、共享 Git、完整审计交接、分流、入池、原场景归属与收口恢复 | 完成审查，相关缺陷已修复 |
| 人工反馈 | 全部七个命名节点、原材料、条件设计调用、分诊、范围决定、开发承接与完成输出 | 完成审查，相关缺陷已修复／澄清 |
| 跨阶段与历史 | 三个历史 run 的必要状态、180 份需求步骤结果、候选映射、版本衔接及定向会话证据 | 完成核对，证据边界见第 6 节 |

15 个显式参与的能力正文已按领域审查：`project-intake`、`project-readiness`、`project-bootstrap`、`tailwind-theme`、`media-assets`、`solution-design`、`engineering-architecture`、`ui-ux-framework`、`requirement-breakdown`、`trd-design`、`dev-workflow`、`session-rule-retrospective`、`commit-changes`、`product-experience-audit`、`product-feedback-triage`。另核对 `ui-component-patterns`、`playwright-cli`、dev/reviewer、项目规则与插件加载边界。相关 reference 和媒体工具接口按实际调用读取，没有遍历全部素材或第三方库。

Skill 正文没有因审查而机械重写；已确认的问题主要在编排、调用边界和交接。评估定义与能力正文的一致性已检查，但未执行 203 条真实模型评估。

## 3. 已纳入整改清单

以下代码和测试路径均相对 `pcm-demo/`。每项保留原反例及必要负向保护；同一根因的多处表现合并记录。状态“已修复”表示实现、定向回归和复核已完成，整合测试另列于第 5 节。

### 公共执行、恢复与配置

| 编号 | 基线问题与结果 | 主要实现／回归位置 | 状态 |
|---|---|---|---|
| R01 | Result 回调后中断，pending 恢复跳过 cwd／Skill／slash 等校验，曾使第 15 步误推进。恢复现复用完整校验；无 init 不沿用旧身份，429／5xx 与不可重试错误的实时／恢复分类一致 | `common/agent_decision_loop.py`、`common/test_recovery_regressions.py` | 已修复，优先项 |
| R02 | 新调用再次返回相同正文，被误当旧 pending，负责人不再裁决、轮数不增长。现在新调用形成独立轮次，旧回复恢复仍幂等且不刷新时间戳 | 同上、`common/test_agent_handoff.py` | 已修复，优先项 |
| R03 | 初始 conversation 已写而 state 引用未写时中断，第 17 步预检阻断既有引用恢复。仅对没有执行事实、只有初始历史的窄窗口恢复引用，其余损坏仍拒绝 | `common/agent_decision_loop.py`、`common/test_recovery_regressions.py` | 已修复 |
| R04 | turn／budget 可恢复 subtype 豁免了明确的模型不匹配。现在硬身份错误失败停止，普通尾随异常和合法可恢复结束继续沿原规则处理 | 同上 | 已修复 |
| R05 | 额度不足时先写未投递 repair，遮住 completed 锚点，补齐产物后也不能重验。现在先检查额度再保存投递，原完成结果可在不增加模型调用时重验 | 同上 | 已修复 |
| R06 | 有人工恢复消息时，前置负责人失败被“消息未消费”遮盖，步骤失败不落盘。现在保留原始失败，成功路径仍要求消息实际消费 | `run_step.py`、`test_run_step_retry.py` | 已修复 |
| R07 | 状态停在第 5 步却误调第 7 步，错误处理会把当前位置改成 7。失败保存现检查节点归属，不回退／跳过业务节点或覆盖其它步骤结果 | `run_step.py`、`common/test_runtime_regressions.py` | 已修复，优先项 |
| R08 | 无 coordination 的旧 run 经直接单步入口只取得锁，绕过持久 owner／租约校验。现在复用统一认领及 runtime 接线，同 owner 稳定复用，他 owner／released 拒绝 | 同上 | 已修复 |
| R09 | provider 或进程的显式空 `LLM_MODEL_EFFORT` 无法清除基础 high。现在仅为该可选字段支持显式清空，其它配置的空值政策不变 | `config.py`、`test_config.py` | 已修复 |
| R10 | Basic 认证头只遮住 scheme，编码凭据仍进入诊断。现在完整遮盖认证值，覆盖 Proxy-Authorization、Digest quoted-pair 等，保留正常诊断上下文 | `common/error_diagnostics.py`、`common/test_error_diagnostics.py`、`test_agent_proxy.py` | 已修复 |

R01/R02 的原反例均通过真实公共循环与模拟 SDK 重现：前者曾在恢复时零 Agent 调用、一次裁决后推进开发步骤；后者在裁决上限为 2 时连续取得 4 次同文 success，裁决计数仍为 1，由测试哨兵终止。修复同时保留了正常恢复与终止条件，并非删除去重或扩大轮数上限。

旧 run 首次合法接入会补充协调元数据。这是兼容认领，不是业务节点推进；相关 CLI 夹具在拍摄字节快照前完成真实登记，原业务状态和历史结果保护断言仍在。独立测试用例采用独立产品路径，不能依赖绕过 owner 检查。

### 初始化、Git 与需求循环

| 编号 | 基线问题与结果 | 主要实现／回归位置 | 状态 |
|---|---|---|---|
| R11 | 第 4 步误调用会把后续节点回退到 4，并覆盖成功结果。现在只在本节点合法失败锚点保存，误调用保留原结果与业务位置 | `steps/step_04_assemble_foundation/` | 已修复 |
| R12 | 第 4 步 success 已写、state 尚未推进时，重跑把已发布工程当占位失败。现在只读复验既有成功并补推进，不 clone、不清理已发布工程 | 同上 | 已修复 |
| R13 | 第 2 步继续依赖已导入的外部初稿；源删除或移动就阻断。现在核验工作区发布副本及记录 hash，副本篡改、符号链接和路径漂移仍拒绝 | `steps/step_02_project_intake/` | 已修复 |
| R14 | Tailwind v4 gate 误拒合法 source／url／同行语法。现接受这些顶层导入，同时排除注释、字符串、普通块内属性值中的伪 import 与 v3 | `steps/step_06_project_bootstrap/` | 已修复 |
| R15 | 第 8～11 步继承外部 Git 索引／仓库重定向，可能把真实暂存变化误判 clean。现共享小型环境隔离函数，同时保留作者／提交者覆盖的检测及适用全局配置 | `common/git_environment.py`、`steps/step_08_initialize_repositories/test_git_environment.py`、步骤 08～11 | 已修复 |
| R16 | 第 8 步 clean 快路径跳过显式人工恢复消息。现在有待消费消息时仍投递原 session、之后复验，正常无消息场景保持零调用 | `steps/step_08_initialize_repositories/` | 已修复 |
| R17 | 第 13/17/18 步漏掉 clean HEAD 下未结束的多提交 cherry-pick／revert sequencer。现在在 intent 或成功记录前拒绝；共享质量 Git 边界同步覆盖 | 步骤 13、17、18 与 `quality/git.py` | 已修复 |
| R18 | 第 18 步切回旧 main 后中断，新 tip 忽略的正常产物变成 untracked，原节点无法恢复。现在写入前使用 Git 原生规则证明这些路径被 saved tip 忽略；外部新增非忽略文件、tracked/index dirty 仍拒绝 | `steps/step_18_merge/` | 已修复 |

R18 的负向对照验证了真正的范围外 untracked 在任何 Git 写入前被拒绝，main 和文件保持不变；没有用“最后仍会 dirty”代替写入前保护。忽略规则由 Git 解释，没有新增持久 marker 或自写 ignore 解析器。

### 质量与反馈迭代

| 编号 | 基线问题与结果 | 主要实现／回归位置 | 状态 |
|---|---|---|---|
| R19 | 本批修复完成后，独立必要 coverage gap／required_inputs 被吞掉。现在不误收口，并在现有 complete 节点沿原审计会话补证；有纳入和无纳入批次均能从真实 blocked 经合法 resume／消息恢复完成 | `quality/workflow.py`、`quality/test_workflow.py`、`quality/test_agent_handoff.py` | 已修复，优先项 |
| R20 | 后续质量批次没有交接来源中的候选处置，难以遵守“无新证据不绕过原决定”。现在只读提供结构化候选、理由、前提与版本，不递归包装会话，也不建立永久排除名单 | `quality/workflow.py` 及对应测试 | 已修复 |
| R21 | Git `-z` 输出被 strip，` docs/backlog.md` 被误认成允许的 `docs/backlog.md`。现在保留完整 NUL 输出，真实不同路径被拒绝 | `quality/git.py`、`quality/test_git.py` | 已修复 |
| R22 | 干净 main 上未结束的 bisect 被质量／反馈入口接受。现在检测 BISECT_START 和 sequencer，正常结束后恢复可用 | 同上 | 已修复 |
| R23 | 最终反馈完成输出仍复制前期“尚未开发／验证／合并”的摘要与限制。现在按已核验完成事实生成当前结果，前期说明明确标阶段，原处置和回归归属保留，不猜测旧限制已解除 | `feedback/workflow.py`、`feedback/test_workflow.py`、`feedback/test_agent_handoff.py` | 已修复 |

R19 补证没有新增节点或长期台账，没有回退运行位置、重复全量审计或重新执行已完成修复。原 audit、route、pool、register 文件与需求完成事实保留；新的外部提交、活动／pending 需求或缺少合并证据仍不能完成。补证只处理独立未承接缺口，不机械否定已由需求完成的原场景回归。

### 文档与必要优化

| 编号 | 工作 | 结果 |
|---|---|---|
| D01 | 根 README／能力说明四处旧流程链接及失效目录树条目 | 已修复；59 处本地链接目标全部有效 |
| D02 | 主文档误称第 15～17 步共用开发 session | 已修复；第 15/16 步共用，第 17 步独立提交会话 |
| O01 | 回复完整块后缀识别反复切片拼接 | 等价改成一次拼接与块边界索引；空白／XML／完整块后缀穷举通过 |
| O02 | 显式启动的纯正向反馈批次交接不清 | 调用提示明确用简短处置摘要记录实际信号，零推荐、零需求，沿原文档归档流程完成；不新增 no-op 状态 |

O01 在 9999×1024 字符构造样本中的测试耗时由 4.304 秒降至 0.080 秒，只说明该算法样本，不代表真实产品端到端提速幅度。重复 state／conversation I/O 尚无实测收益，不因“可以更少”删除异常后的最终保存或恢复加载；严格 JSON 失败与缺少真实生成路径的 SDK 组合也未冒充必修缺陷。

## 4. 验证和复核方法

- 既有全量基线为 764 项通过；没有把“测试原本全绿”当作覆盖充分。
- 已纳入缺陷先建立反例，再修复并保留负向保护；涉及 Git 的反例使用真实临时仓库，SDK／负责人调用使用替身。
- 实现按文件划分唯一负责人；完成后独立检查原反例和受影响差异，不在每次补修后重启全仓审查。
- 独立复核与整合中发现并关闭了 pending 恢复丢失重试分类、普通 untracked 被过早合并、认证 quoted-pair 泄漏、CSS 伪入口，以及质量必要缺口被改成永久阻塞等问题。
- 首轮整合运行 822 项，5 项失败。逐一确认后，四项来自旧夹具拍快照前未登记 coordination，一项来自独立测试 run 共用产品路径触发正确 owner 拒绝。夹具已补合法前提，原失败、字节和归属断言保留；没有放宽产品保护来让测试通过。

## 5. 最终验证

| 检查 | 结果 |
|---|---|
| 最终整合全量 unittest | 823 项全部通过，171.965 秒，退出码 0；测试期间 Python 源码指纹不变 |
| Python 编译与差异格式 | `compileall`、`git diff --check` 通过 |
| Skill eval 定义 | 15 份 JSON、203 条定义可解析、各文件 ID 无重复；未执行真实模型 eval |
| 本地文档链接 | 59 处目标有效；不包括外部 URL 和章节锚点 |
| 历史 run／真实产品 | 只读核对，没有修改或重跑 |

标准全量入口，在 `pcm-demo/` 下执行：

```bash
.venv/bin/python -m unittest discover -s . -t . -p 'test*.py' -v
```

新文件需要精确收录：`common/git_environment.py`、`common/test_recovery_regressions.py`、`common/test_runtime_regressions.py`、`quality/test_git.py`、`steps/step_08_initialize_repositories/test_git_environment.py` 与本记录。未修改整个 `pcm-demo/` 的本机忽略政策。

## 6. 历史证据与结论边界

已核对 `active-club-20260922`、`active-club-20260922-quality`、`active-club-feedback-20261003-ui`：

- 正式需求累计 14→24→30；30 项需求共 180 份第 13～18 步结果的 ID、TRD、session 与 Git base/tip 交接一致。
- 阶段末版本与下一阶段入口版本一致；质量 15 个纳入候选对应 10 项增量需求，反馈 6 个纳入候选对应 6 项增量需求，拆分后的完整回归归属与依赖成立。
- 历史中存在人工恢复、范围澄清、规则归属补交和桌面／DevTools 补证，不能宣称三个 run 全程无需人工介入。
- 第三阶段最终摘要确有前期状态混入最终结果的历史证据，与 R23 当前实现反例一致；本轮只修当前输出，不回写历史。
- 原模板版本为 `f6c76a8`，部分能力内容与审查基线不同；历史 run 没有保存 PCM 调度代码 commit，不能根据日期和 success 推断历史覆盖当前全部代码。
- Agent 报告、状态和 Git 交接不是本次独立浏览器／服务验收。本轮未重做真实产品全程运行，也未证明所有模型或产品类型的泛化效果。

本轮交付目标是当前支持边界内的代码、能力合同、交接和恢复整改。历史证据限制、未运行的真实模型评估及未重跑的产品验收如实保留，不用 mock 或一次成功记录冒充。
