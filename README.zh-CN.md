# CAD AI Renderer

[![CI](https://github.com/youyouhdhd/cad-ai-renderer/actions/workflows/ci.yml/badge.svg)](https://github.com/youyouhdhd/cad-ai-renderer/actions/workflows/ci.yml)
[![代码许可：MIT](https://img.shields.io/badge/code%20license-MIT-yellow.svg)](LICENSE)
[English](README.md)
[路线图](ROADMAP.md)

面向 Codex 的开源 Skill：从 STEP/STP 或支持的网格模型出发，生成以几何证据为锚点的 CAD 到产品可视化流程，并以 [GPT Image 2](https://developers.openai.com/api/docs/guides/image-generation) 作为主要参考目标。

CAD AI Renderer 为 Codex 提供可复现的工作流：把 STEP/STP 和支持的网格文件转化为确定性的 CAD 证据，再通过宿主官方生图能力引导高质量产品可视化。当宿主提供 GPT Image 2 时，它是主要的效果图合成参考目标；Skill 本身仍保持模型中立，不调用原始生图 API、不要求 API Key，也不硬编码模型 ID。

## 为什么重要

AI 生图可以让产品“看起来合理”，却很容易悄悄偏离 CAD：孔位、轮廓、零件数量、接缝和比例都可能漂移。CAD AI Renderer 把模型转化为确定、可检查的几何证据，并提供结构化、可审计的生成交接层，让外观探索保持灵活，同时不让生成图像悄悄取代几何事实来源。

## 为什么要做成 Skill？

CAD 到图像不是一句提示词就能完成的任务，而是一条可重复的 Agent 工作流：发现附件、准备依赖、转换几何、选择相机、生成辅助通道、构造提示词、比较候选图、检查几何并最终定稿。

把这条流程封装成 Codex Skill，可以让行为可复用、可检查、可测试。仓库把确定性的 CAD 证据层与由宿主控制的生成式图像层分开，因此生图模型的可用性变化不会悄悄改变几何合同。

## 面向 Codex + GPT Image 2 的工作方式

Codex 负责围绕 CAD 证据、参考图、渲染意图、候选生成和视觉复核进行多步骤编排；确定性管线准备结构证据；宿主官方生图能力负责视觉合成。

```text
STEP / STP / 网格模型
        │
        ▼
      Codex
        │
        ▼
CAD AI Renderer Skill
        │
        ├── 模型发现与转换
        ├── 相机选择与几何预览
        ├── 轮廓 / 线稿 / 深度 / 法线证据
        └── 部件 ID、拓扑、孔洞、接缝和比例检查
        │
        ▼
结构化生图交接
        │
        ▼
GPT Image 2 或宿主支持的其他官方生图能力
        │
        ▼
候选暂存 → 视觉 QA → 选定最终图
```

GPT Image 2 可以负责材质、灯光、反射、环境和展示质量；CAD 证据仍是可审计的结构参考，最终商业效果图仍属于结构引导的近似结果，而不是尺寸级 CAD 验证产物。

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

单视角运行的标准目录为 `auxiliary/`、`planning/`、`candidates/` 和 `final/`。未指定输出视角时，还会生成独立的 `views/<view-id>/` bundle，覆盖前后左右上下以及上下方向的轴测视角。项目刻意不使用 Windows 保留设备名 `aux/`。

## 支持的输入

| 输入 | 用途 |
| --- | --- |
| `.step`、`.stp` | 首选 CAD 模型 |
| `.glb`、`.gltf`、`.obj`、`.stl`、`.ply`、`.3mf` | 转换成功时支持的网格模型 |
| `.png`、`.jpg`、`.jpeg`、`.webp`、`.bmp`、`.tif`、`.tiff` | 可选材质、灯光、风格或相机参考图 |
| 自然语言意图 | 由宿主或用户提供的渲染要求 |

## 作为 Codex Skill 使用

本仓库设计为可安装、可复用的 `$cad-ai-renderer` Skill。向 Codex 提供：

1. 一个 STEP/STP 或支持的网格模型；
2. 可选的材质、灯光、相机或风格参考图；
3. 一段自然语言渲染要求。

Skill 会准备确定性的 CAD 证据和结构化交接文件。未指定输出视角时，默认准备完整的多方向视角集合。效果图合成默认使用 Codex 官方 `$imagegen` Skill，目标为 4K、高质量、高细节；如果宿主不能提供精确 4K 控制，则使用最高可用分辨率并记录实际尺寸。

示例请求：

> 使用 `$cad-ai-renderer` 处理这个 STEP 文件。未指定视角时生成前后左右上下以及上下轴测视角。使用 Codex 官方 `$imagegen` Skill 为每个视角生成四张 4K、高细节候选图，结合 CAD 证据比较，并在视觉 QA 后分别定稿。

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

`--width/--height` 控制确定性的 CAD 证据尺寸；最终效果图默认通过 Codex 官方 `$imagegen` Skill 请求 4K。可以用 `--host-skill imagegen --target-resolution 4k --detail-level high` 显式写出默认值。未指定视角时，应分别检查 `views/<view-id>/` 下的视角 bundle，并分别暂存、视觉 QA 和定稿。

首次运行可以加 `--grid-only`，在相机网格处暂停。如果没有参考图锁定单一相机，宿主应保留完整默认视角集合，而不是只选择一张主视角。

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

Python 包只负责结构化交接；商业效果图默认由 Codex 官方 `$imagegen` Skill 生成。`planning/imagegen_request.json`、`planning/input_roles.json` 和 `planning/final_prompt.txt` 描述包括 4K、高质量、高细节目标在内的交接内容，但不嵌入模型锁定或 API 凭据。

GPT Image 2 是集成目标和评估参考，不是随仓库打包的依赖。本仓库不会直接调用 OpenAI Images API，从而把凭据、模型可用性和宿主策略留在 Skill 包之外。

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
ROADMAP.md                      公开的可靠性、评估和 Skill 体验路线图
.github/                         CI、Issue 表单和贡献模板
```

## 示例资产与权利范围

`examples/steam-controller-2026/` 用于让流程可以直接理解和复现。模型文件来自用户提供的 `SC_solid_stp_20260429.stp`，对应 Printables 条目 [Steam Controller 2026 STEP model + puck](https://www.printables.com/model/1577616-steam-controller-2026-step-model-puck)。该条目当前公开元数据标注模型许可为 **Creative Commons — Public Domain**。具体范围与说明见示例目录中的 `README.md` 和 `THIRD_PARTY_NOTICES.md`。

示例效果图和确定性的辅助图是演示产物，不代表 AI 生成图像具有尺寸级 CAD 精确性。

## 公开视觉示例

已提交的 Steam Controller 示例展示了一条完整的“几何证据到产品图”路径，同时没有发布工作站清单或宿主凭据：

| 阶段 | 公开产物 |
| --- | --- |
| 源 CAD | [STEP 模型](examples/steam-controller-2026/model/SC_solid_stp_20260429.stp) |
| 前视候选图 | [联系表](examples/steam-controller-2026/renders/front/contact_sheet.png) |
| 前视定稿图 | [代表性效果图](examples/steam-controller-2026/renders/front/best.png) |
| 前视几何证据 | [相机网格与辅助通道](examples/steam-controller-2026/renders/front/auxiliary/) |
| 后视定稿图 | [代表性效果图](examples/steam-controller-2026/renders/rear/best.png) |
| 后视几何证据 | [相机网格与辅助通道](examples/steam-controller-2026/renders/rear/auxiliary/) |

这个示例把边界直接展示出来：CAD 模型和辅助图是确定性的证据，而商业效果图是参考输出，重复执行宿主生图阶段时可能发生变化。

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
