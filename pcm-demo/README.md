# PCM 自动化流程 Demo

PCM Demo 是正式 PCM 开发前的本地流程验证工具。它用 Python 串联确定性操作、AI-compatible 负责人决策和 Claude Agent SDK，在仓库外的独立产品工作区中执行真实产品开发流程。

当前已实现第 1～18 步和阶段一需求循环：输入可以是一句话产品想法或完整初稿，流程能够建立工作区、形成产品定义、准备工程与资源、完成设计和 Backlog，再逐需求执行 TRD、开发验证、规则复盘、提交和 ff-only 合并。第 6 步还会在适用时完成项目风格定制和基础品牌资产准备。阶段二全项目体验审计与迭代尚未实现。

Demo 只验证流程可行性，不建设正式 PCM 的 Web 管理界面、数据库、分布式调度、部署或生产运维能力。当前支持同一 Demo checkout 在容量限制内并发执行不同产品；同一产品始终互斥。

产品项目位于：

```text
<PCM_WORKSPACE_ROOT>/<project_directory_name>/
```

`runs/<run-id>/` 只保存编排状态、结果、对话、诊断和计时，不是产品项目目录。

## 验证目标

第一轮端到端黄金输入是 [`docs/prd/修迹-产品需求文档-v1.md`](../docs/prd/修迹-产品需求文档-v1.md)。它只作为正常产品初稿输入，不触发专用步骤或硬编码结果；首轮范围以初稿中的当前必须实现内容为准。

完整 Demo 的完成标准是：统一入口能够顺序执行和恢复全部已定义流程；每个适用步骤有真实成功证据；正式需求均经过第 13～18 步；产品完成真实安装、测试、构建、启动、联调和浏览器验收；适用仓库最终位于预期 `main` 且工作树清楚；源初稿前后保持不变且产品项目内副本与其一致；至少验证一次外部阻塞解除后的恢复和一次进程中断后的原节点恢复；阶段二完成全产品审计、候选分流、修复回归和复审。由于阶段二尚未实现，当前能力只能完成阶段一，不能宣称整个 Demo 已端到端完成。

完整流程语义与最终停止条件以 [PCM 程序化调度的 AI Agent 产品开发流程](../.claude/PCM版AI%20Agent自动化流程设计.md) 为准。

## 环境配置

要求 Python 3.11+、`uv` 和 Git，并具备可访问的 AI-compatible Responses API、Claude Agent SDK Messages 网关，以及当前产品所需的模板和开发资源权限。

```bash
cd pcm-demo
uv sync
test -e .env || cp .env.example .env
```

只在首次配置且 `.env` 不存在时复制示例，避免覆盖已有本地凭据。配置入口：

- [`.env.example`](.env.example)：AI-compatible、Agent 网关与认证、自动压缩窗口、统一代理、工作区、模板和开发资源路径；实际 `.env` 必须保持 Git 忽略。
- [`model-policy.toml`](model-policy.toml)：Claude Agent 各任务使用的真实 `model` 与 `effort`。模型策略不再从 `.env` 的低、中、高变量读取。
- 产品工作区中的 `.env`：由流程按项目合同维护，不与 `pcm-demo/.env` 混用。

AI-compatible 与 Claude Agent SDK 使用独立配置，不相互回退。`PCM_AGENT_WORKSPACE_ENV_FILE` 只由第 1 步安装为产品工作区根的受保护工具配置，不并入 SDK 子进程环境，也不作为目标产品运行配置或开发资源清单。

修改 `model-policy.toml` 前必须停止当前编排，再使用 `uv run python run_all.py --resume <run-id>` 从原节点恢复；`run_all.py` 每次启动或恢复只读取一次策略，运行中不会热加载。策略必须完整有效，程序不会用默认模型、环境变量或命令行覆盖兜底。

## 启动与恢复

### 新建阶段一运行

流程从第 1 步建立工作区开始。入口会把产品初稿和可选初始资料交给第 1 步；产品初稿必须在创建 `runs/<run-id>/` 和调用 AI 前通过可读、UTF-8、非空白检查。

```bash
uv run python run_all.py \
  --product-draft "../docs/prd/修迹-产品需求文档-v1.md" \
  --run-id "mendmark-20260901"
```

`--run-id` 可省略。常用可选参数：

```text
--initial-resources <普通文件或目录>   只用于新运行，发布后不再同步源路径
--workspace-root <绝对路径>           覆盖 PCM_WORKSPACE_ROOT
--catalog-path <绝对路径>             覆盖 PCM_TEMPLATE_CATALOG
```

### 恢复已有运行

```bash
uv run python run_all.py --resume <run-id>
```

恢复只进入 `state.json` 指向的当前节点，并重新核验该节点负责的现场；不会从头重跑已完成流程。进程退出会释放实时执行锁，但产品登记及配对端口会继续保留。

### 单独运行当前步骤

```bash
uv run python run_step.py --step <1-18> --run-id <run-id>
```

第 1 步创建新运行时需提供 `--product-draft`，并可同时提供 `--initial-resources`。完整流程使用 `run_all.py`；单步入口用于定向开发、诊断和恢复，并遵循相同锁、状态和重试合同。

只有 Claude Agent SDK 执行通道明确请求重试时，单步入口才按 10 秒、30 秒有界重跑当前步骤。业务 `blocked`、普通 `failed`、负责人裁决失败、本地合同错误和主动取消不会自动重试。

## 用负责人指令恢复 blocked 步骤

仅当当前节点为 `blocked`，且已有对应 Agent conversation 和原 session 时，可以追加真正负责人的恢复指令：

```bash
uv run python run_all.py --resume <run-id> \
  --resume-message-file /absolute/path/to/resume-message.md
```

只处理当前步骤并在完成后停下：

```bash
uv run python run_step.py --step <当前步骤> --run-id <run-id> \
  --resume-message-file /absolute/path/to/resume-message.md
```

该文件必须是可读、非空白的 UTF-8 普通文本。正文会先完整写入当前 conversation，再原样发送给原 Claude session；它不是自由跳转、强制完成或绕过裁决轮数的入口。消息落盘后若进程中断，后续使用不带文件参数的普通 `--resume` 即可；只有确需追加新指令时才再次提供文件。

**凭据边界：文件参数只避免正文出现在 shell 命令行，不提供脱敏或秘密隔离。正文会进入 PCM 对话历史、Agent session 和模型请求。API key、令牌、密码等秘密必须先写入已有受保护配置，指令只引用配置路径、配置键和资源说明，不得直接包含秘密。** 不要手改 `state.json`、步骤结果、conversation 或 Claude session，也不要使用 stdin 管道代替该入口。

## 产品端口与锁

```bash
uv run python run_all.py --product-status /absolute/path/to/product
uv run python run_all.py --release-product /absolute/path/to/product
```

`--product-status` 展示 owner run、生命周期、前后端端口和实时 Product Lock 状态。只有确认产品不再继续开发时才使用 `--release-product`；运行锁或产品锁仍被持有、端口仍在监听或注册记录冲突时会拒绝释放。释放不会删除产品目录或 run 历史。

锁文件长期存在是正常现象，文件存在不表示锁仍被持有。**不得删除 `.lock` 文件解锁**；删除仍被持有的锁文件可能破坏互斥。应先查看产品状态，再确认归属明确的相关进程已经退出。

产品工作区存在 `.pcm/runtime.json` 时，启动、健康检查、联调、CORS 和浏览器验收必须使用其中分配的 host、port 与 endpoint，不自行改端口或允许框架静默换端口。

## 诊断与运行数据

```text
runs/<run-id>/
├── state.json                         # 当前节点、需求注册表、session 引用和恢复状态
├── timings.json                       # 步骤与 Agent/AI 调用计时和用量
├── steps/                             # 第 1～12 步及按需求隔离的第 13～18 步结果
├── conversations/<domain-key>.json   # Agent 回复、负责人决定和人工恢复指令
└── logs/*.json                        # 最近一次结构化故障诊断快照
```

诊断顺序：

1. 先看命令 stderr 给出的当前节点、结果路径和恢复命令；
2. 再看 `state.json` 与当前步骤结果，确认当前 `status`、`current_node`、`error` 或 `blocked`；
3. 需要 SDK/provider 细节时打开结果引用的 `logs/*.json`；
4. 对话恢复问题查看对应 `conversations/*.json` 和已保存 session 引用；
5. 并发或端口问题先运行 `--product-status`，不要删除锁文件。

诊断文件在恢复成功后可以继续保留，因此文件存在不表示当前仍失败。运行数据受 Git 忽略；不要在日志、提交或回复中展示 `.env` 具体值、认证头或其它秘密。

计时字段、结束原因和用量口径见 [计时与用量说明](docs/timing.md)。

## 验证

程序改动的基础验证入口是：

```bash
uv run python -m unittest discover -s . -t . -p 'test*.py' -v
uv run python -m compileall common steps run_step.py run_all.py test_run_step_retry.py test_run_all.py
```

涉及真实步骤时，还需按对应步骤说明完成适用的外部服务、Git、构建、测试、联调和浏览器验证。

## 导航

- [流程主文档](../.claude/PCM版AI%20Agent自动化流程设计.md)：流程语义、步骤职责、阶段一与阶段二、停止条件。
- [`steps/step_xx_*/README.md`](steps/)：各步骤当前输入、输出、完成条件和恢复边界。
- [通用 Agent 决策对话循环 TRD](docs/trd/20260822-PCM%20Demo%20通用%20Agent%20决策对话循环%20TRD.md)：conversation、session、人工恢复和诊断合同。
- [单机多产品并发执行 TRD](docs/trd/20260903-PCM%20Demo%20单机多产品并发执行%20TRD.md)：锁、产品登记、端口和 `.pcm/runtime.json` 合同。
- [基础品牌资产准备 TRD](docs/trd/20260910-PCM%20Demo%20基础品牌资产准备%20TRD.md)：第 6 步品牌资产任务合同。
- [`AGENTS.md`](AGENTS.md)：Demo 开发与运行约束。
