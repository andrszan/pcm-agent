# Third-Party Notices

本仓库中的第一方内容未授予统一的开源许可。下列目录包含经筛选保留的第三方参考资源，其使用与再分发继续遵循对应上游许可证。

## tweakcn Themes Registry

- 本地路径：`.claude/skills/tailwind-theme/assets/tweakcn/`
- 上游项目：<https://github.com/jnsahaj/tweakcn>
- 发布数据源：<https://tweakcn.com/r/themes/registry.json>
- 许可证：Apache License 2.0
- 本地许可证：[`LICENSE`](.claude/skills/tailwind-theme/assets/tweakcn/LICENSE)
- 说明：主题数据来自公开 registry；本仓将聚合数据拆分为逐主题 JSON，并维护用于候选筛选的本地目录和校验脚本。具体抓取时间、哈希和处理方式见该目录 README。

## shadcn/ui Layout References

- 本地路径：`.claude/skills/ui-ux-framework/assets/layout-source-snapshots/shadcn-ui/`
- 上游项目：<https://github.com/shadcn-ui/ui>
- 上游 Blocks：<https://ui.shadcn.com/blocks>
- 许可证：MIT License
- 本地许可证：[`LICENSE.md`](.claude/skills/ui-ux-framework/assets/layout-source-snapshots/shadcn-ui/LICENSE.md)
- 说明：本地内容是由公开 shadcn/ui Blocks 派生的布局参考，不是独立模板或可直接运行的组件库；目录 README 记录了 Block 对应关系、缺失依赖和使用边界。
