# 通知偏好

## 用途与身份

这是 shadcn/ui Base UI `preview-02` block 内部的通知设置卡片原样源码，不是独立 registry item。它用于参考分组偏好、全选和 mixed 状态。

## 适用

- 用户可以选择多种通知、订阅或同步事件；
- 需要全选、部分选中和逐项说明；
- 目标项目使用 Base UI Checkbox。

## 不适用

- 安全通知必须强制开启，或不同频道/频率需要更复杂的矩阵；
- 只有一个布尔开关。

## 来源与提取方式

- 仓库：`https://github.com/shadcn-ui/ui`
- Commit：`b4a618b97e35f5dadf3a00d51f410c84a2567d4d`
- 路径：`apps/v4/registry/bases/base/blocks/preview-02/cards/notification-settings.tsx`
- 类型：`preview-internal-module`
- 模式：完整文件原样保存。

## 依赖和 Base UI API

依赖 React state、`button`、`card`、`checkbox`、`field`。Base Checkbox 的 mixed 状态使用独立的 `indeterminate={someChecked}`，不能改成 Radix 风格的 checked 字符串。

## 必须替换

- 金融通知分类、默认值和描述；
- 本地 state 与 Save Preferences 空操作；
- 服务端读取、持久化、loading、失败、成功和权限；
- 强制通知、频道、频率和依赖关系。

## 已知缺失与非目标

没有持久化、异步状态、服务器同步、冲突恢复或强制项规则。

## 许可边界和本地文件

代码来源受 [`../../LICENSE.md`](../../LICENSE.md) 的 MIT License 约束。演示通知类别不是产品事实。本地文件：[`source/notification-settings.tsx`](./source/notification-settings.tsx)。
