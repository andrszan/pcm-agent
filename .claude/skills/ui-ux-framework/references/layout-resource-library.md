# 布局参考资源库

本文件是 `ui-ux-framework` 布局资源的索引与维护规则。当前随附 `assets/layout-source-snapshots/` 中的部分框架源码快照和桌面预览；它们带有上游依赖与许可，不保证独立运行，也不代表项目默认布局或技术选型。

## 1. 选择与复用

1. 先依据用户任务、产品表面、入口层级、信息密度、设备和已有框架决定筛选候选；需要区分 Shell、页面模式与滚动模型时读取 [`layout-selection-guide.md`](./layout-selection-guide.md)。不要因已有某个模板而反推产品需求。
2. 优先选择与实际技术栈兼容的成熟参考。React + shadcn/ui 项目优先考察下列 shadcn/ui 资源，但须核对组件版本、Base UI／Radix、路由、Tailwind 和依赖。没有合适资源时依据项目事实设计，不强套现有集合，也不擅自安装依赖。
3. 先读 provider 与候选 README，查看少量相关预览，比较区域比例、任务层级、内容密度和窄屏材料；让视觉参考参与方向选择，再深入选中源码。不要全量加载源码，也不为形式凑候选。
4. 允许复用许可明确、技术兼容且适合目标任务的布局结构、组件组合和响应式代码，并保留适用许可声明。优先接入项目已有组件、token、路由、权限与状态；尺寸和断点按真实内容和目标视口核验，可保留合适值，不要求为了原创重新实现。
5. 不照搬不适用的导航、品牌、fixture、占位内容、假链接或 demo logic。来源或许可不明的文件不作为可复用代码；源码许可不自动覆盖商标、远程媒体和第三方截图。
6. 框架设计借助 [`App Shell 区域示例`](./app-shell-contract.md) 说明项目自己的区域、导航、滚动、sticky 和窄屏变化，不要求逐表填写。仅查阅资源时沿用已有决定，说明可借鉴部分和局限后结束，不重做框架。
7. 示例未闭合的路由跳转、当前项高亮、侧栏展开收缩、sticky 和响应式行为，由实现方按项目实际补齐并验证。预览不证明交互成立，局部源码不证明业务行为已经完成；参考查阅不代替交付验收。

关键决定无论保留还是改变，都应有项目事实依据；业务项目化不等于每行布局代码必须原创。

## 2. shadcn/ui 布局源码快照

Provider 路径：[`../assets/layout-source-snapshots/shadcn-ui/`](../assets/layout-source-snapshots/shadcn-ui/)

这些 Block-derived installed-output snapshots 带有 React、Tailwind CSS、shadcn/ui 及相关生态依赖痕迹，缺少完整宿主配置，不能独立编译或运行。它们可用于理解结构与交互，并在满足上述许可和兼容条件时复用适用代码。

| 语义目录 | shadcn/ui Block ID | 主要决策问题 | 关键局限 |
| --- | --- | --- | --- |
| [`summary-to-record-workbench/`](../assets/layout-source-snapshots/shadcn-ui/summary-to-record-workbench/) | `dashboard-01` | 用户是否需要在同一工作台先扫摘要与趋势，再处理记录并打开单条详情？ | 依赖面广，表头 sticky 与页面滚动高度合同未闭合，多处交互只是演示占位。 |
| [`context-switching-navigation-shell/`](../assets/layout-source-snapshots/shadcn-ui/context-switching-navigation-shell/) | `sidebar-07` | 用户是否需要频繁切换上下文，并在分层模块与 Projects 之间导航？ | 主内容是占位；移动 Drawer、焦点与滚动依赖未随附的 Sidebar base。 |
| [`mode-rail-collection-workbench/`](../assets/layout-source-snapshots/shadcn-ui/mode-rail-collection-workbench/) | `sidebar-09` | 任务是否确实存在“模式—集合—内容”三层关系，并能为窄屏定义进入与返回？ | 不是真正的 list-detail，状态带随机和原地排序，移动端直接隐藏集合列。 |
| [`sectioned-preferences-dialog/`](../assets/layout-source-snapshots/shadcn-ui/sectioned-preferences-dialog/) | `sidebar-13` | 设置任务是否中短、可中断，并适合在保留原页面上下文的模态子系统中完成？ | 分类、面包屑和内容未联动；移动端隐藏分类，关键行为依赖未随附的 Dialog base。 |

四套快照的来源信息均不完整，只有实际随附的桌面预览，没有移动端预览；预览不作为目标项目需求或视觉验收基线。具体依赖、来源边界和许可见 provider 与对应资源 README。

## 3. 源码资源维护

```text
assets/layout-source-snapshots/<provider>/
├── README.md
├── LICENSE.md
└── <semantic-name>/
    ├── README.md
    ├── source/
    └── <实际存在的预览文件>
```

- 优先补充当前真实任务缺少的结构或成熟实现，不为假设中的技术栈预建资源，也不只因颜色、行业或组件库不同重复收录相同布局。
- Provider README 说明来源、共同依赖、许可边界和映射；子 README 说明适用任务、结构、关键局限、源码与预览。
- 保持已知来源映射和源码相对结构，整理后的语义目录不冒充官方原始目录。新收录时记录可核验的版本或 commit；既有未知信息不补造。
- 明确完整模板与部分快照的区别。部分快照不要求独立构建，不伪造未提供的移动端预览、交互验证或来源记录。
- 变更后更新本索引，核对相对链接、许可和源码／预览对应关系；只在行为边界变化时更新 Skill 和 eval。

## 4. 预览用途

现有源码附带的预览用于理解区域比例、信息层级和审美方向，不要求另建图片库或为每种布局补充资产。优先利用现有参考，由 Agent 按项目选择、组合和完善；具体页面美化留给实际设计与开发。

如调用方提供额外图片，只作为视觉参考并遵守其来源与使用边界；生成图不能冒充真实产品或交互验证。
