#!/usr/bin/env python3
"""Prepare deterministic CAD anchors for the host's official image-generation skill.

This script never calls an image API. It accepts direct attachment paths, creates
view/camera/geometry evidence, and writes a model-neutral image-generation request.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from config import (
    ConfigError,
    build_direct_config,
    config_fingerprint,
    dump_resolved_config,
    load_config,
    product_view_specs,
    validate_config,
)
from host_handoff import write_camera_handoff, write_generation_handoff, write_multi_generation_handoff
from input_discovery import InputDiscoveryError, discover_inputs
from pipeline_prompts import (
    build_generation_prompt,
    camera_selection_prompt,
    reference_role_prompt,
    render_brief_prompt,
)
from render_aux_vtk import VTKAnchorRenderer
from runtime_layout import manifest_paths, output_layout
from step_to_glb import convert_model

PIPELINE_VERSION = "2.2.0"
RENDER_PLAN_VERSION = "1.0"
DEFAULT_FINAL_VIEW_IDS = (
    "front",
    "back",
    "left",
    "front_right_axonometric_upper",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _read_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _log(message: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {message}", flush=True)


def _camera_base(config: Mapping[str, Any]) -> dict[str, Any]:
    camera = config["camera"]
    return {
        "projection": camera.get("projection", "perspective"),
        "azimuth": float(camera.get("azimuth", 35)),
        "elevation": float(camera.get("elevation", 22)),
        "roll": float(camera.get("roll", 0)),
        "fov_deg": float(camera.get("fov_deg", 45)),
        "framing": float(camera.get("framing", 0.82)),
        "target": camera.get("target"),
        "position": camera.get("position"),
        "up": camera.get("up", [0, 0, 1]),
    }


def _sanitize_camera_plan(plan: Mapping[str, Any], base: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(base)
    result.update({key: value for key, value in plan.items() if value is not None})
    result["azimuth"] = float(result.get("azimuth", base.get("azimuth", 35)))
    result["elevation"] = float(result.get("elevation", base.get("elevation", 22)))
    result["fov_deg"] = min(75.0, max(24.0, float(result.get("fov_deg", 45))))
    result["framing"] = min(0.90, max(0.65, float(result.get("framing", 0.82))))
    result["roll"] = float(result.get("roll", base.get("roll", 0)))
    if result.get("projection") not in {"perspective", "orthographic"}:
        result["projection"] = "perspective"
    return result


def _camera_from_view(
    view_records: Sequence[Mapping[str, Any]],
    view_id: str,
    base: Mapping[str, Any],
) -> dict[str, Any]:
    match = next((item for item in view_records if str(item.get("view_id")) == view_id), None)
    if match is None:
        available = ", ".join(str(item.get("view_id")) for item in view_records)
        raise ConfigError(f"Unknown view ID {view_id!r}. Available: {available}")
    plan = dict(base)
    plan.update(
        {
            "selected_view_id": view_id,
            "view_label": match.get("label"),
            "view_type": match.get("view_type"),
            "axis": match.get("axis"),
            "azimuth": float(match["azimuth"]),
            "elevation": float(match["elevation"]),
            "projection": match.get("projection", base.get("projection", "perspective")),
            "source": "host_selected_view_grid",
            "rationale": "Selected from the deterministic view grid by the host model or user.",
        }
    )
    return _sanitize_camera_plan(plan, base)


def _configured_view_specs(
    config: Mapping[str, Any],
    view_ids_override: Sequence[str] | None = None,
) -> list[dict[str, Any]] | None:
    camera = config["camera"]
    if str(camera.get("view_set", "all")) != "all":
        if view_ids_override is None:
            return None
        grid_specs: dict[str, dict[str, Any]] = {}
        index = 1
        for elevation in camera.get("view_grid_elevations", []):
            for azimuth in camera.get("view_grid_azimuths", []):
                view_id = f"V{index:02d}"
                grid_specs[view_id] = {
                    "view_id": view_id,
                    "label": f"{view_id}  az {float(azimuth):g}  el {float(elevation):g}",
                    "view_type": "grid",
                    "axis": None,
                    "azimuth": float(azimuth),
                    "elevation": float(elevation),
                    "projection": str(camera.get("projection", "perspective")),
                }
                index += 1
        unknown = [str(item) for item in view_ids_override if str(item) not in grid_specs]
        if unknown:
            raise ConfigError(f"camera plan contains unsupported grid view IDs: {', '.join(unknown)}")
        return [dict(grid_specs[str(item)]) for item in view_ids_override]
    return product_view_specs(
        view_ids_override if view_ids_override is not None else camera.get("view_ids")
    )


def _grid_view_ids(config: Mapping[str, Any]) -> list[str]:
    camera = config["camera"]
    count = len(camera.get("view_grid_azimuths", [])) * len(camera.get("view_grid_elevations", []))
    return [f"V{index:02d}" for index in range(1, count + 1)]


def _available_view_ids(config: Mapping[str, Any]) -> list[str]:
    if str(config["camera"].get("view_set", "all")) == "all":
        return [str(item["view_id"]) for item in product_view_specs(config["camera"].get("view_ids"))]
    return _grid_view_ids(config)


def _camera_plan_view_ids(camera_plan_path: str | Path | None) -> list[str]:
    if not camera_plan_path:
        return []
    raw_plan = _read_json(camera_plan_path)
    if not isinstance(raw_plan, Mapping):
        raise ConfigError("Camera-plan JSON must be an object")
    requested_ids = raw_plan.get("selected_view_ids") or raw_plan.get("view_ids")
    if requested_ids is not None:
        if not isinstance(requested_ids, list):
            raise ConfigError("Camera-plan selected_view_ids/view_ids must be a list")
        return [str(item) for item in requested_ids]
    selected_id = raw_plan.get("selected_view_id")
    return [str(selected_id)] if selected_id else []


def _candidate_ids_for_views(view_ids: Sequence[str], counts: Sequence[int]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    next_index = 1
    for view_id, count in zip(view_ids, counts):
        candidate_ids = [f"C{index:02d}" for index in range(next_index, next_index + int(count))]
        next_index += int(count)
        entries.append(
            {
                "view_id": str(view_id),
                "candidate_count": int(count),
                "candidate_ids": candidate_ids,
            }
        )
    return entries


def _build_render_plan(
    config: Mapping[str, Any],
    discovery: Mapping[str, Any],
    *,
    requested_view_id: str | None = None,
    camera_plan_path: str | Path | None = None,
    requested_candidate_count: int | None = None,
) -> dict[str, Any]:
    """Build the single user-editable plan before any CAD rendering occurs."""
    available_ids = _available_view_ids(config)
    camera_ids = _camera_plan_view_ids(camera_plan_path)
    explicit_ids = [str(requested_view_id)] if requested_view_id else camera_ids
    unknown = [item for item in explicit_ids if item not in available_ids]
    if unknown:
        raise ConfigError(
            f"The requested plan view ID(s) are not available: {', '.join(unknown)}. "
            f"Available: {', '.join(available_ids)}"
        )

    if explicit_ids:
        reference_ids = [*dict.fromkeys([*explicit_ids, *available_ids])]
        generation_view_ids = list(dict.fromkeys(explicit_ids))
        candidate_count = int(
            requested_candidate_count
            if requested_candidate_count is not None
            else config["generation"].get("candidates", 4)
        )
        if not 1 <= candidate_count <= 10:
            raise ConfigError("The confirmed render plan candidate count must be between 1 and 10")
        generation_views = _candidate_ids_for_views(
            generation_view_ids,
            [candidate_count] * len(generation_view_ids),
        )
        view_source = "user_view" if requested_view_id else "camera_plan"
        final_policy = (
            "The user supplied a view; generate the requested number of candidates in that view only."
        )
    else:
        reference_ids = list(available_ids)
        generation_view_ids = [item for item in DEFAULT_FINAL_VIEW_IDS if item in available_ids]
        if not generation_view_ids:
            generation_view_ids = available_ids[:4]
        # The default final budget is four images total: one per requested default view.
        generation_views = _candidate_ids_for_views(
            generation_view_ids,
            [1] * len(generation_view_ids),
        )
        view_source = "inferred_default"
        final_policy = (
            "No output view was specified; generate exactly four final candidates total: "
            "front, back, left, and one upper axonometric view."
        )

    total_candidates = sum(int(item["candidate_count"]) for item in generation_views)
    return {
        "schema_version": RENDER_PLAN_VERSION,
        "status": "awaiting_user_confirmation",
        "confirmation": {
            "required": True,
            "confirmed": False,
            "confirmed_by_user": False,
            "confirmed_at": None,
            "instruction": (
                "Review or edit this file, then set confirmation.confirmed to true and resubmit it "
                "with the prepare command."
            ),
        },
        "model": {
            "path": str(Path(str(discovery["model"])).expanduser().resolve()),
            "format": Path(str(discovery["model"])).suffix.lower().lstrip("."),
        },
        "references": [dict(item) for item in discovery.get("references", [])],
        "intent": str(config["project"].get("description", "")),
        "view_intent": {
            "source": view_source,
            "requested_view_ids": explicit_ids,
            "priority_rule": "User-specified view IDs take priority for reference and final generation plans.",
        },
        "reference_plan": {
            "purpose": "Deterministic CAD model reference images and auxiliary evidence.",
            "view_set": "all" if str(config["camera"].get("view_set", "all")) == "all" else "grid",
            "view_ids": reference_ids,
            "primary_view_ids": explicit_ids,
            "generate_extra_views_for_geometry_evidence": True,
        },
        "generation_plan": {
            "purpose": "Final AI product-render candidates only; do not multiply this budget by reference views.",
            "policy": final_policy,
            "views": generation_views,
            "view_ids": [str(item["view_id"]) for item in generation_views],
            "total_candidate_count": total_candidates,
            "host_skill": str(config["generation"].get("host_skill", "imagegen")),
            "target_resolution": str(config["generation"].get("target_resolution", "4k")),
            "quality": str(config["generation"].get("quality", "high")),
            "detail_level": str(config["generation"].get("detail_level", "high")),
        },
        "editable_fields": [
            "reference_plan.view_ids",
            "generation_plan.views",
            "generation_plan.total_candidate_count",
            "generation_plan.host_skill",
            "generation_plan.target_resolution",
            "generation_plan.quality",
            "generation_plan.detail_level",
            "confirmation.confirmed",
        ],
        "notes": [
            "Reference coverage may contain many deterministic CAD views; final generation follows generation_plan.views only.",
            "Do not place personal information in this plan or commit a runtime plan containing local paths.",
        ],
    }


def _plan_confirmed(plan: Mapping[str, Any]) -> bool:
    confirmation = plan.get("confirmation")
    if isinstance(confirmation, Mapping) and confirmation.get("confirmed") is True:
        return True
    return plan.get("confirmed") is True


def _validate_render_plan(
    plan: Mapping[str, Any],
    config: Mapping[str, Any],
    discovery: Mapping[str, Any],
) -> dict[str, Any]:
    if str(plan.get("schema_version", "")) != RENDER_PLAN_VERSION:
        raise ConfigError(f"Unsupported render plan schema: {plan.get('schema_version')!r}")
    if not _plan_confirmed(plan):
        raise ConfigError(
            "The render plan is not confirmed. Review planning/render_plan.json, set "
            "confirmation.confirmed to true, and resubmit it."
        )
    model = plan.get("model")
    model_path = model.get("path") if isinstance(model, Mapping) else None
    if model_path and Path(str(model_path)).expanduser().resolve() != Path(str(discovery["model"])).expanduser().resolve():
        raise ConfigError("The confirmed render plan belongs to a different model input")
    available_ids = _available_view_ids(config)
    reference_plan = plan.get("reference_plan")
    generation_plan = plan.get("generation_plan")
    if not isinstance(reference_plan, Mapping) or not isinstance(generation_plan, Mapping):
        raise ConfigError("The render plan must contain reference_plan and generation_plan objects")
    reference_ids = reference_plan.get("view_ids")
    if not isinstance(reference_ids, list) or not reference_ids:
        raise ConfigError("reference_plan.view_ids must be a non-empty list")
    reference_ids = [str(item) for item in reference_ids]
    if len(set(reference_ids)) != len(reference_ids):
        raise ConfigError("reference_plan.view_ids must not contain duplicates")
    unknown_reference = [item for item in reference_ids if item not in available_ids]
    if unknown_reference:
        raise ConfigError(f"Unknown reference-plan view ID(s): {', '.join(unknown_reference)}")
    generation_views = generation_plan.get("views")
    if not isinstance(generation_views, list) or not generation_views:
        raise ConfigError("generation_plan.views must be a non-empty list")
    normalized_views: list[dict[str, Any]] = []
    generation_view_ids_seen: set[str] = set()
    all_candidate_ids: list[str] = []
    for entry in generation_views:
        if not isinstance(entry, Mapping):
            raise ConfigError("Each generation_plan.views entry must be an object")
        selected_id = str(entry.get("view_id", ""))
        if selected_id not in available_ids:
            raise ConfigError(f"Unknown generation-plan view ID: {selected_id!r}")
        if selected_id in generation_view_ids_seen:
            raise ConfigError(f"generation_plan.views must not repeat view ID {selected_id!r}")
        generation_view_ids_seen.add(selected_id)
        candidate_ids = entry.get("candidate_ids")
        count = int(entry.get("candidate_count", len(candidate_ids) if isinstance(candidate_ids, list) else 0))
        if not 1 <= count <= 10:
            raise ConfigError(f"Candidate count for {selected_id!r} must be between 1 and 10")
        if candidate_ids is None:
            candidate_ids = []
        if not isinstance(candidate_ids, list) or len(candidate_ids) != count:
            raise ConfigError(
                f"generation_plan.views[{selected_id!r}].candidate_ids must contain exactly {count} IDs"
            )
        candidate_ids = [str(item) for item in candidate_ids]
        if len(set(candidate_ids)) != len(candidate_ids):
            raise ConfigError(f"Candidate IDs must be unique within view {selected_id!r}")
        all_candidate_ids.extend(candidate_ids)
        normalized_views.append(
            {
                "view_id": selected_id,
                "candidate_count": count,
                "candidate_ids": candidate_ids,
            }
        )
    if len(set(all_candidate_ids)) != len(all_candidate_ids):
        raise ConfigError("Candidate IDs must be unique across the confirmed generation plan")
    total = int(generation_plan.get("total_candidate_count", len(all_candidate_ids)))
    if total != len(all_candidate_ids):
        raise ConfigError("generation_plan.total_candidate_count must equal the sum of candidate IDs")
    primary_ids = reference_plan.get("primary_view_ids", [])
    if primary_ids:
        if not isinstance(primary_ids, list):
            raise ConfigError("reference_plan.primary_view_ids must be a list")
        missing = [str(item) for item in primary_ids if str(item) not in [str(item) for item in reference_ids]]
        if missing:
            raise ConfigError("Every primary view must also appear in reference_plan.view_ids")
    normalized = dict(plan)
    normalized["reference_plan"] = dict(reference_plan)
    normalized["reference_plan"]["view_ids"] = reference_ids
    normalized["generation_plan"] = dict(generation_plan)
    normalized["generation_plan"]["views"] = normalized_views
    normalized["generation_plan"]["view_ids"] = [item["view_id"] for item in normalized_views]
    normalized["generation_plan"]["total_candidate_count"] = total
    return normalized


def _resolve_camera_plans(
    view_records: Sequence[Mapping[str, Any]],
    base_camera: Mapping[str, Any],
    config: Mapping[str, Any],
    *,
    view_id: str | None,
    camera_plan_path: str | Path | None,
    selected_view_ids: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    """Resolve one or many camera plans without making up a semantic front view."""
    if selected_view_ids is not None:
        if not selected_view_ids:
            raise ConfigError("The confirmed generation plan must contain at least one view ID")
        plans = []
        for selected_id in selected_view_ids:
            plan = _camera_from_view(view_records, str(selected_id), base_camera)
            plan["source"] = "confirmed_render_plan"
            plan["rationale"] = "Selected by the confirmed user-editable render plan."
            plans.append(plan)
        return plans
    if camera_plan_path:
        raw_plan = _read_json(camera_plan_path)
        if not isinstance(raw_plan, Mapping):
            raise ConfigError("Camera-plan JSON must be an object")
        requested_ids = raw_plan.get("selected_view_ids") or raw_plan.get("view_ids")
        if raw_plan.get("view_set") == "all" or requested_ids:
            if requested_ids is None:
                requested_ids = [str(item.get("view_id")) for item in view_records]
            if not isinstance(requested_ids, list) or not requested_ids:
                raise ConfigError("A multi-view camera plan must contain a non-empty selected_view_ids list")
            plans: list[dict[str, Any]] = []
            for selected_id in requested_ids:
                plan = _camera_from_view(view_records, str(selected_id), base_camera)
                plan["source"] = raw_plan.get("source", "host_camera_analysis")
                if raw_plan.get("rationale"):
                    plan["rationale"] = raw_plan["rationale"]
                plans.append(plan)
            return plans
        selected_id = raw_plan.get("selected_view_id")
        plan = _camera_from_view(view_records, str(selected_id), base_camera) if selected_id else dict(base_camera)
        plan.update({key: value for key, value in raw_plan.items() if value is not None})
        plan["source"] = raw_plan.get("source", "host_camera_plan")
        return [_sanitize_camera_plan(plan, base_camera)]

    if view_id:
        return [_camera_from_view(view_records, view_id, base_camera)]

    if str(config["camera"].get("view_set", "all")) == "all":
        plans = []
        for record in view_records:
            plan = _camera_from_view(view_records, str(record["view_id"]), base_camera)
            plan["source"] = "default_product_view_set"
            plan["rationale"] = "No output viewpoint was specified; preserve broad directional coverage."
            plans.append(plan)
        return plans

    return [
        _sanitize_camera_plan(
            {
                **base_camera,
                "selected_view_id": None,
                "source": "configured_default",
                "rationale": "No host-selected camera plan was supplied; used the configured default.",
            },
            base_camera,
        )
    ]


def _merge_reference_roles(
    references: Sequence[Mapping[str, Any]],
    roles_path: str | Path | None,
) -> list[dict[str, Any]]:
    merged = [dict(item) for item in references]
    if not roles_path:
        return merged
    payload = _read_json(roles_path)
    entries = payload.get("references", payload) if isinstance(payload, Mapping) else payload
    if not isinstance(entries, list):
        raise ConfigError("Reference-role JSON must be a list or contain a 'references' list")
    for index, entry in enumerate(entries):
        if not isinstance(entry, Mapping):
            continue
        target_index = entry.get("reference_index")
        if target_index is None:
            image_index = entry.get("image_index")
            target_index = int(image_index) - 1 if image_index is not None else index
        target_index = int(target_index)
        if not 0 <= target_index < len(merged):
            continue
        for key in ("roles", "notes", "allowed_use", "forbidden_use", "confidence"):
            if key in entry:
                merged[target_index][key] = entry[key]
    return merged


def _deterministic_brief(
    manifest: Mapping[str, Any],
    project_description: str,
    references: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    useful_colors = bool(manifest.get("source_has_useful_colors"))
    return {
        "object_interpretation": "A manufactured object represented by the supplied CAD model; exact category remains uncertain unless stated by the user.",
        "reference_analysis": [
            {
                "reference_index": index,
                "roles": ref.get("roles", ["mixed"]),
                "use": ref.get("allowed_use", "Use only for reliable appearance/camera evidence."),
                "ignore": ref.get(
                    "forbidden_use",
                    "Ignore reference geometry, topology, proportions, part count, and accessories.",
                ),
                "confidence": float(ref.get("confidence", 0.5)),
            }
            for index, ref in enumerate(references)
        ],
        "assumptions": [
            "Use a restrained premium product-visualization treatment.",
            "Use physically plausible materials and controlled studio lighting.",
            (
                "Treat pseudo-colors as part identifiers, not final colors."
                if not useful_colors
                else "Preserve useful CAD color blocks unless explicit user intent or a reliable color reference overrides them."
            ),
        ],
        "material_plan": [
            {
                "region": "modeled parts",
                "material": "commercially plausible product materials",
                "finish": "controlled semi-matte finish with readable edge highlights",
                "evidence": "conservative fallback pending host visual analysis",
            }
        ],
        "color_plan": [
            {
                "region": "modeled parts",
                "color": "preserve CAD colors" if useful_colors else "coherent restrained palette",
                "source": "CAD" if useful_colors else "inferred",
            }
        ],
        "lighting_plan": {
            "setup": "large soft key, gentle fill, subtle rim",
            "direction": "upper front three-quarter",
            "contrast": "medium-low with readable form",
            "shadow": "soft contact shadow",
        },
        "environment_plan": {
            "type": "studio",
            "description": "minimal premium product studio",
            "background": "neutral seamless backdrop",
        },
        "camera_constraints": ["Match the selected CAD camera and framing."],
        "geometry_constraints": [
            "Preserve silhouette, proportions, visible topology, holes, seams, and part placement.",
            "Do not add, remove, merge, or duplicate parts.",
        ],
        "style_targets": ["photoreal", "premium industrial-design visualization"],
        "negative_constraints": [
            "no geometry drift",
            "no extra controls, seams, holes, labels, logos, accessories, or text",
        ],
        "generation_prompt_core": project_description
        or "Render the supplied CAD object as a premium photoreal studio product image with physically plausible materials and clean controlled lighting.",
        "source": "deterministic_fallback; host should refine from attached images",
    }


def _build_generation_inputs(
    aux_files: Mapping[str, str],
    references: Sequence[Mapping[str, Any]],
    anchor_mode: str,
    extra_guard: str | Path | None = None,
) -> tuple[list[Path], list[dict[str, Any]]]:
    definitions = {
        "color_preview": (
            "CAD shaded color preview and camera anchor",
            "camera, silhouette, visible geometry, occlusion, and genuine CAD color blocks; pseudo-colors only as part IDs",
            "do not interpret pseudo-colors as final materials unless explicitly requested",
        ),
        "clay": (
            "CAD clay shaded form anchor",
            "solid form, curvature, bevels, occlusion, and broad surface continuity",
            "do not copy the neutral clay material into the final render unless requested",
        ),
        "lineart": (
            "CAD lineart geometry anchor",
            "visible edges, holes, seams, part boundaries, silhouette, and perspective",
            "do not render the final result as a line drawing",
        ),
        "normal": (
            "CAD view-space normal map",
            "surface orientation, curvature, and local form",
            "do not use normal-map colors as final color",
        ),
        "depth": (
            "CAD depth map",
            "relative depth, occlusion, and spatial ordering",
            "do not use grayscale values as material guidance",
        ),
        "mask": (
            "CAD silhouette mask",
            "object footprint and outer silhouette",
            "do not produce a cutout graphic",
        ),
    }
    if anchor_mode == "compact":
        keys = ["color_preview", "lineart"]
    elif anchor_mode == "max_geometry":
        keys = ["color_preview", "clay", "lineart", "normal", "depth", "mask"]
    else:
        keys = ["color_preview", "clay", "lineart"]

    paths: list[Path] = []
    roles: list[dict[str, Any]] = []
    for key in keys:
        path = Path(aux_files[key])
        label, allowed, forbidden = definitions[key]
        paths.append(path)
        roles.append(
            {
                "image_index": len(paths),
                "role": label,
                "allowed_use": allowed,
                "forbidden_use": forbidden,
                "path": str(path),
                "source": "cad_anchor",
            }
        )
    if extra_guard:
        path = Path(extra_guard)
        paths.append(path)
        roles.append(
            {
                "image_index": len(paths),
                "role": "optional local geometry guard",
                "allowed_use": "reinforce the same CAD silhouette, camera, and topology",
                "forbidden_use": "do not copy guard artifacts, texture, or unintended color",
                "path": str(path),
                "source": "comfyui_guard",
            }
        )
    for reference_index, reference in enumerate(references):
        path = Path(str(reference["path"]))
        declared = reference.get("roles", ["mixed"])
        if isinstance(declared, str):
            declared = [declared]
        paths.append(path)
        roles.append(
            {
                "image_index": len(paths),
                "reference_index": reference_index,
                "role": f"user-attached reference: {', '.join(declared)}",
                "allowed_use": reference.get(
                    "allowed_use",
                    f"Use only for these soft roles: {', '.join(declared)}.",
                ),
                "forbidden_use": reference.get(
                    "forbidden_use",
                    "never copy object geometry, topology, part count, proportions, controls, or accessories",
                ),
                "path": str(path),
                "notes": reference.get("notes", ""),
                "source": "attachment",
            }
        )
    return paths, roles


def _build_report(
    manifest: Mapping[str, Any],
    camera_plan: Mapping[str, Any] | None,
    status: str,
    warnings: Sequence[str],
    grid_only: bool,
    view_bundles: Sequence[Mapping[str, Any]] | None = None,
) -> str:
    lines = [
        "# CAD AI Renderer Preparation Report",
        "",
        f"- Status: {status}",
        f"- Pipeline version: {PIPELINE_VERSION}",
        f"- Source: {manifest.get('source_name', '')}",
        f"- Converter: {manifest.get('converter', '')}",
        f"- Parts: {manifest.get('part_count', '')}",
        "- Final generation backend: host official image-generation skill/tool",
        "- Raw image API calls in this package: none",
        "",
    ]
    if camera_plan:
        lines.extend(
            [
                "## Camera",
                "",
                f"Selected view: {camera_plan.get('view_label') or camera_plan.get('selected_view_id', 'custom/default')}",
                f"Azimuth/elevation: {camera_plan.get('azimuth')} / {camera_plan.get('elevation')}",
                f"Projection/FOV: {camera_plan.get('projection')} / {camera_plan.get('fov_deg')}",
                f"Source: {camera_plan.get('source', '')}",
                "",
            ]
        )
    if view_bundles:
        lines.extend(["## View set", "", f"Prepared view bundles: {len(view_bundles)}", ""])
        for bundle in view_bundles:
            lines.append(
                f"- `{bundle.get('view_id')}` — {bundle.get('view_label', '')}: "
                f"`{Path(str(bundle.get('root'))).resolve() / 'final' / 'best.png'}` after visual QA"
            )
        lines.append("")
    if grid_only:
        lines.extend(
            [
                "## Next action",
                "",
                "Inspect `auxiliary/view_grid.png` together with attached camera/composition references, write a camera plan, then run the prepare command again with `--camera-plan` or `--view-id`.",
                "",
            ]
        )
    else:
        lines.extend(
            [
                "## Next action",
                "",
                "Use `planning/host_handoff.json` to invoke the official image-generation skill/tool with the ordered inputs. Pass returned files directly to the stage command, perform host visual QA, and only then run finalize.",
                "",
            ]
        )
    if warnings:
        lines.extend(["## Warnings", ""])
        lines.extend(f"- {warning}" for warning in warnings)
        lines.append("")
    lines.extend(
        [
            "## Geometry note",
            "",
            "The auxiliary passes are strong visual anchors, not a guarantee of pixel-exact CAD reconstruction. Review engineering-critical details against the original model.",
            "",
        ]
    )
    return "\n".join(lines)


def _prepare_view_bundle(
    renderer: VTKAnchorRenderer,
    model_manifest: Mapping[str, Any],
    config: Mapping[str, Any],
    discovery: Mapping[str, Any],
    view_root: str | Path,
    camera_plan: Mapping[str, Any],
    references: Sequence[Mapping[str, Any]],
    render_brief_path: str | Path | None,
    strict_geometry: bool,
    shared_glb: str | Path,
    candidate_ids: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Render one camera bundle and write its independent host handoff."""
    root = Path(view_root).expanduser().resolve()
    layout = output_layout(root, create=True)
    planning_dir = layout["planning"]
    aux_dir = layout["auxiliary"]
    dump_resolved_config(config, root / "resolved_project.yaml")
    _write_json(root / "input_discovery.json", discovery)
    _write_json(planning_dir / "camera_plan.json", camera_plan)

    aux_result = renderer.render_auxiliary_set(aux_dir, dict(camera_plan))
    aux_files = aux_result["files"]
    _write_json(aux_dir / "model_manifest.json", model_manifest)
    shared_path = Path(shared_glb).expanduser().resolve()
    model_copy = aux_dir / "model.glb"
    if shared_path != model_copy.resolve():
        shutil.copy2(shared_path, model_copy)

    brief_labels = [
        "CAD shaded color preview; pseudo-colors may be part IDs",
        "CAD lineart",
        "CAD normal map",
        "CAD depth map",
    ]
    (planning_dir / "render_brief_prompt.txt").write_text(
        render_brief_prompt(
            model_manifest,
            config["project"].get("description", ""),
            references,
            brief_labels,
        ),
        encoding="utf-8",
    )
    if render_brief_path:
        brief = _read_json(render_brief_path)
        brief["source"] = brief.get("source", "host_visual_analysis")
    else:
        brief = _deterministic_brief(
            model_manifest,
            config["project"].get("description", ""),
            references,
        )
    _write_json(planning_dir / "render_brief.json", brief)

    generation_inputs, input_roles = _build_generation_inputs(
        aux_files,
        references,
        config["geometry"]["anchor_mode"],
    )
    _write_json(planning_dir / "input_roles.json", input_roles)
    generation_prompt = build_generation_prompt(
        brief,
        input_roles,
        config["project"].get("description", ""),
        strict_geometry=strict_geometry,
        host_skill=str(config["generation"].get("host_skill", "imagegen")),
        target_resolution=str(config["generation"].get("target_resolution", "4k")),
        quality=str(config["generation"].get("quality", "high")),
        detail_level=str(config["generation"].get("detail_level", "high")),
    )
    (planning_dir / "final_prompt.txt").write_text(generation_prompt, encoding="utf-8")
    resolved_candidate_ids = [str(item) for item in (candidate_ids or [])]
    if not resolved_candidate_ids:
        candidate_count = int(config["generation"]["candidates"])
        resolved_candidate_ids = [f"C{index:02d}" for index in range(1, candidate_count + 1)]
    candidate_count = len(resolved_candidate_ids)
    imagegen_request = {
        "backend": "official_host_image_generation_skill_or_tool",
        "raw_api_required": False,
        "host_skill": str(config["generation"].get("host_skill", "imagegen")),
        "target_resolution": str(config["generation"].get("target_resolution", "4k")),
        "detail_level": str(config["generation"].get("detail_level", "high")),
        "view_id": camera_plan.get("selected_view_id"),
        "view_label": camera_plan.get("view_label"),
        "view_type": camera_plan.get("view_type"),
        "candidate_count": candidate_count,
        "candidate_ids": resolved_candidate_ids,
        "aspect_ratio": config["generation"]["aspect_ratio"],
        "quality": config["generation"]["quality"],
        "output_format": config["generation"]["output_format"],
        "prompt_path": str(planning_dir / "final_prompt.txt"),
        "input_images": [str(path) for path in generation_inputs],
        "input_roles_path": str(planning_dir / "input_roles.json"),
        "instruction": "Invoke the host's official image-generation capability. Prefer one multi-output invocation; otherwise make separate invocations with the same ordered inputs and prompt.",
        "resolution_policy": "Request the target resolution when the host exposes it; otherwise use the highest supported resolution and record actual dimensions.",
    }
    _write_json(planning_dir / "imagegen_request.json", imagegen_request)
    write_generation_handoff(
        root,
        launcher=Path(__file__).resolve().parent / "run.py",
        imagegen_request=imagegen_request,
    )

    view_manifest = {
        "pipeline_version": PIPELINE_VERSION,
        "output_contract_version": "2.2",
        "status": "prepared_for_image_generation",
        "stage": "local_geometry_preparation",
        "view_id": camera_plan.get("selected_view_id"),
        "view_label": camera_plan.get("view_label"),
        "generation_backend": "host_official_image_generation_skill",
        "raw_image_api_used": False,
        "paths": manifest_paths(layout),
        "steps": [
            {"name": "auxiliary_passes", "status": "ok", "at": _now()},
            {"name": "image_generation", "status": "delegated_to_host_tool", "at": _now()},
        ],
        "finished_at": _now(),
    }
    _write_json(root / "run_manifest.json", view_manifest)
    (layout["final"] / "report.md").write_text(
        _build_report(model_manifest, camera_plan, view_manifest["status"], [], False),
        encoding="utf-8",
    )
    return {
        "view_id": camera_plan.get("selected_view_id"),
        "view_label": camera_plan.get("view_label") or camera_plan.get("selected_view_id"),
        "view_type": camera_plan.get("view_type"),
        "root": str(root),
        "camera_plan": dict(camera_plan),
        "imagegen_request": str(planning_dir / "imagegen_request.json"),
        "host_handoff": str(planning_dir / "host_handoff.json"),
        "candidate_ids": resolved_candidate_ids,
    }


def _load_or_build_config(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any]]:
    intent = args.intent or ""
    if args.intent_file:
        intent = Path(args.intent_file).read_text(encoding="utf-8").strip()

    if args.project:
        cfg = load_config(args.project)
        discovery = {
            "model": cfg["project"]["input_model"],
            "references": cfg["project"]["references"],
            "ignored": [],
            "source": "project_yaml",
        }
        if intent:
            cfg["project"]["description"] = intent
        if args.output:
            cfg["project"]["output_dir"] = str(Path(args.output).expanduser().resolve())
        if args.reference:
            cfg["project"]["references"] = [
                {"path": str(Path(path).expanduser().resolve()), "roles": ["mixed"], "source": "attachment"}
                for path in args.reference
            ]
    else:
        discovery = discover_inputs(args.input, args.model, args.reference)
        model = discovery["model"]
        output = args.output or str((Path.cwd() / "cad-ai-render-output" / Path(model).stem).resolve())
        cfg = build_direct_config(
            model,
            output,
            description=intent,
            references=discovery["references"],
        )

    if args.anchor_mode:
        cfg["geometry"]["anchor_mode"] = args.anchor_mode
    if args.width:
        cfg["render"]["width"] = int(args.width)
    if args.height:
        cfg["render"]["height"] = int(args.height)
    if args.candidates:
        cfg["generation"]["candidates"] = int(args.candidates)
    if args.aspect_ratio:
        cfg["generation"]["aspect_ratio"] = args.aspect_ratio
    if args.quality:
        cfg["generation"]["quality"] = args.quality
    if args.host_skill:
        cfg["generation"]["host_skill"] = args.host_skill
    if args.target_resolution:
        cfg["generation"]["target_resolution"] = args.target_resolution
    if args.detail_level:
        cfg["generation"]["detail_level"] = args.detail_level
    for key in ("azimuth", "elevation", "fov_deg", "framing", "projection"):
        value = getattr(args, key, None)
        if value is not None:
            cfg["camera"][key] = value
    validate_config(cfg)
    return cfg, discovery


def create_render_plan(
    config: Mapping[str, Any],
    discovery: Mapping[str, Any],
    *,
    requested_view_id: str | None = None,
    camera_plan_path: str | Path | None = None,
    requested_candidate_count: int | None = None,
    plan_path: str | Path | None = None,
) -> dict[str, Any]:
    """Write the one user-editable plan without converting or rendering the CAD model."""
    output_dir = Path(str(config["project"]["output_dir"])).expanduser().resolve()
    target = Path(plan_path).expanduser().resolve() if plan_path else output_dir / "planning" / "render_plan.json"
    plan = _build_render_plan(
        config,
        discovery,
        requested_view_id=requested_view_id,
        camera_plan_path=camera_plan_path,
        requested_candidate_count=requested_candidate_count,
    )
    _write_json(target, plan)
    return {"plan_path": str(target), "plan": plan}


def prepare_run(
    config: Mapping[str, Any],
    discovery: Mapping[str, Any],
    *,
    grid_only: bool = False,
    view_id: str | None = None,
    camera_plan_path: str | Path | None = None,
    reference_roles_path: str | Path | None = None,
    render_brief_path: str | Path | None = None,
    strict_geometry: bool = False,
    render_plan_path: str | Path | None = None,
) -> dict[str, Any]:
    output_dir = Path(str(config["project"]["output_dir"])).expanduser().resolve()
    layout = output_layout(output_dir, create=True)
    aux_dir = layout["auxiliary"]
    planning_dir = layout["planning"]
    final_dir = layout["final"]
    render_plan: dict[str, Any] | None = None
    if render_plan_path:
        source_plan_path = Path(render_plan_path).expanduser().resolve()
        render_plan = _validate_render_plan(_read_json(source_plan_path), config, discovery)
        # Keep the confirmed plan beside the generated evidence as the canonical run record.
        _write_json(planning_dir / "render_plan.json", render_plan)
    elif not grid_only:
        raise ConfigError(
            "prepare requires a confirmed render plan. Run the plan command first, review "
            "planning/render_plan.json, set confirmation.confirmed to true, then pass --plan."
        )
    dump_resolved_config(config, output_dir / "resolved_project.yaml")
    _write_json(output_dir / "input_discovery.json", discovery)

    run_manifest: dict[str, Any] = {
        "pipeline_version": PIPELINE_VERSION,
        "output_contract_version": "2.1",
        "started_at": _now(),
        "status": "running",
        "stage": "local_geometry_preparation",
        "grid_only": grid_only,
        "config_fingerprint": config_fingerprint(config),
        "generation_backend": "host_official_image_generation_skill",
        "raw_image_api_used": False,
        "managed_venv": os.environ.get("CAD_AI_RENDERER_MANAGED_VENV"),
        "managed_venv_mode": os.environ.get("CAD_AI_RENDERER_VENV_MODE"),
        "paths": manifest_paths(layout),
        "steps": [],
        "warnings": [],
        "render_plan": str(planning_dir / "render_plan.json") if render_plan else None,
    }
    _write_json(output_dir / "run_manifest.json", run_manifest)

    renderer: VTKAnchorRenderer | None = None
    try:
        _log("Converting the CAD model to GLB")
        glb_path = aux_dir / "model.glb"
        model_manifest = convert_model(
            config["project"]["input_model"],
            glb_path,
            aux_dir / "model_manifest.json",
            converter=config["geometry"]["converter"],
            linear_tolerance=float(config["geometry"]["linear_tolerance"]),
            angular_tolerance=float(config["geometry"]["angular_tolerance"]),
        )
        run_manifest["steps"].append({"name": "convert_model", "status": "ok", "at": _now()})
        if model_manifest.get("warning"):
            run_manifest["warnings"].append(str(model_manifest["warning"]))

        if config["render"]["aux_backend"] not in {"auto", "vtk"}:
            raise RuntimeError("The packaged deterministic backend is VTK. Use render.aux_backend=auto or vtk.")
        renderer = VTKAnchorRenderer(
            glb_path,
            width=int(config["render"]["width"]),
            height=int(config["render"]["height"]),
            background_rgb=config["render"]["background_rgb"],
            source_has_useful_colors=bool(model_manifest.get("source_has_useful_colors")),
            color_mode=config["geometry"]["color_mode"],
        )
        base_camera = _camera_base(config)
        _log("Rendering the deterministic camera view grid")
        view_result = renderer.render_view_grid(
            aux_dir,
            base_camera,
            azimuths=config["camera"]["view_grid_azimuths"],
            elevations=config["camera"]["view_grid_elevations"],
            view_specs=_configured_view_specs(
                config,
                render_plan.get("reference_plan", {}).get("view_ids") if render_plan else None,
            ),
        )
        view_records = view_result["views"]
        references = _merge_reference_roles(config["project"]["references"], reference_roles_path)
        _write_json(planning_dir / "reference_roles.json", {"references": references})
        (planning_dir / "reference_role_prompt.txt").write_text(
            reference_role_prompt(len(references), config["project"].get("description", "")),
            encoding="utf-8",
        )
        (planning_dir / "camera_selection_prompt.txt").write_text(
            camera_selection_prompt(
                view_records,
                config["project"].get("description", ""),
                references,
                default_multi_view=str(config["camera"].get("view_set", "all")) == "all",
            ),
            encoding="utf-8",
        )
        run_manifest["steps"].append({"name": "view_grid", "status": "ok", "at": _now()})

        if grid_only:
            run_manifest["status"] = "camera_selection_needed"
            run_manifest["finished_at"] = _now()
            run_manifest["steps"].append({"name": "auxiliary_passes", "status": "deferred", "at": _now()})
            (final_dir / "report.md").write_text(
                _build_report(model_manifest, None, run_manifest["status"], run_manifest["warnings"], True),
                encoding="utf-8",
            )
            write_camera_handoff(
                output_dir,
                launcher=Path(__file__).resolve().parent / "run.py",
                model=str(config["project"]["input_model"]),
                references=references,
                intent=str(config["project"].get("description", "")),
                view_grid=view_result["view_grid"],
                view_grid_json=view_result["view_grid_json"],
            )
            _write_json(output_dir / "run_manifest.json", run_manifest)
            _log(f"View-grid stage complete: {view_result['view_grid']}")
            return run_manifest

        generation_views = (
            render_plan.get("generation_plan", {}).get("views", []) if render_plan else []
        )
        planned_view_ids = [str(item["view_id"]) for item in generation_views]
        camera_plans = _resolve_camera_plans(
            view_records,
            base_camera,
            config,
            view_id=view_id,
            camera_plan_path=camera_plan_path,
            selected_view_ids=planned_view_ids or None,
        )
        if generation_views and len(generation_views) != len(camera_plans):
            raise ConfigError("The confirmed generation plan and resolved camera plan contain different view counts")
        candidate_ids_by_view = {
            str(item["view_id"]): [str(candidate_id) for candidate_id in item["candidate_ids"]]
            for item in generation_views
        }
        view_bundles: list[dict[str, Any]] = []
        if len(camera_plans) == 1:
            _log("Rendering lineart, mask, normal, depth, part ID, clay, and color preview")
            view_bundles.append(
                _prepare_view_bundle(
                    renderer,
                    model_manifest,
                    config,
                    discovery,
                    output_dir,
                    camera_plans[0],
                    references,
                    render_brief_path,
                    strict_geometry,
                    aux_dir / "model.glb",
                    candidate_ids=candidate_ids_by_view.get(
                        str(camera_plans[0].get("selected_view_id")),
                        None,
                    ),
                )
            )
        else:
            _log(f"Rendering {len(camera_plans)} final directional view bundles")
            view_root = output_dir / "views"
            for camera_plan in camera_plans:
                selected_id = str(camera_plan.get("selected_view_id") or "view")
                safe_id = "".join(char if char.isalnum() or char in "-_" else "_" for char in selected_id)
                view_bundles.append(
                    _prepare_view_bundle(
                        renderer,
                        model_manifest,
                        config,
                        discovery,
                        view_root / (safe_id or "view"),
                        camera_plan,
                        references,
                        render_brief_path,
                        strict_geometry,
                        aux_dir / "model.glb",
                        candidate_ids=candidate_ids_by_view.get(selected_id),
                    )
                )
            candidate_counts = {
                str(bundle.get("view_id")): len(bundle.get("candidate_ids", []))
                for bundle in view_bundles
            }
            total_candidate_count = sum(candidate_counts.values())
            uniform_count = next(iter(candidate_counts.values()), 0)
            if any(count != uniform_count for count in candidate_counts.values()):
                uniform_count_value: int | None = None
            else:
                uniform_count_value = uniform_count
            aggregate_request = {
                "backend": "official_host_image_generation_skill_or_tool",
                "raw_api_required": False,
                "host_skill": str(config["generation"].get("host_skill", "imagegen")),
                "target_resolution": str(config["generation"].get("target_resolution", "4k")),
                "detail_level": str(config["generation"].get("detail_level", "high")),
                "view_set": render_plan.get("reference_plan", {}).get("view_set", "all") if render_plan else "all",
                "view_count": len(view_bundles),
                "candidate_count_per_view": uniform_count_value,
                "candidate_counts": candidate_counts,
                "total_candidate_count": total_candidate_count,
                "aspect_ratio": config["generation"]["aspect_ratio"],
                "quality": config["generation"]["quality"],
                "output_format": config["generation"]["output_format"],
                "views": view_bundles,
                "instruction": "Run the official image-generation handoff independently for every view bundle; preserve each view's CAD camera and never merge view directions into one candidate.",
                "resolution_policy": "Request the target resolution for every view; record actual dimensions if the host cannot expose exact 4K control.",
            }
            _write_json(
                planning_dir / "view_set.json",
                {
                    "view_set": aggregate_request["view_set"],
                    "reference_view_ids": render_plan.get("reference_plan", {}).get("view_ids", []) if render_plan else [],
                    "views": view_bundles,
                    "candidate_counts": candidate_counts,
                    "total_candidate_count": total_candidate_count,
                },
            )
            _write_json(planning_dir / "imagegen_request.json", aggregate_request)
            write_multi_generation_handoff(
                output_dir,
                launcher=Path(__file__).resolve().parent / "run.py",
                view_bundles=view_bundles,
                candidate_count=uniform_count_value or max(candidate_counts.values(), default=1),
                host_skill=str(config["generation"].get("host_skill", "imagegen")),
                target_resolution=str(config["generation"].get("target_resolution", "4k")),
                quality=str(config["generation"].get("quality", "high")),
                detail_level=str(config["generation"].get("detail_level", "high")),
            )
        run_manifest["view_count"] = len(view_bundles)
        run_manifest["view_bundles"] = view_bundles
        run_manifest["final_candidate_count"] = sum(len(item.get("candidate_ids", [])) for item in view_bundles)
        run_manifest["status"] = "prepared_for_image_generation"
        run_manifest["finished_at"] = _now()
        run_manifest["steps"].append({"name": "view_bundles", "status": "ok", "at": _now()})
        run_manifest["steps"].append({"name": "image_generation", "status": "delegated_to_host_tool", "at": _now()})
        (final_dir / "report.md").write_text(
            _build_report(
                model_manifest,
                view_bundles[0]["camera_plan"] if len(view_bundles) == 1 else None,
                run_manifest["status"],
                run_manifest["warnings"],
                False,
                view_bundles if len(view_bundles) > 1 else None,
            ),
            encoding="utf-8",
        )
        _write_json(output_dir / "run_manifest.json", run_manifest)
        _log(f"Local preparation complete: {output_dir}")
        return run_manifest
    except Exception as exc:
        run_manifest["status"] = "failed"
        run_manifest["finished_at"] = _now()
        run_manifest["error"] = {
            "type": type(exc).__name__,
            "message": str(exc),
            "traceback": traceback.format_exc(),
        }
        _write_json(output_dir / "run_manifest.json", run_manifest)
        raise
    finally:
        if renderer is not None:
            renderer.close()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--plan-only",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    source = parser.add_argument_group("input source")
    source.add_argument("--project", help="Optional advanced project YAML; not required for attachment use")
    source.add_argument("--input", action="append", default=[], help="Attached file or directory; repeat as needed")
    source.add_argument("--model", help="Explicit 3D model when multiple model attachments exist")
    source.add_argument("--reference", action="append", default=[], help="Attached reference image; repeat as needed")
    source.add_argument("--intent", help="User's natural-language render request")
    source.add_argument("--intent-file", help="Read the user's render request from a text file")
    source.add_argument("--output", help="Output directory; defaults to ./cad-ai-render-output/<model>")

    camera = parser.add_argument_group("camera")
    camera.add_argument("--grid-only", action="store_true", help="Stop after the camera view grid")
    camera.add_argument("--view-id", help="Use a labeled view such as V06")
    camera.add_argument("--camera-plan", help="Host-generated camera plan JSON")
    camera.add_argument("--azimuth", type=float)
    camera.add_argument("--elevation", type=float)
    camera.add_argument("--projection", choices=["perspective", "orthographic"])
    camera.add_argument("--fov-deg", type=float, dest="fov_deg")
    camera.add_argument("--framing", type=float)

    planning = parser.add_argument_group("host planning artifacts")
    planning.add_argument(
        "--plan",
        help="Confirmed user-editable render_plan.json required before final preparation",
    )
    planning.add_argument(
        "--plan-output",
        help="Where the plan command writes render_plan.json; defaults inside --output/planning",
    )
    planning.add_argument("--reference-roles", help="Host-generated reference-role JSON")
    planning.add_argument("--render-brief", help="Host-generated rendering brief JSON")
    planning.add_argument("--strict-geometry", action="store_true", help="Build a one-time geometry recovery prompt")

    options = parser.add_argument_group("local preparation")
    options.add_argument("--anchor-mode", choices=["compact", "balanced", "max_geometry"])
    options.add_argument("--width", type=int)
    options.add_argument("--height", type=int)
    options.add_argument("--candidates", type=int)
    options.add_argument("--aspect-ratio", choices=["auto", "1:1", "4:3", "3:4", "16:9", "9:16"])
    options.add_argument("--quality", choices=["auto", "draft", "standard", "high"])
    options.add_argument("--host-skill", choices=["imagegen", "auto"], help="Official host Skill; imagegen is the default")
    options.add_argument("--target-resolution", choices=["auto", "2k", "4k"], help="Target host output resolution; 4k is the default")
    options.add_argument("--detail-level", choices=["standard", "high"], help="Requested visual detail; high is the default")
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    try:
        config, discovery = _load_or_build_config(args)
        if args.plan_only:
            result = create_render_plan(
                config,
                discovery,
                requested_view_id=args.view_id,
                camera_plan_path=args.camera_plan,
                requested_candidate_count=args.candidates,
                plan_path=args.plan_output,
            )
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            prepare_run(
                config,
                discovery,
                grid_only=args.grid_only,
                view_id=args.view_id,
                camera_plan_path=args.camera_plan,
                reference_roles_path=args.reference_roles,
                render_brief_path=args.render_brief,
                strict_geometry=args.strict_geometry,
                render_plan_path=args.plan,
            )
    except (ConfigError, InputDiscoveryError, FileNotFoundError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    os.environ.setdefault("VTK_DEFAULT_RENDER_WINDOW_OFFSCREEN", "1")
    raise SystemExit(main())
