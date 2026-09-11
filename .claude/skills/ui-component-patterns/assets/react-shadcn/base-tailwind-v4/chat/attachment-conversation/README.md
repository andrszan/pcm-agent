# 附件对话

## 用途与身份

这是图片输入、文本回复和文件结果组合参考，不包含上传、文件存储或下载实现。

## 适用

- 用户向 Chat 提交图片或文件，系统返回文本和生成文件；
- 需要在同一消息中组织 Bubble 与 Attachment；
- 目标项目已经具备 `message`、`bubble` 和 `attachment` primitives。

## 不适用

- 只需要普通文件上传控件；
- 需要多附件横向组、上传进度、删除、重试或文件权限，而当前范围尚未设计这些行为。

## 依赖和 Base UI API

依赖 `message`、`bubble`、`attachment` 和 Button action。`Attachment` 的 `state`、media、content 和 action 由外部业务状态驱动；本片段没有直接实现上传状态机。

## 必须替换

- Unsplash 远程图片、文件名、大小和 PDF 文案；
- `IconPlaceholder`、下载 URL 与点击行为；
- 文件来源、生命周期、权限、失败和恢复；
- 图片必须固化为目标项目的稳定资源，不能保留临时第三方 URL。

## 已知缺失与非目标

没有文件选择、上传、进度、取消、删除、失败重试、病毒检查、下载授权或 AI SDK `FileUIPart` 映射。

## 本地文件

[`source/message-attachment.tsx`](./source/message-attachment.tsx)。
