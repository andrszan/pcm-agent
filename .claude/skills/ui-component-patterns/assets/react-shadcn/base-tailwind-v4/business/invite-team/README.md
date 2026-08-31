# 团队邀请

## 用途与身份

这是 shadcn/ui Base UI `preview` block 内部的邀请卡片原样源码，不是独立 registry item。它用于参考多成员输入、角色选择、邀请链接和主要提交操作的组合。

## 适用

- 邀请成员、协作者或访客进入工作区；
- 每个受邀对象需要独立角色或权限级别；
- 目标项目具备 Base UI Select、InputGroup 和 Field。

## 不适用

- 权限模型尚未定义；
- 只有单个邮箱输入，或邀请必须经过审批、域限制等不同流程。

## 来源与提取方式

- 仓库：`https://github.com/shadcn-ui/ui`
- Commit：`b4a618b97e35f5dadf3a00d51f410c84a2567d4d`
- 路径：`apps/v4/registry/bases/base/blocks/preview/cards/invite-team.tsx`
- 类型：`preview-internal-module`
- 模式：完整文件原样保存。

## 依赖和 Base UI API

依赖 `button`、`card`、`field`、`input`、`input-group`、`select`、`separator`。Base Select 使用 `items` 和 `alignItemWithTrigger={false}`；邀请链接使用 `InputGroupInput` 与 inline-end addon。

## 必须替换

- 固定邮箱、角色、邀请链接和 `IconPlaceholder`；
- Add another、Copy、Send Invites 的真实行为和反馈；
- 动态增删、标签、Email 校验、重复项和逐行错误；
- 权限、邀请过期、限额和服务端失败。

## 已知缺失与非目标

按钮均无行为，没有动态 Field 数组、剪贴板、邀请 API、loading、成功或恢复状态。

## 许可边界和本地文件

代码来源受 [`../../LICENSE.md`](../../LICENSE.md) 的 MIT License 约束。示例邮箱和链接必须替换。本地文件：[`source/invite-team.tsx`](./source/invite-team.tsx)。
