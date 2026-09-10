"use client";

import React, {
  createContext,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";
import Markdown, { type Components, type ExtraProps } from "react-markdown";
import remarkGfm from "remark-gfm";
import { Check, Copy, WrapText } from "lucide-react";
import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

type Locale = "zh-CN" | "en-US";
type CopyStatus = "copied" | "failed";

export interface MarkdownProProps {
  content?: string;
  className?: string;
  locale?: Locale;
}

const DICT = {
  "zh-CN": {
    copy: "复制",
    copied: "已复制",
    copyFailed: "复制失败",
    wrap: "自动换行",
    unwrap: "取消自动换行",
    code: "代码",
  },
  "en-US": {
    copy: "Copy",
    copied: "Copied",
    copyFailed: "Copy failed",
    wrap: "Auto wrap",
    unwrap: "Disable wrap",
    code: "Code",
  },
} satisfies Record<Locale, Record<string, string>>;

type Dictionary = (typeof DICT)[Locale];

const DictionaryContext = createContext<Dictionary>(DICT["zh-CN"]);

function LanguageBadge({ lang }: { lang: string }) {
  return (
    <span className="select-none rounded-md border border-primary/20 bg-primary/10 px-2 py-0.5 text-xs font-medium text-primary">
      {lang}
    </span>
  );
}

function CodeBlock({
  node: _node,
  className,
  children,
  ...props
}: React.ComponentPropsWithoutRef<"pre"> & ExtraProps) {
  const dict = useContext(DictionaryContext);
  const [isWrapped, setIsWrapped] = useState(false);
  const [copyStatus, setCopyStatus] = useState<CopyStatus>();
  const copyTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const copyAttempt = useRef(0);
  const child = Array.isArray(children) ? children[0] : children;
  const childElement = React.isValidElement<{
    className?: string;
    children?: React.ReactNode;
  }>(child)
    ? child
    : null;
  const raw = String(childElement?.props.children ?? "");
  const language =
    /(?:^|\s)language-([^\s]+)/.exec(childElement?.props.className || "")?.[1] ||
    dict.code;

  useEffect(
    () => () => {
      copyAttempt.current += 1;
      if (copyTimer.current) clearTimeout(copyTimer.current);
    },
    []
  );

  const handleCopy = async () => {
    const attempt = ++copyAttempt.current;
    if (copyTimer.current) {
      clearTimeout(copyTimer.current);
      copyTimer.current = null;
    }
    setCopyStatus(undefined);

    const success = await copyToClipboard(raw);
    if (copyAttempt.current !== attempt) return;

    setCopyStatus(success ? "copied" : "failed");
    copyTimer.current = setTimeout(() => {
      if (copyAttempt.current === attempt) setCopyStatus(undefined);
      copyTimer.current = null;
    }, 1500);
  };

  const copyLabel =
    copyStatus === "copied"
      ? dict.copied
      : copyStatus === "failed"
        ? dict.copyFailed
        : dict.copy;

  return (
    <div className="group relative my-3 min-w-0 rounded-lg border bg-card shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b bg-muted/30 px-3 py-2 text-xs text-muted-foreground">
        <LanguageBadge lang={language} />
        <div className="flex flex-wrap items-center gap-2 opacity-80 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100">
          <button
            type="button"
            onClick={() => setIsWrapped(value => !value)}
            className="inline-flex items-center gap-1 rounded px-2 py-1 text-xs transition-colors hover:bg-muted-foreground/10"
            title={isWrapped ? dict.unwrap : dict.wrap}
            aria-pressed={isWrapped}
          >
            <WrapText className="h-3.5 w-3.5" />
            {isWrapped ? dict.unwrap : dict.wrap}
          </button>
          <button
            type="button"
            onClick={handleCopy}
            className={cn(
              "inline-flex items-center gap-1 rounded px-2 py-1 text-xs transition-colors hover:bg-muted-foreground/10",
              copyStatus === "failed" && "text-destructive"
            )}
            title={copyLabel}
            aria-live="polite"
          >
            {copyStatus === "copied" ? (
              <Check className="h-3.5 w-3.5 text-primary" />
            ) : (
              <Copy className="h-3.5 w-3.5" />
            )}
            {copyLabel}
          </button>
        </div>
      </div>
      <pre
        className={cn(
          "m-0 min-w-0 bg-transparent p-4 font-mono text-sm leading-6",
          isWrapped
            ? "whitespace-pre-wrap break-all"
            : "overflow-x-auto whitespace-pre",
          className
        )}
        tabIndex={0}
        {...props}
      >
        <code className={childElement?.props.className}>
          {raw.replace(/\n$/, "")}
        </code>
      </pre>
    </div>
  );
}

const MARKDOWN_COMPONENTS: Components = {
  a: ({ node: _node, className, children, ...props }) => (
    <a
      className={cn(
        "break-all text-primary underline underline-offset-4",
        className
      )}
      target="_blank"
      rel="noopener noreferrer"
      {...props}
    >
      {children}
    </a>
  ),
  p: ({ node: _node, className, children, ...props }) => (
    <p
      className={cn(
        "my-2 whitespace-pre-wrap text-[0.95rem] leading-7",
        className
      )}
      {...props}
    >
      {children}
    </p>
  ),
  img: ({ node: _node, className, alt, ...props }) => (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      className={cn(
        "my-3 h-auto max-w-full rounded-md border shadow-sm",
        className
      )}
      alt={alt || ""}
      loading="lazy"
      {...props}
    />
  ),
  ul: ({ node: _node, className, children, ...props }) => (
    <ul
      className={cn("my-3 list-disc space-y-1 pl-6", className)}
      {...props}
    >
      {children}
    </ul>
  ),
  ol: ({ node: _node, className, children, ...props }) => (
    <ol
      className={cn("my-3 list-decimal space-y-1 pl-6", className)}
      {...props}
    >
      {children}
    </ol>
  ),
  li: ({ node: _node, className, children, ...props }) => (
    <li
      className={cn(
        "marker:text-primary/70 [&>p:first-child]:inline",
        className
      )}
      {...props}
    >
      {children}
    </li>
  ),
  hr: ({ node: _node, className, ...props }) => (
    <hr className={cn("my-4 border-border", className)} {...props} />
  ),
  table: ({ node: _node, className, children, ...props }) => (
    <div className="my-3 w-full overflow-x-auto rounded-md border bg-card shadow-sm">
      <table className={cn("w-full text-sm", className)} {...props}>
        {children}
      </table>
    </div>
  ),
  thead: ({ node: _node, className, children, ...props }) => (
    <thead
      className={cn("bg-muted/60 text-muted-foreground", className)}
      {...props}
    >
      {children}
    </thead>
  ),
  th: ({ node: _node, className, children, ...props }) => (
    <th
      className={cn("whitespace-nowrap border-b px-3 py-2 text-left", className)}
      {...props}
    >
      {children}
    </th>
  ),
  td: ({ node: _node, className, children, ...props }) => (
    <td
      className={cn("border-b px-3 py-2 align-top", className)}
      {...props}
    >
      {children}
    </td>
  ),
  pre: CodeBlock,
  code: ({ node: _node, className, children, ...props }) => (
    <code
      className={cn(
        "rounded border border-muted bg-muted/60 px-1.5 py-0.5 font-mono text-sm text-foreground",
        className
      )}
      {...props}
    >
      {children}
    </code>
  ),
};

export default function MarkdownPro({
  content,
  className,
  locale = "zh-CN",
}: MarkdownProProps) {
  return (
    <DictionaryContext.Provider value={DICT[locale]}>
      <div
        className={cn(
          "min-w-0 break-words text-foreground",
          "[&>p]:my-2 [&>p]:text-[0.95rem] [&>p]:leading-7",
          "[&>h1]:mt-6 [&>h1]:mb-3 [&>h1]:text-2xl [&>h1]:font-semibold",
          "[&>h2]:mt-5 [&>h2]:mb-2 [&>h2]:text-xl [&>h2]:font-semibold",
          "[&>h3]:mt-4 [&>h3]:mb-2 [&>h3]:text-lg [&>h3]:font-semibold",
          "[&>h4]:mt-4 [&>h4]:mb-2 [&>h4]:text-base [&>h4]:font-semibold",
          "[&>ul]:my-3 [&>ul]:list-disc [&>ul]:pl-6",
          "[&>ol]:my-3 [&>ol]:list-decimal [&>ol]:pl-6",
          "[&_*_ul]:list-[circle] [&_*_ul]:pl-6 [&_*_ol]:list-[lower-alpha] [&_*_ol]:pl-6",
          "[&>img]:my-3 [&>img]:rounded-md [&>img]:border [&>img]:shadow-sm",
          "[&>blockquote]:my-4 [&>blockquote]:border-l-4 [&>blockquote]:pl-4 [&>blockquote]:italic [&>blockquote]:text-muted-foreground",
          className
        )}
      >
        <Markdown remarkPlugins={[remarkGfm]} components={MARKDOWN_COMPONENTS}>
          {content}
        </Markdown>
      </div>
    </DictionaryContext.Provider>
  );
}

export async function copyToClipboard(text: string): Promise<boolean> {
  if (typeof navigator === "undefined" || !navigator.clipboard) return false;

  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}
