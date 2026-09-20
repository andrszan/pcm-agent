# AI Agent 开发能力

`.claude/` 提供一组可独立调用的 Claude Code Skills、两个 Subagent 角色和通用项目规则，用于支持产品定义、技术设计、工程准备、需求开发、真实验证、独立审查和 Git 提交。

这些能力不依赖固定编排器。调用者根据项目事实选择步骤、传递上下文并处理必要决定；不适用的能力可以直接跳过。

## 设计原则

- **能力独立**：每个 Skill 在没有其它自定义 Skill 的情况下仍能完成自身职责。
- **事实优先**：以当前代码、配置、运行结果、测试和 Git 状态为依据，不用口头结论替代证据。
- **职责清楚**：Skill 通过项目文档、活动 TRD、代码和验证结果协作，不通过隐藏指令建立耦合。
- **真实验证**：测试、构建、服务、数据库和浏览器行为按任务风险实际执行；工具缺失时保留缺口。
- **保护工作树**：普通能力不提交、不建分支、不合并；Git 提交只由 `commit-changes` 显式完成。
- **凭据隔离**：密码、API key、token、私钥和个人认证信息只放在受保护且 Git 忽略的配置中。

## 核心 Skills

| Skill | 职责 |
|---|---|
| `project-intake` | 通过对话收敛目标用户、产品范围、核心任务和高风险假设 |
| `solution-design` | 基于已组装的工程事实确定系统边界和总体技术方向 |
| `project-readiness` | 建立开发资源准备基线，核验外部服务、权限和本地配置 |
| `project-bootstrap` | 将业务无关的基础工程项目化，并完成安装、构建、启动和基础验证 |
| `engineering-architecture` | 明确代码交付单元、模块职责、边界、依赖和代表性文件归属 |
| `ui-ux-framework` | 建立或演进跨需求稳定的产品界面、内容语言和交互框架 |
| `tailwind-theme` | 为 Tailwind CSS v4 项目选择、适配或定制基础主题 |
| `media-assets` | 复用、检索、生成、检查并固化开发期媒体资源 |
| `requirement-breakdown` | 将最终产品范围拆成有结果、依赖和验收方向的 Backlog |
| `trd-design` | 为一个内聚需求形成或更新活动 TRD |
| `dev-workflow` | 实现功能、Bug 或重构，并完成与风险相称的真实验证 |
| `product-experience-audit` | 对完整集成产品执行跨需求、跨页面的体验审计 |
| `product-feedback-triage` | 核验、筛选并去重一批人工产品反馈 |
| `project-data-baseline` | 为已集成产品建立可初始化、可重置、可交接的数据基线 |
| `session-rule-retrospective` | 从真实执行中提炼可复用规则，只增量维护项目 rules |
| `commit-changes` | 分析真实 Git 变更并创建一个或多个精确的本地提交 |
| `pcm-product-factory` | 在明确需要时辅助产品构思，并在目标工作区维护产品想法目录 |

`docs/prd/`、`docs/trd/`、`docs/backlog/` 等路径是部分 Skills 在**目标项目**中的默认文档位置，不表示本仓库附带真实产品资料。

## Subagents

| Subagent | 职责 | 边界 |
|---|---|---|
| `dev` | 在给定目标和边界内完成内聚修改及局部验证 | 不提交、不维护最终 Backlog、不擅自扩大范围 |
| `reviewer` | 只读检查正确性、安全、数据、回归和验证缺口 | 不修改文件，不代替负责人作最终裁决 |

## Rules

| Rule | 作用 |
|---|---|
| `existing-resource-use.md` | 优先调查和复用目标项目已有资源 |
| `markdown-writing.md` | 约束 Markdown 文档的结构、链接和表达 |
| `testing.md` | 按真实行为与风险选择验证方式 |

## Git 职责

| 能力 | Git 边界 |
|---|---|
| 普通领域 Skill | 可以读取状态和 diff；留下待提交修改 |
| `dev-workflow` | 完成实现与验证，不暂存、不提交、不建分支、不合并 |
| `session-rule-retrospective` | 只维护项目 rules，不提交 |
| `commit-changes` | 唯一负责精确暂存和本地提交的 Skill，默认不 push |
| `dev` | 不暂存、不提交、不改写历史 |
| `reviewer` | 全程只读 |

分支创建、切换、合并、push 和远端操作仍由调用者显式决定。

## 接入目标项目

1. 将 `.claude/`、`AGENTS.md` 和 `CLAUDE.md` 复制到目标项目，先检查并合并已有规则，不直接覆盖冲突内容。
2. 根据目标项目的版本文件、依赖声明和 README 准备运行时、包管理器、数据库、外部服务与本地配置。
3. 空白项目通常从 `project-intake` 开始；已有项目、Bug 或局部重构只调用当前任务需要的能力。
4. 需要基础工程时，根据 `catalog.json` 选择业务无关模板，再在派生项目中完成裁剪、通信、认证、数据和部署接线。
5. UI 任务使用目标项目已有的 Playwright、端到端测试或其它可靠浏览器通道；没有固定工具时不自动安装，也不伪造验证结果。
6. 真实凭据保留在 Git 忽略的配置中；文档只记录环境、入口、角色、账号标识、初始化方式和安全获取凭据的方法。

## 外部能力

本仓库不分发第三方 Plugin 或通用第三方 Skills，也不会自动安装 CLI、插件或项目依赖。某个 Skill 提到外部工具时，应先确认目标环境已经具备该工具；不可用时继续完成其它工作，并准确报告剩余验证缺口。

保留的少量第三方设计参考位于对应 Skill 的 assets 目录，来源与许可证见根目录 [`THIRD_PARTY_NOTICES.md`](../THIRD_PARTY_NOTICES.md)。
