#!/usr/bin/env python3
"""Stage, score, and select image-generation candidates locally.

The first pass deliberately stops at ``awaiting_visual_qa``. Local edge and
silhouette metrics are diagnostics, not an aesthetic or topology authority.
Candidate selection writes a frozen final-refinement request. It never copies a
candidate directly to ``final/best.*``; final delivery is owned by the separate
refine-stage and finish commands.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml
from PIL import Image

from geometry_metrics import score_candidate
from host_handoff import write_final_refinement_handoff
from image_utils import make_contact_sheet
from pipeline_prompts import qa_prompt
from render_contract import build_final_refine_request, load_and_validate_render_contract
from runtime_layout import manifest_paths, output_layout, resolve_auxiliary_dir

ID_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,31}$")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _parse_candidate_specs(items: Sequence[str] | None) -> list[tuple[str, Path]]:
    parsed: list[tuple[str, Path]] = []
    auto_index = 1
    seen: set[str] = set()
    for item in items or ():
        candidate_id: str
        raw_path: str
        if "=" in item:
            maybe_id, maybe_path = item.split("=", 1)
            if ID_PATTERN.match(maybe_id):
                candidate_id, raw_path = maybe_id, maybe_path
            else:
                candidate_id, raw_path = f"C{auto_index:02d}", item
                auto_index += 1
        else:
            candidate_id, raw_path = f"C{auto_index:02d}", item
            auto_index += 1
        if candidate_id in seen:
            raise ValueError(f"Duplicate candidate ID: {candidate_id}")
        path = Path(raw_path).expanduser().resolve()
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(path)
        seen.add(candidate_id)
        parsed.append((candidate_id, path))
    return parsed


def _discover_staged_candidates(image_dir: Path) -> list[tuple[str, Path]]:
    """Return candidates already copied by the stage command.

    Finalization normally runs after staging, so the host should not have to
    repeat transient image-generator paths. Detect the stable copies by their
    candidate IDs and reject ambiguous duplicate stems.
    """

    allowed_suffixes = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
    by_id: dict[str, Path] = {}
    if image_dir.exists():
        for path in sorted(image_dir.iterdir(), key=lambda item: item.name.lower()):
            if not path.is_file() or path.suffix.lower() not in allowed_suffixes:
                continue
            candidate_id = path.stem
            if not ID_PATTERN.match(candidate_id):
                continue
            if candidate_id in by_id:
                raise ValueError(f"Multiple staged files use candidate ID {candidate_id!r}")
            by_id[candidate_id] = path.resolve()
    return sorted(by_id.items(), key=lambda item: item[0].lower())


def _candidate_resolution_report(
    stored: Sequence[tuple[str, Path]],
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    requested_native = str(contract.get("generation", {}).get("requested_native_size", "auto"))
    records: list[dict[str, Any]] = []
    for candidate_id, path in stored:
        with Image.open(path) as image:
            width, height = image.size
        native_match = requested_native != "auto" and requested_native.lower() == f"{width}x{height}"
        records.append(
            {
                "candidate_id": candidate_id,
                "path": str(path),
                "actual_native_size": {"width": width, "height": height},
                "source_megapixels": round(width * height / 1_000_000, 4),
                "requested_native_size": requested_native,
                "requested_native_size_met": native_match if requested_native != "auto" else None,
            }
        )
    return {
        "schema_version": "1.0",
        "stage": "candidate_generation",
        "contract_id": contract.get("contract_id"),
        "contract_revision": contract.get("contract_revision"),
        "requested_native_size": requested_native,
        "requested_final_size": {
            "width": int(contract["final_output"]["width"]),
            "height": int(contract["final_output"]["height"]),
        },
        "candidates": records,
    }


def _load_project_settings(run_dir: Path) -> dict[str, Any]:
    path = run_dir / "resolved_project.yaml"
    if not path.exists():
        return {
            "description": "",
            "min_geometry_score": 75.0,
            "local_weight": 0.35,
            "visual_weight": 0.65,
            "max_edge_distance_px": 18.0,
        }
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {
        "description": payload.get("project", {}).get("description", ""),
        "min_geometry_score": float(payload.get("qa", {}).get("min_geometry_score", 75.0)),
        "local_weight": float(payload.get("qa", {}).get("local_weight", 0.35)),
        "visual_weight": float(payload.get("qa", {}).get("visual_weight", 0.65)),
        "max_edge_distance_px": float(payload.get("qa", {}).get("max_edge_distance_px", 18.0)),
    }


def _load_visual_qa(path: str | Path | None) -> dict[str, Any] | None:
    if not path:
        return None
    qa_path = Path(path).expanduser().resolve()
    payload = json.loads(qa_path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("Visual QA must be a JSON object")
    candidates = payload.get("candidates")
    if not isinstance(candidates, list):
        raise ValueError("Visual QA JSON must contain a candidates list")
    return dict(payload)


def _choose_best(
    records: Sequence[Mapping[str, Any]],
    threshold: float,
    preferred_id: str | None,
    forced_id: str | None,
) -> dict[str, Any]:
    by_id = {str(record["candidate_id"]): record for record in records}
    if forced_id:
        if forced_id not in by_id:
            raise ValueError(f"--best-id {forced_id!r} does not match a candidate")
        selected = dict(by_id[forced_id])
        reason = "explicit host selection override"
    elif preferred_id and preferred_id in by_id and float(by_id[preferred_id]["combined_geometry_score"]) >= threshold:
        selected = dict(by_id[preferred_id])
        reason = "visual review preferred this geometry-passing candidate"
    else:
        passing = [record for record in records if float(record["combined_geometry_score"]) >= threshold]
        if passing:
            selected = dict(max(passing, key=lambda item: float(item["combined_overall_score"])))
            reason = "highest combined overall score among geometry-passing candidates"
        else:
            selected = dict(
                max(
                    records,
                    key=lambda item: (
                        float(item["combined_geometry_score"]),
                        float(item["combined_overall_score"]),
                    ),
                )
            )
            reason = "no candidate passed the geometry threshold; selected the least-drifted candidate"
    selected["selection_reason"] = reason
    selected["geometry_threshold"] = threshold
    selected["geometry_gate_passed"] = float(selected["combined_geometry_score"]) >= threshold
    return selected


def _clear_final_selection(final_dir: Path) -> None:
    for path in final_dir.glob("best.*"):
        if path.is_file():
            path.unlink()
    for name in ("selection.json", "resolution_report.json", "final_qc.json"):
        path = final_dir / name
        if path.exists():
            path.unlink()


def _visual_template(candidate_ids: Sequence[str], local_records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    local_by_id = {str(item["candidate_id"]): item for item in local_records}
    return {
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
                "local_geometry_score_for_context": local_by_id[candidate_id]["geometry_score_local"],
            }
            for candidate_id in candidate_ids
        ],
    }


def _format_optional(value: Any, digits: int = 2) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return str(value)


def _report_text(
    root: Path,
    auxiliary_dir: Path,
    status: str,
    records: Sequence[Mapping[str, Any]],
    best: Mapping[str, Any] | None,
    visual_qa: Mapping[str, Any] | None,
    warnings: Sequence[str],
) -> str:
    model = _read_json(auxiliary_dir / "model_manifest.json")
    camera = _read_json(root / "planning" / "camera_plan.json")
    brief = _read_json(root / "planning" / "render_brief.json")
    manifest = _read_json(root / "run_manifest.json")

    lines = [
        "# CAD AI Renderer Report",
        "",
        "## Run summary",
        "",
        f"- Status: `{status}`",
        f"- Source: `{model.get('source_name', '')}`",
        f"- Converter: `{model.get('converter', '')}`",
        f"- Parts: `{model.get('part_count', '')}`",
        f"- Pipeline version: `{manifest.get('pipeline_version', '')}`",
        f"- Candidates: `{len(records)}`",
        f"- Host visual QA used: `{visual_qa is not None}`",
        "",
        "## Camera",
        "",
        f"- Selected view: `{camera.get('selected_view_id', 'custom/default')}`",
        f"- Azimuth / elevation: `{camera.get('azimuth', '')}` / `{camera.get('elevation', '')}`",
        f"- Projection / FOV: `{camera.get('projection', '')}` / `{camera.get('fov_deg', '')}`",
        f"- Camera source: `{camera.get('source', '')}`",
        "",
        "## Appearance direction",
        "",
        "The following rendering brief is the structured source of truth for material, color, lighting, environment, and assumptions:",
        "",
        "```json",
        json.dumps(brief, indent=2, ensure_ascii=False),
        "```",
        "",
        "## Candidate QA",
        "",
        "| ID | Local geometry | Visual geometry | Visual overall | Combined geometry | Combined overall | QA source |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for record in records:
        lines.append(
            f"| {record['candidate_id']} | {_format_optional(record['local']['geometry_score_local'])} | "
            f"{_format_optional(record.get('visual_geometry_score'))} | "
            f"{_format_optional(record.get('visual_overall_score'))} | "
            f"{_format_optional(record.get('combined_geometry_score'))} | "
            f"{_format_optional(record.get('combined_overall_score'))} | {record.get('qa_source', '')} |"
        )

    lines.extend(["", "## Selection", ""])
    if best is None:
        lines.extend(
            [
                "No final image has been selected. Local diagnostics and the contact sheet are ready; the host must inspect all candidates at full resolution, write visual QA, and then run finalization.",
                "",
            ]
        )
    else:
        lines.extend(
            [
                f"- Best candidate: `{best.get('candidate_id')}`",
                f"- Selected source: `{best.get('path')}`",
                f"- Geometry gate passed: `{best.get('geometry_gate_passed')}`",
                f"- Selection reason: {best.get('selection_reason', '')}",
                f"- Final-refinement request: `{root / 'planning' / 'final_refine_request.json'}`",
                "- Final image: pending one frozen final-refinement generation and final QC.",
                "",
            ]
        )

    if visual_qa:
        lines.extend(
            [
                "## Host visual decision",
                "",
                f"- Preferred candidate: `{visual_qa.get('best_candidate_id')}`",
                f"- Retry recommended: `{visual_qa.get('retry_recommended', False)}`",
                f"- Summary: {visual_qa.get('decision_summary', '')}",
                "",
            ]
        )
    if warnings:
        lines.extend(["## Warnings", "", *[f"- {warning}" for warning in warnings], ""])

    lines.extend(
        [
            "## Output paths",
            "",
            f"- Auxiliary passes: `{auxiliary_dir}`",
            f"- Candidate contact sheet: `{root / 'candidates' / 'contact_sheet.png'}`",
            f"- Candidate scores: `{root / 'candidates' / 'scores.json'}`",
            f"- Candidate resolution report: `{root / 'candidates' / 'candidate_resolution_report.json'}`",
            f"- Visual QA prompt: `{root / 'planning' / 'qa_prompt.txt'}`",
            f"- Final directory: `{root / 'final'}`",
            "",
            "## Geometry note",
            "",
            "The CAD passes are strong visual anchors rather than a pixel-exact reconstruction guarantee. Verify engineering-critical dimensions and topology against the original model.",
            "",
        ]
    )
    return "\n".join(lines)


def _upsert_manifest_step(manifest: dict[str, Any], name: str, status: str) -> None:
    steps = [item for item in manifest.get("steps", []) if isinstance(item, Mapping) and item.get("name") != name]
    steps.append({"name": name, "status": status, "at": _now()})
    manifest["steps"] = steps


def finalize(
    run_dir: str | Path,
    candidate_specs: Sequence[str] | None = None,
    *,
    visual_qa_path: str | Path | None = None,
    best_id: str | None = None,
    min_geometry_score: float | None = None,
    local_weight: float | None = None,
    visual_weight: float | None = None,
    max_edge_distance_px: float | None = None,
    stage_only: bool = False,
    allow_local_selection: bool = False,
) -> dict[str, Any]:
    root = Path(run_dir).expanduser().resolve()
    contract, contract_consistency = load_and_validate_render_contract(root)
    auxiliary_dir = resolve_auxiliary_dir(root, create=False, allow_legacy=True)
    lineart = auxiliary_dir / "lineart.png"
    mask = auxiliary_dir / "mask.png"
    normal = auxiliary_dir / "normal.png"
    preview = auxiliary_dir / "color_preview.png"
    for required in (lineart, mask, normal, preview):
        if not required.exists():
            raise FileNotFoundError(f"Missing prepared CAD anchor: {required}")

    settings = _load_project_settings(root)
    threshold = float(min_geometry_score if min_geometry_score is not None else settings["min_geometry_score"])
    lw = float(local_weight if local_weight is not None else settings["local_weight"])
    vw = float(visual_weight if visual_weight is not None else settings["visual_weight"])
    max_distance = float(
        max_edge_distance_px if max_edge_distance_px is not None else settings["max_edge_distance_px"]
    )
    if abs((lw + vw) - 1.0) > 1e-6:
        raise ValueError("local_weight + visual_weight must equal 1.0")

    layout = output_layout(root, create=False)
    layout["auxiliary"] = auxiliary_dir
    for key in ("root", "planning", "candidates", "final"):
        layout[key].mkdir(parents=True, exist_ok=True)
    candidates_dir = layout["candidates"]
    image_dir = candidates_dir / "images"
    final_dir = layout["final"]
    planning_dir = layout["planning"]
    image_dir.mkdir(parents=True, exist_ok=True)

    parsed = _parse_candidate_specs(candidate_specs)
    if not parsed:
        parsed = _discover_staged_candidates(image_dir)
    if not parsed:
        raise ValueError(
            "No candidates were supplied and no staged candidates were found. "
            "Run the stage command with --candidate first."
        )
    expected_ids = [str(item) for item in contract.get("generation", {}).get("candidate_ids", [])]
    supplied_ids = [candidate_id for candidate_id, _ in parsed]
    if expected_ids and supplied_ids != expected_ids:
        raise ValueError(
            "Candidate IDs/order do not match the frozen render contract: "
            f"expected {expected_ids}, got {supplied_ids}"
        )
    stored: list[tuple[str, Path]] = []
    for candidate_id, source in parsed:
        suffix = source.suffix.lower() or ".png"
        destination = image_dir / f"{candidate_id}{suffix}"
        if source.resolve() != destination.resolve():
            shutil.copy2(source, destination)
        stored.append((candidate_id, destination))
    _write_json(
        candidates_dir / "candidate_resolution_report.json",
        _candidate_resolution_report(stored, contract),
    )

    local_records: list[dict[str, Any]] = []
    for candidate_id, path in stored:
        local = score_candidate(lineart, mask, path, max_edge_distance_px=max_distance)
        local["candidate_id"] = candidate_id
        local_records.append(local)
    _write_json(candidates_dir / "local_scores.json", local_records)

    candidate_ids = [candidate_id for candidate_id, _ in stored]
    (planning_dir / "qa_prompt.txt").write_text(
        qa_prompt(candidate_ids, settings["description"], local_records),
        encoding="utf-8",
    )
    _write_json(planning_dir / "visual_qa.template.json", _visual_template(candidate_ids, local_records))

    visual_qa = _load_visual_qa(visual_qa_path)
    visual_by_id: dict[str, Mapping[str, Any]] = {}
    preferred_id: str | None = None
    warnings: list[str] = []
    if visual_qa:
        visual_by_id = {
            str(item.get("candidate_id")): item
            for item in visual_qa.get("candidates", [])
            if isinstance(item, Mapping) and item.get("candidate_id")
        }
        preferred_id = str(visual_qa.get("best_candidate_id")) if visual_qa.get("best_candidate_id") else None
        _write_json(planning_dir / "visual_qa.json", visual_qa)
        missing = [candidate_id for candidate_id in candidate_ids if candidate_id not in visual_by_id]
        if missing:
            warnings.append("Host visual QA omitted candidates: " + ", ".join(missing))

    records: list[dict[str, Any]] = []
    for (candidate_id, path), local in zip(stored, local_records):
        visual = visual_by_id.get(candidate_id)
        local_geometry = float(local["geometry_score_local"])
        if visual:
            visual_geometry = float(visual.get("geometry_score", local_geometry))
            visual_overall = float(visual.get("overall_score", visual_geometry))
            combined_geometry = lw * local_geometry + vw * visual_geometry
            combined_overall = lw * local_geometry + vw * visual_overall
            qa_source = "local_plus_visual"
        else:
            visual_geometry = None
            visual_overall = None
            combined_geometry = local_geometry
            combined_overall = local_geometry
            qa_source = "local_only"
        records.append(
            {
                "candidate_id": candidate_id,
                "path": str(path),
                "local": local,
                "visual": dict(visual) if visual else None,
                "visual_geometry_score": visual_geometry,
                "visual_overall_score": visual_overall,
                "combined_geometry_score": round(combined_geometry, 3),
                "combined_overall_score": round(combined_overall, 3),
                "qa_source": qa_source,
            }
        )

    labels = [
        f"{record['candidate_id']}  local G {record['local']['geometry_score_local']:.1f}"
        for record in records
    ]
    make_contact_sheet(
        [Path(str(record["path"])) for record in records],
        candidates_dir / "contact_sheet.png",
        labels=labels,
    )
    _write_json(candidates_dir / "scores.json", records)

    should_stage = stage_only or (visual_qa is None and best_id is None and not allow_local_selection)
    best: dict[str, Any] | None = None
    if should_stage:
        status = "awaiting_visual_qa"
        _clear_final_selection(final_dir)
    else:
        _clear_final_selection(final_dir)
        best = _choose_best(records, threshold, preferred_id, best_id)
        best["visual_qa_used"] = visual_qa is not None
        best["contract_id"] = contract.get("contract_id")
        best["contract_revision"] = contract.get("contract_revision")
        best["contract_consistency_pass"] = contract_consistency["contract_consistency_pass"]
        _write_json(final_dir / "selection.json", best)
        refine_request = build_final_refine_request(root, contract, best)
        write_final_refinement_handoff(
            root,
            launcher=Path(__file__).resolve().parent / "run.py",
            refine_request=refine_request,
        )
        if visual_qa is None:
            status = "awaiting_final_refinement_with_local_only_warning"
            warnings.append("Candidate selection used local diagnostics only because --allow-local-selection was explicit.")
        elif bool(best["geometry_gate_passed"]):
            status = "awaiting_final_refinement"
        else:
            status = "awaiting_final_refinement_with_geometry_warning"

    report_path = final_dir / "report.md"
    report_path.write_text(
        _report_text(root, auxiliary_dir, status, records, best, visual_qa, warnings),
        encoding="utf-8",
    )

    manifest_path = root / "run_manifest.json"
    manifest = _read_json(manifest_path)
    manifest.update(
        {
            "status": status,
            "stage": "candidate_visual_qa" if best is None else "final_refinement",
            "candidate_count": len(records),
            "visual_qa_used": visual_qa is not None,
            "best": best,
            "paths": manifest_paths(layout),
            "finished_at": manifest.get("finished_at"),
        }
    )
    _upsert_manifest_step(
        manifest,
        "candidate_staging" if best is None else "candidate_selection",
        "awaiting_host_visual_qa" if best is None else status,
    )
    _write_json(manifest_path, manifest)

    result = {
        "status": status,
        "best": best,
        "records": records,
        "contact_sheet": str(candidates_dir / "contact_sheet.png"),
        "qa_prompt": str(planning_dir / "qa_prompt.txt"),
        "visual_qa_template": str(planning_dir / "visual_qa.template.json"),
        "report": str(report_path),
        "candidate_resolution_report": str(candidates_dir / "candidate_resolution_report.json"),
    }
    if best is None:
        result["next_action"] = (
            "Inspect every candidate and the contact sheet at full resolution, write host visual QA using the template, "
            "then run finalize with --visual-qa."
        )
    else:
        result["final_refine_request"] = str(planning_dir / "final_refine_request.json")
        result["next_action"] = (
            "Invoke the official image-generation capability exactly once with final_refine_request.json, "
            "then run refine-stage, host final QC, and finish."
        )
    return result


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True, help="Prepared output directory")
    parser.add_argument(
        "--candidate",
        action="append",
        help=(
            "Candidate path or ID=path; repeat for generated images. Required for staging; optional during "
            "finalization because staged candidates are reused automatically."
        ),
    )
    parser.add_argument("--stage-only", action="store_true", help="Compute diagnostics but do not create a final image")
    parser.add_argument("--visual-qa", help="Host-generated visual QA JSON")
    parser.add_argument("--best-id", help="Explicit final candidate override")
    parser.add_argument(
        "--allow-local-selection",
        action="store_true",
        help="Explicitly permit a warning-marked final selection without host visual QA",
    )
    parser.add_argument("--min-geometry", type=float)
    parser.add_argument("--local-weight", type=float)
    parser.add_argument("--visual-weight", type=float)
    parser.add_argument("--max-distance", type=float)
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    try:
        result = finalize(
            args.run,
            args.candidate,
            visual_qa_path=args.visual_qa,
            best_id=args.best_id,
            min_geometry_score=args.min_geometry,
            local_weight=args.local_weight,
            visual_weight=args.visual_weight,
            max_edge_distance_px=args.max_distance,
            stage_only=args.stage_only,
            allow_local_selection=args.allow_local_selection,
        )
    except (FileNotFoundError, ValueError, TypeError, OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
