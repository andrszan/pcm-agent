# 第 12 步：解析 Backlog 并初始化需求注册表

本步骤只解析第 11 步已经提交的固定 Backlog，初始化需求开发生命周期的唯一结构化注册表；不选择需求、不创建分支、不修改产品项目，也不执行 Git 写操作。

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

## 输入与校验

程序严格读取 `steps/11.json` 的完整 success，唯一权威输入是产品根仓已跟踪的：

```text
docs/backlog/backlog.md
```

产品根必须是自身 Git top-level、当前分支为 `main`、工作树 clean，且有有效 `HEAD`。Backlog 必须为非空、非符号链接普通文件；路径不接受绝对路径、越界路径或任一层符号链接。

Responses API 使用 Pydantic 仅提取每项正式详情卡的 `id`、`title`、`order` 与 `depends_on`。当前正式格式必须有唯一 `大需求总览` 表和唯一 `需求详情` 区：总览表必须有唯一 ID、标题和依赖列，依赖列名只接受 `前置依赖`、`依赖`、`depends_on`、`dependency` 或 `dependencies`。`无`、`无。`、`-` 和空单元格归一化为空依赖；其余值只能按原顺序引用总览中已知的需求 ID，不能包含未知文本或 ID。每张详情卡必须有唯一 `##### 前置依赖` 章节，其内容只接受同样的空值或逐行项目符号 ID；详情区内全部四级需求卡必须与总览逐项、标题、出现顺序和依赖一致，模型输出再与该三方确定的静态字段精确一致。附录等详情区外标题不参与解析。Python 拒绝遗漏、虚构、重复 ID 或顺序、非连续顺序、标题或依赖不一致、不存在/重复/自依赖及依赖环。

## 结果、状态与恢复

成功的 `steps/12.json` 保存 Backlog 路径、SHA-256、根仓 `main` SHA 和仅含静态字段的 `requirement_catalog`，`outputs` 始终为空。随后状态写入 `schema_version: 1` 的 `requirement_registry`，每项由 Python 增加：

```json
{
  "status": "pending",
  "completion": null
}
```

成功后状态进入 `phase_1:select_requirement`，`step` 与 `current_step` 均为 13，`active_requirement` 和 `requirement_cycle` 均为 `null`。

完整 success 是恢复锚点：Backlog 指纹、根仓 SHA、静态目录和状态注册表完全一致时零模型调用确认既有成功；若 success 已写入而状态仍停在初始化节点，则从结果恢复全量 pending 注册表。来源、目录或注册表冲突会失败且不覆盖。所有输入、状态、文件、Git、模型或校验错误均保存为 `failed`；失败结果不构成成功锚点，可从初始化节点重跑。生产入口不接受旧 `phase_1:select_requirement` / step 12 占位状态，也不兼容旧第 12 步入口。

## 自动化与真实验证

自动化已通过本体 11 项与 CLI 6 项，共 17 项；加上第 11 步本体 9 项与 CLI 6 项，共 15 项，两步定向共 32 项、全量递归 `unittest` 194 项均通过。`compileall`、`git diff --check` 通过；IDE 对本步骤 `step.py`、`test_step.py`、`test_cli.py` 和 `run_step.py` 无诊断，独立只读审查最终没有高、中置信发现。Ruff 未安装，未执行 Ruff。

真实 run 为 `pcm-demo/runs/step01-mendmark`。执行前严格核验历史第 11 步为完整 success，`active_requirement`、`requirement_cycle` 均为 `null`，没有 `requirement_registry` 或 `steps/12.json`，产品 root/frontend/backend 均为自身 top-level、`main`、clean。该历史 state 当时仍指向旧 `phase_1:select_requirement`；仅在 run-local 将其规范化为 `phase_1:initialize_requirement_registry`，state SHA-256 从 `c153ec8c9d39d82806009c7052988695fe10d3a384566f00f852c2c8b4b02ee8` 变为 `eecf476c3b6c401c9db6a41f9f3ca398056eb509de956c93b0f9fae55f0ec170`，生产代码未添加旧入口兼容。

真实 Responses 调用成功提取 BR-001～BR-014 共 14 条，标题、连续 `order` 1～14 和依赖均与 Backlog 总览、详情卡一致；状态注册表全部为 `pending`、`completion: null`。结果来源记录的 Backlog SHA-256 为 `707c4b91924542e9cbd282fba53cc8857b8ea1fcbdfb7a820c208d0573d759bb`，root `main` SHA 为 `0232d8136c075cb61a6617a95e1504b67bd9acd1`。成功后 state 位于第 13 步 `phase_1:select_requirement`，`active_requirement`、`requirement_cycle` 均为 `null`，未新增 `completed_requirements` 或 `phase_two`，也没有新建 Claude session 或负责人决策 conversation。

运行后的产品仓 root SHA 为 `0232d8136c075cb61a6617a95e1504b67bd9acd1`，frontend 为 `dbab574dbe4d83a02323a750afd04de007565ac5`，backend 为 `9682be837759c20f1a9ebbdf8fa2cfc09c2768d4`；三仓均为 `main`、clean。随后以不可用模型配置重跑 CLI 仍 success，证明完整成功重跑不加载模型；`steps/12.json` 与 state 均保持字节不变，最终 result SHA-256 为 `8f829cb3d4935a9dcd07bea2dd8f0df2a22369c433ba4320938e2a9461f41fb0`，state SHA-256 为 `73fd0cb99c39f64f9ef210a171799f79baaee87a417a18f5db74f5b5374470f7`。
