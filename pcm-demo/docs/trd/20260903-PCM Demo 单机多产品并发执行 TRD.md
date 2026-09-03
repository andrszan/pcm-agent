# PCM Demo 单机多产品并发执行技术设计

> 设计日期：2026-09-03
> 状态：已实现，待真实双产品 Agent 集成验证
> 适用范围：当前 `pcm-demo` 单机、本地文件系统、单个 Demo checkout 运行模型
>
> 实现结果：已新增 `common/coordination.py`，完成 Capacity Slot、Run Lock、Product Lock、父子 FD 传递、Product Registry、配对端口、产品状态与人工 release；第 1 步建立 claim 和 `.pcm/runtime.json`，第 2 步串行化 Claude trust 写入，第 6 步向 `project-bootstrap` 交接本机 endpoint。当前全量 381 项 `unittest`、完整 `compileall`、修改 Python 文件 IDE diagnostics 和 `git diff --check` 通过；尚未调用真实双产品 Claude Agent 同时完成前后端启动。

## 一、实现摘要

当前 `run_all.py` 通过 `pcm-demo/runs/.run_all.lock` 在整个编排期间持有一把全局排他锁，因此不同产品也只能串行执行；直接运行 `run_step.py` 又不参与这套锁协议，不能真正保证同一产品或同一 run 只有一个写入者。

本需求将当前“全局单实例”调整为“有限容量内的多产品并发”：

- 不同产品可以并发执行；
- 同一产品在任意时刻只能有一个活动执行者；
- 同一 run 在任意时刻只能由一个进程执行或恢复；
- 宿主机通过可配置的执行名额限制同时运行的 PCM 项目数量；
- 产品创建时从可读的前后端配对端口范围分配一个稳定 slot；
- 产品因成功、失败、阻塞、取消或异常中断而停止时，执行锁自动释放，但产品端口继续保留；
- 只有人明确释放产品后，端口 slot 才可被其他产品复用；
- Claude Agent 仍可按真实技术栈决定具体接线和启动方式，但必须使用当前产品已分配的 endpoint，不能静默漂移或处理未知进程；
- 外部开发资源继续由 `project-readiness` 和动态资源清单管理，不为本需求建立通用资源 DSL 或逐类 Python verifier。

本设计新增的核心概念只有四类：

1. **Capacity Slot**：限制宿主机同时执行的 PCM 项目数量；
2. **Run Lock**：保护一个 run 的状态、步骤结果和 conversation；
3. **Product Lock**：保护一个产品工作区、Git 和本地运行行为；
4. **Product Registry**：长期保存产品归属、生命周期和端口租约。

锁是进程级临时互斥；Product Registry 中的产品记录和端口租约是跨进程、跨中断的长期事实，两者不得混为一谈。

## 二、需求定位

### 2.1 使用方与核心任务

主要使用方是运行 PCM Demo 的本机操作人员。其核心任务是：

1. 在宿主机容量允许时，同时启动多个不同产品的完整开发流程；
2. 在同一产品或同一 run 已经执行时获得明确拒绝，而不是产生并发写入；
3. 在进程意外中断后，以原 run 恢复原产品并继续使用原端口；
4. 查看产品当前归属、端口和锁状态；
5. 在确认产品不再需要继续开发后，人工释放其端口租约。

### 2.2 完成结果

本需求完成后，应能判定以下结果：

- 两个不同产品可以同时运行 `run_all.py`，且各自状态、Agent、Git、端口和浏览器目标不互相覆盖；
- 超过配置的宿主机并发执行名额时，新执行立即停止并说明容量已满；
- 同一产品的第二个 run、同一 run 的第二个恢复和绕过 `run_all.py` 的直接 `run_step.py` 均不能并发写入；
- 中断后锁由操作系统释放，产品记录和端口不释放；
- `--resume` 能重新取得原产品锁并复用原端口；
- Agent 实际启动和验收使用登记 endpoint；
- 产品端口只能通过明确的人工释放操作进入可复用状态。

### 2.3 非目标

本需求不建设：

- 同一产品内部的多需求并行开发；
- Git worktree 并行需求开发；
- 多机或多个 Demo checkout 共同操作同一产品的分布式协调；
- Redis、etcd、数据库 lease、fencing token 或正式调度平台；
- 后台等待队列、优先级、公平调度或自动唤醒；
- 容器编排或通用进程管理平台；
- 通用外部资源类型、资源 DSL、资源锁或逐 Provider verifier；
- 自动判断产品已经永久交付；
- 自动回收长期未使用的端口；
- 自动接管、转移或重新激活已经人工释放的产品；
- 自动终止未知进程或自动迁移产品端口；
- 因可能出现模型网关限流而增加额外全局串行化。

## 三、历史基础与当前项目分析

### 3.1 当前全局锁

当前 `run_all.py`：

- 将锁固定为 `pcm-demo/runs/.run_all.lock`；
- 使用 `fcntl.flock(..., LOCK_EX | LOCK_NB)` 非阻塞获取；
- 在进入 `orchestrate()` 前获取，并在整个完整编排退出后关闭；
- 任何第二个 `run_all.py` 都会收到“已有 PCM 完整编排正在运行”。

该机制能防止两个 `run_all.py` 同时执行，却把所有产品错误地串行化。

### 3.2 `run_step.py` 不受当前锁保护

`run_step.py` 可独立执行第 0～18 步，但当前没有获取全局锁或其他并发锁。因此当前全局锁只是 `run_all.py` 的入口约束，不能阻止：

- `run_all.py` 与手动 `run_step.py` 同时写同一个 run；
- 两个 `run_step.py` 同时写同一个 run；
- 两个不同 run 同时操作同一个产品目录；
- 同一产品的 Git 分支、工作树、配置和 Agent session 被交错操作。

### 3.3 原子 JSON 写入不是并发控制

`common/files.py` 当前通过同目录临时文件和 `replace()` 写入 JSON。这能避免进程中断后留下半个 JSON，但不能阻止两个进程：

```text
同时读取旧 state
→ 分别形成更新
→ 先后 replace
→ 后写者覆盖先写者
```

因此现有原子写入继续保留用于崩溃一致性，但必须由 Run Lock 和 Product Lock 保证单写入者。

### 3.4 产品身份和工作区发布

当前第 1 步先从产品初稿取得 `project_directory_name`，再计算：

```text
final_path   = workspace_root / project_directory_name
staging_path = workspace_root / <project_directory_name>.pcm-tmp-<run-id>
```

已有 staging marker、内容核验和原子 rename 能保护单 run 的发布恢复，但不能替代产品并发认领。两个 run 仍可能为同一个 `final_path` 分别完成模型调用、clone 和 staging 准备，再在发布阶段才发生冲突。

### 3.5 当前父子进程

`run_all.py` 使用子进程逐步调用 `run_step.py`，并通过 `start_new_session=True` 建立子进程组、转发 `SIGINT` 和 `SIGTERM`。完整编排和单步入口最终必须复用相同步骤函数，但当前仍是父进程持锁、子进程实际执行的结构。

并发改造必须同时覆盖父进程和直接单步入口，不能只替换 `run_all.py` 的锁文件。

### 3.6 Claude 用户级配置

Claude Agent SDK 当前显式使用默认用户级 Claude 配置；第 2 步会对 `~/.claude.json` 中的项目 trust 执行 read-modify-write。不同产品同时进入第 2 步时可能发生丢失更新，因此该单一共享文件需要一个短时配置锁，但 Claude Agent 的完整执行不应被该锁串行化。

### 3.7 当前端口与服务事实

第 6 步、需求开发第 15 步以及未来阶段二会真实启动前端、后端和浏览器。当前文档记录过 Vite、Uvicorn、健康检查和临时服务停止事实，但尚无统一的：

- 产品端口分配；
- 端口长期租约；
- endpoint 交接；
- Agent 使用端口的不变量；
- 并发容量限制；
- 产品人工释放操作。

## 四、产品行为与操作体验

本需求不增加 Web 界面，用户可见行为均通过 CLI 和清楚的本地记录完成。

### 4.1 启动不同产品

当宿主机仍有 Capacity Slot，且目标产品没有其他活动执行者时，命令正常运行：

```bash
python run_all.py --product-draft <draft-a> --run-id <run-a>
python run_all.py --product-draft <draft-b> --run-id <run-b>
```

两者可以同时推进，不互相等待。

### 4.2 宿主机容量已满

当所有 Capacity Slot 均被活动进程持有时，新命令立即退出，不在后台排队。错误信息至少说明：

- 配置的最大并发数；
- 当前没有可用执行名额；
- 原命令可在名额释放后重试。

可安全取得时，可以附带当前 slot 的诊断 owner；诊断信息不能成为锁权威。

### 4.3 同一产品冲突

同一 canonical `final_path` 已有活动执行者时，第二个执行立即退出。信息至少说明：

- 产品路径；
- 当前 owner run；
- 当前锁确实被持有，或产品已由其他 run 长期认领；
- 应恢复哪个 run，或先由人检查现有执行。

不得等待到 clone、Git 或 Agent 操作后才发现冲突。

### 4.4 同一 run 冲突

同一 `run_id` 已有执行者时，第二个 fresh、resume 或直接单步调用立即退出。不得让两个进程分别根据同一份旧 state 继续。

### 4.5 中断与恢复

进程因 success、failed、blocked、取消、异常或机器重启结束后：

- 操作系统文件锁释放；
- Product Registry 中的产品记录保持 `active`；
- 产品端口 slot 保留；
- run 状态和已有工作区现场保留；
- 操作人员使用原 `run_id` 恢复。

恢复时先重新取得 Run Lock 和 Capacity Slot；已经形成产品 claim 的 run 再取得 Product Lock，然后重新读取和执行当前节点。尚未形成 claim 的早期 run 只持有 Run Lock 和 Capacity Slot，继续完成产品身份提取与认领。

### 4.6 查看产品状态

应提供一个最小只读操作，按产品路径展示：

- canonical 产品路径；
- product key；
- owner run；
- lifecycle；
- frontend/backend 端口；
- Product Lock 当前是否被持有；
- 若可安全取得，锁文件中的诊断 PID 和开始时间；
- owner run 的 state 路径及当前状态是否可读。

具体是扩展 `run_all.py` 子命令还是建立一个很小的管理入口，可在稳定边界内部决定；不得要求人直接读取或编辑注册表 JSON。

### 4.7 人工释放产品

应提供明确的人工释放操作。释放只表示：

> 操作人员确认该产品不再需要在当前 PCM 宿主机继续开发，其端口可以分配给其他产品。

释放操作必须：

1. 解析并核验 canonical 产品路径；
2. 从 Product Registry 快照找到唯一 active Product Record 及其 owner run；
3. 按正常执行相同顺序，非阻塞取得该 owner 的 Run Lock，再取得 Product Lock；任一锁仍被持有都拒绝释放；
4. 取得 Registry Lock 后重新读取并核验 product path、owner、lifecycle 和端口与快照一致；
5. 检查已分配端口没有活动监听者；存在监听者时拒绝，不自动终止；
6. 将 lifecycle 改为 `released` 并记录释放时间；
7. 使端口 slot 可被新产品分配；
8. 不删除产品代码、run 历史或诊断记录。

首次 Registry 快照只用于定位锁；最终释放决定必须在三把锁均按上述顺序持有后重新核验。这样即使第 1 步刚完成认领、Product Lock 尚处于父子交接窗口，只要 owner run 仍在执行，release 也会被 Run Lock 拒绝。

释放后若产品需要返工，当前需求不承诺恢复原端口；后续重新激活或转移 owner 属于新的显式生命周期设计。仍可能返工的产品不应被释放。

## 五、总体技术设计

### 5.1 单机协调根

当前范围使用一个 Demo checkout 下的本机协调根：

```text
pcm-demo/runs/.coordination/
├── registry.lock
├── products.json
└── locks/
    ├── capacity/
    │   ├── 0.lock
    │   └── 1.lock
    ├── runs/
    │   └── <run-id>.lock
    └── products/
        └── <product-key>.lock
```

选择该位置的原因：

- 与当前 `runs/.run_all.lock` 的本机作用域一致；
- 不依赖尚未创建的产品目录；
- 不污染产品 Git 仓库；
- 不同 `workspace_root` 的产品仍共享同一宿主机端口和并发容量；
- 可继续使用本地 `flock`，无需新增基础设施。

`.coordination/` 是当前 Demo checkout 的持久本机协调数据，不随某个 run 结束清理。跨 checkout、跨机器或不可靠网络文件系统不属于本需求承诺。

### 5.2 Product Key

当前产品互斥身份使用最终产品路径，而不是 run ID 或单独的目录名：

```text
canonical_path = final_path.expanduser().resolve(strict=False)
product_key = sha256("pcm-product-v1\0" + canonical_path)
```

要求：

- `final_path` 必须来自已验证的 `workspace_root` 和合法单段 `project_directory_name`；
- canonical path 必须仍位于该 `workspace_root` 的直接子级；
- 锁文件只使用 hash，不把任意绝对路径直接拼入文件名；
- Product Registry 同时保存 hash 和原始 canonical path，用于碰撞与漂移核验；
- 同名产品位于不同 workspace root 时具有不同 product key；
- 同一路径无论由哪个 run 请求，都命中同一 Product Lock 和 Product Record。

未来正式 PCM 可以引入不可变 `product_id`；当前 Demo 不为此提前建立产品 ID 服务。

### 5.3 Capacity Slot

新增配置：

```text
PCM_MAX_CONCURRENT_PROJECTS=2
```

语义：当前 Demo checkout 在宿主机上可同时运行的 PCM 执行数量。值必须为正整数，默认建议为 `2`；操作人员可以根据 CPU、内存和 Claude Agent 实际资源占用调整。

实现使用编号锁文件，而不是共享计数器：

```text
capacity/0.lock
...
capacity/<max-1>.lock
```

执行入口依次非阻塞尝试取得任意一个 slot。取得后在锁文件写入仅供诊断的 `run_id`、PID、命令类型和开始时间，持有文件描述符直到本次执行退出。

Capacity Slot：

- 限制同时执行数，不限制未释放产品总数；
- 进程退出后自动释放；
- 不因产品生命周期仍为 active 而长期占用；
- 不提供首版排队或等待。

### 5.4 Run Lock

Run Lock 路径：

```text
runs/.coordination/locks/runs/<run-id>.lock
```

它保护：

- `runs/<run-id>/state.json`；
- 当前 run 的步骤结果；
- conversation、session 引用和诊断；
- fresh 创建与 `--resume` 的互斥。

由于 fresh run 在创建 `runs/<run-id>/` 前也需要互斥，Run Lock 不放在 run 目录内部。

新 run 必须满足 state 中的 run 身份与目录身份一致。已有历史 run 若已知存在目录名与 `state.run_id` 不一致，不直接改写历史字段；首次进入新协调协议时，以受 CLI 路径校验的 run 目录名作为执行身份，在 state 增加新的协调引用并保留旧字段。该兼容只用于已有历史现场，新创建的 run 不允许产生不一致。

### 5.5 Product Lock

Product Lock 路径：

```text
runs/.coordination/locks/products/<product-key>.lock
```

它保护：

- 产品根、frontend、backend 及其它适用仓库；
- 产品文档、代码、配置和 Git；
- 同一产品的 Agent 调用与本地服务操作；
- 对 Product Record 的当前执行身份核验。

Product Lock 是当前活动执行互斥，不代表产品生命周期。进程退出后可以释放，而 Product Record 和端口继续保留。

### 5.6 Product Registry

为减少多文件事务和恢复分叉，产品归属与端口分配使用一份受短时 Registry Lock 保护的注册表，而不是分别维护 Product Record 和 Port Registry：

```text
runs/.coordination/products.json
```

示意结构：

```json
{
  "schema_version": 1,
  "products": {
    "<product-key>": {
      "product_path": "/products/mendmark",
      "owner_run_id": "20260903T081200Z-a1b2c3",
      "lifecycle": "active",
      "port_slot": 137,
      "ports": {
        "frontend": 3137,
        "backend": 8137
      },
      "created_at": "2026-09-03T08:12:00Z",
      "released_at": null
    }
  }
}
```

注册表约束：

- `product_path` 必须与 product key 重新计算结果一致；
- 同一 active 产品路径只能有一条记录；
- 同一 active `port_slot` 只能分配给一个产品；
- `owner_run_id` 是应当恢复的 run，不是实时锁；
- `lifecycle` 首版只需要 `active` 与 `released`；
- `released` 记录保留用于诊断，但不再占用 slot；
- 注册表只保存本机非秘密协调事实；
- 更新继续使用同目录临时文件与原子 replace；
- 所有 read-modify-write 都必须持有 `registry.lock`；
- 普通流程不直接编辑或删除该文件。

### 5.7 产品本地运行配置

产品发布时建立 Git 忽略的本机运行配置：

```text
<product-root>/.pcm/runtime.json
```

示意内容：

```json
{
  "schema_version": 1,
  "product_key": "<product-key>",
  "owner_run_id": "<run-id>",
  "host": "127.0.0.1",
  "services": {
    "frontend": {
      "port": 3137,
      "url": "http://127.0.0.1:3137"
    },
    "backend": {
      "port": 8137,
      "url": "http://127.0.0.1:8137"
    }
  }
}
```

该文件：

- 是 Agent 可直接读取的稳定本机运行事实；
- 不包含数据库、对象存储、SMTP、API Key 或其它秘密；
- 必须被产品根 Git 忽略；
- 现有且内容与 Product Registry 或 state 不一致时停止，不静默覆盖；在已记录的同一 owner `claim_pending` 或 `claimed` 恢复阶段中，缺失文件可以从已锁定并核验的 Product Registry 幂等补齐；
- 由 PCM 确定性创建和核验，Agent 不自行分配或修改端口；
- 具体项目如何把它映射到 frontend/backend `.env`，由 `project-bootstrap` 按真实工程决定。

## 六、锁获取、父子进程与执行顺序

### 6.1 固定锁顺序

为避免不同入口形成锁顺序反转，活动执行统一采用：

```text
Run Lock
→ Capacity Slot
→ Product Lock（产品身份已知后）
```

Registry Lock 和 Claude 用户配置锁都是短锁，只包围自己的单文件 read-modify-write，不在其内部调用模型、clone、Git、测试、服务或浏览器。

### 6.2 Fresh `run_all.py`

```text
生成或接收 run_id
→ 取得 Run Lock
→ 取得 Capacity Slot
→ 执行第 0 步
→ 第 1 步提取项目目录名并解析 canonical final_path
→ 先把 claim intent（execution run、canonical path、product key）写入 state
→ 第 1 步取得 Product Lock
→ 在 Registry Lock 下创建或核验同一 owner 的 Product Record，并分配端口 slot
→ 将 slot 写入 state，创建或补齐本机 runtime 配置
→ 写 workspace intent、准备并发布产品
→ 第 1 步结束后，父编排器从 state 取得同一 Product Lock
→ 后续完整流程由父编排器持续持有并传给步骤子进程
→ 结束时关闭锁 FD；Product Registry 不变
```

Product Lock 必须先于 Product Registry 的创建或 owner 确认取得，避免产品刚登记但尚未受实时互斥保护。两个 fresh run 得到同一 final path 时，只有一个能在 Product Lock 和 Registry Lock 下认领；另一个在 clone 和发布前拒绝。

第 1 步子进程退出到父编排器取得 Product Lock 之间可能存在极短交接窗口。该窗口由仍被父编排器持有的 owner Run Lock 和已提交的 Product Record 保护：其他 run 会因 owner 不一致被拒绝，人工 release 也必须先取得 owner Run Lock，因此不能在窗口中释放产品。

### 6.3 Resume `run_all.py`

恢复必须区分两种状态。

**尚未形成 claim 的早期 run：**

```text
取得 Run Lock
→ 取得 Capacity Slot
→ 读取并核验 state
→ 恢复第 0 步或第 1 步身份提取
→ identity 与 canonical final path 确定后按 fresh claim 流程继续
```

此时 state 可能尚无 `workspace`、`coordination` 或 Product Record，不能要求 Product Lock。

**已经写入 claim intent 或已完成 claim 的 run：**

```text
取得 Run Lock
→ 取得 Capacity Slot
→ 读取并核验 state 中的 execution run、canonical path 和 product key
→ 取得 Product Lock
→ 在 Registry Lock 下核验或补齐同一 owner 的 Product Record
→ 重新读取 state，防止锁前状态漂移
→ 补齐允许恢复的 coordination/runtime 阶段
→ 恢复当前节点
```

当产品记录属于其他 run 时不得自动接管。

### 6.4 父子锁传递

`run_all.py` 持有的 Run Lock、Capacity Slot 和已知后的 Product Lock，必须通过 `subprocess.Popen(..., pass_fds=...)` 或等价的受控文件描述符继承传给 `run_step.py`。环境变量或内部 CLI 参数只携带 FD 编号、run、product key 和预期锁路径等核验信息，不能替代真正的锁 FD。

子进程启动后必须：

1. 核验继承 FD 对应预期 Run Lock、Capacity Slot 和适用的 Product Lock；
2. 核验锁上下文与当前 `run_id`、product key 和 state 一致；
3. 不重新获取父进程已经持有的同一排他锁；
4. 在调用 Claude Agent SDK 或启动项目命令前，将协调 FD 标记为不可继续继承，使 SDK、Shell 和业务服务不会因偶然继承而长期占住执行名额或产品锁；
5. 保持 `run_step.py` 自身持有这些 FD，直到当前步骤结束。

这样可以避免父进程持锁、子进程重新取锁造成自锁，也能在父进程异常退出但当前步骤子进程仍运行时继续保持互斥。`run_step.py` 正常结束后，遗留业务服务不持有协调锁；它们通过登记端口和项目归属规则被识别，而不是通过继承锁表示生命周期。

锁文件中的 owner metadata 只用于诊断；文件描述符上的 `flock` 才是实时互斥权威。

当前 Claude Agent SDK 内部子进程继续由 SDK 管理。本需求不为 SDK 建立自定义 daemon；如果 `run_step.py` 被强制终止而 SDK 子进程异常遗留，协调 FD 会释放。后续恢复必须先核验 Agent session、产品 Git/工作树和登记 endpoint；无法证明归属的现场作为冲突，不自动终止或覆盖。该边界是当前不建设进程监管器前提下接受的单机 Demo 风险。

### 6.5 独立 `run_step.py`

没有继承锁上下文时，`run_step.py` 必须自行：

1. 取得 Run Lock；
2. 取得 Capacity Slot；
3. 对已有 claim 的步骤，从 state 重建 product key 并取得 Product Lock；
4. 对尚未 claim 的第 0 步或早期第 1 步，先继续到 identity 和 canonical path 确定；
5. 写入 claim intent、取得 Product Lock，再在 Registry Lock 下认领和分配端口；
6. 执行单个步骤；
7. 退出时释放实时锁，不释放端口租约。

因此定向开发和恢复入口不能绕过并发协议。

## 七、端口租约设计

### 7.1 可读配对范围

当前 Demo 使用同后三位配对：

```text
slot:     100–999
frontend: 3000 + slot  → 3100–3999
backend:  8000 + slot  → 8100–8999
```

例如：

```text
slot 137
frontend 3137
backend  8137
```

该设计：

- 避开常见默认端口 3000、3001、8000、8001；
- 一眼可区分前后端；
- 同一产品前后端后三位一致；
- 可保留 900 个尚未人工释放的产品；
- 注册表只需要一个 slot 即可核验端口关系。

当前为每个产品保留完整前后端端口对，即使后续选型只有 frontend、只有 backend 或均无业务服务。端口未监听时没有 CPU 和内存成本；用少量端口空间换取从产品创建开始稳定、简单的生命周期，不在第 4 步后再引入服务类型分配分支。

### 7.2 首次分配

第 1 步认领新产品时，在 Registry Lock 内：

1. 收集所有 lifecycle 为 `active` 的 slot；
2. 从小到大寻找未登记 slot；
3. 对 frontend 和 backend 两个端口分别尝试本地 bind；
4. 任一端口当前被宿主机其他程序占用时跳过该 slot；
5. 找到可用配对后，将产品记录和 slot 在一次注册表原子写入中保存；
6. 没有可用 slot 时明确失败，不覆盖或复用 active 产品的 slot。

bind 探测与真实服务启动之间仍存在宿主机外部进程抢占窗口。当前不同 PCM 产品不会重复分配，但不建设跨任意本机程序的 socket reservation。真实启动时必须再次验证。

### 7.3 长期保留与恢复

以下行为均不释放 slot：

- 某个步骤成功；
- 阶段一完成；
- 未来阶段二完成；
- `run_all.py` 正常退出；
- `blocked` 或 `failed`；
- `SIGINT`、`SIGTERM`、`SIGKILL`；
- Python 或 Claude Agent SDK 异常；
- 宿主机重启；
- 一段时间没有活动进程。

恢复和后续步骤严格复用原 slot，不重新选择。

### 7.4 启动时冲突

在启动服务前，Agent 和步骤验收应遵循：

- 使用 `.pcm/runtime.json` 和项目实际本地配置中的登记端口；
- 禁止开发服务器在端口占用后自动选择下一个端口；
- 分配端口被未知监听者占用时返回 `failed`；
- 不静默更新 Product Registry；
- 不自动终止未知进程；
- 不通过访问另一个端口上的成功健康检查替代当前 endpoint。

本需求不固定所有技术栈的启动参数。对 Vite 等支持 strict port 的工程应使用相应能力；其他技术栈采用其等价失败行为。

## 八、Claude Agent 端口约束与自由边界

### 8.1 根 `AGENTS.md` 的稳定规则

产品模板根 `AGENTS.md` 增加简短的本地运行资源规则，表达以下不变量：

1. 启动和验收本地前后端时，读取 PCM 提供的产品本机运行配置；
2. 使用当前产品已分配的 host、port 和 endpoint；
3. 不自行递增、随机选择或静默切换端口；
4. 不依赖框架自动寻找替代端口；
5. 已分配端口被未知进程占用时报告冲突，不终止未知进程；
6. frontend API URL、backend CORS、健康检查和浏览器访问使用同一组 endpoint；
7. 只停止由当前执行明确启动且归属可确认的临时服务。

规则只约束结果，不规定具体框架、命令、目录或配置实现。

### 8.2 Agent 上下文

第 6 步 `project-bootstrap` 的初始上下文增加 `.pcm/runtime.json` 路径和当前 endpoint 事实，使 Agent 能按真实工程完成：

- 开发服务器端口接线；
- frontend API base URL；
- backend CORS；
- health URL；
- Playwright base URL；
- 实际 `.env` 和无秘密 `.env.example` 同步。

第 15 步和未来阶段二不需要重复注入完整端口说明；Agent 按项目规则和本机运行配置读取当前事实。确有完成缺口时，负责人只给出针对登记 endpoint 的简短修复指令。

Agent prompt 的首行 slash command 和其余领域边界继续遵守现有项目规则，不写外层步骤、节点、session 或编排背景。

### 8.3 保留给 Agent 的自由

本需求不固定：

- frontend/backend 最终环境变量名称；
- Vite、Next.js、Uvicorn、Node、Java 或其他框架的接线方式；
- 是否通过项目脚本、测试 fixture 或框架原生命令启动；
- 健康检查的具体路径；
- 配置文件、类、函数和测试文件拆分；
- 同一稳定模块边界内部的实现组织。

只要求最终真实服务与登记 endpoint 一致，且不会影响其他产品。

### 8.4 最小结果核验

不解析 Agent 的启动命令或强制统一服务管理器。适用步骤只做与并发安全直接相关的结果核验：

- frontend 项目存在并需要真实启动时，登记 frontend endpoint 可访问；
- backend 项目存在并需要真实启动时，登记 backend endpoint 及项目实际健康入口可访问；
- 工具没有静默漂移到其他端口；
- 当前产品停止服务不会影响另一个并发产品。

具体功能、测试、构建和浏览器验收仍由原步骤合同负责。本需求不因端口设计扩大每一步的业务 verifier。

## 九、浏览器并发边界

不同产品的浏览器任务使用唯一命名 session，名称至少能关联 product key、run 和用途。实现可采用截断后的安全标识，例如：

```text
pcm-<product-key-short>-<run-id-short>-bootstrap
pcm-<product-key-short>-<run-id-short>-<requirement>
pcm-<product-key-short>-<run-id-short>-audit
```

约束：

- 不使用共享 default session 执行并发项目验收；
- 不跨产品复用 persistent profile；
- 单产品清理只关闭自己的命名 session；
- `close-all`、`kill-all` 不得作为单产品清理方式；
- 非交付截图继续放在该产品工作区根 `.test-screenshots/`，并建议按 run 或用途分目录；
- 使用 CDP endpoint 时，它也必须属于当前产品的明确运行事实，不能让多个项目默认共享固定 `localhost:9222`。

本需求不新增浏览器管理平台，只补充现有浏览器工具的并发使用边界。

## 十、Claude 用户配置并发

对 `~/.claude.json` 的 trust 更新使用独立短锁，例如：

```text
~/.claude/.pcm-config.lock
```

锁只覆盖：

```text
读取 ~/.claude.json
→ 合并当前项目 trust
→ 原子写回
```

不覆盖 Claude Agent SDK session、模型调用或完整步骤。

Claude session 和 AI-compatible conversation 继续按 run 目录及领域 key 隔离。恢复仍需核验实际 session、cwd、Skill、slash command、模型和 effort；不为并发机械修改所有领域 key，也不跨产品共享 conversation。

## 十一、外部开发资源边界

外部开发资源种类和 Provider 会变化。本需求不在 PCM Python 中枚举 PostgreSQL、MinIO、SMTP 或未来资源，也不增加通用 `resource_key`、资源状态机或逐项解析。

继续由：

- `PCM_DEV_RESOURCE_LIST` 指向的动态开发资源资料；
- `project-readiness`；
- 当前产品受保护配置；
- Claude Agent 对真实 Provider 能力和当前项目需求的判断

完成资源选择、创建、命名和隔离。

开发资源资料应以通用原则说明：

1. 新产品优先使用带产品标识的唯一资源名称；
2. 可以创建项目独立资源时，不复用其他产品的可写资源；
3. 必须共享服务实例时，使用服务支持的 database、schema、bucket、prefix、测试身份或等价 namespace；
4. migration、Seed、reset 和清理只能作用于当前产品明确拥有的范围；
5. 名称冲突时可以重新命名，但名称唯一不能替代权限和数据范围隔离；
6. 无法确认写入或清理范围时不执行破坏性动作。

用户指定的 `docs/ignore/dev-resource-list.md` 已按上述通用原则完成最小增量：保留全部真实资源、凭据和 Provider 说明，只扩展使用规则中的产品标识、独立资源优先、共享实例命名空间、最终凭据范围及 migration/Seed/reset/清理边界。该文件继续受 Git 忽略保护，具体值不进入本 TRD、日志或交付回复。

## 十二、状态与持久化

### 12.1 Run state 引用

`state.json` 只增加恢复所需的协调引用，不复制完整 Product Registry：

```json
{
  "coordination": {
    "schema_version": 1,
    "execution_run_id": "<run-directory-name>",
    "claim_phase": "claimed",
    "product_key": "<product-key>",
    "product_path": "/products/mendmark",
    "port_slot": 137,
    "ports": {
      "frontend": 3137,
      "backend": 8137
    },
    "runtime_path": ".pcm/runtime.json"
  }
}
```

`claim_phase` 只需要两个值：

- `claim_pending`：state 已原子保存 execution run、canonical path、product key 和 workspace intent；Product Registry 可能尚无记录，也可能已经写入同一 owner 的记录；
- `claimed`：Product Registry 已存在完全一致的 active 记录，state 已保存其 slot 和端口。

产品 runtime 文件不增加第三个状态机。处于同一 owner 的 `claimed` 且 runtime 文件缺失时，可以从已核验 Registry 幂等重建；已有 runtime 文件内容冲突时才失败。第 1 步既有 `publication_phase` 继续表达 staging、发布和 Git 初始化进度，不复制到协调状态。

每次 post-claim 恢复核验：

- execution run ID 与受校验的 run 目录名一致；
- product key 与 canonical product path 一致；
- `claim_pending` 时，Registry 只能不存在或已经存在同一 path、同一 owner 的 active 记录；前者创建，后者补齐 state，其他情况失败；
- `claimed` 时，Product Registry 必须存在同一 active 记录；
- owner run 与 execution run ID 一致；
- slot 和端口一致；
- 产品本机运行配置缺失时按有效恢复阶段补齐，已有内容则必须一致。

任何冲突保留现场并返回 `failed`，不自动迁移 owner、端口或路径。

### 12.2 旧 run 兼容

已有 run 可能没有 `coordination`，且已知历史中可能存在 run 目录名与旧 `state.run_id` 不一致。兼容原则：

- 不把旧不一致扩展为新 run 的允许行为；
- 不直接改写历史 `state.run_id`；
- 恢复入口仍以受路径校验的 run 目录名作为 execution run ID；
- 根据已有 workspace 和 final path 先写入 `claim_pending` 协调引用；
- 取得对应 Product Lock 后，再在短时 Registry Lock 下核验现有 run 和产品现场；
- Registry 不存在冲突记录时，为该现有产品建立 Product Record 和稳定端口；已经存在同一 path、同一 owner 的记录时幂等复用；
- 将 state 协调引用推进为 `claimed`，并按当前发布现场补齐本机 runtime 配置；
- 后续恢复只使用新协调引用。

如果同一产品已经被其他 active Product Record 认领，则拒绝自动迁移。

### 12.3 写入顺序与中断恢复

新产品最小写入顺序：

```text
取得 Run Lock 和 Capacity Slot
→ 提取 identity、解析 final path
→ 在一次 state 原子写入中保存 workspace intent 和 coordination.claim_pending
→ 取得 Product Lock
→ Registry Lock 下创建或核验同一 owner 的 Product Record + port slot
→ 将 state.coordination 原子推进为 claimed 并保存 slot/ports
→ 在当前 publication_phase 对应的 staging 或 final 位置创建本机 runtime 配置
→ 继续既有 prepare、publish 和 Git 初始化
```

每个中断窗口都有唯一恢复方式：

| 中断现场 | 同一 owner 恢复行为 |
|---|---|
| state 尚无 claim intent | 继续身份提取，不能要求 Product Registry 或 Product Lock |
| `claim_pending`，Registry 无记录 | 取得 Product Lock 后创建记录并分配 slot |
| `claim_pending`，Registry 已有同 path、同 owner 记录 | 复用原 slot，将 state 补为 `claimed` |
| `claim_pending`，Registry 属于其他 owner 或内容冲突 | `failed`，保留现场 |
| `claimed`，runtime 缺失 | 从已核验 Registry 幂等重建后继续 |
| `claimed`，runtime 已有但内容冲突 | `failed`，不覆盖 |
| Product Record 已写但工作区发布失败 | 保留端口，原 run 按既有 `publication_phase` 恢复 |

因此 Registry 成功而后续 state/runtime 写入中断，不会把同一 owner 的既有记录误判为不可恢复冲突；也不会因修复缺失文件而允许改变 path、owner 或 slot。

## 十三、失败、恢复与人工操作

### 13.1 `flock` 的释放语义

Run Lock、Product Lock、Capacity Slot 和短时 Registry Lock 均使用操作系统 `flock`：

- 正常关闭 FD 时释放；
- Python 异常退出时释放；
- `SIGTERM`、`SIGKILL` 或崩溃后，持锁进程及继承该 FD 的子进程全部退出时释放；
- 宿主机重启后释放；
- 锁文件可以长期存在，文件存在不表示锁仍被持有。

不得通过删除 `.lock` 文件解锁。删除仍被持有的锁文件可能让新旧进程锁住不同 inode，破坏互斥。

### 13.2 锁状态诊断

状态操作以再次尝试非阻塞 `flock` 判断实时锁状态：

- 能取得：当前没有执行者，读取到的旧 metadata 仅是历史诊断；
- 不能取得：锁确实由某个进程持有，可展示锁文件 metadata 帮助定位；
- metadata 中 PID 不存在但锁仍取不到时，不依据 PID 强制删除文件，应继续查找继承 FD 的子进程。

### 13.3 人工停止与释放的区别

- **停止执行**：终止明确归属当前 run 的进程，使实时锁和 Capacity Slot 释放，但 Product Record 和端口保留；
- **释放产品**：确认产品不再开发后，将 lifecycle 改为 released 并回收端口，不等同于杀进程；
- **删除 lock 文件**：禁止，不属于任何恢复操作。

首版至少提供状态查看和 release 操作。是否同时提供自动发送 `SIGTERM` 的 stop 操作由实现风险决定；如果没有安全归属证据，只输出需人工检查的 PID 和 run，不提供宽泛 kill。

### 13.4 错误分类

以下属于 `failed` 而不是 `blocked`：

- Run Lock 或 Product Lock 身份冲突；
- Product Registry 损坏或路径、owner、slot 不一致；
- 产品端口被未知进程占用；
- Agent 启动到非登记端口；
- 本机协调目录或锁文件路径异常；
- state 与新协调引用冲突。

Capacity Slot 暂时耗尽属于本机调度拒绝，CLI 使用独立的稳定非成功退出，不写成业务步骤 `blocked` 或覆盖当前步骤结果。其他步骤既有 `success / blocked / failed` 语义保持不变。

## 十四、权限、安全与异常边界

- `.coordination` 和产品 `.pcm` 目录必须是普通目录，不接受符号链接跳转；
- 锁路径和 product key 只能由已校验输入构造；
- Product Registry 更新前后核验 schema、路径、owner 和 slot 唯一性；
- 锁 metadata 不保存 API Key、token、密码、环境变量具体值或完整命令秘密；
- 产品 runtime 配置只保存 host、port、URL 和协调身份，不保存外部资源秘密；
- 人工 release 不删除产品目录、Git、run 状态或外部资源；
- 未知监听进程不终止；
- 单产品浏览器清理不影响其他 session；
- 当前只承诺 POSIX 本地可靠文件系统上的 `flock`；
- 不通过 lock file mtime、PID 或 metadata 推断 stale 并抢占；
- 对 `~/.claude.json` 的更新必须在短锁内重新读取后合并，避免丢失其他产品刚写入的 trust。

## 十五、实现归属与架构影响

### 15.1 架构分类

本需求属于**新增稳定本机协调边界**，但不改变第 0～18 步的业务顺序、领域 Skill、Agent 决策循环、需求生命周期或多仓 Git 职责。

### 15.2 稳定 owner

- PCM 编排器拥有 Capacity Slot、Run Lock、Product Lock、Product Registry 和端口分配；
- 第 1 步拥有产品首次认领、runtime 文件随工作区发布和恢复交接；
- `run_all.py` 拥有完整编排期间锁的生命周期与子进程传递；
- `run_step.py` 拥有独立调用时的同协议获取和核验；
- 第 2 步只在短锁内更新 Claude 用户 trust；
- 第 6 步 `project-bootstrap` 按真实技术栈接入已分配 endpoint；
- 第 15 步和阶段二消费既有项目运行配置，不重新分配；
- Product Registry 的人工状态查看和 release 由 PCM 本机管理入口负责；
- 外部资源隔离继续由 `project-readiness` 和动态资源资料负责。

### 15.3 依赖方向

```text
run_all.py / run_step.py
        ↓
薄本机协调模块
        ↓
fcntl、原子 JSON、路径核验
```

步骤领域模块可以调用协调模块提供的产品运行事实，但协调模块不得依赖具体步骤、Skill、Git 业务或 Agent 决策循环。

### 15.4 可调整的文件组织

实现可根据现有代码量决定：

- 在 `common/` 中新增一个薄协调模块，或拆成锁与注册表两个小模块；
- CLI 状态/release 是放入 `run_all.py` 的互斥子命令，还是使用一个小型独立入口；
- `pass_fds` 使用的内部环境字段或 CLI 参数名称，以及 FD 对应锁路径和身份的核验数据结构；
- 时间字段、诊断 metadata 和测试 helper 的具体结构。

不得把本需求扩展为通用工作流、分布式锁、资源 DSL 或服务管理框架。

## 十六、实现约束与可调整项

### 16.1 必须满足

- 全局长锁不再串行所有产品；
- 宿主机并发数由 Capacity Slot 限制；
- `run_all.py` 与独立 `run_step.py` 使用同一锁协议；
- 同一产品以 canonical final path 互斥；
- 同一 run 只有一个状态写入者；
- 第 1 步在 clone、prepare 和 publish 前保存 claim intent，并按 Product Lock → Registry Lock 顺序完成产品认领；
- `claim_pending`、`claimed` 和 runtime 缺失窗口均有同一 owner 的幂等恢复路径；
- `run_all.py` 使用受控 FD 继承把已持有锁传给 `run_step.py`，环境或 CLI 元数据不能替代锁 FD；
- Product Record 与端口在意外中断后保留；
- 端口只能人工 release；
- frontend 使用 `3xxx`、backend 使用配对 `8xxx`；
- Agent 能读取明确的产品本机运行配置；
- Agent 不静默换端口、不杀未知进程；
- `.env.example` 记录配置合同，不复制某台机器的秘密；实际端口值可存在 Git 忽略配置；
- `~/.claude.json` 的 read-modify-write 使用短锁；
- 锁冲突和端口冲突均提供可执行的恢复说明；
- 旧 run 的已知身份不一致有有限兼容，新 run 不再产生该状态。

### 16.2 允许实现阶段调整

- `PCM_MAX_CONCURRENT_PROJECTS` 的默认值可依据真实宿主机验证调整，但必须有安全默认值；
- Product Registry 的内部字段可以在不改变生命周期语义的前提下精简；
- Agent 项目的实际环境变量名按技术栈确定；
- frontend/backend 健康检查方式按项目事实确定；
- 状态查看和 release 的具体 CLI 形态可以调整；
- lock metadata 的展示内容可以调整；
- 可先不实现自动 stop，只保留安全诊断和人工操作说明。

### 16.3 明确不允许的简化

- 只把 `.run_all.lock` 改成按 run ID 锁；
- 只在 `run_all.py` 加锁而允许 `run_step.py` 绕过；
- 以 `final_path.exists()` 代替 Product Lock 或 Product Record；
- 以原子 JSON replace 代替 Run Lock；
- 在进程退出时释放端口；
- 用删除 `.lock` 文件解决锁冲突；
- 让 Vite 或其他框架自动换端口后继续验收；
- 仅凭 `/health` 成功认定命中了当前产品；
- 通过固定资源类型 schema 形式化所有外部开发资源；
- 为实现并发而改变第 0～18 步业务顺序或需求 Git 生命周期。

## 十七、验证场景

验证以关键并发结果为中心，不要求冻结 Agent 的每条命令或项目内部实现。

### 17.1 锁与容量

1. `PCM_MAX_CONCURRENT_PROJECTS=2` 时，两个不同产品能同时越过入口并各自长期运行；
2. 第三个执行在两个 slot 均被持有时立即拒绝，不创建新的业务步骤结果；
3. 任一执行退出后，其 Capacity Slot 可被新执行取得；
4. 同一 run 的两个 resume 只有一个能取得 Run Lock；
5. 同一路径的两个不同 run 只有 owner run 能继续；
6. 直接 `run_step.py` 不能绕过锁；
7. 父 `run_all.py` 退出但步骤子进程仍运行时，继承的锁继续有效；
8. lock 文件长期存在但未被持有时，不误报占用；
9. 删除 lock 文件不是任何测试或恢复路径。

### 17.2 产品认领与发布

1. 两个 fresh run 得到同一 final path 时，只有一个能按 Product Lock → Registry Lock 顺序认领；
2. 被拒绝 run 不进入 clone、prepare 或 publish；
3. `claim_pending` 写入后、Registry 创建前中断，原 run 可以完成认领；
4. Registry 创建后、state 推进 `claimed` 前中断，原 run 复用原 slot 并补齐 state；
5. `claimed` 后、runtime 创建前中断，原 run 从 Registry 补齐 runtime；
6. 认领完成后第 1 步中断，原 run 继续使用原 Product Record 和 slot；
7. 其他 run 不能因产品目录尚未发布而接管；
8. 不同 final path 可以同时完成发布；
9. 现有 staging marker、安全清理和原子 rename 行为保持不变；
10. owner run 执行期间即使 Product Lock 位于父子交接窗口，人工 release 仍被 Run Lock 拒绝。

### 17.3 端口生命周期

1. 新产品取得一个未登记且当时可 bind 的配对 slot；
2. 两个 active 产品不会分配同一 slot；
3. frontend 和 backend 端口符合 `3xxx/8xxx` 配对规则；
4. run success、failed、blocked、取消或异常退出后，slot 仍归原产品；
5. resume 复用原 slot，Product Registry、state 和 `.pcm/runtime.json` 一致；
6. 未知程序占用已分配端口时，执行失败且不杀进程、不换 slot；
7. owner Run Lock 或 Product Lock 被持有，或分配端口仍在监听时，人工 release 被拒绝；
8. release 成功后，原 slot 可以分给后续新产品；
9. release 不删除产品代码和 run 历史。

### 17.4 Agent 与真实服务

1. 第 6 步 Agent 能读取产品 runtime 配置；
2. 实际项目按自己的技术栈将 endpoint 接入本地配置；
3. frontend 和 backend 真实监听登记端口；
4. frontend API URL、backend CORS、health 和浏览器访问使用同一事实；
5. 支持自动换端口的工具被配置为冲突即失败；
6. 两个产品同时启动前后端时均可访问，且不会访问到对方服务；
7. 一个产品结束临时服务或浏览器 session，不影响另一个产品；
8. 现有业务测试、构建、真实联调和浏览器验收合同保持不变。

### 17.5 状态、配置与兼容

1. 两个不同 run 的 state、steps、conversation 和 logs 不互相覆盖；
2. `~/.claude.json` 两个并发 trust 更新都被保留；
3. 新 run 的 execution run ID 与目录名一致；
4. 已知旧 run 身份不一致可在无产品冲突时建立协调引用并继续，不改写历史字段；
5. Product Registry 损坏、重复 active slot、路径/hash 不一致时停止并保留文件；
6. `.coordination`、Product Lock 或 `.pcm` 路径是符号链接时拒绝；
7. 日志和 metadata 不包含秘密。

### 17.6 人工操作

1. 状态命令能区分“锁文件存在”和“锁实际被持有”；
2. 锁被持有时展示 owner 诊断和正确恢复方向；
3. 锁未持有但产品 active 时，提示产品端口仍保留；
4. 文档明确禁止删除 lock 文件；
5. release 需要明确产品路径，不允许模糊匹配或批量释放；
6. 无法证明产品和端口归属时拒绝 release。

## 十八、风险、假设与后续演进

### 18.1 当前假设

- 只运行一个受控的 PCM Demo checkout；
- `pcm-demo/runs/.coordination` 位于可靠本地 POSIX 文件系统；
- 所有正式入口均使用本设计的锁模块；
- Claude Agent SDK 在 `run_step.py` 生命周期内管理其子进程；
- 产品工作区仍位于当前能力仓库之外；
- 900 个未释放产品 slot 足以覆盖当前 Demo 生命周期。

### 18.2 已接受风险

- bind 探测与真实服务启动之间，非 PCM 程序仍可能抢占端口；处理方式是启动失败，不做 socket activation；
- Agent 仍可能首次忽略规则；通过项目规则、明确 runtime 配置和登记 endpoint 结果核验纠正，而不建立强制服务管理器；
- 一个被强制终止的 `run_step.py` 可能留下无法立即证明归属的 SDK 或服务子进程；后续运行保留现场并报告冲突，不自动清理；
- 外部开发资源隔离依赖资源资料、`project-readiness` 和 Agent 判断，不由本需求统一证明；
- 模型和外部 Provider 配额可能降低实际并发吞吐，但不构成共享数据正确性锁。

### 18.3 重新评估条件

出现以下事实时，再单独设计后续能力：

- 多个 Demo checkout 或多台机器需要共享产品工作区；
- 900 个长期 active 产品不足；
- 孤儿服务频繁导致人工恢复成本高；
- 需要自动排队、优先级或公平调度；
- 需要把已释放产品重新激活并保留兼容入口；
- 外部资源实际发生跨产品污染，且领域说明不能可靠约束；
- 同一产品内部需要并行开发多个需求。

## 十九、本次设计调整

相较最初讨论，本 TRD 作出以下收敛：

- 将“不同项目并发”与“宿主机最多同时运行几个项目”拆开，增加 Capacity Slot；
- 将进程级 `flock` 与长期端口租约拆开，异常中断不释放端口；
- 端口从“第 4 步后按实际服务分配”调整为“第 1 步产品认领时预留完整前后端配对”，以减少交接和恢复分支；
- 将 Product Record 与 Port Registry 合并为一份受短锁保护的 Product Registry，避免双文件事务；
- 不再把通用服务启动器作为首版前置，只约束 endpoint 结果并保留 Agent 的技术栈实现自由；
- 不为动态外部资源建立结构化 DSL，只要求资源资料和 `project-readiness` 保持通用隔离原则；
- 不提供删除锁或强制抢锁操作，只提供状态诊断和人工产品 release；
- 对现有历史 run 的已知 run ID 不一致保留有限兼容，新 run 使用新的协调身份约束。

## 二十、设计审查

### 20.1 自审结论

本设计保持了当前 Demo 的主要工程边界：

- 不改变第 0～18 步业务职责和顺序；
- 不改变 Agent 决策循环；
- 不改变需求注册表、需求分支、提交和 ff-only 合并语义；
- 不引入数据库、队列、分布式锁或资源 DSL；
- 只对本机并发正确性增加最小稳定协调能力；
- 对 Agent 采用“安全不变量严格、内部实现自由”；
- 将人工无法可靠自动判断的产品终止生命周期保留给人决定。

### 20.2 实施前无需再决定的事项

以下已在本次讨论中确认，可直接作为实现基线：

- 不同产品可并发，同一产品互斥；
- 宿主机并发数有限且可配置；
- 产品端口从创建开始长期保留；
- 端口只由人工 release；
- frontend 使用 `3xxx`，backend 使用对应 `8xxx`；
- 根 `AGENTS.md` 增加简短端口结果约束；
- 不过度形式化外部资源；
- 不过度限制 Agent 的具体实现方式；
- 不建设额外工作流或服务编排平台。

### 20.3 尚未核验范围

- `docs/ignore/dev-resource-list.md` 已完成并发资源通用使用规则增量，未改动具体资源和凭据；
- 尚未执行真实双产品并发 Agent、前后端服务和浏览器运行；
- 尚未验证当前 Claude Agent SDK 子进程在父/步骤进程异常终止时的全部遗留行为；
- 尚未确定具体产品模板中各技术栈的端口配置键，这应由实现阶段读取真实模板后决定；
- 尚未实现或验证未来阶段二对同一产品 runtime 配置的复用。

这些缺口不改变本设计的锁、生命周期和端口语义；实现时先完成自动化竞态验证，再用两个独立产品执行最小真实并发验证。
