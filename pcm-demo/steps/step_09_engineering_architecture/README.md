# 第 9 步：工程架构设计

## 输入与前置条件

第 9 步是项目初始化流程的必要步骤，不提供 `applicable: false` 或简单项目跳过路径。

固定输入为：

- 第 2 步 `steps/02.json.outputs` 指向的两份非空产品定义；
- 第 5 步固定项目准备清单 `docs/requirements/项目准备清单.md`；
- 第 7 步固定总体技术方案 `docs/design/技术方案.md`；
- 第 8 步成功结果和状态中的有序 `applicable_repositories`、`repositories` clean 交接事实。

运行状态必须位于 `project:09_engineering_architecture`。产品工作区必须位于状态记录的独立工作区根下且不是符号链接；第 8 步列出的每个权威仓库必须是自身 Git top-level、位于 `main` 且 clean。Python 不从固定前后端目录、Agent 回复或其它历史文字补充仓库。

## Agent、决策与固定产物

步骤在产品根使用一个公共 `agent_decision_loop` conversation 和一个 Claude Agent SDK session：

- conversation/session 领域键固定为 `engineering_architecture`；
- 初始提示第一行固定调用 `/engineering-architecture`；
- 固定输出为 `docs/design/工程架构设计.md`；
- 单次 Agent 上限为 48 turns、`$16`，同一历史最多 8 轮结构化决定；
- 新 conversation 的动态 XML system snapshot 使用 `<role>`、`<project_context>`、`<responsibility>`、`<completion>`、`<output>` 五段；步骤规则位于 completion，output 单独约束 `AgentDecision` 字段组合；恢复时严格使用历史首条 system，不重新渲染覆盖。

`AgentDecision` 的输出约束为：`completed` 时 `answer` 为空且 `required_inputs` 为空；`continue` 时 `answer` 非空且 `required_inputs` 为空；`blocked` 时 `answer` 为空且 `required_inputs` 非空；所有结果的 `reason` 均非空。公共层使用一次 `responses.parse` 和 Pydantic 输出，不手写解析、不注入决定、不格式重试。

Agent 基于权威输入和实际工程，把总体技术方案落实为可执行的工程结构与协作规则。初始工程架构调用只允许创建或更新固定文档，不得实现业务功能、修改工程代码或配置、修改项目规则、执行 Git 写操作或处理秘密。每次请求 AI-compatible 决定前，步骤都会重新核验仓库工作树边界；范围外修改不会进入负责人裁决。

## 完成核验与提交执行锚点

负责人返回 `completed` 后，程序 completion verifier 按固定顺序处理：

1. 文档缺失或为空时，向原 session 发送固定文档 repair prompt，只允许补全 `docs/design/工程架构设计.md`，禁止其它修改和 Git 写操作；
2. 文档存在后，无论相对当前提交是否发生变化，都必须向同一 session 发送一次固定 `/commit-changes` repair prompt；
3. 该提交提示只授权 `commit-changes` 核验并在适用时暂存、提交固定文档；如果发现文档事实矛盾，Skill 可以严格不修改、不暂存、不提交并报告；
4. 提交执行锚点接受 conversation 中任意一条与固定 commit prompt 完全相等的 `assistant` 消息，只要其后紧邻同一 conversation 的非空 `user` Agent 回复且状态仍记录原 Claude session；它不要求该 prompt 位于最后一个 user 之前，也不强制工程架构和提交拆成固定轮次；
5. commit-changes 执行轮结束后，外层负责人仍可通过普通 `continue` 限定通用 Claude Agent 只修正固定文档并精确提交。这是公共循环的后续指令，不是 commit-changes Skill 内部越权行为。

最终成功必须同时满足：

- 固定工程架构文档为非空、非符号链接普通文件且已被产品根 Git 跟踪；
- 根仓库和全部适用子仓仍是各自自身 top-level、位于 `main` 且 clean；
- 固定 `/commit-changes` 调用具有有效的紧邻 Agent 回复锚点；
- `steps/09.json` 为 `status=success`、`applicable=true`，唯一输出为 `docs/design/工程架构设计.md`。

Python 只读 Git，只核验 top-level、当前分支、全仓/固定文档 status 和固定文档 tracked；不读取或保存 HEAD、SHA、提交数或历史形态，也不执行任何 Git 写操作。

## 工作树边界、恢复与安全拒绝

- fresh 入口第一次启动 Agent 前要求全体权威仓库 clean；任何既有 `engineering_architecture` session、conversation 引用、步骤私有状态或历史文件都使 fresh 入口失败；
- Agent 开始后，所有适用子仓必须始终 clean；产品根只允许固定工程架构文档产生 dirty；
- conversation 文件和 `conversations/` 父目录都必须位于当前 run 内且不是符号链接；conversation 叶文件或父目录为符号链接时均拒绝；
- 已存在 Agent 执行事实时，恢复必须同时具备原 session、conversation 引用和实际历史文件；缺少锚点时拒绝静默新建 session；
- conversation 尾部为 `user` 时先裁决，不重复 Agent；普通 `assistant` repair/continue 提示恢复原 session；
- 只有完整 `status=success` 结果是幂等锚点。成功结果写入而状态推进中断时，重验固定文档、提交锚点和全仓 clean 后推进；成功后文档或仓库漂移则拒绝复用。
- `run_step.py` 只对 schema 完整的第 8、9 步 success 保护既有 result 和已经推进的 state；后续重跑即使失败，也不会覆盖该 success 或把节点回退。字段残缺的 success 不构成保护锚点；其它步骤保持原有入口行为。

成功后状态推进到 `project:10_ui_ux_framework`。第 10 步仍是按需的产品级 UI/UX 框架步骤。

## 自动化验证

已执行并通过：

- 第 9 步专属 29 项；
- 公共循环 24 项；
- 第 7 步 8 项；
- 第 8 步 17 项；
- 上述相关定向测试共 78 项；
- 全量 `unittest` 141 项；
- `compileall` 与 `git diff --check`；
- IDE 对第 9 步无诊断。

先前审查中关于 Skill 职责概念的意见已经由用户纠正，不作为遗留问题；本轮文档更新后的最终审查由主代理执行。

## 真实验证

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
