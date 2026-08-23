# PCM 自动化流程 Demo

这是 PCM 自动化流程的本地验证工具。

## 当前步骤

- [第 0 步：形成产品初稿](steps/step_00_product_draft/README.md)
- [第 1 步：建立项目工作区](steps/step_01_create_workspace/README.md)
- [第 2 步：项目需求与产品定义](steps/step_02_project_intake/README.md)
- [第 3 步：基础工程选型](steps/step_03_foundation_selection/README.md)
- [第 4 步：组装基础工程](steps/step_04_assemble_foundation/README.md)
- [第 5 步：核验项目准备状态](steps/step_05_project_readiness/README.md)
- [第 6 步：项目化基础工程](steps/step_06_project_bootstrap/README.md)
- [第 7 步：总体技术方案](steps/step_07_solution_design/README.md)
- [第 8 步：首次提交适用仓库](steps/step_08_initialize_repositories/README.md)

每个步骤的业务代码、测试和详细运行说明都在对应步骤目录中。根 README 只提供导航。

## 统一测试

在 `pcm-demo/` 目录执行：

```bash
uv sync
uv run python -m unittest discover -s . -t . -p 'test*.py' -v
```

该入口从 `pcm-demo/` 根递归发现 `common/` 与 `steps/` 测试。本次机械对齐后的实际测试计数和检查结果以本轮执行记录为准。

## 最近真实验证

隔离 run `agent-loop-step7-20260822T190149Z` 已真实验证公共循环的第 7 步路径：初次环境内部 Explore 子代理模型错误超时后保留 session 与初始对话；仅在隔离历史追加普通 assistant 提示后从同一 session 恢复，完成正常 `success`、两次 `completed` 裁决和固定方案文档补完核验，最终推进到第 8 步。隔离副本未修改既有 `step01-mendmark`；该测试提示和文档置空 failpoint 均不属于生产代码或生产 prompt。

Probe C 的早期成功证据保留于 `probe-c-20260822T185623Z`：普通决定为 `continue`（2 次格式尝试），boundary 为 `blocked`（1 次）。这些以及 `probe-c-20260822T200038Z` 的格式重试相关结果都是旧合同下的历史事实。现行 `request_decision` 要求调用方显式传入完整 XML system prompt，并将其原样用于一次 `responses.parse`，以 Pydantic `AgentDecision` 取得结构化输出；没有公共默认或隐藏追加 prompt，也没有格式重试。现行 XML prompt 已完成一次真实交接事实回放，但 Probe C 尚未按新合同单独重跑，服务重复稳定性仍是验证缺口。

第 8 步首个真实 run `step08-real-20260823-a` 保留失败事实：第 1 步依次出现代码围栏、Responses `incomplete`、自创字段，收紧严格 JSON prompt 后同 run 成功；第 3 步一次 `ValidationError` 后同 run 重试成功；第 7 步 API 500 暴露 failed `07.json` 错误阻断恢复，修正为只有 `status=success` 才复用后同 session 成功。第 8 步因模板快照的 `.coverage` 成为根仓未跟踪垃圾，Agent 按合同未提交，而决策模型重复索取调用方授权并耗尽 8 轮；该 run 未产生任何三仓提交。

修复后的 `step08-real-20260823-b` 在第 6 步真实清除 `.coverage` 后保持三仓 `main` / unborn / 空 index；第 8 步使用唯一 session `64aa707c-268c-48c8-bb3f-f67f62abe75e`，以一轮 Agent 回复和一轮 `completed` 裁决完成。根、前端、后端提交分别为 `c1eb33dfa5bda91a0d7f9aeeb41d8fefe10a6fca`、`5997213c34c09ea6ba4e740e35f9df77d2d45d82`、`5d8dd95d8c42370697d25e6ecaf400bab42785b3`；它们均为干净 `main` 的唯一无父提交，根 tree 不含前端或后端，状态推进到 `project:09_engineering_architecture`。同 run 重跑幂等复用，SHA 不变且没有再次调用 Agent。

Git 忽略 run `prompt-role-replay-20260823` 已使用现行完整 XML system prompt 重建交接事实回放：复用 `step08-real-20260823-a` 中已成功完成的 `solution_design` 真实 Agent 对话和现行项目文件，真实 AI-compatible 服务以 `attempts=1` 返回 `completed`；`result.json` 记录四个 XML section 和当前 prompt 哈希。该回放不是新的 Claude Agent SDK 执行，也不代表重复调用稳定性已经得到证明。
