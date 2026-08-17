# CAD AI Renderer

[![CI](https://github.com/youyouhdhd/cad-ai-renderer/actions/workflows/ci.yml/badge.svg)](https://github.com/youyouhdhd/cad-ai-renderer/actions/workflows/ci.yml)
[![代码许可：MIT](https://img.shields.io/badge/code%20license-MIT-yellow.svg)](LICENSE)
[English](README.md)

从 STEP/STP 或支持的网格模型出发，生成以几何证据为锚点的 AI 产品渲染流程。

CAD AI Renderer 先准备可信的三维几何证据，再把商业效果图生成交给宿主环境的官方生图能力，并把本地诊断与最终视觉判断分开。它适用于产品可视化、相机匹配、材质探索以及可复现的 CAD 到图像交接。

## 功能范围

- 从附件式路径中自动发现模型和可选参考图片。
- 为 CadQuery/OCP、VTK 和图像工具初始化隔离 Python 环境。
- 转换 STEP/STP 或支持的网格模型；在转换器支持时保留叶子部件结构。
- 生成确定性的 CAD 证据：相机网格、颜色预览、黏土图、线稿、轮廓遮罩、相机空间法线、深度图和部件 ID 图。
- 为宿主官方生图能力生成结构化规划与交接文件。
- 暂存多个候选图，计算本地几何诊断，接收宿主视觉 QA，然后最终选定一张图。
- 支持一次定向的几何恢复重试，以及可选的 ComfyUI 深度/边缘几何守卫。

## 非目标与边界

- 不承诺 AI 商业效果图对 CAD 做像素级精确保真。
- 不在包内静默调用原始生图 API，不要求用户提供生图 API Key，也不锁定具体模型 ID。
- 不把 VTK、FreeCAD、Blender 或 ComfyUI 当作默认商业效果图渲染器；它们只负责提供几何证据。
- 不用单一本地数值分数替代人或宿主模型的视觉 QA。

目标是结构引导的近似：优先保证相机、轮廓、比例、拓扑、可见部件数量、孔洞、接缝和遮挡关系；材质与灯光仍然具有生成式不确定性。

## 流程总览

```text
附件
  │
  ▼
发现 ──► 预检/隔离环境 ──► 相机网格
                             │
                             ▼
                    宿主相机/参考图规划
                             │
                             ▼
                    确定性的辅助通道
                             │
                             ▼
                    宿主官方生图交接
                             │
                             ▼
                  候选暂存 + 本地几何诊断
                             │
                             ▼
                      宿主视觉 QA + 定稿
```

标准运行目录为 `auxiliary/`、`planning/`、`candidates/` 和 `final/`。项目刻意不使用 Windows 保留设备名 `aux/`。

## 支持的输入

| 输入 | 用途 |
| --- | --- |
| `.step`、`.stp` | 首选 CAD 模型 |
| `.glb`、`.gltf`、`.obj`、`.stl`、`.ply`、`.3mf` | 转换成功时支持的网格模型 |
| `.png`、`.jpg`、`.jpeg`、`.webp`、`.bmp`、`.tif`、`.tiff` | 可选材质、灯光、风格或相机参考图 |
| 自然语言意图 | 由宿主或用户提供的渲染要求 |

## 快速开始

### 1. 准备兼容的 Python

使用 64 位 CPython 3.10–3.13，优先使用 Python 3.12。不要把 CAD 依赖安装到全局 Python。

```powershell
python scripts/run.py bootstrap
python scripts/run.py preflight
```

启动器会创建或复用托管环境并验证所需导入。第一次隔离安装可能需要数分钟，因为 CadQuery/OCP 和 VTK 包含较大的二进制依赖。

### 2. 发现附件

```powershell
python scripts/run.py discover `
  --input .\examples\steam-controller-2026\model\SC_solid_stp_20260429.stp `
  --output .\runs\steam-controller\input_discovery.json
```

### 3. 生成几何准备包

```powershell
python scripts/run.py prepare `
  --input .\examples\steam-controller-2026\model\SC_solid_stp_20260429.stp `
  --output .\runs\steam-controller `
  --intent "Create a premium studio product image. Preserve the CAD silhouette, proportions, visible topology, seams, holes, and part placement." `
  --width 1024 `
  --height 1024 `
  --candidates 4 `
  --quality high
```

首次运行可以加 `--grid-only`，在相机网格处暂停。宿主应检查 `planning/camera_selection_prompt.txt`，选定视角，并按 `references/PIPELINE.md` 写入相机规划 JSON。

### 4. 暂存并定稿候选图

宿主官方生图能力返回完整候选图后，先暂存但不要立即选最终图：

```powershell
python scripts/run.py stage `
  --run .\runs\steam-controller `
  --candidate C01=.\incoming\C01.png `
  --candidate C02=.\incoming\C02.png `
  --candidate C03=.\incoming\C03.png `
  --candidate C04=.\incoming\C04.png
```

暂存结果为 `awaiting_visual_qa`。宿主随后检查联系表和每张原图，写入视觉 QA JSON，再执行：

```powershell
python scripts/run.py finalize `
  --run .\runs\steam-controller `
  --visual-qa .\runs\steam-controller\planning\visual_qa.json
```

最终运行目录包含 `final/best.png`、`final/selection.json` 和 `final/report.md`。

## 宿主官方生图边界

Python 包只负责结构化交接；商业效果图由宿主环境的官方生图 Skill 或工具生成。`planning/imagegen_request.json`、`planning/input_roles.json` 和 `planning/final_prompt.txt` 描述交接内容，但不嵌入模型锁定或 API 凭据。

如果宿主生图能力不可用，应返回准备包和提示词，而不是静默切换后端。ComfyUI 只是可选的本地几何守卫，不是宿主视觉决策边界的替代品。

## 仓库结构

```text
SKILL.md                         宿主 Skill 合同
agents/openai.yaml               宿主调用元数据
scripts/                         启动、转换、渲染、QA 与 CLI 代码
references/                      安装、Schema、流程和排障文档
assets/                          可选项目与 ComfyUI 模板
docs/                            公开架构、开发和可复现性文档
examples/steam-controller-2026/  脱敏后的模型和输出示例
.github/                         CI、Issue 表单和贡献模板
```

## 示例资产与权利范围

`examples/steam-controller-2026/` 用于让流程可以直接理解和复现。模型文件来自用户提供的 `SC_solid_stp_20260429.stp`，对应 Printables 条目 [Steam Controller 2026 STEP model + puck](https://www.printables.com/model/1577616-steam-controller-2026-step-model-puck)。该条目当前公开元数据标注模型许可为 **Creative Commons — Public Domain**。具体范围与说明见示例目录中的 `README.md` 和 `THIRD_PARTY_NOTICES.md`。

示例效果图和确定性的辅助图是演示产物，不代表 AI 生成图像具有尺寸级 CAD 精确性。

## 验证

内置 self-test 覆盖环境选择、中断恢复、附件发现、STEP 转换、相机网格、辅助通道、候选暂存、视觉 QA 读取、最终定稿、无颜色 STEP 和模型中立配置合同。完成 bootstrap 后运行：

```powershell
python scripts/run.py self-test --output .\runs\self-test
```

独立 Python 测试不能调用宿主专属的官方生图能力；它验证的是其周边的确定性准备和交接边界。

## 隐私与安全

- 不要提交 `.env`、访问令牌、私钥、凭据或未经审查的宿主交接日志。
- 生成的清单应使用仓库相对路径；不要发布 `C:\Users\...` 或 `/home/...` 之类的工作站路径。
- 分享前检查图片与 CAD 元数据；删除超出示例范围的人脸、标签、工程图或作者信息。
- 启动器可能使用本地托管环境和本地 ComfyUI 服务；它们本身不是远程数据外传机制。
- 参见 [SECURITY.md](SECURITY.md) 和 [docs/REPRODUCIBILITY.md](docs/REPRODUCIBILITY.md)。

## 局限

- CAD 导入质量取决于 CadQuery/OCP、FreeCAD 回退是否可用以及源文件本身是否有效。
- 商业效果图仍可能在材质、灯光、拓扑或小特征上漂移；必须执行视觉 QA。
- 本地几何指标只是诊断排序信号，不是美学或拓扑权威。
- 无显示器环境中的 VTK 可能输出显示警告；只要离屏渲染完成即可。
- 较大的 CAD 文件和生成图片不适合频繁改写 Git 历史；未来接近 GitHub 单文件限制的资产应考虑 Git LFS。

## 贡献与支持

提交修改前请阅读 [CONTRIBUTING.md](CONTRIBUTING.md)、[docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) 和 [references/TROUBLESHOOTING.md](references/TROUBLESHOOTING.md)。可复现 Bug 和功能请求请使用 Issue 表单；安全问题请按 [SECURITY.md](SECURITY.md) 处理。

## 许可

本仓库的原创源代码和文档采用 [MIT License](LICENSE)。示例资产及第三方材料以其自身声明为准；仓库 MIT 许可不会重新许可这些材料。
