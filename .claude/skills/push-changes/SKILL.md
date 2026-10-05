---
name: push-changes
description: 显式推送指定 Git 仓库的已有提交，核对目标分支、实际远程地址及逐仓结果；不自动提交或改写历史。
argument-hint: <仓库路径列表，可选分支与 remote>
disable-model-invocation: true
allowed-tools: Read, Bash(python3 *)
---

# 安全推送已有提交

仅在用户显式调用时执行。根据调用参数确定仓库路径列表，默认分支 `main`、remote `origin`；功能分支必须明确指定。不递归扫描目录推断仓库，也不把父仓内的普通子目录当成独立仓库。范围无法确认时，先询问需要推送的仓库。

## 执行

使用本能力目录中的 `scripts/push.py`，不要另写推送命令。脚本只依赖 Python 标准库与 Git，可随目录复制使用。

```bash
python3 <本能力目录>/scripts/push.py \
  --repo /absolute/path/to/backend \
  --repo /absolute/path/to/product \
  --branch main --remote origin
```

`--repo` 可重复，按传入顺序推送。产品包含独立代码仓与根仓时，代码仓先、根仓最后。调用方负责避免其它程序并发修改这些仓库。

执行前确认用户要求的是同步已提交成果；若已知待推送历史含真实外部秘密，停止并说明问题，不清理或改写历史来绕过。被忽略配置、未提交文件及外部数据不属于 Git 同步结果，不能把成功推送称为完整环境备份。

脚本整批预检通过后才开始写入：每个路径须为仓库自身、处于目标分支且有提交、工作树与 index 干净，没有进行中的历史操作。它检查包含 URL rewrite 的唯一实际 push 地址，拒绝镜像配置、内嵌凭据及绑定冲突。明确指定源 SHA 与目标分支，不跟随标签、不递归推送子模块、不依赖默认 push refspec，不设置 upstream。

不暂存、提交、切换分支、合并、变基、修改 remote、建远程项目或强推。不绕过 Git hook、分支保护或 SSH 主机校验。连接非交互且有有限超时；缺少身份、主机信任或权限时保留现场并报告。

## 程序调用

`scripts/push.py` 导出：

```python
push_repositories(repositories: list[dict], *, branch='main', remote='origin', on_update=None) -> list[dict]
```

每个输入包含字符串 `name`、`path`，可选 `expected_url`、`target_sha`。预期地址必须与实际 push URL 完全一致；目标 SHA 必须是当前目标分支的完整提交 SHA，省略时从现场取得。恢复应继续传入已保存的目标 SHA，不能悄悄纳入新提交。

结果逐仓包含 `name`、`path`、`url`、`branch`、`target_sha`、`remote_sha`、`status`，失败项另有 `error`。即使批量预检中途失败，也保留与输入等长的整批结果，尚未执行项保留调用方提供的目标 SHA；尚未取得的地址或 SHA 为空字符串。`on_update(results)` 在逐仓预检信息、远程事实或执行状态更新时接收结果副本，可用于及时保存；保存失败即停止后续操作。

失败抛出 `PushError(RuntimeError)`，携带 `results` 与 `blocked`；仅明确 SSH 身份或权限不可用时 `blocked` 为真。CLI 输出 JSON 逐仓报告，失败返回非零退出码；原始 Git/hook 输出不转发，避免暴露秘密。

## 结果与恢复

向用户说明各仓地址、分支、目标提交与结果：

- `pushed`：已推送，远程 SHA 与目标一致，本地目标复核未漂移。
- `unchanged`：远程已一致，无需写入。
- `failed`：检查或推送失败，说明具体问题与解除条件。
- `pending`：尚未执行推送；不当作成功。

某仓失败后停止，已成功仓库不回滚；三仓同步不是原子事务。dirty 时明确说明存在未提交内容。远程领先、分叉或本地没有远程提交对象时停止，不隐式 fetch、拉取或合并；为避免旧版 Git 在对象检查时隐式联网，带 partial clone 配置的仓库也会停止。

修复已报告条件后可用同一仓库列表、分支与 remote 重试；程序调用恢复还应传入原目标 SHA。重试先读取远程事实，已经一致的仓库跳过写入；网络响应丢失不等于推送必然失败。只有全部仓库 `pushed` 或 `unchanged` 才报告整体同步成功。
