# 第 10 步：产品级 UI/UX 框架

本步骤在产品初始化阶段按当前 Demo v1 合同建立产品级、跨需求稳定的 UI/UX 框架；不做单项需求设计或页面实现。

## 运行

在 `pcm-demo/` 目录执行：

```bash
uv run python run_step.py --step 10 --run-id <run-id>
```

定向自动化测试：

```bash
uv run python -m unittest \
  steps.step_10_ui_ux_framework.test_step \
  steps.step_10_ui_ux_framework.test_cli -v
```

## 适用性与输入

Demo v1 的适用性是确定性规则：仅当第 8 步严格 success 的空 `outputs`、result/state 一致的合法有序 `applicable_repositories` 包含 `frontend` 时适用。程序不扫描目录，也不让 Agent 判断适用性。这是当前前后端交付单元模型下的 Demo 简化，不改变通用 `ui-ux-framework` Skill 可处理更广既有项目语义的能力。

无论是否适用，均须严格核验第 9 步 success 结果唯一输出为 `docs/design/工程架构设计.md`。第 8 步不逐项回放旧 `repositories` path、branch、clean 字段；适用路径在当前现场只读核验权威仓库事实。

适用时，输入还包括：

- 第 2 步结果的两份产品定义输出；
- 第 5 步项目准备清单；
- 第 7 步总体技术方案；
- 第 8 步权威仓库和实际 `frontend/` 工程；
- 第 9 步固定工程架构设计文档。

## 不适用路径

第 8 步权威仓库清单不含 `frontend` 时，步骤只核验上述第 8、9 步交接，写入：

```json
{
  "status": "success",
  "applicable": false,
  "outputs": []
}
```

随后推进到 `project:11_requirement_breakdown`。此路径拒绝所有状态下遗留的本步骤 session、conversation、私有执行状态或历史文件；不得产生 Git、Agent、负责人决策、LLM 配置或 `docs/ui-ux/` 副作用。该分支由自动化覆盖；黄金项目有 `frontend`，没有把不适用路径表述为真实运行证据。

## 适用路径、边界、提交与恢复

适用时只使用一个领域键和 Claude session：`ui_ux_framework`。初始提示首行固定为 `/ui-ux-framework`，明确授权 `bootstrap` 模式，只允许创建或更新唯一固定产物 `docs/ui-ux/framework.md`。提示要求文档区分工程事实、已确认决定、目标状态、假设和待确认事项，并覆盖产品体验目标与原则、信息与交互框架、跨需求一致性、内容与反馈、可访问性和响应式基线、设计资产边界及协作规则。高影响方向须保留给后续负责人确认。

每轮完整 Agent 回复均由公共 `run_agent_decision_loop` 保存、读取和解释，并交给 AI-compatible 负责人返回 `AgentDecision(completed/continue/blocked)`；领域步骤不解析 conversation 消息 schema、角色顺序、尾部 decision、session/reference 组合或完整 commit prompt，也不把 conversation 当长期成功证据。Agent 不得进行单项需求设计、页面/CSS/组件/主题设计或实现，不得修改代码、测试、配置、项目规则或其它文档，不得执行 Git 写操作。Python 只读 Git，并在当前现场核验权威仓库均为自身 top-level、`main`；子仓始终 clean，根仓只能出现固定文档变更。

负责人返回 `completed` 后，verifier 先 repair 缺失或空的固定文档。文档有效后，只有根仓存在且仅存在固定文档的未提交变化时，才在原 session 发送 `/commit-changes`；固定文档已 tracked 且全仓 clean 时直接满足提交交付条件，不制造无变化调用。成功只要求固定文档非空、普通文件、非符号链接、已 tracked，且全部权威仓库在当前现场为自身 top-level、`main`、clean；不要求 exact commit prompt、紧邻 Agent 回复或历史执行锚点。

**证据边界：** Python 只核验当前 Git-visible 工作树和 index；这不是不可绕过的安全隔离，不证明整个 Agent 执行历史未发生 Git 写入，也不覆盖 ignored 文件。本地 Demo 信任项目权限配置和 Agent 遵守领域约束；未来若要求不可绕过隔离，应在项目级权限或沙箱统一实现，而非由领域步骤解析 conversation 或扩展 Git DSL。

fresh 仅因本步骤 session、conversation reference、私有状态或 conversation 路径等执行产物已存在而拒绝；resume 由公共循环恢复原 session。run 目录是受控、Git 忽略的本地恢复状态，不建设防篡改日志。适用的完整 success result/state 写入中断，或完整 success 重跑时，只按严格 result schema、当前固定文档和 Git 事实补状态或确认成功；残缺 success 不受保护。

负责人返回 `blocked` 时始终保存 blocked 并停在第 10 步，不能因本地文档 tracked 且 clean 改判 success；补齐外部条件后由公共循环从原 session 恢复。第 8～10 步的 Git 与提交合同保持步骤私有，不扩展 `common/`、不抽取 Git DSL、commit 事件、持久布尔标记或旧 prompt 兼容列表。

## 自动化与旧合同下的历史运行事实（非当前成功条件）

第 9～11 步新合同代码与自动化已完成：第 9～11 步本体测试合计 49 项通过；公共循环加第 9～11 步本体及第 10/11 步 CLI 定向回归共 84 项通过；PCM Demo 全量 268 项 `unittest` 通过（86.068 秒）；`compileall common steps run_step.py` 与 `git diff --check` 通过；目标第 9～11 步生产/测试和相关文档 IDE diagnostics 无新增问题（既有 pydantic 解析 warning 和第 12 步 unused hint 不属于本次）。尚未按新合同重新执行真实 Claude Agent、负责人 LLM 或 `/commit-changes` 集成；旧真实 run 仍仅为旧合同历史。 以下真实 run 的 7 条 conversation、exact commit prompt、提交和幂等重跑描述，均是旧合同下的历史执行路径，保留作演进依据，不构成当前成功条件。

真实 run 为 `pcm-demo/runs/step01-mendmark`，产品工作区为 `/Users/zhou/resource/fireworks/ANDRSZAN/pcm-products/mendmark`。第 8 步权威仓库为 `root/frontend/backend`，因此适用。fresh 运行中内置 Explore 子代理曾输出未识别模型 `gpt-5.6-terra[1m]` 警告；主 Agent 在同一次调用继续并正常 success，未追加人工或 run-history 恢复提示。

该 run 使用 session `2d052d9a-b9fd-4fcd-b5f9-ff724f25dbc1`；init 核验 `ui-ux-framework` skill 与 slash command 已加载，cwd 为产品根，模型为 `claude-fable-5[1M]`，Claude Code 为 2.1.233，permissionMode 为 `bypassPermissions`。最终 Agent success，5 turns，cost `$3.207112`，`terminal_reason=completed`，无错误。conversation 为 7 条：`system → assistant 初始 → user → assistant completed → assistant commit prompt → user → assistant completed`；文档 repair 为 0 次，固定 commit prompt 恰好一次，锚点有效。

固定文档实际读取为 206 行、25580 字节，只包含产品级框架内容，没有实现代码。产品根形成未 push 的提交 `0ceee1bb8b5836f64112ded0c8fd3cf7fbd1f29c`（父提交 `ead14dffe19bc6417634c24c7bb1103602c3b772`，message `docs: 建立产品级 UI/UX 框架`），仅新增 `docs/ui-ux/framework.md`。frontend HEAD 为 `dbab574dbe4d83a02323a750afd04de007565ac5`，backend HEAD 为 `9682be837759c20f1a9ebbdf8fa2cfc09c2768d4`，三仓均为自身 top-level、`main`、clean。`steps/10.json` 为适用 success 且唯一输出固定文档，state 已推进至第 11 步；幂等重跑未增加 conversation、提交或 Agent/决策调用，session、root HEAD、前后端 SHA 均不变。
