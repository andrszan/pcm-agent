# Mode Rail Collection Workbench

## 快照状态

- Provider：shadcn/ui
- Block ID：`sidebar-09`
- 类型：Block-derived installed-output
- 运行状态：缺少宿主项目与基础依赖，不可独立运行
- Provenance：unknown provenance；CLI 版本、upstream commit、精确安装命令、导入前修改和截图精确 provenance 均未随素材提供，不推断
- 预览：desktop only，`3840 × 1984`；未提供 mobile preview
- 许可边界：shadcn/ui 派生部分见 [`../LICENSE.md`](../LICENSE.md)；`source/components/theme-provider.tsx` 的精确来源与许可未随素材提供

## 决策问题

目标任务是否真的存在“模式 rail → 当前模式下的集合 → 主内容”三层关系，并且用户需要在三者之间持续切换？如果选择集合项不会改变主内容，这就不是 list-detail；若目标需要 list-detail，必须先定义稳定的集合—内容关系和窄屏进入/返回流程。

## 结构、滚动与响应式

- 外层 Sidebar 内嵌两个不可收起 Sidebar：窄 icon mode rail 与 collection pane；页面右侧是带 sticky header 的主内容。
- mode rail 切换 Inbox、Drafts、Sent 等模式；collection pane 显示邮件摘要、search 和 Unreads 控件；主内容只是 24 个占位块。
- collection pane 依赖 Sidebar base 的 `SidebarContent` 处理自身内容，主页面则随文档滚动并让 header `sticky top-0`；两者没有形成真实对象选择和详情滚动合同。
- `--sidebar-width: 350px` 是演示宽度。移动断点下 collection pane 使用 `hidden md:flex` 直接隐藏，没有等价的集合入口、详情进入或返回流程。

## 可借鉴原理

- 将低宽度、高频的模式切换放入 rail，把当前模式的对象集合放在相邻 pane，能减少模式与对象的混淆。
- collection header 可承载当前模式名称、筛选和搜索，列表项集中呈现可扫描的发件人、时间、主题和摘要。
- 主内容 header 与 collection header 分属不同滚动上下文时，应分别声明 sticky 和滚动所有权。
- 三层布局只有在集合选择能稳定驱动主内容、并能恢复选择与滚动位置时才成立。

## 项目化差异要求

- 建立真实、稳定的“模式 → 集合查询 → 当前项 → 内容”状态模型，路由或可恢复状态应表达当前选择；不得复制随机子集作为模式切换反馈。
- 不照搬 fixture、Acme 品牌、邮件内容和 demo logic，使用项目已有 token；布局代码可按许可与兼容条件复用，`350px` 等宽度及断点是否保留由目标信息密度和视口验证决定。
- Search、Unreads 和 mode 切换必须接入真实查询与状态，并提供加载、空态、失败和权限反馈。
- 窄屏必须补齐“进入集合 → 选择内容 → 返回集合/模式”的流程，恢复当前项、焦点和滚动位置；不得直接隐藏 collection 后宣称已响应式适配。
- 只有目标任务确实需要三层并存时才保留 mode rail；更简单的两层关系应使用更简单的导航或 list-detail。

## 已知演示局限与偏差

- 这不是真正的 list-detail：点击邮件链接不会选择对象或更新右侧内容，主内容始终是占位块。
- mode 点击调用 `data.mails.sort(() => Math.random() - 0.5)`，会原地修改共享 fixture，再用 `Math.random()` 截取不稳定子集；结果不可复现，也不表达真实查询。
- Search 输入框和 Unreads Switch 没有行为；邮件链接均为 `#`。
- 移动端直接隐藏 collection pane，没有移动进入/返回路径；外层 `setOpen(true)` 不能替代缺失的集合交互。
- `350px`、固定摘要宽度和当前滚动表现只是桌面演示，不是可直接复用的布局合同。

## 源码完整性与观察到的依赖

随附的是局部 installed output，缺少 `package.json`、`components.json`、aliases、base UI、hooks、global CSS 和完整宿主配置。观察到的外部依赖包括 React、`lucide-react`，以及捕获宿主 ThemeProvider 使用的 `next-themes`；还引用 Sidebar、Switch、Label、DropdownMenu、Avatar、Breadcrumb、Separator 等 `@/components/ui/*`。

`source/components/theme-provider.tsx` 被原样保留，但未被随附 `page.tsx` 或 Block 组件引用；它属于捕获宿主代码，不是官方 registry manifest 的必需文件。

## 文件

- `desktop-preview.png`：`3840 × 1984` 桌面截图。
- `source/app/dashboard/page.tsx`：外层 Shell、固定演示宽度和占位主内容。
- `source/components/`：mode rail / collection Sidebar、用户菜单和捕获宿主 ThemeProvider，共 3 个文件。

## 上游参考与许可

以下是当前官方参考，不是本地 provenance：

- Blocks：<https://ui.shadcn.com/blocks>
- Preview：<https://ui.shadcn.com/view/new-york-v4/sidebar-09>
- Registry JSON：<https://ui.shadcn.com/r/styles/new-york-v4/sidebar-09.json>
- GitHub source：<https://github.com/shadcn-ui/ui/tree/main/apps/v4/registry/new-york-v4/blocks/sidebar-09>
- 官方 License：<https://github.com/shadcn-ui/ui/blob/main/LICENSE.md>
- shadcn/ui 派生部分的本地许可：[`../LICENSE.md`](../LICENSE.md)
