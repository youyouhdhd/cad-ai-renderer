#!/usr/bin/env python3
"""Prompt construction for attachment analysis, image generation, and visual QA."""

from __future__ import annotations

import json
from typing import Any, Mapping, Sequence

REFERENCE_ROLE_VOCAB = [
    "camera",
    "composition",
    "material",
    "color",
    "lighting",
    "style",
    "environment",
    "detail",
    "mixed",
]


def reference_role_prompt(reference_count: int, project_description: str) -> str:
    return f"""Analyze {reference_count} user-attached image(s) for a CAD-to-image rendering task.

Project intent:
{project_description or 'No explicit appearance description was supplied.'}

For each attached reference, classify only the evidence it can reliably provide. Allowed roles are:
{', '.join(REFERENCE_ROLE_VOCAB)}.

A reference may have several roles. A colored screenshot from a 3D application may provide camera,
composition, color blocks, and rough material intent. A single photograph may provide material,
lighting, style, and environment while being unsuitable as geometry truth. Never use a reference
object to replace CAD topology, proportions, holes, seams, controls, part count, or accessories.

Return JSON with this structure:
{{
  "references": [
    {{
      "image_index": 1,
      "roles": ["material", "lighting"],
      "allowed_use": "...",
      "forbidden_use": "...",
      "notes": "...",
      "confidence": 0.0
    }}
  ]
}}
"""


def camera_selection_prompt(
    view_records: Sequence[Mapping[str, Any]],
    project_description: str,
    references: Sequence[Mapping[str, Any]],
    default_multi_view: bool = False,
) -> str:
    view_summary = [
        {
            "view_id": item["view_id"],
            "label": item.get("label", item["view_id"]),
            "view_type": item.get("view_type", "grid"),
            "axis": item.get("axis"),
            "azimuth": item["azimuth"],
            "elevation": item["elevation"],
            "projection": item.get("projection", "perspective"),
        }
        for item in view_records
    ]
    reference_summary = [
        {
            "image_index": index + 2,
            "roles": ref.get("roles", ["mixed"]),
            "notes": ref.get("notes", ""),
        }
        for index, ref in enumerate(references)
    ]
    multi_view_policy = (
        "If the user did not specify an output viewpoint and no reliable reference fixes one, preserve the full default view set. Return `view_set: all` and a `selected_view_ids` list containing every required principal and axonometric view; do not collapse the job to one hero angle."
        if default_multi_view
        else "If one camera is required, select the clearest available view and do not invent a semantic front/back label that the CAD coordinate system cannot support."
    )
    return f"""Act as the camera director for a CAD-to-image rendering workflow.

Image 1 is a contact sheet of deterministic CAD views with the labels listed below.
Images 2 onward are optional user references.

Project intent:
{project_description or 'No additional project description was supplied.'}

Available views:
{json.dumps(view_summary, indent=2, ensure_ascii=False)}

Reference roles:
{json.dumps(reference_summary, indent=2, ensure_ascii=False)}

Select the view or view set that best matches any reliable camera/composition evidence. {multi_view_policy}
Do not change the object's geometry for aesthetic reasons.

Return JSON:
{{
  "selected_view_id": "V02",
  "selected_view_ids": ["front", "right", "back", "left", "top", "bottom"],
  "view_set": "all",
  "azimuth": 45.0,
  "elevation": 30.0,
  "projection": "perspective",
  "fov_deg": 45.0,
  "framing": 0.82,
  "confidence": 0.0,
  "rationale": "one concise paragraph",
  "reference_camera_detected": false
}}

Prefer available views. For a single view, allow at most a small correction of 12 degrees. Keep fov_deg
from 24 to 75 and framing from 0.65 to 0.90. Use coordinate-axis labels as orientation evidence when
the CAD model has no user-defined semantic front.
"""


def render_brief_prompt(
    model_manifest: Mapping[str, Any],
    project_description: str,
    references: Sequence[Mapping[str, Any]],
    anchor_labels: Sequence[str],
) -> str:
    ref_start = len(anchor_labels) + 1
    reference_summary = [
        {
            "image_index": ref_start + index,
            "roles": ref.get("roles", ["mixed"]),
            "notes": ref.get("notes", ""),
        }
        for index, ref in enumerate(references)
    ]
    compact_manifest = {
        "source_name": model_manifest.get("source_name"),
        "part_count": model_manifest.get("part_count"),
        "bbox_mm": model_manifest.get("bbox_mm"),
        "source_has_useful_colors": model_manifest.get("source_has_useful_colors"),
        "parts": [
            {
                "name": part.get("name"),
                "shape_type": part.get("shape_type"),
                "color_rgba": part.get("color_rgba"),
            }
            for part in (model_manifest.get("parts") or [])[:80]
        ],
    }
    anchor_summary = [
        {"image_index": index + 1, "role": label}
        for index, label in enumerate(anchor_labels)
    ]
    return f"""Act as an expert industrial-design rendering director. Analyze the deterministic CAD
anchors and all attached reference images, then create a production-ready rendering brief for the
host's official image-generation capability.

CAD anchors are geometry truth. References are soft evidence for material, color, lighting, style,
environment, detail, camera, or composition only. Never borrow geometry, topology, part count, holes,
seams, controls, proportions, or accessories from a reference.

Project description:
{project_description or 'Infer a conservative, commercially plausible premium presentation.'}

Model manifest:
{json.dumps(compact_manifest, indent=2, ensure_ascii=False)}

CAD anchor image order:
{json.dumps(anchor_summary, indent=2, ensure_ascii=False)}

Reference image roles:
{json.dumps(reference_summary, indent=2, ensure_ascii=False)}

Policies:
- With zero references, infer restrained materials and neutral controlled lighting; record assumptions.
- With one mixed reference, separate reliable evidence from content that must be ignored.
- If the CAD is colorless, pseudo-colors identify parts and are not final colors unless requested.
- Preserve visible geometry, silhouette, camera, object placement, and major CAD color blocks.

Return JSON:
{{
  "object_interpretation": "...",
  "reference_analysis": [
    {{"image_index": 5, "roles": ["material"], "use": "...", "ignore": "...", "confidence": 0.0}}
  ],
  "assumptions": ["..."],
  "material_plan": [{{"region": "...", "material": "...", "finish": "...", "evidence": "..."}}],
  "color_plan": [{{"region": "...", "color": "...", "source": "CAD|reference|inferred"}}],
  "lighting_plan": {{"setup": "...", "direction": "...", "contrast": "...", "shadow": "..."}},
  "environment_plan": {{"type": "studio|contextual", "description": "...", "background": "..."}},
  "camera_constraints": ["..."],
  "geometry_constraints": ["..."],
  "style_targets": ["..."],
  "negative_constraints": ["..."],
  "generation_prompt_core": "a detailed production-ready prompt"
}}
"""


def build_generation_prompt(
    brief: Mapping[str, Any],
    input_roles: Sequence[Mapping[str, Any]],
    project_description: str,
    strict_geometry: bool = False,
) -> str:
    role_lines = [
        f"Image {item['image_index']}: {item['role']}. Allowed: {item.get('allowed_use', '')}. "
        f"Forbidden: {item.get('forbidden_use', '')}."
        for item in input_roles
    ]
    strict_block = ""
    if strict_geometry:
        strict_block = """
GEOMETRY RECOVERY PASS:
The earlier candidates drifted. Match the CAD lineart, silhouette mask, camera, proportions, visible
topology, holes, seams, part boundaries, and occlusion order before improving appearance. Do not move,
add, remove, widen, narrow, bend, merge, or duplicate a modeled feature. Geometry anchors override all
style preferences when evidence conflicts.
"""
    core = str(brief.get("generation_prompt_core", "Create a high-end photoreal product rendering."))
    return f"""Create one finished, high-quality product visualization from the supplied images.

INPUT IMAGE ROLE CONTRACT:
{chr(10).join(role_lines)}

PRIORITY:
1. CAD camera, silhouette, visible topology, proportions, part placement, and occlusion.
2. Explicit user intent and genuine CAD color evidence.
3. Reference materials, color, lighting, environment, and style only inside declared roles.
4. Conservative inference for missing information.

Never average geometry across references. Never copy a reference object's shape. Lineart and masks are
structural evidence, not the desired illustration style. Normal/depth colors are not final colors.
Pseudo-colors are part identifiers unless the user explicitly adopts them.
{strict_block}
PROJECT INTENT:
{project_description or 'Premium, physically plausible product visualization.'}

RENDER DIRECTION:
{core}

ASSUMPTIONS:
{json.dumps(brief.get('assumptions', []), ensure_ascii=False)}

MATERIAL PLAN:
{json.dumps(brief.get('material_plan', []), ensure_ascii=False)}

COLOR PLAN:
{json.dumps(brief.get('color_plan', []), ensure_ascii=False)}

LIGHTING:
{json.dumps(brief.get('lighting_plan', {}), ensure_ascii=False)}

ENVIRONMENT:
{json.dumps(brief.get('environment_plan', {}), ensure_ascii=False)}

GEOMETRY CONSTRAINTS:
{json.dumps(brief.get('geometry_constraints', []), ensure_ascii=False)}

NEGATIVE CONSTRAINTS:
{json.dumps(brief.get('negative_constraints', []), ensure_ascii=False)}

Output one coherent final image. Use realistic materials, controlled highlights, clean edges, credible
contact shadows, no watermark, no collage, no exploded view, and no unrequested text or accessories.
"""


def qa_prompt(
    candidate_ids: Sequence[str],
    project_description: str,
    local_scores: Sequence[Mapping[str, Any]],
) -> str:
    return f"""Act as the final visual quality judge.

Image order:
1. CAD lineart.
2. CAD silhouette mask.
3. CAD color or pseudo-color preview.
4. CAD normal map.
5 onward. Candidates in this exact order: {', '.join(candidate_ids)}.

Project intent:
{project_description or 'Premium product visualization while preserving CAD geometry.'}

Local computer-vision diagnostics are weak evidence only:
{json.dumps(list(local_scores), indent=2, ensure_ascii=False)}

Evaluate every candidate against the CAD anchors. Geometry is the gate: camera, silhouette, proportions,
part count, holes, seams, controls, topology, and occlusion. Then evaluate material plausibility,
lighting, artifacts, composition, and prompt compliance.

Return JSON:
{{
  "candidates": [
    {{
      "candidate_id": "{candidate_ids[0] if candidate_ids else 'C01'}",
      "geometry_score": 0.0,
      "overall_score": 0.0,
      "material_score": 0.0,
      "lighting_score": 0.0,
      "artifact_score": 0.0,
      "geometry_failures": ["..."],
      "strengths": ["..."]
    }}
  ],
  "best_candidate_id": "{candidate_ids[0] if candidate_ids else 'C01'}",
  "retry_recommended": false,
  "retry_instructions": ["name exact geometry errors"],
  "decision_summary": "..."
}}
"""
