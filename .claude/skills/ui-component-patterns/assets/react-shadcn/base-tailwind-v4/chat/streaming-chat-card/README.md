# 流式 Chat 卡片

## 用途与身份

这是脚本化流式 Chat 场景参考，覆盖 transcript、Thinking、Send/Stop 和跳到最新的组合，不包含生产 transport 或可直接安装的 Chat 套件。

## 适用

- AI 助手、客服或生成式任务需要流式回复；
- 需要明确 transcript、composer、发送中状态和中止入口；
- 目标项目已经具备 Base UI Chat primitives 和自己的传输协议。

## 不适用

- 普通评论、非流式消息或只读历史记录；
- 目标项目没有 AI SDK 或等价流式协议，且当前范围不允许引入；
- 需要 tool、reasoning、source、retry 或附件的完整多部件协议。

## 依赖和 Base UI API

示例依赖 `@ai-sdk/react`、宿主 `@/lib/ai` helper，以及 `message-scroller`、`message`、`bubble`、`marker`、`spinner`、`card`、`input-group`。`MessageScroller` 行为来自 `@shadcn/react/message-scroller`，不是手写滚动容器。

## 必须替换

- scripted `createChat` transport、预置消息和只读 composer；
- 固定 `h-140`、状态标题和产品文案；
- `IconPlaceholder` 与上游 aliases；
- AI SDK 状态到产品状态的映射；
- 是否启用 `autoScroll`、turn anchor 和用户上滚后的跟随策略。

## 已知缺失与非目标

示例没有生产服务端、可编辑输入、附件、错误/重试、停止后的反馈、消息持久化或多部件渲染；`MessageScrollerProvider` 也没有显式启用 `autoScroll`。

## 本地文件

[`source/message-scroller-demo.tsx`](./source/message-scroller-demo.tsx)。
