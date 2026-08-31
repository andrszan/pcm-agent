# 场景参考适配检查

只在已通过技术栈闸门并选定具体资产后使用本检查。不要为普通调用创建适配报告、Manifest 或过程文件。

## 1. 技术栈证据

- React、Tailwind v4 和活动 CSS 入口能够从真实工程核对；
- shadcn primitives 实际基于 `@base-ui/react`；
- 现有组合使用 Base UI `render`，不是 Radix `asChild`；
- 目标项目已经具备所选资产需要的 registry components 和 packages；
- 缺失依赖时报告精确缺口，不执行 `shadcn add`、registry 搜索、包安装或技术栈迁移。

## 2. 任务与借用原理

- 用户是谁，正在处理什么对象，要完成什么结果；
- 借用的是信息分组、消息顺序、字段组合、状态表达、操作层级还是趋势表达；
- 参考中的关键决定为什么适合当前任务；
- 保留或改变参考决定都有项目事实依据，不为“看起来不同”随机改动。

## 3. Base UI API

只检查实际使用的 API：

- 自定义 trigger、close 或复合控件使用 `render`，不用 `asChild`；
- `render` 为非 button 元素时按对应组件合同处理 `nativeButton={false}`；
- Select 核对 `items`、placeholder/value、group 和 `alignItemWithTrigger`；
- Checkbox mixed 状态使用 `indeterminate`；
- Accordion 的单选值仍按 Base UI 数组合同处理；
- InputGroup 内使用对应的 `InputGroupInput` 或 `InputGroupTextarea`；
- Dialog、Sheet 和 Drawer 保留可访问名称与焦点合同。

## 4. 项目化内容与视觉

- 使用目标项目自己的对象、动作、状态、术语和内容主次；
- 使用项目已有 token、字体、图标库、圆角、密度和响应式规则；
- 删除或替换 fixture、演示日期、金额、邮箱、文件名、角色、静态选项和趋势结论；
- 不把固定宽度、高度、断点、Card 数量或图表系列当成产品默认；
- 不复制后只换 Logo、颜色和文案。

## 5. 状态与行为

按当前任务补齐适用状态：

- loading、empty、no-result、error、permission、read-only；
- submitted、streaming、stopped、success、retry、recovery；
- 表单校验、保存中、冲突、取消和恢复；
- 操作权限、危险动作、重复提交和幂等；
- 窄屏重排、键盘路径、焦点、滚动和 reduced motion。

参考按钮、链接和状态文案不证明行为已经实现。

## 6. Chat 专项

- `MessageScroller` 是滚动所有者，父容器具备确定高度与 `min-h-0`；
- `messageId` 稳定，turn anchor 与产品消息模型一致；
- 明确是否启用 `autoScroll`，用户主动上滚后不强制拉回；
- 跳到最新、历史 prepend、停止生成和停止后的反馈有明确行为；
- AI SDK 或自有 transport 状态在场景层适配，不进入 Bubble/Message primitive；
- Attachment 区分用户上传、服务端文件和生成产物的生命周期；
- 错误不能只依靠 destructive 颜色，必须有可理解描述和恢复入口。

## 7. Chart 专项

- 图表回答明确的趋势或比较问题，而不是填充 Dashboard；
- series、时间范围、单位、locale、时区和缺失值来自真实数据合同；
- tooltip、legend、轴标签和辅助文本能被用户理解；
- 没有真实趋势任务时不添加 Chart 或 Recharts 依赖。

## 8. 许可、媒体与声明

- 先读资产 README 和 collection MIT License；
- 不把同目录 MIT License 推断为覆盖来源未知文件；
- GitHub 等商标、远程媒体和第三方品牌单独判断；
- 临时或第三方远程 URL 不进入产品运行时；
- SOC 2、SEC registered、加密、供应商、价格和试用等声明必须由项目事实支持；
- 发生实质源码复制时按项目第三方许可约定保留必要 notice。

## 9. 验证移交

实现完成后向当前调用方报告：

- 选中的 asset ID；
- 借用的原理和主要项目化差异；
- 未采用的演示假设；
- 缺失依赖或仍未闭合的状态；
- 需要由当前开发流程执行的测试、真实运行和浏览器验收。

本 Skill 的参考选择不能替代目标项目中的真实渲染与行为验证。
