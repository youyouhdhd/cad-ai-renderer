# CAD AI Renderer

[![CI](https://github.com/youyouhdhd/cad-ai-renderer/actions/workflows/ci.yml/badge.svg)](https://github.com/youyouhdhd/cad-ai-renderer/actions/workflows/ci.yml)
[![Code license: MIT](https://img.shields.io/badge/code%20license-MIT-yellow.svg)](LICENSE)
[简体中文](README.zh-CN.md)

Geometry-anchored AI product rendering from STEP/STP or supported mesh inputs.

CAD AI Renderer prepares trustworthy geometry evidence, delegates the beauty-render step to the host's official image-generation capability, and keeps local diagnostics separate from the final visual decision. It is designed for product visualization, camera matching, material exploration, and reproducible CAD-to-image handoffs.

## Why this matters

AI image generation can make a product look plausible while quietly drifting from CAD: hole locations, silhouette, part count, seams, and proportions are easy to lose. CAD AI Renderer turns the model into deterministic, inspectable geometry evidence and a structured, auditable generation handoff, so appearance exploration is flexible without silently becoming the source of truth for geometry.

## What it does

- Discovers a model and optional reference images directly from attachment-style paths.
- Bootstraps a dedicated Python environment for CadQuery/OCP, VTK, and image utilities.
- Converts STEP/STP or supported meshes into renderable geometry while preserving leaf-part structure where the converter supports it.
- Creates deterministic CAD evidence: camera grids, color previews, clay, lineart, silhouette masks, camera-space normals, depth, and part-ID maps.
- Produces structured planning artifacts for the host image-generation capability.
- Stages multiple candidates, computes local geometry diagnostics, accepts host visual QA, and finalizes one candidate.
- Supports one targeted geometry-recovery retry and an optional ComfyUI depth/canny guard.

## What it does not do

- It does not promise pixel-exact CAD preservation in a generated beauty image.
- It does not silently call a raw image API, request an image API key, or hard-code a model identifier.
- It does not treat VTK, FreeCAD, Blender, or ComfyUI as the default beauty renderer; those tools provide geometry evidence only.
- It does not replace a human/host visual QA decision with a local numerical score.

The intended result is structure-guided approximation: camera, silhouette, proportion, topology, visible part count, holes, seams, and occlusion are prioritized, while generative material and lighting remain probabilistic.

## Pipeline at a glance

```text
attachments
    │
    ▼
discover ──► preflight/bootstrap ──► camera grid
                                      │
                                      ▼
                              host camera/reference plan
                                      │
                                      ▼
                          deterministic auxiliary passes
                                      │
                                      ▼
                         host image-generation handoff
                                      │
                                      ▼
                    candidate staging + local diagnostics
                                      │
                                      ▼
                           host visual QA + finalize
```

The canonical run layout is `auxiliary/`, `planning/`, `candidates/`, and `final/`. The reserved Windows device name `aux/` is intentionally not used.

## Supported inputs

| Input | Role |
| --- | --- |
| `.step`, `.stp` | Preferred CAD model input |
| `.glb`, `.gltf`, `.obj`, `.stl`, `.ply`, `.3mf` | Supported mesh inputs when conversion succeeds |
| `.png`, `.jpg`, `.jpeg`, `.webp`, `.bmp`, `.tif`, `.tiff` | Optional material, lighting, style, or camera references |
| Natural-language intent | Rendering brief supplied by the host/user |

## Quick start

### 1. Prepare a compatible Python

Use a 64-bit CPython 3.10–3.13 installation; Python 3.12 is preferred. Do not install the CAD dependencies into the global interpreter.

```powershell
python scripts/run.py bootstrap
python scripts/run.py preflight
```

The launcher creates or reuses a managed environment and verifies the required imports. The first isolated installation may take several minutes because CadQuery/OCP and VTK contain large binary packages.

### 2. Discover attachments

```powershell
python scripts/run.py discover `
  --input .\examples\steam-controller-2026\model\SC_solid_stp_20260429.stp `
  --output .\runs\steam-controller\input_discovery.json
```

### 3. Create the geometry preparation bundle

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

For a first pass, stop after the camera grid with `--grid-only`. The host should inspect `planning/camera_selection_prompt.txt`, select a view, and write the camera plan described in `references/PIPELINE.md`.

### 4. Stage and finalize candidates

After the host image-generation capability returns complete candidate images, stage them without selecting a final image:

```powershell
python scripts/run.py stage `
  --run .\runs\steam-controller `
  --candidate C01=.\incoming\C01.png `
  --candidate C02=.\incoming\C02.png `
  --candidate C03=.\incoming\C03.png `
  --candidate C04=.\incoming\C04.png
```

The stage result is `awaiting_visual_qa`. The host then reviews the contact sheet and each candidate at full resolution, writes a visual-QA JSON file, and finalizes:

```powershell
python scripts/run.py finalize `
  --run .\runs\steam-controller `
  --visual-qa .\runs\steam-controller\planning\visual_qa.json
```

The final run contains `final/best.png`, `final/selection.json`, and `final/report.md`.

## Host image-generation boundary

The Python package stops at a structured handoff. The host's official image-generation skill or tool is responsible for beauty-image synthesis. `planning/imagegen_request.json`, `planning/input_roles.json`, and `planning/final_prompt.txt` describe the handoff without embedding a model lock or API credential.

If the host capability is unavailable, return the preparation bundle and prompt instead of silently switching to another backend. ComfyUI is an optional local geometry guard, not a substitute for the host decision boundary.

## Repository layout

```text
SKILL.md                         Host skill contract
agents/openai.yaml               Host-facing invocation metadata
scripts/                         Launcher, conversion, rendering, QA, and CLI code
references/                      Installation, schema, pipeline, and troubleshooting docs
assets/                          Optional project and ComfyUI templates
docs/                            Public architecture, development, and reproducibility docs
examples/steam-controller-2026/  Sanitized model and output example
.github/                         CI, issue forms, and contribution templates
```

## Example assets and rights

The example under `examples/steam-controller-2026/` is included to make the workflow concrete. The model file is the user-supplied `SC_solid_stp_20260429.stp`, associated with the Printables listing [Steam Controller 2026 STEP model + puck](https://www.printables.com/model/1577616-steam-controller-2026-step-model-puck). The listing currently identifies the model license as **Creative Commons — Public Domain**. See the example's `README.md` and `THIRD_PARTY_NOTICES.md` for scope and attribution notes.

The example render images and deterministic auxiliary maps are demonstration artifacts. They are not claims that an AI-generated image is a dimensionally exact CAD representation.

## Validation

The bundled self-test covers environment selection, interruption recovery, attachment discovery, STEP conversion, camera-grid generation, auxiliary rendering, candidate staging, visual-QA ingestion, finalization, colorless STEP handling, and the model-neutral configuration contract. Run it through the launcher after bootstrapping:

```powershell
python scripts/run.py self-test --output .\runs\self-test
```

The standalone test cannot invoke the host-only official image-generation capability; it validates the deterministic preparation and handoff boundary around it.

## Privacy and security

- Do not commit `.env` files, access tokens, private keys, credentials, or raw host handoff logs.
- Generated manifests should use repository-relative paths. Do not publish workstation paths such as `C:\Users\...` or `/home/...`.
- Review images and CAD metadata before sharing; remove faces, labels, drawings, or embedded author information that are outside the intended example.
- The launcher may use a local managed environment and local ComfyUI server; neither is a remote data-exfiltration mechanism by itself.
- See [SECURITY.md](SECURITY.md) and [docs/REPRODUCIBILITY.md](docs/REPRODUCIBILITY.md).

## Limitations

- CAD import quality depends on CadQuery/OCP, FreeCAD fallback availability, and the source file's validity.
- A generated beauty image can still drift in material, lighting, topology, or small features; visual QA is mandatory.
- Local geometry metrics are diagnostic ranking signals, not aesthetic or topology authority.
- Headless VTK may emit display warnings; offscreen rendering is expected to remain usable.
- Large CAD files and generated images may be unsuitable for frequent Git history changes. Prefer Git LFS for future assets that approach GitHub's per-file limit.

## Contributing and support

Read [CONTRIBUTING.md](CONTRIBUTING.md), [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md), and [references/TROUBLESHOOTING.md](references/TROUBLESHOOTING.md) before opening a change. Use the issue forms for reproducible bugs and feature requests. Security-sensitive reports belong in [SECURITY.md](SECURITY.md).

## License

Original source code and documentation in this repository are released under the [MIT License](LICENSE). Example assets and third-party materials are governed by their own notices; the repository MIT license does not relicense them.
