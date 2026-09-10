# 第 0 步：接收产品初稿

## 目标

接收产品输入，不判断产品设计是否完整。一句话想法、自由格式说明或已有 PRD 都可以进入后续流程；不要求 Markdown 标题、章节或功能清单。

本步骤不调用 AI、不创建工作区、不扩写或修改初稿。第 1 步建立工作区，第 2 步通过产品定义沟通形成正式需求与功能文档。

## 输入与运行

`--product-draft` 接收本地 UTF-8 文本文件路径，不限制扩展名；`--run-id` 为可选运行标识。文件可以只有一句话。仍保留文件入口，不提供内联字符串或交互式聊天参数。

在 `pcm-demo/` 目录运行：

```bash
uv run python run_step.py \
  --step 0 \
  --product-draft /absolute/path/to/idea.txt \
  --run-id my-product
```

`--prd` 仍是 `--product-draft` 的兼容别名。

## 判断与结果

输入可读、可按 UTF-8 解码且不是纯空白时返回 `success`，不生成新初稿：

```json
{
  "step": 0,
  "status": "success",
  "applicable": false,
  "outputs": [],
  "skip_reason": "已有非空产品输入，无需生成初稿。"
}
```

空文件或纯空白返回 `failed`，错误类型为 `empty_product_draft`；文件读取或解码失败由入口按现有错误处理报告，不进入后续步骤。没有完整产品方案不属于输入错误。

运行证据仍保存在 `runs/<run-id>/state.json`、`steps/00.json` 及适用的诊断日志中；入口核验源文件哈希未改变。第 1 步原样发布为目标工作区的 `docs/产品初稿.md`，源文件扩展名不改变这一交接路径。

此前因旧章节门禁失败的运行，可使用原 run ID 恢复；不重置已经推进到后续步骤的状态。

## 验证

```bash
uv run python -m unittest steps.step_00_product_draft.test_step test_run_step_retry -v
```

覆盖一句话、自由标题、旧 PRD、空白、读取与解码错误，以及失败恢复和源文件不变性。
