# 第 12 步：解析 Backlog 并初始化需求注册表

本步骤将第 11 步已经生成的自由格式 Backlog 交给 OpenAI-compatible Responses API，以 Pydantic Structured Outputs 提取需求静态字段，并初始化需求开发生命周期的唯一结构化注册表；不选择需求、不创建分支、不修改产品项目，也不执行 Git 操作。

## 运行

在 `pcm-demo/` 目录执行：

```bash
uv run python run_step.py --step 12 --run-id <run-id>
```

定向自动化测试：

```bash
uv run python -m unittest \
  steps.step_12_initialize_requirement_registry.test_step \
  steps.step_12_initialize_requirement_registry.test_cli -v
```

## 输入与职责边界

程序严格读取 `steps/11.json` 的完整 success，唯一权威输入是产品工作区中的：

```text
docs/backlog/backlog.md
```

Backlog 是自由格式自然语言文档，不要求固定总览表、详情卡、标题层级或依赖章节。文件必须位于状态记录的产品工作区内，是非空、UTF-8、非符号链接普通文件，且路径链不能包含符号链接。

Responses API 是唯一语义提取器。初始 system prompt 明确要求：

- 提取全部且仅有的正式需求，排除目录、背景、说明、示例、风险、非目标、历史、候选和未来设想；
- 同一正式需求只输出一次，不遗漏、合并、拆分、虚构或补充需求；
- 忠实保留文档明确给出的 `id`、`title`、正式顺序和显式前置依赖；
- 未明确声明的依赖返回空数组，不根据正文关联、出现先后、业务常识或实现关系猜测；
- 数组物理顺序与连续 `order` 一致；顶层只能有 `requirements`，每项只能有 `id`、`title`、`order`、`depends_on`；
- 只返回严格 JSON，不返回动态生命周期字段、Markdown、代码围栏、解释或分析过程。

Python 不解析 Markdown 结构，也不与另一套确定性解析结果进行语义比对。它只校验模型输出能否安全驱动后续生命周期：需求非空、ID 合法且忽略大小写唯一、数组顺序严格对应 `order=1..N`、依赖存在且不重复、不自依赖、无环。

程序从同一次文件字节读取生成模型输入文本和 SHA-256；模型调用完成后重新读取文件并比较指纹。调用期间 Backlog 内容变化会失败，不会把旧文本的提取结果绑定到新文件。

本步骤不读取 root Git 分支、HEAD、工作树或 tracked 状态。第 11 步负责其固定 Backlog 的 Git 交付，第 12 步的来源只绑定实际模型输入的文件路径与内容指纹。

这是本地单进程 Demo 的文件边界，不是针对同权限恶意进程的不可绕过沙箱。路径链在每次读取前拒绝符号链接，模型调用后用 SHA 检测内容漂移；若正式 PCM 需要抵抗并发恶意替换，应在统一工作区隔离层实现，而不是在领域步骤扩展文件系统 DSL。

## 结果、状态与恢复

成功的 `steps/12.json` 保存：

```json
{
  "source": {
    "path": "docs/backlog/backlog.md",
    "sha256": "<backlog-sha256>"
  },
  "requirement_catalog": [
    {
      "id": "BR-001",
      "title": "正式需求标题",
      "order": 1,
      "depends_on": []
    }
  ]
}
```

`outputs` 始终为空。随后状态写入 `schema_version: 1` 的 `requirement_registry`，每项由 Python 增加：

```json
{
  "status": "pending",
  "completion": null
}
```

成功后状态进入 `phase_1:select_requirement`，`step` 与 `current_step` 均为 13，`active_requirement` 和 `requirement_cycle` 均为 `null`。

完整 success 是恢复锚点：当前 Backlog 路径/SHA-256、静态 catalog 和全 pending 注册表完全一致时零模型调用确认既有成功；若 success result 已写入而状态仍停在初始化节点，则从 result 恢复注册表并推进。来源、catalog 或注册表冲突会失败且不覆盖。失败结果只有在状态仍位于初始化节点且不存在注册表时才可重跑；若状态已推进而成功 result 损坏，视为证据冲突并保留现场，不自动回退或重建生命周期。

旧合同的 `source` 还包含 `root_main_sha`，并依赖 Markdown 总览、详情卡和模型三方比对。新生产入口不兼容或迁移该结构；旧 run 仅作为历史证据保留。

## 自动化与真实验证

当前新合同验证结果：

- 第 12 步本体 10 项、CLI 6 项，共 16 项通过；
- 第 12～14 步定向回归 61 项通过；
- PCM Demo 全量递归 `unittest` 282 项通过（82.099 秒）；
- `compileall common steps run_step.py` 通过；
- `step.py` IDE diagnostics 为零。

真实隔离 run 为：

```text
pcm-demo/runs/step12-ai-only-20260826
```

对应产品工作区位于能力仓库外：

```text
/Users/zhou/resource/fireworks/ANDRSZAN/pcm-products/step12-ai-only-validation
```

该工作区没有 Git 仓库。Backlog 使用自然语言段落描述三项正式需求，没有总览表、详情卡模板或固定标题层级，并包含一个明确排除的 `NOTE-001` 示例和一个未来在线支付设想。真实 Responses 调用准确提取 `BR-AI-001`～`BR-AI-003`，标题、顺序和显式依赖均与原文一致，未误收示例或未来设想。

成功来源 SHA-256 为 `c8fb63f1e403fcf36c302f77511dfb7ea29a305a345f6bf125c9c101801f8f76`；注册表三项均为 `pending`、`completion: null`，状态推进到第 13 步。随后以不可连接的 LLM 配置重跑仍 success，证明完整成功路径未调用模型；result/state 字节均未变化，SHA-256 分别为 `047e6b8e615471ecb930709f942b62cffc29b57a9013815cc5ab97ed617e321f` 和 `9871652c38042459827724fab5559df5492ec5377e356fac23bc189487e76472`。
