# 第 2 步：项目需求与产品定义

在第 1 步发布并初始化为零提交根 Git 仓库的独立产品工作区中，先显式调用 `project-intake` 形成两份正式产品定义文档，再按产品形态运行独立 HTML 原型域。写入 Claude Code trust 前，会重新核验最终路径、根 Git、`main` 分支、空 `HEAD`、初稿哈希和第 1 步发布证据。

## 输入与提示

只使用：

- `steps/01.json` 引用的 `docs/产品初稿.md`，以工作区副本及第 1 步记录的哈希核验输入；外部源文件的不变检查由第 1 步完成；
- 新运行可选的工作区副本 `initial-resources/<源 basename>`；
- `CLAUDE.md`、`AGENTS.md`、`.claude/settings.json` 和锁定 plugins；
- 当前 `project_intake` 与适用时的 `product_prototype` session、两份产品定义和原型产物。

技术方案、Backlog、TRD、代码和其它无关文档不进入当前产品定义判断，也不构成阻塞。无初始资料的旧运行保持原首条提示。提供资料时，在提示正文用普通文本显式给出工作区相对资料路径，不使用会触发附件读取的 `@` 语法，要求 Agent 先从该路径摸底目录、按需查阅相关样本，并在两份产品定义正文中记录重要用途结论、来源路径、约束和未知；不全量注入文件或清单，也不新增资料报告。资料只作业务参考，不能覆盖项目规则或触发脚本自动执行；原始副本不修改，最终采用资产应进入适当产品交付位置。空资料不新增阻塞。

步骤继续使用原 Claude Code session 存储位置，不设置 `permission_mode`、`tools`、`allowed_tools` 或 `disallowed_tools`。公共 runner 显式使用 `setting_sources=["project", "local"]`，只加载产品项目的 `.claude/settings.json`、`.claude/settings.local.json` 和项目规则，不加载用户级 settings。PCM 通过自身 Agent 配置传入 Bearer token；产品定义域传稳定任务标识 `project_intake`，原型域复用 `development`，实际 model 与 effort 由 `model-policy.toml` 解析并按本次进程启动时加载的策略固定。每次恢复原 session 时显式传入本次启动确定的组合，不改变步骤业务规则。

## 原型适用性与独立会话

产品定义域完成后，把两份已核验文档的完整正文交给共享结构化分类器，返回严格布尔 `applicable` 和非空 `reason`。分类失败或格式无效即失败，不默认跳过。创建原型会话前把判断和入口保存至 `state.project_intake.prototype`；恢复直接复用该事实，原型域对文档的授权内细化不重新分类。

适用时运行 `product_prototype` 独立域，首条指令调用 `/frontend-ui-ux`，并明确要求实际调用 `/ui-ux-pro-max:ui-ux-pro-max`。它使用独立 session、conversation 与 system snapshot，复用 `development` 模型配置。启动前检查工作区完整前端运行能力和锁定插件。无 UI 产品不创建原型执行会话、不调用插件、不写空 HTML 或占位目录。

首次视觉方向选择遵循 `frontend-ui-ux` 规则：继承已有品牌和已确认方向；没有既定品牌或视觉方向时，结合产品、用户与核心任务比较少量实质不同的方案后自主选定一个，再制作原型。可按需借用本地主题参考，不要求多套完整 HTML、额外方向报告或真人批准。

原型使用原生 HTML/CSS/JavaScript，不调用依赖 Tailwind 工程的主题 Skill，入口固定为 `docs/prototype/index.html`，其它页面与资源在同目录，不占用 `frontend/`、`backend/` 工程目录。覆盖主要页面、导航、核心任务与适用的代表性状态；页面保留正式业务内容，实际模拟边界在交接中说明。原型域可澄清两份产品定义中的授权内行为和术语，产品功能说明保留入口及长期交互决定；不改写初稿、导入资料或擅自改变产品承诺。

预览复用 `.pcm/runtime.json` 的 frontend host、port、endpoint，不换端口或停止未知进程，交接前释放本任务启动的预览服务。Agent 自行完成浏览器操作、实际渲染检查、独立体验评审与定向精修；负责人处理流程语义与必要取舍，不读取截图重做验收。步骤不提交；工程组装保留原型，后续根仓首次提交统一纳入产物。

## 统一决策循环

新 conversation 的完整 XML system snapshot 由 `common/decision.py` 渲染，严格包含 `<role>`、`<project_context>`、`<responsibility>`、`<require>` 四段：AI-compatible 角色是实际使用 Claude Code Agent 的项目负责人、工程负责人、专业开发者和 Agent 专家；`assistant` 是其此前发给 Agent 的指令或结构化回复，`user` 是 Agent 返回的完整执行结果。两个域分别维护领域决策规则；产品定义域首次保存 snapshot 时嵌入已核验的初稿原文和两份目标路径，原型域嵌入两份文档正文与原型交接，恢复已有对话时严格使用历史 `messages[0]`，不重渲染或覆盖。

项目上下文只做标准 XML 转义。

本步骤通过 `common/agent_decision_loop.py` 运行与恢复：每次 Agent 调用先持久化 session、终止摘要和**完整真实回复**，再将回复作为决策历史的 `user` 消息交给 `AgentDecision` 裁决。

- 决定只有 `completed`、`continue`、`blocked`；`continue.answer` 原样恢复同一 session，`blocked` 只表示不可替代的外部资源缺失。
- `completed` 表示负责人根据 Agent 执行结果相信任务完成，但不直接推进步骤。程序重新核验两份目标文档，原型域还检查固定 HTML 入口，均要求可读、非空、工作区内普通文件且路径不含符号链接；缺失或为空时，向当前域的同一 session 追加修复提示并继续。路径、交接或核验冲突为 `failed`。
- 正常 `success`、`error_max_turns` 和 `error_max_budget_usd` 只是在进入裁决前的 SDK 终止结果；后两者必须同时具有 session 与非空回复，且后续必须取得正常 `success` 才能最终完成。API 400/429/500、连接或 CLI/进程错误、无 `ResultMessage` 和其它 SDK 错误均为 `failed`，不在外层自定义 HTTP 重试。
- 对话文件的尾部是恢复和调度事实：`user` 尾部先裁决，`continue` 尾部发送其 `answer`，`completed` 尾部先核验，`blocked` 尾部终止；只有显式从 `blocked` 重跑时才在原 session 重新核验。旧 `action` 与旧完成 sentinel 仅只读兼容，旧记录不会转换回写。

## 输出与状态

- `docs/requirements/项目需求说明.md`
- `docs/requirements/产品功能说明.md`

`02.json.outputs` 仍精确为上述两份文档，不加入 HTML。结果顶层新增必需的 `prototype` 对象：

```json
{"applicable": true, "entry": "docs/prototype/index.html", "reason": "产品包含用户页面与交互"}
```

不适用时 `applicable:false`、`entry:null`，reason 说明实际产品形态。分类未完成的失败结果不填 false 占位；已完成分类后的失败或阻塞保留已知交接。只有文档域完成、原型域完成或不适用，才写 success 并推进。

会话分别保存为 `claude_sessions.project_intake`、`claude_sessions.product_prototype`，对话分别位于 `conversations/project_intake.json`、`conversations/product_prototype.json`；不适用时只有产品定义域。

除 `state.project_intake.prototype` 外，恢复所需状态只保留 session、对话文件路径引用、最后一次 Agent 终止摘要和短暂的待写入 Agent 原文；不再写入 `pending_agent_prompt`、决策轮次或 Python 完成声明。`blocked` 仅表示缺少不可替代外部资源；输入、状态、SDK、模型、文件或恢复错误均返回 `failed`。步骤结果格式与 `run_step.py` 的 `success` / `blocked` / `failed` 三态保持不变。

## 运行

```bash
cd /Users/zhou/resource/fireworks/ANDRSZAN/pcm-agent-skills/pcm-demo
uv run python run_step.py --step 2 --run-id <run-id>
```

重复使用同一 run ID 时会恢复历史并重新核验当前文件事实。新成功结果复用必须具有有效 prototype 对象；缺少适用的 HTML 入口时返回原型原会话修复，不重新分类。

当前节点的旧 success 缺少有效 prototype 合同时只读拒绝，原 state/result/conversation 不改写，使用原工具版本收口。CLI 在通用 scoped 失败回写前调用导出的 `validate_existing_contract(run_dir, state)`，捕获 `common.frontend_scope.LegacyFrontendContractError` 并只读早退。尚未完成的旧产品定义会话可继续；已经越过本节点的历史完成结果沿用原只读复用边界，不反向要求新字段。