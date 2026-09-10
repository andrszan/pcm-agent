import { StrictMode, useState } from "react"
import { createRoot } from "react-dom/client"
import { Button } from "@base-ui/react/button"
import LoadingPage from "./LoadingPage"
import MarkdownPro from "./MarkdownPro"
import "./index.css"

const longLine = `const samePrefix = "${"长行验证".repeat(45)}"`
const content = `# 阅读验证

普通段落、**粗体**与行内代码 \`const value = 1\`。

- 第一项
  - 嵌套项目
- 第二项

> 引用说明

- [x] 已完成
- [ ] 未完成

| 名称 | 说明 |
| --- | --- |
| 长内容 | ${"表格内容".repeat(35)} |

\`\`\`typescript
${longLine}
\`\`\`

\`\`\`typescript
${longLine}
\`\`\`

\`\`\`objective-c
未知语言仍应原样显示
\`\`\`

\`\`\`
无语言代码块
\`\`\`

[安全链接](https://example.com)

[危险链接](javascript:alert(1))

<script>window.__markdownInjected = true</script>
`

function Fixture() {
  const [dark, setDark] = useState(false)
  const [streaming, setStreaming] = useState(false)
  const [count, setCount] = useState(0)
  return (
    <div className={dark ? "dark" : ""}>
      <main className="min-h-screen bg-background p-4 text-foreground sm:p-8">
        <div className="mx-auto max-w-4xl space-y-6">
          <h1 className="text-2xl font-semibold">组件兼容验证</h1>
          <div className="flex flex-wrap gap-3">
            <Button className="rounded border px-3 py-2" onClick={() => setDark(!dark)}>切换主题</Button>
            <Button className="rounded border px-3 py-2" onClick={() => setStreaming(!streaming)}>追加内容</Button>
          </div>
          <section className="rounded border p-4" aria-label="行内加载">
            <LoadingPage />
          </section>
          <section className="relative isolate h-60 rounded border p-4" aria-label="覆盖加载">
            <Button className="rounded border px-3 py-2" onClick={() => setCount(count + 1)}>底层操作 {count}</Button>
            <LoadingPage variant="overlay" message="正在更新内容" />
          </section>
          <section className="rounded border p-4" aria-label="Markdown 阅读">
            <MarkdownPro content={content + (streaming ? "\n\n新增内容" : "")} />
          </section>
          <section className="h-60 rounded border" aria-label="父容器加载">
            <LoadingPage variant="fullscreen" locale="en-US" className="min-h-0" />
          </section>
          <section aria-label="空内容"><MarkdownPro content="" /></section>
        </div>
      </main>
    </div>
  )
}

createRoot(document.getElementById("root")!).render(<StrictMode><Fixture /></StrictMode>)
