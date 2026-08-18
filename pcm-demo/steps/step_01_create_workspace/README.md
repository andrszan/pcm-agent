# 第 1 步：建立项目工作区

## 目标

从产品初稿取得最小项目身份，并把配置的开发管理模板初始化为一个新的产品项目工作区。当前步骤只负责项目工作区发布，不调用 `project-intake`。

## 运行前准备

需要：

- Python 3.10+、`uv`、`git`；
- OpenAI-compatible 服务支持 `POST /v1/responses` 和 `text.format` strict JSON Schema；
- 当前用户具备 `PCM_TEMPLATE_REPOSITORY` 的 Git SSH 读取权限；
- `PCM_WORKSPACE_ROOT` 已存在且可写；
- 目标项目目录尚不存在。

从 `pcm-demo/` 初始化：

```bash
uv sync
cp .env.example .env
chmod 600 .env
```

`.env` 仅保存本机配置，不提交。配置键：

```text
LLM_BASE_URL=
LLM_API_KEY=
LLM_MODEL=
PCM_WORKSPACE_ROOT=
PCM_TEMPLATE_REPOSITORY=
```

`--workspace-root` 的优先级高于进程环境中的 `PCM_WORKSPACE_ROOT`，再高于 `.env`。模板仓库只从进程环境或 `.env` 读取，不提供单次 CLI 覆盖。

## 输入与身份提取

Demo 输入为本地产品初稿路径；正式 PCM 将来可把初稿字符串直接保存到数据库。本步骤从初稿提取：

```json
{
  "topic_name": "修迹 MendMark 社区物品维修预约与进度协作系统",
  "project_directory_name": "mendmark"
}
```

`project_directory_name` 必须是小写 kebab-case。初稿没有明确名称时允许模型生成，并记录来源和理由。

身份提取使用 OpenAI Responses API：`instructions`、`input`、`text.format` strict JSON Schema，结果从 `response.output_text` 读取。当前服务不支持 Responses 或 strict JSON Schema 时返回 `failed`，不会回退 Chat Completions。

## 单独运行

```bash
uv run python run_step.py \
  --step 1 \
  --product-draft ../docs/prd/修迹-产品需求文档-v1.md \
  --workspace-root /absolute/path/to/products \
  --run-id step01-mendmark
```

## 第 0→1 串联

```bash
uv run python run_step.py \
  --step 0 \
  --product-draft ../docs/prd/修迹-产品需求文档-v1.md \
  --run-id step01-mendmark

uv run python run_step.py \
  --step 1 \
  --workspace-root /absolute/path/to/products \
  --run-id step01-mendmark
```

最终项目路径为：

```text
<PCM_WORKSPACE_ROOT>/<project_directory_name>/
```

## 确定性操作

1. 保存初稿源路径、完整 UTF-8 内容和 SHA-256；
2. 计算最终路径和同级临时路径 `<project_directory_name>.pcm-tmp-<run-id>`；
3. `git clone --depth 1` 克隆配置模板并记录 remote、默认分支、实际分支和 commit SHA；
4. 删除临时 clone 的 `.git/`，清空并保留 `docs/`；
5. 写入原始初稿字节到 `docs/产品初稿.md`；
6. 核验模板能力、`.git/`、`docs/` 和三方 SHA-256；
7. 同一文件系统内将临时目录原子重命名为最终目录。

## 运行证据与恢复

```text
runs/<run-id>/
├── state.json
├── steps/01.json
└── logs/
```

`publication_phase` 依次为：

```text
intent_recorded → clone_verified → prepared_verified → published
```

失败或阻塞后保留现场，用相同 `--run-id` 重试：

```bash
uv run python run_step.py \
  --step 1 \
  --workspace-root /absolute/path/to/products \
  --run-id step01-mendmark
```

程序不会覆盖已有最终项目、归属不明临时目录或符号链接。目录冲突、SSH 读取权限缺失和初稿选题不明确属于 `blocked`；API、解析、Git、哈希、清理和发布执行错误属于 `failed`。

## 成功验收

- `state.json` 状态为 `success`，发布阶段为 `published`；
- 最终项目存在，临时路径消失；
- `.git/` 不存在；
- `docs/` 只包含 `产品初稿.md`；
- `CLAUDE.md`、`AGENTS.md`、`project-intake` Skill、`frontend/`、`backend/` 存在；
- 源初稿和项目内初稿 SHA-256 一致；
- `template` 中的仓库、分支和 commit 证据与真实 Git 事实一致。

```bash
uv run python -m unittest discover -s steps -t . -p 'test*.py' -v
```
