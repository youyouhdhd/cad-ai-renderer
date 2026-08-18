# Troubleshooting

## The Skill asks for a YAML file

That is not the normal workflow. Pass attached files directly with `--input`, or let the Skill do so. YAML is only for advanced reproducibility.

## The dedicated environment is not used

Run through:

```bash
python scripts/run.py preflight ...
```

Check `python.inside_virtualenv`, `python.managed_venv`, and `python.managed_venv_mode` in the report. `isolated` means dependencies were installed inside the dedicated environment. `host-linked` means the dedicated interpreter is reusing packages already present in an offline managed runtime. Do not repair by installing globally.

## Package index access is unavailable

The launcher uses short pip retries, then attempts a host-linked dedicated environment only when the current runtime already imports every required package. Use `--isolated-only` to prohibit that fallback. If both paths fail, install compatible packages in a user-controlled Python/conda environment and point `CAD_AI_RENDERER_VENV` to it.

## CadQuery cannot import the STEP assembly

The converter falls back to single-shape import. If both paths fail, install FreeCADCmd and keep `geometry.converter: auto` or select `freecad`. The fallback loses source colors and assembly IDs.

## VTK reports an X/OpenGL warning

Check whether the PNG outputs exist and contain variation. Offscreen rendering can succeed despite a warning. Prefer EGL/OSMesa-enabled VTK in minimal Linux containers.

## The model is clipped or tiny

Inspect `auxiliary/model_manifest.json` bounds. Remove distant construction geometry or export a clean assembly. Adjust `camera.framing` only after checking units and bounds.

## The preview is gray

Check `source_has_useful_colors`. For a colorless model, pseudo colors identify parts and clay communicates surface form. A fused single solid may not have reliable part segmentation.

## The final image copies a reference object's geometry

Narrow the reference roles, strengthen `forbidden_use`, and retry with `max_geometry`. Remove redundant conflicting references. Name the exact copied feature in the strict prompt.

## Technical maps confuse the generator

Return to `balanced`: color preview + clay + lineart. Use normal/depth/mask only for a targeted retry.

## The official image-generation tool is unavailable

Return the preparation bundle and prompt. Do not request an API key or silently switch backends.

## No candidate passes geometry QA

Review the contact sheet at full resolution. Name exact errors and apply one `retry_delta.json` against the current contract revision with `anchor_mode=max_geometry`. Do not change camera, geometry contract, anchor resolutions, reference roles, aspect ratio, candidate count, or final dimensions, and do not lower the threshold merely to report success.

## The ambient `python` is 3.9 or otherwise incompatible

Do not enumerate interpreters manually. Run `python scripts/run.py bootstrap` with a long outer timeout. The launcher probes installed 64-bit Python versions, prefers 3.12, and re-launches itself before creating the environment. Set `CAD_AI_RENDERER_BOOTSTRAP_PYTHON` only when automatic discovery cannot find the intended interpreter.

## Bootstrap was interrupted or timed out

Re-run the same command. The owned environment records `installing`/`ready` state atomically, removes dead or foreign-host bootstrap locks, recovers an interrupted host-linked environment, and resumes a partial isolated venv with pip cache. Do not delete the environment or install packages globally.

## Windows reports WinError 267 for an `aux` path

`AUX` is a Windows reserved device name. Current runs use `auxiliary/` everywhere. Do not work around it with a `\\?\` path prefix; VTK may reject the `?` in GLTF URIs. If a copied older package still writes `aux/`, replace it with the current Skill.

## Local diagnostics selected a different image than visual QA

This is expected evidence that local scores are only heuristics. Run `stage` first; it must not create a selection or final image. Then write host visual QA and run `finalize`, which selects a source and writes a final-refinement request. Only `finish` after final QC may create `final/best.*`. Never use local-only selection unless explicitly required and warning-marked.

## The report contains repeated candidate sections

Candidate selection and final finish rebuild reports rather than appending. Re-run the structured stage instead of hand-editing reports; they are generated from the frozen contract, candidate scores/QA, final QC, and resolution report.

## Exact pixels exist but native 4K is false

Read `final/resolution_report.json`. `delivered_final_size` proves the exact file dimensions; `actual_native_size`, `resampled`, `upscaled`, and `target_met_natively` describe how they were achieved. `complete_exact_dimensions_upscaled` is a successful exact-size delivery, not a native-4K claim.

## Frozen contract mismatch

Do not edit `camera_plan.json`, `render_brief.json`, `input_roles.json`, or component contracts after freezing. Start a new render plan for frozen-field changes. Use a revisioned retry delta only for explicit geometry failures and allowed appearance/lighting changes.
