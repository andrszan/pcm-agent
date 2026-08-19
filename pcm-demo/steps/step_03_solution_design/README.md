# 第 3 步：总体技术方案

本步骤在第 2 步成功后，显式调用 `solution-design`，使用产品定义和必需的基础模板资产生成总体技术方案及前后端基础工程来源选择结果。

## 输入

- 第 2 步 `steps/02.json` 中相对于产品项目根的两份产品定义文档；
- 包含 `repositories.yaml`、`templates.yaml` 和对应候选模板目录的基础模板资产入口。

## 运行

在 `pcm-demo/` 目录执行：

```bash
uv run python run_step.py \
  --step 3 \
  --run-id <run-id> \
  --template-assets /absolute/path/to/template-projects
```

## 输出

产品工作区：

```text
docs/design/技术方案.md
docs/design/基础工程来源.json
```

运行目录：

```text
runs/<run-id>/steps/03.json
runs/<run-id>/conversations/solution_design.json
```

本步骤只完成技术方案和模板选择，不获取、复制或组装模板内容。
