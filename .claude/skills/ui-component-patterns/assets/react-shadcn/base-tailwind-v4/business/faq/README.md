# 分类 FAQ

## 用途与身份

这是 Tabs + Accordion FAQ 卡片参考，用于组织少量分类帮助内容和支持入口。

## 适用

- 问题可以稳定分为少量类别；
- 每类内容规模适合 Accordion 扫描；
- 需要在自助内容后提供支持入口。

## 不适用

- 问题很少，不需要 Tabs；
- 内容规模需要搜索、深链、独立文档或知识库导航；
- 产品事实和合规声明尚未确认。

## 依赖和 Base UI API

依赖 `accordion`、`tabs`、`card`、`button`。Base Accordion 使用数组 `defaultValue={[0]}` 和数字 item value，不使用 Radix 的 `type="single"`；TabsTrigger 必须位于 TabsList 内。

## 必须替换

- Ledger、Plaid、MX、套餐、试用和导航路径；
- AES-256、SOC 2 Type II、SEC registered 等安全与监管声明；
- Contact Support、Learn More 的真实链接和行为；
- 类别数量、默认展开、深链和移动端布局。

## 已知缺失与非目标

没有搜索、路由深链、内容管理、分析、真实支持入口或产品事实验证。

## 本地文件

[`source/faq.tsx`](./source/faq.tsx)。
