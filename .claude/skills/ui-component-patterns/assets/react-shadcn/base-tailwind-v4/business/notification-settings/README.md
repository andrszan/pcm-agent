# 通知偏好

## 用途与身份

这是通知设置卡片参考，用于组织分组偏好、全选和 mixed 状态。

## 适用

- 用户可以选择多种通知、订阅或同步事件；
- 需要全选、部分选中和逐项说明；
- 目标项目使用 Base UI Checkbox。

## 不适用

- 安全通知必须强制开启，或不同频道/频率需要更复杂的矩阵；
- 只有一个布尔开关。

## 依赖和 Base UI API

依赖 React state、`button`、`card`、`checkbox`、`field`。Base Checkbox 的 mixed 状态使用独立的 `indeterminate={someChecked}`，不能改成 Radix 风格的 checked 字符串。

## 必须替换

- 金融通知分类、默认值和描述；
- 本地 state 与 Save Preferences 空操作；
- 服务端读取、持久化、loading、失败、成功和权限；
- 强制通知、频道、频率和依赖关系。

## 已知缺失与非目标

没有持久化、异步状态、服务器同步、冲突恢复或强制项规则。

## 本地文件

[`source/notification-settings.tsx`](./source/notification-settings.tsx)。
