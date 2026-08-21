# 第 5 步：核验项目准备状态

## 输入

- 运行状态位于 `project:05_verify_readiness`，且产品根 Git 仓库与状态记录一致。
- `steps/02.json` 为成功结果，包含两份可解析到产品工作区内、非空且非符号链接的产品定义文件。
- `steps/03.json` 为成功结果，`template_selection` 可由 `FoundationSelectionResult` 校验。
- `steps/04.json` 为成功结果，已组装工程、来源证据和临时目录现场均与选型和状态一致。
- `PCM_DEV_RESOURCE_LIST` 已配置为可读普通文件的绝对路径。

## 行为

以同一 Claude session 调用 `/project-readiness`。初始提示引用第 2 步实际产品定义产物、已组装工程、完整模板选择 JSON 与开发资源清单路径。调用方已授权直接生成或更新清单；Agent 可读取可信资源清单、创建项目专用开发/测试数据库和桶、写入被忽略的实际 `.env` 并用工具验证，但不得泄露秘密或执行 Git 暂存、提交、推送。

本步骤只判断进入基础工程项目化前的外部资源、访问条件和本地配置。依赖安装、构建、测试、启动、独立 Git 初始化、业务实现和完整验收属于后续工作，不作为当前准备阻塞。

每轮保存 Agent 初始化信息、终止语义、session、固定恢复提示和秘密最小化决策历史；Agent 原始文本与决策自由文本只临时用于本轮调用，不持久化。阻塞的具体资源和补齐方式由准备清单脱敏记录，步骤结果只使用固定阻塞说明。单次 Agent 上限为 24 turns、`$8`，最多执行 6 轮决策。预算或 turn 上限恢复同一 session；只有 Agent 正常成功结束、决策批准且清单是工作区内非空普通文件时才成功。

## 输出与恢复

成功产物为 `docs/requirements/项目准备清单.md`，`steps/05.json.outputs` 只记录该相对路径。步骤先写成功结果，再将状态推进到 `project:06_bootstrap_foundation`。若结果已成功而状态写入中断，重跑会核验清单与 Agent 成功事实后恢复推进；完整成功状态会直接复用，不再次调用 Agent。

决策为 `blocked` 时，CLI 将结果写为 `blocked`；若清单已经存在，输出仍会包含其相对路径。`answer`、`continue`，或清单尚不存在时的 `approve` 会保存提示，并在同一 session 中恢复。其它异常由 CLI 写为 `failed`，保留可恢复现场。

## 运行

```bash
cd /Users/zhou/resource/fireworks/ANDRSZAN/pcm-agent-skills/pcm-demo
uv run python run_step.py --step 5 --run-id <run-id>
```
