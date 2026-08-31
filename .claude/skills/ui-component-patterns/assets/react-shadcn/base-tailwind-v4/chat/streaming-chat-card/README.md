# 流式 Chat 卡片

## 用途与身份

这是从 shadcn/ui Base UI `message-scroller-example` 提取的脚本化流式 Chat 场景，覆盖 transcript、Thinking、Send/Stop 和跳到最新的组合。它是派生示例，不是生产 transport 或可直接安装的 Chat 套件。

## 适用

- AI 助手、客服或生成式任务需要流式回复；
- 需要明确 transcript、composer、发送中状态和中止入口；
- 目标项目已经具备 Base UI Chat primitives 和自己的传输协议。

## 不适用

- 普通评论、非流式消息或只读历史记录；
- 目标项目没有 AI SDK 或等价流式协议，且当前范围不允许引入；
- 需要 tool、reasoning、source、retry 或附件的完整多部件协议。

## 来源与提取方式

- 仓库：`https://github.com/shadcn-ui/ui`
- Commit：`b4a618b97e35f5dadf3a00d51f410c84a2567d4d`
- 路径：`apps/v4/registry/bases/base/examples/message-scroller-example.tsx`
- 范围：脚本 fixture 及 `MessageScrollerDemo`，上游约第 51–252 行
- 类型：`example-internal-function`
- 模式：派生摘录；移除 gallery wrapper 和无关 imports，将函数导出。

## 依赖和 Base UI API

上游示例依赖 `@ai-sdk/react`、宿主 `@/lib/ai` helper，以及 `message-scroller`、`message`、`bubble`、`marker`、`spinner`、`card`、`input-group`。`MessageScroller` 行为来自 `@shadcn/react/message-scroller`，不是手写滚动容器。

## 必须替换

- scripted `createChat` transport、预置消息和只读 composer；
- 固定 `h-140`、状态标题和产品文案；
- `IconPlaceholder` 与上游 aliases；
- AI SDK 状态到产品状态的映射；
- 是否启用 `autoScroll`、turn anchor 和用户上滚后的跟随策略。

## 已知缺失与非目标

示例没有生产服务端、可编辑输入、附件、错误/重试、停止后的反馈、消息持久化或多部件渲染；`MessageScrollerProvider` 也没有显式启用 `autoScroll`。

## 许可边界和本地文件

代码来源受 [`../../LICENSE.md`](../../LICENSE.md) 的 MIT License 约束。AI SDK canary 与宿主 helper 只是上游演示依赖，本 Skill 不负责安装。本地文件：[`source/message-scroller-demo.tsx`](./source/message-scroller-demo.tsx)。
