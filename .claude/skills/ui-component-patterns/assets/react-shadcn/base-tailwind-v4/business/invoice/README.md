# 发票摘要

## 用途与身份

这是发票卡片参考，用于组织状态、明细表、金额汇总和主次操作。

## 适用

- 账单、订单、报价或费用记录需要同时展示明细和汇总；
- 用户需要下载、支付或进入后续处理；
- 目标项目已经具备 Card、Table、Badge 和 Button。

## 不适用

- 只展示单个金额或简单状态；
- 金融规则、币种和税务尚未确定，却准备直接沿用示例计算。

## 依赖和 Base UI API

依赖 `badge`、`button`、`card`、`table` 和标准库 `Intl.NumberFormat`。该组合没有直接使用 Base UI primitive API，但必须使用目标项目自己的 Base UI shadcn components。

## 必须替换

- invoice 编号、到期日期、商品、数量、价格、状态和币种；
- `en-US`、`USD`、零税额与浮点金额计算；
- Download PDF、Pay Now 的权限、loading、失败和实际行为；
- 窄屏表格呈现、金额精度和本地化。

## 已知缺失与非目标

没有真实账单模型、税务、支付、PDF、权限、错误、退款或财务精度合同。

## 本地文件

[`source/invoice.tsx`](./source/invoice.tsx)。
