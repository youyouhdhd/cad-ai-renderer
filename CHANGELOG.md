# Changelog / 变更记录

This file follows a lightweight Keep a Changelog style. / 本文件采用简化的 Keep a Changelog 风格。

## [Unreleased] / 未发布

### Changed / 变更

- Upgraded the pipeline to contract version 3.0: structured geometry/scene/output contracts now compile into a hash-validated frozen render contract, while prompts are non-authoritative projections. / 管线升级为合同版本 3.0：结构化几何、场景和输出合同会编译成带哈希校验的冻结渲染合同，Prompt 仅作为非权威投影。
- Separated requested native generation size from exact final delivery pixels, added candidate/final resolution reports, and introduced explicit native/resampled/upscaled completion states. / 正式拆分请求原生生成尺寸与最终精确交付像素，增加候选/最终分辨率报告及原生、重采样、放大完成状态。
- Added stage-aware view-grid/candidate/final CAD anchors, one frozen final-refinement master, final QC, and geometry/resolution/visual/contract gates before `final/best.*` can exist. / 增加分阶段相机网格、候选和最终 CAD 锚点，以及一次冻结的最终精修母图与最终 QC；只有几何、分辨率、视觉和合同门禁完成后才允许生成 `final/best.*`。
- Converted strict retries into one revisioned retry delta with exact failures and immutable camera/geometry/output fields, and fixed the concurrent bootstrap-lock owner-file race. / 将严格重试改为带 revision 的单次增量补丁，要求明确失败项并冻结相机、几何和输出字段，同时修复并发启动时锁目录与 owner 文件之间的竞态。
- Clarified the public positioning as a reusable Codex Skill with GPT Image 2 as a primary reference target while keeping the host image-generation boundary model-neutral. / 明确项目是可复用的 Codex Skill，并将 GPT Image 2 定义为主要参考目标，同时保持宿主生图交接的模型中立性。
- Added a Codex invocation guide, a bilingual roadmap, and stronger `agents/openai.yaml` metadata with an explicit `$cad-ai-renderer` default prompt. / 增加 Codex 调用指南、双语路线图，并强化 `agents/openai.yaml` 元数据，默认提示词显式使用 `$cad-ai-renderer`。
- Documented the reference-target boundary in the image-generation and architecture guidance. / 在生图与架构文档中记录参考目标边界。
- Separated broad fourteen-view deterministic reference coverage from the final candidate budget: unspecified viewpoints now produce exactly four final candidates (front, back, left, and one upper axonometric), while an explicit view keeps all final candidates in that view. / 将十四视角确定性参考覆盖与最终候选预算分离：未指定视角时最终严格生成四张（前、后、左、一个上方轴测），指定视角时所有最终候选都使用该视角。
- Added the editable, user-confirmed `planning/render_plan.json` gate. It preserves user-specified view priority, supports an explicit quantity for that view, and prevents preparation from starting until the plan is confirmed. / 增加可编辑且需用户确认的 `planning/render_plan.json` 门控；它保持用户指定视角优先，支持该视角的明确数量，并在确认前阻止正式准备流程。
- Defaulted the host handoff to the official Codex `$imagegen` Skill with a 4K, high-quality, high-detail target and truthful actual-resolution reporting when the host cannot expose exact 4K controls. / 默认将宿主交接指向 Codex 官方 `$imagegen` Skill，目标为 4K、高质量、高细节；宿主不能精确控制 4K 时如实记录实际分辨率。

## [0.1.0] - 2026-08-18

### Added / 新增

- Published the CAD AI Renderer skill bundle and managed-environment launcher.
- Added bilingual public documentation, architecture notes, development guidance, security policy, contribution guide, and issue templates.
- Added a sanitized Steam Controller STEP example with representative beauty renders and deterministic auxiliary maps.
- Added a repository-relative example manifest and metadata/privacy checks for CI.

### Notes / 说明

- The host-only official image-generation capability is intentionally not bundled as a raw API client.
- The example CAD model is separately licensed and is not covered by the repository MIT code license.
