# 第 3 步：总体技术方案

本步骤在第 2 步成功后，显式调用 `solution-design`，使用产品定义、当前工程事实、开发约束和 `catalog.json` 完成总体技术方案及前后端基础工程选型。

## 输入

- 第 2 步 `steps/02.json` 中相对于产品项目根的两份产品定义文档；
- 单一模板候选目录 `catalog.json`，必须是可读且符合固定结构的 JSON 文件。

## 运行

在 `pcm-demo/` 目录执行：

```bash
uv run python run_step.py \
  --step 3 \
  --run-id <run-id> \
  --catalog-path /absolute/path/to/catalog.json
```

`--catalog-path` 优先于进程环境 `PCM_TEMPLATE_CATALOG`，进程环境优先于 `pcm-demo/.env` 中的同名配置。

## Agent 与结构化交接

Agent 负责读取 catalog、完成技术方案和模板选择。最终自然语言回复必须明确说明：

- frontend 的 `repository_id`、`template_id`、`adoption`；
- backend 的 `repository_id`、`template_id`、`adoption`。

Agent 不需要输出 JSON，也不需要生成基础工程来源文件。PCM 使用 OpenAI-compatible Responses API 读取 Agent 最终回复和 catalog，判断 Agent 是否已经明确作出选择；程序随后核验结构化 ID 确实存在于 catalog，并从 catalog 补齐仓库和模板定位信息。程序不根据 catalog 替 Agent 补选。

## 输出

产品工作区只生成：

```text
docs/design/技术方案.md
```

运行目录的 `runs/<run-id>/steps/03.json` 保存完整步骤结果，其中 `template_selection` 是下一步唯一的机器交接对象。它包含前后端目标路径、仓库 ID、仓库 Git 地址、默认分支、模板 ID、模板路径和采用方式。

本步骤不获取、复制或组装模板内容，不初始化前后端仓库，也不生成 `docs/design/基础工程来源.json`。
