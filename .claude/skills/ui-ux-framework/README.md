# ui-ux-framework

`ui-ux-framework` 是产品级 UI/UX 框架设计 Skill，用于建立或演进跨需求稳定的产品表面、信息架构、App Shell Contract、导航、页面模式、滚动与 sticky 规则、共享视觉语义、响应式和可访问性基线。

它负责形成后续需求可以引用的设计合同，不负责单需求页面设计、前端实现、开发后验收或套用通用导航模板。完整职责与执行规则见 [`SKILL.md`](./SKILL.md)。

## 目录

```text
ui-ux-framework/
├── SKILL.md
├── README.md
├── references/
│   ├── layout-selection-guide.md
│   ├── app-shell-contract.md
│   └── layout-resource-library.md
├── assets/layout-patterns/
│   ├── sidebar-workspace/
│   └── top-navigation/
└── evals/evals.json
```

- [`references/layout-selection-guide.md`](./references/layout-selection-guide.md)：区分产品 Shell、页面模式与滚动模型，按项目事实选择布局方向。
- [`references/app-shell-contract.md`](./references/app-shell-contract.md)：定义区域图、滚动所有者、sticky 基准、响应式转换和 Current/Target 合同。
- [`references/layout-resource-library.md`](./references/layout-resource-library.md)：布局资源索引，以及新增、验证和维护资源的权威规则。
- `assets/layout-patterns/`：技术中立的 HTML/CSS/JavaScript 结构与交互参考，不是项目品牌成品或生产代码。
- `evals/evals.json`：验证 Skill 的职责边界和关键行为。

## 使用方式

显式调用 `/ui-ux-framework`，并提供当前项目范围、产品资料、现有设计或需要演进的框架问题。Agent 会先读取真实项目事实，再按当前问题读取必要的 reference；只有需要结构参考时才查看最接近问题的单个布局资源。

资源示例只能帮助理解一种结构如何工作，不能直接决定项目应采用哪种布局，也不能把示例的导航、尺寸、颜色、文案或代码复制为项目默认实现。

## 长期维护资产

维护时遵循以下最小原则：

1. 只有现有资源无法覆盖新的 Shell、页面模式或滚动决策边界时才新增资产；行业、颜色、圆角或组件库不同不构成新资产。
2. 每个布局资源保持原生 HTML/CSS/JavaScript、自包含、无构建步骤、无 CDN 和远程素材，避免绑定 React、Vue 或特定组件库。
3. 每个资源至少包含 `README.md`、`index.html`、`styles.css`、`script.js`、`desktop-preview.png` 和 `mobile-preview.png`。
4. README 说明适用与不适用条件、区域图、滚动所有者、sticky 基准、宽窄屏转换、交互和非目标。
5. 使用真实浏览器验证桌面与窄屏布局、键盘交互、Drawer、焦点返回、滚动、sticky 和控制台错误；临时截图放入工作区根 `.test-screenshots/`，正式预览图保存在资源目录。
6. 新增或调整资源后更新 [`layout-resource-library.md`](./references/layout-resource-library.md) 的索引；只有 Skill 行为边界发生变化时才修改 `SKILL.md` 或增加 eval。

具体准入条件、目录合同、操作步骤和维护检查以 [`references/layout-resource-library.md`](./references/layout-resource-library.md) 为唯一权威说明，避免在多个文件中重复维护同一套规则。
