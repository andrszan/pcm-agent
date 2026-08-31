# 附件对话

## 用途与身份

这是从 shadcn/ui Base UI `message-example` 提取的图片输入、文本回复和文件结果组合。它是附件展示与消息顺序参考，不是上传、文件存储或下载实现。

## 适用

- 用户向 Chat 提交图片或文件，系统返回文本和生成文件；
- 需要在同一消息中组织 Bubble 与 Attachment；
- 目标项目已经具备 `message`、`bubble` 和 `attachment` primitives。

## 不适用

- 只需要普通文件上传控件；
- 需要多附件横向组、上传进度、删除、重试或文件权限，而当前范围尚未设计这些行为。

## 来源与提取方式

- 仓库：`https://github.com/shadcn-ui/ui`
- Commit：`b4a618b97e35f5dadf3a00d51f410c84a2567d4d`
- 路径：`apps/v4/registry/bases/base/examples/message-example.tsx`
- 范围：`MessageAttachment`，上游约第 595–669 行
- 类型：`example-internal-function`
- 模式：派生摘录；移除 `Example` 展示壳和无关 imports，将函数导出。

## 依赖和 Base UI API

依赖 `message`、`bubble`、`attachment` 和 Button action。`Attachment` 的 `state`、media、content 和 action 由外部业务状态驱动；本片段没有直接实现上传状态机。

## 必须替换

- Unsplash 远程图片、文件名、大小和 PDF 文案；
- `IconPlaceholder`、下载 URL 与点击行为；
- 文件来源、生命周期、权限、失败和恢复；
- 图片必须固化为目标项目有权使用的稳定资源，不能保留临时第三方 URL。

## 已知缺失与非目标

没有文件选择、上传、进度、取消、删除、失败重试、病毒检查、下载授权或 AI SDK `FileUIPart` 映射。

## 许可边界和本地文件

代码来源受 [`../../LICENSE.md`](../../LICENSE.md) 的 MIT License 约束；示例引用的 Unsplash 图片不由该 MIT License 自动覆盖。本地文件：[`source/message-attachment.tsx`](./source/message-attachment.tsx)。
