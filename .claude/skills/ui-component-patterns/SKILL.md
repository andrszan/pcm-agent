---
name: ui-component-patterns
description: Use when React + shadcn/ui Base UI + Tailwind CSS v4 项目正在实现本地库已收录的流式/附件 Chat、双栏登录、发票摘要、配送地址、团队邀请、通知偏好、分类 FAQ、折线趋势、区域加载反馈或 Markdown 内容阅读场景，需要在编码前选择受控组合参考并按当前业务、品牌、数据和状态二次设计时；即使用户没有点名本 Skill，只要这些具体场景正在避免基础组件堆砌或重复手搓也应使用。不用于一般 shadcn 组件任务、registry/docs/add/update、Radix 或其它不兼容栈、只改主题、产品级 Shell/信息架构、单个原子组件调整或开发后验收。
argument-hint: <目标前端路径、具体 UI 场景、业务数据、状态与品牌约束>
allowed-tools: Read, Glob, Grep, Bash, Write, Edit, TodoWrite
---

# ui-component-patterns — 场景组件参考与项目化适配

## 定位

这是一个可独立调用的可选技术适配能力。它根据目标项目的真实技术栈和具体用户任务，从本地受控参考库选择少量场景组合，提取有价值的结构与交互原理，再使用目标项目自己的组件、数据、内容、状态和视觉体系完成二次设计。

参考库不是生产组件包、设计答案或可直接安装的 registry。它用于避免两种低质量结果：只堆叠基础组件形成通用界面，或在已有成熟组合可供分析时重复手搓完成度较低的场景组件。

本能力不自动调用其它自定义 Skill，不形成固定调用链，也不因为本地存在参考就机械使用。

## 适用闸门

开始前先从真实工程核验以下条件：

1. 当前实现使用 React/TSX；
2. Tailwind CSS 为 v4，并能定位活动 CSS-first 入口；
3. shadcn primitives 实际基于 `@base-ui/react`；
4. 当前组件使用 Base UI `render` 等组合方式，而不是 Radix `asChild`；
5. 当前请求涉及具体 Chat、附件、认证、表单、业务卡片、真实时间趋势、区域加载反馈或 Markdown 内容阅读场景；
6. 调用方需要实现时，已经授权相应项目文件写入。

至少结合 `package.json`、`components.json`、实际 imports 和已有组件实现判断。不能只凭“使用 shadcn”、preset 名称或参考素材路径推断兼容。

出现以下情况时无副作用跳过：

- Radix、React Aria、Vue、Bootstrap 或其它不兼容技术栈；
- 技术栈证据冲突或无法确认；
- 只调整 Tailwind light/dark 配色、字体或品牌 token；
- 决定产品级 Shell、主导航、信息架构或全局页面模式；
- 只修改一个 Button、Input、Dialog 或其它原子组件；
- 任务只是搜索、安装、更新 shadcn registry、preset 或项目依赖，而非实现已收录场景；
- 只做开发后浏览器验收、发布判断或代码审查；
- 本地库没有真正匹配当前任务的资产。

只需要建议时返回候选和适配风险，不修改项目。明确要求实现且范围可安全确定时，才在调用方当前 UI 范围内落地。

## 按需读取

不要一次加载整个资源库：

| 需要 | 读取 |
|---|---|
| 核验 collection 技术基线、来源、依赖和本地路径 | [`assets/react-shadcn/base-tailwind-v4/manifest.json`](./assets/react-shadcn/base-tailwind-v4/manifest.json) |
| 根据具体任务选择候选 | [`references/catalog.md`](./references/catalog.md) |
| 已选定资产，需要完成项目化检查 | [`references/adaptation-checklist.md`](./references/adaptation-checklist.md) |
| 确认单项适用、依赖、缺失和许可 | 只读选中资产的 `README.md` |
| 需要分析具体组合方式 | 最后再读选中资产的 `source/` |

默认只选一个资产。只有两个候选代表实质不同的任务结构，且当前事实不足以直接排除其一时，最多比较两个。不要浏览全部源码后选择最容易复制的一项。

## 选择流程

1. 明确用户、对象、完成结果、主要行动、数据规模、关键状态和目标视口；
2. 核验技术栈和目标项目已经存在的 primitives、packages、aliases、图标与 token；
3. 从 manifest 和 catalog 过滤候选；
4. 读取候选 README，确认适用、不适用、依赖、known gaps 和许可；
5. 说明借用的是信息分组、消息顺序、字段组合、状态表达、操作层级还是趋势表达；
6. 只有确定适用后才读取 source；
7. 按目标项目事实重新实现，并完成与当前改动相称的测试和验证移交。

没有匹配资产时直接使用目标项目现有设计与组件完成任务，不为使用本 Skill 而勉强套用最接近的模板。

## 项目化转译

参考只证明一种组合如何工作。使用时必须完成：

1. **项目事实**：以真实用户任务、业务对象、数据、状态、设备和代码为准；
2. **借用原理**：只提取对当前问题有价值的结构或交互；
3. **项目化表达**：使用目标项目自己的信息层级、组件、品牌、token、内容和状态模型；
4. **有依据差异**：保留或改变参考决定都由项目事实解释，不随机变化；
5. **真实验证移交**：明确当前实现仍需执行的测试、运行和浏览器验收。

禁止复制后只替换 Logo、颜色或文案。必须检查并替换：

- fixture、演示日期、金额、邮箱、角色、文件名和静态选项；
- `Acme Inc.`、`Ledger` 等演示品牌；
- `href="#"`、`IconPlaceholder`、上游 aliases 和宿主资源；
- 固定宽高、断点、Card 数量、图表 series 和 demo logic；
- GitHub 等商标、远程媒体和第三方品牌；
- SOC 2、SEC registered、加密、供应商、价格或试用等未经项目事实确认的声明；
- 没有实现的 OAuth、支付、税务、上传、下载、复制、保存和重试行为。

## Base UI 约束

只使用目标项目已经安装的 Base UI shadcn primitives：

- 自定义 trigger、close 或复合控件使用 `render`，不用 `asChild`；
- `render` 为非 button 元素时按对应组件合同处理 `nativeButton={false}`；
- Select 核对 `items`、placeholder/value、group 和 `alignItemWithTrigger`；
- Checkbox mixed 状态使用独立的 `indeterminate`；
- Accordion 的单选值仍按 Base UI 数组合同处理；
- InputGroup 内使用 `InputGroupInput` 或 `InputGroupTextarea`；
- 不把 Base UI 示例机械翻译成 Radix，也不安装第二套 primitive library。

缺失 registry component 或 package 时，报告精确缺口和受影响能力；选择本地参考本身不构成安装授权。调用方已明确要求实现或调试时，可按目标项目现有包管理器安装完成该任务所需的合理依赖并同步 lockfile，不必逐包重复询问，也不得为避免依赖而删除已要求的功能；不能借此扩大为无关的 registry 搜索、`shadcn add`、preset 应用或依赖更新。

## Chat 约束

使用 Chat 参考时：

- 消息内容使用目标项目已有的 `Message` 与 `Bubble` 组合；
- 只有需要滚动、流式增长、历史 prepend 或跳到最新时，才由 `MessageScroller` 作为滚动所有者，并由父容器提供确定高度、`min-h-0` 和正确 overflow；
- 只有存在 Thinking、系统事件、日期分隔或状态行时才使用 `Marker`，附件场景才使用 `Attachment`；
- 需要消息定位时使用稳定 `messageId` 和有业务依据的 turn anchor；
- 使用自动跟随时明确 `autoScroll`，用户主动上滚后不强制拉回；
- 跳到最新、停止生成、停止后的反馈和历史 prepend 按当前场景定义；
- transport、AI SDK 状态、重试和附件生命周期留在场景适配层，不进入 Bubble/Message primitives；
- 已使用 `MessageScroller` 时，不再手写另一套 `scrollTop`、`ResizeObserver` 或 `useStickToBottom` 逻辑。

上游 streaming 示例使用 scripted transport 和 canary AI SDK，只能作为状态与布局参考，不能变成目标项目隐藏依赖。

## Chart 约束

只有真实用户需要判断一个或两个指标的时间变化时，才选择折线趋势参考：

- 数据、series、时间范围、单位、locale、时区和缺失值来自真实合同；
- tooltip、轴、辅助结论和行动语义可被用户理解；
- 表单、设置、审批队列、普通数据表或“后台页面”不自动需要统计卡和图表；
- 没有真实趋势需求时不添加 Chart/Recharts；确需实现而缺少依赖时，按上述实现任务的依赖授权边界补齐。

## Loading 与 Markdown 约束

- Loading 表达实际等待，不把装饰动画解释为业务阶段；加载区域由调用方控制，不能覆盖或重新定义 App Shell，尊重 reduced motion。
- Markdown 保留任务要求的解析、Prism 高亮、行号和 `next-themes` 明暗/system 主题能力；核对 SSR/hydration、未知语言 fallback、代码块状态隔离、复制成功与失败、长行与表格局部滚动。已明确要求实现或调试时可安装必要合理依赖，不得以避免依赖为由降级功能。
- 保留 Markdown 默认安全解析边界，不默认启用 raw HTML；图片来源、链接策略和流式内容按真实项目处理。
- 用户导入的 `loading`、`markdown` 目前来源与许可待确认，只供本地维护验证；不得推断 collection 的 shadcn MIT License 覆盖它们。生产复用前必须核实授权。

## 边界

本能力不负责：

- 产品范围、Backlog、单需求 TRD 或开发顺序；
- 产品级 Shell、主导航、信息架构、页面模式或全局视觉体系；
- shadcn registry、preset、组件安装或更新；
- Tailwind 主题颜色、字体、圆角或阴影基础设施；
- 媒体检索、生成、下载或对象存储；
- 数据模型、后端接口、权限架构或业务规则的最终设计；
- 独立完成浏览器验收、发布判断、提交、合并或 push。

## 完成与汇报

完成后简要报告：

- 适用或跳过依据；
- 选中的 asset ID；
- 借用的原理和主要项目化差异；
- 明确丢弃的 fixture、品牌、声明和 demo logic；
- 缺失依赖、未闭合状态和仍需执行的验证；
- 实际修改文件与已完成检查。

产品运行时代码不得 import 本 Skill 的内部 assets 路径。参考源码、README 和预览不能替代目标项目中的真实运行与浏览器证据。
