# 团队邀请

## 用途与身份

这是邀请卡片参考，用于组织多成员输入、角色选择、邀请链接和主要提交操作。

## 适用

- 邀请成员、协作者或访客进入工作区；
- 每个受邀对象需要独立角色或权限级别；
- 目标项目具备 Base UI Select、InputGroup 和 Field。

## 不适用

- 权限模型尚未定义；
- 只有单个邮箱输入，或邀请必须经过审批、域限制等不同流程。

## 依赖和 Base UI API

依赖 `button`、`card`、`field`、`input`、`input-group`、`select`、`separator`。Base Select 使用 `items` 和 `alignItemWithTrigger={false}`；邀请链接使用 `InputGroupInput` 与 inline-end addon。

## 必须替换

- 固定邮箱、角色、邀请链接和 `IconPlaceholder`；
- Add another、Copy、Send Invites 的真实行为和反馈；
- 动态增删、标签、Email 校验、重复项和逐行错误；
- 权限、邀请过期、限额和服务端失败。

## 已知缺失与非目标

按钮均无行为，没有动态 Field 数组、剪贴板、邀请 API、loading、成功或恢复状态。

## 本地文件

[`source/invite-team.tsx`](./source/invite-team.tsx)。
