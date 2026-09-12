# 第 1 步：建立项目工作区

## 目标

从产品初稿取得最小项目身份，并把配置的开发管理模板初始化为一个新的产品项目工作区。当前步骤只负责项目工作区发布，不调用 `project-intake`。

## 运行前准备

需要：

- Python 3.10+、`uv`、`git`；
- OpenAI-compatible 服务支持 `POST /v1/responses` 以及 Python SDK `responses.parse` 的 Pydantic 结构化输出；
- 当前用户具备 `PCM_TEMPLATE_REPOSITORY` 的 Git SSH 读取权限；
- `PCM_WORKSPACE_ROOT` 已存在、可写，且位于当前能力仓库之外；
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
PCM_AGENT_WORKSPACE_ENV_FILE=
```

`--workspace-root` 的优先级高于进程环境中的 `PCM_WORKSPACE_ROOT`，再高于 `.env`。无论来自哪一层，工作区根都必须位于当前 `pcm-agent-skills` 能力仓库之外。模板仓库和 `PCM_AGENT_WORKSPACE_ENV_FILE` 只从进程环境或 Demo `.env` 读取，不提供单次 CLI 覆盖；后者必须指向绝对、可读、非符号链接、非空的普通文件。

`PCM_AGENT_WORKSPACE_ENV_FILE` 是 PCM 提供给 AI Agent 工作区固定开发工具的受保护配置源。第 1 步只按原始字节把它写为新工作区根 `.env`，不解析或导出变量，不写入 `frontend/`、`backend/`，也不把它当作目标产品资源交给后续项目准备步骤；该 PCM 控制键本身会从 Claude Agent SDK 子进程环境中移除，Agent 只按既有约定在需要时读取工作区根 `.env`。

## 输入与身份提取

Demo 必需输入为本地产品初稿路径。新运行直接从本步骤开始，并在创建 `runs/<run-id>/` 或调用身份提取 AI 前确认初稿可读、可按 UTF-8 解码且不是纯空白。还可通过 `--initial-resources` 提供一个普通文件或目录。新运行保存解析后的源路径，第 1 步把资料复制到产品根 `initial-resources/<源 basename>`，不改名、不移动源、不软链接、不自动解压，目录内部结构保持不变。源及目录递归项中的符号链接和特殊文件会被拒绝；会递归包含目标项目或 staging 的目录也会被拒绝。空文件和空目录允许导入。

正式 PCM 将来可把初稿字符串直接保存到数据库。本步骤从初稿提取：

```json
{
  "status": "success",
  "topic_name": "修迹 MendMark 社区物品维修预约与进度协作系统",
  "project_directory_name": "mendmark",
  "directory_name_source": "source",
  "reason": "初稿已明确仓库名",
  "blocked_reason": null
}
```

`project_directory_name` 必须是小写 kebab-case。初稿没有明确名称时允许模型生成，并记录来源和理由；初稿无法确定明确产品选题时返回 `status: blocked`，其余身份结果字段为 `null`，当前步骤按既有规则记录为 `failed`。

身份提取将产品初稿构造成 Pydantic 输入模型，并使用 OpenAI Python SDK `responses.parse(..., text_format=ProjectIdentity)`；结果直接从 `response.output_parsed` 取得，不手写 JSON Schema 或解析原始 JSON 字符串。

## 单独运行

```bash
uv run python run_step.py \
  --step 1 \
  --product-draft ../docs/prd/修迹-产品需求文档-v1.md \
  --initial-resources ../资料/客户样本 \
  --workspace-root /absolute/path/to/products \
  --run-id step01-mendmark
```

第 2 步使用默认 Claude Code 用户配置、认证、插件、Skill 和 session；第 1 步只负责为产品路径建立项目 Git 边界，不创建独立 Claude 配置目录。

最终项目路径为：

```text
<PCM_WORKSPACE_ROOT>/<project_directory_name>/
```

`steps/01.json` 的 `outputs` 使用相对于该产品项目根的路径，只记录 `docs/产品初稿.md`；产品项目根本身由运行状态中的 `workspace.final_path` 记录。

## 确定性操作

1. 保存初稿源路径、完整 UTF-8 内容和 SHA-256；
2. 计算最终路径和同级临时路径 `<project_directory_name>.pcm-tmp-<run-id>`；
3. `git clone --depth 1` 克隆配置模板并记录 remote、默认分支、实际分支和 commit SHA；
4. 拒绝模板中任何形态的 `.env`，并以实际 Git 规则确认模板根忽略 `.env`；
5. 删除临时 clone 的 `.git/`，清空并保留 `docs/`；
6. 写入原始初稿字节到 `docs/产品初稿.md`，并将配置源原始字节独占写为根 `.env`、设置 `0600`；
7. 如有初始资料，复制到 `initial-resources/<源 basename>` 并核验副本只含普通文件和目录；复制中断保留现场且不把半复制当成功；
8. 核验模板能力、上游 `.git/` 已删除、`docs/`、初稿哈希以及根 `.env` 内容和权限；
9. 同一文件系统内将临时目录原子重命名为最终目录；
10. 在最终项目根执行 `git init -b main`，不暂存、不提交、不 push；
11. 核验 Git 根等于最终目录、分支为 `main`、`HEAD` 尚不存在，并再次确认根 Git 忽略 `.env`；有初始资料时，还必须以仓库自身规则确认实际根 Git 忽略导入路径，程序不会编辑 `.gitignore`。

## 运行证据与恢复

```text
runs/<run-id>/
├── state.json
├── steps/01.json
└── logs/
```

`publication_phase` 依次为：

```text
intent_recorded → clone_verified → prepared_verified → published → git_initialized
```

失败或阻塞后保留现场，用相同 `--run-id` 重试：

```bash
uv run python run_step.py \
  --step 1 \
  --workspace-root /absolute/path/to/products \
  --run-id step01-mendmark
```

程序不会覆盖已有最终项目、归属不明临时目录、已有 `initial-resources/` 或符号链接。初始资料复制中断会明确失败并保留半复制现场；推进到 `prepared_verified` 或已发布后，恢复只核验并使用工作区副本，不重新读取、同步或比较已删除/漂移的外部资料源。只有 SSH 读取权限缺失属于 `blocked`；工作区根位于能力仓库内部、目录冲突、初稿选题不明确、Agent 工作区配置缺失/无效/漂移、模板未忽略 `.env`、API、解析、Git、哈希、清理、发布或根仓库初始化错误属于 `failed`。原子发布后 `git init` 中断时，相同 run 只在发布证据、根 `.env` 和当前配置源一致的最终目录中补齐或核验零提交根仓库。已经推进到后续步骤的旧 run 不回退，也不由其它步骤自动补写根 `.env`。

## 成功验收

- `state.json` 状态为 `success`，发布阶段为 `git_initialized`；
- 最终项目存在，临时路径消失；
- 模板上游 `.git/` 已清理，最终项目根具有新 `.git/`；
- `git rev-parse --show-toplevel` 等于最终项目根，分支为 `main`，`HEAD` 不存在且没有 commit；
- `docs/` 只包含 `产品初稿.md`；
- `CLAUDE.md`、`AGENTS.md`、`project-intake` Skill、`frontend/`、`backend/` 存在；
- 根 `.env` 与当前配置源原始字节一致、权限为 `0600`，且实际根 Git 忽略该文件；
- 源初稿和项目内初稿 SHA-256 一致；
- `template` 中的仓库、分支和 commit 证据与真实 Git 事实一致。

```bash
uv run python -m unittest discover -s steps -t . -p 'test*.py' -v
```
