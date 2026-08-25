# 第 9 步：工程架构设计

## 输入与前置条件

第 9 步是项目初始化流程的必要步骤，不提供 `applicable: false` 或简单项目跳过路径。

固定输入为：

- 第 2 步 `steps/02.json.outputs` 指向的两份非空产品定义；
- 第 5 步固定项目准备清单 `docs/requirements/项目准备清单.md`；
- 第 7 步固定总体技术方案 `docs/design/技术方案.md`；
- 第 8 步成功 result/state 一致的有序 `applicable_repositories`，且第 8 步 `outputs` 必须为空。

运行状态必须位于 `project:09_engineering_architecture`。第 8 步只交接合法、有序的仓库名称；不逐项回放旧 `repositories` 的 path、branch 或 clean 字段。产品工作区必须位于状态记录的独立工作区根下且不是符号链接；本步骤在当前现场只读核验每个权威仓库均为自身 Git top-level、位于 `main` 且 clean。Python 不从固定前后端目录、Agent 回复或其它历史文字补充仓库。

## Agent、决策与固定产物

步骤在产品根使用一个公共 `agent_decision_loop` conversation 和一个 Claude Agent SDK session：

- conversation/session 领域键固定为 `engineering_architecture`；
- 初始提示第一行固定调用 `/engineering-architecture`；
- 固定输出为 `docs/design/工程架构设计.md`；
- 单次 Agent 上限为 48 turns、`$16`，同一历史最多 8 轮结构化决定；
- 新 conversation 的动态 XML system snapshot 使用 `<role>`、`<project_context>`、`<responsibility>`、`<completion>`、`<output>` 五段；步骤规则位于 completion，output 单独约束 `AgentDecision` 字段组合；恢复时严格使用历史首条 system，不重新渲染覆盖。

`AgentDecision` 的输出约束为：`completed` 时 `answer` 为空且 `required_inputs` 为空；`continue` 时 `answer` 非空且 `required_inputs` 为空；`blocked` 时 `answer` 为空且 `required_inputs` 非空；所有结果的 `reason` 均非空。公共层使用一次 `responses.parse` 和 Pydantic 输出，不手写解析、不注入决定、不格式重试。

Agent 基于权威输入和实际工程，把总体技术方案落实为可执行的工程结构与协作规则。初始工程架构调用只允许创建或更新固定文档，不得实现业务功能、修改工程代码或配置、修改项目规则、执行 Git 写操作或处理秘密。每次请求 AI-compatible 决定前，步骤都会重新核验当前 Git-visible 工作树边界；当前可见的范围外修改会使现场核验失败。

## 完成核验、提交与恢复

负责人返回 `completed` 后，程序先 repair 缺失或空的 `docs/design/工程架构设计.md`；repair 只允许补全该固定文档。文档有效后，重新核验工作树边界：仅当根仓有未提交变化、该变化只涉及固定文档时，才在原 session 发送 `/commit-changes`。固定文档已经 tracked 且全仓 clean 时，直接满足提交交付条件，不制造无变化调用。`commit-changes` 仍只在实际需要时处理固定文档；Python 不执行 `add`、`commit`、`push` 或其它 Git 写操作。

**证据边界：** Python 只核验当前 Git-visible 工作树和 index；这不是不可绕过的安全隔离，不证明整个 Agent 执行历史未发生 Git 写入，也不覆盖 ignored 文件。本地 Demo 信任项目权限配置和 Agent 遵守领域约束；未来若要求不可绕过隔离，应在项目级权限或沙箱统一实现，而非由领域步骤解析 conversation 或扩展 Git DSL。

最终成功必须同时满足：

- 固定工程架构文档为非空、非符号链接普通文件且已被产品根 Git 跟踪；
- 根仓库和全部适用子仓在当前现场均为各自自身 top-level、位于 `main` 且 clean；
- `steps/09.json` 为严格 `status=success`、`applicable=true`，唯一输出为 `docs/design/工程架构设计.md`。

成功不依赖 exact commit prompt、紧邻 Agent 回复、conversation 角色/消息顺序或其它历史执行锚点。结果已写而状态推进中断，或完整 success 重跑时，只按严格 result schema、当前固定文档和当前 Git 事实补状态或确认成功。

领域步骤继续使用公共 `run_agent_decision_loop` 保存、读取和解释完整 conversation；领域代码不解析消息 schema、角色顺序、尾部 decision、session/reference 组合或完整 commit prompt，也不把 conversation 作为长期成功证据。fresh 仅因本步骤 session、conversation reference、私有状态或 conversation 路径等既有执行产物而拒绝；resume 交由公共循环恢复原 session。run 目录是受控、Git 忽略的本地恢复状态，不建设防篡改日志。

负责人返回 `blocked` 时，始终保存 blocked result/state 并停在 `project:09_engineering_architecture`；即使本地固定文档已 tracked 且仓库 clean，也不得改判 success。补齐外部条件后由公共循环从原 session 恢复。

`run_step.py` 仅保护 schema 完整的 success；字段残缺不构成保护锚点。成功后状态推进到 `project:10_ui_ux_framework`。第 10 步仍是按需的产品级 UI/UX 框架步骤。

## 自动化验证

第 9～11 步新合同代码与自动化已完成：第 9～11 步本体测试合计 49 项通过；公共循环加第 9～11 步本体及第 10/11 步 CLI 定向回归共 84 项通过；PCM Demo 全量 268 项 `unittest` 通过（86.068 秒）；`compileall common steps run_step.py` 与 `git diff --check` 通过；目标第 9～11 步生产/测试和相关文档 IDE diagnostics 无新增问题（既有 pydantic 解析 warning 和第 12 步 unused hint 不属于本次）。尚未按新合同重新执行真实 Claude Agent、负责人 LLM 或 `/commit-changes` 集成；旧真实 run 仍仅为旧合同历史。

## 旧合同下的历史运行事实（非当前成功条件）

以下 session、11 条 conversation、exact commit prompt、commit-changes 发现文档事实矛盾及提交事实，均是旧合同下的历史运行路径；保留作排障和演进依据，不构成当前成功条件。

### 旧合同详细事实

旧失败时间线保留为根因证据：最初正式运行和恢复曾因 free quota / `use free tier only` 返回 HTTP 403；访问恢复后服务又曾返回非 JSON 普通文本；之后还出现过 `completed` 携带非空 `answer`。这些失败最终定位到旧 `render_decision_system_prompt` 设计：步骤规则混入 responsibility、completion 语义硬编码且重复，并缺少独立 output 合同。

用户将公共 prompt 重构为 `<role>`、`<project_context>`、`<responsibility>`、`<completion>`、`<output>` 五段；实施中补齐 f-string JSON 花括号转义，并在 output 中加入完整 `AgentDecision` 字段组合约束，同时更新 common 与第 2/5/6/7/9 步相关测试。随后按用户要求两次清理第 9 步局部 result、conversation、session 和 private state，并删除失败运行生成的未跟踪工程架构文档；第 0～8 步历史和三仓提交保持不变。

最终 fresh 运行使用唯一 session `f41fc439-4c46-434f-b3e9-d15c18c89601`。conversation 共 11 条，角色顺序为：

```text
system
→ assistant 初始
→ user
→ assistant continue
→ user
→ assistant completed
→ assistant commit prompt
→ user
→ assistant continue
→ user
→ assistant completed
```

首轮工程架构 Agent 先核对事实并请求确认；负责人合法返回 `continue`，要求创建固定文档。Agent 创建约 32 KB 文档，现场只有产品根固定文档 dirty；负责人返回严格 `completed`，completion verifier 在同一 session 发送固定 `/commit-changes`。

commit-changes 执行轮发现文档中的 frontend Git 事实矛盾，严格未修改、未暂存、未提交并如实报告。随后外层负责人通过普通 `continue` 授权通用 Claude Agent 只修正固定文档并提交；Agent 仅修正文档并精确提交。最终产品根提交为 `ead14dffe19bc6417634c24c7bb1103602c3b772`，message 为 `docs: 新增工程架构设计`，仅新增 `docs/design/工程架构设计.md`，共 376 行、32928 字节；未 push，frontend/backend 无变化。

最终负责人返回合法严格 JSON `completed`。`steps/09.json` 为 success，固定 output 为 `docs/design/工程架构设计.md`；state 为 success，并推进到第 10 步 `project:10_ui_ux_framework`。

独立核验确认 root、frontend、backend 均为自身 top-level、`main`、clean，固定文档已 tracked。同 run 幂等重跑后 conversation 仍为 11 条，session、root HEAD 均不变，没有再次调用 Agent、决策服务或产生新提交。

## 运行

```bash
cd /Users/zhou/resource/fireworks/ANDRSZAN/pcm-agent-skills/pcm-demo
uv run python run_step.py --step 9 --run-id <run-id>
uv run python -m unittest steps.step_09_engineering_architecture.test_step -v
```
