# Changelog / 变更记录

This file follows a lightweight Keep a Changelog style. / 本文件采用简化的 Keep a Changelog 风格。

## [Unreleased] / 未发布

### Changed / 变更

- No unreleased changes yet. / 暂无未发布变更。

## [0.2.0] - 2026-08-18

### Added / 新增

- Added a confirmed, editable `planning/render_plan.json` gate that preserves explicit user view priority and final candidate budgets. / 增加需用户确认的可编辑 `planning/render_plan.json` 门控，保持用户明确指定的视角优先级和最终候选预算。
- Added stage-aware CAD anchors for view-grid selection, candidate generation, and final refinement. / 增加用于视角网格选择、候选生成和最终精修的分阶段 CAD 锚点。
- Added structured geometry, scene, output, and hash-validated frozen render contracts. / 增加结构化几何、场景、输出合同以及带哈希校验的冻结渲染合同。
- Added one frozen final-refinement master, final QC, and geometry, resolution, visual-quality, and contract-consistency gates before final delivery. / 增加一次冻结的最终精修母图、最终 QC，以及交付前的几何、分辨率、视觉质量和合同一致性门禁。
- Added explicit candidate and final resolution reports that distinguish native generation from exact resampled or upscaled delivery. / 增加候选和最终分辨率报告，明确区分原生生成与精确重采样/放大交付。
- Added bounded, revisioned retry deltas with immutable camera, geometry, reference, aspect-ratio, and output fields. / 增加有上限且带 revision 的重试增量，并冻结相机、几何、参考、宽高比和输出字段。

### Changed / 变更

- Separated broad fourteen-view deterministic CAD reference coverage from the final candidate budget; explicit multi-view plans now generate only the listed final views. / 将十四视角确定性 CAD 参考覆盖与最终候选预算分离；明确的多视角计划现在只生成计划中列出的最终视角。
- Defaulted host handoff to the official Codex `$imagegen` Skill while keeping the image-generation boundary model-neutral and raw-API-free. / 默认将宿主交接指向 Codex 官方 `$imagegen` Skill，同时保持模型中立且不包含原始 API 调用。
- Updated bilingual documentation, architecture guidance, reproducibility notes, roadmap, and invocation metadata for the v3.0 contract pipeline. / 更新双语文档、架构说明、可复现性说明、路线图和调用元数据，以覆盖 v3.0 合同管线。

### Fixed / 修复

- Fixed the concurrent bootstrap-lock owner-file race and made managed-environment initialization resumable. / 修复并发启动时锁目录与 owner 文件的竞态，并使托管环境初始化支持恢复。

### Release notes / 发布说明

- Beauty images remain host-generated, probabilistic, and structure-guided; local geometry scores remain diagnostic and do not replace visual QA. / 商业效果图仍由宿主生成，具有概率性并属于结构引导近似；本地几何分数仍是诊断信号，不能替代视觉 QA。

## [0.1.0] - 2026-08-18

### Added / 新增

- Published the CAD AI Renderer skill bundle and managed-environment launcher.
- Added bilingual public documentation, architecture notes, development guidance, security policy, contribution guide, and issue templates.
- Added a sanitized Steam Controller STEP example with representative beauty renders and deterministic auxiliary maps.
- Added a repository-relative example manifest and metadata/privacy checks for CI.

### Notes / 说明

- The host-only official image-generation capability is intentionally not bundled as a raw API client.
- The example CAD model is separately licensed and is not covered by the repository MIT code license.
