# PCM 自动化流程 Demo

PCM Demo 是正式 PCM 开发前的本地验证工具。它使用 Python 串联确定性操作、AI-compatible 结构化决策和 Claude Agent SDK，在独立产品工作区中真实执行产品定义、工程准备、设计、逐需求开发、验证、提交与合并流程。

当前已实现第 0～18 步及阶段一需求循环；`run_all.py` 会持续处理需求注册表，直到当前正式需求全部完成。阶段二全项目体验审计与迭代尚未实现。

本项目只验证流程可行性，不建设正式 PCM 的 Web 管理界面、数据库、分布式调度、多项目并发、部署或生产运维能力。

## 流程概览

```text
产品初稿
→ 建立外部产品工作区
→ 收敛产品定义
→ 选择并组装基础工程
→ 准备开发资源并完成项目化
→ 形成技术方案、工程架构、UI/UX 框架和 Backlog
→ 初始化需求注册表
→ 逐需求执行 TRD、开发验证、规则复盘、提交和 ff-only 合并
→ 阶段一完成
```

执行职责分为三层：

- **Python 编排器**：状态转换、文件与路径校验、确定性 Git 操作、失败停止和恢复；
- **AI-compatible 模型**：产品、技术和执行过程中的结构化负责人决策；
- **Claude Agent SDK**：在目标产品工作区加载项目 Skills、plugins 和工具，修改文件并执行真实验证。

产品代码不存放在本仓库中，而是发布到：

```text
<PCM_WORKSPACE_ROOT>/<project_directory_name>/
```

`pcm-demo/runs/<run-id>/` 只保存本次编排的状态、结果、对话和诊断，不是产品项目目录。

## 项目结构

```text
pcm-demo/
├── common/                 # 多个步骤真实复用的状态、Agent、决策和诊断能力
├── probes/                 # Claude Agent SDK、session 和结构化决策探针
├── steps/                  # 第 0～18 步实现、测试和步骤说明
├── docs/                   # PCM Demo 内部活动技术设计
├── config.py               # 本地配置读取与校验
├── run_step.py             # 单步骤入口
├── run_all.py              # 阶段一顺序编排入口
├── pyproject.toml
├── uv.lock
└── .env.example
```

每个步骤的详细输入、输出、完成条件和恢复边界见对应的 `steps/step_xx_*/README.md`。

## 环境准备

要求：

- Python 3.10 或更高版本；
- `uv`；
- Git；
- 可访问 Anthropic Messages 协议的 Claude Agent SDK 网关和受保护 API Key；
- AI-compatible Responses API 配置；
- 当前产品需要的模板仓库、开发资源和外部服务权限。

安装依赖：

```bash
cd pcm-demo
uv sync
```

根据 `.env.example` 创建被 Git 忽略的 `.env`，主要配置包括：

| 配置 | 用途 |
| --- | --- |
| `LLM_BASE_URL`、`LLM_API_KEY`、`LLM_MODEL` | AI-compatible 结构化决策与提取 |
| `PCM_AGENT_BASE_URL`、`PCM_AGENT_API_KEY` | Claude Agent SDK 使用的 Anthropic Messages 网关与受保护 API Key；Base URL 不包含 `/v1` |
| `PCM_AGENT_MODEL_LOW`、`PCM_AGENT_MODEL_MEDIUM`、`PCM_AGENT_MODEL_HIGH` | 低、中、高语义档位对应的网关真实模型名 |
| `PCM_WORKSPACE_ROOT` | 所有目标产品项目的外部父目录，必须位于当前能力仓库之外 |
| `PCM_TEMPLATE_CATALOG` | 基础工程候选目录 JSON |
| `PCM_TEMPLATE_REPOSITORY` | 建立产品工作区使用的固定开发管理模板仓库 |
| `PCM_AGENT_WORKSPACE_ENV_FILE` | 写入目标 AI Agent 工作区的受保护工具配置来源 |
| `PCM_DEV_RESOURCE_LIST` | 项目准备核验使用的可信开发资源清单 |

进程环境变量优先于 `.env`；`--workspace-root` 和 `--catalog-path` 可以覆盖对应配置。AI-compatible 与 Claude Agent SDK 使用独立配置，当前即使指向同一代理服务也不相互回退。PCM 将 Agent 配置转换为 `ANTHROPIC_BASE_URL`、`ANTHROPIC_API_KEY`，压住 `LLM_*`、其它 PCM 编排控制键和冲突认证，并把 `CLAUDE_CODE_SUBAGENT_MODEL` 同步为当前主模型；项目自定义 `dev`、`reviewer` 继续使用 `model: inherit`。`PCM_AGENT_WORKSPACE_ENV_FILE` 仍只由第 1 步安装为目标产品根受保护 `.env`，不合并进 SDK 子进程环境。

固定 Agent profile：

| 步骤 | 模型档位 | effort |
| --- | --- | --- |
| 2、5、7、9、10、11 | 高 | `high` |
| 6（bootstrap/theme）、14、15 | 中 | `high` |
| 8、16、17 | 中 | `medium` |

第 15～17 步恢复同一个 development session 时始终使用中模型；每次 Agent 首次调用和 resume 都重新显式传入 model 与 effort。当前不为 Agent 步骤使用低模型，不配置 fallback model 或 `max_budget_usd`，并保持各步骤既有最大 turn 与负责人决策轮数。

网关真实 GPT 模型名可被 Claude Code 记录为 `unrecognized_model` 警告，但已验证不阻止 Agent SDK 调用；PCM 仍要求 init 返回的实际模型与配置一致。Claude Code 的 `total_cost_usd` 不代表当前订阅代理的真实分模型成本。

## 运行方式

### 从产品初稿运行阶段一

```bash
uv run python run_all.py \
  --product-draft "../docs/prd/修迹-产品需求文档-v1.md" \
  --run-id "mendmark-20260901"
```

`--run-id` 可省略，程序会生成带 UTC 时间戳的运行 ID。也可以按需传入：

```bash
--workspace-root /absolute/path/to/products
--catalog-path /absolute/path/to/catalog.json
```

### 恢复已有运行

```bash
uv run python run_all.py --resume <run-id>
```

恢复只重新进入 `state.json` 指向的当前节点；不会从头重跑已经完成的流程。

### 单独运行当前步骤

```bash
uv run python run_step.py --step <0-18> --run-id <run-id>
```

第 0 步首次运行还需要 `--product-draft`。`run_step.py` 主要用于定向开发、验证和恢复；完整流程优先使用 `run_all.py`。

## Run 目录与产物

```text
runs/
├── .run_all.lock
└── <run-id>/
    ├── state.json
    ├── steps/
    │   ├── 00.json
    │   ├── ...
    │   └── requirements/
    │       └── <requirement-id>/
    │           ├── 13.json
    │           └── ...
    ├── conversations/
    │   └── <domain-key>.json
    └── logs/
        ├── <domain-key>-agent.json
        ├── <domain-key>-decision.json
        └── step-<step>-error.json
```

### 产物职责

- `state.json`：当前 phase、node、step、活动需求、需求注册表、session 引用和恢复所需最小状态；
- `steps/XX.json`：第 0～12 步最近一次业务结果；
- `steps/requirements/<ID>/XX.json`：第 13～18 步按需求隔离的业务结果；
- `conversations/*.json`：Claude Agent 回复与 AI-compatible 负责人决定组成的完整编排历史；
- `logs/*.json`：结构化故障诊断快照，不是普通执行流水。

### `logs/*.json` 命名

| 命名 | 内容 |
| --- | --- |
| `<domain-key>-agent.json` | Claude Agent SDK 执行错误、终止原因、SDK errors 和异常信息 |
| `<domain-key>-decision.json` | AI-compatible 决策服务的 provider code、HTTP status 和异常信息 |
| `step-XX-error.json` | 参数、路径、状态、文件、Git 或其它本地步骤异常 |

诊断文件采用 JSON，是为了保存稳定 schema、精确脱敏、异常链、traceback 位置和可供程序引用的字段。同名文件会原子覆盖为该领域最近一次故障快照。

诊断文件在恢复成功后可以继续保留，因此**文件存在不表示当前仍然失败**。当前运行状态应以 `state.json` 的 `status`、`current_node`、`error`、`blocked` 以及当前步骤结果为准。

`run_all.py` 和 `run_step.py` 不会在 `runs/` 根目录创建 `.log` 文本文件；此类文件通常来自外部 Shell 的 stdout/stderr 重定向，不属于恢复状态或正式结果。

### 全局锁

`runs/.run_all.lock` 是当前 Demo 的全局 `run_all.py` 互斥锁，同一时间只允许一个完整编排运行。锁由操作系统持有，空文件长期存在是正常现象，不能根据文件是否存在判断编排是否仍在运行。

## 状态、停止与恢复

步骤只返回三种业务状态：

- `success`：完成条件满足，或确认不适用并无副作用跳过；
- `blocked`：缺少当前环境无法取得的不可替代外部资源；
- `failed`：输入、配置、程序、模型、SDK、文件、Git 或验证发生错误。

`run_all.py` 遇到非 `success` 会立即停止并打印恢复命令。文件、Git 和运行现场会保留，问题解除后使用同一 run ID 恢复。

只有 Claude Agent SDK 执行通道明确请求重试时，`run_step.py` 才会按 10 秒、30 秒有界重跑当前步骤；业务 `blocked`、普通 `failed`、负责人裁决失败、本地合同错误和主动取消不会自动重试。

Demo 默认只执行本地文件、本地服务和本地 Git 操作，不自动 push、部署或操作生产环境。

## 验证

```bash
uv run python -m unittest discover -s . -t . -p 'test*.py' -v
uv run python -m compileall common steps run_step.py run_all.py test_run_step_retry.py test_run_all.py
```

涉及真实步骤时，还应按对应步骤 README 完成适用的外部服务、Git、构建、测试、联调和浏览器验证。

## 设计文档

- [PCM 程序化调度的 AI Agent 产品开发流程](../.claude/PCM版AI%20Agent自动化流程设计.md)
- [PCM 自动化流程 Demo 项目设计](../docs/pcm/PCM自动化流程Demo项目设计.md)
- [PCM 自动化流程 Demo 项目 TRD](../docs/pcm/PCM自动化流程Demo项目TRD.md)

README 只维护稳定的项目入口和使用合同；具体步骤设计、真实验证证据与历史演进记录放在对应步骤说明和设计文档中。