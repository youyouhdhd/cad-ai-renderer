# Security Policy / 安全策略

## English

### Scope

Report vulnerabilities in the launcher, CAD conversion, auxiliary rendering, candidate staging, or manifest handling. Do not include real credentials, private CAD, personal data, or private host prompts in a public issue.

### Reporting

Use GitHub Security Advisories or another private repository reporting channel when available. If the repository has no private channel, open a minimal issue that says a private follow-up is needed; do not attach secrets or exploit details.

### Release hygiene

- Never commit `.env`, access tokens, private keys, cookies, or credential files.
- Review generated JSON and Markdown for absolute workstation paths before publishing.
- Treat model files, images, and embedded metadata as data that may require a separate license review.
- Keep the official image-generation boundary outside raw API clients in this repository.

## 中文

### 范围

可报告启动器、CAD 转换、辅助渲染、候选暂存或清单处理中的漏洞。不要在公开 Issue 中放入真实凭据、私有 CAD、个人信息或宿主私有提示词。

### 报告方式

如果可用，请使用 GitHub Security Advisories 或其他仓库私密报告渠道。如果仓库没有私密渠道，只创建一条说明“需要私下跟进”的最小 Issue，不要附加密钥或完整利用细节。

### 发布前检查

- 绝不提交 `.env`、访问令牌、私钥、Cookie 或凭据文件。
- 发布前检查生成的 JSON 和 Markdown，删除工作站绝对路径。
- 模型、图片和内嵌元数据都可能需要单独进行权利审查。
- 保持官方生图边界在本仓库的原始 API 客户端之外。
