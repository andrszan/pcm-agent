# GPT Image 2 Prompt Gallery Index

本索引是工作区运行快照保留的完整案例 Prompt 目录。不要默认加载所有分类；只选最相关的一类（混合任务最多选择相邻的 2–3 类），编写提示词时按需结合 `craft.md`。

每个 `gallery-*.md` 分类文件保留具体 Prompt、参数、元数据以及作者和来源标记。本快照不打包上游案例图片，已移除相应本地图片路径和预览标签；不要尝试读取缺失图片或自动下载整套预览。需要查看原图时可访问上游仓库，正常使用案例 Prompt 不依赖原图。

## Category files

| Category | File | Range | Count |
|---|---|---:|---:|
| 🎌 Anime & Manga | [`gallery-anime-and-manga.md`](gallery-anime-and-manga.md) | No. 1–12 | 12 |
| 🎮 Gaming | [`gallery-gaming.md`](gallery-gaming.md) | No. 13–22 | 10 |
| 🤖 Retro & Cyberpunk | [`gallery-retro-and-cyberpunk.md`](gallery-retro-and-cyberpunk.md) | No. 23–25 | 3 |
| 🎬 Cinematic & Animation | [`gallery-cinematic-and-animation.md`](gallery-cinematic-and-animation.md) | No. 26–30 | 5 |
| 👤 Character Design | [`gallery-character-design.md`](gallery-character-design.md) | No. 31–32 | 2 |
| 📝 Typography & Posters | [`gallery-typography-and-posters.md`](gallery-typography-and-posters.md) | No. 33–45 | 13 |
| 🎨 Illustration | [`gallery-illustration.md`](gallery-illustration.md) | No. 46–47 | 2 |
| 💧 Watercolor | [`gallery-watercolor.md`](gallery-watercolor.md) | No. 48–49 | 2 |
| 🖌️ Ink & Chinese | [`gallery-ink-and-chinese.md`](gallery-ink-and-chinese.md) | No. 50–51 | 2 |
| 🕹️ Pixel Art | [`gallery-pixel-art.md`](gallery-pixel-art.md) | No. 52–53 | 2 |
| 📐 Isometric | [`gallery-isometric.md`](gallery-isometric.md) | No. 54–55 | 2 |
| 📦 Product & Food | [`gallery-product-and-food.md`](gallery-product-and-food.md) | No. 56–59 | 4 |
| 🧩 Brand Systems & Identity | [`gallery-brand-systems-and-identity.md`](gallery-brand-systems-and-identity.md) | No. 60–62 | 3 |
| 📷 Photography | [`gallery-photography.md`](gallery-photography.md) | No. 63–66 | 4 |
| 📊 Infographics & Field Guides | [`gallery-infographics-and-field-guides.md`](gallery-infographics-and-field-guides.md) | No. 67–74 | 8 |
| 📚 Research Paper Figures | [`gallery-research-paper-figures.md`](gallery-research-paper-figures.md) | No. 75–95 | 21 |
| 🏢 Official OpenAI Cookbook Examples | [`gallery-official-openai-cookbook-examples.md`](gallery-official-openai-cookbook-examples.md) | No. 96–99 | 4 |
| ✨ Edit Endpoint Showcase | [`gallery-edit-endpoint-showcase.md`](gallery-edit-endpoint-showcase.md) | No. 100–101 | 2 |
| 📱 UI/UX Mockups | [`gallery-ui-ux-mockups.md`](gallery-ui-ux-mockups.md) | No. 102–106 | 5 |
| 📊 Data Visualization | [`gallery-data-visualization.md`](gallery-data-visualization.md) | No. 107–111 | 5 |
| ⚙️ Technical Illustration | [`gallery-technical-illustration.md`](gallery-technical-illustration.md) | No. 112–116 | 5 |
| 🏛️ Architecture & Interior | [`gallery-architecture-and-interior.md`](gallery-architecture-and-interior.md) | No. 117–121 | 5 |
| 🔬 Scientific & Educational | [`gallery-scientific-and-educational.md`](gallery-scientific-and-educational.md) | No. 122–128 | 7 |
| 👗 Fashion Editorial | [`gallery-fashion-editorial.md`](gallery-fashion-editorial.md) | No. 129–135 | 7 |
| 🎨 Fine Art Painting | [`gallery-fine-art-painting.md`](gallery-fine-art-painting.md) | No. 136–140 | 5 |
| ✏️ More Illustration Styles | [`gallery-more-illustration-styles.md`](gallery-more-illustration-styles.md) | No. 141–146 | 6 |
| 🎥 Cinematic Film References | [`gallery-cinematic-film-references.md`](gallery-cinematic-film-references.md) | No. 147–152 | 6 |
| 💄 Beauty & Lifestyle | [`gallery-beauty-and-lifestyle.md`](gallery-beauty-and-lifestyle.md) | No. 153–154 | 2 |
| 🎟️ Events & Experience | [`gallery-events-and-experience.md`](gallery-events-and-experience.md) | No. 155–156 | 2 |
| 🖋️ Tattoo Design | [`gallery-tattoo-design.md`](gallery-tattoo-design.md) | No. 157–160 | 4 |
| 🖥️ Screen Photography | [`gallery-screen-photography.md`](gallery-screen-photography.md) | No. 161–162 | 2 |

## Loading policy

- Start here to choose a category; do not read the whole Reference Gallery into context.
- Read `craft.md` for general prompt-writing principles.
- Read exactly one `gallery-*.md` category file for normal requests; read two or three only when the user asks for hybrid styles.
- Preserve `Curated` versus `Author + Source` metadata when adapting examples into README/gallery entries.
- If entries move, update both this index and the corresponding category file in the same PR. Promote to README only when the example belongs in the selected visual showcase.
