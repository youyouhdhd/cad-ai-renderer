# Reproducibility and Data Handling / 可复现性与数据处理

## English

### Two different kinds of reproducibility

This project separates:

1. **Deterministic geometry evidence:** conversion, camera grids, auxiliary maps, manifests, and local diagnostics should be repeatable for the same inputs, configuration, and dependency environment.
2. **Generated beauty images:** host image-generation output is probabilistic and host-dependent. Candidate images, prompts, and model versions may not reproduce pixel-for-pixel.

The repository promises the first contract and documents the boundary of the second; it does not claim that a generated image is a CAD verification artifact.

### Portable run records

A shareable run should contain:

- the source model filename and a SHA-256 hash;
- sanitized relative paths;
- the selected converter and geometry settings;
- camera plan and render dimensions;
- contract ID/revision, component hashes, and frozen-field consistency result;
- view-grid, candidate-anchor, and final-anchor dimensions plus nonblank checks;
- candidate IDs, native pixel report, and visual-QA decision;
- final-master native size, exact delivered size, resampled/upscaled flags, and final-QC gates;
- final report and known limitations.

Do not copy raw `run_manifest.json`, `host_handoff.json`, or `resolved_project.yaml` from a workstation without reviewing them. They may contain absolute paths, temporary host paths, or private prompt content.

### Example policy

The checked-in example is intentionally curated:

- the model is the supplied public-domain sample described in `examples/steam-controller-2026/THIRD_PARTY_NOTICES.md`;
- images are representative outputs rather than a full raw run;
- auxiliary maps are copied without the original workstation manifests;
- `manifest.json` uses repository-relative paths and records hashes;
- no cache, virtual environment, or host credential is part of the example.

### Data review checklist

Before publishing a new example:

1. Inspect CAD header entities and embedded author/organization fields.
2. Inspect image EXIF/text chunks and visually check the whole frame.
3. Search text and binary strings for emails, tokens, private-key markers, usernames, and workstation paths.
4. Remove or rewrite absolute paths to relative paths.
5. Record source URL, license, retrieval/check date, and file hashes.
6. Keep third-party assets outside the repository's MIT code-license claim.

## 中文

### 两种不同的可复现性

本项目把以下两件事分开：

1. **确定性几何证据：** 对相同输入、配置和依赖环境，转换、相机网格、辅助图、清单和本地诊断应尽量重复。
2. **生成式商业效果图：** 宿主官方生图输出具有概率性且依赖宿主环境；候选图、提示词和模型版本不保证逐像素复现。

仓库承诺第一种合同，并明确记录第二种边界；生成图不是 CAD 验证工件。

### 可迁移运行记录

可分享的运行记录应包含：

- 源模型文件名和 SHA-256；
- 脱敏后的相对路径；
- 使用的转换器与几何设置；
- 相机规划与渲染尺寸；
- 合同 ID/revision、组件哈希和冻结字段一致性结果；
- 相机网格、候选锚点、最终锚点尺寸与非空检查；
- 候选 ID、原生像素报告与视觉 QA 决定；
- 最终母图原生尺寸、精确交付尺寸、重采样/放大标记和最终 QC 门禁；
- 最终报告和已知局限。

不要未经审查就复制工作站生成的 `run_manifest.json`、`host_handoff.json` 或 `resolved_project.yaml`。它们可能含有绝对路径、宿主临时路径或私有提示词。

### 示例策略

仓库中的示例经过刻意筛选：

- 模型是 `examples/steam-controller-2026/THIRD_PARTY_NOTICES.md` 中说明的公共领域样例；
- 图片是代表性输出，不是完整原始运行目录；
- 辅助图不携带原工作站清单；
- `manifest.json` 只使用仓库相对路径并记录哈希；
- 不包含缓存、虚拟环境或宿主凭据。

### 数据审查清单

发布新示例前：

1. 检查 CAD 文件头以及内嵌的作者/组织字段。
2. 检查图片 EXIF/文本块，并目视检查整张图片。
3. 对文本和二进制字符串搜索邮箱、令牌、私钥标记、用户名和工作站路径。
4. 将绝对路径删除或改写为相对路径。
5. 记录来源 URL、许可、获取/检查日期和文件哈希。
6. 将第三方资产明确排除在仓库 MIT 代码许可之外。
