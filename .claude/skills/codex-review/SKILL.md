---
name: codex-review
description: Use when 需要使用可用的 Codex 环境，对代码变更、分支差异、活动 TRD 或指定技术问题进行独立只读审查时；只返回真实审查发现，不修改内容，也不替 Leader 作最终判断。
argument-hint: <仓库路径、审查对象、目标或关注点，可选 scope/base>
---

# codex-review — Codex 独立审查

## 能力定位

通过本机 Codex CLI 和已启用的 `codex@openai-codex` companion，对指定 Git 仓库中的代码、文档或分支差异进行一次独立、只读的审查。

本能力只负责取得并返回真实 Codex 审查发现。它不替代 Leader 自审、测试和真实验收，也不把 Codex 意见自动转化为修改或最终裁决。

## 适用场景

可以在以下场景独立调用：

- 审查 working tree 中与当前目标相关的代码或文档变更；
- 审查当前分支相对于指定 `base` 的差异；
- 审查活动 TRD 的完整性、可实现性和风险；
- 针对正确性、回归、权限、安全、数据、兼容性或验证缺口进行对抗式检查。

是否调用 Codex、是否增加其他审查者，由调用方根据风险决定。Codex 不可用不等于审查通过，也不自动阻塞普通开发。

## 审查输入

调用时尽量从参数、当前对话、活动 TRD 和 Git 状态中确定：

- `repo`：目标 Git 仓库路径，所有命令必须在该仓库语境下执行；
- `target`：要审查的变更、分支差异、活动 TRD、文件或技术问题；
- `goal`：这些内容预期达到的功能或设计结果；
- `mode`：`review` 或 `adversarial`；未指定时默认 `review`；
- `scope`：`working-tree`、`branch` 或 `auto`；未提供 `base` 和 `scope` 时默认 `working-tree`；
- `base`：可选 Git ref；提供时明确审查当前分支相对于该基准的差异，并优先于 `scope`；
- `focus`：可选重点，仅用于 `adversarial`；
- `output_file`：可选；只有明确要求保留原始输出时才落盘。

不要求调用方机械填写每个字段。能够从现有上下文可靠判断时直接继续；目标、范围或比较基准存在实质歧义时再请求补充。

## 确定审查范围

开始前先检查仓库状态和差异范围，确认本次 Codex 实际会看到什么。Codex companion 只能审查命令实际运行所在 repository/check-out 可见的内容；`working-tree` 只有在传入的 `repo` 是包含待审版本的权威工作区时，才代表其中的未提交改动。隔离 checkout 的已检出提交不能替代其他工作区中的未提交实现。

`target` 和 `goal` 用于解释审查目的，不代表 companion 一定支持按路径过滤。未提供 `base` 和 `scope` 时，显式使用 `--scope working-tree`，避免干净工作树被 companion 的 `auto` 行为自动切换为分支差异。只有调用方明确要求自动选择时才使用 `auto`；明确审查当前分支时使用 `branch`，或直接提供 `base`。

working tree 中混有多个无关目标时，不能把它们当成一个功能结论，也不能假装 companion 只审查了其中一部分。多个相关 Git 仓库共同组成工作区且含未提交改动时，调用方必须分别提供各仓库的权威路径、完整 staged/unstaged diff 与未跟踪文件范围；`auto` 范围不能替代这些证据。

范围混杂时，优先使用调用方提供的 `base`、独立工作区或明确的审查环境缩小范围；无法可靠隔离时，清楚说明实际覆盖范围，并将发现按目标和文件区分。若隔离环境、权限或路径限制使权威工作区的真实 diff 不可见，必须在结果中记录盲区，不能把当前基线的“无发现”当作对未提交实现的审查结论。只有范围会实质影响结论且无法自主判断时才请求调用方确认。

## 执行审查

1. 确认 `repo` 是有效 Git 仓库：
   ```bash
   git -C <repo> rev-parse --show-toplevel
   ```
2. 确认 Node.js、Codex CLI、Codex 认证状态和 companion 脚本可用。优先从 `CLAUDE_PLUGIN_ROOT` 解析；变量不存在或目标文件不存在时，只在当前环境已启用的插件位置中查找。将最终确认存在的 `scripts/codex-companion.mjs` 绝对路径记为 `<companion>`，不要硬编码本机缓存版本。
3. 根据真实目标选择且显式传递范围，在 `repo` 下前台等待结果：
   ```bash
   # 默认：审查 working tree
   node "<companion>" review --wait --scope working-tree

   # 审查相对于明确基准的分支差异
   node "<companion>" review --wait --base <base>

   # 明确要求 companion 自动选择，或审查相对默认分支的分支差异
   node "<companion>" review --wait --scope auto
   node "<companion>" review --wait --scope branch

   # mode=adversarial 使用同样的 --scope 或 --base 规则
   node "<companion>" adversarial-review --wait --scope working-tree <focus...>
   ```
4. 记录 companion 实际返回的范围。`REVIEW_SCOPE` 必须来自实际执行参数和结果，不能根据工作树状态自行假设。
5. 只有显式提供 `output_file` 时才保存 Codex 原始 stdout；普通调用不创建审查报告、失败报告或过程文件。
6. 忠实返回有证据的发现。原文过长时可以简明整理，但不得改变原意、补造发现或把推测写成事实。

## 运行条件与降级

执行状态只描述 Codex 是否成功运行：

- `completed`：Codex 已真实执行并返回有效结果；
- `degraded`：已经尝试调用，但非零退出、超时、远程错误或输出不可用；
- `unavailable`：当前缺少运行时、CLI、认证、插件脚本或有效 Git 仓库，未真正执行审查。

`completed` **不代表审查通过、变更正确或功能完成**。`degraded` 和 `unavailable` 也不能写成“未发现问题”。

环境不满足时说明缺少条件即可。本能力不擅自全局安装软件、修改用户 settings、执行登录或开通服务；实际调用暴露的额度或远程服务问题归为 `degraded`。

## Leader 如何处理审查发现

Codex 发现是独立建议，不是必须采纳的命令。Leader 必须结合需求、活动 TRD、当前代码、测试和真实运行证据逐项判断：

- 合理且属于当前结果的问题，修复或调整后重新验证；
- 指向活动设计错误的建议，可以直接同步活动 TRD 后继续；
- 缺乏证据、理解错误、偏离目标或收益不合理的建议，可以说明理由后拒绝；
- 高风险但无法确认的问题，应增加验证或请求必要决策。

Codex 没有报告发现，只表示本次审查没有返回可报告问题，不替代 Leader 自审、测试、服务运行和浏览器验收。

## 完成输出

默认直接返回简洁、稳定的结果，不落盘：

```text
REVIEW_EXECUTION: completed | degraded | unavailable
REVIEW_MODE: review | adversarial
REVIEW_REPO: <repo>
REVIEW_SCOPE: <base、working tree 或实际覆盖范围>
OUTPUT_FILE: <显式要求时填写，否则 none>
SUMMARY: <执行情况和重要结论>
FINDINGS:
- [严重程度] <位置>：<问题、证据和可能影响>
- none
```

`FINDINGS: none` 只能在成功取得真实审查结果且确实没有可报告发现时使用；执行失败时应写明未取得有效审查结果。

## 安全边界

- 只读：不修改代码或 TRD，不 patch、不 stage、不 commit；
- 不裁决：不输出通过、批准或最终交付结论；
- 不伪造：没有真实 Codex 输出时不得编造结果；
- 不泄密：输出和可选落盘内容不得主动扩散开发 `.env`、凭据、token、私钥或其他秘密；
- 不用 `/codex:rescue`、Stop review-gate 或其他机制代替开发执行。

## 不负责的内容

本能力不修复发现、不运行完整测试、不启动服务、不操作浏览器、不判断需求是否完成，也不创建 Git 提交。这些工作由调用方或相应独立能力负责。
