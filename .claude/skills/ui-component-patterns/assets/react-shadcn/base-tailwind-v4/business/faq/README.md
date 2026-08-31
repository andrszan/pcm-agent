# 分类 FAQ

## 用途与身份

这是 shadcn/ui Base UI `preview-02` block 内部的 Tabs + Accordion FAQ 卡片原样源码，不是独立 registry item。它用于参考少量分类帮助内容和支持入口的组合。

## 适用

- 问题可以稳定分为少量类别；
- 每类内容规模适合 Accordion 扫描；
- 需要在自助内容后提供支持入口。

## 不适用

- 问题很少，不需要 Tabs；
- 内容规模需要搜索、深链、独立文档或知识库导航；
- 产品事实和合规声明尚未确认。

## 来源与提取方式

- 仓库：`https://github.com/shadcn-ui/ui`
- Commit：`b4a618b97e35f5dadf3a00d51f410c84a2567d4d`
- 路径：`apps/v4/registry/bases/base/blocks/preview-02/cards/faq.tsx`
- 类型：`preview-internal-module`
- 模式：完整文件原样保存，包括内部 `QuestionList`。

## 依赖和 Base UI API

依赖 `accordion`、`tabs`、`card`、`button`。Base Accordion 使用数组 `defaultValue={[0]}` 和数字 item value，不使用 Radix 的 `type="single"`；TabsTrigger 必须位于 TabsList 内。

## 必须替换

- Ledger、Plaid、MX、套餐、试用和导航路径；
- AES-256、SOC 2 Type II、SEC registered 等安全与监管声明；
- Contact Support、Learn More 的真实链接和行为；
- 类别数量、默认展开、深链和移动端布局。

## 已知缺失与非目标

没有搜索、路由深链、内容管理、分析、真实支持入口或产品事实验证。

## 许可边界和本地文件

代码来源受 [`../../LICENSE.md`](../../LICENSE.md) 的 MIT License 约束；MIT 不证明任何安全、供应商、监管或商业声明真实。本地文件：[`source/faq.tsx`](./source/faq.tsx)。
