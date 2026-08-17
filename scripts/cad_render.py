#!/usr/bin/env python3
"""Prepare deterministic CAD anchors for the host's official image-generation skill.

This script never calls an image API. It accepts direct attachment paths, creates
view/camera/geometry evidence, and writes a model-neutral image-generation request.
"""

from __future__ import annotations

import argparse
import json
import os
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
    validate_config,
)
from host_handoff import write_camera_handoff, write_generation_handoff
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

PIPELINE_VERSION = "2.1.0"


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
            "azimuth": float(match["azimuth"]),
            "elevation": float(match["elevation"]),
            "source": "host_selected_view_grid",
            "rationale": "Selected from the deterministic view grid by the host model or user.",
        }
    )
    return _sanitize_camera_plan(plan, base)


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
                f"Selected view: {camera_plan.get('selected_view_id', 'custom/default')}",
                f"Azimuth/elevation: {camera_plan.get('azimuth')} / {camera_plan.get('elevation')}",
                f"Projection/FOV: {camera_plan.get('projection')} / {camera_plan.get('fov_deg')}",
                f"Source: {camera_plan.get('source', '')}",
                "",
            ]
        )
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
    for key in ("azimuth", "elevation", "fov_deg", "framing", "projection"):
        value = getattr(args, key, None)
        if value is not None:
            cfg["camera"][key] = value
    validate_config(cfg)
    return cfg, discovery


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
) -> dict[str, Any]:
    output_dir = Path(str(config["project"]["output_dir"])).expanduser().resolve()
    layout = output_layout(output_dir, create=True)
    aux_dir = layout["auxiliary"]
    planning_dir = layout["planning"]
    final_dir = layout["final"]
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
        )
        view_records = view_result["views"]
        references = _merge_reference_roles(config["project"]["references"], reference_roles_path)
        _write_json(planning_dir / "reference_roles.json", {"references": references})
        (planning_dir / "reference_role_prompt.txt").write_text(
            reference_role_prompt(len(references), config["project"].get("description", "")),
            encoding="utf-8",
        )
        (planning_dir / "camera_selection_prompt.txt").write_text(
            camera_selection_prompt(view_records, config["project"].get("description", ""), references),
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

        if camera_plan_path:
            raw_plan = _read_json(camera_plan_path)
            selected_id = raw_plan.get("selected_view_id") if isinstance(raw_plan, Mapping) else None
            camera_plan = _camera_from_view(view_records, str(selected_id), base_camera) if selected_id else dict(base_camera)
            camera_plan.update({key: value for key, value in raw_plan.items() if value is not None})
            camera_plan["source"] = raw_plan.get("source", "host_camera_plan")
            camera_plan = _sanitize_camera_plan(camera_plan, base_camera)
        elif view_id:
            camera_plan = _camera_from_view(view_records, view_id, base_camera)
        else:
            camera_plan = _sanitize_camera_plan(
                {
                    **base_camera,
                    "selected_view_id": None,
                    "source": "configured_default",
                    "rationale": "No host-selected camera plan was supplied; used the configured default.",
                },
                base_camera,
            )
        _write_json(planning_dir / "camera_plan.json", camera_plan)

        _log("Rendering lineart, mask, normal, depth, part ID, clay, and color preview")
        aux_result = renderer.render_auxiliary_set(aux_dir, camera_plan)
        aux_files = aux_result["files"]
        run_manifest["steps"].append({"name": "auxiliary_passes", "status": "ok", "at": _now()})

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
        )
        (planning_dir / "final_prompt.txt").write_text(generation_prompt, encoding="utf-8")
        candidate_count = int(config["generation"]["candidates"])
        candidate_ids = [f"C{index:02d}" for index in range(1, candidate_count + 1)]
        imagegen_request = {
            "backend": "official_host_image_generation_skill_or_tool",
            "raw_api_required": False,
            "candidate_count": candidate_count,
            "candidate_ids": candidate_ids,
            "aspect_ratio": config["generation"]["aspect_ratio"],
            "quality": config["generation"]["quality"],
            "output_format": config["generation"]["output_format"],
            "prompt_path": str(planning_dir / "final_prompt.txt"),
            "input_images": [str(path) for path in generation_inputs],
            "input_roles_path": str(planning_dir / "input_roles.json"),
            "instruction": "Invoke the host's official image-generation capability. Prefer one multi-output invocation; otherwise make separate invocations with the same ordered inputs and prompt.",
        }
        _write_json(planning_dir / "imagegen_request.json", imagegen_request)
        write_generation_handoff(
            output_dir,
            launcher=Path(__file__).resolve().parent / "run.py",
            imagegen_request=imagegen_request,
        )

        run_manifest["status"] = "prepared_for_image_generation"
        run_manifest["finished_at"] = _now()
        run_manifest["steps"].append({"name": "image_generation", "status": "delegated_to_host_tool", "at": _now()})
        (final_dir / "report.md").write_text(
            _build_report(model_manifest, camera_plan, run_manifest["status"], run_manifest["warnings"], False),
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
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    try:
        config, discovery = _load_or_build_config(args)
        prepare_run(
            config,
            discovery,
            grid_only=args.grid_only,
            view_id=args.view_id,
            camera_plan_path=args.camera_plan,
            reference_roles_path=args.reference_roles,
            render_brief_path=args.render_brief,
            strict_geometry=args.strict_geometry,
        )
    except (ConfigError, InputDiscoveryError, FileNotFoundError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    os.environ.setdefault("VTK_DEFAULT_RENDER_WINDOW_OFFSCREEN", "1")
    raise SystemExit(main())
