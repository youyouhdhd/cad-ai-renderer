# Steam Controller 2026 Example / Steam Controller 2026 示例

## English

This example demonstrates the public workflow on one STEP model. It includes a source model, two representative final renders, contact sheets, and deterministic auxiliary passes. It intentionally omits raw workstation manifests and host handoff logs so that no local absolute path is published.

### Included files

```text
model/SC_solid_stp_20260429.stp
renders/front/best.png
renders/front/contact_sheet.png
renders/front/auxiliary/{clay,color_preview,depth,lineart,mask,normal,part_id,view_grid}.png
renders/rear/best.png
renders/rear/contact_sheet.png
renders/rear/auxiliary/{clay,color_preview,depth,lineart,mask,normal,part_id,view_grid}.png
manifest.json
THIRD_PARTY_NOTICES.md
```

### Re-run preparation

From the repository root:

```powershell
python scripts/run.py preflight `
  --input .\examples\steam-controller-2026\model\SC_solid_stp_20260429.stp `
  --output-dir .\runs\steam-controller

python scripts/run.py plan `
  --input .\examples\steam-controller-2026\model\SC_solid_stp_20260429.stp `
  --output .\runs\steam-controller `
  --intent "Preserve the CAD silhouette, proportions, visible topology, seams, holes, and part placement in a neutral studio product image."
```

Review `planning/render_plan.json`, then set `confirmation.confirmed` to `true` and run:

```powershell
python scripts/run.py prepare `
  --input .\examples\steam-controller-2026\model\SC_solid_stp_20260429.stp `
  --output .\runs\steam-controller `
  --intent "Preserve the CAD silhouette, proportions, visible topology, seams, holes, and part placement in a neutral studio product image." `
  --plan .\runs\steam-controller\planning\render_plan.json
```

The default plan keeps broad deterministic reference coverage but schedules exactly four final
candidates total. The committed images are reference artifacts; re-running the host image-generation
stage can produce different candidates.

## 中文

本示例使用一个 STEP 模型展示公开工作流，包含源模型、两张代表性定稿图、联系表和确定性的辅助通道。为避免发布本机绝对路径，示例刻意不包含原始工作站清单和宿主交接日志。

### 包含文件

见上方目录树；`manifest.json` 记录相对路径、尺寸和 SHA-256。

### 重新生成准备包

在仓库根目录运行上方 PowerShell 命令，确认 `render_plan.json` 后即可重新执行几何准备。已提交图片仅作为参考工件，重新运行宿主生图阶段可能得到不同候选图。
