# Pipeline and Planning Schemas

## End-to-end sequence

```text
Conversation attachments
  -> input discovery
  -> automatic compatible-Python bootstrap
  -> resumable dedicated virtual environment
  -> one editable reference/generation plan
  -> user confirmation gate
  -> STEP/mesh to GLB
  -> low-resolution deterministic reference-view grid
  -> candidate-resolution per-view auxiliary passes
  -> final-refinement high-resolution per-view auxiliary passes
  -> host reference analysis and render brief
  -> geometry_contract + scene_contract + output_contract
  -> frozen render_contract (authoritative)
  -> official image-generation skill/tool
  -> exact candidates from generation_plan.views
  -> candidate staging + native-size report (no final image)
  -> host visual QA
  -> visual-QA-backed candidate selection
  -> one frozen final-refinement generation
  -> final-master staging + final QC
  -> exact-dimension delivery + resolution report
  -> optional single contract-delta retry
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

When no output viewpoint is specified, the default `camera.view_set: all` expands to fourteen named views:

- `front`, `right`, `back`, `left`, `top`, and `bottom` principal views using the `+X`, `+Y`, `-X`, `-Y`, `+Z`, and `-Z` coordinate conventions.
- Four upper and four lower axonometric views covering all horizontal quadrants.

The host may explicitly request a subset with `selected_view_ids`. A multi-view camera plan uses this shape:

```json
{
  "view_set": "all",
  "selected_view_ids": ["front", "right", "back", "left", "top", "bottom"],
  "rationale": "No reliable reference fixed a single output camera; preserve directional coverage.",
  "source": "host_visual_analysis"
}
```

Treat this camera plan as camera evidence and reference-view guidance. Do not multiply final image
generation from it; the confirmed `render_plan.json` and its `generation_plan.views` control final
candidate count and output views.

The local preparation creates `views/<view-id>/` bundles. Each bundle has its own camera, auxiliary passes, prompt, candidates, visual QA, and final output; never mix cameras between bundles.

## Render plan schema and candidate policy

Run `python scripts/run.py plan ...` before `prepare`. It writes the one user-editable
`planning/render_plan.json`. Preparation refuses to proceed until the user sets
`confirmation.confirmed` to `true` and passes the same file with `--plan`.

The plan intentionally separates deterministic CAD reference coverage from final image generation:

```json
{
  "schema_version": "1.1",
  "status": "awaiting_user_confirmation",
  "confirmation": {"required": true, "confirmed": false},
  "reference_plan": {
    "view_set": "all",
    "view_ids": ["front", "right", "back", "left", "top", "bottom"],
    "primary_view_ids": ["front"],
    "generate_extra_views_for_geometry_evidence": true
  },
  "generation_plan": {
    "views": [
      {"view_id": "front", "candidate_count": 1, "candidate_ids": ["C01"]},
      {"view_id": "back", "candidate_count": 1, "candidate_ids": ["C02"]},
      {"view_id": "left", "candidate_count": 1, "candidate_ids": ["C03"]},
      {"view_id": "front_right_axonometric_upper", "candidate_count": 1, "candidate_ids": ["C04"]}
    ],
    "total_candidate_count": 4
  },
  "final_output": {
    "width": 3840,
    "height": 2160,
    "format": "png",
    "resize_policy": "fit_pad",
    "allow_upscale": true,
    "exact_dimensions_required": true
  }
}
```

Rules:

- No user-specified view: keep broad reference coverage, but generate exactly four final candidates total—front, back, left, and one upper axonometric.
- User-specified view: generate four candidates in that view by default.
- User-specified view plus quantity: generate that quantity in that view.
- A user-specified view is the first/highest-priority reference view and cannot be silently replaced by a host camera suggestion.
- User edits to the plan are authoritative. Keep candidate IDs unique across the plan and make `total_candidate_count` equal the listed IDs.

## Frozen render contract

Preparation compiles the confirmed plan and host brief into machine-authoritative files:

```text
camera_plan.json
reference_roles.json
geometry_contract.json
scene_contract.json
output_contract.json
        -> render_contract.json
        -> final_prompt.txt + imagegen_request.json + host_handoff.json
```

`render_contract.json` contains `contract_id`, `contract_revision`, `config_fingerprint`, component hashes, a semantic `frozen_snapshot`, `frozen_fields`, `mutable_fields`, stage-aware anchor policy, retry policy, exact final pixels, and the requested native-size policy. Every later command validates the contract hash and frozen component revisions before changing state.

Prompts are projections, not authority. Host calls must read `imagegen_request.json.tool_parameters` and pass supported fields as actual tool arguments. Camera, input order, candidate count, aspect ratio, requested native size, and exact final pixels must not be reconstructed from chat.

## Geometry contract

Each constraint records:

```json
{
  "id": "geometry.holes-seams-controls",
  "statement": "Preserve every visible modeled hole, seam, control, opening, and small feature.",
  "severity": "hard",
  "prompt_priority": 97,
  "preservation_space": "both",
  "view_behavior": "verify_only_when_visible",
  "source": "CAD lineart and color preview",
  "verification_method": "feature_inventory_host_visual_qa"
}
```

Use the same constraints for candidate prompts, retry prompts, candidate QA, final QC, and reports.

## Native generation versus final delivery

`output_contract.json` separates:

```text
generation.requested_native_size
generation.tool_parameters
final_output.width
final_output.height
final_output.resize_policy
```

`auto` native size means the host uses its highest supported size matching the frozen aspect ratio and records the returned pixels. Exact final dimensions are enforced only after final refinement. Resampling and upscaling are reported explicitly; neither counts as native resolution.

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

## Final QC schema

After `refine-stage`, copy/fill `planning/final_qc.template.json` as `planning/final_qc.host.json`:

```json
{
  "candidate_id": "F01",
  "approve_delivery": true,
  "geometry_score": 92,
  "visual_quality_score": 94,
  "visual_quality_pass": true,
  "contract_consistency_pass": true,
  "geometry_failures": [],
  "issues": [],
  "strengths": ["Camera and openings preserved", "Clean final material detail"],
  "decision_summary": "F01 preserves the frozen contract and is approved for exact-pixel delivery."
}
```

Final QC cannot waive contract consistency. `finish` combines the local final-anchor diagnostic with host geometry QA, evaluates visual quality, performs exact-size delivery, and records every gate in `final/final_qc.json`.

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

Staging returns `awaiting_visual_qa`, writes `candidate_resolution_report.json`, and must not create `final/best.*`. After host review:

```bash
python scripts/run.py finalize --run ./output \
  --visual-qa ./output/planning/visual_qa.host.json
```

Candidate finalization automatically reuses stable files from `candidates/images/`, writes `final/selection.json` and `planning/final_refine_request.json`, and returns `awaiting_final_refinement`. It must not create `final/best.*`.

Generate one final master from the refine request, then:

```bash
python scripts/run.py refine-stage --run ./output --master F01=/returned/final-master.png
python scripts/run.py finish --run ./output --final-qa ./output/planning/final_qc.host.json
```

`finish` writes `final/best.*`, `final/resolution_report.json`, `final/final_qc.json`, and the idempotent report. Pure `complete` requires geometry, native resolution, exact delivery resolution, visual quality, and contract consistency to pass. Non-native exact delivery uses a specific resampled/upscaled status.

Use `planning/host_handoff.json` as the machine-readable source for every argument array. Candidate selection rewrites it for final refinement; `finish` overwrites `final/report.md` from structured artifacts.

## Retry delta

Retry exactly once and only from `retry_delta.template.json`. Require the source contract revision, explicit geometry failures, and `anchor_mode=max_geometry`. Reject camera, crop, geometry contract, reference roles, aspect ratio, candidate count, anchor resolution, or final-dimension changes. The revised contract keeps the same ID, increments the revision once, and labels replacement candidates `R01` onward.

## Geometry gate

Blend local diagnostics and visual QA using `qa.local_weight` and `qa.visual_weight`. The default weights are 0.35 and 0.65. The local score is deliberately subordinate because segmentation and edge extraction can be fooled by backgrounds, reflections, or dark materials.

When nothing passes the threshold, select the least-drifted image but mark the run with a geometry warning.
