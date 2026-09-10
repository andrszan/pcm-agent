# ui-ux-framework

`ui-ux-framework` 用于建立或演进跨需求稳定的产品表面、信息架构、App Shell Contract、导航、页面模式、滚动与 sticky 规则、共享视觉语义、响应式和可访问性基线；也支持设计或开发时只查阅布局参考。

它不接管单需求设计、前端实现或开发后验收。完整职责与执行规则见 [`SKILL.md`](./SKILL.md)。

## 目录

```text
ui-ux-framework/
├── SKILL.md
├── README.md
├── references/
│   ├── layout-selection-guide.md
│   ├── app-shell-contract.md
│   └── layout-resource-library.md
├── assets/layout-source-snapshots/shadcn-ui/
│   ├── summary-to-record-workbench/
│   ├── context-switching-navigation-shell/
│   ├── mode-rail-collection-workbench/
│   └── sectioned-preferences-dialog/
└── evals/evals.json
```

- [`references/layout-selection-guide.md`](./references/layout-selection-guide.md)：区分 Shell、页面模式与滚动模型，按项目事实比较布局方向。
- [`references/app-shell-contract.md`](./references/app-shell-contract.md)：区域图、滚动所有者、sticky 基准、响应式转换和 Current/Target 合同。
- [`references/layout-resource-library.md`](./references/layout-resource-library.md)：资源索引、选择与复用、源码及纯图片资源的唯一权威维护规则。
- `assets/layout-source-snapshots/`：带实际预览的部分框架源码快照，保留上游依赖与许可，不保证独立运行；符合许可与技术兼容条件的适用代码可以复用。
- `evals/evals.json`：职责边界、参考选择和资源查阅行为的验证用例。

## 使用方式

可以显式调用 `/ui-ux-framework`，也可以由 Agent 根据任务主动调用：

- **建立或演进框架**：提供项目范围、产品资料、现有设计或框架问题；依据真实事实形成适用设计合同，只有真正高影响的取舍才需要确认。
- **仅查阅资源**：提供当前设计或开发问题、已有框架决定和技术事实；比较少量候选预览，再深入选中源码，说明可借鉴部分和局限后结束。不要求创建或更新框架文档，不重做已确定的 Shell，不接管代码实现。

按实际技术栈优先选择兼容参考；React + shadcn/ui 项目优先考察本地 shadcn/ui 资源，但仍需核对组件 API、版本和依赖。允许合理复用布局与响应式代码，不为原创强制重写，也不将已有模板作为设计上限。真实业务、路由、权限、状态、品牌和 token 必须按项目接入，后续实现仍需验证。

## 长期维护资产

源码快照的 provider 保留 README 与许可；每个语义目录保留 README、`source/` 和实际存在的预览。记录来源、依赖、局限和许可，未知信息不推断，不承诺部分快照独立运行。

纯图片参考可以独立于代码收录，以成熟产品截图为主、生成概念图为补充；当前尚未收录独立纯图片资源。来源、授权、视口、用途、概念标识及索引维护规则统一见 [`layout-resource-library.md`](./references/layout-resource-library.md)，不预建空目录或批量图库。
