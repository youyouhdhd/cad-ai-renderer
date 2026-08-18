#!/usr/bin/env python3
"""Generate real STEP fixtures and test the model-neutral local workflow."""

from __future__ import annotations

import argparse
import copy
import json
import os
import shutil
import subprocess
import sys
import traceback
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from cad_render import _render_resolution, create_render_plan, prepare_run
from config import ConfigError, build_direct_config, product_view_specs, validate_config
from final_refinement import finish_final_master, stage_final_master
from finalize_candidates import finalize
from geometry_metrics import score_candidate
from input_discovery import discover_inputs
from preflight import run_preflight
from run import BOOTSTRAP_MARKER, _lock_is_stale, _managed_environment_action, _select_best_interpreter
from runtime_layout import AUXILIARY_DIRNAME, resolve_auxiliary_dir
from render_contract import load_and_validate_render_contract, validate_retry_delta
from step_to_glb import convert_model


def _confirmed_render_plan(
    config: dict[str, Any],
    discovery: dict[str, Any],
    path: Path,
    *,
    view_id: str | None = None,
    candidates: int | None = None,
) -> Path:
    result = create_render_plan(
        config,
        discovery,
        requested_view_id=view_id,
        requested_candidate_count=candidates,
        plan_path=path,
    )
    plan = result["plan"]
    plan["confirmation"]["confirmed"] = True
    plan["confirmation"]["confirmed_by_user"] = True
    path.write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def _create_step_fixtures(root: Path) -> tuple[Path, Path]:
    import cadquery as cq

    fixtures = root / "fixtures"
    fixtures.mkdir(parents=True, exist_ok=True)

    assembly_path = fixtures / "colored_assembly.step"
    base = cq.Workplane("XY").box(60, 42, 8, centered=(True, True, False)).edges("|Z").fillet(3).val()
    post = (
        cq.Workplane("XY")
        .workplane(offset=8)
        .circle(10)
        .extrude(30)
        .edges(">Z")
        .fillet(1.5)
        .val()
    )
    rail = cq.Workplane("XZ").workplane(offset=-21).box(42, 8, 10, centered=(True, False, False)).val()
    assembly = cq.Assembly(name="self_test_assembly")
    assembly.add(base, name="base", color=cq.Color(0.72, 0.18, 0.10))
    assembly.add(post, name="post", color=cq.Color(0.10, 0.34, 0.78))
    assembly.add(rail, name="rail", color=cq.Color(0.14, 0.58, 0.34))
    assembly.save(str(assembly_path), exportType="STEP")

    colorless_path = fixtures / "colorless_bracket.step"
    bracket = (
        cq.Workplane("XY")
        .box(72, 48, 8, centered=(True, True, False))
        .faces(">Z")
        .workplane()
        .pushPoints([(-24, 0), (24, 0)])
        .hole(10)
        .faces(">Z")
        .workplane(offset=0)
        .rect(34, 14)
        .extrude(22)
        .edges("|Z")
        .fillet(2)
    )
    cq.exporters.export(bracket, str(colorless_path))
    return assembly_path, colorless_path


def _create_reference(path: Path) -> Path:
    image = Image.new("RGB", (640, 480), (224, 219, 210))
    draw = ImageDraw.Draw(image)
    draw.rectangle((90, 100, 550, 390), fill=(79, 86, 92))
    draw.ellipse((190, 130, 450, 350), fill=(184, 139, 92))
    draw.text((24, 24), "material + lighting reference", fill=(30, 30, 30))
    image.save(path, quality=92)
    return path


def _make_candidates(preview_path: Path, output_dir: Path) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    source = Image.open(preview_path).convert("RGB")
    width, height = source.size
    paths: list[Path] = []

    exact = output_dir / "candidate_01.png"
    source.save(exact)
    paths.append(exact)

    shifted = Image.new("RGB", (width, height), (240, 240, 240))
    shifted.paste(source, (max(18, width // 18), 0))
    shifted_path = output_dir / "candidate_02.png"
    shifted.save(shifted_path)
    paths.append(shifted_path)

    scaled_image = source.resize((int(width * 0.72), int(height * 0.72)), Image.Resampling.LANCZOS)
    scaled = Image.new("RGB", (width, height), (240, 240, 240))
    scaled.paste(scaled_image, ((width - scaled_image.width) // 2, (height - scaled_image.height) // 2))
    scaled_path = output_dir / "candidate_03.png"
    scaled.save(scaled_path)
    paths.append(scaled_path)

    blurred_path = output_dir / "candidate_04.png"
    source.filter(ImageFilter.GaussianBlur(max(5, width // 64))).save(blurred_path)
    paths.append(blurred_path)
    return paths


def _image_stats(path: Path) -> dict[str, Any]:
    array = np.asarray(Image.open(path))
    if array.ndim == 3:
        unique = int(len(np.unique(array.reshape(-1, array.shape[-1]), axis=0)))
    else:
        unique = int(len(np.unique(array)))
    return {
        "path": str(path),
        "shape": list(array.shape),
        "min": int(array.min()),
        "max": int(array.max()),
        "unique_approx": unique,
    }


def _package_text_is_model_neutral(skill_root: Path) -> tuple[bool, list[str]]:
    forbidden = [
        "gpt-" + "5.6",
        "gpt-" + "image-2",
        "OPENAI" + "_API_KEY",
        "api." + "openai.com",
        "reasoning" + "_model",
    ]
    hits: list[str] = []
    for path in skill_root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in {".py", ".md", ".yaml", ".yml", ".json", ".txt"}:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for token in forbidden:
            if token in text:
                hits.append(f"{path.relative_to(skill_root)}:{token}")
    return not hits, hits


def run_self_test(output_dir: str | Path) -> dict[str, Any]:
    root = Path(output_dir).expanduser().resolve()
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {
        "status": "running",
        "checks": [],
        "errors": [],
        "output_dir": str(root),
        "python": sys.executable,
        "managed_venv": os.environ.get("CAD_AI_RENDERER_MANAGED_VENV"),
    }
    try:
        preflight = run_preflight()
        required_ok = all(item["ok"] for item in preflight["modules"])
        report["checks"].append({"name": "required_dependencies", "ok": required_ok, "details": preflight})
        if not required_ok:
            raise RuntimeError("Required dependencies are missing")

        managed_value = os.environ.get("CAD_AI_RENDERER_MANAGED_VENV")
        managed_mode = os.environ.get("CAD_AI_RENDERER_VENV_MODE")
        managed_path = Path(managed_value).expanduser().resolve() if managed_value else None
        executable_path = Path(sys.executable).resolve()
        environment_ok = bool(
            preflight["python"].get("inside_virtualenv")
            and managed_path
            and executable_path.is_relative_to(managed_path)
            and managed_mode in {"isolated", "host-linked", "external"}
        )
        report["checks"].append(
            {
                "name": "dedicated_environment_contract",
                "ok": environment_ok,
                "managed_venv": str(managed_path) if managed_path else None,
                "managed_venv_mode": managed_mode,
                "executable": str(executable_path),
            }
        )
        if not environment_ok:
            raise RuntimeError("Self-test was not executed through the dedicated environment launcher")

        selected = _select_best_interpreter(
            [
                {"executable": "/python39", "version": (3, 9, 20), "bits": 64},
                {"executable": "/python313", "version": (3, 13, 4), "bits": 64},
                {"executable": "/python312", "version": (3, 12, 8), "bits": 64},
                {"executable": "/python311", "version": (3, 11, 10), "bits": 64},
            ]
        )
        resume_action = _managed_environment_action(
            exists=True,
            recognized=True,
            python_pair=(3, 12),
            current_pair=(3, 12),
            refresh=False,
        )
        explicit_selected = _select_best_interpreter(
            [
                {"executable": "/python312", "version": (3, 12, 8), "bits": 64, "source": "current"},
                {"executable": "/explicit-python313", "version": (3, 13, 4), "bits": 64, "source": "explicit"},
            ]
        )
        migrated_lock = root / "foreign-host.bootstrap.lock"
        migrated_lock.mkdir(parents=True, exist_ok=True)
        (migrated_lock / "owner.json").write_text(
            json.dumps({"pid": 1, "hostname": "copied-from-another-host", "started_at": 1}),
            encoding="utf-8",
        )
        foreign_lock_stale = _lock_is_stale(migrated_lock)
        ownerless_lock = root / "fresh-ownerless.bootstrap.lock"
        ownerless_lock.mkdir(parents=True, exist_ok=True)
        fresh_ownerless_lock_preserved = not _lock_is_stale(ownerless_lock)
        bootstrap_ok = bool(
            selected
            and selected["version"][:2] == (3, 12)
            and explicit_selected
            and explicit_selected["source"] == "explicit"
            and resume_action == "resume"
            and foreign_lock_stale
            and fresh_ownerless_lock_preserved
        )
        report["checks"].append(
            {
                "name": "portable_bootstrap_selection_and_resume",
                "ok": bootstrap_ok,
                "selected": selected,
                "explicit_override_selected": explicit_selected,
                "partial_environment_action": resume_action,
                "foreign_host_lock_treated_as_stale": foreign_lock_stale,
                "fresh_ownerless_lock_preserved": fresh_ownerless_lock_preserved,
            }
        )
        if not bootstrap_ok:
            raise RuntimeError("Bootstrap interpreter selection or resumable-environment decision failed")

        skill_root = Path(__file__).resolve().parent.parent
        help_env = os.environ.copy()
        help_env[BOOTSTRAP_MARKER] = "1"
        help_process = subprocess.run(
            [
                sys.executable,
                str(skill_root / "scripts" / "run.py"),
                "--venv-dir",
                str(managed_path),
                "--no-install",
                "finalize",
                "--help",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=180,
            env=help_env,
        )
        help_text = help_process.stdout + help_process.stderr
        refine_help_process = subprocess.run(
            [
                sys.executable,
                str(skill_root / "scripts" / "run.py"),
                "--venv-dir",
                str(managed_path),
                "--no-install",
                "refine-stage",
                "--help",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=180,
            env=help_env,
        )
        finish_help_process = subprocess.run(
            [
                sys.executable,
                str(skill_root / "scripts" / "run.py"),
                "--venv-dir",
                str(managed_path),
                "--no-install",
                "finish",
                "--help",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=180,
            env=help_env,
        )
        refine_help = refine_help_process.stdout + refine_help_process.stderr
        finish_help = finish_help_process.stdout + finish_help_process.stderr
        help_ok = (
            help_process.returncode == 0
            and "--visual-qa" in help_text
            and "--stage-only" in help_text
            and "--candidate" in help_text
            and refine_help_process.returncode == 0
            and "--master" in refine_help
            and finish_help_process.returncode == 0
            and "--final-qa" in finish_help
        )
        report["checks"].append(
            {
                "name": "command_specific_help_dispatch",
                "ok": help_ok,
                "returncode": help_process.returncode,
                "help_excerpt": help_text[-2000:],
                "refine_help_excerpt": refine_help[-1000:],
                "finish_help_excerpt": finish_help[-1000:],
            }
        )
        if not help_ok:
            raise RuntimeError("The launcher did not delegate command-specific help")

        assembly_step, colorless_step = _create_step_fixtures(root)
        reference = _create_reference(root / "attached_reference.jpg")
        fixtures_ok = assembly_step.exists() and colorless_step.exists() and reference.exists()
        report["checks"].append(
            {
                "name": "generate_real_step_and_reference_fixtures",
                "ok": fixtures_ok,
                "files": [str(assembly_step), str(colorless_step), str(reference)],
            }
        )
        if not fixtures_ok:
            raise RuntimeError("Fixture generation failed")

        discovery = discover_inputs([assembly_step, reference])
        discovery_ok = (
            discovery["model"] == str(assembly_step.resolve())
            and len(discovery["references"]) == 1
            and discovery["references"][0]["roles"] == ["mixed"]
        )
        report["checks"].append(
            {"name": "attachment_input_discovery_without_yaml", "ok": discovery_ok, "details": discovery}
        )
        if not discovery_ok:
            raise RuntimeError("Attachment discovery did not identify model and reference")

        plan_probe_output = root / "plan_probe_output"
        plan_probe_config = build_direct_config(
            assembly_step,
            plan_probe_output,
            description="Plan confirmation contract.",
            references=discovery["references"],
            overrides={"render": {"width": 256, "height": 256}},
        )
        plan_probe_path = plan_probe_output / "planning" / "render_plan.json"
        adaptive_final_anchor = _render_resolution(plan_probe_config, "final_anchor_resolution")
        plan_probe = create_render_plan(plan_probe_config, discovery, plan_path=plan_probe_path)
        plan_payload = plan_probe["plan"]
        priority_plan = create_render_plan(
            plan_probe_config,
            discovery,
            requested_view_id="back",
            requested_candidate_count=4,
            plan_path=plan_probe_output / "planning" / "priority_render_plan.json",
        )["plan"]
        blocked_without_confirmation = False
        try:
            prepare_run(plan_probe_config, discovery)
        except ConfigError:
            blocked_without_confirmation = True
        plan_ok = (
            plan_payload["confirmation"]["confirmed"] is False
            and len(plan_payload["reference_plan"]["view_ids"]) == 14
            and plan_payload["generation_plan"]["view_ids"]
            == ["front", "back", "left", "front_right_axonometric_upper"]
            and plan_payload["generation_plan"]["total_candidate_count"] == 4
            and plan_payload["generation_plan"]["requested_native_size"] == "auto"
            and plan_payload["final_output"]["width"] > 0
            and plan_payload["final_output"]["height"] > 0
            and adaptive_final_anchor == (4096, 4096)
            and priority_plan["reference_plan"]["view_ids"][0] == "back"
            and priority_plan["generation_plan"]["view_ids"] == ["back"]
            and priority_plan["generation_plan"]["total_candidate_count"] == 4
            and blocked_without_confirmation
        )
        report["checks"].append(
            {
                "name": "editable_render_plan_confirmation_gate_and_candidate_policy",
                "ok": plan_ok,
                "reference_view_count": len(plan_payload["reference_plan"]["view_ids"]),
                "final_view_ids": plan_payload["generation_plan"]["view_ids"],
                "final_candidate_count": plan_payload["generation_plan"]["total_candidate_count"],
                "adaptive_final_anchor": adaptive_final_anchor,
            }
        )
        if not plan_ok:
            raise RuntimeError("Render-plan confirmation gate or candidate policy failed")

        grid_output = root / "grid_only_output"
        grid_config = build_direct_config(
            assembly_step,
            grid_output,
            description="Premium studio render with brushed metal and dark polymer.",
            references=discovery["references"],
            overrides={
                "render": {
                    "width": 384,
                    "height": 384,
                    "view_grid_resolution": {"width": 384, "height": 384},
                    "candidate_anchor_resolution": {"width": 384, "height": 384},
                    "final_anchor_resolution": {"width": 512, "height": 512},
                },
                "camera": {
                    "view_set": "grid",
                    "view_grid_azimuths": [0, 90],
                    "view_grid_elevations": [15, 30],
                },
            },
        )
        grid_manifest = prepare_run(grid_config, discovery, grid_only=True)
        grid_ok = (
            grid_manifest["status"] == "camera_selection_needed"
            and (grid_output / AUXILIARY_DIRNAME / "view_grid.png").exists()
            and (grid_output / "planning" / "camera_selection_prompt.txt").exists()
        )
        report["checks"].append({"name": "two_stage_camera_grid", "ok": grid_ok})
        if not grid_ok:
            raise RuntimeError("Grid-only stage failed")

        multi_output = root / "multi_view_output"
        multi_config = build_direct_config(
            assembly_step,
            multi_output,
            description="Directional product-view coverage.",
            references=discovery["references"],
            overrides={
                "render": {
                    "width": 256,
                    "height": 256,
                    "view_grid_resolution": {"width": 256, "height": 256},
                    "candidate_anchor_resolution": {"width": 256, "height": 256},
                    "final_anchor_resolution": {"width": 512, "height": 512},
                },
                "camera": {
                    "view_set": "all",
                },
                "generation": {"candidates": 4},
            },
        )
        multi_plan_path = _confirmed_render_plan(
            multi_config,
            discovery,
            multi_output / "planning" / "render_plan.json",
        )
        multi_manifest = prepare_run(multi_config, discovery, render_plan_path=multi_plan_path)
        default_view_ids = [item["view_id"] for item in product_view_specs()]
        multi_view_ids = [item.get("view_id") for item in multi_manifest.get("view_bundles", [])]
        multi_candidate_ids = [
            candidate_id
            for bundle in multi_manifest.get("view_bundles", [])
            for candidate_id in bundle.get("candidate_ids", [])
        ]
        multi_ok = (
            multi_manifest["status"] == "prepared_for_image_generation"
            and multi_manifest.get("view_count") == 4
            and len(default_view_ids) == 14
            and multi_view_ids == ["front", "back", "left", "front_right_axonometric_upper"]
            and multi_candidate_ids == ["C01", "C02", "C03", "C04"]
            and (multi_output / AUXILIARY_DIRNAME / "view_grid.json").exists()
            and (multi_output / "planning" / "imagegen_request.json").exists()
            and (multi_output / "planning" / "host_handoff.json").exists()
            and all(
                (
                    (multi_output / "views" / str(view_id) / AUXILIARY_DIRNAME / "color_preview.png").exists()
                    and (multi_output / "views" / str(view_id) / "planning" / "imagegen_request.json").exists()
                    and (multi_output / "views" / str(view_id) / "planning" / "render_contract.json").exists()
                    and (multi_output / "views" / str(view_id) / "final_refinement" / "auxiliary" / "lineart.png").exists()
                )
                for view_id in multi_view_ids
            )
        )
        report["checks"].append(
            {
                "name": "default_directional_multi_view_bundle",
                "ok": multi_ok,
                "default_view_count": len(default_view_ids),
                "prepared_view_ids": multi_view_ids,
                "final_candidate_ids": multi_candidate_ids,
            }
        )
        if not multi_ok:
            raise RuntimeError("Default directional multi-view bundle failed")

        pipeline_output = root / "pipeline_output"
        config = build_direct_config(
            assembly_step,
            pipeline_output,
            description="Premium studio render with brushed metal and dark polymer.",
            references=discovery["references"],
            overrides={
                "render": {
                    "width": 384,
                    "height": 384,
                    "view_grid_resolution": {"width": 384, "height": 384},
                    "candidate_anchor_resolution": {"width": 384, "height": 384},
                    "final_anchor_resolution": {"width": 512, "height": 512},
                },
                "camera": {
                    "view_set": "grid",
                    "view_grid_azimuths": [0, 90],
                    "view_grid_elevations": [15, 30],
                },
                "geometry": {"converter": "cadquery", "anchor_mode": "balanced"},
                "generation": {"candidates": 4, "aspect_ratio": "1:1", "quality": "high"},
                "final_output": {"width": 768, "height": 768, "format": "png", "resize_policy": "fit_pad"},
            },
        )
        plan_path = _confirmed_render_plan(
            config,
            discovery,
            pipeline_output / "planning" / "render_plan.json",
            view_id="V02",
            candidates=4,
        )
        manifest = prepare_run(config, discovery, render_plan_path=plan_path)
        required_files = [
            pipeline_output / AUXILIARY_DIRNAME / "view_grid.png",
            pipeline_output / AUXILIARY_DIRNAME / "color_preview.png",
            pipeline_output / AUXILIARY_DIRNAME / "clay.png",
            pipeline_output / AUXILIARY_DIRNAME / "lineart.png",
            pipeline_output / AUXILIARY_DIRNAME / "mask.png",
            pipeline_output / AUXILIARY_DIRNAME / "normal.png",
            pipeline_output / AUXILIARY_DIRNAME / "depth.png",
            pipeline_output / AUXILIARY_DIRNAME / "part_id.png",
            pipeline_output / "planning" / "input_roles.json",
            pipeline_output / "planning" / "geometry_contract.json",
            pipeline_output / "planning" / "scene_contract.json",
            pipeline_output / "planning" / "output_contract.json",
            pipeline_output / "planning" / "render_contract.json",
            pipeline_output / "planning" / "retry_delta.template.json",
            pipeline_output / "planning" / "final_prompt.txt",
            pipeline_output / "planning" / "imagegen_request.json",
            pipeline_output / "planning" / "host_handoff.json",
            pipeline_output / "planning" / "NEXT_STEPS.md",
            pipeline_output / "planning" / "visual_qa.template.json",
            pipeline_output / "final_refinement" / "auxiliary" / "color_preview.png",
            pipeline_output / "final_refinement" / "auxiliary" / "clay.png",
            pipeline_output / "final_refinement" / "auxiliary" / "lineart.png",
        ]
        pipeline_view_grid = json.loads(
            (pipeline_output / AUXILIARY_DIRNAME / "view_grid.json").read_text(encoding="utf-8")
        )
        grid_thumbnail_size = tuple(pipeline_view_grid[0]["camera"]["image_size"])
        with Image.open(pipeline_output / AUXILIARY_DIRNAME / "color_preview.png") as image:
            candidate_anchor_size = image.size
        with Image.open(pipeline_output / "final_refinement" / "auxiliary" / "color_preview.png") as image:
            final_anchor_size = image.size
        frozen_contract, frozen_consistency = load_and_validate_render_contract(pipeline_output)
        prepare_ok = (
            manifest["status"] == "prepared_for_image_generation"
            and all(path.exists() for path in required_files)
            and pipeline_view_grid[0]["view_id"] == "V02"
            and grid_thumbnail_size[0] <= 384
            and candidate_anchor_size == (384, 384)
            and final_anchor_size == (512, 512)
            and frozen_consistency["contract_consistency_pass"]
            and frozen_contract["final_output"]["width"] == 768
            and frozen_contract["final_output"]["height"] == 768
        )
        report["checks"].append(
            {
                "name": "contract_frozen_stage_aware_anchor_pipeline",
                "ok": prepare_ok,
                "files": [str(path) for path in required_files],
                "view_grid_resolution_contract": frozen_contract["anchor_policy"]["view_grid_resolution"],
                "grid_thumbnail_size": grid_thumbnail_size,
                "candidate_anchor_size": candidate_anchor_size,
                "final_anchor_size": final_anchor_size,
                "contract_id": frozen_contract.get("contract_id"),
            }
        )
        if not prepare_ok:
            raise RuntimeError("Local preparation pipeline failed")

        resolved_auxiliary = resolve_auxiliary_dir(pipeline_output, create=False)
        layout_ok = (
            resolved_auxiliary.name == "auxiliary"
            and resolved_auxiliary.exists()
            and not (pipeline_output / "aux").exists()
            and manifest.get("paths", {}).get("auxiliary") == str(resolved_auxiliary)
        )
        report["checks"].append(
            {
                "name": "windows_safe_portable_output_layout",
                "ok": layout_ok,
                "auxiliary_dir": str(resolved_auxiliary),
            }
        )
        if not layout_ok:
            raise RuntimeError("Portable auxiliary output layout is invalid")

        stats = [_image_stats(path) for path in required_files[:8] if path.suffix == ".png"]
        nonblank = all(item["max"] > item["min"] and item["unique_approx"] >= 2 for item in stats)
        report["checks"].append({"name": "auxiliary_images_nonblank", "ok": nonblank, "stats": stats})
        if not nonblank:
            raise RuntimeError("One or more auxiliary images are blank")

        request = json.loads((pipeline_output / "planning" / "imagegen_request.json").read_text(encoding="utf-8"))
        handoff = json.loads((pipeline_output / "planning" / "host_handoff.json").read_text(encoding="utf-8"))
        finalize_argv = handoff.get("finalization", {}).get("command_argv_template", [])
        delegation_ok = (
            request.get("raw_api_required") is False
            and request.get("host_skill") == "imagegen"
            and request.get("target_resolution") == "4k"
            and request.get("requested_native_size") == "auto"
            and request.get("detail_level") == "high"
            and request.get("candidate_count") == 4
            and request.get("candidate_ids") == ["C01", "C02", "C03", "C04"]
            and len(request.get("input_images", [])) >= 4
            and request.get("render_contract_path") == str(pipeline_output / "planning" / "render_contract.json")
            and request.get("exact_final_output", {}).get("width") == 768
            and request.get("exact_final_output", {}).get("height") == 768
            and request.get("tool_parameters", {}).get("candidate_count") == 4
            and manifest.get("raw_image_api_used") is False
            and handoff.get("stage") == "host_image_generation"
            and handoff.get("image_generation", {}).get("host_skill") == "imagegen"
            and handoff.get("image_generation", {}).get("target_resolution") == "4k"
            and handoff.get("image_generation", {}).get("render_contract") == str(pipeline_output / "planning" / "render_contract.json")
            and handoff.get("image_generation", {}).get("quality") == "high"
            and "stage" in handoff.get("candidate_staging", {}).get("command_argv_template", [])
            and "finalize" in finalize_argv
            and "--candidate" not in finalize_argv
        )
        report["checks"].append({"name": "official_image_skill_delegation_contract", "ok": delegation_ok, "request": request})
        if not delegation_ok:
            raise RuntimeError("Image-generation delegation contract is invalid")

        invalid_retry_rejected = False
        try:
            validate_retry_delta(
                frozen_contract,
                {
                    "retry_from_contract_revision": frozen_contract["contract_revision"],
                    "exact_failures": ["hole-A missing"],
                    "anchor_mode": "max_geometry",
                    "camera": {"azimuth": 90},
                },
            )
        except ValueError:
            invalid_retry_rejected = True
        retry_delta_path = root / "retry_delta.json"
        retry_delta_path.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "retry_from_contract_revision": frozen_contract["contract_revision"],
                    "exact_failures": ["restore the two modeled circular holes"],
                    "anchor_mode": "max_geometry",
                    "appearance_delta": {},
                    "lighting_delta": {},
                    "notes": "Synthetic contract-scoped retry.",
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        retry_manifest = prepare_run(
            config,
            discovery,
            strict_geometry=True,
            retry_delta_path=retry_delta_path,
            render_plan_path=plan_path,
        )
        retry_contract, retry_consistency = load_and_validate_render_contract(pipeline_output)
        retry_request = json.loads(
            (pipeline_output / "planning" / "imagegen_request.json").read_text(encoding="utf-8")
        )
        retry_ok = (
            invalid_retry_rejected
            and retry_manifest["status"] == "prepared_for_image_generation"
            and retry_contract["contract_id"] == frozen_contract["contract_id"]
            and retry_contract["contract_revision"] == frozen_contract["contract_revision"] + 1
            and retry_contract["retry_delta"]["exact_failures"] == ["restore the two modeled circular holes"]
            and retry_contract["anchor_policy"]["candidate_anchor_mode"] == "max_geometry"
            and retry_request["candidate_ids"] == ["R01", "R02", "R03", "R04"]
            and retry_consistency["contract_consistency_pass"]
        )
        report["checks"].append(
            {
                "name": "retry_delta_preserves_frozen_contract_and_revises_once",
                "ok": retry_ok,
                "contract_id": retry_contract.get("contract_id"),
                "contract_revision": retry_contract.get("contract_revision"),
            }
        )
        if not retry_ok:
            raise RuntimeError("Contract-scoped retry validation failed")

        candidates = _make_candidates(pipeline_output / AUXILIARY_DIRNAME / "color_preview.png", root / "mock_candidates")
        local_scores = []
        for index, path in enumerate(candidates, start=1):
            score = score_candidate(
                pipeline_output / AUXILIARY_DIRNAME / "lineart.png",
                pipeline_output / AUXILIARY_DIRNAME / "mask.png",
                path,
                max_edge_distance_px=18,
            )
            score["candidate_id"] = f"C{index:02d}"
            local_scores.append(score)
        metric_best = max(local_scores, key=lambda item: item["geometry_score_local"])
        metric_ok = metric_best["candidate_id"] == "C01" and local_scores[0]["geometry_score_local"] > local_scores[-1]["geometry_score_local"]
        report["checks"].append(
            {"name": "local_geometry_metric_ranking", "ok": metric_ok, "scores": local_scores}
        )
        if not metric_ok:
            raise RuntimeError("Local geometry metrics did not rank the exact candidate first")

        candidate_specs = [f"R{index:02d}={path}" for index, path in enumerate(candidates, start=1)]
        staged = finalize(pipeline_output, candidate_specs, stage_only=True)
        staged_best_files = list((pipeline_output / "final").glob("best.*"))
        stage_ok = (
            staged["status"] == "awaiting_visual_qa"
            and staged["best"] is None
            and not staged_best_files
            and not (pipeline_output / "final" / "selection.json").exists()
            and (pipeline_output / "candidates" / "contact_sheet.png").exists()
            and (pipeline_output / "candidates" / "candidate_resolution_report.json").exists()
            and (pipeline_output / "planning" / "qa_prompt.txt").exists()
        )
        report["checks"].append(
            {
                "name": "candidate_staging_does_not_prematurely_select",
                "ok": stage_ok,
                "result": staged,
            }
        )
        if not stage_ok:
            raise RuntimeError("Candidate staging created a premature final selection")

        visual_qa_path = root / "visual_qa.json"
        visual_qa = {
            "candidates": [
                {"candidate_id": "R01", "geometry_score": 98, "overall_score": 94},
                {"candidate_id": "R02", "geometry_score": 65, "overall_score": 70},
                {"candidate_id": "R03", "geometry_score": 45, "overall_score": 58},
                {"candidate_id": "R04", "geometry_score": 30, "overall_score": 42},
            ],
            "best_candidate_id": "R01",
            "retry_recommended": False,
            "decision_summary": "Synthetic visual QA for the self-test.",
        }
        visual_qa_path.write_text(json.dumps(visual_qa, indent=2), encoding="utf-8")
        finalization = finalize(
            pipeline_output,
            visual_qa_path=visual_qa_path,
        )
        report_path = pipeline_output / "final" / "report.md"
        first_report = report_path.read_text(encoding="utf-8")
        repeated = finalize(
            pipeline_output,
            visual_qa_path=visual_qa_path,
        )
        second_report = report_path.read_text(encoding="utf-8")
        finalize_ok = (
            finalization["status"] == "awaiting_final_refinement"
            and finalization["best"]["candidate_id"] == "R01"
            and repeated["best"]["candidate_id"] == "R01"
            and all(Path(record["path"]).parent == pipeline_output / "candidates" / "images" for record in finalization["records"])
            and (pipeline_output / "candidates" / "contact_sheet.png").exists()
            and not (pipeline_output / "final" / "best.png").exists()
            and (pipeline_output / "final" / "selection.json").exists()
            and (pipeline_output / "planning" / "final_refine_request.json").exists()
        )
        report["checks"].append({"name": "candidate_visual_qa_selects_without_premature_delivery", "ok": finalize_ok})
        if not finalize_ok:
            raise RuntimeError("Candidate selection/final-refinement handoff failed")

        report_idempotent = first_report == second_report and second_report.count("## Candidate QA") == 1
        report["checks"].append(
            {
                "name": "idempotent_structured_final_report",
                "ok": report_idempotent,
                "candidate_qa_heading_count": second_report.count("## Candidate QA"),
            }
        )
        if not report_idempotent:
            raise RuntimeError("Final report accumulated duplicate or inconsistent sections")

        refinement_stage = stage_final_master(pipeline_output, f"F01={candidates[0]}")
        final_qc_path = root / "final_qc.host.json"
        final_qc_path.write_text(
            json.dumps(
                {
                    "candidate_id": "F01",
                    "approve_delivery": True,
                    "geometry_score": 98,
                    "visual_quality_score": 95,
                    "visual_quality_pass": True,
                    "contract_consistency_pass": True,
                    "geometry_failures": [],
                    "issues": [],
                    "strengths": ["Synthetic exact-geometry master"],
                    "decision_summary": "Synthetic final QC for the self-test.",
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        finished = finish_final_master(pipeline_output, final_qc_path)
        final_report_text = (pipeline_output / "final" / "report.md").read_text(encoding="utf-8")
        finished_again = finish_final_master(pipeline_output, final_qc_path)
        final_report_again = (pipeline_output / "final" / "report.md").read_text(encoding="utf-8")
        with Image.open(pipeline_output / "final" / "best.png") as image:
            delivered_size = image.size
        resolution_payload = json.loads(
            (pipeline_output / "final" / "resolution_report.json").read_text(encoding="utf-8")
        )
        final_refinement_ok = (
            refinement_stage["status"] == "awaiting_final_qc"
            and finished["status"] == "complete_exact_dimensions_upscaled"
            and finished_again["status"] == "complete_exact_dimensions_upscaled"
            and delivered_size == (768, 768)
            and resolution_payload["delivered_final_size"] == {"width": 768, "height": 768}
            and resolution_payload["upscaled"] is True
            and resolution_payload["target_met_natively"] is False
            and (pipeline_output / "final" / "final_qc.json").exists()
            and final_report_text == final_report_again
        )
        report["checks"].append(
            {
                "name": "final_refinement_resolution_gate_and_exact_delivery",
                "ok": final_refinement_ok,
                "status": finished.get("status"),
                "delivered_size": delivered_size,
                "resolution_report": resolution_payload,
            }
        )
        if not final_refinement_ok:
            raise RuntimeError("Final refinement or exact-resolution delivery gate failed")

        render_brief_path = pipeline_output / "planning" / "render_brief.json"
        original_brief = render_brief_path.read_text(encoding="utf-8")
        render_brief_path.write_text(original_brief + "\n", encoding="utf-8")
        tamper_rejected = False
        try:
            load_and_validate_render_contract(pipeline_output)
        except ValueError:
            tamper_rejected = True
        finally:
            render_brief_path.write_text(original_brief, encoding="utf-8")
        restored_contract_ok = load_and_validate_render_contract(pipeline_output)[1]["contract_consistency_pass"]
        contract_guard_ok = tamper_rejected and restored_contract_ok
        report["checks"].append(
            {"name": "frozen_contract_tamper_rejected_and_restore_verified", "ok": contract_guard_ok}
        )
        if not contract_guard_ok:
            raise RuntimeError("Frozen contract tamper detection failed")

        colorless_glb = root / "colorless" / "model.glb"
        colorless_manifest = convert_model(
            colorless_step,
            colorless_glb,
            root / "colorless" / "manifest.json",
            converter="cadquery",
        )
        colorless_ok = colorless_manifest.get("source_has_useful_colors") is False
        report["checks"].append(
            {"name": "colorless_step_detection", "ok": colorless_ok, "manifest": colorless_manifest}
        )
        if not colorless_ok:
            raise RuntimeError("Colorless STEP was not detected as colorless")

        invalid = copy.deepcopy(config)
        invalid["generation"]["aspect_ratio"] = "7:5"
        invalid_rejected = False
        try:
            validate_config(invalid, require_files=True)
        except ConfigError:
            invalid_rejected = True
        report["checks"].append({"name": "model_neutral_configuration_validation", "ok": invalid_rejected})
        if not invalid_rejected:
            raise RuntimeError("Invalid model-neutral configuration was accepted")

        neutral_ok, forbidden_hits = _package_text_is_model_neutral(skill_root)
        no_api_client = not (skill_root / "scripts" / "openai_rest.py").exists()
        neutral_ok = neutral_ok and no_api_client
        report["checks"].append(
            {
                "name": "no_model_lock_or_raw_image_api_client",
                "ok": neutral_ok,
                "forbidden_hits": forbidden_hits,
                "openai_rest_absent": no_api_client,
            }
        )
        if not neutral_ok:
            raise RuntimeError("Model-lock or raw API artifacts remain in the package")

        report["status"] = "passed"
    except Exception as exc:
        report["status"] = "failed"
        report["errors"].append(
            {"type": type(exc).__name__, "message": str(exc), "traceback": traceback.format_exc()}
        )

    report_path = root / "self_test_report.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    markdown = [
        "# CAD AI Renderer Self-Test",
        "",
        f"Status: **{report['status'].upper()}**",
        "",
        "The test verifies portable interpreter selection, concurrent-lock safety, attachment discovery, real STEP conversion, stage-aware CAD anchors, frozen render/output/geometry contracts, host tool-parameter delegation, contract-scoped retry deltas, candidate native-size reporting, candidate selection without premature delivery, one final-refinement master, final QC, exact-pixel resolution gating, tamper rejection, idempotent reporting, colorless STEP detection, and the absence of model locks or a raw image API client. The host image-generation tool itself is not callable from this local Python test.",
        "",
        "## Checks",
        "",
        "| Check | Result |",
        "|---|---|",
    ]
    for check in report["checks"]:
        markdown.append(f"| {check['name']} | {'PASS' if check.get('ok') else 'FAIL'} |")
    if report["errors"]:
        markdown.extend(["", "## Errors", "", "```json", json.dumps(report["errors"], indent=2), "```"])
    markdown.extend(["", f"Machine-readable report: `{report_path}`", ""])
    (root / "SELF_TEST.md").write_text("\n".join(markdown), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="./cad-ai-renderer-self-test")
    args = parser.parse_args()
    report = run_self_test(args.output)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
