# 配送地址表单

## 用途与身份

这是结构化地址卡片参考，用于组织字段分组、双列组合、Select 和默认地址选择。

## 适用

- 创建或编辑结构化地址；
- 需要把街道、城市、地区、邮编和国家组织成清晰表单；
- 目标项目使用 Base UI Select 与 Field。

## 不适用

- 地址规则尚未确定却准备把美国字段模型当成全球通用；
- 只需要一行自由文本地址或地址搜索服务。

## 依赖和 Base UI API

依赖 `button`、`card`、`checkbox`、`field`、`input`、`select`。Base Select 使用 `items`、`defaultValue`、`SelectValue` 和 `SelectContent → SelectGroup → SelectItem`；Checkbox 通过水平 Field 与 Label 关联。

## 必须替换

- 美国 State/ZIP 模型、静态州和国家选项、默认 CA/US；
- 地址 schema、字段 name、autocomplete、校验、错误和国际化；
- Save/Cancel 行为和服务端提交；
- 双列布局在目标容器和窄屏中的转换。

## 已知缺失与非目标

没有 `<form>`、提交、验证、地址补全、地区联动、失败恢复或真实国际地址支持。

## 本地文件

[`source/shipping-address.tsx`](./source/shipping-address.tsx)。
