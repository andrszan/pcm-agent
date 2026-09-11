# 折线趋势卡片

## 用途与身份

这是双序列折线趋势参考，只服务真实时间趋势或序列变化任务，不是 Dashboard 默认装饰。

## 适用

- 用户需要观察一段时间内一个或两个指标的变化；
- 目标项目已经安装 shadcn Chart primitive 与兼容的 Recharts；
- 图表能帮助判断或采取下一步行动，而不是补空白。

## 不适用

- 表单、设置、审批队列或普通数据表没有趋势判断需求；
- 分类对比、构成、分布或单值 KPI；
- 当前项目没有图表依赖且任务不允许安装。

## 依赖和 Base UI API

依赖目标项目已有的 `chart`、`card` 和兼容 Recharts 3.8.0。颜色通过 `ChartContainer` 将 `--chart-*` token 映射为 `--color-*`。

## 必须替换

- visitor fixture、月份、series 名称、`5.2%` 和时间范围；
- 图表标题、辅助结论和行动语义；
- `IconPlaceholder` 与目标图标库；
- 根据真实数据决定单线或双线、缺失值、时间格式和 tooltip 内容。

## 已知缺失与非目标

不包含数据加载、空态、失败、时区、大数据降采样、筛选或实时更新；不提供 bar、pie、area、radar、radial 或完整 Dashboard。

## 本地文件

[`source/chart-line-example.tsx`](./source/chart-line-example.tsx)。
