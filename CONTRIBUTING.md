# Contributing / 贡献指南

## English

Thank you for contributing. This project has two contracts: deterministic CAD evidence must be reproducible, while beauty-image generation remains a host capability and must not be hidden inside the bundled scripts.

### Before you start

1. Read [README.md](README.md), [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), and [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md).
2. Check existing issues and avoid duplicating an open proposal.
3. Keep changes focused. Separate code, documentation, and example-asset changes when practical.
4. Do not add credentials, personal contact details, workstation paths, private CAD, or unreviewed generated handoff logs.

### Development rules

- Run Python through `scripts/run.py` for CAD operations.
- Preserve the model-neutral host boundary: do not hard-code a model ID, raw image API endpoint, or API-key requirement.
- Keep geometry evidence deterministic and document any tolerance, camera, or conversion change.
- Use repository-relative paths in fixtures, examples, and JSON manifests.
- Do not turn a local diagnostic score into an automatic final-selection authority.
- Add or update tests when changing discovery, conversion, auxiliary rendering, candidate staging, or finalization behavior.

### Pull requests

Every pull request should explain:

- what changed and why;
- which commands or tests were run;
- whether output contracts or schemas changed;
- whether an example asset is original, public-domain, or third-party;
- any known limitation or follow-up work.

Keep reviewable generated artifacts small. Prefer a representative image and a sanitized manifest over an entire workstation run directory.

## 中文

感谢贡献。本项目有两个边界：确定性的 CAD 几何证据必须可复现；商业效果图生成属于宿主能力，不应隐藏在本仓库脚本内部。

### 开始前

1. 阅读 [README.zh-CN.md](README.zh-CN.md)、[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) 和 [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)。
2. 先检查现有 Issue，避免重复提交已有提案。
3. 保持改动聚焦；条件允许时，将代码、文档和示例资产拆开提交。
4. 不要加入凭据、个人联系方式、工作站路径、私有 CAD 或未经审查的生图交接日志。

### 开发约束

- CAD 操作统一通过 `scripts/run.py` 使用隔离环境。
- 保持模型中立的宿主边界：不得硬编码模型 ID、原始生图 API 地址或 API Key 要求。
- 几何证据应保持确定性；修改容差、相机或转换逻辑时必须记录原因。
- Fixture、示例和 JSON 清单只使用仓库相对路径。
- 不要把本地诊断分数升级为自动最终选图权威。
- 修改发现、转换、辅助通道、候选暂存或定稿逻辑时，请补充或更新测试。

### Pull Request 要求

每个 PR 应说明：

- 修改了什么、为什么修改；
- 执行过哪些命令或测试；
- 输出合同或 Schema 是否变化；
- 示例资产是原创、公共领域还是第三方材料；
- 已知局限和后续工作。

生成的工件应保持便于审查。优先提交一张代表性图片和脱敏清单，不要直接提交整个工作站运行目录。
