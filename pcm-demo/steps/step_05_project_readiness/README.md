# 第 5 步：核验项目准备状态

## 输入

- 运行状态位于 `project:05_verify_readiness`，且产品根 Git 仓库与状态记录一致。
- `steps/02.json` 成功，引用两份位于产品工作区内、非空且非符号链接的权威产品定义文件。
- `steps/03.json` 成功，`template_selection` 可由 `FoundationSelectionResult` 校验；传入提示的选型仅投影 `applicable`、`id`、`default_branch`、`path`、`reason`，不传 `git_url` 或 `origin`。
- `steps/04.json` 成功，已组装工程、来源证据和临时目录现场均与选型和状态一致；每个适用 `frontend` / `backend` 都是自身 top-level 为目录本身、`main`、unborn HEAD、空 index 的独立 Git 仓库，不适用端不存在。
- `PCM_DEV_RESOURCE_LIST` 是可读、非符号链接普通文件的绝对路径。Python 不读取或解析正文，只将路径交给 Agent。

## 行为

在产品项目根显式调用 `/project-readiness`。首条提示第一行保留 slash command，正文只描述产品定义、实际工程、最小选型公开事实、动态可信资源资料和项目准备领域约束；不包含步骤号、PCM 节点、session 或其它外层编排语义。

Agent 为当前项目周期建立唯一、完整的准备基线：从最终产品范围推导开发、联调、真实体验验收和交付所需的不可替代条件，再对照任意格式的动态资源资料匹配资源。在授权、配置合同和安全边界允许时，实际准备项目专用开发/测试资源和最小权限运行凭据。每项被判为 `ready` 的外部运行资源都必须把最终项目运行凭据和资源绑定持久化到所属仓库被 Git 忽略的实际 `.env` 或等价受保护配置，确保后续开发无需重新读取共享资源清单；即使消费代码稍后实现，只要配置键、归属和用途可以唯一确定，也应先建立最小配置键合同。同步无秘密的 `.env.example` 或既有公开示例及必要说明，含秘密配置在 POSIX 上通常使用 `0600`，并使用最终项目运行凭据验证身份、权限和所需最小读写能力。

项目准备清单只是实际准备结果的脱敏记录，不能为 `ready` 自证。管理凭据、资源说明、Mock、截图、文档自述或 Agent 口头结论不能替代实际工具证据。任何最终范围必要条件仍为 `missing`、`pending` 或没有真实核验证据时都必须阻塞，并说明外部输入、影响和复验方式。

完整依赖安装、构建、测试、应用启动、基础联调、业务实现、最终体验验收和发布执行不在本次提前实施，但这些工作需要的资源、身份、数据、浏览器、视口、回调、权限和其它前置条件必须纳入当前准备基线。不得创建生产、未授权付费或不可逆资源，不得泄露秘密、改变既有 Git 边界，或执行 Git 暂存、提交、分支、合并、push。

## 统一决策与恢复

本步骤只维护 readiness 的 `DECISION_RULES`。新 conversation 的完整 XML system snapshot 由 `common/decision.py` 渲染，严格包含 `<role>`、`<project_context>`、`<responsibility>`、`<completion>`、`<output>` 五段。项目上下文仅包括两份产品定义原文、适用工程、选型白名单投影，以及资源清单的绝对路径和可读性；不读取或内联资源清单正文或 `.env`。恢复严格使用历史 `messages[0]`，不重渲染或覆盖。

每次 Agent 调用保存 init 核验、session 和安全的终止摘要；完整真实 Agent 回复先作为决策历史 `user` 消息保存，再交给步骤专属决策 system prompt 生成统一 `AgentDecision`：

- `continue` 表示仍有可使用现有事实和工具完成的资源准备、项目凭据持久化、公开配置键合同、文件权限、最小权限验证或证据补全工作，非空 `answer` 原样发送给同一 session。
- `completed` 表示负责人根据 Agent 的实际工具结果相信完整准备基线已建立：所有必要条件均为真实 `ready` 或有事实依据的 `not-applicable`，不存在必要的 `missing`、`pending` 或未验证项；所有 `ready` 外部运行资源均已把最终凭据绑定持久化到项目受保护配置并同步公开键合同，不能只留在共享资源资料中；含秘密配置权限安全；清单自身不构成完成证据。程序随后重新核验前序交接、产品根和全部适用子仓 Git 边界及非空普通清单。
- 清单缺失或为空时，程序向同一 session 追加固定修复提示，要求继续完成实际准备、每项 `ready` 外部资源的项目凭据持久化、公开示例、文件权限和最终运行凭据验证，不能只补文档后宣称完成；交接、路径、Git 或文件类型冲突为 `failed`。
- `blocked` 只表示必要条件需要当前环境无法取得的真实外部账号、运行凭据、私有数据、授权、设备、素材、付费服务、外部决定或线下动作；终止前同样复核 Git 边界，清单已存在时保留输出引用。
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
