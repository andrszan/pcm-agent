# shadcn/ui Layout Source Snapshots

这里保存 shadcn/ui Block-derived installed-output snapshots，用于在确定布局方向后查阅具体结构和实现细节。它们不是字节级绑定某个固定 commit 的官方快照，不是可独立使用的模板、生产组件库，也不代表项目默认技术选型。

## 与 `layout-patterns` 的区别

- [`layout-patterns`](../../layout-patterns/) 是技术中立、可独立查看的布局模式参考，重点是区域关系、滚动所有权、响应式转换和交互合同。
- 本目录是带有 shadcn/ui、React、Tailwind CSS 与相关生态依赖痕迹的源码快照，重点是观察某个 Block 的 installed output 如何组织页面和组件。
- 先依据项目事实和 [`layout-selection-guide.md`](../../../references/layout-selection-guide.md) 选择最相关的资源层：需要技术中立运行机制时使用 `layout-patterns`，需要核对第三方实现假设时进入本目录。不得要求先读取另一套资源，也不得因为存在某套源码而替项目选择布局或技术栈。

## 使用规则

每次只读取与当前决策最相关的一套：先读该套 `README.md`，确认决策问题、局限和依赖，再按需读取 `source/`。不要一次加载四套源码，也不要把截图当作需求或视觉验收基线。

项目化转译按以下五个检查点进行：

1. **项目事实**：确认真实用户任务、信息层级、数据规模、目标视口、既有技术栈和约束。
2. **借用原理**：只提取有助于当前问题的布局、滚动、导航、响应式或反馈原理。
3. **项目化表达**：使用目标项目自己的信息架构、组件、品牌、token、内容和状态模型重新实现。
4. **有依据差异**：每个与参考不同或相同的关键决定都应能由项目事实解释，而不是为了随机变化。
5. **真实验证**：在目标项目中验证代表性数据、加载、空态、失败、权限、成功、恢复、窄屏和键盘/焦点行为。

禁止复制后只替换 Logo、颜色或文案。禁止复制 fixture、品牌、token、固定宽度、断点和 demo logic；这不等于要求随机变化，而是要求所有保留或改变都有项目依据。

## 完整性边界

随附内容缺少 `package.json`、`components.json`、路径 aliases、base UI 组件、hooks、global CSS 和完整宿主配置，因此任何一套都不可独立编译或运行。`source/components/theme-provider.tsx` 在四套中均保留，但未被随附 Block 源码引用；它属于捕获宿主代码，不是官方 registry manifest 的必需文件。

以下信息未随素材提供，不推断：

- shadcn CLI 版本；
- upstream commit；
- 精确安装命令；
- 导入前修改；
- 截图的精确 provenance，包括捕获 URL、构建、浏览器、主题切换方式和操作路径。

## 快照映射与首要决策

| 本地目录 | shadcn/ui Block ID | 原素材目录 | 决策问题 | 首要局限 |
| --- | --- | --- | --- | --- |
| [`summary-to-record-workbench/`](summary-to-record-workbench/) | `dashboard-01` | `dashboard-01` | 用户是否需要在同一工作台先扫摘要与趋势，再处理记录并打开单条详情？ | 依赖面广，表头 sticky 与页面滚动高度合同未闭合，且多处交互只是演示占位。 |
| [`context-switching-navigation-shell/`](context-switching-navigation-shell/) | `sidebar-07` | `sidebar-07` | 用户是否需要频繁切换上下文，并在分层模块与 Projects 之间导航？ | 主内容是占位；移动 Drawer、焦点与滚动行为依赖未随附的 Sidebar base。 |
| [`mode-rail-collection-workbench/`](mode-rail-collection-workbench/) | `sidebar-09` | `sidebar-09` | 任务是否确实存在“模式—集合—内容”三层关系，并能为窄屏定义进入与返回？ | 它不是真正 list-detail，状态带随机和原地排序，移动端直接隐藏集合列。 |
| [`sectioned-preferences-dialog/`](sectioned-preferences-dialog/) | `sidebar-13` | `sidebar-13` | 设置任务是否中短、可中断，并适合在保留原页面上下文的模态子系统中完成？ | 分类、面包屑和内容未联动；移动端隐藏分类，关键模态行为依赖未随附的 Dialog base。 |

四套均为 unknown provenance、仅有 `3840 × 1984` desktop preview，未提供 mobile preview。

## 官方当前参考

以下 URL 仅用于当前人工核对，不构成本地文件的 provenance，也不证明本地内容对应某个固定 upstream commit：

- Blocks：<https://ui.shadcn.com/blocks>

| Block ID | Preview | Registry JSON | GitHub source |
| --- | --- | --- | --- |
| `dashboard-01` | <https://ui.shadcn.com/view/new-york-v4/dashboard-01> | <https://ui.shadcn.com/r/styles/new-york-v4/dashboard-01.json> | <https://github.com/shadcn-ui/ui/tree/main/apps/v4/registry/new-york-v4/blocks/dashboard-01> |
| `sidebar-07` | <https://ui.shadcn.com/view/new-york-v4/sidebar-07> | <https://ui.shadcn.com/r/styles/new-york-v4/sidebar-07.json> | <https://github.com/shadcn-ui/ui/tree/main/apps/v4/registry/new-york-v4/blocks/sidebar-07> |
| `sidebar-09` | <https://ui.shadcn.com/view/new-york-v4/sidebar-09> | <https://ui.shadcn.com/r/styles/new-york-v4/sidebar-09.json> | <https://github.com/shadcn-ui/ui/tree/main/apps/v4/registry/new-york-v4/blocks/sidebar-09> |
| `sidebar-13` | <https://ui.shadcn.com/view/new-york-v4/sidebar-13> | <https://ui.shadcn.com/r/styles/new-york-v4/sidebar-13.json> | <https://github.com/shadcn-ui/ui/tree/main/apps/v4/registry/new-york-v4/blocks/sidebar-13> |

## 许可

[`LICENSE.md`](LICENSE.md) 只记录可确认的 shadcn/ui 上游派生部分所适用的 MIT License。四个 `source/components/theme-provider.tsx` 的精确来源和许可未随素材提供，本目录不声称该 MIT License 自动覆盖这些宿主捕获文件；它们仅用于保留用户提供的上下文，在来源澄清前不得作为可复用素材复制。该许可文件不修改、替代或扩展仓库根许可。官方当前 License 参考：<https://github.com/shadcn-ui/ui/blob/main/LICENSE.md>。
