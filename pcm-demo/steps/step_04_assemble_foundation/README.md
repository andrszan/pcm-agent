# 第 4 步：组装基础工程

## 输入

只读取当前 run 的 `steps/03.json`。该结果必须是成功的基础工程选型，并用第 3 步的 `FoundationSelectionResult` 校验前端和后端模板选择。运行状态必须仍指向 `project:04_assemble_foundation`，产品根目录必须是 state 已记录的零提交、空 index 的 `main` Git 仓库。

## 动作

对每个非 `null` 选择，按唯一的 `(git_url, default_branch)` 执行一次浅克隆，核验 origin、分支和 HEAD SHA 后复制选中的模板子目录。准备过程位于产品目录同级的 run-owned 临时目录：上游 `.git` 和任何符号链接均在复制前拒绝；复制后，对每个实际适用 payload 执行 `git init -b main`，核验 Git top-level 就是 payload 自身、分支为 `main`、HEAD 为 unborn、index 为空，并且 `git ls-files --others --exclude-standard` 至少返回一个可提交文件。全部内容被自身 ignore 或没有文件的适用模板会在发布前失败。

新复制的前后端 payload 在初始化 Git 前补充内部 Agent 配置的 `.gitignore` 规则，保留配置文件和已有忽略内容；初始化后核验内部配置不在可提交候选中，冲突时发布前失败。该策略不改模板源仓库、产品根工作区或已组装产品，具体规则见 [PCM 流程第 4 步](../../../.claude/PCM版AI%20Agent自动化流程设计.md#第-4-步组装基础工程)。

只有全部 payload 均通过上述核验，才替换 `frontend/`、`backend/` 中严格唯一的 `.gitkeep` 占位目录并以 `os.rename()` 发布。目标不存在也可发布；空目录、符号链接、额外内容和既有工程均会被拒绝。`null` 端仅移除严格占位目录，发布后必须不存在。第 4 步不执行 `git add`、`git commit` 或 push。

## 结果和恢复

成功结果写入 `steps/04.json`，其中记录适用端、产物目录和实际 origin、branch、commit SHA；状态推进到 `project:05_verify_readiness`、第 5 步。成功复用会重新核验来源记录、适用仓自身 top-level、`main`、unborn HEAD、空 index、非适用端不存在及临时目录，不重新 clone。

Git 认证或读取权限缺失会写入 `blocked`，补齐模板仓库访问权限后用相同 run 重试。其他错误写入 `failed` 并停留在本步骤。仅当临时目录名称、父目录和 ownership marker 均与当前 run 完全匹配，且目标仍是占位或不存在时，才会删除失败残留并重新准备；未知残留和部分发布现场会保留且拒绝覆盖。

## 运行

```bash
cd pcm-demo
uv run python run_step.py --step 4 --run-id <run-id>
uv run python -m unittest steps.step_04_assemble_foundation.test_step -v
```
