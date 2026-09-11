# 导入组件完整功能检查

这些 fixture 和脚本用于本地维护测试，不是产品页面或正式预览。实现或调试任务可以建立独立项目并安装必要依赖，不能为了规避依赖删掉原功能。

## 独立宿主

在根工作区 Git 忽略的 `.test-screenshots/` 下建立 React + Vite + Tailwind v4 项目，保存真实 `package.json`、lockfile 和独立 `node_modules`。安装 React/ReactDOM、Base UI、`clsx`、`tailwind-merge`、`lucide-react`、`react-markdown`、`remark-gfm`、`react-syntax-highlighter`、`next-themes`，开发依赖包括对应类型声明、TypeScript、Vite/React/Tailwind 插件和 Playwright。按现有包管理器执行安装并保留锁文件，不改其它模板或产品依赖。

1. 将 `loading/source/LoadingPage.tsx`、`markdown/source/MarkdownPro.tsx` 复制到宿主 `src/`；将 `components.fixture.tsx` 复制为 `src/main.tsx`。
2. `src/index.css` 包含 Tailwind v4 入口、源码扫描、shadcn 语义 token 和 `.dark` 变体。fixture 使用 `ThemeProvider` 支持 light/dark/system。
3. 严格类型检查并执行 Vite build；用固定端口、`strictPort` 启动产物 preview。有 `.pcm/runtime.json` 时遵循其中端口。
4. 在工作区根执行：

```bash
node .claude/skills/ui-component-patterns/evals/components.spec.mjs \
  /absolute/path/to/runtime http://127.0.0.1:41739 \
  .test-screenshots/ui-patterns/full-results
```

## SSR/hydration

宿主 Vite 配置增加 `ssr: { noExternal: ['react-syntax-highlighter'] }`，以便处理该包 ESM 子路径；这只属于验证工程。

在宿主执行 `vite build --ssr src/main.tsx --outDir dist-ssr`，保留此前客户端 `dist/`，然后从工作区根执行：

```bash
node .claude/skills/ui-component-patterns/evals/components.ssr.mjs /absolute/path/to/runtime
node .claude/skills/ui-component-patterns/evals/components.spec.mjs \
  /absolute/path/to/runtime http://127.0.0.1:41739/ssr.html \
  .test-screenshots/ui-patterns/full-results-ssr
```

SSR 脚本用 Node `renderToString` 生成真实 HTML，浏览器使用 `hydrateRoot`，并执行与客户端入口相同的完整回归。它不是 Next.js 构建验证。

## 覆盖

- Markdown/GFM、行内代码、表格、任务列表、空内容；未知/无语言代码块保持可读。
- 原有十种语言的 Prism token 着色和行号；相同代码块的独立换行与复制状态。
- 键盘操作、焦点保留、追加内容；长行换行不把 token 挤成竖列。
- 真实 Clipboard API 复制成功；注入 API 拒绝后验证真实 `execCommand` fallback、焦点恢复和节点清理；注入两种途径均失败和异步乱序，验证失败反馈与竞态保护。
- 原始 HTML 不执行、危险协议被过滤、AST `node` 不进入 DOM。
- Loading 覆盖层阻挡底层指针操作、父容器高度、reduced motion。
- light/dark 与 system 随系统变化时的实际高亮颜色、375px 响应式、浏览器无运行错误。
- 截图保存到 `.test-screenshots/` 并实际打开阅读，不能仅依赖断言。

## 本次结果

2026-09-11，独立工程实际执行 npm install 并生成 lockfile，不使用跨项目 node_modules 链接。验证版本：React 19.2.4、Vite 8.2.0、TypeScript 5.9.2、Tailwind 4.3.3、Base UI 1.6.0、react-markdown 10.1.0、remark-gfm 4.0.1、react-syntax-highlighter 16.1.1、对应类型 15.5.13、next-themes 0.4.6、Playwright 1.63.0 / Chromium。

严格类型检查、客户端构建、Node SSR 构建与渲染、客户端和 hydration 两套浏览器回归均通过，代表性明暗/移动端截图已阅读。实际发现并修复了 `pre.style` 与高亮主题对象的类型冲突，以及开启行号和换行时 token 被 flex 挤成竖列的问题。

没有修改外部 PCM 模板或产品依赖，没有执行 PCM Python 全流程或 Next.js 构建。两项导入资产的来源与许可仍待确认；功能验证不代替来源核验。
