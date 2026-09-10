# 加载状态页

## 用途

React + Tailwind CSS v4 的通用加载状态参考，提供 `inline`、`overlay` 和 `fullscreen` 三种布局。默认文案不表示具体业务阶段；需要阶段信息时由调用方通过 `message` 传入真实状态。

## 依赖与接入

依赖 React、`clsx`、`tailwind-merge` 和 Tailwind CSS v4，均为当前 PCM React 模板已有依赖。使用 shadcn 常见的 `background`、`muted`、`primary`、`ring` 颜色 token。复制到项目后，若项目已有 `cn`，应替换源码中的局部 `cn`。

`overlay` 使用 `absolute`，父容器需设置定位上下文（通常为 `relative`）和明确尺寸；需要裁切时由父容器设置 `overflow-hidden`。`fullscreen` 填满父容器，不使用 viewport fixed，因此不会主动越过 App Shell。

`overlay` 是非阻塞、非模态的视觉状态，设置了 `pointer-events-none`，不会锁定焦点或拦截父区域操作；若业务必须阻止交互，应使用项目已有的模态或禁用状态方案，不要依赖此参考。

## 可访问性

组件使用 `role="status"` 和礼貌播报，装饰动画不暴露为业务阶段。系统启用 reduced motion 时停止旋转、轨道和流光动画。

## 来源与许可

此文件由用户从原项目导入，本地仅完成 React/CSS 兼容转换与通用化。原项目、作者和许可证尚未确认，不能推断或继承本 collection 的 MIT License；用于产品前必须确认来源与许可。

本地文件：[`source/LoadingPage.tsx`](./source/LoadingPage.tsx)。
