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

每个步骤的业务代码、测试和详细运行说明都在对应步骤目录中。根 README 只提供导航。

## 统一测试

在 `pcm-demo/` 目录执行：

```bash
uv sync
uv run python -m unittest discover -s . -t . -p 'test*.py' -v
```

该入口从 `pcm-demo/` 根递归发现 `common/` 与 `steps/` 测试。当前全量共 83 项，其中公共循环 23 项。

## 最近真实验证

隔离的新 run `agent-loop-step7-20260822T190149Z` 已使用新 `solution_design` session 真实验证公共循环的第 7 步路径：初次环境内部 Explore 子代理模型错误超时后，保留 session 与初始对话；加入仅用于隔离验证的普通 assistant 提示后从同一 session 恢复，完成正常 `success`、两次 `completed` 裁决以及固定方案文档补完核验，最终推进到第 8 步节点。隔离副本未修改既有 `step01-mendmark`；该测试提示和文档置空 failpoint 均不属于生产代码或生产 prompt。

Probe C 的早期成功证据保留于 `probe-c-20260822T185623Z`：普通决定为 `continue`（2 次格式尝试），boundary 为 `blocked`（1 次）。后续最终验证连续两次失败：一次普通决定在唯一重试后仍返回带“验证：”前缀的非 JSON，触发 `ValidationError`；一次普通决定成功后，boundary 调用返回 Responses `status=incomplete`。代码均按合同返回 `failed`，没有增加第三次重试或手写解析。

随后 `common/decision.py` 将“严格 JSON、首尾花括号、双引号、禁止 YAML”格式约束统一附加到首次请求和唯一格式重试；步骤专属 system prompt 仍只描述领域完成条件。更新后的真实复跑 `probe-c-20260822T200038Z` 通过：ordinary 为 `continue`（attempts=1），boundary 为 `blocked`（attempts=1）。这确认前置格式约束后的单次复验成功，但不消除先前观察到的服务格式/完成状态波动，重复稳定性仍是验证缺口。
