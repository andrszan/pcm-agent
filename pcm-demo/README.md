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

该入口从 `pcm-demo/` 根递归发现 `common/` 与 `steps/` 测试。实际 `unittest` 输出为 108 项：公共循环 23 项，步骤测试 85 项；第 8 步专属为 14 项。

## 最近真实验证

隔离 run `agent-loop-step7-20260822T190149Z` 已真实验证公共循环的第 7 步路径：初次环境内部 Explore 子代理模型错误超时后保留 session 与初始对话；仅在隔离历史追加普通 assistant 提示后从同一 session 恢复，完成正常 `success`、两次 `completed` 裁决和固定方案文档补完核验，最终推进到第 8 步。隔离副本未修改既有 `step01-mendmark`；该测试提示和文档置空 failpoint 均不属于生产代码或生产 prompt。

Probe C 的早期成功证据保留于 `probe-c-20260822T185623Z`：普通决定为 `continue`（2 次格式尝试），boundary 为 `blocked`（1 次）。后续最终验证连续两次失败：一次普通决定在唯一重试后仍返回带“验证：”前缀的非 JSON，触发 `ValidationError`；一次普通决定成功后，boundary 调用返回 Responses `status=incomplete`。代码均按合同返回 `failed`，没有增加第三次重试或手写解析。随后 `common/decision.py` 将“严格 JSON、首尾花括号、双引号、禁止 YAML”格式约束统一附加到首次请求和唯一格式重试；更新后的真实复跑 `probe-c-20260822T200038Z` 通过：ordinary 为 `continue`（attempts=1），boundary 为 `blocked`（attempts=1）。单次复验不消除服务格式/完成状态波动，重复稳定性仍是验证缺口。

第 8 步首个真实 run `step08-real-20260823-a` 保留失败事实：第 1 步依次出现代码围栏、Responses `incomplete`、自创字段，收紧严格 JSON prompt 后同 run 成功；第 3 步一次 `ValidationError` 后同 run 重试成功；第 7 步 API 500 暴露 failed `07.json` 错误阻断恢复，修正为只有 `status=success` 才复用后同 session 成功。第 8 步因模板快照的 `.coverage` 成为根仓未跟踪垃圾，Agent 按合同未提交，而决策模型重复索取调用方授权并耗尽 8 轮；该 run 未产生任何三仓提交。

修复后的 `step08-real-20260823-b` 在第 6 步真实清除 `.coverage` 后保持三仓 `main` / unborn / 空 index；第 8 步使用唯一 session `64aa707c-268c-48c8-bb3f-f67f62abe75e`，以一轮 Agent 回复和一轮 `completed` 裁决完成。根、前端、后端提交分别为 `c1eb33dfa5bda91a0d7f9aeeb41d8fefe10a6fca`、`5997213c34c09ea6ba4e740e35f9df77d2d45d82`、`5d8dd95d8c42370697d25e6ecaf400bab42785b3`；它们均为干净 `main` 的唯一无父提交，根 tree 不含前端或后端，状态推进到 `project:09_engineering_architecture`。同 run 重跑幂等复用，SHA 不变且没有再次调用 Agent。
