# 场景组件参考目录

本目录是 `ui-component-patterns` 的选择索引。机器可读技术基线、依赖和本地路径以 [`manifest.json`](../assets/react-shadcn/base-tailwind-v4/manifest.json) 为准；选定资产后的具体适配风险以该资产 README 为准。

## 当前技术基线

首批资源的已验证技术基线是 React 19.2.3、shadcn/ui 4.19.0、Base UI 1.6.0 与 Tailwind CSS 4.3.0。目标项目需要满足：

- 使用 React/TSX，并核对当前 React 版本与所选源码 API 的兼容性；
- shadcn/ui Base UI；
- Tailwind CSS v4；
- 核对资产依赖的 primitives 和 packages；明确实现或调试任务内可按项目方式补齐必要合理依赖。

不能仅凭 `components.json` 或“使用 shadcn”推断兼容。至少结合 `package.json`、实际 `@base-ui/react` imports 和现有组件组合 API 判断。Radix、React Aria、Vue、其它 CSS 框架或证据冲突时不读取源码并无副作用跳过。

## 选择规则

1. 先从真实用户任务、数据、状态和目标视口定义当前问题；
2. 默认只选择一个资产；只有两个候选代表实质不同的结构边界时最多比较两个；
3. 先读选中资产 README，确认适用、依赖和缺失，再读 `source/`；
4. 不浏览完整资源库后选择最容易复制的一项；
5. 参考只证明一种组合如何工作，不能证明当前项目应该采用它；
6. 使用前按 [`adaptation-checklist.md`](./adaptation-checklist.md) 完成项目化转译。

## Chat

| 资产 | 适合解决 | 首要限制 |
|---|---|---|
| [对话记录基础组合](../assets/react-shadcn/base-tailwind-v4/chat/transcript-foundation/README.md) | 自己/对方消息对齐、连续回复分组和基础阅读节奏 | 没有滚动、composer、状态或传输 |
| [流式 Chat 卡片](../assets/react-shadcn/base-tailwind-v4/chat/streaming-chat-card/README.md) | 流式消息、Thinking、Send/Stop、跳到最新的完整表面 | 使用 scripted transport、只读 composer，未显式启用 `autoScroll` |
| [附件对话](../assets/react-shadcn/base-tailwind-v4/chat/attachment-conversation/README.md) | 图片输入、文本回复和生成文件的消息顺序 | 只展示附件，不实现上传、下载授权和失败恢复 |

选择 Chat 参考时优先复用目标项目已有的 `MessageScroller`、`Message`、`Bubble`、`Marker` 和 `Attachment`。不要手写 `scrollTop`、`ResizeObserver` 或另一套滚动 primitive 来模仿示例。

首版不包含群聊、reasoning、tool call/result、source citation、retry/regenerate 或完整 PromptInput；当前 Base `preview-03` 只是空占位，不作为资源。

## 业务场景

| 资产 | 适合解决 | 首要限制 |
|---|---|---|
| [双栏登录页](../assets/react-shadcn/base-tailwind-v4/business/login-two-column/README.md) | 桌面辅助视觉区与窄屏单栏认证入口 | 没有真实认证，包含品牌、商标、空链接和宿主资源 |
| [发票摘要](../assets/react-shadcn/base-tailwind-v4/business/invoice/README.md) | 明细、金额汇总、状态和后续操作 | 金额、税务、币种和支付均为演示 |
| [配送地址表单](../assets/react-shadcn/base-tailwind-v4/business/shipping-address/README.md) | 结构化地址、字段分组和地区选择 | 固定美国地址模型，没有提交和校验 |
| [团队邀请](../assets/react-shadcn/base-tailwind-v4/business/invite-team/README.md) | 多成员邮箱、角色和邀请链接 | Add/Copy/Send 均没有行为 |
| [通知偏好](../assets/react-shadcn/base-tailwind-v4/business/notification-settings/README.md) | 全选、部分选中和逐项偏好 | 只有本地 state，没有持久化 |
| [分类 FAQ](../assets/react-shadcn/base-tailwind-v4/business/faq/README.md) | 少量分类帮助内容与支持入口 | 含未经验证的安全、监管、供应商和商业声明 |

外观相似不等于任务相同。Card、Table、Tabs、Accordion 或表单控件不能代替用户任务、信息层级和操作主次。

## Chart

| 资产 | 适合解决 | 首要限制 |
|---|---|---|
| [折线趋势卡片](../assets/react-shadcn/base-tailwind-v4/chart/line-trend/README.md) | 一个或两个指标随时间变化 | 依赖现有 Chart/Recharts，数据和结论全是演示 |

只有真实任务需要比较时间趋势时才读取 Chart。表单、设置、审批队列、普通表格或“后台页面”不自动需要统计卡和图表。首版不包含 bar、pie、area、radar、radial 或完整 Dashboard。

## Loading 与 Markdown

| 资产 | 适合解决 | 首要限制 |
|---|---|---|
| [区域加载反馈](../assets/react-shadcn/base-tailwind-v4/loading/README.md) | 内容区域等待时的状态文字和装饰动画 | `overlay` 阻挡覆盖区域指针但不是模态框，父容器负责尺寸和 App Shell 边界 |
| [Markdown 阅读](../assets/react-shadcn/base-tailwind-v4/markdown/README.md) | Markdown/GFM 排版、Prism 高亮、行号、代码复制和长行换行 | 依赖解析、高亮与 `next-themes` |

两项均按目标项目已有组件、`cn` 和语义 token 适配。选择参考本身不授权安装依赖；明确实现或调试任务可按项目包管理器安装必要合理依赖并同步 lockfile，不得为避免依赖删减要求功能。隔离宿主中的构建和浏览器验证不代表目标产品已经完成接入。
