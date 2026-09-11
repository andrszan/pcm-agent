# 加载状态页

## 用途

React + Tailwind CSS v4 的通用加载状态参考，提供 `inline`、`overlay` 和 `fullscreen` 三种布局。默认文案不表示具体业务阶段；需要阶段信息时由调用方通过 `message` 传入真实状态。

## 依赖与接入

依赖 React、`clsx`、`tailwind-merge` 和 Tailwind CSS v4。使用 shadcn 常见的 `background`、`muted`、`primary`、`ring` 颜色 token。复制到项目后，若项目已有 `cn`，应替换源码中的局部 `cn`。

`overlay` 使用 `absolute` 和普通指针命中，父容器需设置定位上下文（通常为 `relative`）和明确尺寸；需要裁切时由父容器设置 `overflow-hidden`。它会阻挡覆盖区域内的指针操作，但不是模态框：不锁定焦点、不设置 `aria-modal`，也不替代业务层的禁用、取消、超时或错误恢复。`fullscreen` 填满父容器，不使用 viewport fixed，因此不会主动越过 App Shell。

## 可访问性

组件使用 `role="status"` 和礼貌播报，装饰动画设为隐藏，不冒充真实业务阶段。系统启用 reduced motion 时停止旋转、轨道和流光动画。

本地文件：[`source/LoadingPage.tsx`](./source/LoadingPage.tsx)。
