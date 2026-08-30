# 媒体测试 Fixture 维护

本目录是 `media-assets` 随附的受跟踪稳定测试媒体入口。它用于保存经确认的上传、预览、格式校验和失败状态测试文件；不是产品静态资源目录、对象存储模拟器，也不是可对外分发的素材库。

当前目录随附一组小而稳定的基础 fixture，实际条目和校验信息记录在 `manifest.json`；`manifest.template.json` 继续作为空清单结构参考。

## 当前集合

- `image-valid-landscape.jpg`：有效横向 JPG，用于上传、预览、缩略图、裁切和方向检查；
- `image-valid-square-alpha.png`：有效方形透明 PNG，用于透明和半透明边缘检查；
- `image-valid-portrait.webp`：有效纵向 WebP，用于纵向容器和上下方向检查；
- `image-invalid-extension.txt`：非媒体扩展名拒绝输入；
- `image-invalid-signature.jpg`：使用 JPG 扩展名但实际为文本的文件签名拒绝输入；
- `image-corrupt-truncated.jpg`：保留 JPEG 签名但无法解码的损坏输入。

这些图片采用非对称构图、明确的四角或上下视觉差异、渐变、锐利边缘及少量自然纹理，便于发现旋转、镜像、裁切、透明通道和压缩异常。它们不包含人物、真实用户数据、文字、Logo、商标或水印。

## 何时添加

只在已有项目或测试出现当前集合无法覆盖的明确行为时添加，例如 EXIF 方向、动画保留、SVG 清洗、特定编解码格式或视频上传。不同项目的体积限制并不统一，大小边界文件应由目标项目按真实阈值确定性生成，不在共享目录预存含义不明的大型二进制文件。

不要为了“以后可能有用”批量收集图片或视频；不要在每次测试时重新联网搜索或生成 fixture。

## 添加步骤

1. 确认文件只包含可用于测试的内容，不含个人照片、真实用户数据、秘密、客户私有素材或不适合公开提交的信息。
2. 选择稳定、语义中性的文件名，例如 `image-valid-landscape.jpg`、`image-invalid-extension.txt`、`image-corrupt-truncated.jpg`。文件名表达测试行为，不表达一次性的 Provider URL。
3. 保持文件足够小；大小边界测试应优先由目标项目按真实阈值确定性生成，只有形成稳定的共享限制合同后才考虑增加对应 fixture。
4. 校验文件真实类型、尺寸和用途，并使用当前环境可用的 SHA-256 工具计算哈希；不要把 API key、Cookie、完整请求响应或临时下载 URL 写进任何文件。
5. 在 `manifest.json` 中记录稳定 ID、相对路径、MIME、尺寸或时长、哈希、测试用途、预期结果和状态。来源、许可、模型、提示词摘要或替换依据仅在维护者确有需要时作为最小内部记录，不用于产品 UI 展示。
6. 检查 Git diff，确认只加入预期文件；随后用目标项目真实上传路径验证 fixture。

## 清单约定

`manifest.template.json` 只提供空结构，`manifest.json` 记录本目录当前受维护的实际资源。每个资源至少应能回答：它是什么、位于哪里、用来测试什么、预期被接受还是拒绝、是否仍有效、文件是否被意外替换。

可按需要使用以下字段：

```json
{
  "id": "image-valid-landscape",
  "relativePath": "image-valid-landscape.jpg",
  "mimeType": "image/jpeg",
  "sizeBytes": 169177,
  "width": 1200,
  "height": 800,
  "sha256": "…",
  "purpose": "正常图片上传与预览",
  "expectedResult": "accepted",
  "status": "approved",
  "source": {
    "origin": "external | generated | internal",
    "providerId": "可选的受控 Provider ID",
    "reference": "可选的稳定资源页或内部说明",
    "licenseNote": "可选的维护说明",
    "model": "可选的生成模型",
    "promptSummary": "可选的脱敏摘要"
  }
}
```

`source` 是可选的维护信息。`origin` 只描述来源类别；`providerId` 在确有追溯需要时引用当前受控 Provider catalog 中的稳定 ID，不构成在线重建依赖。不要记录临时 CDN 下载链接、完整敏感提示词、原始 API 响应、Cookie 或任何凭据。

## 修改、替换与复制

- 需要改变文件行为、格式、体积或语义时，新增 fixture 或显式更新清单；不要静默用不同文件覆盖同一路径。
- 删除或替换前，先检查哪些目标项目或测试引用该文件，再同步调整引用和清单状态。
- 仅作工作区本地验证且本目录路径稳定可访问时，可以直接使用这里的 fixture，无需为了当次验证复制文件。
- 只有目标产品的自动化测试需要将 fixture 纳入其独立仓库或 CI 输入时，才由负责该测试的 Agent 将所需最小文件复制到项目已有测试资源目录；目录名称遵循目标项目约定，不强制使用 `tests/fixtures/`。
- 产品运行时代码不得依赖本 Skill 的内部路径；产品专属静态图片应进入目标项目自己的资产目录，而不是回写到此处。
- 视频 fixture 仅在明确需要视频上传或播放测试时维护，并同时说明体积、时长和测试目标。
