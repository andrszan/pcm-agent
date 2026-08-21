# 第 4 步：组装基础工程

## 输入

只读取当前 run 的 `steps/03.json`。该结果必须是成功的基础工程选型，并用第 3 步的 `FoundationSelectionResult` 校验前端和后端模板选择。运行状态必须仍指向 `project:04_assemble_foundation`，产品根目录必须是 state 已记录的零提交 `main` Git 仓库。

## 动作

对每个非 `null` 选择，按唯一的 `(git_url, default_branch)` 执行一次浅克隆，核验 origin、分支和 HEAD SHA 后复制选中的模板子目录。准备过程位于产品目录同级的 run-owned 临时目录，全部 payload 合格后才替换 `frontend/`、`backend/` 中严格唯一的 `.gitkeep` 占位目录。目标不存在也可发布；空目录、符号链接、额外内容和既有工程均会被拒绝。

模板路径必须是未逃出 clone 根目录的真实目录。选中子树中的 `.git` 和任何符号链接都会被拒绝。发布后不允许存在嵌套 `.git`。

## 结果和恢复

成功结果写入 `steps/04.json`，其中记录适用端、产物目录和实际 origin、branch、commit SHA；状态推进到 `project:05_verify_readiness`、第 5 步。已成功的运行会在最小现场核验后复用结果，不重新 clone。

Git 认证或读取权限缺失会写入 `blocked`，补齐模板仓库访问权限后用相同 run 重试。其他错误写入 `failed` 并停留在本步骤。仅当临时目录名称、父目录和 ownership marker 均与当前 run 完全匹配，且目标仍是占位或不存在时，才会删除失败残留并重新准备；未知残留和部分发布现场会保留且拒绝覆盖。

## 运行

```bash
cd pcm-demo
uv run python run_step.py --step 4 --run-id <run-id>
uv run python -m unittest steps.step_04_assemble_foundation.test_step -v
```
