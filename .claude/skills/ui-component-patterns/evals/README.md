# 导入组件兼容检查

`components.fixture.tsx` 与 `components.spec.mjs` 只用于本地维护测试，不是产品页面或正式预览。测试数据不连接真实业务接口。

## 运行

使用已有 React + Vite + Tailwind v4 隔离宿主，避免写入正在运行的产品。宿主需已具备 React、React DOM、Base UI、`clsx`、`tailwind-merge`、`lucide-react`、`react-markdown`、`remark-gfm`、TypeScript 和 Playwright；本测试不安装依赖。

1. 将 `loading/source/LoadingPage.tsx`、`markdown/source/MarkdownPro.tsx` 复制到宿主 `src/`；将 `components.fixture.tsx` 复制为 `src/main.tsx`。
2. 使用宿主现有 `src/index.css`，包含 Tailwind v4 入口、源码扫描范围、shadcn 语义 token 和 `.dark` 变体。禁止产品运行时 import Skill 内部路径。
3. 对宿主执行严格类型检查与 Vite build，启动 build 产物的本地 preview，固定端口并开启 `strictPort`。有 `.pcm/runtime.json` 时使用其中端口。
4. 在工作区根执行：

```bash
node .claude/skills/ui-component-patterns/evals/components.spec.mjs \
  /absolute/path/to/existing-runtime \
  http://127.0.0.1:41739 \
  .test-screenshots/ui-patterns/results
```

脚本从传入宿主解析已经安装的 Playwright，启动并仅关闭自己创建的浏览器。截图必须写入工作区 Git 忽略的 `.test-screenshots/`。

## 覆盖

- Markdown 标题、列表、嵌套列表、GFM 表格和任务列表；空内容；未知语言和无语言代码块。
- 相同代码块的换行与复制状态隔离、键盘操作、焦点保留、追加内容后的状态保持。
- 真实 Clipboard API 复制成功；注入权限拒绝和异步乱序结果验证失败反馈与竞态保护。失败注入不等于验证所有浏览器权限 UI。
- 原始 HTML 不执行，危险链接协议被过滤，AST `node` 不传给 DOM。
- 加载区域定位、非阻塞覆盖层、父容器高度覆盖、reduced motion。
- 桌面明暗主题、375px 视口无页面横向溢出、浏览器运行错误。
- 截图仍需实际打开阅读，自动断言不能代替视觉检查。

## 本次核验基线

2026-09-11，使用已有本地依赖组成隔离宿主，未安装包、未改 PCM 模板或产品：React 19.2.4、Vite 8.2.0、TypeScript 5.9.2、Tailwind CSS 4.3.3、Base UI 1.6.0、`react-markdown` 10.1.0、`remark-gfm` 4.0.1、Playwright 1.63.0 / Chromium。严格类型检查、构建和以上浏览器检查通过，桌面与移动端代表性截图已阅读。

原文件在纯 React 类型环境复现两处 `style jsx` 的 TS2322，以及高亮包和子模块共 13 项 TS2307。修正后不再依赖 styled-jsx 或高亮引擎。

真实 PCM 两套基础模板均缺 `react-markdown`、`remark-gfm`。本次通过只证明组件在明确依赖下可运行，不代表模板或产品已经接入。未执行 Next.js 构建、产品后端联调或 PCM 全流程；这些都不属于此次资产级验证。两项导入资产的来源与许可仍待确认。
