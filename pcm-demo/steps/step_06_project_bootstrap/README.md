# 第 6 步：项目化基础工程与项目风格定制

## 输入

- 运行状态位于 `project:06_bootstrap_foundation`，产品根仍是零提交、空 index 的 `main`；每个适用基础工程已经是自身 top-level 为目录本身、unborn HEAD、空 index 的 `main` 独立 Git 仓库，不适用端不存在。
- `steps/02.json` 引用两份工作区内非空、非符号链接的产品定义文档。
- `steps/04.json` 提供实际适用工程目录和组装证据；第 3 步选型只用于核验该组装事实。
- `steps/05.json` 是严格成功结果，包含当前 `docs/requirements/项目准备清单.md` 和两份产品定义的无秘密 `readiness_baseline` 指纹；当前文件必须与该指纹一致。
- 适用工程内部的 README、manifest、锁文件、配置、代码和测试由 Agent 按当前现场读取，不由 Python 重复建模。

## 行为

本步骤在同一个数字步骤中顺序运行两个独立 `AgentDecisionLoopSpec`，二者各自拥有 Claude session、decision conversation、XML system snapshot 和私有恢复状态：

1. `project_bootstrap`：显式调用 `/project-bootstrap` 完成有限项目化和真实工程验证；
2. `tailwind_theme`：仅当 `steps/04.json.outputs` 含 `frontend` 时，在 bootstrap 完成后显式调用 `/tailwind-theme`，请其依据产品和前端完成项目风格定制。

两个 Skill 不共用 Claude session，也不写入同一 conversation。两项任务分别只传稳定任务标识 `project_bootstrap` 和 `tailwind_theme`，实际 model 与 effort 由 `model-policy.toml` 解析并按本次进程启动时加载的策略固定；各自恢复调用显式传入本次启动确定的组合。公共循环、步骤编号和 `current_node` 不增加双阶段抽象；步骤程序只在两项适用能力都完成后写 success 并推进第 7 步。

本次项目风格定制调用合同只对新创建的主题任务生效，不重写旧 run 已保存的 XML system snapshot、Claude session 或 success 结果，也不自动为历史成功补跑或升级；既有未完成任务仍按其原 snapshot 和 session 恢复。已发布产品工作区中的 Skill 副本不会随本步骤代码自动更新，需要按发布边界显式同步后才会采用新合同。

### 项目化

`project-bootstrap` prompt 只描述产品定义、已完成准备基线、实际适用工程和白名单化组装事实，不传可能带凭据的 `git_url` 或 `origin`，也不包含步骤号、PCM 节点、session 或 Skill 编排背景。

Agent 负责项目身份、基础配置、README、模板测试迁移、经引用检查的误导残留，以及适用的真实安装、检查、测试、构建、启动、浏览器检查和基础联调。它保持或建立可替换的 Tailwind 基础视觉主题基础设施，但不选择或生成项目专属主题，也不把模板默认主题认定为最终产品主题。

准备基线、受保护运行配置和资源身份是项目化的既定输入。配置键名和结构可以按实际加载合同迁移，但必须复用同一既有资源绑定和真实值，保持资源身份、endpoint 与权限范围，不得重新选择、创建、派生、轮换或替换资源或凭据。完成前必须删除所属仓未忽略的 `.coverage`，或将其加入所属仓 `.gitignore`。

### Tailwind 项目风格定制

有 `frontend` 时，Python 在创建或恢复 `tailwind_theme` conversation 前执行最小确定性 gate：

- `frontend/package.json` 是可读非符号链接普通 JSON；
- `dependencies` 或 `devDependencies` 中存在唯一、可明确判断为 major 4 的直接 `tailwindcss` 声明；
- frontend 自身 Git 可见且未忽略的 CSS 文件中至少一个包含单引号或双引号形式的 `@import "tailwindcss"` CSS-first 入口。

版本无法可靠判断、非 v4 或缺少 CSS-first 证据属于本地模板合同错误，返回 `failed`，不创建主题 session，也不映射为 `blocked`。Python 不实现完整 semver、CSS import graph、token parser 或工作树 fingerprint。

`tailwind-theme` 初始 prompt 只有 `/tailwind-theme`、两份产品定义、`@./frontend` 和“请依据产品和前端完成风格定制”的任务请求，不追加固定属性范围或主题合同。Agent 可自主选择保留默认、采用全部或部分 preset、适配或 custom，并按实际改动执行相称验证、诚实报告结果；具体选择、修改和验证规则以 [`tailwind-theme` Skill](../../../.claude/skills/tailwind-theme/SKILL.md) 为唯一真源。

## 决策与恢复

两个领域分别维护自己的 `DECISION_RULES`，通用 `completed/continue/blocked` 三态不变：

- bootstrap `completed` 只表示项目化与工程验证完成，不包含项目专属基础视觉主题；README 或 `.coverage` 可安全补完时只恢复 `project_bootstrap` session。
- theme `completed` 表示“项目风格定制已完成”；允许 Agent 依据产品和工程事实选择保留默认且无修改完成，步骤不另设固定属性清单或全套验证声明。
- theme `continue` 表示“本次任务未完可继续”，只恢复当前领域自己的 session；theme 失败或阻塞时不会重新执行已 completed 的 bootstrap Agent。
- `blocked` 仍只用于当前环境无法取得的不可替代外部条件。本地版本、文件、主题入口、工作树或状态冲突属于 `failed` 或可继续修正的问题。
- bootstrap blocked 时不创建 theme session/conversation；theme blocked 时保留 bootstrap completed 历史和 theme 自己的恢复锚点。

状态仍保持 `step/current_step: 6` 与 `current_node: project:06_bootstrap_foundation`。重跑时公共循环根据各自 conversation 尾部恢复：bootstrap completed 只重做其 verifier，然后进入或恢复 theme。成功 result 已写而 state 推进中断时，只复验严格 result marker、前序交接、Tailwind gate 和 Git 事实后补状态，不调用 Agent。

## 输出

成功时 `steps/06.json.outputs` 继续记录第 4 步实际适用工程目录，顶层 `applicable` 语义不变，并新增专属布尔：

```json
{
  "tailwind_theme": true
}
```

其严格关系为：

```text
tailwind_theme == ("frontend" in outputs)
```

- 有 frontend 且两个领域完成：`true`；
- backend-only 或无适用工程：`false`；
- blocked/failed result 使用默认 `false`。

字段缺失、不是真实布尔或与 outputs 不一致的旧 success 不可复用。无任何适用工程时仍核验根 Git 后保持两个 Agent 都不调用，以 `applicable:false`、空 outputs、`tailwind_theme:false` 无副作用跳过。有 frontend 的成功摘要中，风格定制部分只写“已完成项目风格定制”，不追加属性清单或验证清单。

最终 success 先写 `steps/06.json`，再推进到 `project:07_solution_design`。完整成功重跑不依赖 session/conversation 作为长期证据，也不会再次调用两个 Agent或负责人模型。

## 运行

```bash
cd /Users/zhou/resource/fireworks/ANDRSZAN/pcm-agent-skills/pcm-demo
uv run python run_step.py --step 6 --run-id <run-id>
```
