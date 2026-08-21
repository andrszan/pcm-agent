# 第 3 步：基础工程选型

第 3 步读取 `steps/02.json` 引用的两份产品定义和本次 `catalog.json`，将它们构造成 Pydantic 输入模型，再通过 OpenAI Python SDK `responses.parse` 返回 Pydantic 选型结果。

本步骤不调用 `foundation-selection` Skill 或 Claude Agent SDK。system prompt 是 `step.py` 中的普通 Python 字符串，只描述模板选型任务，不包含步骤编号、PCM、Skill 或其它编排背景。

## 运行

```bash
uv run python run_step.py \
  --step 3 \
  --run-id <run-id> \
  --catalog-path /path/to/catalog.json
```

catalog 路径优先级为 `--catalog-path`、进程环境 `PCM_TEMPLATE_CATALOG`、`pcm-demo/.env`。

## 输出

Pydantic `FoundationSelectionResult` 包含 `frontend` 和 `backend`。每个适用选择直接包含：

- `id`
- `git_url`
- `default_branch`
- `path`
- `reason`

不适用的交付面为 `null`。程序直接保存 `response.output_parsed.model_dump()` 到 `runs/<run-id>/steps/03.json.template_selection`，不手写 JSON Schema、不解析原始 JSON 字符串，也不执行第二套字段校验。

成功后状态推进到 `project:04_assemble_foundation`。第 4 步尚未实现，入口仍明确返回“步骤尚未实现”。
