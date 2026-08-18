# Architecture / 架构说明

## English

### Purpose and audience

This document is for maintainers who need to understand the boundaries between CAD processing, deterministic evidence generation, host planning, and final image selection. It enables safe changes to one subsystem without accidentally turning a diagnostic or local renderer into an unreviewed beauty-generation backend.

### Responsibilities and boundaries

| Boundary | Responsibility | Explicit non-responsibility |
| --- | --- | --- |
| `input_discovery.py` | Classify model and image inputs; infer default roles | Deciding the final visual style |
| `run.py` | Find a compatible interpreter, create/reuse the managed environment, dispatch subcommands | Installing into the global interpreter |
| `step_to_glb.py`, `freecad_step_export.py` | Convert CAD inputs into a renderable intermediate | Claiming generated-image geometry is mathematically exact |
| `render_aux_vtk.py` and `cad_render.py` | Create named directional view grids, per-view bundles, and deterministic auxiliary maps | Producing the final beauty image |
| `pipeline_prompts.py`, `host_handoff.py` | Serialize planning and host handoff artifacts | Calling a raw remote image API |
| `finalize_candidates.py` | Stage candidates, calculate local diagnostics, ingest visual QA, finalize | Replacing visual QA with a local score |
| Optional ComfyUI client | Add one geometry guard before a strict retry | Becoming the default render backend or retry loop |

### Data flow

```text
model + references + intent
            │
            ▼
      input discovery
            │
            ▼
     direct configuration
            │
            ▼
  CAD conversion / passthrough
            │
            ├──────────────► model manifest and geometry metrics
            │
            ▼
   camera grid and directional view plan
            │
            ▼
       per-view CAD bundles
  color / clay / lineart / mask
  normal / depth / part-ID maps
            │
            ▼
      host handoff bundle
            │
            ▼
        candidate images
            │
            ▼
  local diagnostics + contact sheet
            │
            ▼
   host visual QA and final report
```

The run directory is the persistence boundary. A normal run is portable when its manifests contain repository-relative or run-relative paths. Host-only paths may exist during a live handoff but must not be copied into a public example.

### Key decisions

1. **Attachment-first inputs.** Conversation attachments are the normal interface; YAML is an optional advanced configuration, not a prerequisite.
2. **Dedicated environment.** The launcher can select a compatible 64-bit CPython 3.10–3.13, create an isolated environment, resume interrupted setup, and verify imports before dispatch.
3. **Evidence before generation.** CAD software produces structural evidence first. The host image-generation capability receives that evidence and the natural-language brief.
4. **Directional coverage with explicit overrides.** A deterministic grid is generated first. With no requested viewpoint, six principal and eight axonometric bundles are prepared; an explicit camera plan or view ID still produces one bundle.
5. **Stage before finalize.** Candidates are copied into stable run-owned locations and locally ranked before visual QA. Staging alone never writes the final image.
6. **One targeted retry.** Geometry recovery is bounded. A failed guard must not become an unlimited generation loop.
7. **Reference target without a model lock.** GPT Image 2 is the primary reference target for product-image evaluation when available, while the host handoff remains model-neutral and the package never embeds an image API client or credential.
8. **Codex image-generation default.** The handoff prefers the official `$imagegen` Skill and requests 4K, high quality, and high detail. When exact host resolution controls are unavailable, the actual dimensions are recorded rather than overstated.

### Failure modes

- **No compatible Python:** stop with an actionable error; do not install into the ambient global interpreter.
- **Partial bootstrap or stale lock:** inspect managed ownership metadata and resume or rebuild only environments owned by the launcher.
- **STEP conversion failure:** return the input and converter diagnostics; do not fabricate a geometry pass.
- **Blank or invalid auxiliary image:** fail validation before host handoff.
- **Host generation unavailable:** return the preparation bundle and prompt; do not silently change providers.
- **Geometry drift in all candidates:** permit at most the configured strict retry, then report that visual QA did not pass.
- **Conflicting local and visual ranking:** preserve the host visual-QA decision and record the disagreement in the final report.

### Operational considerations

- VTK uses offscreen rendering where possible; a headless display warning is not automatically a failure.
- `auxiliary/` is canonical because `aux/` is a reserved Windows device name.
- The local score is intentionally diagnostic and weighted with host visual QA during finalization.
- Generated prompts and manifests can contain model-derived information; review them before publishing.

### Known limits and future changes

- Exact CAD constraints are not enforced in the generated image layer.
- Mesh fallback quality varies by source format and converter availability.
- The official image-generation capability is host-dependent and cannot be fully reproduced by the standalone test.
- Future changes should preserve the output schemas or version them explicitly, add migration notes, and keep retry behavior bounded.

## 中文

### 目的与读者

本文面向需要维护本项目的开发者，说明 CAD 处理、确定性证据、宿主规划和最终选图之间的边界。它帮助维护者安全修改单个子系统，避免把诊断逻辑或本地渲染器误变成未经审查的商业效果图后端。

### 职责与边界

| 边界 | 负责内容 | 明确不负责 |
| --- | --- | --- |
| `input_discovery.py` | 分类模型/图片输入并推断默认角色 | 决定最终视觉风格 |
| `run.py` | 查找兼容解释器、创建/复用隔离环境、分发子命令 | 向全局解释器安装依赖 |
| `step_to_glb.py`、`freecad_step_export.py` | 把 CAD 输入转换为可渲染中间格式 | 声称生成图像具备数学级精确几何 |
| `render_aux_vtk.py`、`cad_render.py` | 生成命名方向视角网格、逐视角 bundle 和确定性辅助图 | 生成最终商业效果图 |
| `pipeline_prompts.py`、`host_handoff.py` | 序列化规划与宿主交接文件 | 调用原始远程生图 API |
| `finalize_candidates.py` | 暂存候选、计算本地诊断、读取视觉 QA、定稿 | 用本地分数替代视觉 QA |
| 可选 ComfyUI 客户端 | 在一次严格重试前提供几何守卫 | 变成默认渲染后端或无限重试循环 |

### 数据流

```text
模型 + 参考图 + 意图
          │
          ▼
      输入发现
          │
          ▼
      直接配置
          │
          ▼
 CAD 转换 / 直接使用
          │
          ├────────────► 模型清单与几何指标
          │
          ▼
       相机网格和方向视角规划
          │
          ▼
      逐视角 CAD bundle
颜色 / 黏土 / 线稿 / 遮罩
法线 / 深度 / 部件 ID 图
          │
          ▼
    宿主交接准备包
          │
          ▼
        候选图像
          │
          ▼
   本地诊断 + 联系表
          │
          ▼
  宿主视觉 QA 与最终报告
```

运行目录是持久化边界。只要清单使用仓库相对路径或运行目录相对路径，运行结果就更容易迁移。宿主临时路径可以在实时交接中存在，但不应复制进公开示例。

### 关键决策

1. **附件优先。** 对话附件是正常接口；YAML 只是可选高级配置，不是使用前提。
2. **隔离环境。** 启动器可选择兼容的 64 位 CPython 3.10–3.13，创建隔离环境，恢复中断安装，并在分发命令前验证依赖。
3. **先证据后生成。** 传统 CAD 工具先提供结构证据，宿主官方生图能力再结合证据和自然语言要求生成图片。
4. **方向覆盖与显式覆盖。** 先生成确定性视角网格；未指定视角时准备六个主视图和八个轴测 bundle，显式相机规划或视角 ID 仍只生成一个 bundle。
5. **先暂存后定稿。** 候选图先复制到运行目录并做本地诊断；暂存阶段永远不写最终图。
6. **最多一次定向重试。** 几何恢复是有上限的，失败后不能变成无限生图循环。
7. **有参考目标但不锁定模型。** 在宿主提供时，GPT Image 2 是产品效果图评估的主要参考目标；宿主交接仍保持模型中立，包内不嵌入生图 API 客户端或凭据。
8. **默认 Codex 生图。** 交接默认优先使用官方 `$imagegen` Skill，并请求 4K、高质量、高细节；宿主无法精确控制分辨率时记录实际尺寸，不夸大输出能力。

### 失败模式

- **没有兼容 Python：** 输出可操作错误，不向当前全局解释器安装依赖。
- **环境中断或锁过期：** 检查托管所有权元数据；只恢复或重建由启动器持有的环境。
- **STEP 转换失败：** 返回输入和转换器诊断，不伪造几何通道。
- **辅助图为空或无效：** 在交接给宿主前失败并停止。
- **宿主生图不可用：** 返回准备包和提示词，不静默更换供应商。
- **所有候选都有几何漂移：** 只允许配置的一次严格重试，之后报告视觉 QA 未通过。
- **本地与视觉排序冲突：** 保留宿主视觉 QA 决定，并在最终报告中记录冲突。

### 运维注意事项

- VTK 尽量使用离屏渲染；无显示器警告不应自动被视为失败。
- `auxiliary/` 是标准目录，因为 `aux/` 是 Windows 保留设备名。
- 本地分数只是诊断信号；定稿时会与宿主视觉 QA 一起使用。
- 生成的提示词和清单可能包含模型派生信息，发布前需要审查。

### 已知限制与后续方向

- 生成图层不会强制满足 CAD 的全部精确约束。
- 网格回退质量取决于源格式与转换器。
- 官方生图能力依赖宿主，独立测试无法完全复现它。
- 后续修改应保持输出 Schema，或显式版本化并附迁移说明；重试行为必须有上限。
