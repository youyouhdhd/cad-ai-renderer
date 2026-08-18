#!/usr/bin/env python3
"""Write machine-readable and human-readable handoff instructions for the host."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(payload), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _input_arguments(model: str, references: Sequence[Mapping[str, Any]]) -> list[str]:
    arguments = ["--input", model]
    for reference in references:
        path = reference.get("path")
        if path:
            arguments.extend(["--input", str(path)])
    return arguments


def write_camera_handoff(
    run_dir: str | Path,
    *,
    launcher: str | Path,
    model: str,
    references: Sequence[Mapping[str, Any]],
    intent: str,
    view_grid: str | Path,
    view_grid_json: str | Path,
) -> dict[str, Any]:
    root = Path(run_dir).expanduser().resolve()
    planning = root / "planning"
    camera_target = planning / "camera_plan.host.json"
    arguments = [
        "python",
        str(Path(launcher).resolve()),
        "prepare",
        *_input_arguments(model, references),
        "--intent",
        intent,
        "--output",
        str(root),
        "--camera-plan",
        str(camera_target),
    ]
    payload = {
        "contract_version": "3.0",
        "stage": "camera_selection",
        "status": "camera_selection_needed",
        "run_dir": str(root),
        "inspect": {
            "view_grid": str(Path(view_grid).resolve()),
            "view_grid_json": str(Path(view_grid_json).resolve()),
            "camera_prompt": str(planning / "camera_selection_prompt.txt"),
        },
        "write": {"camera_plan": str(camera_target)},
        "next_command_argv": arguments,
        "notes": [
            "Select a labeled deterministic view after inspecting the grid and any camera/composition references.",
            "The user does not need to author the camera plan; the host writes it.",
        ],
    }
    _write_json(planning / "host_handoff.json", payload)
    markdown = [
        "# Host handoff: camera selection",
        "",
        f"1. Inspect `{payload['inspect']['view_grid']}` and attached camera/composition references.",
        f"2. Write the selected camera plan to `{camera_target}`.",
        "3. Resume preparation using the argument array in `host_handoff.json`.",
        "",
        "Do not ask the user to write JSON unless multiple camera choices remain genuinely ambiguous.",
        "",
    ]
    (planning / "NEXT_STEPS.md").write_text("\n".join(markdown), encoding="utf-8")
    return payload


def write_generation_handoff(
    run_dir: str | Path,
    *,
    launcher: str | Path,
    imagegen_request: Mapping[str, Any],
) -> dict[str, Any]:
    root = Path(run_dir).expanduser().resolve()
    planning = root / "planning"
    candidate_ids = [str(item) for item in imagegen_request.get("candidate_ids", [])]
    if not candidate_ids:
        count = int(imagegen_request.get("candidate_count", 4))
        candidate_ids = [f"C{index:02d}" for index in range(1, count + 1)]
    candidate_args: list[str] = []
    for candidate_id in candidate_ids:
        candidate_args.extend(["--candidate", f"{candidate_id}=<generated-image-{candidate_id}>"])

    stage_argv = [
        "python",
        str(Path(launcher).resolve()),
        "stage",
        "--run",
        str(root),
        *candidate_args,
    ]
    finalize_argv = [
        "python",
        str(Path(launcher).resolve()),
        "finalize",
        "--run",
        str(root),
        "--visual-qa",
        str(planning / "visual_qa.host.json"),
    ]
    _write_json(
        planning / "visual_qa.template.json",
        {
            "best_candidate_id": None,
            "retry_recommended": False,
            "decision_summary": "",
            "candidates": [
                {
                    "candidate_id": candidate_id,
                    "geometry_score": None,
                    "overall_score": None,
                    "material_score": None,
                    "lighting_score": None,
                    "camera_match": None,
                    "issues": [],
                }
                for candidate_id in candidate_ids
            ],
        },
    )
    payload = {
        "contract_version": "3.0",
        "stage": "host_image_generation",
        "status": "prepared_for_image_generation",
        "run_dir": str(root),
        "image_generation": {
            "host_skill": imagegen_request.get("host_skill", "imagegen"),
            "target_resolution": imagegen_request.get("target_resolution", "4k"),
            "requested_native_size": imagegen_request.get("requested_native_size", "auto"),
            "quality": imagegen_request.get("quality", "high"),
            "detail_level": imagegen_request.get("detail_level", "high"),
            "resolution_policy": imagegen_request.get("resolution_policy", "Use the highest supported host resolution and record actual dimensions."),
            "request": str(planning / "imagegen_request.json"),
            "prompt": str(planning / "final_prompt.txt"),
            "input_roles": str(planning / "input_roles.json"),
            "ordered_input_images": list(imagegen_request.get("input_images", [])),
            "candidate_ids": candidate_ids,
            "tool_parameters": dict(imagegen_request.get("tool_parameters", {})),
            "exact_final_output": dict(imagegen_request.get("exact_final_output", {})),
            "render_contract": imagegen_request.get("render_contract_path"),
            "contract_id": imagegen_request.get("contract_id"),
            "contract_revision": imagegen_request.get("contract_revision"),
        },
        "candidate_staging": {
            "command_argv_template": stage_argv,
            "contact_sheet": str(root / "candidates" / "contact_sheet.png"),
            "qa_prompt": str(planning / "qa_prompt.txt"),
            "visual_qa_template": str(planning / "visual_qa.template.json"),
        },
        "finalization": {
            "command_argv_template": finalize_argv,
            "visual_qa_target": str(planning / "visual_qa.host.json"),
            "selection": str(root / "final" / "selection.json"),
            "final_refine_request": str(planning / "final_refine_request.json"),
            "report": str(root / "final" / "report.md"),
        },
        "notes": [
            "Use the official Codex imagegen Skill by default; do not call a raw image API.",
            "Treat planning/render_contract.json as authoritative. Do not rewrite size, aspect, count, camera, or input order from chat context.",
            "Pass every supported field in tool_parameters as a real host-tool argument and record actual native dimensions.",
            "Pass the image generator's returned file paths directly to the stage command; do not pre-copy them.",
            "The stage command stores stable candidate copies and never selects a final image. Inspect all candidates at full resolution and write host visual QA before finalization.",
            "Candidate finalization selects a source and writes final_refine_request.json; it does not create final/best.*.",
            "Generate exactly one final master from the refine request, stage it, perform final QC, and then run finish.",
            "Do not manually rewrite report.md; finalization rebuilds it idempotently from structured artifacts.",
        ],
    }
    _write_json(planning / "host_handoff.json", payload)
    markdown = [
        "# Host handoff: generate, stage, review, finalize",
        "",
        f"1. Invoke the official image-generation capability using `{planning / 'imagegen_request.json'}`.",
        f"2. Generate {len(candidate_ids)} independent candidates with IDs {', '.join(candidate_ids)}.",
        "3. Pass the returned image paths directly to the `stage` argument array in `host_handoff.json`; no manual copy is needed.",
        f"4. Inspect `{root / 'candidates' / 'contact_sheet.png'}` and every candidate at full resolution.",
        f"5. Write visual QA to `{planning / 'visual_qa.host.json'}` using `{planning / 'visual_qa.template.json'}`.",
        "6. Run the candidate-finalization argument array. It selects the best source and writes `final_refine_request.json`.",
        "7. Generate exactly one final master, run `refine-stage`, inspect final QC, then run `finish` to create `final/best.*`.",
        "",
        "The local geometry score is diagnostic and must not be treated as the final visual choice.",
        "",
    ]
    (planning / "NEXT_STEPS.md").write_text("\n".join(markdown), encoding="utf-8")
    return payload


def write_multi_generation_handoff(
    run_dir: str | Path,
    *,
    launcher: str | Path,
    view_bundles: Sequence[Mapping[str, Any]],
    candidate_count: int,
    host_skill: str = "imagegen",
    target_resolution: str = "4k",
    quality: str = "high",
    detail_level: str = "high",
) -> dict[str, Any]:
    """Write one aggregate handoff for independent multi-view generation bundles."""
    root = Path(run_dir).expanduser().resolve()
    planning = root / "planning"
    launcher_path = str(Path(launcher).resolve())
    views: list[dict[str, Any]] = []
    for bundle in view_bundles:
        view_root = Path(str(bundle["root"])).expanduser().resolve()
        view_planning = view_root / "planning"
        candidate_ids = [str(item) for item in bundle.get("candidate_ids", [])]
        if not candidate_ids:
            candidate_ids = [f"C{index:02d}" for index in range(1, candidate_count + 1)]
        candidate_args: list[str] = []
        for candidate_id in candidate_ids:
            candidate_args.extend(["--candidate", f"{candidate_id}=<generated-image-{candidate_id}>"])
        views.append(
            {
                "view_id": bundle.get("view_id"),
                "view_label": bundle.get("view_label"),
                "view_type": bundle.get("view_type"),
                "run_dir": str(view_root),
                "request": str(view_planning / "imagegen_request.json"),
                "prompt": str(view_planning / "final_prompt.txt"),
                "input_roles": str(view_planning / "input_roles.json"),
                "render_contract": str(view_planning / "render_contract.json"),
                "candidate_ids": candidate_ids,
                "candidate_staging": {
                    "command_argv_template": [
                        "python",
                        launcher_path,
                        "stage",
                        "--run",
                        str(view_root),
                        *candidate_args,
                    ],
                    "contact_sheet": str(view_root / "candidates" / "contact_sheet.png"),
                    "qa_prompt": str(view_planning / "qa_prompt.txt"),
                    "visual_qa_template": str(view_planning / "visual_qa.template.json"),
                },
                "finalization": {
                    "command_argv_template": [
                        "python",
                        launcher_path,
                        "finalize",
                        "--run",
                        str(view_root),
                        "--visual-qa",
                        str(view_planning / "visual_qa.host.json"),
                    ],
                    "selection": str(view_root / "final" / "selection.json"),
                    "final_refine_request": str(view_planning / "final_refine_request.json"),
                    "best_image_after_refinement": str(view_root / "final" / "best.png"),
                    "report": str(view_root / "final" / "report.md"),
                },
            }
        )
    candidate_counts = {
        str(view.get("view_id")): len(view.get("candidate_ids", []))
        for view in views
    }
    unique_counts = set(candidate_counts.values())
    payload = {
        "contract_version": "3.0",
        "stage": "host_image_generation_multi_view",
        "status": "prepared_for_image_generation",
        "run_dir": str(root),
        "view_count": len(views),
        "candidate_count_per_view": next(iter(unique_counts)) if len(unique_counts) == 1 else None,
        "candidate_counts": candidate_counts,
        "total_candidate_count": sum(candidate_counts.values()),
        "host_skill": host_skill,
        "target_resolution": target_resolution,
        "quality": quality,
        "detail_level": detail_level,
        "resolution_policy": "Use each frozen output contract for native-size requests and exact final delivery; record native, resampled, and upscaled states separately.",
        "views": views,
        "notes": [
            "Use the official Codex imagegen Skill by default; do not call a raw image API.",
            "Read each view's render_contract.json; do not reinterpret its tool parameters or frozen fields.",
            "Generate each view independently; never average, collage, or morph different camera directions into one candidate.",
            "Reference-view coverage and final candidate budget are separate: only the listed view bundles generate final images.",
            "Each view has its own contract, candidate QA, final-refinement request, resolution gate, final QC, and final/best.png output.",
            "Stage and select candidates independently, then generate exactly one final master per view and pass final QC.",
        ],
    }
    _write_json(planning / "host_handoff.json", payload)
    markdown = [
        "# Host handoff: independent multi-view generation",
        "",
        f"Generate and review {len(views)} independent CAD-anchored view bundles.",
        "",
        "Do not combine view directions into a collage or use one view's beauty image as geometry evidence for another view.",
        "",
    ]
    for index, view in enumerate(views, start=1):
        markdown.extend(
            [
                f"{index}. **{view.get('view_label') or view.get('view_id')}** (`{view.get('view_id')}`): invoke `{view['request']}`, then use its stage and finalize argument arrays.",
                f"   Candidate selection writes `{view['finalization']['final_refine_request']}`; final output follows refinement and QC.",
            ]
        )
    markdown.extend(
        [
            "",
            "The aggregate `imagegen_request.json` lists every view. The local geometry score is diagnostic and must not replace host visual QA.",
            "",
        ]
    )
    (planning / "NEXT_STEPS.md").write_text("\n".join(markdown), encoding="utf-8")
    return payload


def write_final_refinement_handoff(
    run_dir: str | Path,
    *,
    launcher: str | Path,
    refine_request: Mapping[str, Any],
) -> dict[str, Any]:
    """Replace the candidate handoff with the frozen final-refinement handoff."""
    root = Path(run_dir).expanduser().resolve()
    planning = root / "planning"
    launcher_path = str(Path(launcher).resolve())
    payload = {
        "contract_version": "3.0",
        "stage": "final_refinement",
        "status": "awaiting_final_refinement",
        "run_dir": str(root),
        "render_contract": refine_request.get("contract_path"),
        "contract_id": refine_request.get("contract_id"),
        "contract_revision": refine_request.get("contract_revision"),
        "image_generation": {
            "request": str(planning / "final_refine_request.json"),
            "prompt": str(planning / "final_refine_prompt.txt"),
            "candidate_id": "F01",
            "ordered_input_images": list(refine_request.get("input_images", [])),
            "input_roles": list(refine_request.get("input_roles", [])),
            "tool_parameters": dict(refine_request.get("tool_parameters", {})),
            "exact_final_output": dict(refine_request.get("exact_final_output", {})),
        },
        "refine_staging": {
            "command_argv_template": [
                "python",
                launcher_path,
                "refine-stage",
                "--run",
                str(root),
                "--master",
                "F01=<generated-final-master>",
            ],
            "resolution_report": str(root / "final_refinement" / "resolution_report.json"),
            "final_qc_template": str(planning / "final_qc.template.json"),
        },
        "finish": {
            "command_argv_template": [
                "python",
                launcher_path,
                "finish",
                "--run",
                str(root),
                "--final-qa",
                str(planning / "final_qc.host.json"),
            ],
            "best_image": str(root / "final" / "best.png"),
            "resolution_report": str(root / "final" / "resolution_report.json"),
            "final_qc": str(root / "final" / "final_qc.json"),
            "report": str(root / "final" / "report.md"),
        },
        "notes": [
            "Generate exactly one final master; do not redesign the scene or camera.",
            "The selected candidate and high-resolution CAD anchors are all mandatory ordered inputs.",
            "Stage the returned master before final QC. Only finish may create final/best.*.",
            "An exact-size upscale is reported as upscaled, never as native resolution.",
        ],
    }
    _write_json(planning / "host_handoff.json", payload)
    markdown = [
        "# Host handoff: frozen final refinement",
        "",
        f"1. Read `{planning / 'render_contract.json'}` and `{planning / 'final_refine_request.json'}`.",
        "2. Generate exactly one final master with ID `F01`; keep every frozen field unchanged.",
        "3. Pass the returned path to the `refine-stage` argument array in `host_handoff.json`.",
        f"4. Inspect the master, high-resolution CAD anchors, and `{root / 'final_refinement' / 'resolution_report.json'}`.",
        f"5. Write `{planning / 'final_qc.host.json'}` from the template, then run `finish`.",
        "",
        "Only the finish stage can create `final/best.*`; it records native, resampled, and upscaled states separately.",
        "",
    ]
    (planning / "NEXT_STEPS.md").write_text("\n".join(markdown), encoding="utf-8")
    return payload
