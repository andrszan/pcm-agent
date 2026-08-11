# Claude Code 设置、权限与沙箱指南

> 调研日期：2026-08-11。Claude Code 更新较快，具体字段、可选值和设置来源以当前版本的官方文档为准。

## 1. 心智模型

Claude Code 的安全控制主要分为两层：

- **Permissions** 决定工具调用能否执行，以及执行前是否需要确认。
- **Sandbox** 决定命令获准执行后，在操作系统层面能够访问哪些文件和网络。

简化理解：

```text
Permissions：能不能执行
Sandbox：执行后能碰到什么
```

二者互补，不能互相替代。Permissions 是调用前的策略判断；sandbox 是命令运行时的系统边界。

## 2. Settings 的作用域与优先级

Claude Code 从多个来源读取 `settings.json`：

| 作用域 | 位置 | 典型用途 |
| --- | --- | --- |
| Managed | 组织下发、系统策略或 `managed-settings.json` | 管理员强制策略，普通配置不可覆盖 |
| User | `~/.claude/settings.json` | 当前用户的所有项目 |
| Project | `<repo>/.claude/settings.json` | 团队共享，通常提交到 Git |
| Local | `<repo>/.claude/settings.local.json` | 当前用户在当前仓库的私有设置，通常不提交 |
| CLI | 启动参数，如 `--permission-mode` 或 `--settings` | 当前启动或会话 |

普通标量设置的优先级由高到低为：

```text
Managed > CLI > Local > Project > User
```

高优先级标量覆盖低优先级值。`permissions.allow`、`ask`、`deny` 和多数 sandbox 路径、域名数组会跨作用域合并，而不是简单覆盖。

需要注意：

- 任意作用域中的 `deny` 都不能被其他作用域的 `allow` 覆盖。
- Project 中能够扩大能力的 `permissions.allow` 和 `permissions.additionalDirectories`，只有在用户接受 workspace trust 后才会应用。
- 部分安全字段只接受 User、Managed 或 CLI 来源。把它们放入 Project settings，可能不会生效。
- 使用 `/status` 可检查实际加载的配置来源；使用 `/permissions` 可查看权限规则及来源文件。

## 3. Permission rules

### 3.1 三类规则

```json
{
  "permissions": {
    "allow": ["Bash(pnpm test)"],
    "ask": ["Bash(git push *)"],
    "deny": ["Read(.env)"]
  }
}
```

| 规则 | 行为 |
| --- | --- |
| `allow` | 匹配调用无需确认 |
| `ask` | 匹配调用必须确认 |
| `deny` | 阻止匹配调用 |

判定顺序固定为：

```text
deny > ask > allow
```

规则具体程度不会改变优先级。若同一调用同时匹配具体的 `allow` 和宽泛的 `deny`，最终仍会被拒绝。

### 3.2 规则语法

规则格式为：

```text
Tool
Tool(specifier)
```

常见示例：

```json
{
  "permissions": {
    "allow": [
      "Bash(pnpm run *)",
      "Read(/src/**)",
      "Edit(/docs/**)",
      "WebFetch(domain:github.com)",
      "mcp__github__get_*"
    ],
    "ask": [
      "Bash(git push *)",
      "Bash(run_in_background:true)"
    ],
    "deny": [
      "Read(.env)",
      "Edit(.claude/**)",
      "Bash(curl *)"
    ]
  }
}
```

关键规则：

- 裸工具名如 `Bash` 匹配该工具的全部调用；在 `deny` 中会让模型完全看不到该工具。
- Bash 的 `*` 可跨参数和空格匹配。`Bash(git *)` 会覆盖大量 Git 子命令。
- 复合命令会按子命令分别检查。允许 `safe-command` 不代表同时允许 `safe-command && other-command`。
- `Read`、`Edit` 路径使用 gitignore 风格。Project settings 中的 `/src/**` 表示项目根目录下的 `src`；文件系统绝对路径使用 `//tmp/file`。
- 文件路径权限应写成 `Read(path)`、`Edit(path)`；不要用 `Write(path)`、`Glob(path)` 或 `NotebookEdit(path)` 代替。
- `Read`、`Edit` 主要约束内置文件工具和 Claude Code 能识别的文件命令，不能可靠限制 Python、Node 等任意子进程间接读写文件；这种场景需要 sandbox。
- 用 Bash 参数模式限制 URL 较脆弱。更可靠的做法是限制 `curl`、`wget`，并用 `WebFetch(domain:...)` 与 sandbox 网络策略控制访问。

### 3.3 常见路径写法

`Read` 和 `Edit` 权限规则使用以下路径前缀：

| 写法 | 含义 |
| --- | --- |
| `Edit(/src/**)` | 相对定义该规则的 Project settings 根目录 |
| `Read(./config.json)` | 相对 Claude Code 启动目录 |
| `Read(~/.ssh/**)` | 相对用户主目录 |
| `Read(//tmp/**)` | 文件系统绝对路径 `/tmp/**` |

Sandbox 的路径规则不同，使用常规路径语义：`./src` 为项目相对路径，`~/cache` 为主目录相对路径，`/tmp/build` 为绝对路径。

## 4. Permission modes

`permissions.defaultMode` 设置新会话的默认权限模式：

| 模式 | 核心行为 | 适用场景 |
| --- | --- | --- |
| `default` | 读取通常直接运行，其他操作按规则确认 | 敏感工作、初次使用 |
| `acceptEdits` | 自动接受工作区内文件编辑和常见文件操作 | 持续编码并通过 diff 复核 |
| `plan` | 以读取、探索和规划为主，不直接修改源码 | 改动前分析 |
| `auto` | 由后台安全分类器逐操作审核，减少常规提示 | 方向可信的长任务 |
| `dontAsk` | 未被预先允许的工具自动拒绝，不弹窗 | 非交互 CI、严格 allowlist |
| `bypassPermissions` | 默认批准几乎所有工具调用 | 仅限容器、VM 或完整进程 sandbox |

### 4.1 `bypassPermissions` 最容易被误解

它不是“只执行 allowlist 中的操作”。准确行为是：

- 显式 `deny` 仍然生效。
- 显式 `ask` 仍然强制确认。
- `allow` 不再提供限制作用，因为其他未列出的操作也默认获准。
- 组织设为 `ask` 的 Connector、标记 `requiresUserInteraction` 的 MCP 工具仍需确认。
- 删除 `/` 或用户主目录仍有安全断路器。
- `.git`、`.claude` 等 protected paths 的普通写入保护会被跳过。

如果目标是“只允许运行明确列出的工具”，应该选择 `dontAsk` 加精确 `allow`，而不是 `bypassPermissions`。

### 4.2 `auto` 也不是 sandbox

`auto` 使用安全分类器逐操作判断是否允许执行，能够减少人工提示，但它不是文件系统或网络隔离边界。无人值守任务仍应放在容器、VM 或完整进程 sandbox 中运行。

## 5. Sandbox environments

### 5.1 可选隔离边界

| 方案 | 隔离范围 | 典型用途 |
| --- | --- | --- |
| 内置 Bash sandbox | 仅 Bash 及其子进程 | 日常本机开发、减少 Bash 提示 |
| `@anthropic-ai/sandbox-runtime` | 整个 Claude Code 进程，包括文件工具、MCP 和 hooks | 不使用 Docker 的完整进程隔离 |
| Dev container / 自定义容器 | 完整开发环境 | 团队标准化、CI、无人值守任务 |
| VM | 完整操作系统 | 不可信仓库、高隔离要求 |
| Claude Code on the web | Anthropic 托管 VM | 托管式完整隔离 |

内置 Bash sandbox 使用 macOS Seatbelt 或 Linux、WSL2 的 bubblewrap，但它**不覆盖**内置 `Read`、`Edit`、`WebFetch`、MCP server 和 hooks。因此，它不能单独作为 `bypassPermissions` 或完全无人值守运行的完整安全边界。

### 5.2 内置 Bash sandbox 的默认边界

默认情况下，sandboxed Bash 命令：

- 可写当前工作目录和会话临时目录；
- 默认可读取计算机上的大部分文件，包括未显式保护的凭据文件；
- 访问新网络域名时请求批准；
- 不能在 sandbox 中运行时，可能回退到普通权限流程并尝试 unsandboxed 执行。

严格隔离通常至少需要：

```json
{
  "sandbox": {
    "enabled": true,
    "failIfUnavailable": true,
    "allowUnsandboxedCommands": false,
    "filesystem": {
      "denyRead": ["~/"],
      "allowRead": ["."]
    },
    "network": {
      "allowedDomains": [
        "registry.npmjs.org",
        "*.npmjs.org",
        "github.com",
        "api.github.com"
      ]
    }
  }
}
```

其含义是：sandbox 无法启动时直接失败；不允许命令逃逸到宿主机运行；阻止读取整个主目录，再重新开放工作区根目录；预先允许列出的网络域名。

实际使用时还应通过 `sandbox.credentials` 明确保护凭据文件和敏感环境变量，因为默认读取策略不会自动屏蔽它们。

### 5.3 Sandbox auto-allow

`sandbox.autoAllowBashIfSandboxed` 默认为 `true`。启用后，能够在 sandbox 内执行的 Bash 命令会自动获准；sandbox 边界取代普通的整工具确认。

即使开启 auto-allow，以下规则仍生效：

- 显式 `deny`；
- 内容明确的 `ask`，例如 `Bash(git push *)`；
- 删除根目录、主目录或关键系统路径的安全检查。

若希望所有 Bash 命令仍按普通 Permissions 流程确认，可设置：

```json
{
  "sandbox": {
    "autoAllowBashIfSandboxed": false
  }
}
```

## 6. Attribution settings

Claude Code 支持：

| 字段 | 作用 |
| --- | --- |
| `attribution.commit` | Git commit attribution；空字符串关闭 |
| `attribution.pr` | Pull Request 描述 attribution；空字符串关闭 |
| `attribution.sessionUrl` | 是否在支持的会话中加入 `Claude-Session` trailer 或会话链接；默认开启 |

完全关闭 attribution：

```json
{
  "attribution": {
    "commit": "",
    "pr": "",
    "sessionUrl": false
  }
}
```

如果需要 attribution，可将 `commit` 设置为 commit trailer 文本，将 `pr` 设置为加入 Pull Request 描述的普通文本。

## 7. 完整、直观的 `settings.json` 示例

### 7.1 为什么不建议把所有官方字段放进一个文件

Claude Code 的完整 Settings 表包含大量与 UI、模型、插件、云端会话、企业策略和平台能力相关的字段。部分字段：

- 只允许出现在 User 或 Managed settings；
- 在 Project settings 中会被忽略；
- 互相排斥或代表不同安全策略；
- 依赖特定操作系统、代理、插件或组织功能。

因此，不存在一个适用于所有环境、把全部字段都写上的“万能配置”。下面的示例覆盖本文讨论的主要领域，并严格区分 Project、User 和 Managed 三种来源。

### 7.2 可提交到仓库的 Project settings 示例

文件位置：`<repo>/.claude/settings.json`。

这是一个适用于常见 Node.js、pnpm 和 Git 工作流的安全基线。它是有效 JSON，可以直接复制；其中的目录、命令、域名和插件需要根据实际项目调整。

```json
{
  "permissions": {
    "defaultMode": "default",
    "disableBypassPermissionsMode": "disable",
    "allow": [
      "Edit(/src/**)",
      "Edit(/tests/**)",
      "Edit(/docs/**)",
      "Bash(pnpm install --frozen-lockfile)",
      "Bash(pnpm run lint *)",
      "Bash(pnpm run test *)",
      "Bash(pnpm run build *)",
      "Bash(git status *)",
      "Bash(git diff *)",
      "Bash(git log *)",
      "Bash(git show *)",
      "Bash(git add -- *)"
    ],
    "ask": [
      "Edit(/.claude/**)",
      "Bash(git commit *)",
      "Bash(git push *)",
      "Bash(run_in_background:true)",
      "Agent(isolation:worktree)"
    ],
    "deny": [
      "Read(.env)",
      "Read(**/.env)",
      "Read(.env.local)",
      "Read(**/.env.local)",
      "Read(.env.*.local)",
      "Read(**/.env.*.local)",
      "Edit(.git/**)",
      "Edit(.claude/settings.json)",
      "Edit(.claude/settings.local.json)",
      "Bash(git push --force *)",
      "Bash(git push -f *)",
      "Bash(npm publish *)",
      "Bash(pnpm publish *)",
      "Bash(curl *)",
      "Bash(wget *)"
    ]
  },
  "sandbox": {
    "enabled": true,
    "failIfUnavailable": true,
    "autoAllowBashIfSandboxed": false,
    "allowUnsandboxedCommands": false,
    "excludedCommands": [],
    "filesystem": {
      "allowWrite": [
        "~/.cache/pnpm"
      ],
      "denyWrite": [
        "./.git/hooks",
        "./.claude"
      ],
      "denyRead": [
        "~/"
      ],
      "allowRead": [
        ".",
        "~/.cache/pnpm"
      ]
    },
    "network": {
      "allowedDomains": [
        "registry.npmjs.org",
        "*.npmjs.org",
        "github.com",
        "api.github.com",
        "codeload.github.com",
        "objects.githubusercontent.com"
      ],
      "deniedDomains": [
        "metadata.google.internal",
        "169.254.169.254"
      ]
    },
    "credentials": {
      "files": [
        {
          "path": "~/.aws/credentials",
          "mode": "deny"
        }
      ],
      "envVars": [
        {
          "name": "AWS_ACCESS_KEY_ID",
          "mode": "deny"
        },
        {
          "name": "AWS_SECRET_ACCESS_KEY",
          "mode": "deny"
        },
        {
          "name": "AWS_SESSION_TOKEN",
          "mode": "deny"
        }
      ]
    }
  },
  "enabledPlugins": {
    "context7@claude-plugins-official": true,
    "typescript-lsp@claude-plugins-official": true
  },
  "attribution": {
    "commit": "",
    "pr": "",
    "sessionUrl": false
  }
}
```

这个示例的实际效果：

1. 使用 `default` 权限模式，不会默认跳过安全检查。
2. 禁止在会话中启用 `bypassPermissions`。
3. 自动允许指定目录的编辑，以及确定的安装、检查、测试、构建和只读 Git 命令。
4. 修改 Claude Code 配置、创建 commit、执行 push、启动后台命令或创建 worktree 前要求确认。
5. 强制推送、发布 npm 包、直接使用 `curl` 或 `wget` 被拒绝。
6. 内置 Bash sandbox 必须可用，而且命令不能回退到宿主机执行。
7. Sandboxed Bash 不能读取整个主目录，只重新开放工作区根目录和 pnpm 缓存。
8. Bash 网络访问预先允许 npm registry 和常见 GitHub 下载域名。
9. AWS 凭据文件和环境变量不会暴露给 sandboxed Bash。
10. 关闭 commit、Pull Request 和会话链接 attribution。

注意：

- `denyRead: ["~/"]` 会阻止 Bash 读取主目录。目标仓库通常位于主目录下，因此必须通过更具体的 `allowRead: ["."]` 重新开放工作区根目录。
- 拒绝 AWS 凭据只是示例。如果任务确实需要 AWS，应删除对应 `deny`，或在可信的 User、Managed 设置中改用凭据 masking。
- `Bash(curl *)` 和 `Bash(wget *)` 的 deny 用于推动网络读取通过 `WebFetch` 或已批准的包管理器完成。如果项目确实依赖它们，应改成更精确的规则。
- `enabledPlugins` 只声明启用状态，不会替其他用户静默安装插件。每位用户仍需安装并信任相应插件。
- 原生 Windows 不支持内置 Bash sandbox。使用此基线时应在 WSL2、容器或 VM 中运行。

### 7.3 可选的附加目录

如果 Claude 还需要访问仓库外的共享代码，可加入：

```json
{
  "permissions": {
    "additionalDirectories": [
      "../shared-types"
    ]
  }
}
```

`additionalDirectories` 会扩大文件访问范围，Project 中的配置只有在用户接受 workspace trust 后才会应用。不要加入与任务无关的主目录或大型目录。

### 7.4 适合 User settings 的严格网络和凭据 masking

以下字段不应放入仓库的 Project settings，而应放入 `~/.claude/settings.json`、Managed settings，或通过受信任的 `--settings` 文件传入：

```json
{
  "sandbox": {
    "network": {
      "strictAllowlist": true,
      "tlsTerminate": {}
    },
    "credentials": {
      "envVars": [
        {
          "name": "GITHUB_TOKEN",
          "mode": "mask",
          "injectHosts": [
            "api.github.com"
          ]
        },
        {
          "name": "NPM_TOKEN",
          "mode": "mask",
          "injectHosts": [
            "registry.npmjs.org"
          ]
        }
      ]
    }
  }
}
```

其含义是：

- 未列入网络 allowlist 的域名直接拒绝，而不是临时请求批准。
- Sandboxed Bash 看到的是凭据占位符，不是真实 token。
- Sandbox 网络代理只在发往指定域名的请求中替换真实凭据。
- `tlsTerminate` 使代理能够检查并替换加密请求中的凭据。

`mask`、`strictAllowlist` 和 `tlsTerminate` 属于可信配置，放进 Project 或 Local settings 不会按上述方式生效。

### 7.5 适合 Managed settings 的组织强制策略

组织管理员可使用 Managed settings 强制所有用户遵守隔离策略：

```json
{
  "permissions": {
    "disableBypassPermissionsMode": "disable",
    "disableAutoMode": "disable"
  },
  "sandbox": {
    "enabled": true,
    "failIfUnavailable": true,
    "allowUnsandboxedCommands": false,
    "filesystem": {
      "allowManagedReadPathsOnly": true
    },
    "network": {
      "allowManagedDomainsOnly": true
    }
  }
}
```

其含义是：

- 用户不能启用 `bypassPermissions` 或 `auto`。
- Sandbox 不可用时拒绝启动，命令不能逃逸到宿主机。
- 只有 Managed settings 中声明的 `allowRead` 和网络域名能够扩大访问范围。
- User、Project 和 Local settings 仍可继续增加 deny 限制，但不能放宽管理员边界。

## 8. Project settings 中容易误用的字段

| 字段或配置 | Project 中是否生效 | 说明 |
| --- | --- | --- |
| `sandbox.filesystem.allowWrite` | 是 | 增加 sandboxed Bash 可写路径 |
| `sandbox.filesystem.denyWrite` | 是 | 阻止 sandboxed Bash 写入路径 |
| `sandbox.filesystem.denyRead` | 是 | 阻止 sandboxed Bash 读取路径 |
| `sandbox.filesystem.allowRead` | 是 | 在宽泛 `denyRead` 内重新开放指定路径 |
| `sandbox.filesystem.disabled` | 否 | 仅 User、Managed 或 CLI 来源可以关闭文件系统隔离 |
| `sandbox.filesystem.allowManagedReadPathsOnly` | 否 | 仅 Managed settings 有效 |
| `sandbox.network.allowedDomains` | 是 | 预先允许 sandboxed Bash 访问的域名 |
| `sandbox.network.deniedDomains` | 是 | 阻止指定域名，deny 优先 |
| `sandbox.network.strictAllowlist` | 否 | 仅 User、Managed 或 CLI 来源有效 |
| `sandbox.network.allowManagedDomainsOnly` | 否 | 仅 Managed settings 有效 |
| `sandbox.network.tlsTerminate` | 否 | 仅 User、Managed 或 CLI 来源有效 |
| `sandbox.credentials.*.mode: "deny"` | 是 | 阻止 sandboxed Bash 读取凭据或继承变量 |
| `sandbox.credentials.*.mode: "mask"` | 否 | 仅 User、Managed 或 CLI 来源有效 |
| `pluginConfigs` | 否 | 只从 User、Managed 或 CLI settings 读取 |
| `enabledPlugins` | 是 | 可在 Project 中声明项目插件启用状态 |

## 9. 常见冲突和误区

| 组合 | 问题 | 建议 |
| --- | --- | --- |
| `bypassPermissions` 加宽泛 `allow` | 未匹配 allow 的操作也默认获准，allowlist 不构成安全边界 | 使用 `default`，或在非交互环境使用 `dontAsk` 加精确 allowlist |
| `bypassPermissions` 但没有完整环境隔离 | 可直接写 protected paths；内置 Bash sandbox 也不隔离 MCP 与 hooks | 只在容器、VM 或 sandbox runtime 中使用 |
| `autoAllowBashIfSandboxed: true`，同时期望每个 Bash 都确认 | Sandbox 内命令会自动执行 | 需要人工确认时设为 `false` |
| `allowUnsandboxedCommands: false` 加大量 `excludedCommands` | `excludedCommands` 会明确创建 sandbox 外执行路径 | 严格隔离时保持例外列表为空 |
| `denyRead: ["~/"]` 没有 `allowRead: ["."]` | 项目位于主目录时，项目源码也可能被阻止 | 成对配置并重新开放项目根目录 |
| 拒绝 `NPM_TOKEN` 或 `GITHUB_TOKEN`，同时使用私有依赖 | 对应 CLI 或包管理器认证会失败 | 在可信 User 或 Managed settings 中使用 `mask` |
| 在 Project 中设置 `strictAllowlist`、`filesystem.disabled` 或 `mask` | 字段存在但该来源不被接受，容易形成错误安全感 | 移至 User、Managed 或 CLI settings |
| 把 `enabledPlugins` 当作自动安装 | Project settings 只声明启用，用户仍需安装和信任 | 同时记录插件来源、用途和信任要求 |
| 关闭 `commit` attribution，但保留 `sessionUrl: true` | 支持的 cloud 或 Remote Control 会话仍可能加入会话链接 | 需要完全关闭时同步设置三个 attribution 字段 |

## 10. 常用检查命令

```text
/status       查看实际加载的配置来源
/permissions  查看、添加和删除权限规则
/sandbox      查看和调整内置 Bash sandbox
```

修改 settings 后，应重新启动 Claude Code，并用 `/status`、`/permissions` 和 `/sandbox` 检查最终解析结果，而不是只检查单个 JSON 文件。

## 官方资料

- [Settings](https://code.claude.com/docs/en/settings)
- [Permissions](https://code.claude.com/docs/en/permissions)
- [Permission modes](https://code.claude.com/docs/en/permission-modes)
- [Sandbox environments](https://code.claude.com/docs/en/sandbox-environments)
- [Sandboxing](https://code.claude.com/docs/en/sandboxing)
