# gpt-image 工作区运行快照

- 上游：[wuyoscar/GPT-Image2-Skill](https://github.com/wuyoscar/GPT-Image2-Skill)
- Plugin 版本：`0.2.0`
- 作者及许可：Wuyoscar，见原始 [MIT LICENSE](LICENSE)

这是供 AI Agent 工作区使用的精简运行快照，不是上游展示仓库的完整镜像。

## 保留内容

- `.claude-plugin/`：Plugin 与 Marketplace 元数据。
- `skills/gpt-image/`：生图与编辑能力、launcher、完整案例 Prompt、创作方法和协议参考。
- `skills/get-prompt-from-image/`：参考图提示词提炼能力及分析方法。
- `src/`：原始 Python CLI 实现。
- `pyproject.toml`、本 README、`.gitignore` 和 `LICENSE`：包安装元数据、使用说明、生成物排除规则与许可。

## 与上游的差异

不打包 `docs/` 中的案例原图或其它展示资源，以及中文版 README、贡献、支持、行为准则、更新记录和 TODO 等上游项目维护文档。本 README 替代上游展示首页。

案例库保留 Prompt 正文、参数、作者和来源信息，只移除指向未打包图片的本地路径和预览标签；分类索引注明这一差异。案例原图可在上游仓库查看，不作为本地运行输入，也不在运行时自动下载。源代码、两个 Skill 的职责与执行指令、launcher 和创作方法保持不变；参考图编辑与提示词提炼仍使用调用方实际提供的图片。

## 运行

从产品工作区根目录执行受控 launcher，不需要在此目录创建 `.venv`：

```bash
uv run --no-project .agents/plugins/gpt-image/skills/gpt-image/scripts/generate.py --help
```

脚本通过 PEP 723 声明依赖，由 `uv` 在隔离缓存中准备。它从自身位置导入本快照的 `src/`，但 `.env` 和相对输入、输出路径仍按当前工作目录解析。

连接配置使用 `OPENAI_BASE_URL` 和 `OPENAI_API_KEY`，模型默认 `gpt-image-2`，其它模型通过 `--model` 指定；不在快照中保存凭据。实际生成必须遵循工作区的授权、成本和资产落盘约定，传入明确的 `-f` 输出路径。`--help` 不调用生图接口。
