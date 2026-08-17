# PCM 自动化流程 Demo 项目设计

> 本文定义 PCM 正式开发前的轻量 Python 验证项目。Demo 的目的不是提前实现正式 PCM，而是用可独立运行、可串联的一组脚本真实验证 [`PCM版AI Agent自动化流程设计.md`](../../.claude/PCM%E7%89%88AI%20Agent%E8%87%AA%E5%8A%A8%E5%8C%96%E6%B5%81%E7%A8%8B%E8%AE%BE%E8%AE%A1.md)。
>
> Demo 采用阶段性实施和逐步验证，不预设在一天内完成。首个阶段优先打通最小骨架、Claude Agent SDK 调用、会话恢复和首个纵向切片；后续按步骤逐个实现、单独验证，最终再进行完整端到端运行。允许代码朴素、只支持一个本地样例，不追求正式系统的通用性和可靠性。

## 一、验证目标

给定一个现有产品需求文档，通过一条命令自动完成：

1. 第 0～10 步项目初始化；
2. 生成完整但规模可控的 Backlog；
3. 对每个需求循环执行第 11～19 步；
4. 在活动步骤内部完成文档补充、实现修复和重新验证；
5. 遇到真实外部依赖时保存进度并停止；
6. 人补齐资源后从原步骤继续；
7. 所有需求完成后执行项目最终检查。

最终验证命令形态：

```bash
python run_all.py --prd "../docs/prd/修迹-产品需求文档-v1.md"
```

## 二、明确不做

Demo 不建设：

- Web 管理界面；
- 数据库或正式状态存储；
- 工作流引擎或 DSL；
- 复杂状态机和步骤回退；
- 分布式队列和并发任务；
- 多用户、多租户和多项目管理；
- 容器调度和正式安全隔离；
- 向量记忆、知识库或复杂上下文压缩；
- 通用多模型框架；
- 自动 push、部署或生产操作；
- 正式 PCM 的权限、审计、计费和运维体系。

Demo 只保留跑通完整流程必需的脚本、薄封装、JSON 状态和日志。

## 三、黄金项目输入

第一轮端到端验收使用现有产品需求文档：

```text
docs/prd/修迹-产品需求文档-v1.md
```

对应项目为“修迹 MendMark——基于 Web 的社区物品维修预约与维修进度协作系统”。该项目是正常 PCM 项目，不使用专用流程或硬编码结果。选择它是因为：

- PRD 已明确产品目标、用户角色、业务闭环、范围边界、数据要求和验收标准，可以验证“已有项目资料”输入路径；
- 可以覆盖前端、后端、数据库以及送修用户、维修服务者、门店运营人员和平台管理员等多角色业务；
- 可以拆出多个有依赖关系的需求，验证 Backlog 和需求循环；
- 问题描述引导卡、维修进度时间轴和维修档案册具有明确的 UI/UX 验证价值；
- 首版核心流程可以使用本地数据库、站内通知、样例图片和初始化数据完成；
- 首版不依赖真实支付、地图、物流、即时聊天或自动诊断服务；
- 可以通过本地测试、真实服务和浏览器完成验收。

完整运行通过 `--prd` 接收源 PRD。程序将源文件复制到本次运行的独立工作区，记录源路径和内容哈希，后续步骤只读取或修正工作区副本，不修改当前能力仓库中的原始 PRD。

因为输入已经是完整产品初稿，第 0 步应确认输入充分后无副作用跳过；第 2 步仍需调用 `project-intake` 核验和收敛工作区副本，使其成为被开发项目的当前权威产品定义。源 PRD 只提供产品要求，不提供预生成的技术方案、Backlog、TRD、代码或验收结论，因此不会把目标实现作为隐藏答案交给 Agent。

完整 Demo 默认只承诺实现 PRD 中“E.1 当前必须实现”的首版范围。“E.2 重要增强”和“E.3 未来扩展”不得自动进入首轮 Backlog，除非它们是完成 E.1 闭环不可缺少的条件。

修迹项目跑通后，可以换第二份符合 PCM 准入条件的 PRD 直接运行，用于发现脚本和提示词中的项目、品牌或文件名硬编码，但不属于第一轮完成条件。

## 四、项目位置与边界

Demo 计划位于当前工作区根目录：

```text
pcm-demo/
```

它是 PCM 前置验证工具，不属于被开发项目的 `frontend/` 或 `backend/`。实际被 Agent 开发的项目放在 Demo 的可丢弃工作区中：

```text
pcm-demo/workspace/<run-id>/
```

Demo 不直接在当前 `pcm-agent-skills` 能力仓库中执行项目初始化、功能分支和合并，避免验证过程破坏当前仓库。

实现前应明确把 `pcm-demo/` 作为本工作区工具代码的例外边界；是否单独初始化 Git 不属于本次文档设计的强制要求。

## 五、最小目录结构

```text
pcm-demo/
├── pyproject.toml
├── .env.example
├── README.md
│
├── common/
│   ├── config.py
│   ├── ai_chat.py
│   ├── claude_agent.py
│   ├── command.py
│   ├── files.py
│   └── state.py
│
├── prompts/
│   ├── decisions/
│   └── steps/
│
├── steps/
│   ├── step_00_product_draft.py
│   ├── step_01_create_workspace.py
│   ├── step_02_project_intake.py
│   ├── step_03_solution_design.py
│   ├── step_04_assemble_projects.py
│   ├── step_05_project_readiness.py
│   ├── step_06_project_bootstrap.py
│   ├── step_07_initialize_repositories.py
│   ├── step_08_engineering_architecture.py
│   ├── step_09_ui_ux_framework.py
│   ├── step_10_requirement_breakdown.py
│   ├── step_11_select_requirement.py
│   ├── step_12_finalize_trd.py
│   ├── step_13_create_feature_branches.py
│   ├── step_14_develop.py
│   ├── step_15_ui_ux_review.py
│   ├── step_16_merge_code.py
│   ├── step_17_sync_status.py
│   ├── step_18_merge_root.py
│   └── step_19_retrospective.py
│
├── run_step.py
├── run_all.py
│
├── runs/
└── workspace/
```

目录可以在实现时按实际代码量合并。不要为了保持目录结构而创建无内容模块。

## 六、公共封装

### 1. OpenAI-compatible LLM 调用

`common/ai_chat.py` 使用 `openai` Python 包调用支持相同消息格式的模型服务。模型不限定为 OpenAI 模型。

最小接口：

```python
async def chat(messages: list[dict], *, model: str | None = None) -> str:
    ...
```

约定：

- `base_url`、`api_key` 和 `model` 从环境配置读取；
- 历史消息由 Demo 自己维护和保存；
- 调用封装不依赖服务端 conversation 或 response ID；
- 需要结构化决策时，通过提示词要求返回 JSON，并在 Python 中解析；
- 解析失败可以进行少量重试，持续失败则当前步骤返回 `failed`；
- 不在日志和状态文件中保存密钥。

### 2. Claude Agent SDK 调用

`common/claude_agent.py` 只封装 Demo 实际需要的能力：

```python
async def run_claude(
    prompt: str,
    *,
    cwd: Path,
    resume_session_id: str | None = None,
) -> ClaudeRunResult:
    ...
```

返回：

```python
@dataclass
class ClaudeRunResult:
    success: bool
    result: str
    session_id: str | None
    error: str | None
```

约定：

- `cwd` 始终指向当前运行的项目工作区根目录；
- 加载项目 `.claude/`、Skills 和必要设置；
- 消费并打印关键消息和工具执行信息；
- 检查最终 Result 类型，不因收到文本就假定成功；
- 捕获并保存 session ID；
- 开发修复等场景可以恢复原 session；
- Claude session 只保存 Agent 对话上下文，文件和 Git 事实仍从工作区读取。

### 3. 命令和 Git 调用

`common/command.py` 提供一个简单命令执行函数，返回：

```text
退出码
标准输出
标准错误
```

Git 命令必须显式指定目标仓库，不在根目录使用宽泛暂存或清理命令。提交仍通过 `commit-changes` 完成；建分支和合并由步骤脚本显式执行。

### 4. 文件和状态

`common/files.py` 负责 JSON、Markdown 和目录的简单读写。

`common/state.py` 负责读取和覆盖当前运行的 `state.json`，不建设数据库、事件系统或复杂锁。

## 七、配置与输入

`.env.example` 至少说明以下配置键，实际值保存在被 Git 忽略的 `.env` 中：

```text
LLM_BASE_URL=
LLM_API_KEY=
LLM_MODEL=
ANTHROPIC_API_KEY=
```

如果 Claude Agent SDK 通过当前环境的其他认证方式运行，按实际支持方式配置，不伪造凭据。

完整运行的输入包括：

- 现有产品需求文档路径；
- 当前能力仓库或待复制的项目工作区来源；
- 可用基础模板或脚手架来源；
- AI-compatible 模型配置；
- Claude Agent SDK 认证和运行环境；
- Git、Python、Node.js、包管理器和浏览器等本机工具；
- 修迹首版不需要的外部服务默认不提供。

程序必须在开始运行时校验 PRD 文件存在且可读，将其复制到独立工作区，并在 `state.json` 中记录源路径、源文件 SHA-256 和工作区副本路径。源文件后续发生变化不影响已开始的运行；`--resume` 始终继续使用原工作区副本。

缺少不可替代资源时允许在运行中阻塞。

## 八、步骤脚本约定

每个步骤脚本：

1. 可以单独运行；
2. 从命令行参数或 `state.json` 读取输入；
3. 调用一个或多个公共封装、Skill 或确定性命令；
4. 在当前步骤内部处理局部修正和重新核验；
5. 输出一个步骤结果 JSON；
6. 只返回 `success`、`blocked` 或 `failed`；
7. 成功返回退出码 `0`，阻塞和失败返回非 `0`；
8. 不自行推进其他外层步骤；
9. 不静默覆盖无法判断的已有文件或 Git 状态。

最小结果示例：

```json
{
  "step": 14,
  "name": "实现与验证",
  "status": "blocked",
  "summary": "支付接口需要真实商户凭据",
  "outputs": [],
  "blocked": {
    "reason": "缺少 PAYMENT_MERCHANT_ID",
    "required_inputs": ["PAYMENT_MERCHANT_ID"],
    "resume_step": 14
  },
  "error": null
}
```

## 九、最小运行状态

每次完整运行创建：

```text
runs/<run-id>/
├── state.json
├── steps/
└── logs/
```

`state.json` 示例：

```json
{
  "run_id": "20260816-153000",
  "status": "blocked",
  "input": {
    "type": "prd",
    "source_prd": "../docs/prd/修迹-产品需求文档-v1.md",
    "source_sha256": "<sha256>",
    "workspace_prd": "docs/prd/修迹-产品需求文档-v1.md"
  },
  "project": {
    "name": "修迹 MendMark",
    "repository": "mendmark"
  },
  "workspace": "workspace/20260816-153000",
  "current_step": 14,
  "active_requirement": "REQ-003",
  "completed_requirements": ["REQ-001", "REQ-002"],
  "claude_sessions": {
    "project_intake": "session-id",
    "REQ-003:trd": "session-id",
    "REQ-003:development": "session-id"
  },
  "blocked": {
    "reason": "缺少不可替代的外部资源",
    "required_inputs": ["EXTERNAL_RESOURCE"],
    "resume_step": 14
  },
  "error": null
}
```

不保存完整工作流历史。每一步的详细输入和结果分别写入 `steps/`，日志写入 `logs/`。

## 十、运行方式

### 单步验证

```bash
python run_step.py --step 2 --run-id <run-id>
```

或者：

```bash
python -m steps.step_02_project_intake --run-id <run-id>
```

### 区间调试

```bash
python run_all.py \
  --run-id <run-id> \
  --from-step 11 \
  --to-step 15
```

### 从 PRD 完整运行

```bash
python run_all.py \
  --prd "../docs/prd/修迹-产品需求文档-v1.md"
```

### 阻塞或失败后继续

```bash
python run_all.py --resume <run-id>
```

恢复时：

1. 读取原 `state.json`；
2. 使用原工作区；
3. 检查当前文件、Git 和外部资源；
4. 重新执行当前步骤；
5. 当前步骤成功后继续后续步骤。

## 十一、一键流程逻辑

```python
async def run_project(prd_path: Path) -> None:
    project_input = await prepare_prd_input(prd_path)
    await run_initialization_steps(project_input)  # 0～10

    while True:
        requirement = await select_next_requirement()
        if requirement is None:
            break

        await run_requirement_steps(requirement)  # 11～19

    await run_final_project_check()
```

步骤内部只使用普通条件和循环。例如第 15 步：

```python
while True:
    review = await run_ui_ux_after()

    if review.passed_or_not_applicable:
        return success()

    await handle_review_findings_inside_current_step(review)
    await rerun_affected_verification()
```

`handle_review_findings_inside_current_step` 根据问题调用负责修改的能力，但外层步骤编号不回退。

## 十二、建议实现顺序

下一开发会话按以下顺序实现，不要求一次写出所有复杂逻辑：

1. 建立 `pcm-demo/` 和最小配置；
2. 实现 AI-compatible 聊天封装；
3. 实现 Claude Agent SDK 封装并完成一次指定目录调用；
4. 实现命令、文件和 `state.json` 读写；
5. 建立统一步骤入口和结果格式；
6. 按第 0～19 步逐个实现和单独验证；
7. 实现 `run_all.py` 的初始化流程；
8. 实现 Backlog 需求循环；
9. 实现 `--resume`；
10. 使用《修迹》PRD 完整运行，并确认源 PRD 未被修改；
11. 根据真实失败只修正阻断跑通的问题；
12. 记录正式 PCM 需要重新设计的事实和风险。

## 十三、完成标准

Demo 完成需要同时满足：

1. 第 0～19 步均有独立可运行脚本；
2. 每一步至少单独成功验证一次，或明确证明在修迹项目中不适用；第 0 步必须验证为无副作用跳过；
3. AI-compatible 模型能够完成必要的语义决策；
4. Claude Agent SDK 能在指定工作区调用项目 Skills、修改文件和执行验证；
5. 上一步输出能够成为下一步输入；
6. `run_all.py` 能从指定 PRD 开始执行第 0～10 步，正确复制输入、记录哈希并使用工作区副本；
7. 至少两个需求经过第 11～19 步，证明需求循环真实发生；
8. 活动步骤内的修正和重新核验可以完成，不需要外层步骤回退；
9. 至少验证一次人工补充资源后的 `--resume`，可以使用人为制造的非秘密测试阻塞；
10. 所有 Backlog 需求完成后，项目最终检查通过；
11. 最终生成的根仓库、前端和后端项目可以真实安装、构建、启动和验收；
12. 输出一份简短的 Demo 结论，记录可行能力、失败点、成本耗时和正式 PCM 的设计输入；
13. 完整运行前后，当前能力仓库中的 `docs/prd/修迹-产品需求文档-v1.md` 内容哈希保持不变。

## 十四、Demo 结论应回答的问题

完整运行后至少回答：

- Claude Agent SDK 加载当前项目能力是否稳定；
- Skills 在程序化调用下与人工会话有何差异；
- 哪些步骤最需要 AI 决策；
- 哪些步骤应该保持确定性脚本；
- 跨步骤上下文需要保存哪些最小信息；
- Claude session 恢复是否能支持开发和审查修正；
- 多仓库分支、提交和合并是否可以可靠自动化；
- 哪些外部资源会成为真实阻塞；
- 一次完整项目开发的模型成本和运行时间；
- 正式 PCM 最优先需要设计的模块是什么。

这些真实结论是 Demo 的主要价值，不要求 Demo 代码直接演进为正式 PCM。
