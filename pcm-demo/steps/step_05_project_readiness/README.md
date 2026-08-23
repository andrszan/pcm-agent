# 第 5 步：核验项目准备状态

## 输入

- 运行状态位于 `project:05_verify_readiness`，且产品根 Git 仓库与状态记录一致。
- `steps/02.json` 成功，引用两份位于产品工作区内、非空且非符号链接的产品定义文件。
- `steps/03.json` 成功，`template_selection` 可由 `FoundationSelectionResult` 校验；传入提示的选型仅投影 `applicable`、`id`、`default_branch`、`path`、`reason`，不传 `git_url` 或 `origin`。
- `steps/04.json` 成功，已组装工程、来源证据和临时目录现场均与选型和状态一致；每个适用 `frontend` / `backend` 都是自身 top-level 为目录本身、`main`、unborn HEAD、空 index 的独立 Git 仓库，不适用端不存在。
- `PCM_DEV_RESOURCE_LIST` 是可读普通文件的绝对路径。

## 行为

在产品项目根显式调用 `/project-readiness`。首条提示第一行保留 slash command，正文只描述产品定义、实际工程、选型公开事实、可信资源清单和项目准备核验边界；不包含步骤号、PCM 节点或其它外层编排语义。

调用方已授权创建或更新 `docs/requirements/项目准备清单.md`。Agent 可读取可信资源清单、创建项目专用开发/测试数据库和桶、写入被忽略的实际 `.env` 并以工具核验；不得创建生产资源、泄露秘密、改变现有 Git 边界，或执行 Git 暂存、提交、分支、合并、推送。依赖安装、构建、测试、启动、仓库首次提交、业务实现和完整验收属于后续工作，不作为当前准备阻塞。

## 统一决策与恢复

每次 Agent 调用保存 init 核验、session 和安全的终止摘要；完整真实 Agent 回复先作为决策历史 `user` 消息保存，再交给步骤专属决策 system prompt 生成统一 `AgentDecision`：

- `continue` 的非空 `answer` 原样发给同一 session；它是内部循环，不产生步骤结果。
- `completed` 后程序重新核验前序交接、产品根和全部适用子仓的 Git 边界（各自 top-level、`main`、unborn HEAD、空 index）及非空普通清单。清单可安全补完时，向同一 session 追加固定清单修复提示后继续；交接、路径、Git 或文件类型冲突为 `failed`。
- `blocked` 只表示当前环境不可取得的真实账号、凭据、私有数据、授权、专用设备、素材、付费服务或线下动作；写入终止前同样复核上述 Git 边界。CLI 保持原有三态结果格式，并在清单已存在时保留其输出引用。
- `error_max_turns`、`error_max_budget_usd` 只在有 session 和非空回复时进入裁决；最终完成前必须恢复一次正常 `success`。400/429/500、连接、CLI/进程、无 `ResultMessage` 与其它 SDK/API 错误返回 `failed`，没有外层自定义 HTTP 重试。

`conversations/project_readiness.json` 尾部是唯一调度真相：`user` 尾部先裁决，结构化 `continue` 尾部执行 answer，`completed` 尾部先核验，`blocked` 尾部停止；显式从 `blocked` 重跑才重新核验。状态不再写 `pending_agent_prompt`、决策轮次或 Python 完成声明，只保留 session、对话路径引用、最后一次 Agent 终止摘要和短暂的待写入 Agent 原文。旧 `action` 和旧完成 sentinel 仅只读兼容，既有对话不会转换回写。

## 输出与幂等

成功产物为 `docs/requirements/项目准备清单.md`，`steps/05.json.outputs` 只记录该相对路径。步骤先写成功结果，再推进到 `project:06_bootstrap_foundation`。只有 `status=success` 的既有结果可作为幂等锚点；若成功结果后状态写入中断，重跑会重新核验清单、领域事实和 Git 边界后推进。`failed` / `blocked` 结果不视为成功，也不阻止恢复原 session。

## 运行

```bash
cd /Users/zhou/resource/fireworks/ANDRSZAN/pcm-agent-skills/pcm-demo
uv run python run_step.py --step 5 --run-id <run-id>
```