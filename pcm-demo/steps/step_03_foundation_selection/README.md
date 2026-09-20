# 第 3 步：基础工程选型

第 3 步读取 `steps/02.json` 引用的两份产品定义和本次 `catalog.json`，将它们构造成 Pydantic 输入模型，再通过 OpenAI Python SDK `responses.parse` 返回 Pydantic 选型结果。候选可以声明可选的 `applicability` 资格条件；只有产品定义或明确工程约束提供直接满足证据时才可选择，缺少该字段的既有候选保持原行为。

本步骤不调用 Claude Agent SDK。system prompt 是 `step.py` 中的普通 Python 字符串，只描述模板选型任务，不包含步骤编号、PCM、Skill 或其它编排背景。

## 运行

```bash
uv run python run_step.py \
  --step 3 \
  --run-id <run-id> \
  --catalog-path /path/to/catalog.json
```

catalog 路径优先级为 `--catalog-path`、进程环境 `PCM_TEMPLATE_CATALOG`、`pcm-demo/.env`。

## 输出

模型的 Pydantic 输出只包含 `frontend` 和 `backend` 的选择引用。每个适用选择包含：

- `candidate_id`
- `reason`

不适用的交付面为 `null`。同一交付面的候选 ID 必须唯一；程序按 `candidate_id` 在对应输入候选中执行精确匹配，并从原候选回填：

- `id`
- `git_url`
- `default_branch`
- `path`
- `reason`

最终完整结果保存到 `runs/<run-id>/steps/03.json.template_selection`，供后续步骤继续使用。模型无法选择候选列表之外的方案，也不负责复制仓库地址、分支或路径。

成功后状态推进到 `project:04_assemble_foundation`。第 4 步尚未实现，入口仍明确返回“步骤尚未实现”。
