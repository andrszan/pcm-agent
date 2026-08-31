# 对话记录基础组合

## 用途与身份

这是从 shadcn/ui Base UI `message-example` 中提取的消息对齐、气泡分组和纵向节奏参考。它是派生摘录，不是独立 registry item，也不包含滚动、输入、传输或持久化。

## 适用

- 用户与助手、客服或协作者之间的连续消息记录；
- 需要区分自己和对方消息，并表达连续回复分组；
- 目标项目已经具备 `Message` 和 `Bubble` primitives。

## 不适用

- 需要流式跟随、跳到最新、历史加载或 composer 的完整 Chat；
- 只是单条通知、活动日志或普通评论列表。

## 来源与提取方式

- 仓库：`https://github.com/shadcn-ui/ui`
- Commit：`b4a618b97e35f5dadf3a00d51f410c84a2567d4d`
- 路径：`apps/v4/registry/bases/base/examples/message-example.tsx`
- 范围：`MessageDefault`，上游约第 170–213 行
- 类型：`example-internal-function`
- 模式：派生摘录；移除 `Example` 展示壳和无关 imports，将函数导出。

## 依赖和 Base UI API

依赖目标项目已有的 `message`、`bubble` registry components。该片段本身不直接调用 Base UI widget，但其 primitives 属于 Base UI 版本，不能换成 Radix 版本后假设 API 等价。

## 必须替换

- 部署玩笑文案和角色语义；
- `max-w-md`、`gap-10` 与 Bubble variant；
- 消息分组、对齐和内容宽度应由真实角色与阅读任务决定。

## 已知缺失与非目标

不包含头像、时间、发送状态、错误、附件、滚动、虚拟化、流式状态、键盘路径或消息操作。

## 许可边界和本地文件

代码来源受 [`../../LICENSE.md`](../../LICENSE.md) 的 MIT License 约束。演示文案不构成产品内容事实。本地文件：[`source/message-default.tsx`](./source/message-default.tsx)。
