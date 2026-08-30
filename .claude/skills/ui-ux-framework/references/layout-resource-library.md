# 布局参考资源库

本目录索引可运行的技术中立布局参考。资源用于理解区域关系、导航转换、sticky 行为、滚动所有者和基础键盘交互，不是项目品牌成品、设计系统或可直接复制的生产实现。

使用前先阅读 [`layout-selection-guide.md`](./layout-selection-guide.md)，根据真实产品事实选择最接近当前决策问题的单个资源；不要浏览全部示例后选择最容易实现的一套。

## 1. 当前资源

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

## 2. 使用方式

1. 先根据产品表面、任务频率、入口数量、信息密度、对象上下文、设备和迁移成本形成布局候选。
2. 只读取最接近当前问题的资源 README 和源码。
3. 比较项目事实与示例假设，明确哪些关系可借鉴、哪些不适用。
4. 在 App Shell Contract 中重新表达项目自己的区域、导航、滚动、sticky 和响应式规则。
5. 后续实现按项目技术栈、路由、权限、组件和品牌体系二次开发，不复制示例文案、尺寸、颜色或数据。

资源可以证明“这种结构如何工作”，不能证明：

- 当前项目应该选择这种结构；
- 权限、路由、持久化或业务行为已经正确；
- 示例满足目标项目全部可访问性、品牌和浏览器兼容要求；
- 预览图等同于真实产品验收。

## 3. 新增资源的准入

仅当现有资源不能覆盖一个具有实质差异的决策边界时新增，例如：

- 顶部全局栏与侧边上下文导航的复合 Shell；
- 列表—详情并列与窄屏页面栈；
- 画布、工具栏和停靠面板；
- 移动端底部一级导航；
- 面向专注任务的最小 Shell。

不要仅因颜色、圆角、阴影、文案、行业或组件库不同而复制一套资源。

## 4. 目录合同

每个资源使用以下最小结构：

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

## 5. 新增步骤

1. 写清现有资源为什么不能覆盖新的结构或交互边界。
2. 确定 Shell、页面模式和滚动模型，不先选择视觉风格。
3. 建立目录并完成 README、HTML、CSS 和 JavaScript。
4. 使用本地静态服务器打开资源；不得依赖 `file://` 特例完成验证。
5. 在桌面和窄屏视口检查布局、导航、滚动、sticky、菜单、键盘和控制台错误。
6. 将临时验证截图放入工作区根 `.test-screenshots/`；确认稳定后，再生成并提交固定初始状态的正式 `desktop-preview.png` 与 `mobile-preview.png`。
7. 在本文件“当前资源”中登记用途和路径。
8. 只有资源引入新的 Skill 行为边界时才增加或调整 eval；不要为每个示例建立独立测试框架。

## 6. 维护检查

更新资源时确认：

- 源码和预览仍对应同一初始状态；
- 没有新增远程依赖或技术栈绑定；
- 示例没有被描述成项目默认答案；
- 宽屏和窄屏都能完成演示交互；
- 滚动所有者与 sticky 基准仍和 README 一致；
- 当前项、展开状态、菜单和焦点状态可理解；
- 控制台没有错误；
- 新资源确实增加决策覆盖，而不是视觉变体。
