# 第 10 步：产品级 UI/UX 框架

本步骤在产品初始化阶段按当前 Demo v1 合同建立产品级、跨需求稳定的 UI/UX 框架；不做单项需求设计或页面实现。适用时的 Claude Agent 只传稳定任务标识 `ui_ux_framework`，实际 model 与 effort 由 `model-policy.toml` 解析并按本次进程启动时加载的策略固定；不适用路径保持零 Agent 调用。

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

无论是否适用，均须严格核验第 5 步 `readiness_baseline` 与当前准备清单、两份产品定义一致，并核验第 9 步 success 结果唯一输出为 `docs/design/工程架构设计.md`。第 8 步不逐项回放旧 `repositories` path、branch、clean 字段；适用路径在当前现场只读核验权威仓库事实。

适用时，输入还包括：

- 第 2 步结果的两份产品定义输出；
- 第 5 步严格成功结果和项目准备清单，当前清单及两份产品定义与 `readiness_baseline` 指纹一致；
- 第 7 步总体技术方案；
- 第 8 步权威仓库和实际 `frontend/` 工程；
- 第 9 步固定工程架构设计文档。

## 不适用路径

第 8 步权威仓库清单不含 `frontend` 时，步骤先核验上述第 5 步 readiness baseline、第 8 步仓库交接和第 9 步工程架构交接，写入：

```json
{
  "status": "success",
  "applicable": false,
  "outputs": []
}
```

随后推进到 `project:11_requirement_breakdown`。此路径拒绝所有状态下遗留的本步骤 session、conversation、私有执行状态或历史文件；不得产生 Git、Agent、负责人决策、LLM 配置或 `docs/ui-ux/` 副作用。该分支由自动化覆盖；黄金项目有 `frontend`，没有把不适用路径表述为真实运行证据。

## 适用路径、边界、提交与恢复

适用时只使用一个领域键和 Claude session：`ui_ux_framework`。初始提示首行固定为 `/ui-ux-framework`，明确授权 `bootstrap` 模式，只允许创建或更新唯一固定产物 `docs/ui-ux/framework.md`。适用范围必须闭合 App Shell Contract，明确产品表面、区域职责、导航层级、页面模式、常规滚动所有者、sticky 基准和窄屏转换；文档必须区分 Current、已确认 Target、默认 Target、具体待确认、已知偏差和非目标。能由项目事实安全推导的低风险结构直接收敛为保留依据和重议条件的默认 Target；仅实质高影响、会改变跨需求体验骨架、迁移成本或兼容性的具体分歧交由负责人决定，负责人可用 `continue` 作出决定并要求回写，不接受整份框架泛化待确认。Agent 按需读取本能力自带的 `references/` 或 `assets/` 辅助判断，但资源不是项目默认实现，不得将示例内容当作项目事实。

每轮完整 Agent 回复均由公共 `run_agent_decision_loop` 保存、读取和解释，并交给 AI-compatible 负责人返回 `AgentDecision(completed/continue/blocked)`；领域步骤不解析 conversation 消息 schema、角色顺序、尾部 decision、session/reference 组合或完整 commit prompt，也不把 conversation 当长期成功证据。Agent 不得进行单项需求设计、页面/CSS/组件/主题设计或实现，不得修改代码、测试、配置、项目规则或其它文档，不得执行 Git 写操作。Python 只读 Git，并在当前现场核验权威仓库均为自身 top-level、`main`；子仓始终 clean，根仓只能出现固定文档变更。

负责人返回 `completed` 后，verifier 先 repair 缺失或空的固定文档。文档有效后，只有根仓存在且仅存在固定文档的未提交变化时，才在原 session 发送 `/commit-changes`；固定文档已 tracked 且全仓 clean 时直接满足提交交付条件，不制造无变化调用。成功只要求固定文档非空、普通文件、非符号链接、已 tracked，且全部权威仓库在当前现场为自身 top-level、`main`、clean；不要求 exact commit prompt、紧邻 Agent 回复或历史执行锚点。

**证据边界：** Python 只核验当前 Git-visible 工作树和 index；这不是不可绕过的安全隔离，不证明整个 Agent 执行历史未发生 Git 写入，也不覆盖 ignored 文件。本地 Demo 信任项目权限配置和 Agent 遵守领域约束；未来若要求不可绕过隔离，应在项目级权限或沙箱统一实现，而非由领域步骤解析 conversation 或扩展 Git DSL。

fresh 仅因本步骤 session、conversation reference、私有状态或 conversation 路径等执行产物已存在而拒绝；resume 由公共循环恢复原 session。run 目录是受控、Git 忽略的本地恢复状态，不建设防篡改日志。适用的完整 success result/state 写入中断，或完整 success 重跑时，只按严格 result schema、当前固定文档和 Git 事实补状态或确认成功；残缺 success 不受保护。

负责人返回 `blocked` 时始终保存 blocked 并停在第 10 步，不能因本地文档 tracked 且 clean 改判 success；补齐外部条件后由公共循环从原 session 恢复。第 8～10 步的 Git 与提交合同保持步骤私有，不扩展 `common/`、不抽取 Git DSL、commit 事件、持久布尔标记或旧 prompt 兼容列表。

## 本轮合同同步验证

新版 App Shell Contract、默认 Target 收敛和负责人 `continue` 回写规则已由本步骤及第 11、14、15 步的步骤本体与 CLI 合计 72 项定向测试覆盖；PCM Demo 全量 321 项 `unittest`、`compileall common steps run_step.py test_run_step_retry.py` 与 `git diff --check` 通过。未运行新的真实 Claude Agent 或 AI-compatible 负责人集成，本轮不改写下述旧合同历史事实。

## 自动化与旧合同下的历史运行事实（非当前成功条件）

共享自动化统计已同步为本轮当前工作树验证：第 9～11 步本体合计 51 项（18+18+15）通过；公共循环加第 9～11 步本体及第 10/11 步 CLI 的相关回归 97 项通过（20.800 秒）；全量 320 项 `unittest` 通过（61.405 秒）。其中第 9 步定向 18 项通过（5.498 秒）；`compileall common steps run_step.py test_run_step_retry.py` 与本次目标 `git diff --check` 通过。当前工作树还包含其它公共循环/CLI 的未提交修改，以上全量结果不能全部归因于第 9 步；这只更新共享统计，不改变本步骤业务合同。第 9 步新版 prompt 合同尚未执行安全的 fresh 真实 Claude Agent、AI-compatible 负责人或 `/commit-changes` 集成，旧真实 run 仍仅为旧合同历史。 以下真实 run 的 7 条 conversation、exact commit prompt、提交和幂等重跑描述，均是旧合同下的历史执行路径，保留作演进依据，不构成当前成功条件。

真实 run 为 `pcm-demo/runs/step01-mendmark`，产品工作区为 `/Users/zhou/resource/fireworks/ANDRSZAN/pcm-products/mendmark`。第 8 步权威仓库为 `root/frontend/backend`，因此适用。fresh 运行中内置 Explore 子代理曾输出未识别模型 `gpt-5.6-terra[1m]` 警告；主 Agent 在同一次调用继续并正常 success，未追加人工或 run-history 恢复提示。

该 run 使用 session `2d052d9a-b9fd-4fcd-b5f9-ff724f25dbc1`；init 核验 `ui-ux-framework` skill 与 slash command 已加载，cwd 为产品根，模型为 `claude-fable-5[1M]`，Claude Code 为 2.1.233，permissionMode 为 `bypassPermissions`。最终 Agent success，5 turns，cost `$3.207112`，`terminal_reason=completed`，无错误。conversation 为 7 条：`system → assistant 初始 → user → assistant completed → assistant commit prompt → user → assistant completed`；文档 repair 为 0 次，固定 commit prompt 恰好一次，锚点有效。

固定文档实际读取为 206 行、25580 字节，只包含产品级框架内容，没有实现代码。产品根形成未 push 的提交 `0ceee1bb8b5836f64112ded0c8fd3cf7fbd1f29c`（父提交 `ead14dffe19bc6417634c24c7bb1103602c3b772`，message `docs: 建立产品级 UI/UX 框架`），仅新增 `docs/ui-ux/framework.md`。frontend HEAD 为 `dbab574dbe4d83a02323a750afd04de007565ac5`，backend HEAD 为 `9682be837759c20f1a9ebbdf8fa2cfc09c2768d4`，三仓均为自身 top-level、`main`、clean。`steps/10.json` 为适用 success 且唯一输出固定文档，state 已推进至第 11 步；幂等重跑未增加 conversation、提交或 Agent/决策调用，session、root HEAD、前后端 SHA 均不变。
