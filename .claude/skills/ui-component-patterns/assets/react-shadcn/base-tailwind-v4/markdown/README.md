# MarkdownPro

用于 React + Tailwind CSS v4 项目的 Markdown 展示参考。组件沿用 `react-markdown` 与 `remark-gfm`，提供 GFM 排版、Prism 语法高亮、行号、语言标记、代码换行和剪贴板复制成功/失败反馈。

## 依赖

源码直接依赖：

- `react`
- `react-markdown`
- `remark-gfm`
- `react-syntax-highlighter` 与对应类型声明
- `next-themes`
- `lucide-react`
- `clsx`
- `tailwind-merge`

接入前应核对目标项目现有依赖和主题基础设施。选择本参考本身不授权安装包；但调用方已明确要求实现或调试时，可按目标项目包管理器安装实现所需的合理依赖并同步 lockfile，不必逐包再次询问，也不得为避免依赖而删除高亮、行号或主题能力。

## 使用

把 `source/MarkdownPro.tsx` 的实现按目标项目组件目录、`cn` 工具和样式约定进行适配，不要从产品运行时代码导入本 Skill 的内部资产路径。宿主需在 `ThemeProvider` 中启用对应的 light/dark/system 主题控制。

```tsx
import MarkdownPro from "@/components/MarkdownPro";

<MarkdownPro
  content={message.content}
  locale="zh-CN"
  className="w-full text-inherit"
/>;
```

组件支持 `zh-CN`、`en-US` 两种操作文案。显式注册原参考中的 TSX、TypeScript/TS、JavaScript/JS、JSON、Bash/Shell、Python/Py、Go/Golang、Java、SQL、Markdown/MD；未注册语言仍以纯文本显示并保留原语言标签。高亮使用 `useTheme().resolvedTheme`，首屏先渲染稳定原生代码块，挂载后再应用对应 Prism 主题，避免 SSR hydration 不一致。

## 行为与限制

- 每个代码块独立维护换行、复制反馈、定时器和异步请求序号；相似内容不会共享状态，较早复制结果不会覆盖较新操作。
- 复制优先使用 Clipboard API；不可用或拒绝时保留 `textarea` + `execCommand` 兼容 fallback，并清理临时节点、恢复焦点与选择。两种方式均失败才显示失败提示；浏览器可能限制已废弃的兼容接口。
- 外链统一在新标签页打开；图片使用原生 `img`。接入目标项目时仍需按链接信任边界、图片域名和内容安全策略调整。
- 保持 `react-markdown` 默认安全边界，不启用 raw HTML。本组件不负责内容清洗、远程资源代理、编辑、流式传输或持久化。

## 来源与许可

该文件来自用户导入资产，但当前没有可核验的上游来源与许可信息。不能推定、声明或继承 MIT 等许可证。对外分发、复制到产品仓库或商用前，调用方必须先确认来源、授权范围和归属要求。
