# 第 14 步：形成活动 TRD

## 当前职责

第 14 步只为当前活动需求形成一份可直接指导实现和验证的活动 TRD。它采用与第 15 步一致的薄编排方式：信任严格串行流程中已经写入 state 的活动需求和 cycle，不重新执行前序步骤的职责，也不防御流程外的人为修改。

步骤只读取当前运行所需的最小状态：

- 运行位置为 `requirement:14_trd_design`，或已推进到 `requirement:15_development`；
- `active_requirement` 对应注册表唯一 `active` 且尚未完成的需求；
- `requirement_cycle` 属于同一需求，并提供统一需求分支名；
- 产品工作区存在。

第 14 步不重新读取或精确复验第 2、5、7、8、9、10、11、12、13 步结果，不检查上游文档是否 tracked，也不重复核验第 13 步已经建立的 Git 分支和基线。Agent 根据 `/trd-design` 能力和当前项目事实按需读取产品资料、Backlog、代码、测试、接口、数据、权限、配置与运行约定。

## 路径 intent

首次执行时，Python 按以下格式计算唯一输出路径：

```text
docs/trd/<YYYY-MM-DD>-<requirement-id>-<requirement-title>.md
```

文件名使用首次执行日期，并对直接用于文件名的需求标题做最小合法性检查。目标已存在时不覆盖。

程序在首次调用 Agent 前先把精确 `trd_path` 写入 `requirement_cycle`。进程中断、blocked 或后续恢复都只复用这个值，不根据新的日期重新计算。

## Agent 与负责人决策

Claude Agent 在产品根运行，使用 requirement-scoped key：

```text
trd_design_<requirement-id>
```

初始 prompt 首行显式调用 `/trd-design`，只给出当前需求 ID、标题和唯一 `trd_path`，以及收敛活动 TRD 的简短职责；其它项目资料由 Agent 按需读取。prompt 只允许创建或更新该 TRD，禁止实现业务功能、修改其它文件或执行 Git 写操作。

对本需求真正适用的体验决定，Agent 按需从任意来源发现已确认的 Target 或有依据的默认 Target，并在 TRD 记录来源、适用范围、经核验的 Current、Target 与本需求遵循或改变。默认 Target 必须包含依据与重议条件，偏离必须说明理由；改变跨需求骨架由负责人决定。没有适用决定时不虚构也不阻塞，不要求固定框架文档、资料来源或技术栈。

第 14 步直接复用公共 `run_agent_decision_loop`：

- 公共循环保存并恢复 Claude session、conversation 和待裁决 Agent 回复；
- `continue` 恢复同一 session；
- `blocked` 只用于当前环境无法取得的不可替代外部条件；
- `completed` 要求范围、关键行为、技术方案、验证场景、需求级体验设计和阻碍实现的决定已经收敛；适用体验决定已在 TRD 留下来源、范围、Current、Target 与遵循或改变的记录，默认 Target 的依据和重议条件齐全、没有静默偏离，跨需求骨架改变已有负责人决定。

领域步骤不解析公共 conversation 的消息结构，不重复核验 session/reference 组合，也不增加步骤私有 tool hook 或 Git 监管逻辑。

## 完成、结果与状态

负责人返回 `completed` 后，Python只核验指定 `trd_path` 是产品工作区内的非空文件。文档缺失或为空时，公共循环向原 session 发送固定补全提示；本步骤不调用 `/commit-changes`。

成功时先写：

```text
steps/requirements/<requirement-id>/14.json
```

result 保存 requirement ID、统一分支、`trd_path`、原 TRD session ID和唯一 output。随后 state 推进到：

```text
requirement:15_development
```

活动需求仍为 `active`，`completion` 仍为 `null`，TRD 保留为待提交变更。

第 14 步不读取或写入 Git，不证明工作树只有这一份文件，也不重复检查 `HEAD/main/target/base`、index、merge、rebase、bisect 或其它仓库状态。第 13 步负责建立统一需求分支，第 17 步负责提交，第 18 步负责合并；这些职责不在第 14 步重复实现。

## 恢复与幂等

- `trd_path` 尚未写入时发生错误，不创建 scoped result；
- `trd_path` 已写入后，后续运行沿用原路径；
- 原 session 和 conversation 由公共循环恢复；
- blocked 写 scoped result并保留当前节点、路径和 session；
- success result 已写但 state 未推进时，确认指定 TRD 非空后只补状态推进；
- state 已进入第 15 步后，只校验当前 requirement 的完整 scoped success 和状态，不再读取 TRD、调用 Agent 或负责人模型；
- 历史 requirement 的 result、session 或 conversation 不保护当前 requirement。

## 自动化覆盖

当前测试覆盖：

- 不依赖上游步骤结果、Git 仓库或固定项目文档的薄输入执行；
- 首次 `trd_path` 在 Agent 前持久化；
- `continue` 与补全文档均恢复公共循环保存的同一 session；
- 指定 TRD 缺失或为空时的 repair；
- blocked scoped result和 session 保留；
- result 写入后 state 推进中断恢复；
- 推进到第 15 步后的无文件、无 Agent 幂等；
- CLI scoped success、blocked、failed 与成功保护；
- 第 14 步不导入或执行 Git `subprocess`；
- 本轮与第 10、11、15 步合计 72 项步骤本体和 CLI 定向测试通过；
- PCM Demo 全量 321 项 `unittest`、`compileall common steps run_step.py test_run_step_retry.py` 与 `git diff --check` 通过；未运行新的真实 Claude Agent 或负责人集成。

## 历史真实运行

真实 run `pcm-demo/runs/step01-mendmark` 曾使用 session `b9ed4756-0acf-4666-b3f9-c8f3628c03f1` 生成：

```text
docs/trd/2026-08-25-BR-001-身份、角色访问与站内消息入口.md
```

首次负责人错误接受了 8 项“实现前必须确认”事项，随后在同一 session 中收敛这些决定；负责人服务 HTTP 403 后也从原 conversation 尾部恢复完成。该事实继续证明路径 intent、同 session 恢复和 completion 语义有价值。

当时 root 只有唯一未跟踪 TRD、其它仓库 clean、各仓 refs 等于第 13 步 base，这是旧实现运行结束时的历史现场，不再是现行第 14 步 success 条件，也不会由现行代码重复核验。既有 TRD、result、state 和 conversation 不因本次精简而改写。

## 运行

```bash
uv --directory /Users/zhou/resource/fireworks/ANDRSZAN/pcm-agent-skills/pcm-demo run \
  python run_step.py --step 14 --run-id <run-id>

uv --directory /Users/zhou/resource/fireworks/ANDRSZAN/pcm-agent-skills/pcm-demo run \
  python -m unittest \
  steps.step_14_trd_design.test_step \
  steps.step_14_trd_design.test_cli -v
```
