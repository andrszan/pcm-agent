# 第 5 步：核验项目准备状态

## 输入

- 运行状态位于 `project:05_verify_readiness`，且产品根 Git 仓库与状态记录一致。
- `steps/02.json` 成功，引用两份位于产品工作区内、非空且非符号链接的权威产品定义文件。
- `steps/03.json` 成功，`template_selection` 可由 `FoundationSelectionResult` 校验；传入提示的选型仅投影 `applicable`、`id`、`default_branch`、`path`、`reason`，不传 `git_url` 或 `origin`。
- `steps/04.json` 成功，已组装工程、来源证据和临时目录现场均与选型和状态一致；每个适用 `frontend` / `backend` 都是自身 top-level 为目录本身、`main`、unborn HEAD、空 index 的独立 Git 仓库，不适用端不存在。
- `PCM_DEV_RESOURCE_LIST` 是可读、非符号链接普通文件的绝对路径。Python 不读取或解析正文，只将路径交给 Agent。

## 行为

在产品项目根显式调用 `/project-readiness`。首条提示第一行保留 slash command，正文只描述产品定义、实际工程、最小选型公开事实、动态可信资源资料和项目准备领域约束；不包含步骤号、PCM 节点、session 或其它外层编排语义。

Agent 为当前 PCM 自动化开发周期建立唯一的开发资源准备基线：从产品范围和工程事实识别完成编码、开发环境联调和开发环境真实验收所需、且必须由调用方提供的外部服务、账号、凭据、授权素材、私有数据或专用设备，再对照任意格式的动态资源资料匹配候选。在授权、配置合同和安全边界允许时，实际准备项目专用开发/测试资源和最小权限运行凭据。每项被判为 `ready` 的外部运行资源都必须把最终项目运行凭据和资源绑定持久化到所属仓库被 Git 忽略的实际 `.env` 或等价受保护配置，确保后续开发无需重新读取共享资源清单；即使消费代码稍后实现，只要配置键、归属和用途可以唯一确定，也应先建立最小配置键合同。同步无秘密的 `.env.example` 或既有公开示例及必要说明，含秘密配置在 POSIX 上通常使用 `0600`，并使用最终运行凭据验证身份、权限、隔离和所需最小行为。

项目准备清单只是实际资源准备结果的脱敏记录，不能为 `ready` 自证。管理凭据、资源说明、Mock、截图、文档自述或 Agent 口头结论不能替代实际工具证据。只允许两类阻塞：开发必需外部资源在候选池中不存在、当前环境无法安全生成且无兼容替代；或已匹配的开发资源真实不可用、凭据无效、权限不足、隔离不合格，或缺少开发所需接口能力、可用配额、回调/白名单、沙箱范围及其它既定能力。

依赖安装、构建、测试、migration、Seed、业务实现、项目内测试账号、完整联调和浏览器验收由后续开发完成，不属于资源缺失。生产部署、正式域名、DNS/TLS、生产凭据、监控、备份恢复、容量和发布安全属于自动化开发范围外；产品规则、隐私保留和其它设计决定交给后续产品/技术设计。这些事项可以记录，但不得阻塞第 5 步。不得创建生产、未授权付费或不可逆资源，不得泄露秘密、改变既有 Git 边界，或执行 Git 暂存、提交、分支、合并、push。

## 统一决策与恢复

本步骤只维护 readiness 的 `DECISION_RULES`。新 conversation 的完整 XML system snapshot 由 `common/decision.py` 渲染，严格包含 `<role>`、`<project_context>`、`<responsibility>`、`<completion>`、`<output>` 五段。项目上下文仅包括两份产品定义原文、适用工程、选型白名单投影，以及资源清单的绝对路径和可读性；不读取或内联资源清单正文或 `.env`。恢复严格使用历史 `messages[0]`，不重渲染或覆盖。

每次 Agent 调用保存 init 核验、session 和安全的终止摘要；完整真实 Agent 回复先作为决策历史 `user` 消息保存，再交给步骤专属决策 system prompt 生成统一 `AgentDecision`：

- `continue` 表示仍有可使用现有事实和工具完成的开发资源准备、项目凭据持久化、公开配置键合同、文件权限、最小行为/隔离验证或证据补全工作，非空 `answer` 原样发送给同一 session。业务实现、生产发布或产品规则待定不在本步骤继续处理。
- `completed` 表示负责人根据 Agent 的实际工具结果相信开发资源准备基线已建立：当前开发必需外部资源均真实可用或明确不需要，不存在候选池缺失、当前环境无法安全生成且无替代，或资源不可用、凭据无效、权限/隔离不合格、必要能力/配额/回调/白名单不足；所有 `ready` 外部运行资源均已把最终凭据绑定持久化到项目受保护配置并同步公开键合同；含秘密配置权限安全；清单自身不构成完成证据。生产和后续实现事项的 `missing` / `pending` 不影响 completed。
- 清单缺失或为空时，程序向同一 session 追加固定修复提示，要求继续完成开发资源准备、每项 `ready` 外部资源的项目凭据持久化、公开示例、文件权限和最终运行凭据验证，不能只补文档后宣称完成；生产发布和后续业务实现事项必须记录为非阻塞。
- `blocked` 只允许两种情况：开发必需外部资源在候选池中缺失、当前环境无法安全生成且无兼容替代；或已匹配资源真实不可用、凭据无效、权限不足、隔离不合格，或缺少开发所需接口能力、可用配额、回调/白名单、沙箱范围及其它既定能力。不得因生产发布条件、业务实现、内部配置键待整理、产品规则待定或未来最终验收返回 blocked。
- `error_max_turns`、`error_max_budget_usd` 只有在存在 session 和非空回复时才可裁决，最终完成前必须恢复一次正常 `success`。400/429/500、连接、CLI/进程、无 `ResultMessage` 与其它 SDK/API 错误返回 `failed`，不增加外层自定义 HTTP 重试。

`conversations/project_readiness.json` 尾部是调度真相：`user` 尾部先裁决，结构化 `continue` 尾部执行 answer，`completed` 尾部先核验，`blocked` 尾部停止；显式从 `blocked` 重跑才重新核验。状态不写 `pending_agent_prompt`、决策轮次或 Python 完成声明，只保留 session、对话路径引用、最后一次 Agent 终止摘要和短暂的待写入 Agent 原文。

## 输出与幂等

成功产物仍只有 `docs/requirements/项目准备清单.md`，`steps/05.json.outputs` 只记录该相对路径。成功结果另保存无秘密的 `readiness_baseline`：

- `checklist_sha256`：成功时准备清单字节的 SHA-256；
- `product_outputs_sha256`：成功时两份权威产品定义按相对路径记录的 SHA-256。

该指纹只防止已经完成的准备基线被静默替换，不证明资源本身 `ready`，也不记录或哈希 `.env`、凭据、资源清单正文或资源语义。第 6、7、9、10、11 步消费第 5 步结果时都会重新比对当前清单和产品定义；缺少指纹的旧成功结果、清单漂移或产品范围漂移均不可复用，不能自动升级或补写历史证据。

步骤先写成功结果，再推进到 `project:06_bootstrap_foundation`。若成功结果后状态写入中断，重跑以严格成功结果、当前清单、产品定义和 Git 边界恢复推进；完整成功重跑不再次调用 Agent 或重复资源副作用。`failed` / `blocked` 结果不视为成功，也不阻止恢复原 session。

## 运行

```bash
cd /Users/zhou/resource/fireworks/ANDRSZAN/pcm-agent-skills/pcm-demo
uv run python run_step.py --step 5 --run-id <run-id>
```
