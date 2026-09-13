# shadcn/ui Layout Source Snapshots

这里保存 shadcn/ui Block-derived installed-output snapshots，用于比较布局预览、查阅实现细节，并在技术兼容且任务适配时复用代码。它们不是字节级绑定某个固定 commit 的官方快照，不是可独立使用的模板、生产组件库，也不代表项目默认技术选型。

## 使用规则

选择与复用统一遵循 [`layout-resource-library.md`](../../../references/layout-resource-library.md)：先依据真实任务和已有框架决定筛选少量候选，读 README、看预览比较，再深入选中源码，不一次加载四套源码。

React + shadcn/ui 项目可优先考察本目录，但仍须核对组件版本、Base UI／Radix、路由、Tailwind 与依赖。允许合理复用布局结构、组件组合和响应式实现，尺寸与断点按实际内容和视口验证，不一概禁止保留；接入项目自己的组件、token、业务、权限和状态，不照搬品牌、fixture、占位交互或 demo logic，不为原创强制重写。

仅查阅时说明适用部分和局限后结束，不重做既定框架或要求写文档。预览不证明交互或响应式成立，后续实现仍需在目标项目真实验证。

## 完整性边界

随附内容缺少 `package.json`、`components.json`、路径 aliases、base UI 组件、hooks、global CSS 和完整宿主配置，因此任何一套都不可独立编译或运行。`source/components/theme-provider.tsx` 在四套中均保留，但未被随附 Block 源码引用；它属于捕获宿主代码，不是官方 registry manifest 的必需文件。

以下技术版本与捕获信息未随素材提供，不推断：

- shadcn CLI 版本；
- upstream commit；
- 精确安装命令；
- 导入前修改；
- 截图捕获信息，包括 URL、构建、浏览器、主题切换方式和操作路径。

## 快照映射与首要决策

| 本地目录 | shadcn/ui Block ID | 原素材目录 | 决策问题 | 首要局限 |
| --- | --- | --- | --- | --- |
| [`summary-to-record-workbench/`](summary-to-record-workbench/) | `dashboard-01` | `dashboard-01` | 用户是否需要在同一工作台先扫摘要与趋势，再处理记录并打开单条详情？ | 依赖面广，表头 sticky 与页面滚动高度合同未闭合，且多处交互只是演示占位。 |
| [`context-switching-navigation-shell/`](context-switching-navigation-shell/) | `sidebar-07` | `sidebar-07` | 用户是否需要频繁切换上下文，并在分层模块与 Projects 之间导航？ | 主内容是占位；移动 Drawer、焦点与滚动行为依赖未随附的 Sidebar base。 |
| [`mode-rail-collection-workbench/`](mode-rail-collection-workbench/) | `sidebar-09` | `sidebar-09` | 任务是否确实存在“模式—集合—内容”三层关系，并能为窄屏定义进入与返回？ | 它不是真正 list-detail，状态带随机和原地排序，移动端直接隐藏集合列。 |
| [`sectioned-preferences-dialog/`](sectioned-preferences-dialog/) | `sidebar-13` | `sidebar-13` | 设置任务是否中短、可中断，并适合在保留原页面上下文的模态子系统中完成？ | 分类、面包屑和内容未联动；移动端隐藏分类，关键模态行为依赖未随附的 Dialog base。 |

四套均未附 CLI 版本、upstream commit、精确安装命令、导入前修改和截图捕获信息，仅有 `3840 × 1984` desktop preview，未提供 mobile preview。

## 官方当前参考

以下 URL 用于当前人工技术核对，不标定本地文件对应的固定 upstream commit：

- Blocks：<https://ui.shadcn.com/blocks>

| Block ID | Preview | Registry JSON | GitHub source |
| --- | --- | --- | --- |
| `dashboard-01` | <https://ui.shadcn.com/view/new-york-v4/dashboard-01> | <https://ui.shadcn.com/r/styles/new-york-v4/dashboard-01.json> | <https://github.com/shadcn-ui/ui/tree/main/apps/v4/registry/new-york-v4/blocks/dashboard-01> |
| `sidebar-07` | <https://ui.shadcn.com/view/new-york-v4/sidebar-07> | <https://ui.shadcn.com/r/styles/new-york-v4/sidebar-07.json> | <https://github.com/shadcn-ui/ui/tree/main/apps/v4/registry/new-york-v4/blocks/sidebar-07> |
| `sidebar-09` | <https://ui.shadcn.com/view/new-york-v4/sidebar-09> | <https://ui.shadcn.com/r/styles/new-york-v4/sidebar-09.json> | <https://github.com/shadcn-ui/ui/tree/main/apps/v4/registry/new-york-v4/blocks/sidebar-09> |
| `sidebar-13` | <https://ui.shadcn.com/view/new-york-v4/sidebar-13> | <https://ui.shadcn.com/r/styles/new-york-v4/sidebar-13.json> | <https://github.com/shadcn-ui/ui/tree/main/apps/v4/registry/new-york-v4/blocks/sidebar-13> |
