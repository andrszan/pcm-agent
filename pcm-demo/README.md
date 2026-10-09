# PCM 自动化流程 Demo

PCM Demo 是正式 PCM 开发前的本地流程验证工具。它用 Python 串联确定性操作、AI-compatible 负责人决策和 Claude Agent SDK，在仓库外的独立产品工作区中执行真实产品开发流程。

当前已实现第 1～18 步、阶段一需求循环、独立产品质量迭代和可选的人工反馈迭代：产品初稿经初始化、设计和 Backlog 进入逐需求开发、验证、复盘、提交与 ff-only 合并；完整产品可由新的质量 run 接入：完整审计、负责人处置、增量 Backlog 与登记后，复用原需求开发循环，完成本次修复后结束。质量阶段完成后，可提交一批人工反馈，由独立反馈 run 完成核验、取舍、文档收尾及必要的增量开发。第 6 步在适用时完成项目风格定制和基础品牌资产准备。`run_all.py` 默认只执行阶段一，显式 `--with-quality` 才串联独立质量运行。

产品定义中的 HTML 原型与逐需求独立前端先行已接入当前执行代码，初始化、质量与反馈需求开发共用该路线。当前合同、恢复边界及实际验证状态见 [原型设计与逐需求前端先行 TRD](docs/trd/20261009-PCM%20Demo%20原型设计与逐需求前端先行重构%20TRD.md)。

Demo 只验证流程可行性，不建设正式 PCM 的 Web 管理界面、数据库、分布式调度、部署或生产运维能力。当前支持同一 Demo checkout 在容量限制内并发执行不同产品；同一产品始终互斥。

产品项目位于：

```text
<PCM_WORKSPACE_ROOT>/<project_directory_name>/
```

`runs/<run-id>/` 只保存编排状态、结果、对话、诊断和计时，不是产品项目目录。

## 验证目标

第一轮端到端黄金输入是 [`docs/prd/修迹-产品需求文档-v1.md`](../docs/prd/修迹-产品需求文档-v1.md)。它只作为正常产品初稿输入，不触发专用步骤或硬编码结果；首轮范围以初稿中的当前必须实现内容为准。

完整 Demo 的完成标准是：统一入口能够顺序执行和恢复全部已定义流程；每个适用步骤有真实成功证据；正式需求均经过第 13～18 步；产品完成真实安装、测试、构建、启动、联调和浏览器验收；适用仓库最终位于预期 `main` 且工作树清楚；源初稿前后保持不变且产品项目内副本与其一致；至少验证一次外部阻塞解除后的恢复和一次进程中断后的原节点恢复；阶段二完成全产品审计、候选分流、本次修复及相关回归。程序测试通过与实际产品端到端交付分别报告；质量周期的真实集成范围及尚未覆盖项见[产品质量迭代 TRD](docs/trd/20260922-PCM%20Demo%20产品质量迭代工作流%20TRD.md)，不能用隔离编排测试宣称某个产品已经通过质量审计。

完整流程语义与最终停止条件以 [PCM 程序化调度的 AI Agent 产品开发流程](../docs/pcm/PCM版AI%20Agent自动化流程设计.md) 为准。

## 环境配置

要求 Python 3.11+、`uv` 和 Git，并具备可访问的 AI-compatible Responses API、Claude Agent SDK Messages 网关，以及当前产品所需的模板和开发资源权限。

```bash
cd pcm-demo
uv sync
test -e .env || cp .env.example .env
```

只在首次配置且 `.env` 不存在时复制示例，避免覆盖已有本地凭据。配置入口：

- [`.env.example`](.env.example)：AI-compatible、Agent 网关与认证、自动压缩窗口、Claude Code 单次调用重试次数、统一代理、工作区、模板和开发资源路径；实际 `.env` 必须保持 Git 忽略。
- [`model-policy.toml`](model-policy.toml)：Claude Agent 各任务使用的真实 `model` 与 `effort`。模型策略不再从 `.env` 的低、中、高变量读取。
- 模型提供商切换：`.env` 中设置 `PCM_PROVIDER=<名称>` 后，程序叠加读取 Git 忽略的 `.env.d/<名称>.env`（提供商各自的 LLM_* 与 PCM_AGENT_* 配置），模型策略同步改用 `model-policy.<名称>.toml`；两个文件都必须存在。留空时直接使用 `.env` 与 `model-policy.toml`。切换提供商或修改 `model-policy.toml` 前，都先停止当前编排，再用 `uv run python run_all.py --resume <run-id>` 从原节点恢复。
- 产品工作区中的 `.env`：由流程按项目合同维护，不与 `pcm-demo/.env` 混用。

AI-compatible 与 Claude Agent SDK 使用独立配置，不相互回退。`PCM_AGENT_WORKSPACE_ENV_FILE` 只由第 1 步安装为产品工作区根的受保护工具配置，不并入 SDK 子进程环境，也不作为目标产品运行配置或开发资源清单。

修改 `model-policy.toml` 前必须停止当前编排，再使用 `uv run python run_all.py --resume <run-id>` 从原节点恢复；`run_all.py` 每次启动或恢复只读取一次策略，运行中不会热加载。策略必须完整有效，程序不会用默认模型、环境变量或命令行覆盖兜底。

## 远程仓库与推送

后续新产品默认启用远程同步：第 8 步本地首次提交后建立 private 产品 subgroup 与适用空仓、配置 SSH `origin` 并首推；阶段一、阶段二和阶段三每批收尾再次同步各仓 `main`。父 group 由 `PCM_GITLAB_GROUP_URL` 配置，产品名沿用首次工程目录名，仓库分别为 `<项目名>`、适用的 `<项目名>-frontend` 和 `<项目名>-backend`。

在 `pcm-demo/.env` 中设置父 group 的完整 HTTPS 地址，例如：

```dotenv
PCM_GITLAB_GROUP_URL=https://gitlab.com/baiyiyu/andrszan/pcm-projects
```

支持 GitLab.com 的普通 group URL 和带 `/groups/` 前缀的浏览器地址，进程环境优先于 `.env`。新 run 创建时固定解析后的 group 路径，恢复及后续质量／反馈运行沿用该绑定；修改配置只影响之后的新产品，不迁移已有远程仓库。旧记录已有 `parent_group` 时继续使用其完整路径；尚未记录任何父组的旧运行在首次准备时按配置绑定。

在受保护的 `pcm-demo/.env` 或进程环境提供 `PCM_GITLAB_TOKEN`，对应身份须有目标父 group 下的建组、建仓与必要设置权限；本机 SSH 身份另须能推送这些项目的 `main`。令牌只供 PCM API 使用，不写进产品配置、URL、命令参数或对话。新运行先核验配置与 API 身份；缺失真实授权会 blocked，不伪造凭据或跳过同步。能力代码可在本地安装，但真实 GitLab 建仓／SSH 链路的当前验收状态以 [远程仓库与推送 TRD](docs/trd/20261005-PCM%20Demo%20GitLab远程仓库与推送%20TRD.md) 为准。

临时修改先完成本地提交和必要合并，再执行：

```bash
# 当前目录为 pcm-demo；读取产品已有登记与适用仓清单，取得产品锁。
uv run python push_project.py --workspace /absolute/path/to/product
```

该命令不启动完整工作流、不加载模型、不创建 run、不修改业务完成状态。工作树不干净、分支不是 main、产品锁被占用或远程冲突时停止，不自动提交、切分支、拉取或强推。逐仓报告目标提交和成功、已一致、失败、尚未执行；三仓同步不是原子操作。被忽略配置、数据库和外部文件不属于 Git 备份。

在产品工作区也可显式调用 `/push-changes`，或使用其中的标准库脚本推送明确指定的单仓分支：

```bash
python3 .claude/skills/push-changes/scripts/push.py \
  --repo /absolute/path/to/repository --branch req/example
```

缺少远程同步约定的旧 run 保持原行为，不补建、不迁移。旧产品手工配置远程后可用上述手动入口；新的质量／反馈 run 仅继承来源已经启用的自动同步约定。当前工作区更新不会自动发布远程模板或刷新旧产品的 Skill。

自动推送失败保留已完成需求、部分远程成功和固定目标 SHA，恢复只补当前收尾；目标版本漂移时停止，不把后来的提交纳入旧阶段。阶段一最后一条需求通过单步完成后，须用 `run_all.py --resume <run-id>` 进入 `phase_1:complete`；远程成功后才进入 `phase_1:completed` 并可串联质量阶段。阶段二、三分别用原 `run_quality.py --resume`、`run_feedback.py --resume` 恢复 complete 节点。手动补推成功后仍需恢复原 run，由它核验并发布自己的完成状态。Git 网络错误不进入 Agent SDK 的 6 小时重试。

## 启动与恢复

### 新建阶段一运行

流程从第 1 步建立工作区开始。入口会把产品初稿和可选初始资料交给第 1 步；产品初稿必须在创建 `runs/<run-id>/` 和调用 AI 前通过可读、UTF-8、非空白检查。

```bash
uv run python run_all.py \
  --product-draft "../docs/prd/修迹-产品需求文档-v1.md" \
  --run-id "mendmark-20260901"
```

`--run-id` 可省略。常用可选参数：

```text
--initial-resources <普通文件或目录>   只用于新运行，发布后不再同步源路径
--workspace-root <绝对路径>           覆盖 PCM_WORKSPACE_ROOT
--catalog-path <绝对路径>             覆盖 PCM_TEMPLATE_CATALOG
--git-user-name <提交姓名>            与 --git-user-email 成对提供
--git-user-email <提交邮箱>           覆盖本次新产品的默认提交身份
```

新产品默认提交姓名为第 1 步解析出的 `project_directory_name`，邮箱为 `<project_directory_name>@example.com`，例如 `rulefolio <rulefolio@example.com>`；邮箱仅用于提交署名展示。需要指定身份时，在上述新建命令中同时追加 `--git-user-name "规则研发团队" --git-user-email "team@example.com"`。身份保存在本次运行状态中，第 8 步首次提交前统一写入产品根仓与适用前后端仓库的本地 Git 配置；不修改全局配置、其它项目或已有提交历史。没有身份记录的旧运行保持原行为。

### 恢复已有运行

```bash
uv run python run_all.py --resume <run-id>
```

恢复只进入 `state.json` 指向的当前节点，并重新核验该节点负责的现场；不会从头重跑已完成流程。Git 提交身份继续使用运行状态中的记录，`--resume` 不接受重新指定姓名和邮箱。进程退出会释放实时执行锁，但产品登记及配对端口会继续保留。

### 独立产品质量迭代

来源必须是已完成且没有活动需求的阶段一或质量 run；使用当前产品的 clean main，保留产品 owner、端口和资源，所有来源执行记录只读。未知未提交文件不会被自动清理或提交。

```bash
uv run python run_quality.py --source-run <completed-run-id> --run-id <quality-run-id>
uv run python run_quality.py --resume <quality-run-id>

# 只执行 state 当前指向的质量命名节点
uv run python run_quality.py --resume <quality-run-id> --node quality:audit

# 当前需求进入数值步骤后，仍可使用原单步入口
uv run python run_step.py --step <13-18> --run-id <quality-run-id>
```

审计与入池从完整有序对话提取当前有效成果，后续局部补证不替代整份报告。分流只依据已保存审计材料作负责人处置；有必要覆盖缺口时不能最终收口。公共 Responses API 请求使用 `timeout=None`，允许长时间推理。

当前 Backlog 的正式 ID 必须能与来源完成记录对应；标题、旧指纹和当前 main 的正常变化不要求回写历史。新增正式需求在本周期单独登记，原发现回归属于提交合并前的开发完成条件；本批需求全部完成后结束阶段二。

每个质量 run 执行一次完整审计；中断恢复续接原任务。准备、审计和入池的 Agent 恢复消息通过 `--resume-message-file` 传入，适用边界与下节一致。分流直接调用负责人 Responses API，使用 `--resume` 重试请求。收口时仍有独立必要缺口，则在 `quality:complete` 沿原审计会话定向补证；条件缺失保持阻塞，补齐后可用同一 run 恢复并传入原会话消息，不重跑完整审计或已完成需求。

在新建或恢复阶段一的命令中追加 `--with-quality`，即可在阶段一成功后自动启动独立的 `<阶段一-run-id>-quality`；同源质量 run 已存在时恢复，不重复创建。后续另一个质量周期以最近完成的质量 run 为来源。质量运行有自己的 run 锁，与前序共用产品互斥边界，不重新认领产品或重新分配端口。

### 独立人工反馈迭代

来源必须是已成功结束、没有活动或待开发需求的质量 run 或反馈 run。新批次附着同一产品，原记录只读；当前适用仓库须位于 clean main。没有反馈时无需启动，不影响前两阶段完成。

```bash
uv run python run_feedback.py --source-run <completed-quality-or-feedback-run> \
  --run-id <feedback-run-id> --feedback-file /absolute/path/to/feedback.md

# 可选：重复传入附件，以及本批目标或授权说明
uv run python run_feedback.py --source-run <completed-quality-or-feedback-run> \
  --run-id <feedback-run-id> --feedback-file /absolute/path/to/feedback.md \
  --attachment /absolute/path/to/screenshot.png \
  --intent-file /absolute/path/to/batch-intent.md

uv run python run_feedback.py --resume <feedback-run-id>
uv run python run_feedback.py --resume <feedback-run-id> --node feedback:triage
uv run python run_step.py --step <13-18> --run-id <feedback-run-id>
```

反馈正文必须是可读、非空白的 UTF-8 普通文本。新建时保存本批正文、来源路径、附件路径和可选意图，原始文件不改动；附件保持可访问。恢复不重新读取后来编辑的原正文，也不接受替换初始材料的参数。新诉求使用下一批；本批澄清或解除条件可按下节合同向当前原会话传入 `--resume-message-file`。

分诊在独立会话核验整批材料，负责人在已有授权内确定处理目标。缺陷、体验改进和已授权新增能力均可进入增量 Backlog，复用原需求开发链，并在提交合并前验证原场景或采纳的目标结果。无纳入项时仍提交实际产生的反馈处置文档，但不创建空需求或空提交。

“本批处理完成”不表示所有反馈均已解决：结果保留未纳入、待补证或待决的依据；本批明确必达事项不能被静默延期。完成后不常驻等待人再次确认满意。输入及附件会交给模型处理，凭据只引用受保护配置，不直接写入材料。实现与验证边界见[人工反馈迭代工作流 TRD](docs/trd/20261001-PCM%20Demo%20人工反馈迭代工作流%20TRD.md)。

### 独立代码注释维护

主要功能和本轮修复稳定后，手动执行全量注释检查与必要整理。目标须是本 Demo 已登记且租约有效的产品，创建 run 的适用仓库清单完整，各仓位于 clean main；首次运行遇到已有未提交修改、未知仓库或产品锁占用时直接停止并保留现场。只涉及部分仓库的产品按真实清单执行，不强制同时存在前后端。

```bash
# 当前目录为 pcm-demo；--run-id 可省略，默认按时间生成。
uv run python run_comments.py --workspace /absolute/path/to/product --run-id product-comments

# 失败或中断后续接原任务，保留已有注释变更。
uv run python run_comments.py --resume product-comments

# 原 Agent 对话满足下文恢复条件时，补充说明或解除条件。
uv run python run_comments.py --resume product-comments \
  --resume-message-file /absolute/path/to/resume-message.md
```

入口从当前工具工作区读取 [code-comments](../.claude/skills/code-comments/SKILL.md) 及语言参考，作为本次任务直接交给 Agent，不安装或覆盖目标产品的 Skill。初始输入保存在该注释 run 中，恢复不会更换任务正文；模型与 effort 复用当前提供商策略的 development 分配，不因注释任务另行降档，不新增环境变量。

Agent 全量检查授权的手写维护代码，统一标准后按内聚模块有限并发，补充或纠正代码本身不能清楚表达的约束；不要求每个文件新增注释，不改变产品行为或工具指令。脚本复用现有产品锁、run 锁、容量和负责人决策循环，不重启开发流程、不修改来源 run、产品租约或运行端口，不提交、合并或推送。目标项目资料只读，不创建需求、TRD 或注释规范文档。

结果和原对话保存在 `runs/<注释-run-id>/state.json`、`conversations/code_comments.json`；完成时打印 Agent 交接，产品保留待提交变更，无必要修改也可成功。脚本对分支、HEAD、暂存区及文件结构进行核验；注释是否准确、是否只有说明变化、实际检查是否充分，由 Agent 编辑、复核和验证，不把 Git 检查当作语义证明。完成后按既有 Git 交接方式另行提交，下一次整理使用新的 run。

失败或中断后不要混入其它开发修改，使用原 `--resume` 继续；分支、提交、暂存或文件结构已改变时停止，不自动还原。SDK 保留已有底层重试，但这个手动入口不增加外层自动重启，失败退出后显式恢复。已完成 run 的 `--resume` 只返回原结果，不重新检查当前版本，也不接受追加消息。退出码：`0` 完成、`1` 本地或执行失败、`2` 缺少不可替代外部条件的阻塞。普通编译或测试失败不等于外部阻塞。

### 单独运行当前步骤

```bash
uv run python run_step.py --step <1-18> --run-id <run-id>
```

第 1 步创建新运行时需提供 `--product-draft`，并可同时提供 `--initial-resources` 和成对的 `--git-user-name`、`--git-user-email`。完整流程使用 `run_all.py`；单步入口用于定向开发、诊断和恢复，并遵循相同锁、状态和重试合同。

只有 Claude Agent SDK 执行通道明确请求重试时，单步入口才自动恢复当前步骤，不使用网络探针。公共 runner 从 `.env` 的 `CLAUDE_CODE_MAX_RETRIES` 读取 Claude Code 单次调用最大重试次数，默认 10，可按需改为 15；设为 0 可禁用底层重试。进程环境优先于 `.env`，runner 将最终值和固定的 `CLAUDE_CODE_RETRY_WATCHDOG=0` 显式传入 SDK，覆盖子进程继承值；不调整单次 API 请求超时。底层重试耗尽或遇到无法在原请求内恢复的错误后，单步入口依次等待 30、60、120、300 秒，此后每次等待 300 秒。

恢复窗口从外层首次收到可恢复失败开始计时，最多 6 小时；等待与失败尝试的执行时间均计入，后续失败不重置起点。到期不再发起新尝试，但不打断已启动的 Agent，成功仍正常接受；既有单次 Agent 调用 10 小时上限不变。因此进程实际运行时间可能超过 6 小时。日志显示重试序号、窗口已用时间和下一次等待；窗口耗尽后保存最终失败并停止编排。窗口不持久化，进程退出后人工 `--resume` 开始新的恢复窗口。

HTTP `408/409/429`、临时 `5xx`、可恢复连接／CLI 进程故障及无不可恢复证据的明确 API 失败可以自动恢复；明确的其它 `4xx`、上下文超限、不可恢复的认证／参数／计费错误不会长时间重试。业务 `blocked`、普通 `failed`、负责人裁决失败、本地合同错误、CLI 缺失、主动取消和既有整体超时仍直接停止。每次恢复复用现有 state、session、工作区及锁，不放宽完成条件。完整合同见 [PCM 自动化流程的结果与恢复规则](../docs/pcm/PCM版AI%20Agent自动化流程设计.md#3-每一步只返回三类结果)。

## 用负责人指令恢复 Agent 对话

`--resume-message-file` 可用于当前节点的以下 Agent 对话现场：

- `blocked`，并且 conversation 保留合法 blocked 裁决锚点；
- 进程中断后仍为 `running`；
- `failed`，且 `state.json` 顶层 `error.type` 为 `AgentExecutionFailure`。

三种情况都必须已有对应 conversation 和原 session。正常完成的 loop、负责人裁决失败、其它程序失败、确定性阻塞和无法唯一定位原对话的现场会被拒绝。

```bash
uv run python run_all.py --resume <run-id> \
  --resume-message-file /absolute/path/to/resume-message.md
```

只处理当前步骤并在完成后停下：

```bash
uv run python run_step.py --step <当前步骤> --run-id <run-id> \
  --resume-message-file /absolute/path/to/resume-message.md
```

CLI 取得执行锁后校验目标，并只读取一次可读、非空白的 UTF-8 普通文本。多 loop 步骤会排除已正常 `completed` 的历史 loop，只允许唯一尚未完成的原对话。若已有待裁决的 Agent 回复，循环会先恢复并裁决该回复；即将再次调用 Agent 时，人工正文替代待发送的普通、`continue` 或泛化恢复指令，旧历史不改写。即使先前回复被裁决为 `completed`，本次显式人工消息仍会投递。

正文会先完整写入当前 conversation，随后标记本次内存消息已消费，再原样发送给原 Claude session；它不是自由跳转、强制完成或绕过裁决轮数的入口。容量不足时不会追加或消费消息。消息落盘后若进程中断，后续使用不带文件参数的普通 `--resume`，循环会从已落盘正文继续；同一命令的 SDK 自动重试复用消费状态，不重复追加正文，但整体仍是 at-least-once，不承诺 Agent 业务操作恰好执行一次。只有确需追加新指令时才再次提供文件。

**凭据边界：文件参数只避免正文出现在 shell 命令行，不提供脱敏或秘密隔离。正文会进入 PCM 对话历史、Agent session 和模型请求。API key、令牌、密码等秘密必须先写入已有受保护配置，指令只引用配置路径、配置键和资源说明，不得直接包含秘密。** 不要手改 `state.json`、步骤结果、conversation 或 Claude session，也不要使用 stdin 管道代替该入口。

## 产品端口与锁

```bash
uv run python run_all.py --product-status /absolute/path/to/product
uv run python run_all.py --release-product /absolute/path/to/product
```

`--product-status` 展示 owner run、生命周期、前后端端口和实时 Product Lock 状态。只有确认产品不再继续开发时才使用 `--release-product`；运行锁或产品锁仍被持有、端口仍在监听或注册记录冲突时会拒绝释放。释放不会删除产品目录或 run 历史。

锁文件长期存在是正常现象，文件存在不表示锁仍被持有。**不得删除 `.lock` 文件解锁**；删除仍被持有的锁文件可能破坏互斥。应先查看产品状态，再确认归属明确的相关进程已经退出。

产品工作区存在 `.pcm/runtime.json` 时，启动、健康检查、联调、CORS 和浏览器验收必须使用其中分配的 host、port 与 endpoint，不自行改端口或允许框架静默换端口。

## 诊断与运行数据

```text
runs/<run-id>/
├── state.json                         # 当前节点、需求注册表、session 引用和恢复状态
├── timings.json                       # 步骤与 Agent/AI 调用计时和用量
├── steps/                             # 第 1～12 步及按需求隔离的第 13～18 步结果
├── quality/                           # 质量 run 的准备、按轮审计/分流/入池/登记和收口结果
├── feedback/                          # 反馈 run 的本批输入、核验、范围决定、入池与收尾结果
├── conversations/<domain-key>.json   # Agent 回复、负责人决定和人工恢复指令
└── logs/*.json                        # 最近一次结构化故障诊断快照
```

诊断顺序：

1. 先看命令 stderr 给出的当前节点、结果路径和恢复命令；
2. 再看 `state.json` 与当前步骤结果，确认当前 `status`、`current_node`、`error` 或 `blocked`；
3. 需要 SDK/provider 细节时打开结果引用的 `logs/*.json`；
4. 对话恢复问题查看对应 `conversations/*.json` 和已保存 session 引用；
5. 并发或端口问题先运行 `--product-status`，不要删除锁文件。

诊断文件在恢复成功后可以继续保留，因此文件存在不表示当前仍失败。运行数据受 Git 忽略；不要在日志、提交或回复中展示 `.env` 具体值、认证头或其它秘密。

计时字段、结束原因和用量口径见 [计时与用量说明](docs/timing.md)。

## 验证

程序改动的基础验证入口是：

```bash
uv run python -m unittest discover -s . -t . -p 'test*.py' -v
uv run python -m compileall common steps quality feedback run_step.py run_all.py run_quality.py run_feedback.py run_comments.py
```

涉及真实步骤时，还需按对应步骤说明完成适用的外部服务、Git、构建、测试、联调和浏览器验证。

## 导航

- [流程主文档](../docs/pcm/PCM版AI%20Agent自动化流程设计.md)：流程语义、步骤职责、三个阶段与停止条件。
- [`steps/step_xx_*/README.md`](steps/)：各步骤当前输入、输出、完成条件和恢复边界。
- [通用 Agent 决策对话循环 TRD](docs/trd/20260822-PCM%20Demo%20通用%20Agent%20决策对话循环%20TRD.md)：conversation、session、人工恢复和诊断合同。
- [单机多产品并发执行 TRD](docs/trd/20260903-PCM%20Demo%20单机多产品并发执行%20TRD.md)：锁、产品登记、端口和 `.pcm/runtime.json` 合同。
- [基础品牌资产准备 TRD](docs/trd/20260910-PCM%20Demo%20基础品牌资产准备%20TRD.md)：第 6 步品牌资产任务合同。
- [产品质量迭代工作流 TRD](docs/trd/20260922-PCM%20Demo%20产品质量迭代工作流%20TRD.md)：独立 run、候选到需求、原场景回归、一次性完成条件与真实验证边界。
- [人工反馈迭代工作流 TRD](docs/trd/20261001-PCM%20Demo%20人工反馈迭代工作流%20TRD.md)：批次输入、反馈取舍、文档收尾、原开发链复用与真实验证边界。
- [`AGENTS.md`](AGENTS.md)：Demo 开发与运行约束。
