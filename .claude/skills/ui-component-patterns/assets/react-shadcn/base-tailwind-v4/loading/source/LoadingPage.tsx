"use client"

import type { CSSProperties, FC } from "react"
import { type ClassValue, clsx } from "clsx"
import { twMerge } from "tailwind-merge"

type Locale = "zh-CN" | "en-US"

type LoadingPageProps = {
  variant?: "inline" | "overlay" | "fullscreen"
  message?: string
  className?: string
  locale?: Locale
}

const DEFAULT_MESSAGES: Record<Locale, string> = {
  "zh-CN": "正在加载...",
  "en-US": "Loading...",
}

function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

const LoadingPage: FC<LoadingPageProps> = ({
  variant = "inline",
  message,
  className,
  locale = "zh-CN",
}) => (
  <div
    className={cn(
      "relative flex items-center justify-center",
      variant === "inline" && "min-h-[120px]",
      variant === "overlay" &&
        "absolute inset-0 z-50 bg-background/60 backdrop-blur-sm",
      variant === "fullscreen" && "h-full min-h-[60vh] w-full",
      className,
    )}
    role="status"
    aria-live="polite"
  >
    <div className="flex flex-col items-center gap-5">
      <div className="relative" aria-hidden="true">
        <div className="relative h-16 w-16 rounded-full bg-primary/20 shadow-lg ring-2 ring-ring/50">
          <div className="absolute inset-2 rounded-full bg-primary/40 blur-sm" />
          <div className="absolute inset-[22%] rounded-full bg-primary" />
        </div>

        <div className="pointer-events-none absolute -inset-2 rounded-full">
          <div
            className="h-full w-full rounded-full"
            style={{ mask: "radial-gradient(transparent 58%, black 60%)" }}
          >
            <div
              className="loading-page-ring h-full w-full rounded-full"
              style={{
                background:
                  "conic-gradient(from 0deg,var(--ring),transparent 60%)",
              }}
            />
          </div>
        </div>

        <OrbDot delay="0s" />
        <OrbDot delay="0.6s" />
        <OrbDot delay="1.2s" />
      </div>

      <div className="w-64 max-w-[72vw] space-y-2" aria-hidden="true">
        <SkeletonLine width="100%" />
        <SkeletonLine width="92%" />
        <SkeletonLine width="84%" />
      </div>

      <div className="text-sm text-muted-foreground">
        {message ?? DEFAULT_MESSAGES[locale]}
      </div>
    </div>

    <style>{`
      @keyframes loading-page-ring-spin {
        to { transform: rotate(360deg); }
      }

      @keyframes loading-page-orbit {
        0% {
          transform: rotate(0deg) translateX(32px) rotate(0deg);
          opacity: 0.8;
        }
        50% { opacity: 1; }
        100% {
          transform: rotate(360deg) translateX(32px) rotate(-360deg);
          opacity: 0.8;
        }
      }

      @keyframes loading-page-shimmer {
        from { transform: translateX(-100%); }
        to { transform: translateX(300%); }
      }

      .loading-page-ring {
        animation: loading-page-ring-spin 2.2s linear infinite;
      }

      .loading-page-orb {
        animation: loading-page-orbit 2.4s linear infinite;
      }

      .loading-page-shimmer {
        animation: loading-page-shimmer 1.2s ease infinite;
      }

      @media (prefers-reduced-motion: reduce) {
        .loading-page-ring,
        .loading-page-orb,
        .loading-page-shimmer {
          animation: none;
        }
      }
    `}</style>
  </div>
)

function OrbDot({ delay }: { delay: string }) {
  return (
    <div
      className="loading-page-orb absolute left-1/2 top-1/2 h-2 w-2 -translate-x-1/2 -translate-y-1/2"
      style={{ animationDelay: delay }}
    >
      <div className="h-2 w-2 rounded-full bg-primary shadow-[0_0_12px_var(--color-ring)]" />
    </div>
  )
}

function SkeletonLine({ width }: { width: CSSProperties["width"] }) {
  return (
    <div
      className="h-2 overflow-hidden rounded-sm bg-muted"
      style={{ width }}
    >
      <div className="loading-page-shimmer h-full w-1/3 bg-ring/30" />
    </div>
  )
}

export type { LoadingPageProps, Locale }
export default LoadingPage
