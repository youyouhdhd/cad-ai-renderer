# Changelog / 变更记录

This file follows a lightweight Keep a Changelog style. / 本文件采用简化的 Keep a Changelog 风格。

## [Unreleased] / 未发布

### Changed / 变更

- Clarified the public positioning as a reusable Codex Skill with GPT Image 2 as a primary reference target while keeping the host image-generation boundary model-neutral. / 明确项目是可复用的 Codex Skill，并将 GPT Image 2 定义为主要参考目标，同时保持宿主生图交接的模型中立性。
- Added a Codex invocation guide, a bilingual roadmap, and stronger `agents/openai.yaml` metadata with an explicit `$cad-ai-renderer` default prompt. / 增加 Codex 调用指南、双语路线图，并强化 `agents/openai.yaml` 元数据，默认提示词显式使用 `$cad-ai-renderer`。
- Documented the reference-target boundary in the image-generation and architecture guidance. / 在生图与架构文档中记录参考目标边界。

## [0.1.0] - 2026-08-18

### Added / 新增

- Published the CAD AI Renderer skill bundle and managed-environment launcher.
- Added bilingual public documentation, architecture notes, development guidance, security policy, contribution guide, and issue templates.
- Added a sanitized Steam Controller STEP example with representative beauty renders and deterministic auxiliary maps.
- Added a repository-relative example manifest and metadata/privacy checks for CI.

### Notes / 说明

- The host-only official image-generation capability is intentionally not bundled as a raw API client.
- The example CAD model is separately licensed and is not covered by the repository MIT code license.
