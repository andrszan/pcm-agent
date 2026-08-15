# AI Agent 开发能力说明

## 1. 目录定位

`.claude/` 提供一组可独立调用的 AI Agent Skills、两个 Subagent 角色和项目内配置，用于支持产品定义、技术与工程设计、开发验证、只读审查、Git 提交和会话复盘。

本目录只定义**能力**；具体的先后顺序、重复、跳过、分支、合并和停止条件属于人工流程。默认人工流程见 [`AI Agent开发流程设计.md`](./AI%20Agent开发流程设计.md)。

## 2. 独立性原则

- 每个 Skill 必须能在没有其它自定义 Skill 时完成自身职责。
- Skill 不写死固定上游或下游，不自动调用其它自定义 Skill，不依赖另一 Skill 的专属过程产物。
- 能力之间通过已有项目事实协作，例如产品文档、活动 TRD、代码、Git diff 和验证结果；这些事实不要求由某个特定 Skill 生成。
- 每个 Skill 只保留完成自身职责所需的最小安全边界，不通过共享隐藏指令建立耦合。
- 工具适配型 Skill 可以依赖对应运行工具，但必须是可选能力；核心领域 Skill 不得硬依赖它们。
- 第三方 Skill 不属于核心流程隐藏依赖，不因“可能有用”自动安装。

## 3. Git 职责

| 能力 | Git 边界 |
|---|---|
| 普通领域 Skill | 可以读取状态和 diff；留下待提交变更，不 stage、不 commit、不建分支、不合并、不 push |
| `dev-workflow` | 完成实现与验证并报告受影响仓库；不 stage、不 commit、不建分支、不合并、不 push |
| `session-rule-retrospective` | 只编辑 `.claude/rules/`，不提交 |
| `commit-changes` | 唯一负责精确 stage/commit；按仓库分别显式调用，默认不 push |
| `dev` Subagent | 不 stage、不 commit、不改 Git 历史 |
| `reviewer` Subagent / `codex-review` | 只读，不改变文件或 Git 状态 |

建分支、切换分支和合并回 `main` 是人工流程中的显式 Git 操作，不属于 `commit-changes`。

## 4. 能力分类

### 核心领域 Skills

| Skill | 职责 |
|---|---|
| `project-intake` | 通过对话把想法或已有资料收敛为当前项目权威产品定义 |
| `solution-design` | 确定项目级技术方向、交付单元和跨模块边界；可选评估用户提供的模板资产 |
| `project-readiness` | 核验仓库、依赖、服务、账号、素材、配置和真实验证条件，维护准备清单 |
| `project-bootstrap` | 将已有基础工程项目化，并完成适用安装、构建、启动和基础验证 |
| `engineering-architecture` | 设计分层、模块、目录职责、依赖方向和架构演进条件；默认不修改 `AGENTS.md` |
| `ui-ux-framework` | 通过 `bootstrap`、`before`、`after` 建立框架、补足需求级设计或只读审查实现 |
| `requirement-breakdown` | 将产品范围拆成有明确结果、依赖和验收方向的 Backlog |
| `trd-design` | 为一个内聚需求形成或更新活动 TRD；默认不跨文档同步 Backlog 或产品资料 |
| `dev-workflow` | 实现功能、Bug 或重构，完成适用自动化、真实运行、浏览器和独立审查证据 |
| `session-rule-retrospective` | 从一次真实执行中提炼可复用项目规则，只增量编辑 `.claude/rules/` |
| `commit-changes` | 分析真实 Git 变更，按功能结果精确创建一个或多个本地提交 |

### 可选工具适配 Skills

| Skill | 依赖与边界 |
|---|---|
| `codex-review` | 依赖可用的 Codex CLI/companion；只读审查，不可用不代表审查通过，也不阻塞普通开发 |
| `playwright-cli` | 依赖对应浏览器运行工具；用于真实浏览器操作与验证，核心 Skills 不得把它作为隐藏必需 Skill |

浏览器工具不可用时，应记录真实验证缺口；本仓库不为此自动安装新的 CLI 或插件。

### 第三方 Skills

- `find-skills`
- `shadcn`

它们由外部来源维护，本仓库不直接重写其内容，也不把它们作为核心流程必经能力。

### 流程外辅助能力

`pcm-product-factory` 是面向特定产品选题场景的专用能力，可输出产品初稿并更新其产品目录。它不是核心开发流程的必经 Skill；若使用，其结果仍由 `project-intake` 收敛为当前项目权威产品定义。

## 5. Subagents

| Subagent | 职责 | 边界 |
|---|---|---|
| `dev` | 在 Leader 给定的目标与边界内实现内聚修改并完成局部真实验证 | 实质扩大范围或重大迁移时返回 `needs-decision`；不提交、不维护 Backlog 或最终状态 |
| `reviewer` | 独立、只读、基于证据检查正确性、安全、数据、回归和验证缺口 | 不修改文件，不运行会写状态的测试，不作最终裁决 |

`reviewer` 与 `codex-review` 不重复：前者是本地通用只读 Subagent，后者是可选的外部独立审查工具适配。

## 6. 目录结构

```text
.claude/
├── README.md
├── AI Agent开发流程设计.md
├── agents/
│   ├── dev.md
│   └── reviewer.md
├── skills/
│   ├── codex-review/SKILL.md
│   ├── commit-changes/SKILL.md
│   ├── dev-workflow/SKILL.md
│   ├── engineering-architecture/SKILL.md
│   ├── pcm-product-factory/SKILL.md
│   ├── playwright-cli/
│   │   ├── SKILL.md
│   │   └── references/
│   ├── project-bootstrap/SKILL.md
│   ├── project-intake/SKILL.md
│   ├── project-readiness/SKILL.md
│   ├── requirement-breakdown/SKILL.md
│   ├── session-rule-retrospective/SKILL.md
│   ├── solution-design/SKILL.md
│   ├── trd-design/SKILL.md
│   ├── ui-ux-framework/
│   │   ├── SKILL.md
│   │   └── evals/
│   ├── find-skills -> 第三方 Skill
│   └── shadcn -> 第三方 Skill
├── settings.json
└── settings.local.json
```

项目执行时可以另有 `.claude/rules/` 保存项目级稳定规则。普通运行不创建专属过程目录、Manifest、Run ID 或阶段报告；需要长期保留的事实进入产品文档、活动 TRD、代码、测试、Git 或项目已有记录位置。

## 7. 使用边界摘要

- 先读取真实项目事实，再决定是否以及如何调用某个 Skill。
- 不因为示例流程存在就机械运行所有能力；不适用时允许无副作用跳过。
- 活动需求和活动 TRD 可随当前事实调整；归档历史保持不可变。
- 开发 `.env` 可以在项目范围内安全使用，但不能伪造外部凭据，秘密必须保持 Git 忽略并在输出中脱敏。
- 不为当前任务擅自引入新基础设施、CLI、插件或第三方 Skill。
- 验证以真实行为和风险为中心，局部 Mock、代码阅读或工具缺位不能冒充完成。
