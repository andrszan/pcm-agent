# PCM 开发管理与能力工作区

本仓库是 PCM 的内部开发管理、AI Agent 能力、产品开发流程和 `pcm-demo` 技术验证工作区。它不是客户产品仓库，也不是已经建成的正式 PCM Core 或对外商业平台。

## 从这里开始

- [PCM 文档导航](docs/pcm/README.md)
- [PCM 项目规划](docs/pcm/项目规划/README.md)

## 主要组成

| 路径 | 职责 |
|---|---|
| [`.claude/`](.claude/README.md) | Skills、Subagents、Plugins、项目规则和开发流程能力 |
| [`pcm-demo/`](pcm-demo/README.md) | 正式 PCM 前的本地程序化流程验证工具 |
| [`docs/pcm/`](docs/pcm/README.md) | PCM 项目治理、历史商业资料和 Demo 上位设计 |
| [`docs/prd/`](docs/prd/) | 产品初稿和 PRD |
| [`catalog.json`](catalog.json) | 业务无关的前端、后端基础工程候选目录 |
| [`docs/pcm-product-catalog.json`](docs/pcm-product-catalog.json) | 产品初稿目录数据，不等同于成品目录 |
| `frontend/`、`backend/` | 根工作区约定的独立前后端代码仓位置；当前不代表正式 PCM 或商业平台已实现 |

## 技术入口

- [AI Agent 开发能力说明](.claude/README.md)
- [人工调度的 AI Agent 产品开发流程](.claude/AI%20Agent开发流程设计.md)
- [PCM 程序化调度的 AI Agent 产品开发流程](.claude/PCM版AI%20Agent自动化流程设计.md)
- [PCM 自动化流程 Demo](pcm-demo/README.md)
- [PCM 自动化流程 Demo 项目设计](docs/pcm/PCM自动化流程Demo项目设计.md)
- [PCM 自动化流程 Demo 项目 TRD](docs/pcm/PCM自动化流程Demo项目TRD.md)

## 仓库与客户交付边界

本仓库及其中的 Agent 能力、内部规则、流程 Prompt、运行状态、会话、诊断和内部生产资料不属于客户默认交付物。客户交付以订单列明的应用代码、必要文档和约定资源为准。当前规划见 [PCM 项目规划](docs/pcm/项目规划/README.md)。

任何密钥、令牌、实际 `.env`、外部资源凭据或其它秘密都不得进入公开文档或客户交付包。

## 协作规范

仓库结构、语言、环境配置、验证和 Git 操作规则见 [AGENTS.md](AGENTS.md)。
