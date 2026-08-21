---
name: foundation-selection
description: Use only when the user provides readable foundation-selection reference data and asks to choose the frontend/backend project foundations. Select exactly one listed template for each required side; never invent a template or answer without the reference data. In PCM, return only the fixed JSON object defined below, with no surrounding text.
argument-hint: <需求/产品资料 + catalog.json 或其它明确的选型参考资料>
disable-model-invocation: true
---

# foundation-selection — 基础项目选型

## 职责

根据需求、产品资料和本次可读的选型参考资料，为项目需要的前端和后端各选择一个基础模板。只做资料内选型，不克隆、组装、自建或修改项目，也不补充资料外的技术推荐。

## 选型规则

1. 必须先读取本次提供的参考资料；资料缺失或无法读取时返回错误。
2. 每个选中模板必须原样存在于资料中，`id`、`git_url`、`default_branch` 和 `path` 必须与资料一致。
3. 根据需求在资料内为每个需要的交付面选择且只选择一个模板；项目明确不需要某一端时，该字段返回 `null`。
4. `reason` 只说明需求与候选模板的匹配关系，不添加资料中没有的技术事实。
5. 不得依赖记忆、缓存、常见技术栈或资料外候选补全结果。
6. 无论成功或失败，除规定 JSON 外不得输出文本、Markdown、代码围栏或解释。

## `catalog.json` 输入

PCM 使用 `catalog.json`：

```json
{
  "repositories": {
    "<repository_id>": {
      "git_url": "...",
      "default_branch": "...",
      "templates": [
        {
          "id": "...",
          "path": "...",
          "project_type": "frontend | backend"
        }
      ]
    }
  }
}
```

从模板的 `project_type` 判断前端或后端，从其所属 repository 读取仓库字段。不得向结果添加资料中不存在的字段。

## 固定成功输出

始终只返回以下结构的合法 JSON 对象：

```json
{
  "frontend": {
    "id": "<catalog.templates[].id>",
    "git_url": "<catalog.repositories[...].git_url>",
    "default_branch": "<catalog.repositories[...].default_branch>",
    "path": "<catalog.templates[].path>",
    "reason": "<基于需求的选择理由>"
  },
  "backend": {
    "id": "<catalog.templates[].id>",
    "git_url": "<catalog.repositories[...].git_url>",
    "default_branch": "<catalog.repositories[...].default_branch>",
    "path": "<catalog.templates[].path>",
    "reason": "<基于需求的选择理由>"
  }
}
```

明确不需要某一端时，对应值为 `null`：

```json
{
  "frontend": null,
  "backend": {
    "id": "...",
    "git_url": "...",
    "default_branch": "...",
    "path": "...",
    "reason": "..."
  }
}
```

## 固定错误合同

资料缺失、无法读取、没有匹配模板、必须自建项目，或需求不足以在候选中作出选择时，不输出部分结果或猜测，直接返回：

```json
{
  "error": "无法根据当前选型参考资料完成基础项目选型：<具体原因>"
}
```

错误对象只表示选型未完成，不得与成功字段混合。
