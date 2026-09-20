# 第 6 步：项目化基础工程、项目风格定制与基础品牌资产

## 输入

- 运行状态位于 `project:06_bootstrap_foundation`，产品根仍是零提交、空 index 的 `main`；每个适用基础工程已经是自身 top-level 为目录本身、unborn HEAD、空 index 的 `main` 独立 Git 仓库，不适用端不存在。
- `steps/02.json` 引用两份工作区内非空、非符号链接的产品定义文档。
- `steps/04.json` 提供实际适用工程目录和组装证据；第 3 步选型只用于核验该组装事实。
- `steps/05.json` 是严格成功结果，包含当前 `docs/requirements/项目准备清单.md` 和两份产品定义的无秘密 `readiness_baseline` 指纹；当前文件必须与该指纹一致。
- 适用工程内部的 README、manifest、锁文件、配置、代码和测试由 Agent 按当前现场读取，不由 Python 重复建模。

## 行为

本步骤在同一个数字步骤中顺序运行三个独立 `AgentDecisionLoopSpec`，各自拥有 Claude session、decision conversation、XML system snapshot 和私有恢复状态：

1. `project_bootstrap`：显式调用 `/project-bootstrap` 完成有限项目化和真实工程验证；
2. `tailwind_theme`：仅当 `steps/04.json.outputs` 含 `frontend` 时，在 bootstrap 完成后显式调用 `/tailwind-theme`，请其依据产品和前端完成项目风格定制；
3. `brand_assets`：同样仅 frontend 适用，在 theme 完成后显式调用 `/media-assets`，准备并接入基础品牌资产。

三个任务不共用 Claude session，也不写入同一 conversation。任务标识 `project_bootstrap`、`tailwind_theme`、`brand_assets` 分别对应模型策略中的 `6.bootstrap`、`6.theme`、`6.brand`；实际 model 与 effort 由 `model-policy.toml` 按本次进程启动时加载的策略固定，恢复时显式传入。公共循环、步骤编号和 `current_node` 不增加阶段抽象；步骤程序只在全部适用任务完成后写 success 并推进第 7 步。

本次项目风格定制调用合同只对新创建的主题任务生效，不重写旧 run 已保存的 XML system snapshot、Claude session 或 success 结果，也不自动为历史成功补跑或升级；既有未完成任务仍按其原 snapshot 和 session 恢复。已发布产品工作区中的 Skill 副本不会随本步骤代码自动更新，需要按发布边界显式同步后才会采用新合同。

### 项目化

`project-bootstrap` prompt 只描述产品定义、已完成准备基线、实际适用工程和白名单化组装事实，不传可能带凭据的 `git_url` 或 `origin`，也不包含步骤号、PCM 节点、session 或 Skill 编排背景。

Agent 负责项目身份、基础配置、README、模板测试迁移、经引用检查的误导残留，以及适用的真实安装、检查、测试、构建、启动、浏览器检查和基础联调。它保持或建立可替换的 Tailwind 基础视觉主题基础设施，但不选择或生成项目专属主题，也不把模板默认主题认定为最终产品主题。

准备基线、受保护运行配置和资源身份是项目化的既定输入。配置键名和结构可以按实际加载合同迁移，但必须复用同一既有资源绑定和真实值，保持资源身份、endpoint 与权限范围，不得重新选择、创建、派生、轮换或替换资源或凭据。模板声明需按资源绑定保留唯一派生变体时，以准备清单的最终绑定为权威选择，完整收口未选变体的目录、依赖和锁文件、配置与公开示例、构建测试入口、README 和适用本地 Agent 规则；Python 不解析清单正文或保存数据库枚举。完成前必须删除所属仓未忽略的 `.coverage`，或将其加入所属仓 `.gitignore`。

### Tailwind 项目风格定制

有 `frontend` 时，Python 在创建或恢复 `tailwind_theme` conversation 前执行最小确定性 gate：

- `frontend/package.json` 是可读非符号链接普通 JSON；
- `dependencies` 或 `devDependencies` 中存在唯一、可明确判断为 major 4 的直接 `tailwindcss` 声明；
- frontend 自身 Git 可见且未忽略的 CSS 文件中至少一个包含单引号或双引号形式的 `@import "tailwindcss"` CSS-first 入口。

版本无法可靠判断、非 v4 或缺少 CSS-first 证据属于本地模板合同错误，返回 `failed`，不创建主题 session，也不映射为 `blocked`。Python 不实现完整 semver、CSS import graph、token parser 或工作树 fingerprint。

`tailwind-theme` 初始 prompt 只有 `/tailwind-theme`、两份产品定义、`@./frontend` 和“请依据产品和前端完成风格定制”的任务请求，不追加固定属性范围或主题合同。Agent 可自主选择保留默认、采用全部或部分 preset、适配或 custom，并按实际改动执行相称验证、诚实报告结果；具体选择、修改和验证规则以 [`tailwind-theme` Skill](../../../.claude/skills/tailwind-theme/SKILL.md) 为唯一真源。

### 基础品牌资产

`brand_assets` 读取两份产品定义、实际 frontend 和适用的 `.pcm/runtime.json`，优先复用已有正式品牌资产；没有既定品牌时结合产品和当前主题制作。基础交付是页面品牌标识与浏览器 favicon，保持同一视觉身份；Apple Touch Icon、PWA 图标、社交分享图及背景变体按实际用途决定，不自动增加业务功能或插画。

Agent 负责生成、选择、派生、实际看图、质量检查、前端接入与适用验证。品牌文字保持可编辑；PNG 和 SVG 按真实用途选择，不强制矢量化。favicon 要检查小尺寸辨识度，最终文件按目标前端已有约定落地并完成必要引用，不依赖工具路径或临时 URL。不存在相应页面时不为展示 Logo 提前开发页面。

整套共享最多 8 次生成调用，首次包含在内，由 Agent 在提示约束下自行调度；满足用途即可停止，继续或恢复时沿用候选和已用次数，不重新分配额度。额度耗尽或生成服务不可用时允许合格简洁 SVG／文字标识兜底。Python 不增加计数器、预算状态、配置项或图像质量检查，也不以生图调用发生作为完成条件。媒体凭据仍是工作区工具私有配置，不进入目标产品运行配置或开发资源清单。

负责人只依据 Agent 回复判断交付是否完成，防止明确遗漏，不读文件、看图评选或复做验收，不要求逐项证明或“一切无问题”的完成声明。品牌任务的授权和尝试规则由 PCM 传入，不修改或耦合其它 Skill。完整范围见[基础品牌资产准备 TRD](../../docs/trd/20260910-PCM%20Demo%20基础品牌资产准备%20TRD.md)。

## 决策与恢复

三个领域分别维护自己的 `DECISION_RULES`，通用 `completed/continue/blocked` 三态不变：

- bootstrap `completed` 只表示项目化与工程验证完成，不包含项目专属基础视觉主题；声明派生变体的模板还必须已经按准备清单最终绑定收口，未选变体在目录、依赖、配置、README 和本地规则中没有残留。README、派生变体或 `.coverage` 可安全补完时只恢复 `project_bootstrap` session。
- theme `completed` 表示“项目风格定制已完成”；允许 Agent 依据产品和工程事实选择保留默认且无修改完成，步骤不另设固定属性清单或全套验证声明。
- theme `continue` 表示“本次任务未完可继续”，只恢复当前领域自己的 session；theme 失败或阻塞时不会重新执行已 completed 的 bootstrap Agent。
- brand `completed` 表示基础品牌资产已交付并完成适用接入，允许合理复用或合格兜底；明确尚未完成但可继续处理时返回 `continue`。
- `blocked` 仍只用于当前环境无法取得的不可替代外部条件。本地版本、文件、主题入口、工作树或状态冲突属于 `failed` 或可继续修正的问题。
- 前序 blocked 时不创建后续任务的 session/conversation；brand 失败或阻塞时保留前两项 completed 历史，只恢复品牌原会话。人工恢复消息只进入当前 blocked 领域。

状态仍保持 `step/current_step: 6` 与 `current_node: project:06_bootstrap_foundation`。重跑时公共循环根据各自 conversation 尾部恢复：已 completed 的任务只重做其 verifier，再进入下一个任务，不重复调用已完成 Agent。品牌 completed 后步骤推进中断同样复用完成历史。

已成功的历史第 6 步不补跑品牌任务，也不因缺少品牌会话而失败，不宣称历史产品已补齐新资产。尚未完成的旧 bootstrap/theme 沿用原 snapshot 和 session，完成后再创建品牌任务。成功 result 已写而 state 推进中断时，只复验严格 result marker、前序交接、Tailwind gate 和 Git 事实后补状态，不调用 Agent。

## 输出

成功时 `steps/06.json.outputs` 继续记录第 4 步实际适用工程目录，顶层 `applicable` 语义不变，保留既有专属布尔：

```json
{
  "tailwind_theme": true
}
```

其严格关系为：

```text
tailwind_theme == ("frontend" in outputs)
```

- 有 frontend 且全部适用领域完成：`true`；
- backend-only 或无适用工程：`false`；
- blocked/failed result 使用默认 `false`。

字段缺失、不是真实布尔或与 outputs 不一致的旧 success 不可复用。无任何适用工程时仍核验根 Git 后保持所有 Agent 都不调用，以 `applicable:false`、空 outputs、`tailwind_theme:false` 无副作用跳过。有 frontend 的成功摘要中，风格定制部分只写“已完成项目风格定制”，不追加属性清单或验证清单。

品牌任务不新增 result 必需字段；其新任务完成事实保存在既有领域状态和对话中，不改变历史 success 的准入要求。最终 success 先写 `steps/06.json`，再推进到 `project:07_solution_design`。完整成功重跑不依赖 session/conversation 作为长期证据，也不会再次调用 Agent 或负责人模型。

## 运行

```bash
cd /Users/zhou/resource/fireworks/ANDRSZAN/pcm-agent-skills/pcm-demo
uv run python run_step.py --step 6 --run-id <run-id>
```
