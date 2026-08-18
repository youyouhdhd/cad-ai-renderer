---
name: cad-ai-renderer
description: Generate geometry-anchored industrial product renders from an attached STEP/STP CAD model or supported mesh plus optional reference images as a reusable Codex Skill. Use when Codex must inspect CAD geometry, create deterministic multi-direction camera coverage or a specified camera, silhouette, clay, line-art, depth, normal, and part-ID evidence, then guide the host's official image-generation capability through high-detail candidate product visualization, camera matching, visual QA, and final selection while preserving visible proportions, topology, holes, seams, and part placement. Discover attachments automatically, self-initialize a dedicated CAD/VTK Python environment, use 3D only as geometry evidence, and delegate final rendering to the host rather than a raw API client.
---

# CAD AI Renderer

## Core contract

Treat the current host conversation model as the planner and visual judge. Keep runtime execution model-neutral: do not add model IDs, model locks, routing restrictions, or reasoning-mode requirements to the Skill contract. Public documentation may name GPT Image 2 as a reference target, but execution must continue to use the host's currently supported official image-generation capability.

Use the host's official image-generation skill or tool for final images. Prefer the official `imagegen` skill when it is exposed. Otherwise use the host's official image-generation tool. Do not call a raw image API from bundled Python, do not request an API key, and do not substitute a third-party generator silently.

Use CAD, FreeCAD, Blender, VTK, or ComfyUI only to create deterministic geometry evidence. Do not treat a traditional renderer as the default beauty renderer.

Do not claim pixel-exact CAD preservation. Maximize camera, silhouette, proportion, topology, part count, holes, seams, and occlusion fidelity, then report remaining uncertainty.

## Accept attachments directly

Inspect the files attached to the current user message before asking for paths or configuration.

Identify inputs as follows:

- Treat `.step` or `.stp` as the preferred model input.
- Also accept `.glb`, `.gltf`, `.obj`, `.stl`, `.ply`, or `.3mf` when conversion succeeds.
- Treat attached `.png`, `.jpg`, `.jpeg`, `.webp`, `.bmp`, `.tif`, or `.tiff` files as potential references.
- Treat a colored 3D-software screenshot as a valid mixed reference for camera, composition, color blocks, and rough material intent.
- Use the user's natural-language request as the project intent.

Do not require the user to create YAML, JSON, role labels, or a folder layout. Generate internal manifests and planning JSON yourself.

Proceed without clarification when one model is identifiable. Ask only when no model exists or several equally plausible model files remain after considering the user's wording.

## Self-initialize a dedicated Python environment

Run every bundled Python operation through `scripts/run.py`. Never install the requirements into the global interpreter.

Before the first CAD command in a new machine or workspace, run:

```bash
python scripts/run.py bootstrap
```

Give the first bootstrap a long tool timeout, preferably at least 10 minutes, because CadQuery/OCP and VTK are large binary packages. The launcher must automatically:

- Discover a compatible 64-bit CPython 3.10-3.13 and prefer Python 3.12. Do not manually enumerate interpreters first.
- Re-launch itself under the selected interpreter when the ambient `python` is incompatible.
- Create a dedicated environment at `~/.cache/cad-ai-renderer/venv` by default.
- Honor `CAD_AI_RENDERER_BOOTSTRAP_PYTHON`, `CAD_AI_RENDERER_VENV`, `--bootstrap-python`, or `--venv-dir` when explicit control is needed.
- Lock concurrent initialization, write state atomically, and resume a partial installation after interruption.
- Install `requirements.txt` only when missing or changed, then verify every required import.
- Reuse the environment on later runs.

If bootstrap is interrupted or a host command timeout expires, rerun the same command. Do not delete the partial environment or invoke `pip` manually; the launcher resumes cached work.

Use commands in this form:

```bash
python scripts/run.py bootstrap
python scripts/run.py preflight ...
python scripts/run.py prepare ...
python scripts/run.py stage ...
python scripts/run.py finalize ...
python scripts/run.py self-test ...
```

## Standard workflow

### 1. Discover the attached files

Pass the attachment paths directly to the launcher. The normal flow requires no project file:

```bash
python scripts/run.py discover \
  --input /path/to/model.step \
  --input /path/to/reference-1.jpg \
  --input /path/to/reference-2.png
```

Use `--model` only when several attached 3D files are ambiguous. Use `--reference` only when an image path was not included through `--input`.

### 2. Run preflight

Run preflight through the managed environment:

```bash
python scripts/run.py preflight \
  --input /path/to/model.step \
  --input /path/to/reference.jpg \
  --output-dir /path/to/run-output
```

Verify the model path, reference count, output write access, CadQuery/OCP, VTK, Pillow, OpenCV, and trimesh. Treat missing FreeCAD or Blender as warnings when the CadQuery plus VTK path works.

### 3. Generate broad camera coverage first

Unless the user supplied an exact camera, run the camera-grid stage before final anchors:

```bash
python scripts/run.py prepare \
  --input /path/to/model.step \
  --input /path/to/reference.jpg \
  --intent "<user request>" \
  --output /path/to/run-output \
  --grid-only
```

Inspect these together:

- `auxiliary/view_grid.png`.
- Attached camera or composition references.
- The user's requested viewpoint.
- `auxiliary/view_grid.json`.

The default named view set contains six principal views—front (+X), back (-X), left (-Y), right (+Y), top (+Z), and bottom (-Z)—plus eight upper/lower axonometric views. These are coordinate-axis conventions, not claims about semantic product front/back unless the user or a reliable reference establishes that mapping.

If the user specifies an exact viewpoint, or a reliable reference fixes one camera, choose one labeled view that exposes defining geometry and avoids accidental occlusion. If no output viewpoint is specified, do not collapse the task to one hero angle: continue without `--view-id` or `--camera-plan` and let the default multi-view bundle render every named direction. Use `view_set: all` and `selected_view_ids` when writing a host camera plan explicitly.

Write `planning/camera_plan.host.json` using the schema in `references/PIPELINE.md`. Do not ask the user to author it.

### 4. Classify every reference automatically

Use vision to assign one or more roles:

```text
camera, composition, material, color, lighting, style, environment, detail, mixed
```

For every reference, record:

- What may be used.
- What must be ignored.
- Confidence.
- Any ambiguity.

Always forbid copying reference-object geometry, topology, proportions, part count, holes, seams, controls, logos, or accessories unless the user explicitly asks to add a non-CAD element.

Write `planning/reference_roles.host.json`. Do not require the user to label images.

### 5. Build the rendering brief

Analyze the model preview, clay image, lineart, available CAD colors, references, and user intent. Infer missing material, color, light, or environment information conservatively.

When no reference exists:

- Use a restrained premium visualization.
- Choose physically plausible materials.
- Use controlled studio lighting and a neutral background.
- Record every significant assumption.

When only one mixed reference exists:

- Separate reliable material/color/light evidence from unreliable geometry.
- Preserve CAD geometry over the reference object.

When the model is colorless:

- Treat part pseudo-colors as segmentation IDs, not paint.
- Use the clay image for natural shaded form.
- Infer a coherent palette or use the user's/reference color evidence.

Write `planning/render_brief.host.json` using `references/PROMPTING.md`.

### 6. Render the final auxiliary set

Run preparation again with the host-generated plans:

```bash
python scripts/run.py prepare \
  --input /path/to/model.step \
  --input /path/to/reference.jpg \
  --intent "<user request>" \
  --output /path/to/run-output \
  --camera-plan /path/to/run-output/planning/camera_plan.host.json \
  --reference-roles /path/to/run-output/planning/reference_roles.host.json \
  --render-brief /path/to/run-output/planning/render_brief.host.json
```

Generate and retain:

- `view_grid.png` and view thumbnails.
- `color_preview.png`.
- `clay.png`.
- `lineart.png`.
- `mask.png`.
- `normal.png`.
- `depth.png`.
- `part_id.png`.
- `camera.json`.
- `model_manifest.json`.

For the default multi-view path, the same auxiliary set is written under `views/<view-id>/` for every named view, with an independent camera plan and host handoff. Do not reuse one view's auxiliary images as another view's geometry evidence.

Use `color_preview + clay + lineart` as the default balanced image-generation input set. This combination gives natural shaded form, component/color evidence, and crisp topology without overwhelming the image model with technical maps.

Use anchor modes as follows:

- `compact`: color preview + lineart.
- `balanced`: color preview + clay + lineart. Use by default.
- `max_geometry`: color preview + clay + lineart + normal + depth + mask. Use only for difficult geometry or the single retry.

Always output all auxiliary passes even when only a subset is sent to image generation.

### 7. Invoke the official image-generation skill or tool

Read the per-view files when a multi-view bundle exists; otherwise read the root files:

- `planning/imagegen_request.json`.
- `planning/final_prompt.txt`.
- `planning/input_roles.json`.

Pass the listed input images in exactly that order to the official image-generation capability. Keep each image's role explicit in the prompt.

Use the host's official `$imagegen` Skill by default when it is exposed. Generate four candidates per view by default. Prefer one official multi-output invocation for each view; when the host capability returns one image per call, make four equivalent calls with the same prompt and ordered inputs. For a multi-view run, generate each view independently. Do not create a collage, morph between cameras, or use one view's beauty image as another view's geometry evidence.

Save the generated images as local files and assign IDs `C01` through `C04`. Follow `planning/host_handoff.json` and `planning/NEXT_STEPS.md`; these files contain the exact ordered inputs and stage/finalize argument templates.

If the official image-generation capability is unavailable, stop after local preparation and return the complete auxiliary bundle plus prompt. Do not fall back to a hidden raw API path.

### 8. Stage candidates and create local diagnostics

Read `planning/host_handoff.json` and pass the image generator's returned file paths directly to the `stage` command. Do not manually pre-copy generated images.

```bash
python scripts/run.py stage \
  --run /path/to/run-output \
  --candidate C01=/path/to/generated-1.png \
  --candidate C02=/path/to/generated-2.png \
  --candidate C03=/path/to/generated-3.png \
  --candidate C04=/path/to/generated-4.png
```

Run the stage command independently for each view directory in a multi-view run. The stage command must return `awaiting_visual_qa`, create the contact sheet and QA prompt, and leave `final/best.*` and `final/selection.json` absent. Treat local edge and silhouette metrics as weak diagnostics only; never let them create a provisional best image.

### 9. Perform visual QA with the host model

Inspect the CAD anchors, contact sheet, and each candidate at full resolution. Score:

- Camera and perspective.
- Silhouette and proportions.
- Visible topology and part count.
- Holes, seams, controls, and occlusion order.
- Material plausibility and color plan.
- Lighting, artifacts, and prompt compliance.

Write `planning/visual_qa.host.json` using `planning/visual_qa.template.json` and the schema in `references/PIPELINE.md`, then run finalize:

```bash
python scripts/run.py finalize \
  --run /path/to/run-output \
  --visual-qa /path/to/run-output/planning/visual_qa.host.json
```

Finalize from the stable copies created by `stage`; do not repeat temporary image-generator paths. Supply `--candidate` during finalize only when deliberately replacing or adding a candidate.

Gate selection on geometry before beauty. Return `complete_with_geometry_warning` when no candidate passes; do not lower the threshold automatically.

### 10. Retry at most once

Retry only when a material geometry error is visible. Name exact failures such as a missing hole, moved seam, merged part, changed camera, widened base, or added control.

Re-run preparation with:

```bash
--anchor-mode max_geometry --strict-geometry
```

Optionally use the configured ComfyUI depth/canny guard before the retry. Feed its output as an additional structural reference, not as the final render.

Generate one replacement batch only. Label retry images `R01` onward, include them in final QA, and never enter an open-ended regeneration loop.

## STEP handling

Use CadQuery/OCP first to preserve assembly structure, part transforms, and available colors. Fall back to FreeCADCmd only when CadQuery fails and FreeCAD is installed.

Record that the FreeCAD STL fallback loses STEP colors, assembly hierarchy, and part IDs.

Never pass raw STEP bytes to image generation. Convert the model to pixels first.

## Output contract

Produce this structure:

```text
output/
  input_discovery.json
  resolved_project.yaml
  run_manifest.json
  auxiliary/
    model.glb
    model_manifest.json
    view_grid.png
    view_grid.json
    views/
    color_preview.png
    clay.png
    lineart.png
    mask.png
    normal.png
    depth.png
    part_id.png
    camera.json
    aux_manifest.json
  planning/
    reference_role_prompt.txt
    reference_roles.json
    reference_roles.host.json       # when host analysis is used
    camera_selection_prompt.txt
    camera_plan.json
    camera_plan.host.json           # when host analysis is used
    render_brief_prompt.txt
    render_brief.json
    render_brief.host.json          # when host analysis is used
    input_roles.json
    final_prompt.txt
    imagegen_request.json
    host_handoff.json
    NEXT_STEPS.md
    visual_qa.template.json
    qa_prompt.txt
    visual_qa.json
    visual_qa.host.json             # when host analysis is used
  views/                            # default when no output viewpoint is specified
    <view-id>/
      auxiliary/
      planning/
      candidates/
      final/
  candidates/
    images/
    local_scores.json
    scores.json
    contact_sheet.png
  final/
    best.png
    selection.json
    report.md
```

Always write new deterministic passes under `auxiliary/`. When reading an old POSIX run, accept the legacy `aux/` directory, but never create `aux/` because `AUX` is a reserved Windows device name.

Only visual-QA-backed finalization creates `final/best.*`. Rebuild `final/report.md` from structured artifacts on every stage/finalize call; never append duplicate report sections or hand-edit it.

Return links to at least:

- `final/best.*`, or every `views/<view-id>/final/best.*` after a multi-view run.
- `candidates/contact_sheet.png`.
- `auxiliary/view_grid.png`.
- `auxiliary/color_preview.png`.
- `auxiliary/clay.png`.
- `auxiliary/lineart.png`.
- `auxiliary/mask.png`.
- `auxiliary/normal.png`.
- `final/report.md`.

When generation was unavailable, state that clearly and return the prepared prompt and every auxiliary image instead of fabricating candidates.

## Validation

After installation or code changes, run the real-data test through the dedicated environment:

```bash
python scripts/run.py self-test --output ./cad-ai-renderer-self-test
```

Require every local check to pass before packaging. The self-test creates real STEP fixtures, uses direct attachment-style discovery, renders named directional coverage and all auxiliary passes, tests automatic bootstrap decisions, Windows-safe paths, candidate staging/finalization, and idempotent reporting, and verifies the absence of model locks and raw image API code. It cannot exercise a host-only image-generation tool from local Python.

## References

Read only what is needed:

- Installation and managed environment: `references/INSTALL.md`.
- Attachment discovery and automatic role inference: `references/ATTACHMENTS.md`.
- Camera, planning, visual-QA schemas, and end-to-end flow: `references/PIPELINE.md`.
- Prompt and missing-information policies: `references/PROMPTING.md`.
- Official image-generation delegation: `references/IMAGEGEN.md`.
- Optional advanced YAML: `references/PROJECT_SCHEMA.md`.
- Optional ComfyUI guard: `references/COMFYUI.md`.
- Failure diagnosis: `references/TROUBLESHOOTING.md`.
- Executed test evidence: `references/TEST_REPORT.md`.
