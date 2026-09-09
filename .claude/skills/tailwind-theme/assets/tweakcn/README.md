# tweakcn 官方主题 registry 快照

本目录保存 tweakcn 官方公开 themes registry 的离线快照，供 `tailwind-theme` 在不联网、不执行远程代码的情况下发现并读取候选主题。

## 来源与版本

- 官方发布源：[`https://tweakcn.com/r/themes/registry.json`](https://tweakcn.com/r/themes/registry.json)
- 官方仓库：[`jnsahaj/tweakcn`](https://github.com/jnsahaj/tweakcn)
- 获取与核验时间：2026-09-09
- 发布响应 `Last-Modified`：2026-09-09 04:15:25 GMT
- 发布响应 ETag：`"65342c530706214c27faac5b599007b2"`
- 下载字节数：290925
- 发布 registry SHA-256：`1b054571c07af03998e16b352c55a3c19a89be9248a96069734a9ed0d8b9c791`
- 主题数量：42

数据直接取自上述官方发布 endpoint。上游仓库在核验时的 `main` HEAD 是 `a3b47b37cba97dd637de517aab52c45ec0f83456`，仓库中的 preset 源数据也包含这 42 个名称；但 `r/themes/registry.json` 是发布生成物，仓库没有提交同路径的聚合 JSON，因此这里不把该发布 payload 强行归属或伪造为某个源码 commit。

旧入口 `https://tweakcn.com/r/registry.json` 当时只有 36 项，是旧子集，不是本快照的数据源，也不能用于判断当前完整主题集合。

`themes/<slug>.json` 是发布 registry 的 `items` 中对应 `registry:style` object 的逐项拆分：保留原有字段、嵌套结构和值，只将 JSON 空白统一为两空格缩进并补末尾换行；未补写 `$schema`，也未删除 `title`、`description`、`css` 或任何 token。`catalog.json` 仅是本地轻量发现索引，其中中文风格特征是本仓库为筛选候选补充的概括，不属于上游主题数据。

## 许可

上游官方仓库根 `LICENSE` 为 **Apache License 2.0**。本目录的 [`LICENSE`](./LICENSE) 是核验时官方仓库 `main` HEAD 中该文件的原文副本；该提交未包含 `NOTICE` 文件。许可文件只说明上游作品的适用许可，不代表主题名称涉及的第三方商标获得额外授权。

## 离线校验

在仓库根目录运行：

```bash
python3 .claude/skills/tailwind-theme/assets/tweakcn/validate.py
```

脚本只使用 Python 标准库并读取本目录文件，不联网、不更新资源。它检查：

- 所有 JSON 可解析，catalog 与主题文件集合一致；
- slug、主题名、文件名和相对路径一致且唯一；
- 每个主题精确为 `registry:style`，并保留已知顶层结构；
- `cssVars.theme`、`cssVars.light`、`cssVars.dark` 完整，light/dark 具备该快照的完整 token 集；
- 已知颜色、字体、长度、透明度、tracking、shadow 和受控顶层 `css` 使用字符串安全类型；
- 值中不含换行、控制字符、声明分隔、外部 URL、data URI、at-rule 或常见可执行 CSS 载荷。

这是针对本快照已知合同的轻量检查，不是通用 CSS parser，也不替代主题应用到具体工程后的浏览器、对比度、字体可用性和 token 消费验证。

## 手工更新方法

不提供也不自动运行更新服务。维护者需要更新时：

1. 直接下载官方 `https://tweakcn.com/r/themes/registry.json`，记录抓取时间、响应 ETag、`Last-Modified`、字节数与 SHA-256；不要退回旧的 `/r/registry.json`；
2. 检查聚合 JSON 顶层结构，确认所有 item 均为 `registry:style`，并记录主题数量、名称和顺序；
3. 查阅官方仓库当前源码，只用于核对主题名称、生成逻辑和许可；不运行仓库脚本、依赖安装、构建或其它远程代码，不为发布生成物伪造 commit；
4. 核实根 `LICENSE`，并检查是否新增 `NOTICE` 或资源专属许可；
5. 将每个发布 item 按 `name` 写为 `themes/<name>.json`，同步轻量 `catalog.json`，更新本 README 的来源元数据、哈希、数量和限制；
6. 运行本目录 `validate.py`，再用 Git diff 确认只改变本资源目录。

## 已知限制

- 本目录是核验日官方发布 themes registry 的完整 42 项快照，不包含数据库中的社区/用户主题。
- 发布 endpoint 是可变资源；本目录通过抓取时间、HTTP 元数据和内容哈希标识这次快照，而不是声称它永久代表最新版。
- 逐主题文件由发布聚合 JSON 拆分，结构和值可逐项验证，但格式空白不是上游逐主题响应的逐字节副本。
- catalog 的中文特征用于初筛，不应被当作稳定 schema、完整 token、许可结论或采用依据；使用主题时必须直接读取并独立校验对应完整 JSON。
