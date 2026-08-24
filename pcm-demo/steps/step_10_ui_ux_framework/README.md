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

Demo v1 的适用性是确定性规则：仅当 `steps/08.json` 与 `state.json` 中完全一致的 `applicable_repositories` 包含 `frontend` 时适用。程序不扫描目录，也不让 Agent 判断适用性。这是当前前后端交付单元模型下的 Demo 简化，不改变通用 `ui-ux-framework` Skill 可处理更广既有项目语义的能力。

无论是否适用，均须先读取第 8 步权威仓库交接并严格核验第 9 步 success 结果唯一输出为 `docs/design/工程架构设计.md`。

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

## 适用路径、边界与提交

适用时只使用一个领域键和 Claude session：`ui_ux_framework`。初始提示首行固定为 `/ui-ux-framework`，明确授权 `bootstrap` 模式，只允许创建或更新唯一固定产物：

```text
docs/ui-ux/framework.md
```

提示要求文档区分工程事实、已确认决定、目标状态、假设和待确认事项，并覆盖产品体验目标与原则、信息与交互框架、跨需求一致性、内容与反馈、可访问性和响应式基线、设计资产边界及协作规则。高影响方向须保留给后续负责人确认。每轮完整 Agent 回复都交给 AI-compatible 负责人返回 `AgentDecision(completed/continue/blocked)`；只有 `completed` 后才执行本步骤完成核验，`continue` 恢复原 session，`blocked` 仅用于不可替代外部资源。

Agent 不得进行单项需求设计、页面/CSS/组件/主题设计或实现，不得修改代码、测试、配置、项目规则或其它文档，不得执行 Git 写操作。运行期间所有权威仓库必须是自身 top-level、位于 `main`；子仓必须始终 clean，根仓只能出现固定文档的变更。Python 只读 Git。

负责人返回 `completed` 后，verifier 先对缺失或空的固定文档发送固定 repair prompt；之后无论文档相对提交是否有 diff，都在原 session 精确发送一次 `/commit-changes`。提交锚点要求 exact commit prompt、紧邻的非空 Agent `user` 回复和原 session 均存在。最终固定文档必须非空、普通文件、非符号链接且已被跟踪，并且全部权威仓库均为自身 top-level、`main`、clean。

## 恢复与安全

fresh 入口要求权威仓库全 clean，并拒绝预置 session、conversation 引用、私有状态或历史文件。恢复必须具有原 session、conversation 引用和非符号链接历史；缺失或不一致不静默新建会话。父/叶 conversation 路径及固定文档路径都拒绝符号链接。

适用与不适用结果都支持 result/state 写入中断恢复和幂等重跑。`run_step.py` 仅对 schema 完整的第 10 步 success 保护 result 与已推进 state：仅接受 `applicable: true` 加唯一固定输出，或 `applicable: false` 加空输出；残缺 success 不受保护。第 8～10 步的 Git 与提交合同保持各步骤私有，不扩展 `common/` 或抽取通用 commit DSL。

## 自动化与真实验证

自动化已通过第 10 步本体 16 项与 CLI 5 项，共 21 项；公共循环和第 9 步回归也已单独通过。全量递归 `unittest` 为 162 项，通过 `compileall`、`git diff --check` 和新增 README 的 no-index whitespace 检查；IDE 对 `step.py`、`test_step.py`、`test_cli.py`、`run_step.py` 无诊断。独立审查曾发现不适用路径在 failed、blocked 或已推进状态遗留执行产物时会误报跳过成功，现已统一拒绝并补测试。

真实 run 为 `pcm-demo/runs/step01-mendmark`，产品工作区为 `/Users/zhou/resource/fireworks/ANDRSZAN/pcm-products/mendmark`。第 8 步权威仓库为 `root/frontend/backend`，因此适用。fresh 运行中内置 Explore 子代理曾输出未识别模型 `gpt-5.6-terra[1m]` 警告；主 Agent 在同一次调用继续并正常 success，未追加人工或 run-history 恢复提示。

该 run 使用 session `2d052d9a-b9fd-4fcd-b5f9-ff724f25dbc1`；init 核验 `ui-ux-framework` skill 与 slash command 已加载，cwd 为产品根，模型为 `claude-fable-5[1M]`，Claude Code 为 2.1.233，permissionMode 为 `bypassPermissions`。最终 Agent success，5 turns，cost `$3.207112`，`terminal_reason=completed`，无错误。conversation 为 7 条：`system → assistant 初始 → user → assistant completed → assistant commit prompt → user → assistant completed`；文档 repair 为 0 次，固定 commit prompt 恰好一次，锚点有效。

固定文档实际读取为 206 行、25580 字节，只包含产品级框架内容，没有实现代码。产品根形成未 push 的提交 `0ceee1bb8b5836f64112ded0c8fd3cf7fbd1f29c`（父提交 `ead14dffe19bc6417634c24c7bb1103602c3b772`，message `docs: 建立产品级 UI/UX 框架`），仅新增 `docs/ui-ux/framework.md`。frontend HEAD 为 `dbab574dbe4d83a02323a750afd04de007565ac5`，backend HEAD 为 `9682be837759c20f1a9ebbdf8fa2cfc09c2768d4`，三仓均为自身 top-level、`main`、clean。`steps/10.json` 为适用 success 且唯一输出固定文档，state 已推进至第 11 步；幂等重跑未增加 conversation、提交或 Agent/决策调用，session、root HEAD、前后端 SHA 均不变。
