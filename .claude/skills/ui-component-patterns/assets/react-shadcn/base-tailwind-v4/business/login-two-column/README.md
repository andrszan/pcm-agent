# 双栏登录页

## 用途与身份

这是桌面双栏、窄屏单栏和居中认证表单的页面构图参考，不包含完整认证流程，也不承诺独立运行。

## 适用

- 认证入口需要比单个居中 Card 更完整的品牌或内容表面；
- 桌面可使用辅助视觉区域，窄屏应保持单列；
- 目标项目已经具备 Base UI `Field`、`Input` 和 `Button`。

## 不适用

- 产品不需要品牌辅助区域，或登录主要发生在 Dialog/Sheet；
- 当前任务需要 SSO、MFA、Magic Link、Passkey 等不同认证流程，但尚未设计。

## 依赖和 Base UI API

Registry dependencies：`button`、`input`、`label`、`field`。表单使用 `FieldGroup → Field → FieldLabel/Input` 和 `FieldSeparator`；没有 Radix `asChild`。

## 必须替换

- `Acme Inc.`、`IconPlaceholder`、GitHub mark 与登录提供商；
- `href="#"`、占位邮箱、标题、帮助文案和泛化 `alt="Image"`；
- `/placeholder.svg` 宿主资源，需使用目标项目有明确价值且已固化的媒体，或删除辅助视觉区；
- 提交、校验、错误、恢复、loading、CSRF、密码重置和注册路径。

## 已知缺失与非目标

源码没有真实认证、错误反馈、会话、权限、MFA、第三方 OAuth 或浏览器验收。小屏直接隐藏视觉列，是否合适需按产品任务判断。

## 本地文件

[`source/page.tsx`](./source/page.tsx)、[`source/components/login-form.tsx`](./source/components/login-form.tsx)。
