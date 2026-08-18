# CAD AI Renderer

[![CI](https://github.com/youyouhdhd/cad-ai-renderer/actions/workflows/ci.yml/badge.svg)](https://github.com/youyouhdhd/cad-ai-renderer/actions/workflows/ci.yml)
[![Code license: MIT](https://img.shields.io/badge/code%20license-MIT-yellow.svg)](LICENSE)
[简体中文](README.zh-CN.md)
[Roadmap](ROADMAP.md)

Open-source Codex Skill for geometry-anchored CAD-to-product visualization, with [GPT Image 2](https://developers.openai.com/api/docs/guides/image-generation) as a primary reference target.

CAD AI Renderer gives Codex a reproducible workflow for turning STEP/STP and supported mesh files into deterministic CAD evidence, then using that evidence to guide high-quality product visualization through the host image-generation capability. GPT Image 2 is the primary reference target when the host exposes it; the Skill itself remains model-neutral and does not call a raw image API, require an API key, or hard-code a model ID.

## Why this matters

AI image generation can make a product look plausible while quietly drifting from CAD: hole locations, silhouette, part count, seams, and proportions are easy to lose. CAD AI Renderer turns the model into deterministic, inspectable geometry evidence and a structured, auditable generation handoff, so appearance exploration is flexible without silently becoming the source of truth for geometry.

## Why a Skill?

CAD-to-image rendering is not a single prompt. It is a repeatable agent workflow involving attachment discovery, dependency setup, geometry conversion, camera selection, auxiliary rendering, prompt construction, candidate comparison, geometry review, and final selection.

Packaging that process as a Codex Skill keeps the behavior reusable, inspectable, and testable. The repository separates the deterministic CAD evidence layer from the host-controlled generative image layer, so a change in image-model availability does not silently change the geometry contract.

## Designed for Codex + GPT Image 2

Codex orchestrates the multi-step workflow and reasoning around CAD evidence, references, rendering intent, candidate generation, and visual review. The deterministic pipeline prepares the structural evidence; the host image-generation capability performs visual synthesis.

```text
STEP / STP / mesh
        │
        ▼
      Codex
        │
        ▼
CAD AI Renderer Skill
        │
        ├── model discovery and conversion
        ├── camera selection and geometry previews
        ├── silhouette / lineart / depth / normal evidence
        └── part-ID, topology, hole, seam, and proportion checks
        │
        ▼
structured image-generation handoff
        │
        ▼
GPT Image 2 or another host-supported image capability
        │
        ▼
candidate staging → visual QA → selected final image
```

GPT Image 2 can provide materials, lighting, reflections, environment, and presentation quality. The CAD evidence remains the auditable structural reference; the generated beauty image remains a structure-guided approximation, not a dimensional CAD verification artifact.

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

The canonical single-view run layout is `auxiliary/`, `planning/`, `candidates/`, and `final/`. When no output viewpoint is specified, the default layout additionally contains independent `views/<view-id>/` bundles for front, back, left, right, top, bottom, and upper/lower axonometric directions. The reserved Windows device name `aux/` is intentionally not used.

## Supported inputs

| Input | Role |
| --- | --- |
| `.step`, `.stp` | Preferred CAD model input |
| `.glb`, `.gltf`, `.obj`, `.stl`, `.ply`, `.3mf` | Supported mesh inputs when conversion succeeds |
| `.png`, `.jpg`, `.jpeg`, `.webp`, `.bmp`, `.tif`, `.tiff` | Optional material, lighting, style, or camera references |
| Natural-language intent | Rendering brief supplied by the host/user |

## Using it as a Codex Skill

This repository is designed to be installed and invoked as the reusable `$cad-ai-renderer` Skill. Give Codex:

1. a STEP/STP or supported mesh model;
2. optional material, lighting, camera, or style references; and
3. a natural-language rendering brief.

The Skill prepares deterministic CAD evidence and a structured handoff. When no output viewpoint is specified, it prepares the full default directional view set. Beauty-image synthesis defaults to the official Codex `$imagegen` Skill with a 4K, high-quality, high-detail target; if the host cannot expose exact 4K controls, it must use the highest supported resolution and report the actual dimensions.

Example request:

> Use `$cad-ai-renderer` with this STEP file. With no specified viewpoint, prepare front/back/left/right/top/bottom and upper/lower axonometric outputs. Use the official Codex `$imagegen` Skill to create four 4K, high-detail candidates per view, compare them against the CAD evidence, and select each view after visual QA.

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

The `--width/--height` values control deterministic CAD evidence. Final images target 4K through the official Codex `$imagegen` Skill by default. Use `--host-skill imagegen --target-resolution 4k --detail-level high` to make the defaults explicit. If no output viewpoint is specified, inspect each generated view bundle under `views/<view-id>/` and stage/finalize each view independently.

For a first pass, stop after the camera grid with `--grid-only`. The host should inspect `planning/camera_selection_prompt.txt`; if no reference fixes a single camera, preserve the full default view set instead of selecting only one hero angle.

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

The Python package stops at a structured handoff. The official Codex `$imagegen` Skill is responsible for beauty-image synthesis by default. `planning/imagegen_request.json`, `planning/input_roles.json`, and `planning/final_prompt.txt` describe the handoff, including the 4K/high-detail target, without embedding a model lock or API credential.

GPT Image 2 is an integration target and evaluation reference, not a bundled dependency. The repository does not directly invoke the OpenAI Images API; this keeps credentials, model availability, and host policy outside the Skill package.

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
ROADMAP.md                      Public reliability, evaluation, and Skill-experience roadmap
.github/                         CI, issue forms, and contribution templates
```

## Example assets and rights

The example under `examples/steam-controller-2026/` is included to make the workflow concrete. The model file is the user-supplied `SC_solid_stp_20260429.stp`, associated with the Printables listing [Steam Controller 2026 STEP model + puck](https://www.printables.com/model/1577616-steam-controller-2026-step-model-puck). The listing currently identifies the model license as **Creative Commons — Public Domain**. See the example's `README.md` and `THIRD_PARTY_NOTICES.md` for scope and attribution notes.

The example render images and deterministic auxiliary maps are demonstration artifacts. They are not claims that an AI-generated image is a dimensionally exact CAD representation.

## Public visual example

The committed Steam Controller example shows one complete evidence-to-image path without publishing workstation manifests or host credentials:

| Stage | Public artifact |
| --- | --- |
| Source CAD | [STEP model](examples/steam-controller-2026/model/SC_solid_stp_20260429.stp) |
| Front candidates | [contact sheet](examples/steam-controller-2026/renders/front/contact_sheet.png) |
| Front selected image | [representative render](examples/steam-controller-2026/renders/front/best.png) |
| Front geometry evidence | [camera grid and auxiliary passes](examples/steam-controller-2026/renders/front/auxiliary/) |
| Rear selected image | [representative render](examples/steam-controller-2026/renders/rear/best.png) |
| Rear geometry evidence | [camera grid and auxiliary passes](examples/steam-controller-2026/renders/rear/auxiliary/) |

The example makes the intended boundary visible: the CAD model and auxiliary maps are deterministic evidence, while the beauty renders are reference outputs that may vary when the host image-generation stage is repeated.

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
