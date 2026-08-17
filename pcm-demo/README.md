# PCM 自动化流程 Demo

这是 PCM 自动化流程的本地验证工具。当前只实现并验证了：

- **第 0 步：形成产品初稿**——检查输入是否已经是完整产品初稿；完整时无副作用跳过；
- **第 1 步：建立项目工作区**——从产品初稿提取选题和项目文件夹名，浅克隆配置的开发管理模板，清理上游 Git 历史和模板文档，再安全发布为新项目目录。

第 2 步及后续步骤尚未实现，调用时会以退出码 `2` 明确拒绝。

## 环境准备

要求：

- Python 3.10+；
- `uv`；
- `git`；
- 能通过 SSH 读取 `PCM_TEMPLATE_REPOSITORY` 指向的 GitLab 仓库；
- 支持 Responses API 且支持 `text.format.json_schema` 的 OpenAI-compatible 服务。

在 `pcm-demo/` 目录执行：

```bash
uv sync
cp .env.example .env
chmod 600 .env
```

`chmod 600 .env` 使包含 API Key 的本机配置仅能由当前用户读取和修改。然后在 `.env` 中填写或确认以下配置。`.env` 已被 Git 忽略，不要提交其中的实际值：

```text
LLM_BASE_URL=
LLM_API_KEY=
LLM_MODEL=
PCM_WORKSPACE_ROOT=
PCM_TEMPLATE_REPOSITORY=
```

- `LLM_*`：第 1 步从产品初稿提取项目身份时使用的 OpenAI-compatible 服务配置；
- `PCM_WORKSPACE_ROOT`：所有新产品项目的父目录；
- `PCM_TEMPLATE_REPOSITORY`：第 1 步固定使用的开发管理模板仓库。

Claude Agent SDK 的认证使用当前进程环境或既有 Claude 登录态；Demo `.env` 当前不加载 `ANTHROPIC_API_KEY`。进入 SDK 步骤前，再按当时已确认的认证合同配置。

配置优先级：

1. `--workspace-root` 仅覆盖 `PCM_WORKSPACE_ROOT`；
2. 同名进程环境变量覆盖 `.env`；
3. `.env` 覆盖 `.env.example` 中的占位说明。

模板仓库没有 CLI 覆盖参数，避免单次运行悄然替换模板来源。

## 运行步骤

以下命令都在 `pcm-demo/` 目录执行。示例产品初稿位于仓库根目录的 `docs/prd/修迹-产品需求文档-v1.md`。

### 单独验证第 0 步

```bash
uv run python run_step.py \
  --step 0 \
  --product-draft ../docs/prd/修迹-产品需求文档-v1.md \
  --run-id mendmark-demo-001
```

成功时会创建：

```text
runs/mendmark-demo-001/
├── state.json
├── steps/00.json
└── logs/
```

### 从第 0 步串联运行第 1 步

第 1 步使用第 0 步已经保存的初稿和 run 状态：

```bash
uv run python run_step.py \
  --step 1 \
  --workspace-root /absolute/path/to/products \
  --run-id mendmark-demo-001
```

`--workspace-root` 可省略，此时读取 `PCM_WORKSPACE_ROOT`。第 1 步成功后，项目目录为：

```text
/absolute/path/to/products/<project_directory_name>/
├── CLAUDE.md
├── AGENTS.md
├── .claude/
├── frontend/
├── backend/
└── docs/
    └── 产品初稿.md
```

其中 `<project_directory_name>` 由 Responses API 从产品初稿提取或生成，必须是小写 kebab-case。发布后的目录不保留模板上游 `.git/`；`docs/` 只保留本次写入的 `产品初稿.md`。

### 独立运行第 1 步

第 1 步也可以从初稿直接开始：

```bash
uv run python run_step.py \
  --step 1 \
  --product-draft ../docs/prd/修迹-产品需求文档-v1.md \
  --workspace-root /absolute/path/to/products \
  --run-id mendmark-demo-standalone
```

## 状态、恢复与产物

`runs/<run-id>/` 是本地、被 Git 忽略的运行证据目录：

- `state.json`：项目身份、初稿路径/内容/SHA-256、模板分支和 commit、发布阶段及检查结果；
- `steps/00.json`、`steps/01.json`：每一步的详细结果；
- `logs/`：后续步骤使用的脱敏日志目录。

步骤只返回三种业务状态：

- `success`：所有完成条件与文件事实均已满足；
- `blocked`：缺少 SSH 读取权限、产品选题不明确、目录已存在或现场归属不明等需要人工处理的条件；
- `failed`：配置、Responses API、Git 命令、文件、哈希或发布操作发生错误。

第 1 步失败或阻塞后，不要删除临时目录或最终项目目录。确认外部条件后，用**相同的** `--run-id` 重跑第 1 步：

```bash
uv run python run_step.py \
  --step 1 \
  --workspace-root /absolute/path/to/products \
  --run-id mendmark-demo-001
```

程序会依据保存的发布阶段、模板证据、初稿哈希、临时目录和最终目录事实继续或安全阻塞，不会覆盖归属不明的目录。

## 验收检查

第 1 步成功后，至少检查：

```bash
# 源初稿与项目内初稿应具有相同 SHA-256
shasum -a 256 ../docs/prd/修迹-产品需求文档-v1.md \
  /absolute/path/to/products/mendmark/docs/产品初稿.md

# 项目目录不应保留模板上游 Git 历史
[ ! -e /absolute/path/to/products/mendmark/.git ]

# docs 仅保留当前产品初稿
find /absolute/path/to/products/mendmark/docs -maxdepth 1 -type f -print
```

运行测试：

```bash
uv run python -m unittest discover -s tests -t . -v
```

## 常见问题

| 现象 | 处理方式 |
| --- | --- |
| `缺少配置：PCM_WORKSPACE_ROOT` | 在 `.env` 设置该目录，或传入 `--workspace-root`。 |
| `缺少配置：PCM_TEMPLATE_REPOSITORY` | 在 `.env` 设置固定模板仓库 SSH 地址。 |
| `服务不支持 Responses API` | 当前服务只兼容 Chat Completions；改用支持 `/v1/responses` 的服务或修正 `LLM_BASE_URL`。不会自动回退到旧 API。 |
| `服务不支持 Responses API 的 strict JSON Schema` | 当前服务未实现 `text.format.json_schema`；需使用支持 Responses Structured Outputs 的服务。 |
| `缺少固定模板仓库的 SSH 凭据或读取权限` | 核验本机 SSH/GitLab 授权后，使用同一 run ID 重试。 |
| `最终项目路径已存在或发布现场冲突` | 不要覆盖已有目录；核对该目录和临时目录归属后，改用新项目名或新 run。 |

## 参考

- [第 1 步活动技术合同](../docs/pcm/PCM自动化流程Demo项目TRD.md)
- [PCM Demo 项目设计](../docs/pcm/PCM自动化流程Demo项目设计.md)
- [OpenAI Responses API 迁移指南](https://developers.openai.com/api/docs/guides/migrate-to-responses#migrating-from-chat-completions)
