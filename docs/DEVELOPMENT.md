# Development Guide / 开发指南

## English

### Prerequisites

- 64-bit CPython 3.10–3.13; 3.12 is preferred.
- Git.
- Network access for the first isolated dependency bootstrap, unless the host can provide a verified package environment.
- Optional FreeCAD for a fallback STEP export path.
- Optional local ComfyUI only when a geometry guard is explicitly configured.

### Environment workflow

Always use the launcher from the repository root:

```powershell
python scripts/run.py bootstrap
python scripts/run.py preflight
```

Useful overrides:

```powershell
$env:CAD_AI_RENDERER_VENV = "D:\venvs\cad-ai-renderer"
python scripts/run.py --venv-dir $env:CAD_AI_RENDERER_VENV preflight
```

Use `--no-install` when the environment must not be changed. Use `--isolated-only` when host-linked fallback is not acceptable. Never run `pip install -r requirements.txt` against a global interpreter as a substitute for the launcher.

### Fast static checks

The public CI intentionally avoids installing the heavy CAD stack. It checks Python syntax, JSON/YAML examples, sensitive-path patterns, and repository hygiene. Run equivalent checks locally:

```powershell
python -c "import ast; from pathlib import Path; [ast.parse(p.read_text(encoding='utf-8'), filename=str(p)) for p in Path('scripts').glob('*.py')]; print('python syntax: OK')"
python -c "import json; from pathlib import Path; [json.loads(p.read_text(encoding='utf-8')) for p in Path('.').rglob('*.json') if '__pycache__' not in str(p)]; print('json: OK')"
```

### Functional validation

After bootstrapping the managed environment:

```powershell
python scripts/run.py self-test --output .\runs\self-test
```

The self-test deliberately creates temporary fixtures and validates the deterministic side of the pipeline. It does not invoke a host-only official image-generation tool.

### Safe code changes

- Keep public functions and manifest fields stable unless the change includes a schema note and test update.
- Prefer `pathlib.Path` and run-relative paths over string-built absolute paths.
- Use atomic writes for metadata that may be read after interruption.
- Keep Windows-safe names and long-path behavior in mind.
- Add an explicit failure message when a tool is missing; do not silently downgrade geometry evidence.
- Preserve the bounded retry policy.
- Do not add raw HTTP image-generation clients or ask users for credentials.

### Documentation changes

When behavior changes, update the closest source-of-truth document:

- installation/bootstrap → `references/INSTALL.md`;
- input roles → `references/ATTACHMENTS.md`;
- schemas and handoff → `references/PIPELINE.md` and `references/PROJECT_SCHEMA.md`;
- operational recovery → `references/TROUBLESHOOTING.md`;
- public contract → `README.md` and `README.zh-CN.md`;
- architectural trade-offs → `docs/ARCHITECTURE.md`.

### Release checklist

1. Run static checks and the managed-environment self-test.
2. Inspect the diff and tracked file list.
3. Search for secrets, emails, user directories, absolute paths, and generated caches.
4. Review every example model/image license and notice.
5. Confirm `final/report.md` or sample manifests do not leak a workstation path.
6. Update `CHANGELOG.md`, `CITATION.cff`, and version references when appropriate.
7. Tag or publish only after the repository is clean and the release scope is clear.

## 中文

### 前置条件

- 64 位 CPython 3.10–3.13，优先 3.12。
- Git。
- 首次安装隔离依赖时需要网络，除非宿主能提供已经验证过的包环境。
- 可选 FreeCAD，用于 STEP 回退导出。
- 仅在显式配置几何守卫时使用本地 ComfyUI。

### 环境流程

始终在仓库根目录使用启动器：

```powershell
python scripts/run.py bootstrap
python scripts/run.py preflight
```

可通过环境变量指定环境目录：

```powershell
$env:CAD_AI_RENDERER_VENV = "D:\venvs\cad-ai-renderer"
python scripts/run.py --venv-dir $env:CAD_AI_RENDERER_VENV preflight
```

如果不允许环境发生变化，使用 `--no-install`；如果不能接受宿主包回退，使用 `--isolated-only`。不要把 `pip install -r requirements.txt` 直接对着全局解释器执行，以此替代启动器。

### 快速静态检查

公开 CI 有意不安装重量级 CAD 栈，而是检查 Python 语法、JSON/YAML 示例、敏感路径模式和仓库卫生。可以在本地运行等价检查：

```powershell
python -c "import ast; from pathlib import Path; [ast.parse(p.read_text(encoding='utf-8'), filename=str(p)) for p in Path('scripts').glob('*.py')]; print('python syntax: OK')"
python -c "import json; from pathlib import Path; [json.loads(p.read_text(encoding='utf-8')) for p in Path('.').rglob('*.json') if '__pycache__' not in str(p)]; print('json: OK')"
```

### 功能验证

初始化托管环境后运行：

```powershell
python scripts/run.py self-test --output .\runs\self-test
```

self-test 会创建临时 Fixture，验证流程的确定性部分；它不会调用宿主专属的官方生图工具。

### 安全修改代码

- 除非同时更新 Schema 说明和测试，否则保持公开函数与清单字段稳定。
- 优先使用 `pathlib.Path` 和运行目录相对路径，不要拼接绝对路径字符串。
- 对可能在中断后被读取的元数据使用原子写入。
- 注意 Windows 保留名称和长路径行为。
- 工具不可用时输出明确错误，不要静默降低几何证据质量。
- 保持重试上限。
- 不得增加原始生图 HTTP 客户端或要求用户提供凭据。

### 文档修改

行为变化时，更新最近的事实来源：

- 安装/启动 → `references/INSTALL.md`；
- 输入角色 → `references/ATTACHMENTS.md`；
- Schema 与交接 → `references/PIPELINE.md`、`references/PROJECT_SCHEMA.md`；
- 运维恢复 → `references/TROUBLESHOOTING.md`；
- 公开合同 → `README.md`、`README.zh-CN.md`；
- 架构取舍 → `docs/ARCHITECTURE.md`。

### 发布清单

1. 执行静态检查和隔离环境 self-test。
2. 检查 diff 与已跟踪文件列表。
3. 搜索密钥、邮箱、用户目录、绝对路径和生成缓存。
4. 检查每个示例模型/图片的许可和声明。
5. 确认 `final/report.md` 或示例清单没有泄露工作站路径。
6. 适时更新 `CHANGELOG.md`、`CITATION.cff` 和版本信息。
7. 仓库干净且发布范围明确后，再打 Tag 或发布。
