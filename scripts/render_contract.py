#!/usr/bin/env python3
"""Frozen render-contract construction and consistency validation.

The contract is the authoritative machine input for candidate generation,
targeted retries, final refinement, and final delivery. Prompts and host
handoffs are compiled projections of this file, not independent sources of
truth.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping, Sequence


CONTRACT_SCHEMA_VERSION = "1.0"
GEOMETRY_CONTRACT_VERSION = "1.0"
OUTPUT_CONTRACT_VERSION = "1.0"
RETRY_DELTA_VERSION = "1.0"


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _read_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _canonical_bytes(payload: Any) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def payload_sha256(payload: Any) -> str:
    return hashlib.sha256(_canonical_bytes(payload)).hexdigest()


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolution_dict(value: Any, fallback_width: int, fallback_height: int) -> dict[str, int]:
    if isinstance(value, Mapping):
        return {
            "width": int(value.get("width") or fallback_width),
            "height": int(value.get("height") or fallback_height),
        }
    if isinstance(value, (list, tuple)) and len(value) == 2:
        return {"width": int(value[0]), "height": int(value[1])}
    return {"width": int(fallback_width), "height": int(fallback_height)}


def derive_final_size(target_resolution: str, aspect_ratio: str) -> tuple[int, int]:
    target = str(target_resolution or "4k").lower()
    aspect = str(aspect_ratio or "auto").lower()
    if target == "2k":
        long_edge = 2048
        square_edge = 2048
    elif target == "4k":
        long_edge = 3840
        square_edge = 4096
    else:
        long_edge = 3840
        square_edge = 4096
    sizes = {
        "1:1": (square_edge, square_edge),
        "4:3": (long_edge, int(round(long_edge * 3 / 4))),
        "3:4": (int(round(long_edge * 3 / 4)), long_edge),
        "16:9": (long_edge, int(round(long_edge * 9 / 16))),
        "9:16": (int(round(long_edge * 9 / 16)), long_edge),
        "auto": (long_edge, int(round(long_edge * 9 / 16))),
    }
    return sizes.get(aspect, sizes["auto"])


def build_output_contract(config: Mapping[str, Any], candidate_ids: Sequence[str]) -> dict[str, Any]:
    generation = config.get("generation", {})
    final_cfg = config.get("final_output", {})
    derived_width, derived_height = derive_final_size(
        str(generation.get("target_resolution", "4k")),
        str(generation.get("aspect_ratio", "auto")),
    )
    width = int(final_cfg.get("width") or derived_width)
    height = int(final_cfg.get("height") or derived_height)
    requested_native = str(generation.get("requested_native_size", "auto"))
    tool_parameters: dict[str, Any] = {
        "candidate_count": len(candidate_ids),
        "quality": str(generation.get("quality", "high")),
        "output_format": str(generation.get("output_format", "png")),
    }
    if requested_native != "auto":
        tool_parameters["size"] = requested_native
    return {
        "schema_version": OUTPUT_CONTRACT_VERSION,
        "generation": {
            "requested_native_size": requested_native,
            "requested_native_policy": (
                "exact_tool_parameter_when_supported"
                if requested_native != "auto"
                else "highest_supported_size_matching_frozen_aspect_ratio"
            ),
            "aspect_ratio": str(generation.get("aspect_ratio", "auto")),
            "quality": str(generation.get("quality", "high")),
            "detail_level": str(generation.get("detail_level", "high")),
            "output_format": str(generation.get("output_format", "png")),
            "candidate_count": len(candidate_ids),
            "candidate_ids": [str(item) for item in candidate_ids],
            "tool_parameters": tool_parameters,
        },
        "final_output": {
            "width": width,
            "height": height,
            "format": str(final_cfg.get("format") or generation.get("output_format", "png")),
            "resize_policy": str(final_cfg.get("resize_policy", "fit_pad")),
            "allow_upscale": bool(final_cfg.get("allow_upscale", True)),
            "exact_dimensions_required": True,
        },
        "resolution_gate": {
            "require_exact_delivery_dimensions": True,
            "native_pass_requires_exact_dimensions": True,
            "record_resampling": True,
            "record_upscaling": True,
        },
    }


def build_geometry_contract(
    model_manifest: Mapping[str, Any],
    camera_plan: Mapping[str, Any],
    brief: Mapping[str, Any],
) -> dict[str, Any]:
    constraints: list[dict[str, Any]] = [
        {
            "id": "geometry.camera",
            "statement": "Preserve the selected CAD camera, projection, roll, crop, and framing.",
            "severity": "hard",
            "prompt_priority": 100,
            "preservation_space": "image",
            "view_behavior": "per_view_frozen",
            "source": "camera_plan.json",
            "verification_method": "host_camera_match_plus_anchor_overlay",
        },
        {
            "id": "geometry.silhouette",
            "statement": "Preserve the complete visible CAD silhouette and outer proportions.",
            "severity": "hard",
            "prompt_priority": 100,
            "preservation_space": "both",
            "view_behavior": "per_view_frozen",
            "source": "CAD mask and lineart",
            "verification_method": "silhouette_iou_plus_host_visual_qa",
        },
        {
            "id": "geometry.topology",
            "statement": "Preserve visible topology, surface breaks, part count, and occlusion order.",
            "severity": "hard",
            "prompt_priority": 98,
            "preservation_space": "both",
            "view_behavior": "per_view_frozen",
            "source": "CAD lineart, clay, and part ID",
            "verification_method": "host_visual_qa",
        },
        {
            "id": "geometry.holes-seams-controls",
            "statement": "Preserve every visible modeled hole, seam, control, opening, and small feature.",
            "severity": "hard",
            "prompt_priority": 97,
            "preservation_space": "both",
            "view_behavior": "verify_only_when_visible",
            "source": "CAD lineart and color preview",
            "verification_method": "feature_inventory_host_visual_qa",
        },
        {
            "id": "geometry.part-placement",
            "statement": "Do not add, remove, merge, duplicate, mirror, widen, flatten, or move modeled geometry.",
            "severity": "hard",
            "prompt_priority": 96,
            "preservation_space": "object",
            "view_behavior": "all_views",
            "source": "model manifest and CAD anchors",
            "verification_method": "part_count_and_host_visual_qa",
        },
    ]
    for index, statement in enumerate(brief.get("geometry_constraints", []) or [], start=1):
        constraints.append(
            {
                "id": f"geometry.brief-{index:02d}",
                "statement": str(statement),
                "severity": "guarded",
                "prompt_priority": 85,
                "preservation_space": "both",
                "view_behavior": "per_view",
                "source": "render_brief.json",
                "verification_method": "host_visual_qa",
            }
        )
    return {
        "schema_version": GEOMETRY_CONTRACT_VERSION,
        "model_sha256": model_manifest.get("source_sha256"),
        "part_count": int(model_manifest.get("part_count", 0)),
        "bbox_mm": model_manifest.get("bbox_mm"),
        "view_id": camera_plan.get("selected_view_id"),
        "constraints": constraints,
    }


def build_scene_contract(brief: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "appearance_contract": {
            "materials": deepcopy(brief.get("material_plan", [])),
            "colors": deepcopy(brief.get("color_plan", [])),
            "style_targets": deepcopy(brief.get("style_targets", [])),
            "assumptions": deepcopy(brief.get("assumptions", [])),
        },
        "scene_contract": {
            "lighting": deepcopy(brief.get("lighting_plan", {})),
            "environment": deepcopy(brief.get("environment_plan", {})),
            "negative_constraints": deepcopy(brief.get("negative_constraints", [])),
            "generation_direction": str(brief.get("generation_prompt_core", "")),
        },
    }


def _anchor_policy(config: Mapping[str, Any], root: Path) -> dict[str, Any]:
    render = config.get("render", {})
    legacy_width = int(render.get("width", 1024))
    legacy_height = int(render.get("height", 1024))
    output = build_output_contract(config, ["F01"])["final_output"]
    target_width = int(output["width"])
    target_height = int(output["height"])
    long_edge = max(target_width, target_height)
    desired_long_edge = min(4096, max(2048, long_edge))
    adaptive_scale = desired_long_edge / long_edge
    adaptive_final = {
        "width": max(256, int(round(target_width * adaptive_scale))),
        "height": max(256, int(round(target_height * adaptive_scale))),
    }
    return {
        "view_grid_resolution": _resolution_dict(
            render.get("view_grid_resolution"), min(768, legacy_width), min(768, legacy_height)
        ),
        "candidate_anchor_resolution": _resolution_dict(
            render.get("candidate_anchor_resolution"), legacy_width, legacy_height
        ),
        "final_anchor_resolution": _resolution_dict(
            render.get("final_anchor_resolution"), adaptive_final["width"], adaptive_final["height"]
        ),
        "candidate_anchor_mode": str(config.get("geometry", {}).get("anchor_mode", "balanced")),
        "final_anchor_mode": "balanced",
        "candidate_anchor_root": str(root / "auxiliary"),
        "final_anchor_root": str(root / "final_refinement" / "auxiliary"),
    }


def validate_retry_delta(contract: Mapping[str, Any], delta: Mapping[str, Any]) -> dict[str, Any]:
    allowed = {
        "schema_version",
        "retry_from_contract_revision",
        "exact_failures",
        "anchor_mode",
        "appearance_delta",
        "lighting_delta",
        "notes",
    }
    unknown = sorted(set(delta) - allowed)
    if unknown:
        raise ValueError("Retry delta attempts to modify frozen or unsupported fields: " + ", ".join(unknown))
    revision = int(delta.get("retry_from_contract_revision", -1))
    if revision != int(contract.get("contract_revision", 0)):
        raise ValueError("Retry delta contract revision does not match the frozen render contract")
    failures = delta.get("exact_failures")
    if not isinstance(failures, list) or not failures or not all(str(item).strip() for item in failures):
        raise ValueError("Retry delta requires a non-empty exact_failures list")
    if str(delta.get("anchor_mode", "max_geometry")) != "max_geometry":
        raise ValueError("Retry delta must use anchor_mode=max_geometry")
    return {
        "schema_version": RETRY_DELTA_VERSION,
        "retry_from_contract_revision": revision,
        "frozen_fields": list(contract.get("frozen_fields", [])),
        "exact_failures": [str(item).strip() for item in failures],
        "anchor_mode": "max_geometry",
        "appearance_delta": deepcopy(delta.get("appearance_delta", {})),
        "lighting_delta": deepcopy(delta.get("lighting_delta", {})),
        "notes": str(delta.get("notes", "")),
    }


def write_render_contract_bundle(
    run_dir: str | Path,
    *,
    config: Mapping[str, Any],
    config_fingerprint: str,
    model_manifest: Mapping[str, Any],
    camera_plan: Mapping[str, Any],
    brief: Mapping[str, Any],
    input_roles: Sequence[Mapping[str, Any]],
    candidate_ids: Sequence[str],
    retry_delta: Mapping[str, Any] | None = None,
    previous_contract: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    root = Path(run_dir).expanduser().resolve()
    planning = root / "planning"
    geometry_contract = build_geometry_contract(model_manifest, camera_plan, brief)
    scene_bundle = build_scene_contract(brief)
    output_contract = build_output_contract(config, candidate_ids)
    _write_json(planning / "geometry_contract.json", geometry_contract)
    _write_json(planning / "scene_contract.json", scene_bundle)
    _write_json(planning / "output_contract.json", output_contract)

    reference_roles = [
        {
            "reference_index": item.get("reference_index"),
            "role": item.get("role"),
            "allowed_use": item.get("allowed_use"),
            "forbidden_use": item.get("forbidden_use"),
            "source": item.get("source"),
        }
        for item in input_roles
        if item.get("source") == "attachment"
    ]
    anchor_policy = _anchor_policy(config, root)
    frozen_output_contract = deepcopy(output_contract)
    frozen_output_contract["generation"].pop("candidate_ids", None)
    frozen_anchor_policy = deepcopy(anchor_policy)
    frozen_anchor_policy.pop("candidate_anchor_mode", None)
    frozen_input_images = [
        str(item.get("path"))
        for item in input_roles
        if item.get("source") == "attachment"
        or any(token in str(item.get("role", "")).lower() for token in ("color preview", "clay", "lineart"))
    ]
    frozen_snapshot = {
        "camera": deepcopy(dict(camera_plan)),
        "geometry_contract": geometry_contract,
        "output_contract": frozen_output_contract,
        "reference_roles": reference_roles,
        "ordered_input_images": frozen_input_images,
        "anchor_policy": frozen_anchor_policy,
    }
    if previous_contract is not None:
        if frozen_snapshot != previous_contract.get("frozen_snapshot"):
            raise ValueError(
                "Frozen render-contract fields changed after candidate generation. "
                "Camera, geometry, anchors, references, aspect ratio, and final dimensions cannot drift."
            )
        normalized_delta = validate_retry_delta(previous_contract, retry_delta or {})
        contract_id = str(previous_contract["contract_id"])
        revision = int(previous_contract.get("contract_revision", 1)) + 1
    else:
        normalized_delta = None
        contract_seed = {
            "model_sha256": model_manifest.get("source_sha256"),
            "view_id": camera_plan.get("selected_view_id"),
            "config_fingerprint": config_fingerprint,
            "frozen_snapshot": frozen_snapshot,
        }
        contract_id = "rc-" + payload_sha256(contract_seed)[:24]
        revision = 1

    source_files = {
        "planning/camera_plan.json": planning / "camera_plan.json",
        "planning/render_brief.json": planning / "render_brief.json",
        "planning/input_roles.json": planning / "input_roles.json",
        "planning/geometry_contract.json": planning / "geometry_contract.json",
        "planning/scene_contract.json": planning / "scene_contract.json",
        "planning/output_contract.json": planning / "output_contract.json",
    }
    source_revisions = {relative: file_sha256(path) for relative, path in source_files.items()}
    contract: dict[str, Any] = {
        "schema_version": CONTRACT_SCHEMA_VERSION,
        "contract_id": contract_id,
        "contract_revision": revision,
        "state": "frozen_candidate_generation" if revision == 1 else "frozen_retry_generation",
        "config_fingerprint": config_fingerprint,
        "camera_plan_revision": source_revisions["planning/camera_plan.json"],
        "render_brief_revision": source_revisions["planning/render_brief.json"],
        "geometry_contract_revision": source_revisions["planning/geometry_contract.json"],
        "scene_contract_revision": source_revisions["planning/scene_contract.json"],
        "output_contract_revision": source_revisions["planning/output_contract.json"],
        "view_id": camera_plan.get("selected_view_id"),
        "camera": deepcopy(dict(camera_plan)),
        "geometry_contract": geometry_contract,
        "appearance_contract": scene_bundle["appearance_contract"],
        "scene_contract": scene_bundle["scene_contract"],
        "generation": output_contract["generation"],
        "final_output": output_contract["final_output"],
        "anchor_policy": anchor_policy,
        "retry_policy": {
            "max_retries": int(config.get("generation", {}).get("max_retries", 1)),
            "retry_is_contract_patch": True,
            "requires_exact_failures": True,
            "allowed_delta_fields": ["exact_failures", "anchor_mode", "appearance_delta", "lighting_delta", "notes"],
        },
        "frozen_fields": [
            "camera",
            "camera.projection",
            "camera.framing",
            "camera.roll",
            "geometry_contract",
            "generation.aspect_ratio",
            "generation.candidate_count",
            "final_output.width",
            "final_output.height",
            "anchor_policy.view_grid_resolution",
            "anchor_policy.candidate_anchor_resolution",
            "anchor_policy.final_anchor_resolution",
            "anchor_policy.final_anchor_mode",
            "reference_roles",
            "ordered_input_images",
        ],
        "mutable_fields": [
            "appearance_contract.materials",
            "appearance_contract.colors",
            "scene_contract.lighting",
            "anchor_policy.candidate_anchor_mode_on_retry",
        ],
        "frozen_snapshot": frozen_snapshot,
        "source_revisions": source_revisions,
        "retry_delta": normalized_delta,
    }
    contract["contract_hash"] = payload_sha256(contract)
    _write_json(planning / "render_contract.json", contract)
    _write_json(
        planning / "retry_delta.template.json",
        {
            "schema_version": RETRY_DELTA_VERSION,
            "retry_from_contract_revision": revision,
            "exact_failures": [],
            "anchor_mode": "max_geometry",
            "appearance_delta": {},
            "lighting_delta": {},
            "notes": "Only the listed mutable fields may change; every frozen field remains authoritative.",
        },
    )
    return contract


def load_and_validate_render_contract(run_dir: str | Path) -> tuple[dict[str, Any], dict[str, Any]]:
    root = Path(run_dir).expanduser().resolve()
    path = root / "planning" / "render_contract.json"
    if not path.exists():
        raise FileNotFoundError(f"Missing frozen render contract: {path}")
    contract = _read_json(path)
    if not isinstance(contract, Mapping):
        raise ValueError("render_contract.json must contain an object")
    contract = dict(contract)
    expected_hash = str(contract.get("contract_hash", ""))
    unsigned = dict(contract)
    unsigned.pop("contract_hash", None)
    actual_hash = payload_sha256(unsigned)
    mismatches: list[dict[str, str]] = []
    if expected_hash != actual_hash:
        mismatches.append({"field": "contract_hash", "expected": expected_hash, "actual": actual_hash})
    for relative, expected in contract.get("source_revisions", {}).items():
        source_path = root / str(relative)
        actual = file_sha256(source_path) if source_path.exists() else "missing"
        if actual != expected:
            mismatches.append({"field": str(relative), "expected": str(expected), "actual": actual})
    report = {
        "contract_id": contract.get("contract_id"),
        "contract_revision": contract.get("contract_revision"),
        "contract_consistency_pass": not mismatches,
        "mismatches": mismatches,
    }
    if mismatches:
        raise ValueError(
            "Frozen render-contract consistency check failed: "
            + "; ".join(f"{item['field']} expected {item['expected']} got {item['actual']}" for item in mismatches)
        )
    return contract, report


def build_final_refine_request(
    run_dir: str | Path,
    contract: Mapping[str, Any],
    selection: Mapping[str, Any],
) -> dict[str, Any]:
    root = Path(run_dir).expanduser().resolve()
    planning = root / "planning"
    anchor_root = Path(str(contract["anchor_policy"]["final_anchor_root"]))
    anchors = [anchor_root / name for name in ("color_preview.png", "clay.png", "lineart.png")]
    for path in anchors:
        if not path.exists():
            raise FileNotFoundError(f"Missing final-refinement CAD anchor: {path}")
    selected_path = Path(str(selection.get("path", ""))).expanduser().resolve()
    if not selected_path.exists():
        raise FileNotFoundError(f"Selected candidate does not exist: {selected_path}")
    output = contract["final_output"]
    prompt = f"""Create exactly one final master image by refining the selected candidate.

AUTHORITY:
- Frozen render contract: {planning / 'render_contract.json'}
- Contract ID/revision: {contract.get('contract_id')} / {contract.get('contract_revision')}
- Image 1 is the selected candidate and fixes composition, scene, material direction, and object placement.
- Images 2-4 are high-resolution CAD color-preview, clay, and lineart anchors and fix camera, silhouette, topology, holes, seams, controls, and occlusion.

ALLOWED CHANGES:
- Improve only material micro-detail, edge quality, anti-aliasing, reflection smoothness, and clarity.

FROZEN:
- Camera, projection, crop, framing, object placement, geometry, aspect ratio, scene, background, and final pixel contract.
- Do not add, remove, move, merge, duplicate, restyle, relight, or redesign any feature.

FINAL DELIVERY CONTRACT:
- Exact final dimensions: {output['width']}x{output['height']}.
- Preserve the complete product; no crop, collage, labels, logos, watermark, or new props.
"""
    prompt_path = planning / "final_refine_prompt.txt"
    prompt_path.write_text(prompt, encoding="utf-8")
    tool_parameters = deepcopy(contract.get("generation", {}).get("tool_parameters", {}))
    tool_parameters["candidate_count"] = 1
    request = {
        "schema_version": "1.0",
        "stage": "final_refinement",
        "contract_path": str(planning / "render_contract.json"),
        "contract_id": contract.get("contract_id"),
        "contract_revision": contract.get("contract_revision"),
        "candidate_id": "F01",
        "selected_candidate_id": selection.get("candidate_id"),
        "selected_candidate": str(selected_path),
        "prompt_path": str(prompt_path),
        "input_images": [str(selected_path), *[str(path) for path in anchors]],
        "input_roles": [
            "selected candidate; preserve composition, scene, and appearance direction",
            "high-resolution CAD color preview; geometry and occupancy anchor",
            "high-resolution CAD clay; curvature and continuous-form anchor",
            "high-resolution CAD lineart; topology, holes, seams, and edge anchor",
        ],
        "tool_parameters": tool_parameters,
        "requested_native_size": contract.get("generation", {}).get("requested_native_size", "auto"),
        "exact_final_output": deepcopy(output),
        "allowed_changes": ["material micro-detail", "edge quality", "anti-aliasing", "reflection smoothness", "clarity"],
        "frozen_fields": list(contract.get("frozen_fields", [])),
        "instruction": "Generate one final master only. Do not reinterpret the conversation or rewrite contract values.",
    }
    _write_json(planning / "final_refine_request.json", request)
    return request
