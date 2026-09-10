# Sectioned Preferences Dialog

## 快照状态

- Provider：shadcn/ui
- Block ID：`sidebar-13`
- 类型：Block-derived installed-output
- 运行状态：缺少宿主项目与基础依赖，不可独立运行
- Provenance：unknown provenance；CLI 版本、upstream commit、精确安装命令、导入前修改和截图精确 provenance 均未随素材提供，不推断
- 预览：desktop only，`3840 × 1984`；未提供 mobile preview
- 许可边界：shadcn/ui 派生部分见 [`../LICENSE.md`](../LICENSE.md)；`source/components/theme-provider.tsx` 的精确来源与许可未随素材提供

## 决策问题

设置任务是否中短、可中断，并且用户完成或取消后应回到原页面上下文？如果设置是长表单、关键任务、需要深链接/分享、跨会话恢复或复杂错误处理，应使用独立页面而不是模态子系统。

## 结构、滚动与响应式

- 页面只负责居中放置 `SettingsDialog`。Dialog 默认打开，内部用 SidebarProvider 组织左侧分区导航和右侧设置内容。
- 右侧 `main` 固定为 `h-[480px]` 并 `overflow-hidden`；header 保持固定，正文区域 `overflow-y-auto` 独立滚动，形成“分区 nav + 固定 header + 独立内容滚动”的模态子系统。
- Dialog 最大高度/宽度和右侧固定高度都是演示值；实际 viewport 适配、Dialog 外层滚动锁和边界行为依赖未随附的 Dialog base。
- `md` 以下左侧分类直接隐藏，没有替代的分类选择、返回或当前路径入口。

## 可借鉴原理

- 对中短设置任务，用分区 nav 降低单页扫描成本，同时由固定 header 持续表达当前位置。
- 只让右侧内容区滚动，可保持分类导航和标题稳定；前提是高度、sticky/固定区域和焦点顺序合同清楚。
- 模态子系统适合保留原任务上下文、快速调整后返回，不适合承载需要深链接或长时间完成的工作。
- 分类、active 状态、breadcrumb 和内容必须由同一状态源驱动，不能只做视觉高亮。

## 项目化差异要求

- 使用目标项目真实设置分类、表单、保存模型、权限和未保存变更保护，不照搬分类文案或占位块；接入已有 token，布局代码可按许可与兼容条件复用，尺寸和断点按真实内容与视口核验。
- 让 active 分类、breadcrumb、标题和右侧内容同步，并决定是否需要 URL / 可恢复状态。
- 窄屏提供等价的分类进入与返回流程，不得直接隐藏分类导航。
- 使用目标项目现有 Dialog 实现并真实验证 focus trap、初始焦点、Escape、遮罩关闭策略、背景 scroll lock、关闭后的 focus return 和长内容边界。
- 仅用于中短、可中断设置；长表单、关键任务和需要深链接的设置应转为独立页面。

## 已知演示局限与偏差

- Dialog 用 `useState(true)` 默认打开；`Open Dialog` trigger 在初始截图中没有实际使用路径。
- active 分类和 breadcrumb 固定为 `Messages & media`，点击其它分类只导航到 `#`，不会更新内容或当前位置。
- 右侧是 10 个占位块，没有真实表单、保存、失败、权限或未保存状态。
- 移动端隐藏分类，没有替代导航；固定 `480px` 高度也未证明适配不同 viewport。
- focus trap、Escape、背景 scroll lock、关闭后的 focus return 等关键模态行为依赖缺失的 Dialog base，不能由当前局部源码确认。

## 源码完整性与观察到的依赖

随附的是局部 installed output，缺少 `package.json`、`components.json`、aliases、base UI、hooks、global CSS 和完整宿主配置。观察到的外部依赖包括 React、`lucide-react`，以及捕获宿主 ThemeProvider 使用的 `next-themes`；还引用 Dialog、Sidebar、Breadcrumb、Button 等 `@/components/ui/*`。

`source/components/theme-provider.tsx` 被原样保留，但未被随附 `page.tsx` 或 Block 组件引用；它属于捕获宿主代码，不是官方 registry manifest 的必需文件。

## 文件

- `desktop-preview.png`：`3840 × 1984` 桌面截图。
- `source/app/dashboard/page.tsx`：居中打开设置 Dialog 的页面入口。
- `source/components/settings-dialog.tsx`：分区导航、固定 header 与独立滚动内容。
- `source/components/theme-provider.tsx`：未被随附 Block 源码引用的捕获宿主 ThemeProvider。

## 上游参考与许可

以下是当前官方参考，不是本地 provenance：

- Blocks：<https://ui.shadcn.com/blocks>
- Preview：<https://ui.shadcn.com/view/new-york-v4/sidebar-13>
- Registry JSON：<https://ui.shadcn.com/r/styles/new-york-v4/sidebar-13.json>
- GitHub source：<https://github.com/shadcn-ui/ui/tree/main/apps/v4/registry/new-york-v4/blocks/sidebar-13>
- 官方 License：<https://github.com/shadcn-ui/ui/blob/main/LICENSE.md>
- shadcn/ui 派生部分的本地许可：[`../LICENSE.md`](../LICENSE.md)
