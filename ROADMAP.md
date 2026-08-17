# Roadmap / 路线图

This roadmap records intended areas of work, not promised release dates. Each item should become a real issue or pull request before it is presented as completed.

本路线图记录计划中的工作方向，不承诺具体发布日期。只有形成真实 Issue 或 Pull Request 后，项目才会把条目标记为已完成。

## v0.1.x — Reliability / 可靠性

- Expand cross-platform bootstrap validation for Windows and Linux.
- Improve STEP assembly and leaf-part preservation diagnostics.
- Add more geometry-regression fixtures for holes, seams, openings, and part counts.
- Harden repository-relative path and manifest handling.
- Improve interrupted-run recovery and error messages.

中文：

- 扩展 Windows 与 Linux 的启动器验证。
- 改进 STEP 装配体和叶子部件保留诊断。
- 为孔洞、接缝、开口和部件数量增加更多几何回归 Fixture。
- 强化仓库相对路径和清单处理。
- 改进中断恢复和错误信息。

## v0.2 — Image-generation evaluation / 生图评估

- Build a public CAD-to-image evaluation set using assets with clear redistribution notices.
- Compare geometry-evidence and prompt/handoff variants against the same CAD views.
- Add structured visual-QA examples and repeatable review criteria.
- Track silhouette, topology, holes, seams, visible-part count, and part-placement fidelity.
- Document a reproducible evaluation method for GPT Image 2 and other host-supported image capabilities.

中文：

- 使用具有清晰再分发声明的资产建立公开 CAD-to-image 评估集。
- 在相同 CAD 视角下比较几何证据与提示词/交接方案的差异。
- 增加结构化视觉 QA 示例和可重复的审查标准。
- 记录轮廓、拓扑、孔洞、接缝、可见部件数量和部件位置保真度。
- 为 GPT Image 2 及其他宿主支持的生图能力记录可复现的评估方法。

## v0.3 — Codex Skill experience / Codex Skill 体验

- Improve Skill discovery and invocation metadata.
- Add more end-to-end Codex Skill examples.
- Improve installation and first-run diagnostics.
- Add reusable product-rendering presets without locking the image model.
- Expand contribution fixtures and regression tests.

中文：

- 改进 Skill 发现和调用元数据。
- 增加更多端到端 Codex Skill 示例。
- 改进安装和首次运行诊断。
- 在不锁定生图模型的前提下增加可复用产品渲染预设。
- 扩展贡献用 Fixture 和回归测试。

## Future / 后续方向

- Additional CAD import paths and assembly-aware evidence generation.
- Optional local geometry-control integrations.
- Larger open evaluation datasets with explicit asset rights.
- Better comparison reports for deterministic evidence and host visual QA.

中文：

- 增加 CAD 导入路径，并生成更理解装配体的几何证据。
- 提供可选的本地几何控制集成。
- 建立更大的、具有明确资产权利说明的开放评估数据集。
- 改进确定性证据与宿主视觉 QA 的对照报告。
