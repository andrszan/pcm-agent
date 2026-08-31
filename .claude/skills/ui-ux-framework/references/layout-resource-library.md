# 布局参考资源库：可运行模式与框架源码快照

本文件是 `ui-ux-framework` 布局资源的唯一权威说明。资源分为两层：`assets/layout-patterns/` 保存技术中立、原生、自包含、可运行且固定六文件的布局模式；`assets/layout-source-snapshots/` 保存部分、不可独立运行、带上游依赖与许可的第三方框架源码快照，只用于分析结构、交互和实现假设，不代表项目技术栈、组件库或生产实现。

使用前先阅读 [`layout-selection-guide.md`](./layout-selection-guide.md)，根据真实产品事实选择资源层和最接近当前决策问题的单套资源；不要浏览全部资源后选择最容易实现的一套。

## 1. 技术中立可运行资源

### Sidebar Workspace

路径：[`../assets/layout-patterns/sidebar-workspace/`](../assets/layout-patterns/sidebar-workspace/)

适合研究：

- 模块较多、切换频繁的操作型工作区；
- `100dvh` Shell 与主内容独立滚动；
- 可折叠侧边栏、多层导航和当前项；
- 相对主滚动区 sticky 的 route toolbar；
- 窄屏将侧边栏转换为 Drawer。

主要文件：

- [`README.md`](../assets/layout-patterns/sidebar-workspace/README.md)：适用条件、区域合同和非目标；
- [`index.html`](../assets/layout-patterns/sidebar-workspace/index.html)：语义结构与演示内容；
- [`styles.css`](../assets/layout-patterns/sidebar-workspace/styles.css)：Shell、滚动、sticky 与响应式；
- [`script.js`](../assets/layout-patterns/sidebar-workspace/script.js)：折叠、展开、当前项和 Drawer 交互；
- `desktop-preview.png`、`mobile-preview.png`：固定初始状态下的正式参考图。

### Top Navigation

路径：[`../assets/layout-patterns/top-navigation/`](../assets/layout-patterns/top-navigation/)

适合研究：

- 一级入口较少、层级较浅的产品表面；
- document scroll 与 sticky 顶部导航；
- 全局主导航和页面局部 tabs 的职责分离；
- 窄屏将横向主导航转换为菜单 Drawer。

主要文件：

- [`README.md`](../assets/layout-patterns/top-navigation/README.md)：适用条件、区域合同和非目标；
- [`index.html`](../assets/layout-patterns/top-navigation/index.html)：语义结构与演示内容；
- [`styles.css`](../assets/layout-patterns/top-navigation/styles.css)：文档滚动、sticky 与响应式；
- [`script.js`](../assets/layout-patterns/top-navigation/script.js)：当前项、tabs 和 Drawer 交互；
- `desktop-preview.png`、`mobile-preview.png`：固定初始状态下的正式参考图。

### List–Detail Workspace

路径：[`../assets/layout-patterns/list-detail-workspace/`](../assets/layout-patterns/list-detail-workspace/)

适合研究：

- 围绕对象列表连续扫描、选择和处理的工作区；
- `100dvh` 下列表与详情两个独立滚动 pane；
- 分别相对列表 pane 和详情 pane sticky 的头部；
- 按钮通过 `aria-controls`、`aria-pressed` 和详情 `hidden` 建立当前项关系；
- 窄屏在列表与详情间转换，并恢复焦点和列表滚动位置。

主要文件：

- [`README.md`](../assets/layout-patterns/list-detail-workspace/README.md)：适用条件、双 pane 合同、窄屏焦点和非目标；
- [`index.html`](../assets/layout-patterns/list-detail-workspace/index.html)：语义列表、预置详情与中性演示内容；
- [`styles.css`](../assets/layout-patterns/list-detail-workspace/styles.css)：双滚动 pane、sticky 头部与窄屏转换；
- [`script.js`](../assets/layout-patterns/list-detail-workspace/script.js)：目标验证、互斥选择、焦点和滚动恢复；
- [`desktop-preview.png`](../assets/layout-patterns/list-detail-workspace/desktop-preview.png)：`1440 × 1024` 的桌面初始状态预览；
- [`mobile-preview.png`](../assets/layout-patterns/list-detail-workspace/mobile-preview.png)：`390 × 844` 的窄屏详情状态预览，显示返回入口与详情标题。

## 2. shadcn/ui 布局源码快照

Provider 路径：[`../assets/layout-source-snapshots/shadcn-ui/`](../assets/layout-source-snapshots/shadcn-ui/)

这些 Block-derived installed-output snapshots 带有 React、Tailwind CSS、shadcn/ui 及相关生态依赖痕迹，缺少完整宿主配置，不能独立编译或运行。它们用于核对具体结构和实现假设，不构成项目布局或技术选型。

| 语义目录 | shadcn/ui Block ID | 主要决策问题 | 关键局限 |
| --- | --- | --- | --- |
| [`summary-to-record-workbench/`](../assets/layout-source-snapshots/shadcn-ui/summary-to-record-workbench/) | `dashboard-01` | 用户是否需要在同一工作台先扫摘要与趋势，再处理记录并打开单条详情？ | 依赖面广，表头 sticky 与页面滚动高度合同未闭合，多处交互只是演示占位。 |
| [`context-switching-navigation-shell/`](../assets/layout-source-snapshots/shadcn-ui/context-switching-navigation-shell/) | `sidebar-07` | 用户是否需要频繁切换上下文，并在分层模块与 Projects 之间导航？ | 主内容是占位；移动 Drawer、焦点与滚动依赖未随附的 Sidebar base。 |
| [`mode-rail-collection-workbench/`](../assets/layout-source-snapshots/shadcn-ui/mode-rail-collection-workbench/) | `sidebar-09` | 任务是否确实存在“模式—集合—内容”三层关系，并能为窄屏定义进入与返回？ | 不是真正的 list-detail，状态带随机和原地排序，移动端直接隐藏集合列。 |
| [`sectioned-preferences-dialog/`](../assets/layout-source-snapshots/shadcn-ui/sectioned-preferences-dialog/) | `sidebar-13` | 设置任务是否中短、可中断，并适合在保留原页面上下文的模态子系统中完成？ | 分类、面包屑和内容未联动；移动端隐藏分类，关键行为依赖未随附的 Dialog base。 |

四套快照的来源信息均不完整，只有实际随附的桌面预览，没有移动端预览；预览不作为目标项目需求或视觉验收基线。具体依赖、来源边界和许可先读 provider README 与所选语义目录 README，不在本索引重复四份说明。

## 3. 使用方式与项目化转译

1. 先根据产品表面、用户任务、入口层级、信息密度、对象上下文、设备、现有技术事实和迁移成本形成候选，再选择技术中立可运行模式或第三方源码快照。
2. 每次只读取最接近当前问题的一套资源。使用 `layout-patterns` 时先读该资源 README，再按需查看源码和预览；使用 source snapshot 时先读 provider README 和所选语义目录 README，确认决策问题、依赖、局限与许可，再按需读取 `source/`。
3. 按五个检查点完成项目化转译：
   1. **项目事实**：确认真实用户任务、信息层级、数据规模、目标视口、既有技术栈和约束；
   2. **借用原理**：只提取有助于当前问题的布局、滚动、导航、响应式或反馈原理；
   3. **项目化表达**：使用目标项目自己的信息架构、组件、品牌、token、内容和状态模型重新设计；
   4. **有依据差异**：参考中的关键决定无论保留还是改变，都能由项目事实解释，不为随机变化而变化；
   5. **真实验证**：在目标项目中验证代表性数据、加载、空态、失败、权限、成功、恢复、窄屏和键盘/焦点行为。
4. 在 App Shell Contract 中重新表达项目自己的区域、导航、页面模式、滚动所有者、sticky 基准和宽窄屏转换。
5. 后续实现按项目实际路由、权限、组件、技术栈和品牌体系二次开发，不把参考当作生产模板。

禁止复制后只替换 Logo、颜色或文案；禁止复制 fixture、品牌、token、固定宽度、断点和 demo logic。这不等于要求随机变化，相同或不同的关键决定都必须有项目事实依据。

资源可以证明“这种结构如何工作”，不能证明：

- 当前项目应该选择这种结构；
- 权限、路由、持久化或业务行为已经正确；
- 示例满足目标项目全部可访问性、品牌和浏览器兼容要求；
- 预览图等同于真实产品验收。

## 4. `layout-source-snapshots` 目录合同

Provider 与语义目录保持以下最小合同：

```text
assets/layout-source-snapshots/<provider>/
├── README.md
├── LICENSE.md
└── <semantic-name>/
    ├── README.md
    ├── source/
    └── <实际存在的预览文件>
```

- Provider README 说明来源边界、共同依赖、使用规则和快照映射，许可文件覆盖该 provider 内的上游派生内容；
- 子 README 说明上游 ID、决策问题、依赖、关键局限、源码与实际存在的预览；
- 保持已知来源映射和 `source/` 内相对结构，不把整理后的语义目录冒充官方原始目录；
- 未随材料提供的版本、commit、安装命令、导入前修改或截图 provenance 不推断；
- 记录依赖、局限和许可，不要求快照编译、独立运行，也不伪造未提供的移动端预览或交互材料。

## 5. `layout-patterns` 新增资源的准入

以下准入、固定六文件、静态服务器、截图和浏览器维护规则只适用于 `layout-patterns`，不适用于 `layout-source-snapshots`。

仅当现有资源不能覆盖一个具有实质差异的决策边界时新增，例如：

- 顶部全局栏与侧边上下文导航的复合 Shell；
- 列表—详情并列与窄屏页面栈；
- 画布、工具栏和停靠面板；
- 移动端底部一级导航；
- 面向专注任务的最小 Shell。

不要仅因颜色、圆角、阴影、文案、行业或组件库不同而复制一套资源。

## 6. `layout-patterns` 目录合同

每个资源固定且只使用以下六个文件：

```text
assets/layout-patterns/<pattern-name>/
├── README.md
├── index.html
├── styles.css
├── script.js
├── desktop-preview.png
└── mobile-preview.png
```

### README 必须说明

- 解决的决策问题；
- 适用与不适用条件；
- Shell 区域图；
- 滚动所有者和 sticky 基准；
- 桌面与窄屏转换；
- 演示交互；
- 明确非目标；
- 源码与预览文件。

### HTML/CSS/JS 约束

- 使用原生语义 HTML、CSS 和少量 JavaScript；
- 不依赖框架、构建步骤、包管理器、CDN、远程字体、远程图片或第三方图标库；
- 使用中性对象、任务和状态，不引入真实项目品牌；
- 交互控件有清晰名称、可见焦点和正确的 `aria-current`、`aria-expanded` 等状态；
- 菜单 Drawer 支持关闭按钮、`Escape`、选择后关闭和焦点返回；
- 动效尊重 `prefers-reduced-motion`；
- 不模拟鉴权、服务端数据、持久化、完整路由或生产错误处理。

## 7. `layout-patterns` 新增步骤

1. 写清现有资源为什么不能覆盖新的结构或交互边界。
2. 确定 Shell、页面模式和滚动模型，不先选择视觉风格。
3. 建立目录并完成 README、HTML、CSS 和 JavaScript。
4. 使用本地静态服务器打开资源；不得依赖 `file://` 特例完成验证。
5. 在桌面和窄屏视口检查布局、导航、滚动、sticky、菜单、键盘和控制台错误。
6. 将临时验证截图放入工作区根 `.test-screenshots/`；确认稳定后，再生成并提交固定初始状态的正式 `desktop-preview.png` 与 `mobile-preview.png`。
7. 在本文件“技术中立可运行资源”中登记用途和路径。
8. 只有资源引入新的 Skill 行为边界时才增加或调整 eval；不要为每个示例建立独立测试框架。

## 8. `layout-patterns` 维护检查

更新资源时确认：

- 源码和预览仍对应同一初始状态；
- 没有新增远程依赖或技术栈绑定；
- 示例没有被描述成项目默认答案；
- 宽屏和窄屏都能完成演示交互；
- 滚动所有者与 sticky 基准仍和 README 一致；
- 当前项、展开状态、菜单和焦点状态可理解；
- 控制台没有错误；
- 新资源确实增加决策覆盖，而不是视觉变体。
