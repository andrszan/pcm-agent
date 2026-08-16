# Claude Agent SDK（Python）能力、边界与工程实践

> 调研日期：2026-08-16
> 适用对象：需要在 Python 应用中嵌入 Claude Code Agent 能力的开发者和架构设计者。
> Claude Agent SDK 和 Claude Code 更新频繁；涉及字段、模型、版本和平台支持时，应以当前官方文档与 SDK changelog 为准。

## 1. 结论摘要

Claude Agent SDK 是 Claude Code 的程序化运行形态。它不是普通的聊天 API，也不是通过键盘和屏幕自动化控制 Claude Code 终端界面的工具。

它的实际结构是：

```text
Python 应用
  ↓ Claude Agent SDK
claude 子进程（Claude Code runtime）
  ↓ agent loop
内置工具、Skills、Subagents、Hooks、MCP
  ↓
目标工作目录、Shell 和外部服务
```

SDK 会启动 Claude Code runtime，通过结构化的标准输入输出协议与其通信。Claude 仍可自主读取项目、搜索代码、编辑文件、执行命令、运行测试、调用子代理并根据结果继续工作；应用则负责提供任务、消费事件、管理会话、处理审批和控制运行环境。

核心判断如下：

| 问题 | 结论 |
| --- | --- |
| 能否对指定目录进行开发？ | 可以，通过 `cwd` 指定工作目录 |
| 能否读写代码和执行命令？ | 可以，使用 Claude Code 内置工具 |
| 能否连续自主完成多步任务？ | 可以，SDK 内置 Claude Code agent loop |
| 是否必须另装 Claude Code CLI？ | 通常不需要，Python wheel 通常捆绑 native binary |
| 是否仍然运行 Claude Code？ | 是，每个活动会话对应一个 `claude` 子进程 |
| 能否使用本机 `~/.claude/` 配置？ | 可以；binary 所在位置不决定配置目录 |
| 能否继承当前 Shell 中的 API key？ | 可以，Python SDK 默认继承父进程环境变量 |
| 能否加载项目 `.claude/`？ | 可以，由 `cwd` 和 `setting_sources` 控制 |
| 能否使用 Skills、Subagents、Hooks、MCP？ | 可以，但各功能有独立加载和权限边界 |
| 能否完全替代 Claude Code CLI？ | 核心 Agent 能力接近，但没有终端 UI 和部分交互式专属能力 |
| 能否使用任意 OpenAI-compatible 模型？ | 不能直接视为官方支持；官方支持的是 Claude 模型及规定的 API 格式 |
| 适合无人值守和多租户运行吗？ | 可以自托管，但必须自行建设隔离、权限、凭据和审计体系 |

一句话概括：

> 如果目标是让程序驱动 Claude Code 式 Agent 在项目中自主开发，Agent SDK 是合适的接口；如果目标是复刻 Claude Code 的终端或 IDE 界面，则界面和宿主能力仍需自行实现。

---

## 2. 产品定位与相关工具对比

### 2.1 Claude Agent SDK

适合希望复用完整 Agent loop、但需要自行构建产品界面的应用。

它提供：

- Claude Code agent loop；
- 文件读取、搜索、创建和编辑；
- Shell 命令执行；
- 工具权限与审批回调；
- 多轮会话、恢复和分叉；
- Skills、Slash commands、Subagents、Hooks、MCP 和 Plugins；
- 流式消息、工具事件、费用和 token 使用量；
- Structured output 和文件 checkpoint。

应用仍需负责：

- HTTP、WebSocket、桌面或其他交互界面；
- 用户身份和权限；
- 任务编排与业务状态；
- 运行环境、容器和网络；
- 凭据管理；
- 审计、监控、重试和数据保留。

### 2.2 Claude Code CLI

适合人在终端中直接进行交互式开发。它提供完整终端 UI、快捷键、交互式命令、权限确认和部分只适用于交互会话的能力。

### 2.3 Anthropic Client SDK

即直接调用 Messages API 的 Python 或 TypeScript SDK。它适合需要完全自行定义 Agent loop 和工具执行逻辑的应用。

使用 Client SDK 时，调用方通常需要自己实现：

```text
发送消息
→ 识别 tool_use
→ 执行工具
→ 返回 tool_result
→ 继续调用模型
→ 判断停止条件
```

Agent SDK 已经提供了这套循环以及 Claude Code 的工具系统。

### 2.4 Tool Runner

Tool Runner 适合已经拥有一组业务工具、希望由官方客户端帮助执行工具循环的应用。它仍以调用方定义的工具为中心，不等于完整 Claude Code harness。

### 2.5 Managed Agents

Managed Agents 是另一种产品形态：由 Anthropic 托管 Agent 和 sandbox。Agent SDK 则运行在开发者自己的基础设施上。

### 2.6 对比表

| 维度 | Agent SDK | Claude Code CLI | Client SDK | Managed Agents |
| --- | --- | --- | --- | --- |
| Agent loop | 内置 Claude Code loop | 内置 | 自行实现 | 托管提供 |
| Claude Code 内置工具 | 有 | 有 | 无 | 取决于产品能力 |
| 运行位置 | 自有进程和基础设施 | 用户本机或开发环境 | 自有应用 | Anthropic 托管 |
| 终端 UI | 无 | 有 | 无 | 无 Claude Code CLI UI |
| 多轮会话 | 有 | 有 | 自行实现 | 有 |
| Sandbox | 自行部署和配置 | 本地配置 | 自行实现 | 托管 |
| 适合嵌入产品 | 是 | 主要面向人 | 是 | 是 |

---

## 3. 运行时：自带 binary 与系统 CLI

这是最容易产生误解的部分。

### 3.1 SDK 实际会启动 `claude` 子进程

调用 `query()` 或创建 `ClaudeSDKClient` 时，Python SDK 会启动一个 Claude Code 子进程，并通过 stdio 与其交换结构化消息。

一个活动会话通常对应：

```text
一个 Python 侧会话
+ 一个 claude 子进程
+ 该进程启动的工具进程树
+ 一个工作目录
+ 一组本地 session transcript
```

因此，Agent SDK 不是无状态 HTTP 包装器。并发运行 N 个会话，通常意味着运行 N 个 Claude Code 子进程。

### 3.2 默认使用哪一个 binary？

Python SDK 的常见安装方式是：

```bash
pip install claude-agent-sdk
```

官方 Python wheel 通常捆绑 native Claude Code binary。Executable 的查找优先级是：

```text
显式 ClaudeAgentOptions.cli_path
→ SDK bundled binary
→ PATH 中的 claude
→ 常见安装路径
```

因此，未设置 `cli_path` 的常规安装会优先使用包内 runtime：

- 不要求机器预先安装独立的 `claude`；
- SDK 版本决定捆绑的 Claude Code runtime 版本；
- 升级系统 CLI 不会自动升级 SDK 捆绑的 runtime。

少数安装没有 bundled binary，例如某个平台只能安装 source distribution。此时 SDK 才继续从 `PATH` 和常见安装路径查找独立安装的 `claude`。

也可以显式指定 executable：

```python
from claude_agent_sdk import ClaudeAgentOptions

options = ClaudeAgentOptions(
    cli_path="/usr/local/bin/claude",
)
```

显式指定适合以下场景：

- 需要让 SDK 与人工 CLI 使用完全相同的 runtime 版本；
- 使用经过组织审核的固定 binary；
- 使用特殊安装路径；
- 当前 SDK 安装没有 bundled binary；
- 需要验证某个 Claude Code 版本的兼容性。

### 3.3 Bundled binary 与系统 CLI 有什么区别？

核心能力来自 Claude Code runtime，因此两者的主要区别是**版本和来源**，不是两套不同的 Agent。

| 维度 | SDK bundled binary | 系统安装的 CLI |
| --- | --- | --- |
| 安装来源 | Python 包携带 | 用户单独安装 |
| 默认升级方式 | 升级 `claude-agent-sdk` | 升级 Claude Code CLI |
| 版本是否可能不同 | 是 | 是 |
| SDK 默认是否使用 | 通常是 | 仅无 bundled binary、显式指定或 fallback 时 |
| 配置目录 | 默认仍是当前用户的 `~/.claude/` | 默认是当前用户的 `~/.claude/` |
| 环境变量 | 继承 Python 父进程环境 | 继承启动 CLI 的 Shell 环境 |
| 工作目录 | `ClaudeAgentOptions.cwd` | 启动 CLI 时的目录 |

推荐在生产环境中固定 SDK 版本，并记录启动时的 SDK 与 Claude Code runtime 版本。不要把系统 CLI 和 SDK 捆绑 runtime 当作必然同步。

### 3.4 Binary 位置不决定配置位置

即使 SDK 使用包内 bundled binary，它默认仍以当前操作系统用户身份运行，也仍然使用该用户的 Claude 配置目录。

换句话说：

```text
使用哪个 claude executable
```

和：

```text
读取哪个 ~/.claude 配置目录
```

是两件事。

默认情况下，bundled binary 仍可能读取：

```text
~/.claude/settings.json
~/.claude/CLAUDE.md
~/.claude/rules/
~/.claude/skills/
~/.claude/agents/
~/.claude.json
~/.claude/projects/
```

是否加载 user、project 和 local settings，主要由 `setting_sources` 控制，而不是由 binary 来自 SDK 还是系统安装决定。

### 3.5 如何使用独立配置目录？

通过环境变量指定：

```python
options = ClaudeAgentOptions(
    env={
        "CLAUDE_CONFIG_DIR": "/srv/agents/config/tenant-a",
    },
)
```

这样可以将全局配置、cache、session transcript 等从默认 `~/.claude/` 移到独立目录。

需要特别注意：`CLAUDE_CONFIG_DIR` 不等于认证隔离。尤其在 macOS 上，Claude Code 的登录凭据保存在系统 Keychain，而不是该目录中；同一 OS 用户下的多个配置目录仍可能共享登录身份。

典型用途：

- 测试一个干净的 SDK 环境；
- 隔离不同租户；
- 隔离不同运行节点；
- 避免生产 Agent 读取开发者个人配置；
- 固定受控的 Plugins、MCP 和配置版本。

需要注意：`CLAUDE_CONFIG_DIR` 只是配置目录隔离的一部分，不是完整的文件系统或进程安全边界。

---

## 4. 环境变量、API key 与现有 CLI 配置

### 4.1 Python SDK 默认继承父进程环境

Python SDK 创建 `claude` 子进程时，会继承启动 Python 应用的环境变量，再将 `ClaudeAgentOptions.env` 中的值覆盖到子进程环境。

概念上相当于：

```python
process_env = {
    **os.environ,
    **options.env,
}
```

因此，如果在同一个 Shell 中已经配置：

```bash
export ANTHROPIC_API_KEY=...
export ANTHROPIC_BASE_URL=...
export ANTHROPIC_AUTH_TOKEN=...
```

然后从这个 Shell 启动 Python 程序：

```bash
python agent.py
```

SDK 启动的 bundled Claude Code runtime 会继承这些变量，一般不需要再次配置。

这与 binary 是否 bundled 无关。环境变量属于进程环境，而不是某个 executable 的私有配置。

### 4.2 哪些情况下不会自动继承？

以下情况下需要重新注入配置：

- Python 服务由 systemd、Docker、Kubernetes、IDE、任务队列或进程管理器启动，而不是从已配置的 Shell 启动；
- API key 只写在某个 `.env` 中，但应用没有加载它；
- API key 只存在于另一个终端窗口；
- 应用启动后才在外部 Shell 修改变量；
- 使用不同系统用户运行服务；
- 使用独立容器或远程执行节点；
- 显式传入了覆盖原值的 `options.env`；
- 凭据实际由交互式登录、系统 keychain 或组织登录流程提供，而不是环境变量。

SDK 不会自动加载 `.env`。如果配置保存在 `.env` 中，应由应用按自己的配置机制加载，再传入进程环境。

### 4.3 建议的生产方式

不要依赖开发者终端里的临时 `export`。生产应用应从 secret manager 或受控配置注入：

```python
options = ClaudeAgentOptions(
    env={
        "ANTHROPIC_BASE_URL": gateway_url,
        "ANTHROPIC_AUTH_TOKEN": gateway_token,
        "CLAUDE_CONFIG_DIR": config_dir,
    },
)
```

不要把真实 key 写入源码、日志、session prompt、可提交的 settings 文件或 `.env.example`。

### 4.4 能否复用 CLI 已经保存的登录状态？

SDK runtime 和独立 CLI 默认使用同一用户配置目录，因此在技术上可能看到已有的本地认证状态。

但第三方产品和生产服务不应把个人 `claude.ai` 登录作为产品用户的推理额度来源。官方要求第三方产品使用文档化的 API key 或云提供商认证方式，除非另有批准。

因此应区分：

- 本机个人实验：可以验证已有登录状态是否可用；
- 服务端产品：应显式配置服务端 API 或云提供商认证；
- 多租户系统：应隔离配置和凭据，不共享开发者个人登录目录；在 macOS 上还要考虑系统 Keychain 不随 `CLAUDE_CONFIG_DIR` 隔离。

多租户服务应优先使用显式的服务端凭据或凭据代理，并结合独立 OS 身份、容器或更强隔离环境，而不是依赖本机已保存的登录状态。

---

## 5. 安装与认证

### 5.1 安装要求

Python SDK 要求 Python 3.10 或更高版本：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install claude-agent-sdk
```

或者：

```bash
uv add claude-agent-sdk
```

### 5.2 Anthropic API

最直接的方式是：

```bash
export ANTHROPIC_API_KEY="..."
```

### 5.3 官方支持的其他推理渠道

Agent SDK 复用 Claude Code 的供应商配置，支持的主要渠道包括：

| 渠道 | 典型开关或认证 |
| --- | --- |
| Anthropic API | `ANTHROPIC_API_KEY` |
| Amazon Bedrock | `CLAUDE_CODE_USE_BEDROCK=1` 和 AWS 凭据 |
| Claude Platform on AWS | `CLAUDE_CODE_USE_ANTHROPIC_AWS=1` 等 |
| Google Cloud’s Agent Platform | `CLAUDE_CODE_USE_VERTEX=1` 和 GCP 凭据 |
| Microsoft Foundry | `CLAUDE_CODE_USE_FOUNDRY=1` 和 Azure 凭据 |
| Anthropic-format LLM gateway | `ANTHROPIC_BASE_URL` 加 gateway credential |

不同提供方支持的 Web search、Fast mode、Auto mode、Remote Control 等附加能力可能不同。核心本地能力，如 Agent SDK、CLI、Skills、Subagents、Hooks、Plugins、MCP 和 sandbox，通常仍可使用。

### 5.4 自定义 LLM gateway

自定义 gateway 可通过：

```text
ANTHROPIC_BASE_URL
ANTHROPIC_AUTH_TOKEN
ANTHROPIC_API_KEY
ANTHROPIC_CUSTOM_HEADERS
```

接入。

其中：

- `ANTHROPIC_BASE_URL` 只改变请求发送地址，不自动改变模型；
- `ANTHROPIC_AUTH_TOKEN` 通常产生 Bearer token；
- `ANTHROPIC_API_KEY` 通常通过 `x-api-key` 发送；
- `ANTHROPIC_CUSTOM_HEADERS` 可传租户、路由或审计字段。

Anthropic-format gateway 至少需要兼容：

```text
POST /v1/messages
POST /v1/messages/count_tokens    # 可选但建议
SSE 流式响应
Anthropic Messages tool use
相关 anthropic-version 与 anthropic-beta 字段
```

Gateway 必须正确转发 Claude Code 持续新增的 capability headers 和 body fields。对字段做固定 allowlist 或随意改写请求，可能导致新版本功能失效。

### 5.5 任意 OpenAI-compatible 服务不是直接兼容条件

仅支持 OpenAI Chat Completions 或 Responses API 的服务，不能因为“支持工具调用”就直接作为 Agent SDK 后端。

若要接入，需要 gateway 完成协议转换：

```text
Claude Code 的 Anthropic Messages 请求
→ gateway 转换
→ 其他提供方 API
```

官方不支持通过 gateway 将 Claude Code 路由到非 Claude 模型。即使某个第三方 gateway 技术上可以转换，也需要自行验证：

- tool use；
- 并行工具调用；
- streaming；
- thinking；
- structured output；
- context management；
- prompt caching；
- 错误格式和重试；
- 模型对 Claude Code system prompt 的遵循质量。

因此，非 Claude 模型或仅 OpenAI-compatible 的后端应视为独立兼容性项目，而不是 Agent SDK 的标准配置。

---

## 6. 两种主要 Python 调用方式

### 6.1 `query()`：单次或单向任务

最小示例：

```python
import asyncio

from claude_agent_sdk import query


async def main():
    async for message in query(prompt="分析当前目录中的项目结构"):
        print(message)


asyncio.run(main())
```

`query()` 适合：

- 一次性分析；
- 单个后台任务；
- CI 或队列消费者；
- 无需长时间保持双向连接的任务；
- 只消费完整消息或最终结果的场景。

每次普通 `query()` 默认创建新 session。需要继续指定 session 时，可使用 `resume` 或相应 continuation 选项。

### 6.2 `ClaudeSDKClient`：持续、多轮和可中断会话

```python
import asyncio

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    TextBlock,
)


async def main():
    options = ClaudeAgentOptions(
        cwd="/path/to/project",
        max_turns=30,
    )

    async with ClaudeSDKClient(options) as client:
        await client.query("检查项目并修复当前测试失败")

        async for message in client.receive_response():
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        print(block.text)
            elif isinstance(message, ResultMessage):
                print(message.subtype, message.session_id)


asyncio.run(main())
```

适合：

- 对话窗口；
- 多轮开发任务；
- 运行期间继续发送输入；
- 消息排队；
- 图片输入；
- 中途打断；
- 动态调整 model 或 permission mode；
- 长时间保持一个 Claude Code runtime。

### 6.3 选择建议

| 需求 | 推荐 |
| --- | --- |
| 单次代码分析或修改 | `query()` |
| 后台队列任务 | `query()` |
| 多轮聊天窗口 | `ClaudeSDKClient` |
| 需要中断、补充输入或排队 | `ClaudeSDKClient` |
| 需要持续审批回调 | `ClaudeSDKClient` |
| Stateless serverless 任务 | `query()`，并显式管理 session storage |

---

## 7. Agent loop 与消息生命周期

### 7.1 Agent loop

SDK 内部循环大致如下：

```text
接收 prompt
→ Claude 判断下一步
→ 返回文本和/或请求工具调用
→ SDK 执行工具
→ 工具结果返回 Claude
→ Claude 再次判断
→ 重复直到没有工具调用
→ 返回 ResultMessage
```

调用方不需要手工执行每一次 tool-use 往返。

### 7.2 Turn 的含义

在 Agent SDK 中，一个 turn 通常指一次 Claude 输出、工具执行和工具结果回流的往返，而不是一条用户消息。

```python
ClaudeAgentOptions(max_turns=30)
```

限制的是工具使用循环，不是聊天窗口最多发送 30 条消息。

### 7.3 主要消息类型

| 消息 | 用途 |
| --- | --- |
| `SystemMessage` | 初始化、压缩边界和运行状态 |
| `AssistantMessage` | Claude 文本和工具调用 |
| `UserMessage` | 用户输入和工具结果回流 |
| `StreamEvent` | 开启 partial messages 后的 token/content delta |
| `ResultMessage` | 一次 Agent loop 的最终状态 |

初始化消息可用于检查实际运行环境，例如：

- session metadata；
- 可用工具；
- 已加载 Plugins；
- 已发现 Skills；
- 可派发 Slash commands；
- MCP server 状态。

### 7.4 Result subtype

不能看到 `ResultMessage` 就假定任务成功。应检查 `subtype`：

| Subtype | 含义 |
| --- | --- |
| `success` | Agent 正常完成 |
| `error_max_turns` | 达到 turn 上限 |
| `error_max_budget_usd` | 达到预算上限 |
| `error_during_execution` | API、进程或执行错误 |
| `error_max_structured_output_retries` | 多次无法生成符合 schema 的结果 |

只有成功结果才应读取最终 `result` 文本。错误结果也通常包含 session ID 和部分使用量信息，可用于诊断或恢复。

单次 `query()` 在产生错误 `ResultMessage` 后还可能抛出普通 `Exception`，因此生产代码应同时消费结果并捕获异常。

---

## 8. 对指定目录进行项目开发

### 8.1 使用 `cwd`

```python
options = ClaudeAgentOptions(
    cwd="/path/to/project",
)
```

`cwd` 同时影响：

- `claude` 子进程工作目录；
- Bash 命令默认目录；
- 项目设置发现；
- `CLAUDE.md`、Rules、Skills 和 Agents 的发现；
- session transcript 使用的 project key；
- 相对路径解析。

SDK 可以从任何目录启动，真正的项目根目录由 `cwd` 决定。

### 8.2 推荐的项目开发配置

```python
from claude_agent_sdk import ClaudeAgentOptions

options = ClaudeAgentOptions(
    cwd="/path/to/project",
    setting_sources=["project", "local"],
    system_prompt={
        "type": "preset",
        "preset": "claude_code",
        "append": "遵循当前项目规则，并以实际测试结果作为完成依据。",
    },
    skills="all",
    allowed_tools=[
        "Read",
        "Write",
        "Edit",
        "Glob",
        "Grep",
        "Bash",
        "Skill",
        "Agent",
    ],
    max_turns=50,
    max_budget_usd=10.0,
)
```

这里的数值只是示例，生产值应根据任务类型和成本测试确定。

### 8.3 `cwd` 应放在哪里？

如果项目级 `.claude/settings.json` 位于仓库根目录，最稳妥的是将 `cwd` 设为仓库根目录。

原因是：

- 项目 `settings.json` 和项目 Hooks 只从 `<cwd>/.claude/` 读取，不向父目录回退；
- `CLAUDE.md`、Rules、Skills 和 filesystem Subagents 可以按各自规则向父目录发现；
- 不同功能的查找规则并不完全相同。

对于包含多个子仓库的工作区，可以：

```text
SDK cwd = 工作区根目录
Git 操作 = git -C <子仓库> ...
```

这样既可加载根目录 Agent 配置，也能精确操作每个子仓库。

### 8.4 能力边界

配置合适时，SDK Agent 可以完成：

```text
理解需求
→ 读取项目规则
→ 搜索和分析代码
→ 修改文件
→ 安装依赖
→ 运行测试和构建
→ 启动服务
→ 调用浏览器或 MCP
→ 修复失败
→ 调用 Subagent 审查
→ 汇报结果
```

但 SDK 不会自动提供项目所需的：

- Git；
- Node.js、Python、Java 等运行时；
- 包管理器；
- 数据库和中间件；
- 浏览器和 Playwright；
- Docker；
- 外部 CLI；
- 项目开发 `.env`；
- 第三方账号和凭据。

这些属于执行镜像或宿主环境。

---

## 9. 配置加载：`setting_sources`

### 9.1 默认行为

当前文档中，省略 `setting_sources` 等价于：

```python
setting_sources=["user", "project", "local"]
```

这与 Claude Code CLI 的文件系统配置加载方式接近。

为了让部署行为可预测，生产代码建议显式设置，而不是依赖默认值。

### 9.2 三类来源

| Source | 主要内容 | 位置 |
| --- | --- | --- |
| `user` | 用户 CLAUDE.md、Rules、Skills、Agents、settings | `~/.claude/` |
| `project` | 项目 CLAUDE.md、Rules、Skills、Agents、Hooks、`settings.json` | 以 `cwd` 为起点 |
| `local` | `CLAUDE.local.md`、`.claude/settings.local.json` | `cwd` 和相关父目录规则 |

### 9.3 常见文件的加载行为

| 文件或目录 | 如何加载 |
| --- | --- |
| `<cwd>/.claude/settings.json` | 需要 `project` |
| `<cwd>/.claude/settings.local.json` | 需要 `local` |
| 项目 `CLAUDE.md` | 需要 `project` |
| 项目 `.claude/rules/*.md` | 需要 `project` |
| 项目 `.claude/skills/*/SKILL.md` | 需要 `project` |
| 项目 `.claude/agents/*.md` | 需要 `project` |
| 用户 `~/.claude/settings.json` | 需要 `user` |
| 用户 `~/.claude/skills/` | 需要 `user` |

### 9.4 完全程序化配置

如果不希望读取 user、project 和 local 配置：

```python
options = ClaudeAgentOptions(
    setting_sources=[],
)
```

然后通过 options 显式传入：

- system prompt；
- tools；
- permissions；
- agents；
- hooks；
- MCP；
- plugins。

不过 `setting_sources=[]` 仍不是完整隔离。以下内容可能不完全受它控制：

- Endpoint managed policy；
- Server-managed settings；
- 全局 `~/.claude.json`；
- Auto memory；
- 某些 claude.ai connectors。

多租户环境还应组合：

```python
options = ClaudeAgentOptions(
    cwd=tenant_workspace,
    setting_sources=[],
    env={
        "CLAUDE_CONFIG_DIR": tenant_config_dir,
        "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1",
    },
)
```

并使用独立文件系统、容器和网络策略。

---

## 10. System prompt 与 Claude Code 行为

### 10.1 默认 prompt 不等于完整 CLI prompt

Python SDK 未设置 `system_prompt` 时，默认行为不应直接理解为完整 Claude Code CLI 编码体验。

希望尽量采用 Claude Code 的默认编码指导时，应使用 preset：

```python
system_prompt={
    "type": "preset",
    "preset": "claude_code",
}
```

追加自定义规则：

```python
system_prompt={
    "type": "preset",
    "preset": "claude_code",
    "append": "只修改当前需求直接涉及的文件，并运行相关测试。",
}
```

### 10.2 普通字符串会替换默认 prompt

```python
system_prompt="你是一个 Python 开发者"
```

表示使用自定义 system prompt，而不是在完整 Claude Code preset 后追加一句话。调用方需要自行承担工具规则、行为边界和输出要求是否完整的问题。

### 10.3 文件形式

大 system prompt 可放入受控文件，以避免命令行参数长度和维护问题：

```python
system_prompt={
    "type": "file",
    "path": "/absolute/path/to/system-prompt.md",
}
```

### 10.4 `CLAUDE.md` 与 system prompt 的取舍

- 需要 CLI 和 SDK 共同遵守的项目规则：放在 `CLAUDE.md` 或 Rules；
- 只属于宿主产品的运行约束：通过 `system_prompt.append`；
- 敏感、租户专属或动态内容：由应用注入，不提交到项目；
- 长期规则不要只放在第一条用户消息中，因为 compaction 后可能弱化。

---

## 11. 内置工具与权限

### 11.1 常用内置工具

| 类别 | 工具 |
| --- | --- |
| 文件 | `Read`、`Write`、`Edit` |
| 搜索 | `Glob`、`Grep` |
| 执行 | `Bash` |
| Web | `WebSearch`、`WebFetch` |
| 编排 | `Agent`、`Skill`、任务跟踪工具 |
| 交互 | `AskUserQuestion` |
| 发现 | `ToolSearch` |

不同版本和模型可见的工具可能变化，应从初始化消息核验实际列表。

### 11.2 `tools`、`allowed_tools` 和 `disallowed_tools`

这三个概念不能混用。

| 配置 | 含义 |
| --- | --- |
| `tools` | 控制哪些内置工具对模型可见 |
| `allowed_tools` | 自动批准匹配调用，不是白名单 |
| `disallowed_tools` | 移除工具或永久拒绝匹配调用 |

例如：

```python
allowed_tools=["Read"]
```

只表示 Read 自动批准。其他工具可能仍可见，并继续进入 permission mode 或审批回调。

严格只读的 headless Agent 可使用：

```python
options = ClaudeAgentOptions(
    tools=["Read", "Glob", "Grep"],
    allowed_tools=["Read", "Glob", "Grep"],
    permission_mode="dontAsk",
)
```

### 11.3 权限求值顺序

当前官方规则可概括为：

```text
Hooks
→ deny rules
→ ask rules
→ permission mode
→ allow rules
→ can_use_tool callback
```

因此：

- deny 在 `bypassPermissions` 下仍生效；
- ask 在 `bypassPermissions` 下仍会进入审批；
- 自动批准的调用不会到达 `can_use_tool`；
- 必须审查每一次调用的规则应放在 `PreToolUse` hook，而不是只放在 `can_use_tool`。

### 11.4 Permission modes

| Mode | 行为 | 常见用途 |
| --- | --- | --- |
| `default` | 未决工具进入审批 callback；无 callback 时通常拒绝 | 交互式应用 |
| `dontAsk` | 不询问；预批准外全部拒绝 | 严格 headless Agent |
| `acceptEdits` | 自动批准工作区内编辑和部分文件操作 | 隔离环境中的开发任务 |
| `plan` | 只读探索和规划，写入需审批 | 代码审查、方案设计 |
| `auto` | 由模型分类器参与审批 | 受控自动化 |
| `bypassPermissions` | 几乎全部自动执行，ask/deny/hook 仍优先 | 仅隔离环境 |

### 11.5 `bypassPermissions` 不是 allowlist

下面的组合仍然可能允许所有工具：

```python
ClaudeAgentOptions(
    allowed_tools=["Read"],
    permission_mode="bypassPermissions",
)
```

原因是：

```text
Read 命中 allow
其他工具未命中 allow
→ 落入 bypassPermissions
→ 仍被批准
```

需要固定工具面时，使用 `tools`、`disallowed_tools` 和 `dontAsk`，并在高风险场景增加 Hooks 与操作系统隔离。

### 11.6 人工审批和 `AskUserQuestion`

交互式 CLI 自带确认界面，SDK 不提供现成 UI。宿主应用需要通过 `can_use_tool` 处理：

- 工具审批；
- `AskUserQuestion`；
- 组织要求确认的 connector；
- 标记为 `requiresUserInteraction` 的 MCP 工具。

宿主应用还需处理：

- 审批人的身份；
- 超时；
- 取消；
- 断线重连；
- 审计；
- 并发审批去重。

---

## 12. Streaming input 与 streaming output

### 12.1 两者不是一回事

- Streaming input：会话持续接收用户消息；
- Streaming output：应用实时收到模型输出增量。

### 12.2 Streaming input

适合：

- 多轮聊天；
- 任务运行中追加信息；
- 输入排队；
- 图片；
- 中断当前响应；
- 长连接应用。

Python 中通常优先使用 `ClaudeSDKClient`，而不是依赖很快结束的有限 async generator。权限审批尚未完成时，输入 generator 提前结束可能造成会话无法继续。

### 12.3 Streaming output

开启 partial messages：

```python
options = ClaudeAgentOptions(
    include_partial_messages=True,
)
```

之后可以收到 `StreamEvent`，包括文本 delta 和工具参数 delta。

需要注意：

- 完整 `AssistantMessage` 仍是稳定的业务处理边界；
- token delta 主要用于 UI；
- Subagent 的每个 token 增量不一定转发给主会话；
- Structured output 通常只在最终结果中提供，不作为可直接消费的 JSON delta。

---

## 13. Sessions、恢复与上下文

### 13.1 Session ID

从 `ResultMessage.session_id` 获取 session ID，并存入业务数据库，而不是只保存在进程内存中。

### 13.2 Resume

```python
options = ClaudeAgentOptions(
    resume=session_id,
)
```

恢复会话会恢复对话历史、工具调用和结果上下文。

### 13.3 Fork

Fork 用于从现有会话历史创建不同分支。它分叉的是会话上下文，不是文件系统。

### 13.4 Transcript 不等于文件快照

Session 保存：

- 对话；
- 工具调用；
- 工具结果；
- 上下文信息。

Session 不自动保存或回滚整个工作目录。因此：

```text
恢复旧 session
≠
恢复旧代码状态
```

代码状态仍需依赖 Git、独立工作区、volume snapshot 或 file checkpoint。

### 13.5 Context compaction

会话接近上下文上限时会自动压缩旧历史，并产生 compact boundary 事件。

建议：

- 长期规则放进 `CLAUDE.md`；
- 大型子任务交给 Subagent；
- 避免无必要的大文件和超长命令输出；
- 记录关键状态到代码、Git 或权威文档；
- 不将超长会话当作唯一的业务状态存储。

### 13.6 SessionStore

SessionStore 可将 transcript 镜像到 S3、Redis、Postgres 或自定义后端，以便跨容器恢复。

它只处理 transcript，不自动持久化：

- 项目工作区；
- `CLAUDE.md` memory 文件；
- file checkpoint；
- 外部服务状态。

SessionStore 是本地 transcript 的 mirror，不应被理解为完整 Agent 状态数据库。应自行实现租户隔离、加密、保留和删除策略。

使用 SessionStore 跨主机恢复时，恢复端应使用与原会话匹配的 `cwd`，因为 store 的 project key 由工作目录派生。工作区文件、memory 和 checkpoint 仍需单独持久化。

`session_store` 与 `enable_file_checkpointing=True` 不能在同一个 session 中组合。Checkpoint 依赖没有进入 SessionStore 的本地文件备份，SDK 会拒绝这一配置；需要跨主机恢复文件时，应使用 Git、工作区快照或独立的文件持久化方案。

---

## 14. 文件 checkpoint

启用：

```python
options = ClaudeAgentOptions(
    enable_file_checkpointing=True,
    extra_args={"replay-user-messages": None},
)
```

然后可从用户消息 UUID 获取 checkpoint，并调用：

```python
await client.rewind_files(checkpoint_id)
```

Checkpoint 只追踪内置 `Write`、`Edit` 和 `NotebookEdit` 的修改。

它不可靠覆盖：

- `Bash` 中的 `sed -i`、重定向或脚本写入；
- 大部分 Subagent 修改；
- 目录移动和完整文件系统状态；
- 远程文件；
- 数据库和外部 API 副作用。

因此 checkpoint 是便捷撤销能力，不是 Git、容器快照或事务系统的替代品。

---

## 15. Skills 与 Slash commands

### 15.1 Skills 的发现

项目 Skill 位于：

```text
.claude/skills/<name>/SKILL.md
```

启用 project source 后，SDK 会发现这些 Skills。可使用：

```python
skills="all"
```

或：

```python
skills=["review", "deploy"]
```

传入 `[]` 可禁用全部 Skills。

### 15.2 Skills 必须是文件系统工件

Python SDK 没有“传一个字符串就注册 Skill”的普通 API。需要动态能力时可选择：

- 生成受控的 Skill 文件；
- 使用 programmatic AgentDefinition；
- 使用 custom MCP tool；
- 将动态规则加入 system prompt。

### 15.3 显式调用 Skill

User-invocable Skill 可作为 prompt 发送：

```python
await client.query("/review src/auth")
```

`disable-model-invocation: true` 表示 Claude 不会自主调用，但用户或上层程序仍可显式发送 `/name`。

### 15.4 SDK 中的 `allowed-tools` 差异

当前 Agent SDK Skills 文档明确说明：`SKILL.md` frontmatter 中的 `allowed-tools` 不应用于 SDK 权限控制。SDK 应通过主查询的 `allowed_tools`、`tools`、`disallowed_tools`、permission mode 和 Hooks 管理权限。

因此，将 CLI Skill 迁移到 SDK 时必须检查：

```yaml
allowed-tools: ...
```

是否承载了关键授权。如果有，应将其转成 session options 或确定性的权限策略。

同时要注意：`allowed-tools` 即使在直接 CLI 中也主要表示临时预批准，而不是限制其他工具的白名单。

### 15.5 Slash commands

只有不依赖交互式终端的命令才能通过 SDK 派发。初始化消息中的：

```text
slash_commands
```

才是当前 session 的实际可用列表。

常见可用命令包括：

- `/compact`；
- `/clear`；
- 项目自定义 commands；
- User-invocable Skills。

不要假定 CLI 中所有命令都能通过 SDK 使用。特别是登录、插件管理、交互式 picker 和 UI 操作，应通过 options 或宿主应用完成。

---

## 16. Subagents

### 16.1 定义方式

SDK 支持：

1. `agents={...}` 程序化定义；
2. `.claude/agents/*.md` 文件定义；
3. 内置 `general-purpose` 等 Agent。

程序化定义示例：

```python
from claude_agent_sdk import AgentDefinition, ClaudeAgentOptions

agents = {
    "reviewer": AgentDefinition(
        description="只读审查代码正确性和安全风险",
        prompt="基于代码和测试证据审查，不修改文件。",
        tools=["Read", "Glob", "Grep"],
        model="sonnet",
    )
}

options = ClaudeAgentOptions(
    agents=agents,
    allowed_tools=["Read", "Glob", "Grep", "Agent"],
)
```

### 16.2 Subagent 的上下文

Subagent 获得：

- 自己的 system prompt；
- Agent tool 传入的任务 prompt；
- 项目 `CLAUDE.md`；
- 为它配置的工具和部分项目上下文。

Subagent 不自动获得：

- 父 Agent 的完整对话历史；
- 父 Agent 所有工具结果；
- 父 Agent 已经加载的全部 Skill 内容。

因此，父 Agent 应在委派 prompt 中提供必要路径、错误、约束和完成标准。

### 16.3 普通 Subagents 与 Agent Teams

| 能力 | Subagents | Agent Teams |
| --- | --- | --- |
| SDK 支持 | 支持 | 不直接支持 |
| 上下文 | 独立、短任务 | 多个独立 teammate session |
| 结果 | 返回父 Agent | 共享任务与直接通信 |
| 适用 | 分析、实现、审查子任务 | 交互式大型团队协作 |

Agent Teams 需要交互式 Claude Code session，不应作为 Agent SDK 的可用能力设计。

### 16.4 并发、深度和成本

Subagent 会独立发起模型请求。应限制：

- 最大嵌套深度；
- 最大并发数；
- 整个 query 的预算；
- 每个 AgentDefinition 的 `maxTurns`。

Subagent 花费会计入整体 query 的费用。

---

## 17. Hooks

### 17.1 两类 Hooks

SDK 可以同时使用：

- settings 文件中的 filesystem Hooks；
- `ClaudeAgentOptions.hooks` 中的 Python callback Hooks。

Filesystem Hooks 适合 CLI 与 SDK 共享规则；Python Hooks 适合宿主应用的动态策略和业务集成。

### 17.2 常用事件

Python SDK 支持的主要事件包括：

- `PreToolUse`；
- `PostToolUse`；
- `PostToolUseFailure`；
- `UserPromptSubmit`；
- `Stop`；
- `SubagentStart`；
- `SubagentStop`；
- `PreCompact`；
- `PermissionRequest`；
- `Notification`。

Python 与 TypeScript 的事件支持并非完全一致。部分生命周期事件可在 TypeScript callback 中使用，而 Python 需要通过 filesystem Hooks 或应用外围处理。

### 17.3 `PreToolUse` 是强制策略入口

权限 callback 只处理前序规则尚未决定的调用。若要求每一次 Bash、发布、删除或外部 API 调用都经过策略检查，应使用 `PreToolUse`。

典型用途：

- 拒绝破坏性命令；
- 限制工作目录；
- 阻止读取秘密；
- 拦截 push、发布、部署；
- 修改工具输入；
- 记录审计日志。

Hooks 不是 OS sandbox。Hook 规则写错、遗漏工具或被宿主环境绕过时，仍需操作系统隔离兜底。

---

## 18. MCP 与自定义工具

### 18.1 MCP server 类型

SDK 可接入：

- stdio MCP；
- HTTP MCP；
- SSE MCP；
- Python 进程内 SDK MCP server；
- 项目 `.mcp.json` 中的 MCP。

工具名通常是：

```text
mcp__<server>__<tool>
```

### 18.2 Python 进程内工具

```python
from claude_agent_sdk import create_sdk_mcp_server, tool


@tool("lookup_order", "查询订单状态", {"order_id": str})
async def lookup_order(args):
    return {
        "content": [
            {
                "type": "text",
                "text": f"订单 {args['order_id']} 正常",
            }
        ]
    }


server = create_sdk_mcp_server(
    name="orders",
    tools=[lookup_order],
)
```

配置：

```python
options = ClaudeAgentOptions(
    mcp_servers={"orders": server},
    allowed_tools=["mcp__orders__lookup_order"],
)
```

### 18.3 MCP OAuth

SDK 不会为远程 MCP 自动打开完整业务授权流程。宿主应用需要：

- 发起 OAuth；
- 保存和刷新 token；
- 将 token 放入 MCP transport headers；
- 将用户身份与 MCP 权限绑定；
- 审计工具调用。

### 18.4 `strict_mcp_config`

多租户或强控制场景应考虑只允许程序显式传入的 MCP server，避免自动拾取用户、项目、Plugin 或 claude.ai connector。

具体字段和行为应按当前 Python API reference 核对，因为 MCP 配置能力迭代较快。

### 18.5 Tool Search

大量 MCP 工具会显著消耗上下文并降低模型选工具质量。Tool Search 可以按需发现和加载工具 schema。

它是上下文和规模优化，不是权限机制。找到的工具仍须经过权限、Hooks 和外部授权。

---

## 19. Plugins

### 19.1 SDK 的确定性加载方式

Agent SDK 通过本地路径加载 Plugin：

```python
options = ClaudeAgentOptions(
    plugins=[
        {
            "type": "local",
            "path": "/absolute/path/to/plugin-root",
        }
    ],
)
```

当前 SDK 只接受本地路径类型。Marketplace 或远程仓库中的 Plugin 需要先下载或安装到本地。

Plugin 可以包含：

- Skills；
- Agents；
- Hooks；
- MCP servers；
- Commands。

### 19.2 已安装 CLI Plugin 如何复用？

可以找到 CLI 的本地安装目录，再显式传给 SDK。不要只假设“CLI 已安装”就代表 SDK session 一定加载。

推荐启动流程：

```text
确认 Plugin 已安装到受控路径
→ 在 options.plugins 中显式传入
→ 读取 SystemMessage(init)
→ 核验 plugins、skills、slash_commands 和 tools
→ 缺失则终止本次任务
```

### 19.3 `enabledPlugins` 的边界

`settings.json` 中的 `enabledPlugins` 表示已知 Plugin 的启用状态，不负责：

- 下载 Plugin；
- 安装 Marketplace；
- 修复不存在的路径；
- 安装 Plugin 依赖；
- 保证 SDK 已加载该 Plugin。

为了可移植和可审计，SDK 应显式传本地 Plugin 路径，并核验初始化消息。

### 19.4 不需要 `/reload-plugin`

SDK 应通过“创建 session 时显式加载并检查”替代交互式 CLI 中的 reload 操作。Plugin 配置变化后，重建 session 通常比依赖交互式 reload 命令更可控。

---

## 20. Structured output

配置 JSON Schema：

```python
schema = {
    "type": "object",
    "properties": {
        "status": {
            "type": "string",
            "enum": ["completed", "blocked"],
        },
        "summary": {"type": "string"},
    },
    "required": ["status", "summary"],
    "additionalProperties": False,
}

options = ClaudeAgentOptions(
    output_format={
        "type": "json_schema",
        "schema": schema,
    }
)
```

最终从 `ResultMessage.structured_output` 读取。

注意：

- Structured output 约束最终结果，不会取消中间工具调用；
- 结果通常只在最终消息中提供；
- 即使 subtype 为 success，也应检查字段是否存在；
- 应用仍应使用 Pydantic 等再次验证；
- JSON Schema 不能替代授权、数据库约束和输入安全校验；
- 多次验证失败会产生 `error_max_structured_output_retries`。

适合：

- 工作流路由；
- 状态判断；
- 工单或任务输出；
- 确定性后处理；
- 数据抽取。

不适合把整个开发过程强行塞进单个巨大 JSON。

---

## 21. 成本、模型和运行限制

### 21.1 模型

通过：

```python
ClaudeAgentOptions(model="claude-sonnet-5")
```

或提供方对应 deployment ID 指定模型。

生产环境建议显式指定模型和 fallback，避免账号默认值变化导致行为或成本漂移。

### 21.2 Effort 与 thinking

`effort` 控制模型投入的推理强度；extended thinking 是另一项能力。两者不是同一个设置，也都不是严格预算边界。

### 21.3 Turn 和预算限制

至少考虑：

```python
ClaudeAgentOptions(
    max_turns=50,
    max_budget_usd=10.0,
)
```

预算会覆盖 Subagent 消耗。达到限制后，任务不是成功完成，而是返回相应错误 subtype。

### 21.4 没有默认顶层 wall-clock timeout

Agent session 可能长时间运行。`max_turns` 不能完全替代 wall-clock timeout，因为单个工具或外部服务也可能挂起。

宿主系统还需要：

- 任务 deadline；
- 子进程终止；
- 工具 timeout；
- MCP timeout；
- 卡死检测；
- 取消和清理；
- 幂等恢复。

### 21.5 资源估算

官方 Hosting 文档给出的初始估算约为每 Agent：

```text
1 GiB RAM
5 GiB disk
1 CPU
```

这只是起点。长会话、较大工具输出、MCP 和并发 Subagents 会继续增加资源占用。

---

## 22. 自托管与多租户安全

### 22.1 内置权限不是完整安全边界

Agent 可以动态生成命令，也可能受到项目文件、网页或用户输入中的 prompt injection 影响。

完整安全需要纵深防御：

```text
工具权限
+ PreToolUse Hooks
+ 独立工作目录
+ 容器、gVisor 或 microVM
+ 网络 egress 控制
+ 凭据代理
+ 资源限制
+ 审计和告警
```

### 22.2 每租户独立运行边界

至少保证：

- 独立 `cwd`；
- 独立 `CLAUDE_CONFIG_DIR`；
- 禁用跨租户 auto memory；
- 独立 transcript 和 SessionStore namespace；
- 独立文件系统权限；
- 独立或严格隔离的容器；
- 独立网络与凭据策略。

`CLAUDE_CONFIG_DIR` 可以隔离 `.claude.json`、transcript、cache 和部分文件式配置，但不能单独作为认证边界。尤其在 macOS 上，登录凭据位于系统 Keychain。多租户服务应使用显式服务端凭据或凭据代理，并结合独立 OS 身份或隔离运行环境。

### 22.3 不要直接暴露凭据

推荐模式：

```text
Agent 容器不持有长期密钥
→ 请求发往容器外代理
→ 代理检查目标与权限
→ 代理注入短期凭据
→ 记录审计
```

这适用于模型 API，也适用于 Git、云平台、包仓库和内部服务。

### 22.4 网络控制

仅有 hostname allowlist 不能覆盖所有攻击方式。高安全场景应使用：

- 无默认外网；
- egress proxy；
- TLS termination 和内容策略；
- 域名与方法 allowlist；
- 请求体大小和速率限制；
- 凭据注入；
- 完整审计。

### 22.5 高风险操作必须确定性授权

以下动作不应只依赖另一个模型判断：

- 删除重要数据；
- Push、发布和生产部署；
- 付款；
- 权限或账号变更；
- 发送外部消息；
- 读取或导出秘密；
- 不可逆迁移；
- 高额资源消费。

应通过确定性服务端策略和必要的人工审批控制。

---

## 23. Agent SDK、CLI 与 IDE 集成对比

### 23.1 三者的关系

```text
Agent SDK：程序化表面
CLI：终端交互表面
VS Code / Cursor：图形化 IDE 扩展表面
JetBrains：以 CLI 终端为主、附加 IDE 上下文和诊断集成
```

四种表面都可使用 Claude Code runtime 的核心 Agent 能力，但宿主 UI 和附加能力不同。

### 23.2 能力矩阵

| 维度 | Python Agent SDK | Claude Code CLI | VS Code / Cursor 扩展 | JetBrains 插件 |
| --- | --- | --- | --- | --- |
| Agent loop | 有 | 有 | 有 | 有 |
| 指定工作目录 | `cwd` | 启动目录 | IDE workspace | IDE project / CLI 启动目录 |
| 文件读写和 Bash | 有 | 有 | 有 | 有 |
| Skills | 有 | 最完整 | 有，命令 UI 可能是子集 | 由 CLI 提供 |
| Filesystem Subagents | 有 | 有 | 有 | 由 CLI 提供 |
| Hooks | 有 | 有 | 有 | 由 CLI 提供 |
| MCP | 有 | 有 | 部分图形管理 | 由 CLI 管理 |
| Plugins | 本地路径显式加载 | Marketplace 和命令管理 | 图形化安装和管理 | 由 CLI 管理 |
| 权限审批 UI | 自行实现 | 终端内置 | 扩展对话框 | 主要在 CLI 终端中完成 |
| Session UI | 自行实现 | 终端选择器 | 会话历史面板 | 主要使用 CLI 会话界面 |
| 原生 diff review | 自行实现 | 可连接 IDE | 原生 side-by-side diff | IDE diff viewer |
| 当前选中代码 | 不自动拥有 | 连接 IDE 后可用 | 自动集成 | 自动集成 |
| IDE diagnostics | 不自动拥有 | 连接 IDE MCP 后可用 | Problems diagnostics | IDE inspections / diagnostics |
| Plan 审阅界面 | 自行实现 | 终端 | 原生 Markdown 审阅 | 主要使用 CLI 终端流程 |
| `!` Bash 快捷键 | 不需要，直接用工具 | 有 | 无 | 由 CLI 提供 |
| 完整交互式 commands | 仅可派发子集 | 最完整 | 子集 | 由 CLI 提供 |
| Agent Teams | 不直接支持 | 交互模式支持 | 依赖交互式 runtime | 依赖交互式 CLI runtime |
| Remote Control | 不提供 | 支持，受认证条件限制 | 支持 | 不应假定提供 IDE 入口 |
| Checkpoint | API 支持 | 支持 | UI 支持 | 由 CLI 能力和 IDE 集成决定 |
| 嵌入自有产品 | 最合适 | 不适合作为稳定 UI 协议 | 面向人工 IDE 使用 | 面向人工 IDE 使用 |

### 23.3 SDK 主要缺少什么？

主要缺少的是产品界面和交互式专属能力：

- 终端 UI；
- IDE Chat panel；
- 原生 diff 审批；
- 编辑器 selection；
- Problems diagnostics；
- Plugin Marketplace UI；
- 完整命令菜单；
- 会话列表 UI；
- Plan review UI；
- Remote Control；
- Agent Teams。

它并不明显缺少自主开发所需的核心部分：

- Agent loop；
- 文件工具；
- Bash；
- Skills；
- Hooks；
- MCP；
- 普通 Subagents；
- 多轮会话；
- Structured messages；
- 权限 callback；
- Usage 和成本数据。

---

## 24. 推荐的最小项目开发模板

下面的示例强调配置关系，不是完整生产框架：

```python
import asyncio
import os

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    SystemMessage,
    TextBlock,
)


async def run_project_agent(project_dir: str) -> None:
    options = ClaudeAgentOptions(
        cwd=project_dir,
        setting_sources=["project", "local"],
        system_prompt={
            "type": "preset",
            "preset": "claude_code",
            "append": "遵循项目规则，以实际验证结果判断任务是否完成。",
        },
        skills="all",
        allowed_tools=[
            "Read",
            "Write",
            "Edit",
            "Glob",
            "Grep",
            "Bash",
            "Skill",
            "Agent",
        ],
        permission_mode="default",
        max_turns=50,
        max_budget_usd=10.0,
        env={
            "CLAUDE_CONFIG_DIR": os.path.join(
                project_dir,
                ".agent-runtime",
                "claude-config",
            ),
        },
    )

    async with ClaudeSDKClient(options) as client:
        await client.query("检查当前项目，修复失败测试，并运行相关验证。")

        async for message in client.receive_response():
            if isinstance(message, SystemMessage) and message.subtype == "init":
                print("skills:", message.data.get("skills"))
                print("plugins:", message.data.get("plugins"))

            elif isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        print(block.text)

            elif isinstance(message, ResultMessage):
                print("status:", message.subtype)
                print("session:", message.session_id)
                print("cost:", message.total_cost_usd)


asyncio.run(run_project_agent("/path/to/project"))
```

生产实现还应加入：

- `can_use_tool`；
- `PreToolUse`；
- timeout 和取消；
- transcript 持久化；
- session 与用户绑定；
- Plugin 和 Skill 启动核验；
- 容器隔离；
- network egress；
- secret manager；
- OTEL；
- 错误分类和幂等恢复。

---

## 25. 常见误区

### 误区 1：SDK 是普通聊天 SDK

错误。它会启动 Claude Code runtime，并真实操作文件和运行命令。

### 误区 2：SDK 是 PTY 自动化

错误。SDK 通过结构化 stdio 协议控制 runtime，不需要解析 ANSI 屏幕和模拟按键。

### 误区 3：使用 bundled binary 就不会读取 `~/.claude/`

错误。Binary 来源和配置目录相互独立。默认仍可能读取当前用户配置。

### 误区 4：CLI 已配置环境变量，任何服务都会自动继承

错误。只有作为该环境子进程启动的 Python 程序才能继承。容器、systemd、IDE 和队列 worker 需要单独注入。

### 误区 5：`allowed_tools` 是白名单

错误。它表示自动批准。严格限制需要 `tools`、`disallowed_tools`、`dontAsk` 和 Hooks。

### 误区 6：`bypassPermissions` 加 allowlist 就安全

错误。未列出的工具也会被 bypass mode 批准。

### 误区 7：Session resume 会恢复代码

错误。它恢复对话；代码状态需要 Git、checkpoint 或文件系统 snapshot。

### 误区 8：复制 `.claude/` 就复制了完整运行环境

错误。Plugins、外部 CLI、语言运行时、浏览器、数据库和凭据可能都不在 `.claude/` 内。

### 误区 9：CLI 已安装 Plugin，SDK 一定自动加载

不应这样假设。SDK 应显式传本地 Plugin 路径并检查 init message。

### 误区 10：任何 OpenAI-compatible 模型都能替代 Claude

错误。协议兼容、工具行为和 Agent 质量都需要独立验证，且非 Claude 模型不属于官方支持范围。

### 误区 11：SDK sandbox 等于完整容器隔离

错误。工具权限、Bash sandbox、文件系统、MCP、Hooks 和网络不是同一层边界。

### 误区 12：Structured output 可以代替业务校验

错误。它只约束模型输出形状，不替代授权、数据库约束和安全验证。

---

## 26. 采用前检查清单

### Runtime

- [ ] 固定 `claude-agent-sdk` 版本；
- [ ] 明确使用 bundled binary 还是 `cli_path`；
- [ ] 记录实际 runtime 版本；
- [ ] 真实执行最小 Agent 任务。

### Authentication

- [ ] 明确 Anthropic、Bedrock、Google Cloud、Foundry 或 gateway；
- [ ] 验证模型、streaming、tool use 和 token counting；
- [ ] 不依赖开发者个人终端中的临时 key；
- [ ] 不向第三方用户转售个人 Claude 订阅额度。

### Configuration

- [ ] 显式设置 `cwd`；
- [ ] 显式设置 `setting_sources`；
- [ ] 决定是否复用 `~/.claude/`；
- [ ] 多租户使用独立 `CLAUDE_CONFIG_DIR`，并单独隔离认证凭据；
- [ ] 核验 `CLAUDE.md`、Rules、Skills 和 Agents；
- [ ] 将 Skill 的关键 `allowed-tools` 转为 SDK 权限。

### Extensions

- [ ] Plugins 已安装到受控路径；
- [ ] 通过 `options.plugins` 显式加载；
- [ ] 从 init message 核验 Plugins、Skills、commands 和 tools；
- [ ] MCP OAuth、timeout 和凭据已处理；
- [ ] 外部 CLI 与浏览器依赖已进入执行镜像。

### Sessions

- [ ] 保存 `session_id`；
- [ ] 明确 resume 和 fork 语义；
- [ ] SessionStore 与 file checkpoint 不在同一 session 中组合；
- [ ] SessionStore 跨主机恢复使用匹配的 `cwd`；
- [ ] 工作区独立持久化；
- [ ] SessionStore 实施加密和租户隔离；
- [ ] 不把 transcript 当作文件快照。

### Safety

- [ ] 定义 `tools` 和 `disallowed_tools`；
- [ ] 选择合适 permission mode；
- [ ] 高风险调用经过 `PreToolUse`；
- [ ] 容器使用非 root、资源限制和独立文件系统；
- [ ] 网络默认拒绝并经 egress proxy；
- [ ] 长期凭据位于 Agent 安全边界之外；
- [ ] Push、发布、删除和生产操作有确定性授权。

### Operations

- [ ] 设置 turn、预算和 wall-clock 限制；
- [ ] 处理异常 Result subtype；
- [ ] 处理 subprocess crash 和卡死；
- [ ] 配置 OTEL、日志脱敏和告警；
- [ ] 对 SDK 升级运行兼容性测试。

---

## 27. 最终评价

Claude Agent SDK 的价值不是“把 Claude API 包装得更简单”，而是将 Claude Code 的 Agent harness 作为可编程 runtime 提供给应用。

它尤其适合：

- 自动代码分析和修复；
- 多轮项目开发助手；
- 后台研发任务；
- 带 Skills、MCP 和 Subagents 的领域 Agent；
- 需要程序化权限、会话和结果处理的应用；
- 在隔离工作区中运行的自动化开发系统。

不适合直接期待它提供：

- 完整 Claude Code 终端 UI；
- IDE 原生交互界面；
- 无需基础设施的托管 Agent；
- 任意模型的通用 Agent 兼容层；
- 默认安全的多租户执行环境。

如果现有工作方式主要依赖项目中的 `CLAUDE.md`、`.claude/settings.json`、Rules、Skills、filesystem Subagents、Hooks、MCP 和 Bash，那么迁移到 Agent SDK 通常可以复用大部分能力资产。主要改造集中在：

1. 把人工阶段顺序转成应用层编排；
2. 显式管理 session；
3. 将 CLI 中隐含的审批和 UI 行为改成 callback 与产品界面；
4. 显式加载并核验 Plugins；
5. 将 Skill 工具授权转换为 SDK 权限配置；
6. 建设隔离、凭据、网络和运维体系。

---

## 官方资料

- [Agent SDK overview](https://code.claude.com/docs/en/agent-sdk/overview)
- [Agent SDK quickstart](https://code.claude.com/docs/en/agent-sdk/quickstart)
- [Python SDK reference](https://code.claude.com/docs/en/agent-sdk/python)
- [How the agent loop works](https://code.claude.com/docs/en/agent-sdk/agent-loop)
- [Streaming input modes](https://code.claude.com/docs/en/agent-sdk/streaming-vs-single-mode)
- [Streaming output](https://code.claude.com/docs/en/agent-sdk/streaming-output)
- [User input and approvals](https://code.claude.com/docs/en/agent-sdk/user-input)
- [Structured outputs](https://code.claude.com/docs/en/agent-sdk/structured-outputs)
- [Permissions](https://code.claude.com/docs/en/agent-sdk/permissions)
- [Claude Code features in the SDK](https://code.claude.com/docs/en/agent-sdk/claude-code-features)
- [System prompts](https://code.claude.com/docs/en/agent-sdk/modifying-system-prompts)
- [Skills](https://code.claude.com/docs/en/agent-sdk/skills)
- [Slash commands](https://code.claude.com/docs/en/agent-sdk/slash-commands)
- [Subagents](https://code.claude.com/docs/en/agent-sdk/subagents)
- [Hooks](https://code.claude.com/docs/en/agent-sdk/hooks)
- [MCP](https://code.claude.com/docs/en/agent-sdk/mcp)
- [Custom tools](https://code.claude.com/docs/en/agent-sdk/custom-tools)
- [Plugins](https://code.claude.com/docs/en/agent-sdk/plugins)
- [Sessions](https://code.claude.com/docs/en/agent-sdk/sessions)
- [Session storage](https://code.claude.com/docs/en/agent-sdk/session-storage)
- [File checkpointing](https://code.claude.com/docs/en/agent-sdk/file-checkpointing)
- [Cost tracking](https://code.claude.com/docs/en/agent-sdk/cost-tracking)
- [Hosting](https://code.claude.com/docs/en/agent-sdk/hosting)
- [Secure deployment](https://code.claude.com/docs/en/agent-sdk/secure-deployment)
- [LLM gateways](https://code.claude.com/docs/en/llm-gateway)
- [Gateway protocol](https://code.claude.com/docs/en/llm-gateway-protocol)
- [Feature availability](https://code.claude.com/docs/en/feature-availability)
- [VS Code and Cursor integration](https://code.claude.com/docs/en/vs-code)
- [Python SDK repository](https://github.com/anthropics/claude-agent-sdk-python)
- [Python SDK releases](https://github.com/anthropics/claude-agent-sdk-python/releases)
