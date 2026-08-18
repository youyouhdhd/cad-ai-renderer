# 安装与隔离环境

## 1. 安装 Skill

将打包后的 `skill.zip` 上传到支持自定义 Skill 的 ChatGPT/Codex 环境。Skill 的显示名称为 **CAD AI Renderer**。

最终生图由宿主环境的官方生图 Skill 或工具完成；本包不要求用户配置图像 API Key。

## 2. Python 要求

启动器支持 64 位 CPython 3.10–3.13，并优先选择 Python 3.12。即使当前 shell 的 `python` 指向 3.9 或其他不兼容版本，也不要先手工排查；启动器会自动发现并重新调用兼容解释器。

不要把依赖安装到全局 Python。所有命令统一通过：

```bash
python scripts/run.py <command> ...
```

在新环境中先执行：

```bash
python scripts/run.py bootstrap
```

第一次初始化应给外层 Codex/shell 命令至少 10 分钟超时，因为 CadQuery/OCP 与 VTK 的二进制包较大。启动器会：

1. 自动探测兼容的 64 位 Python，优先 3.12，并在需要时重新启动自身；
2. 在 `~/.cache/cad-ai-renderer/venv` 创建专用虚拟环境；
3. 使用进程锁避免并发安装，自动清理失效或从其他主机复制来的锁，并原子写入安装状态；
4. 在该环境中安装 `requirements.txt` 并运行真实导入探针；
5. 若外层命令被中断，下次执行同一命令时复用已有 venv 和 pip 缓存继续安装，而不是删除重来；
6. 后续运行复用已验证环境，依赖变更时在原环境内同步，只有 Python 不兼容、环境损坏或显式 `--refresh` 才重建。

默认优先使用完全隔离的 pip 安装。在无网络的托管 Codex 环境中，如果当前宿主 Python 已经具备全部依赖，启动器会自动重建一个**独立解释器环境**，并通过 `.pth` 只读复用宿主已安装包。该 `host-linked` 模式不会把依赖安装到全局 Python，也不会修改宿主包。预检报告会显示实际模式。

若 `--venv-dir` 或 `CAD_AI_RENDERER_VENV` 指向一个已经存在、依赖完整的用户 Python/conda 环境，启动器只做导入探针并以 `external` 模式使用它；不会删除、重建或向其中安装包。只有带有 Skill 所有权标记的环境才允许自动重建。


指定用于创建虚拟环境的 Python：

```bash
export CAD_AI_RENDERER_BOOTSTRAP_PYTHON=/absolute/path/to/python3.12
python scripts/run.py bootstrap
```

或：

```bash
python scripts/run.py --bootstrap-python /absolute/path/to/python3.12 bootstrap
```

自定义环境目录：

```bash
export CAD_AI_RENDERER_VENV=/absolute/path/to/cad-ai-renderer-venv
python scripts/run.py preflight
```

或：

```bash
python scripts/run.py --venv-dir /absolute/path/to/venv preflight
```

Windows PowerShell：

```powershell
$env:CAD_AI_RENDERER_VENV = "D:\venvs\cad-ai-renderer"
python scripts/run.py preflight
```

强制完整重建 Skill 所有的环境：

```bash
python scripts/run.py --refresh preflight
```

只使用已有环境、绝不创建或安装：

```bash
python scripts/run.py --no-install preflight
```

强制只接受完全隔离安装、禁止离线宿主包回退：

```bash
python scripts/run.py --isolated-only preflight
```

也可通过环境变量关闭回退：

```bash
export CAD_AI_RENDERER_ALLOW_HOST_PACKAGES=0
```

## 3. 附件式运行

用户通常只需在输入框附上：

- 一个 `model.step`；
- 零张或多张参考图；
- 一句自然语言渲染要求。

Skill 会直接把附件路径传给脚本，不要求用户创建 YAML。

手工演示：

```bash
python scripts/run.py preflight \
  --input ./model.step \
  --input ./reference.jpg \
  --output-dir ./output
```

先生成可编辑渲染计划（这一步不会转换或渲染 CAD）：

```bash
python scripts/run.py plan \
  --input ./model.step \
  --input ./reference.jpg \
  --intent "高端工业产品棚拍，拉丝金属与深色聚合物" \
  --output ./output
```

审查 `./output/planning/render_plan.json`，如有需要修改参考视角或最终候选数量，然后设置
`confirmation.confirmed` 为 `true`。未指定视角时，参考图可以覆盖十四个方向，但最终只生成
四张（前、后、左、一个上方轴测）；指定视角时，候选都使用该视角。

提交已确认计划并生成辅助图：

```bash
python scripts/run.py prepare \
  --input ./model.step \
  --input ./reference.jpg \
  --intent "高端工业产品棚拍，拉丝金属与深色聚合物" \
  --output ./output \
  --plan ./output/planning/render_plan.json
```

正式 Skill 流程会由宿主模型自动分析视角和参考图，并传入 `--camera-plan`、`--reference-roles`、`--render-brief`，用户无须手写这些文件；但确认后的 `render_plan.json` 始终是视角和候选预算的控制面。

## 4. STEP 支持

默认顺序：

```text
CadQuery/OCP 装配导入
  -> CadQuery 单实体导入
  -> FreeCADCmd 兜底
```

CadQuery 主路径尽量保留装配、零件变换和 STEP 颜色。FreeCAD 兜底通过 STL 中转，会损失颜色、装配层级和零件 ID。

## 5. 可选软件

- **FreeCADCmd**：仅作为特殊 STEP 的兜底。
- **Blender**：不是默认依赖；可用于未来的特殊 UV、材质 ID 或复杂离屏渲染扩展。
- **ComfyUI**：仅在一次严格重试前作为深度/边缘几何强化器。

## 6. 验证

```bash
python scripts/run.py self-test --output ./cad-ai-renderer-self-test
```

测试会实际创建 STEP、转换为 GLB、渲染辅助图、进行候选几何打分和收尾，但不会调用宿主的官方生图工具。

## 7. 常见安装问题

### CadQuery 无可用 wheel

先直接重跑 `python scripts/run.py bootstrap`。启动器会跳过不兼容的 Python 3.9，优先寻找 3.12/3.11，并恢复上次未完成的安装。只有自动发现失败时才设置 `CAD_AI_RENDERER_BOOTSTRAP_PYTHON`。若宿主没有兼容解释器或包，可在 conda 环境中预装 CadQuery/OCP 与 VTK，再把 `CAD_AI_RENDERER_VENV` 指向该环境目录；或者安装 FreeCADCmd 作为 STEP 兜底。

### 首次安装被外层命令超时中断

不要删除 `~/.cache/cad-ai-renderer/venv`，也不要手工检查后逐包安装。使用更长的外层命令超时重新执行同一条 `bootstrap` 或业务命令；启动器会识别 `installing` 状态、恢复已写入的 host-link、清理失效锁或迁移时从其他主机带来的锁，并继续已有环境。

### 包索引不可访问

启动器的 pip 尝试使用有限重试和超时。若宿主依赖完整，会自动切换到 `host-linked`；若宿主依赖也不完整，则会明确列出缺失导入项并保留可恢复的环境。不要改为全局 `pip install`。

### VTK 在无显示器服务器上报警

Skill 默认设置 `VTK_DEFAULT_RENDER_WINDOW_OFFSCREEN=1`。只要 PNG 输出存在且非空，部分 X/OpenGL 警告不一定表示失败。EGL/OSMesa 版本的 VTK 通常更安静。

### 隐私

本地 STEP 转换与辅助图生成留在本机。最终生图需要把所选辅助图和参考图交给宿主官方生图能力。发送前应确认参考图权利、保密要求和组织政策。

### Windows 输出目录报 WinError 267

新版本统一使用 `output/auxiliary/`，不会创建 Windows 保留设备名 `aux`。旧的 POSIX 运行目录仍可读取 `aux/`，但新输出永远写入 `auxiliary/`。不要使用 `\\?\` 长路径前缀绕过该问题，因为 VTK 的 GLTF 导入器可能拒绝其中的 `?`。
