# 第 16 步：规则复盘

## 当前职责

第 16 步只负责恢复第 15 步的原开发 session，并调用 `/session-rule-retrospective` 完成规则复盘。它采用与第 15 步一致的薄编排，不读取 Git，不重新核验第 15 步 result、TRD、分支、仓库或工作树。

最小输入为：

- 当前节点位于 `requirement:16_rule_retrospective`，或已推进到 `requirement:17_commit`；
- 当前活动需求与 cycle 一致；
- cycle 保存非空 `development_session_id`；
- `claude_sessions.development_<ID>` 保存同一个 session；
- 产品工作区可作为 Agent cwd。

## Agent、session 与 no-change

负责人 conversation 使用独立 key：

```text
rule_retrospective_<requirement-id>
```

首次调用 Agent 前，程序将该 key 的 Claude session alias 绑定为第 15 步保存的 `development_session_id`。公共 `run_agent_decision_loop` 因而恢复原开发 session，而不是新建替代 session；负责人 conversation 仍保持独立。

初始 prompt 固定为：

```text
/session-rule-retrospective 本次开发会话
请基于本会话真实发生的开发、验证、修复和审查事实完成复盘；如无满足沉淀门槛的候选，不修改文件并明确报告。
```

`completed` 允许规则有变化，也允许 no-change。第 16 步不根据 Git diff 判断复盘结果，不限制 Skill 的规则文件结构，也不要求必须生成产物。`continue` 和 `blocked` 沿用公共循环语义。

## 结果与恢复

success scoped result 写入：

```text
steps/requirements/<requirement-id>/16.json
```

`outputs` 固定为空，只保存 `requirement_id` 和 `development_session_id`。success 先写 result，再推进 `requirement:17_commit` / step 17；需求仍为 `active`、`completion: null`。

恢复规则：

- retrospective alias 已存在时必须仍等于原 `development_session_id`；
- Agent 返回不同 session 时由公共循环拒绝；
- blocked 保留当前节点、原 session alias 和独立 conversation；
- success result 已写但 state 未推进时只补状态，不调用 Agent；
- 已推进到第 17 步后只校验当前 scoped success 和 session，不读取工作区或调用模型。

第 16 步不读取 Git，也不建立 Git baseline。第 17 步负责读取实际未提交变更并执行提交；第 18 步负责合并。

## 自动化验证

当前覆盖：

- 原 development session alias 在 Agent 前持久化；
- 独立负责人 conversation；
- no-change success；
- `continue` 始终恢复同一 development session；
- blocked 保留当前节点和 session；
- Agent 返回替代 session 时失败；
- result→state 中断恢复；
- advanced 幂等不需要工作区或 Agent；
- CLI scoped success、blocked、failed 与成功保护；
- 第 16 步不导入 Git、哈希或文件取证模块。

第 16 步本体 7 项、CLI 4 项，共 11 项；相关定向 51 项和 PCM Demo 全量 282 项 `unittest` 通过，`compileall common steps run_step.py` 与 `git diff --check` 通过。

## 历史真实运行

真实 `step01-mendmark` 使用 development session `e6bd1b82-39f9-41b2-9cc9-a69b281015dc` 完成规则复盘，retrospective alias 使用同一 ID。Agent normal success，conversation 为 `system → assistant 初始 → user Agent 回复 → assistant completed`，唯一规则增量为 root `.claude/rules/frontend-playwright-container.md`。

当时旧实现曾因三仓提前需求提交与 cycle base 冲突而在 Agent 前失败，恢复后还使用 Git-visible baseline 证明规则增量范围。这些是旧实现的历史现场，不再是现行第 16 步 success 条件，也不会由现行代码重复核验；既有规则、result、state 和 conversation 不因本次精简而改写。

## 运行

```bash
uv --directory /Users/zhou/resource/fireworks/ANDRSZAN/pcm-agent-skills/pcm-demo run \
  python run_step.py --step 16 --run-id <run-id>

uv --directory /Users/zhou/resource/fireworks/ANDRSZAN/pcm-agent-skills/pcm-demo run \
  python -m unittest \
  steps.step_16_rule_retrospective.test_step \
  steps.step_16_rule_retrospective.test_cli -v
```
