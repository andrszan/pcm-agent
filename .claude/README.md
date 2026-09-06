# AI Agent 开发能力说明

## 1. 目录定位

`.claude/` 提供一组可独立调用的 AI Agent Skills、两个 Subagent 角色和项目内配置，用于支持产品定义、技术与工程设计、开发验证、只读审查、Git 提交和会话复盘。

本目录只定义**能力**；具体的先后顺序、重复、跳过、分支、合并和停止条件属于人工流程。默认人工流程见 [`AI Agent开发流程设计.md`](./AI%20Agent开发流程设计.md)。

## 2. 受控 Claude Agent SDK Plugins

模板根目录的 `.agents/plugins/` 保存由维护者管理的本地 Plugin 快照，根目录 `plugins-lock.json` 是 PCM 通过 Claude Agent SDK 加载 Plugin 的唯一清单。每个条目的 `path` 必须指向一个 Plugin root，版本、提供方和来源标识随快照更新同步维护。

SDK 运行时不会扫描 `.agents/plugins/`，也不解析用户级 `~/.claude/plugins/cache/`；`pcm-demo/common/claude_agent.py` 会读取产品项目根的 `plugins-lock.json`，校验路径仍位于项目根内且目录存在，再把每个 Plugin root 显式传给 `ClaudeAgentOptions.plugins`。Plugin 变更后应创建新的 Agent SDK session，并从 `SystemMessage(init)` 核对实际加载的 `plugins`、`skills` 和 `slash_commands`；SDK 不使用 CLI 的 `/reload-plugin` 作为热加载接口。

项目 `.claude/settings.json` 中的 `enabledPlugins` 继续服务人工 Claude Code CLI 的启用声明，不替代 `plugins-lock.json`，也不负责下载、安装或解析 Plugin 路径。更新 Plugin 时先更新 `.agents/plugins/<plugin>` 快照，再同步 `plugins-lock.json` 的版本和提供方信息；不得写入用户目录绝对路径、密钥或 Marketplace cache 路径。

### 2.1 独立性原则

- 每个 Skill 必须能在没有其它自定义 Skill 时可以完成自身职责。
- Skill 不写死固定上游或下游，不明确说一定要调用其它某个 Skill，不强制依赖。
- 能力之间通过调用方传入的资料和已有项目事实协作，例如产品文档、选模资料、活动 TRD、代码、Git diff 和验证结果；这些资料不要求由某个特定 Skill 生成或采用固定文件格式。
- 每个 Skill 只保留完成自身职责所需的最小安全边界，不通过共享隐藏指令建立耦合。
- 工具适配型 Skill 可以依赖对应运行工具，但必须是可选能力；核心领域 Skill 不得硬依赖它们。
- 审计或反馈分诊只形成带证据的候选、重复项和覆盖缺口，不创建正式需求、不分配需求 ID、不修改 canonical Backlog；是否需求化、如何纳入以及如何进入后续开发，由调用方按项目事实显式调度。
- 第三方 Skill 不属于核心流程隐藏依赖，不因“可能有用”自动安装。
- 最终产品范围表达当前产品承诺；首条验证切片只用于尽早验证关键假设，不表示缩减或完成最终范围。复杂度删减和条件式原型按风险决定；全项目级产品体验审计只在完整集成产品进入阶段二后执行，不构成单需求或验证切片的调用链。

## 3. 运行环境与使用准备

将本目录复制到目标工作区后，先确认基础工具、目录权限和目标项目自身的运行依赖。不同项目可以使用不同语言、框架、数据库、浏览器和第三方服务，但不能因此省略完整环境检查。

### 基础运行环境

| 项 | 要求 | 缺位时 |
|---|---|---|
| **Claude Code** | 能够打开目标工作区并读取项目内的 Agent、Skill 和配置文件 | 无法按本目录定义的能力和角色运行 |
| **Git** | 根仓库以及实际涉及的独立代码仓库均已正确初始化，Agent 能读取状态、差异和历史 | 无法可靠保护已有修改、建立审查基线或执行提交步骤 |
| **目录授权** | Agent 对本次任务涉及的工作区和外部仓库具有必要的读取、编辑与命令权限 | 只能准确报告不可访问范围，不能假设文件或验证结果 |
| **权限策略** | `.claude/settings.json` 或实际运行环境允许当前项目需要的 Git、运行时、包管理、测试、构建和服务命令 | 先补充或确认必要权限，不通过绕过安全边界伪造执行结果 |
| **项目运行时与包管理器** | 根据目标仓库的 README、贡献说明、版本文件、锁文件和构建配置使用正确版本 | 不凭经验替换技术栈、版本或包管理器；环境未就绪时先处理准备问题 |
| **项目依赖与验证工具** | 安装目标项目实际需要的依赖，并保证测试、静态检查、类型检查、构建等适用命令可执行 | 保留真实验证缺口，不以代码阅读或历史结果代替本次执行 |
| **本地服务与数据** | 按项目事实准备数据库、中间件、迁移、初始化数据、第三方沙箱或其它必要服务 | 不使用 Mock、假数据或删除验收项来掩盖真实依赖缺失 |
| **本地配置** | 按项目说明准备开发 `.env` 或等价配置，实际秘密保持 Git 忽略 | 可补齐本机可生成或项目已提供的配置；不得伪造外部账号、授权或凭据 |

### 开发账号与凭据边界

- PCM 或 Agent 为目标产品创建或调整、最终保留在交付开发数据中且交付后仍可登录的所有开发账号及密码，都是受版本控制的产品交付信息，包括普通用户、业务角色、产品管理员和产品超级管理员。真实开发账号应项目专用、不冒用真实个人身份、在开发数据中真实存在且可登录；真实开发数据不等于真实个人或生产数据。不得将这些账号称为演示账号、体验账号或假账号，也不得附加演示租户、隔离业务数据、生产禁用 Seed 等部署阶段限制。
- 项目约定的受跟踪 README 或独立账号文档必须记录适用开发环境、登录入口、角色、账号、密码、Seed/reset 方式及必要已有开发数据说明。账号创建、修改或删除时同步文档；开发完成前逐个核验账号真实存在、密码可登录、角色一致和已有开发数据可见。Seed/reset 保持幂等、不重复且不覆盖其管理范围外的已有账号或数据。临时测试后删除或事务回滚、未保留在最终交付开发状态中的短期账号无需逐个记录。
- 凭据是否公开按认证目标判断：用于登录目标产品的交付开发账号公开；PCM 或目标产品用于访问其它系统或资源的数据库、对象存储、SMTP、OAuth client secret、API key、私钥、令牌、Git、云、服务器、基础设施账号、PCM 工具和媒体 Provider 凭据及真实个人认证信息仍属秘密。`docs/ignore/` 可继续保存真正私密的开发资源资料，但不承担目标产品账号交接。

开始文档设计或开发前，根据当前任务至少检查：

1. 阅读目标仓库的 README、贡献说明、`AGENTS.md`、版本文件、锁文件和构建配置；
2. 分别确认根仓库及适用子仓库的目录、当前分支、Git 基线和工作树状态；
3. 确认语言运行时、包管理器、项目依赖和目标命令能够执行；
4. 确认必要服务、迁移、初始化数据和本地配置可用；
5. 确认本次完成标准需要的测试、构建、真实接口、浏览器或其它验证条件已经具备。

环境检查的深度应与当前任务相称。纯文档修改不机械启动全部服务；实现、联调和交付验收不能因环境准备复杂而跳过适用条件。

### UI 浏览器验收环境

只要任务包含 UI、用户交互或浏览器可见结果，就应使用真实浏览器验证动态行为，并实际读取代表性渲染结果；不能只依赖代码阅读、组件测试、Mock、DOM 结构或未查看的截图。验证不仅确认“可以操作”，还要按任务风险检查流程复杂度、内容理解、信息与操作层级、目标视口和基本可访问性。

可以使用当前项目已经具备的任一可靠通道：

1. 项目已有的 Playwright、端到端测试或其它浏览器测试能力；
2. 已安装并可用的 Playwright MCP 或等价浏览器工具；
3. 当前环境已经可用的 `playwright-cli`；
4. 只有自动化无法替代主观体验、外部设备或特殊授权时，才由用户进行现场验收。

实现前若核心任务、信息架构或视觉方向存在多个高影响方案，可以采用任务流、关键状态草图、可抛弃点击原型或真实项目窄范围预览取得最低成本证据；不固定工具、目录或文件格式，也不要求普通局部变化机械制作原型。

核心领域 Skill 不依赖某一个固定浏览器 Skill 或插件。浏览器工具缺失时，继续完成其它可执行验证，但相关 UI 验收必须保持未完成，并明确缺失条件和补验方式；不得删除验收项后宣称完成。

`product-experience-audit` 只用于完整集成产品的全项目级审计，同样使用目标项目已经具备的真实浏览器通道，不硬依赖 `playwright-cli` 或其它固定适配。单页面、单需求、验证切片或局部改动由当前设计和开发验收覆盖，不调用该 Skill；缺少全项目范围、环境、测试身份、可复位数据或动态证据能力时，只能报告范围不足或真实覆盖缺口，不能用代码阅读、Mock 或截图替代任务级体验结论。

## 4. Git 职责

| 能力 | Git 边界 |
|---|---|
| 普通领域 Skill | 可以读取状态和 diff；留下待提交变更，不 stage、不 commit、不建分支、不合并、不 push |
| `dev-workflow` | 完成实现与验证并报告受影响仓库；不 stage、不 commit、不建分支、不合并、不 push |
| `session-rule-retrospective` | 只编辑 `.claude/rules/`，不提交 |
| `commit-changes` | 唯一负责精确 stage/commit；按仓库分别显式调用，默认不 push |
| `dev` Subagent | 不 stage、不 commit、不改 Git 历史 |
| `reviewer` Subagent | 只读，不改变文件或 Git 状态 |

建分支、切换分支和合并回 `main` 是人工流程中的显式 Git 操作，不属于 `commit-changes`。

## 5. 能力分类

### 核心领域 Skills

| Skill | 职责 |
|---|---|
| `project-intake` | 通过对话收敛最终产品范围、核心任务、用户语言、复杂度取舍和需要尽早验证的高风险假设 |
| `solution-design` | 基于已组装的工程事实确定项目级技术方向、系统边界和跨模块技术方案 |
| `project-readiness` | 建立当前自动化开发周期唯一的开发资源准备基线，实际准备外部服务、运行凭据和受保护配置，并维护脱敏清单 |
| `project-bootstrap` | 将已有基础工程项目化，按既有资源绑定迁移配置接线，并完成适用安装、构建、启动和基础验证 |
| `product-experience-audit` | 对当前完整集成产品执行跨需求、跨模块、跨页面的全项目级体验审计，输出经核验候选、重复项和覆盖缺口，不修改正式 Backlog |
| `product-feedback-triage` | 核验、拆解、去重和分级人工产品反馈，并按项目约定形成候选变更项 |
| `engineering-architecture` | 在单份项目架构文档中，按每个适用业务代码交付单元设计可核验的 Current/Target、职责/边界/依赖和代表性文件归属；默认不修改 `AGENTS.md` |
| `ui-ux-framework` | 建立、校正或演进跨需求稳定的产品表面、App Shell Contract、内容语言、视觉和交互框架；按需读取技术中立布局资源或明确记录来源、许可与未知边界的框架源码快照，后者不代表项目技术选型；不负责单需求设计或开发后验收 |
| `requirement-breakdown` | 完整覆盖最终产品范围，拆成有明确结果、依赖和验收方向的 Backlog，并建议首条验证切片 |
| `trd-design` | 为一个内聚需求设计产品行为、体验复杂度、关键内容意图和技术实现，形成或更新活动 TRD |
| `dev-workflow` | 实现功能、Bug 或重构，以自动化、真实运行、浏览器、实际渲染和独立审查证明功能与体验结果 |
| `session-rule-retrospective` | 从一次真实执行中提炼可复用项目规则，只增量编辑 `.claude/rules/` |
| `commit-changes` | 分析真实 Git 变更，按功能结果精确创建一个或多个本地提交 |

### 可选技术与工具适配 Skills

| Skill | 依赖与边界 |
|---|---|
| `tailwind-theme` | 适用于 Tailwind CSS v4 CSS-first 前端；根据项目事实和明确主题要求选择经校验的 tweakcn 内置主题或生成自定义配色，只落实完整 light/dark 语义颜色并验证真实渲染，不修改字体、圆角、阴影、布局、组件或业务页面，也不自动安装 Tailwind 或组件库 |
| `ui-component-patterns` | 适用于 React + shadcn/ui Base UI + Tailwind CSS v4 的具体 Chat、认证、业务卡片、结构化表单和真实趋势场景；从本地受控参考中选择少量候选并按真实业务、品牌、数据和状态二次设计，不安装或复制 registry，不决定 Shell、信息架构或主题；Radix 及其它不兼容栈无副作用跳过 |
| `playwright-cli` | 依赖当前环境已具备的对应浏览器运行工具；用于真实浏览器操作与验证，核心 Skills 不得把它作为隐藏必需 Skill |
| `media-assets` | 工作区固有、按需调用的开发期媒体工具；通过受控 Provider catalog 选择适配来源，获取少量资源并固化到目标项目，但不构成产品运行时依赖 |

可选技术或工具能力不适用、不可用时，应无副作用跳过或记录真实验证缺口；本仓库不为此自动安装新的 CLI、插件或项目依赖。

### 第三方 Skills

- `find-skills`
- `shadcn`
- `ui-ux-pro-max` 系列：可选的设计、品牌和 UI 实现辅助，不是核心流程前置，也不能作为体验合格或开发完成的证据。

它们由外部来源维护，本仓库不直接重写其内容，也不把它们作为核心流程必经能力。

### 流程外辅助能力

`pcm-product-factory` 是面向特定产品选题场景的专用能力，可输出产品初稿并更新其产品目录。它不是核心开发流程的必经 Skill；若使用，其结果仍由 `project-intake` 收敛为当前项目权威产品定义。

## 6. Subagents

| Subagent | 职责 | 边界 |
|---|---|---|
| `dev` | 在 Leader 给定的目标与边界内实现内聚修改，完成局部真实验证；用户可见范围同时提供可理解性、关键状态和实际渲染证据或明确缺口 | 实质扩大范围或重大迁移时返回 `needs-decision`；不提交、不维护 Backlog 或最终状态 |
| `reviewer` | 独立、只读、基于证据检查正确性、安全、数据、回归和验证缺口；有 UI 证据时同时检查任务理解、关键状态和明显视觉退化 | 不修改文件，不运行会写状态的测试，不作最终裁决 |

`reviewer` 是本仓库内建的独立只读审查路径。调用方如因高风险变更另行引入外部审查结果，仍须确保审查者获得权威工作区中的完整变更、验收条件和验证证据，并由 Leader 结合项目事实作最终判断。

## 7. 目录结构

```text
.claude/
├── README.md
├── AI Agent开发流程设计.md
├── agents/
│   ├── dev.md
│   └── reviewer.md
├── skills/
│   ├── commit-changes/SKILL.md
│   ├── dev-workflow/
│   │   ├── SKILL.md
│   │   └── evals/evals.json
│   ├── engineering-architecture/
│   │   ├── SKILL.md
│   │   └── evals/evals.json
│   ├── media-assets/
│   │   ├── SKILL.md
│   │   ├── providers/
│   │   │   ├── README.md
│   │   │   ├── pixabay/README.md
│   │   │   └── openai-compatible-image/README.md
│   │   ├── assets/fixtures/
│   │   │   ├── README.md
│   │   │   └── manifest.template.json
│   │   └── evals/evals.json
│   ├── pcm-product-factory/SKILL.md
│   ├── playwright-cli/
│   │   ├── SKILL.md
│   │   └── references/
│   ├── product-experience-audit/
│   │   ├── SKILL.md
│   │   └── evals/evals.json
│   ├── product-feedback-triage/
│   │   ├── SKILL.md
│   │   └── evals/evals.json
│   ├── project-bootstrap/SKILL.md
│   ├── project-intake/SKILL.md
│   ├── project-readiness/
│   │   ├── SKILL.md
│   │   └── evals/evals.json
│   ├── requirement-breakdown/
│   │   ├── SKILL.md
│   │   └── evals/evals.json
│   ├── session-rule-retrospective/SKILL.md
│   ├── solution-design/SKILL.md
│   ├── tailwind-theme/
│   │   ├── SKILL.md
│   │   ├── references/theme-selection.md
│   │   └── evals/
│   │       ├── evals.json
│   │       └── files/
│   ├── ui-component-patterns/
│   │   ├── SKILL.md
│   │   ├── references/
│   │   │   ├── adaptation-checklist.md
│   │   │   └── catalog.md
│   │   ├── assets/react-shadcn/base-tailwind-v4/
│   │   │   ├── LICENSE.md
│   │   │   ├── manifest.json
│   │   │   ├── chat/
│   │   │   │   ├── attachment-conversation/
│   │   │   │   ├── streaming-chat-card/
│   │   │   │   └── transcript-foundation/
│   │   │   ├── business/
│   │   │   │   ├── faq/
│   │   │   │   ├── invoice/
│   │   │   │   ├── invite-team/
│   │   │   │   ├── login-two-column/
│   │   │   │   ├── notification-settings/
│   │   │   │   └── shipping-address/
│   │   │   └── chart/line-trend/
│   │   └── evals/evals.json
│   ├── trd-design/
│   │   ├── SKILL.md
│   │   └── evals/evals.json
│   ├── ui-ux-framework/
│   │   ├── SKILL.md
│   │   ├── references/
│   │   │   ├── app-shell-contract.md
│   │   │   ├── layout-resource-library.md
│   │   │   └── layout-selection-guide.md
│   │   ├── assets/layout-patterns/
│   │   │   ├── list-detail-workspace/
│   │   │   ├── sidebar-workspace/
│   │   │   └── top-navigation/
│   │   ├── assets/layout-source-snapshots/shadcn-ui/
│   │   │   ├── summary-to-record-workbench/
│   │   │   ├── context-switching-navigation-shell/
│   │   │   ├── mode-rail-collection-workbench/
│   │   │   └── sectioned-preferences-dialog/
│   │   └── evals/evals.json
│   ├── find-skills -> 第三方 Skill
│   └── shadcn -> 第三方 Skill
├── settings.json
└── settings.local.json
```

项目执行时可以另有 `.claude/rules/` 保存项目级稳定规则。普通运行不创建专属过程目录、Manifest、Run ID 或阶段报告；需要长期保留的事实进入产品文档、活动 TRD、代码、测试、Git 或项目已有记录位置。

`media-assets` 的 `providers/` 维护显式准入的 Provider catalog 和适配说明，不扫描目录或自动安装来源；`assets/fixtures/` 是受跟踪测试输入的维护入口，不承载目标产品资产、对象存储数据或工作区私有凭据。

`tailwind-theme` 只面向实际采用 Tailwind CSS v4 CSS-first 语义颜色变量的前端。它按需读取 tweakcn 当前动态 registry，但只消费经过校验的 light/dark 颜色白名单并把最终值固化进目标项目；网络不可用或没有合适 preset 时依据项目事实生成自定义配色，不把动态 URL、完整远程 CSS、字体、圆角、阴影或其它非颜色 token 变成产品依赖。

`ui-component-patterns` 只面向实际采用 React、shadcn/ui Base UI 与 Tailwind CSS v4 的具体 UI 实现场景。其 `assets/react-shadcn/base-tailwind-v4/` 保存固定上游 commit 的独立 registry block、preview 内部模块和明确标记为派生的 example 函数摘录；不复制基础 primitives、完整 gallery、可运行 demo 或正式预览。Agent 每次只读取最相关的少量候选，并使用目标项目自己的业务、品牌、数据、状态、组件和 token 二次设计；MIT 代码许可不自动覆盖商标、远程媒体或演示中的安全、监管和商业声明。

`ui-ux-framework` 的布局资源分为两层：`assets/layout-patterns/` 是技术中立、原生、自包含且可运行的固定六文件模式；`assets/layout-source-snapshots/` 是记录上游来源、许可与未知边界、带有外部依赖且不可独立运行的部分框架源码快照，只用于分析结构、交互和实现假设，不代表项目技术栈或组件选型。两类资源都按需只读最相关单套，Agent 必须依据目标项目的真实用户、任务、层级、设备、技术栈和品牌事实二次设计，不能复制后只换皮。具体索引与维护合同以 `ui-ux-framework/references/layout-resource-library.md` 为准。

## 8. 使用边界摘要

- 先读取真实项目事实，再决定是否以及如何调用某个 Skill。
- 最终产品范围与首条验证切片分开表达；验证切片用于降低关键不确定性，不能冒充范围缩减或最终完成。
- 用户可见功能以任务简单、内容易懂、产品化视觉和真实运行证据共同判断，不能只检查逻辑闭环与组件正确。
- 不因为示例流程存在就机械运行所有能力；不适用时允许无副作用跳过。
- 活动需求和活动 TRD 可随当前事实调整；归档历史保持不可变。
- 开发 `.env` 可以在项目范围内安全使用；用于登录目标产品的交付开发账号及密码应进入受跟踪账号文档，PCM 或目标产品用于访问其它系统或资源的凭据及其它秘密必须保持 Git 忽略并在输出中脱敏。
- 工作区媒体 Provider 的私有配置仅服务 `media-assets`，按需调用；它们不属于目标项目配置、开发资源清单或产品运行时依赖。
- 不为当前任务擅自引入新基础设施、CLI、插件或第三方 Skill。
- 验证以真实行为和风险为中心，局部 Mock、代码阅读或工具缺位不能冒充完成。

## 9. 复制到新项目

1. 复制本仓库作为新项目工作区，或按需复制 `.claude/` 与 `AGENTS.md`；保留并核对目标项目已有的贡献规范、安全要求和 Agent 指令，不直接覆盖冲突内容。
2. 检查 `.claude/settings.json` 中的权限和插件配置是否适合目标机器与项目；不需要的可选插件可以停用，缺失工具不会由 Skill 自动安装。
3. 根据目标项目的版本文件、锁文件和说明准备运行时、包管理器、依赖、数据库、服务、迁移、初始化数据与浏览器验证条件。
4. 补齐被 Git 忽略的开发 `.env` 或等价本地配置，不复制、提交或输出原项目用于访问外部系统或资源的真实凭据及真实个人认证信息；目标产品最终保留的交付开发账号及密码按新项目事实写入其受跟踪账号文档。
5. 从当前目标需要的独立能力开始；空白项目通常先收敛产品定义，再根据实际不确定性选择技术设计、项目准备核验、工程项目化或其它适用步骤。
6. 使用目标项目自身的测试、构建、服务、数据和浏览器环境验证，不假设所有项目采用同一技术栈或工具组合。
7. 进入产品体验审计时，准备目标项目可访问的真实环境、项目专用且真实可登录的开发账号、可复位开发数据和允许操作边界；缺少固定浏览器工具不会触发自动安装，但缺少必要动态证据时必须保留覆盖缺口。

完整的新项目人工调度顺序以 [`AI Agent开发流程设计.md`](./AI%20Agent开发流程设计.md) 为准；已有项目、小改动、Bug 修复或重构不需要机械执行所有初始化步骤。

## 10. 常见问题

### 前端、后端或前后端分离项目怎么使用？

分别确认每个独立仓库的分支、状态、依赖和验证结果。后端验证真实数据库、迁移、初始化数据和接口行为；前端依赖后端时连接真实后端，在浏览器中联调关键路径。两个仓库可以分别推进，但最终验收必须覆盖真实集成。工程架构仍只维护根仓的单份项目文档；前端与后端均为适用业务代码交付单元时必须分别覆盖，不能相互替代。

### 空白项目怎么开始？

先使用 `project-intake` 收敛目标用户、产品范围、核心流程和外部约束；需要模板选型时，基于当前可读参考资料完成选型并组装适用基础工程。随后使用 `project-readiness` 建立当前自动化开发周期唯一的开发资源准备基线，实际准备并核验后续编码和开发联调所需的外部资源、权限和开发配置；生产发布条件不属于该基线。基线完成后执行 `project-bootstrap` 项目化工程；当前存在 Tailwind CSS v4 CSS-first 前端且尚无项目专属主题配色时，在项目化完成后、初始提交前条件性调用 `tailwind-theme`，同时落实并验证 light/dark 语义颜色，不新增固定编号步骤。然后基于真实工程事实调用 `solution-design` 形成总体技术方案。默认完整顺序见人工流程文档，但每个 Skill 仍可独立调用。

### 小改动或 Bug 修复也要走完整流程吗？

不需要机械执行项目初始化或完整 TRD 工作量，但仍要按行为影响完成相称验证。涉及业务规则、数据写入、权限、安全、接口兼容、跨服务集成或用户可见流程时，不能仅因改动文件少而降低完成标准。

### 没有现成接口契约怎么办？

以现有代码、真实调用方、测试和可运行行为为依据，明确尚不确定的边界并补充必要验证。接口契约有帮助，但不是开始调查或形成当前技术判断的绝对前提；无法安全推断的产品或兼容性决定仍应交由人确认。

### 执行中途被打断怎么办？

先读取活动 TRD、代码、测试结果、各仓库 Git 状态和最近提交，从这些权威事实恢复。只有项目已经约定长期协作或交接记录位置时才增量使用，不为普通中断创建专属过程目录、Manifest 或运行流水。

### 已归档的需求或 TRD 需要调整怎么办？

已完成并归档的历史需求和 TRD 保持不可变。后续升级、重构、补完或缺陷修复创建新的需求和新 TRD；当前实现需要改变旧行为时，在新的活动范围中记录变化、兼容性和验证结果。
