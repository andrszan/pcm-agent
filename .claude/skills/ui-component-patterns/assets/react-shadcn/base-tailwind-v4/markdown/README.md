# MarkdownPro

用于 React + Tailwind CSS v4 项目的 Markdown 展示参考。组件沿用 `react-markdown` 解析与 `remark-gfm` 扩展，提供基础排版、链接、图片、表格、原生代码块、语言标记、代码换行和剪贴板复制反馈。

## 依赖

源码直接依赖：

- `react`
- `react-markdown`
- `remark-gfm`
- `lucide-react`
- `clsx`
- `tailwind-merge`

当前 PCM React 基础模板已有 `react`、`lucide-react`、`clsx` 和 `tailwind-merge`，但没有 `react-markdown`、`remark-gfm`。本资产的隔离验证环境能解析这两个包，不代表目标项目已经具备依赖。生产使用前必须核对目标项目并取得明确的依赖安装授权；本资产不会自行安装依赖。

## 使用

把 `source/MarkdownPro.tsx` 的实现按目标项目组件目录、`cn` 工具和样式约定进行适配，不要从产品运行时代码导入本 Skill 的内部资产路径。

```tsx
import MarkdownPro from "@/components/MarkdownPro";

<MarkdownPro
  content={message.content}
  locale="zh-CN"
  className="w-full text-inherit"
/>;
```

组件支持 `zh-CN`、`en-US` 两种操作文案。代码块语言从 fenced code 的 `language-*` class 读取并原样显示；因此 `c++`、`objective-c` 等包含符号的语言名不会被截断。

## 已知限制

- 不提供语法着色引擎和行号，只渲染原生 `pre`/`code`。目标项目确有高亮需求时，应按项目已有能力适配；不要仅为复制本资产新增高亮依赖。
- 复制仅使用浏览器 Clipboard API。非安全上下文、权限拒绝或 API 不可用时会显示失败提示，不提供已废弃的 `execCommand` fallback。
- 外链统一在新标签页打开；图片使用原生 `img`。接入目标项目时仍需按其链接信任边界、图片域名和内容安全策略调整。
- 本组件只负责渲染传入 Markdown，不负责内容清洗、远程资源代理、编辑、流式传输或持久化。

## 来源与许可

该文件来自用户导入资产，但当前没有可核验的上游来源与许可信息。不能推定、声明或继承 MIT 等许可证。对外分发、复制到产品仓库或商用前，调用方必须先确认来源、授权范围和归属要求。
