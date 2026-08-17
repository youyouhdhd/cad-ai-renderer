# Pipeline and Planning Schemas

## End-to-end sequence

```text
Conversation attachments
  -> input discovery
  -> automatic compatible-Python bootstrap
  -> resumable dedicated virtual environment
  -> STEP/mesh to GLB
  -> deterministic view grid
  -> host camera selection
  -> auxiliary passes
  -> host reference analysis and render brief
  -> official image-generation skill/tool
  -> four candidates
  -> candidate staging and local diagnostics (no final image)
  -> host visual QA
  -> visual-QA-backed final selection and idempotent report
  -> optional single strict retry
```

## Camera plan schema

Write `planning/camera_plan.host.json`:

```json
{
  "selected_view_id": "V06",
  "azimuth": 225.0,
  "elevation": 15.0,
  "projection": "perspective",
  "fov_deg": 45.0,
  "framing": 0.82,
  "roll": 0.0,
  "confidence": 0.86,
  "reference_camera_detected": true,
  "rationale": "V06 most closely matches the attached three-quarter reference while keeping the rear opening visible.",
  "source": "host_visual_analysis"
}
```

Prefer `selected_view_id`. Small angle refinements are acceptable when justified. Keep FOV from 24 to 75 and framing from 0.65 to 0.90.

## Reference roles schema

Write `planning/reference_roles.host.json`:

```json
{
  "references": [
    {
      "reference_index": 0,
      "image_index": 1,
      "roles": ["material", "color", "lighting"],
      "allowed_use": "Use the satin metal, dark polymer, and broad softbox reflection.",
      "forbidden_use": "Ignore the reference object's geometry, controls, seams, and accessory cable.",
      "notes": "Do not use its camera.",
      "confidence": 0.9
    }
  ]
}
```

`reference_index` is zero-based and follows attachment order. `image_index` is one-based for human-readable prompts.

## Render brief schema

Write `planning/render_brief.host.json`:

```json
{
  "object_interpretation": "Compact manufactured appliance housing; exact function uncertain.",
  "reference_analysis": [],
  "assumptions": ["The internal pseudo colors identify parts only."],
  "material_plan": [
    {
      "region": "main shell",
      "material": "powder-coated aluminum",
      "finish": "fine satin texture",
      "evidence": "user text and reference 1"
    }
  ],
  "color_plan": [
    {
      "region": "main shell",
      "color": "warm off-white",
      "source": "user"
    }
  ],
  "lighting_plan": {
    "setup": "large soft key plus weak fill and rim",
    "direction": "upper left",
    "contrast": "medium-low",
    "shadow": "soft grounded contact shadow"
  },
  "environment_plan": {
    "type": "studio",
    "description": "premium neutral product studio",
    "background": "warm light gray seamless"
  },
  "camera_constraints": ["Match the selected CAD camera."],
  "geometry_constraints": ["Preserve every modeled opening and seam."],
  "style_targets": ["photoreal", "commercial product photography"],
  "negative_constraints": ["no added buttons", "no text", "no accessories"],
  "generation_prompt_core": "A detailed production-ready rendering direction.",
  "source": "host_visual_analysis"
}
```

## Visual QA schema

After the `stage` command creates the contact sheet and QA prompt, copy/fill `planning/visual_qa.template.json` as `planning/visual_qa.host.json`:

```json
{
  "candidates": [
    {
      "candidate_id": "C01",
      "geometry_score": 91,
      "overall_score": 88,
      "material_score": 90,
      "lighting_score": 87,
      "artifact_score": 92,
      "geometry_failures": [],
      "strengths": ["Correct camera", "All openings retained"]
    }
  ],
  "best_candidate_id": "C01",
  "retry_recommended": false,
  "retry_instructions": [],
  "decision_summary": "C01 is the strongest geometry-passing render."
}
```

Score candidates independently against CAD. Do not rank only by attractiveness.

## Candidate IDs

Use:

- Initial batch: `C01`, `C02`, ...
- Single retry batch: `R01`, `R02`, ...

Pass returned generator paths directly to staging; no manual pre-copy is required:

```bash
python scripts/run.py stage --run ./output \
  --candidate C01=/returned/path/C01.png \
  --candidate C02=/returned/path/C02.png
```

Staging returns `awaiting_visual_qa` and must not create `final/best.*`. After host review:

```bash
python scripts/run.py finalize --run ./output \
  --visual-qa ./output/planning/visual_qa.host.json
```

Finalization automatically reuses the stable files copied into `candidates/images/` by `stage`. Repeat `--candidate` only when intentionally replacing or adding a candidate.

Use `planning/host_handoff.json` as the machine-readable source for these argument arrays. Finalization overwrites `final/report.md` from structured artifacts, so reruns are idempotent and never append contradictory selection sections.

## Geometry gate

Blend local diagnostics and visual QA using `qa.local_weight` and `qa.visual_weight`. The default weights are 0.35 and 0.65. The local score is deliberately subordinate because segmentation and edge extraction can be fooled by backgrounds, reflections, or dark materials.

When nothing passes the threshold, select the least-drifted image but mark the run with a geometry warning.
