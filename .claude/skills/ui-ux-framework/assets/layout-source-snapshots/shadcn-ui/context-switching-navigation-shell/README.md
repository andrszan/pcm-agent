# Context Switching Navigation Shell

## 快照状态

- Provider：shadcn/ui
- Block ID：`sidebar-07`
- 类型：Block-derived installed-output
- 运行状态：缺少宿主项目与基础依赖，不可独立运行
- Provenance：unknown provenance；CLI 版本、upstream commit、精确安装命令、导入前修改和截图精确 provenance 均未随素材提供，不推断
- 预览：desktop only，`3840 × 1984`；未提供 mobile preview
- 许可边界：shadcn/ui 派生部分见 [`../LICENSE.md`](../LICENSE.md)；`source/components/theme-provider.tsx` 的精确来源与许可未随素材提供

## 决策问题

用户是否会频繁切换团队、账户或工作区上下文，并在当前上下文内使用稳定的分层导航和 Projects？只有当上下文切换会实质改变数据、权限或导航范围时，才应把切换器置于 Shell 的最高层。

## 结构、滚动与响应式

- 侧栏从上到下由 Team switcher、`Platform` 分层导航、`Projects`、用户菜单组成，并通过 `SidebarRail` 支持 icon rail / 收起状态。
- 主内容仅有 breadcrumb、三张占位卡和一块大占位区域，未定义真实页面任务、加载或空态。
- 顶层页面未显式建立独立主内容滚动合同；侧栏滚动、收起、移动 Drawer、焦点恢复和 scroll 管理由未随附的 Sidebar base 决定。
- 分层导航用 Collapsible 展开子项，`Playground` 由 fixture 固定为默认展开；Projects 在 icon 收起状态隐藏。

## 可借鉴原理

- 将“当前上下文”与“当前模块”分开表达：上下文切换器置顶，模块导航保持稳定，避免把团队和页面入口混成同一层级。
- 对有稳定层级的模块使用可展开分组，对跨模块对象使用独立的 Projects 区域，使导航扫描路径清楚。
- icon rail 适合熟练用户节省宽度，但完整标签和工具提示仍应可恢复，不能让图标成为唯一可理解线索。
- 用户菜单放在侧栏底部，可与主任务导航保持视觉和语义分离。

## 项目化差异要求

- 使用真实上下文、权限、路由和项目集合；禁止复制 `Acme`、`Models`、`Projects`、用户资料、品牌 icon 和其它 fixture。
- Team switcher 必须连接目标项目状态、路由或数据刷新；不得复制当前仅在本地 React state 中切换名称和 plan 的行为。
- 快捷键只有在真实注册、可发现且不冲突时才展示；禁止复制菜单中的假 `⌘1`、`⌘2`、`⌘3` 提示。
- 根据真实访问频率决定哪些分组默认展开并持久化状态；禁止复制固定展开 `Playground`。
- 使用目标项目已有 Sidebar / Drawer、token、断点和 focus 规则，真实验证窄屏打开、选择、关闭、返回焦点与滚动位置。

## 已知演示局限与偏差

- 页面主内容完全是占位块，不能证明这种 Shell 对任何具体任务有效。
- Team switcher 只更新组件本地状态，不改变导航、数据、权限或 URL；Add team 没有行为。
- 大量链接为 `#`，Projects 菜单和用户菜单没有业务集成，显示的快捷键没有对应监听器。
- 默认展开、固定 fixture 和 icon 收起行为都是演示选择，不是产品规则。
- 移动侧栏的 Drawer、focus、scroll 和关闭恢复完全依赖缺失的 Sidebar base；desktop 截图不能替代移动验证。

## 源码完整性与观察到的依赖

随附的是局部 installed output，缺少 `package.json`、`components.json`、aliases、base UI、hooks、global CSS 和完整宿主配置。观察到的外部依赖包括 React、`lucide-react`，以及捕获宿主 ThemeProvider 使用的 `next-themes`；还引用 Sidebar、Collapsible、DropdownMenu、Avatar、Breadcrumb、Separator 等 `@/components/ui/*`。

`source/components/theme-provider.tsx` 被原样保留，但未被随附 `page.tsx` 或 Block 组件引用；它属于捕获宿主代码，不是官方 registry manifest 的必需文件。

## 文件

- `desktop-preview.png`：`3840 × 1984` 桌面截图。
- `source/app/dashboard/page.tsx`：Shell 与占位主内容装配。
- `source/components/`：侧栏、分层导航、Projects、Team switcher、用户菜单和捕获宿主 ThemeProvider，共 6 个文件。

## 上游参考与许可

以下是当前官方参考，不是本地 provenance：

- Blocks：<https://ui.shadcn.com/blocks>
- Preview：<https://ui.shadcn.com/view/new-york-v4/sidebar-07>
- Registry JSON：<https://ui.shadcn.com/r/styles/new-york-v4/sidebar-07.json>
- GitHub source：<https://github.com/shadcn-ui/ui/tree/main/apps/v4/registry/new-york-v4/blocks/sidebar-07>
- 官方 License：<https://github.com/shadcn-ui/ui/blob/main/LICENSE.md>
- shadcn/ui 派生部分的本地许可：[`../LICENSE.md`](../LICENSE.md)
