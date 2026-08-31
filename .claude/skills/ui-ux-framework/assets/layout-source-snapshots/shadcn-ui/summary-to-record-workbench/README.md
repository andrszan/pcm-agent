# Summary to Record Workbench

## 快照状态

- Provider：shadcn/ui
- Block ID：`dashboard-01`
- 类型：Block-derived installed-output
- 运行状态：缺少宿主项目与基础依赖，不可独立运行
- Provenance：unknown provenance；CLI 版本、upstream commit、精确安装命令、导入前修改和截图精确 provenance 均未随素材提供，不推断
- 预览：desktop only，`3840 × 1984`；未提供 mobile preview
- 许可边界：shadcn/ui 派生部分见 [`../LICENSE.md`](../LICENSE.md)；`source/components/theme-provider.tsx` 的精确来源与许可未随素材提供

## 决策问题

用户是否需要在同一个工作台中按“摘要指标 → 趋势 → 记录表 → 单条详情”推进扫描和处理，并且记录表的密度、批量操作与详情编辑确实服务于同一任务？如果主要任务只是阅读摘要，或详情需要长期并列对照，应先比较更简单的 document page 或明确的 list-detail 模式。

## 结构、滚动与响应式

- `SidebarProvider` 包住侧栏与 `SidebarInset`；主内容依次放置固定高度站点 header、摘要卡、趋势图、tabs/记录表。
- 页面没有建立明确的 `100dvh` 主滚动容器，实际主要依赖 document scroll。记录区的 `TabsContent` 声明 `overflow-auto`，表头声明 `sticky top-0`，但该区域没有闭合的可用高度，因此“谁滚动、表头相对谁 sticky、何时生效”的高度合同并未完整建立。
- 点击记录标题打开 Drawer。Drawer 内正文使用 `overflow-y-auto`，页脚留在正文外；其可用高度、桌面侧滑与移动下滑行为依赖未随附的 Drawer base。
- 摘要卡、图表控制和 tabs 使用 container query / 响应式显示切换；窄容器下会显示一个视图 Select，但它没有连接 Tabs 状态，只有图表时间范围 Select 具备实际状态切换。

## 可借鉴原理

- 先用少量摘要回答“现在怎样”，再用趋势回答“如何变化”，最后把处理入口落到可筛选、选择、分页的记录层。
- 让单条详情通过临时 Drawer 保留列表上下文，适合短时查看或轻量编辑；若详情任务很长，应改为独立页面或稳定详情 pane。
- 将列显隐、分页、选择、拖拽和详情触发集中在记录层，而不是把操作散到摘要卡中。
- 用容器宽度决定卡片列数和工具切换，比仅按 viewport 猜测组件可用空间更接近可复用工作台。

## 项目化差异要求

- 使用目标项目自己的指标定义、图表维度、记录 schema、权限、状态、分页策略和保存流程；禁止复制收入、访客、文档章节、人员、日期、图表数值等 fixture。
- 先明确 document 与记录区的滚动所有权，再实现 sticky 表头；不得照搬当前未闭合的 `overflow-auto` / `sticky` 组合。
- 根据真实详情任务决定 Drawer 的方向、宽度、关闭恢复、未保存保护和移动端替代方案，不复制演示固定行为。
- 使用目标项目已有组件、icon 集、token 和断点。源码中的 `lucide-react` icon 及其命名可能与当前 registry 输出不同，不应据此锁定版本。
- Tabs、列菜单、拖拽和保存只保留真实需要的能力，不以“更像截图”为理由引入依赖。

## 已知演示局限与偏差

- `Past Performance`、`Key Personnel`、`Focus Documents` 面板只有虚线占位；侧栏多项、记录菜单、Add Section 和部分按钮没有业务行为。
- 窄容器下显示的视图 Select 只有 `defaultValue`，没有驱动 Tabs 的共享状态；原 TabsTrigger 同时被隐藏，因此选择其它视图不会切换面板。
- Target / Limit 提交只用延时 Promise 和 Sonner toast 模拟保存；详情表单的 Submit 没有提交逻辑，Select 也没有持久化。
- 大量导航 URL 为 `#`，fixture 与图表数据是固定演示内容。
- 截图与随附源码并非完全一致：截图 header 右侧显示 `GitHub`，而 `site-header.tsx` 没有该操作；截图列按钮为 `Customize Columns`，源码文案为 `Columns`。
- 截图只证明一个桌面暗色捕获状态，不能证明窄屏、空态、失败、权限、拖拽、保存或恢复行为。

## 源码完整性与观察到的依赖

随附的是局部 installed output，缺少 `package.json`、`components.json`、aliases、base UI、hooks、global CSS 和完整宿主配置。观察到的外部依赖包括 React、`@dnd-kit/core`、`@dnd-kit/modifiers`、`@dnd-kit/sortable`、`@dnd-kit/utilities`、TanStack React Table、Recharts、Sonner、Zod 和 `lucide-react`；还引用 `@/hooks/use-mobile` 以及 Sidebar、Card、Chart、Tabs、Table、Drawer、DropdownMenu、Select 等大量 `@/components/ui/*`。

`source/components/theme-provider.tsx` 被原样保留，但未被随附 `page.tsx` 或 Block 组件引用；它属于捕获宿主代码，不是官方 registry manifest 的必需文件。

## 文件

- `desktop-preview.png`：`3840 × 1984` 桌面截图。
- `source/app/dashboard/page.tsx`：页面装配。
- `source/app/dashboard/data.json`：记录表演示 fixture。
- `source/components/`：侧栏、摘要卡、趋势图、记录表、header、导航和捕获宿主 ThemeProvider，共 10 个文件。

## 上游参考与许可

以下是当前官方参考，不是本地 provenance：

- Blocks：<https://ui.shadcn.com/blocks>
- Preview：<https://ui.shadcn.com/view/new-york-v4/dashboard-01>
- Registry JSON：<https://ui.shadcn.com/r/styles/new-york-v4/dashboard-01.json>
- GitHub source：<https://github.com/shadcn-ui/ui/tree/main/apps/v4/registry/new-york-v4/blocks/dashboard-01>
- 官方 License：<https://github.com/shadcn-ui/ui/blob/main/LICENSE.md>
- shadcn/ui 派生部分的本地许可：[`../LICENSE.md`](../LICENSE.md)
