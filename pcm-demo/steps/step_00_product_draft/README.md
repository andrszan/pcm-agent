# 第 0 步：形成产品初稿

## 目标

判断输入是否已经是完整产品初稿。当前黄金产品初稿已经具备产品身份、用户场景、核心闭环、产品范围和验收标准，因此通过确定性检查后无副作用跳过。

本步骤不调用 AI、不创建工作区、不修改初稿，也不生成正式产品文档。

## 输入

- `--product-draft`：产品初稿的本地 UTF-8 Markdown 路径；
- `--run-id`：可选的运行标识。

## 运行

在 `pcm-demo/` 目录执行：

```bash
uv run python run_step.py \
  --step 0 \
  --product-draft ../docs/prd/修迹-产品需求文档-v1.md \
  --run-id step00-mendmark
```

也可以使用兼容旧命令的 `--prd` 参数，但新脚本建议使用 `--product-draft`。

## 判断与结果

程序检查以下 Markdown 二级标题且每个标题后有正文：

- `## A. 产品身份与文档边界`
- `## C. 用户与使用场景`
- `## D. 核心价值与业务闭环`
- `## E. 产品范围`
- `## P. 产品验收`

完整时结果为：

```json
{
  "step": 0,
  "status": "success",
  "applicable": false,
  "outputs": [],
  "skip_reason": "输入已经是完整产品初稿"
}
```

缺少文件或必要章节时返回 `failed`，不会伪造成功。

## 产物与验证

运行证据保存在：

```text
runs/<run-id>/
├── state.json
├── steps/00.json
└── logs/
```

验证源文件未被修改：

```bash
shasum -a 256 ../docs/prd/修迹-产品需求文档-v1.md
```

第 1 步会从同一个 run 继续建立项目工作区，并把初稿写入项目的 `docs/产品初稿.md`。
