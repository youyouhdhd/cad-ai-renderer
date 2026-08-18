#!/usr/bin/env python3
"""Stage one frozen final master, run resolution/contract gates, and deliver exact pixels."""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml
from PIL import Image

from geometry_metrics import score_candidate
from render_contract import load_and_validate_render_contract


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _read_json(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError(f"Expected a JSON object: {path}")
    return dict(payload)


def _image_info(path: Path) -> dict[str, Any]:
    with Image.open(path) as image:
        width, height = image.size
        return {
            "path": str(path),
            "width": int(width),
            "height": int(height),
            "megapixels": round(width * height / 1_000_000, 4),
            "format": image.format,
        }


def _parse_master(value: str) -> tuple[str, Path]:
    if "=" in value:
        candidate_id, raw_path = value.split("=", 1)
    else:
        candidate_id, raw_path = "F01", value
    if candidate_id != "F01":
        raise ValueError("Final refinement accepts exactly one master with candidate ID F01")
    path = Path(raw_path).expanduser().resolve()
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"Final master does not exist: {path}")
    return candidate_id, path


def _settings(root: Path) -> dict[str, float]:
    payload = yaml.safe_load((root / "resolved_project.yaml").read_text(encoding="utf-8")) or {}
    qa = payload.get("qa", {})
    return {
        "min_geometry": float(qa.get("min_geometry_score", 75.0)),
        "min_visual": float(qa.get("min_visual_quality_score", 75.0)),
        "local_weight": float(qa.get("local_weight", 0.35)),
        "visual_weight": float(qa.get("visual_weight", 0.65)),
        "max_distance": float(qa.get("max_edge_distance_px", 18.0)),
    }


def _update_manifest(root: Path, *, status: str, stage: str, step_name: str) -> None:
    path = root / "run_manifest.json"
    manifest = _read_json(path)
    steps = [
        item
        for item in manifest.get("steps", [])
        if isinstance(item, Mapping) and item.get("name") != step_name
    ]
    steps.append({"name": step_name, "status": status, "at": _now()})
    manifest.update({"status": status, "stage": stage, "steps": steps})
    if stage == "complete":
        manifest["finished_at"] = _now()
    _write_json(path, manifest)


def _background_color(image: Image.Image) -> tuple[int, int, int]:
    rgb = image.convert("RGB")
    width, height = rgb.size
    corners = [rgb.getpixel((0, 0)), rgb.getpixel((width - 1, 0)), rgb.getpixel((0, height - 1)), rgb.getpixel((width - 1, height - 1))]
    return tuple(int(round(sum(pixel[channel] for pixel in corners) / len(corners))) for channel in range(3))


def _deliver_exact(
    source: Path,
    destination: Path,
    *,
    width: int,
    height: int,
    allow_upscale: bool,
) -> dict[str, Any]:
    with Image.open(source) as opened:
        image = opened.convert("RGB")
        source_width, source_height = image.size
        scale = min(width / source_width, height / source_height)
        upscaled = scale > 1.000001
        if upscaled and not allow_upscale:
            raise ValueError("Final master is smaller than the exact output contract and upscaling is disabled")
        resized_width = max(1, int(round(source_width * scale)))
        resized_height = max(1, int(round(source_height * scale)))
        resampled = (resized_width, resized_height) != (source_width, source_height)
        if resampled:
            image = image.resize((resized_width, resized_height), Image.Resampling.LANCZOS)
        canvas = Image.new("RGB", (width, height), _background_color(opened))
        offset = ((width - resized_width) // 2, (height - resized_height) // 2)
        canvas.paste(image, offset)
        destination.parent.mkdir(parents=True, exist_ok=True)
        save_kwargs = {"quality": 96} if destination.suffix.lower() in {".jpg", ".jpeg"} else {}
        canvas.save(destination, **save_kwargs)
    return {
        "source_width": source_width,
        "source_height": source_height,
        "delivered_width": width,
        "delivered_height": height,
        "scale": round(scale, 6),
        "resampled": resampled or (resized_width, resized_height) != (width, height),
        "upscaled": upscaled,
        "fit_padding": {
            "left": offset[0],
            "top": offset[1],
            "right": width - resized_width - offset[0],
            "bottom": height - resized_height - offset[1],
        },
    }


def stage_final_master(run_dir: str | Path, master_spec: str) -> dict[str, Any]:
    root = Path(run_dir).expanduser().resolve()
    contract, consistency = load_and_validate_render_contract(root)
    selection_path = root / "final" / "selection.json"
    if not selection_path.exists():
        raise FileNotFoundError("Candidate selection is missing; run finalize before final refinement")
    _read_json(selection_path)
    candidate_id, source = _parse_master(master_spec)
    refine_root = root / "final_refinement"
    stable = refine_root / f"master_source{source.suffix.lower() or '.png'}"
    for existing in refine_root.glob("master_source.*"):
        if existing.is_file() and existing.resolve() != source:
            existing.unlink()
    stable.parent.mkdir(parents=True, exist_ok=True)
    if source != stable.resolve():
        shutil.copy2(source, stable)
    source_info = _image_info(stable)
    final_anchor_root = Path(str(contract["anchor_policy"]["final_anchor_root"]))
    local = score_candidate(
        final_anchor_root / "lineart.png",
        final_anchor_root / "mask.png",
        stable,
        max_edge_distance_px=_settings(root)["max_distance"],
    )
    local["candidate_id"] = candidate_id
    output = contract["final_output"]
    report = {
        "schema_version": "1.0",
        "stage": "final_master_native_inspection",
        "contract_id": contract.get("contract_id"),
        "contract_revision": contract.get("contract_revision"),
        "requested_native_size": contract.get("generation", {}).get("requested_native_size", "auto"),
        "actual_native_size": {"width": source_info["width"], "height": source_info["height"]},
        "requested_final_size": {"width": int(output["width"]), "height": int(output["height"])},
        "source_megapixels": source_info["megapixels"],
        "target_met_natively": source_info["width"] == int(output["width"]) and source_info["height"] == int(output["height"]),
        "refinement_used": True,
        "final_anchor_size": dict(contract["anchor_policy"]["final_anchor_resolution"]),
        "contract_consistency_pass": consistency["contract_consistency_pass"],
        "local_geometry_diagnostic": local,
    }
    _write_json(refine_root / "resolution_report.json", report)
    _write_json(
        root / "planning" / "final_qc.template.json",
        {
            "candidate_id": "F01",
            "approve_delivery": False,
            "geometry_score": None,
            "visual_quality_score": None,
            "visual_quality_pass": None,
            "contract_consistency_pass": True,
            "geometry_failures": [],
            "issues": [],
            "strengths": [],
            "decision_summary": "",
            "local_geometry_score_for_context": local["geometry_score_local"],
        },
    )
    _update_manifest(root, status="awaiting_final_qc", stage="final_refinement", step_name="final_master_staging")
    return {
        "status": "awaiting_final_qc",
        "master": str(stable),
        "resolution_report": str(refine_root / "resolution_report.json"),
        "final_qc_template": str(root / "planning" / "final_qc.template.json"),
        "next_action": "Inspect F01 against the final CAD anchors, write final_qc.host.json, then run finish.",
    }


def _final_report(
    *,
    contract: Mapping[str, Any],
    selection: Mapping[str, Any],
    final_qc: Mapping[str, Any],
    resolution: Mapping[str, Any],
    status: str,
) -> str:
    gates = final_qc["gates"]
    lines = [
        "# CAD AI Renderer Final Report",
        "",
        f"- Status: `{status}`",
        f"- Contract: `{contract.get('contract_id')}` revision `{contract.get('contract_revision')}`",
        f"- Selected candidate: `{selection.get('candidate_id')}`",
        f"- Final master: `{resolution.get('final_path')}`",
        "",
        "## Completion gates",
        "",
        f"- Geometry pass: `{gates['geometry_pass']}`",
        f"- Visual quality pass: `{gates['visual_quality_pass']}`",
        f"- Contract consistency pass: `{gates['contract_consistency_pass']}`",
        f"- Native resolution pass: `{gates['resolution_native_pass']}`",
        f"- Exact delivery resolution pass: `{gates['resolution_delivery_pass']}`",
        "",
        "## Resolution",
        "",
        f"- Requested native size: `{resolution['requested_native_size']}`",
        f"- Actual native size: `{resolution['actual_native_size']['width']}x{resolution['actual_native_size']['height']}`",
        f"- Requested final size: `{resolution['requested_final_size']['width']}x{resolution['requested_final_size']['height']}`",
        f"- Delivered final size: `{resolution['delivered_final_size']['width']}x{resolution['delivered_final_size']['height']}`",
        f"- Resampled: `{resolution['resampled']}`",
        f"- Upscaled: `{resolution['upscaled']}`",
        f"- Target met natively: `{resolution['target_met_natively']}`",
        "",
        "## Final QC decision",
        "",
        str(final_qc.get("decision_summary", "")),
        "",
        "The final image is geometry-anchored rather than a pixel-exact CAD reconstruction. Engineering-critical dimensions remain authoritative only in the source CAD.",
        "",
    ]
    return "\n".join(lines)


def finish_final_master(run_dir: str | Path, final_qc_path: str | Path) -> dict[str, Any]:
    root = Path(run_dir).expanduser().resolve()
    contract, consistency = load_and_validate_render_contract(root)
    qc = _read_json(Path(final_qc_path).expanduser().resolve())
    if qc.get("candidate_id") != "F01":
        raise ValueError("Final QC must evaluate candidate F01")
    if qc.get("approve_delivery") is not True:
        raise ValueError("Final QC must explicitly set approve_delivery=true before finish")
    if qc.get("contract_consistency_pass") is not True or not consistency["contract_consistency_pass"]:
        raise ValueError("Final delivery refused because the frozen render contract did not pass consistency QA")
    refine_root = root / "final_refinement"
    masters = sorted(refine_root.glob("master_source.*"))
    if len(masters) != 1:
        raise ValueError("Expected exactly one staged final master")
    source = masters[0]
    source_info = _image_info(source)
    settings = _settings(root)
    pre_report = _read_json(refine_root / "resolution_report.json")
    local_geometry = float(pre_report["local_geometry_diagnostic"]["geometry_score_local"])
    try:
        visual_geometry = float(qc.get("geometry_score", local_geometry))
        visual_score = float(qc.get("visual_quality_score"))
    except (TypeError, ValueError):
        raise ValueError("Final QC requires numeric geometry_score and visual_quality_score") from None
    combined_geometry = settings["local_weight"] * local_geometry + settings["visual_weight"] * visual_geometry
    geometry_pass = combined_geometry >= settings["min_geometry"]
    visual_pass = bool(qc.get("visual_quality_pass", visual_score >= settings["min_visual"]))
    output = contract["final_output"]
    extension = ".jpg" if str(output.get("format", "png")) in {"jpeg", "jpg"} else "." + str(output.get("format", "png"))
    destination = root / "final" / f"best{extension}"
    delivery = _deliver_exact(
        source,
        destination,
        width=int(output["width"]),
        height=int(output["height"]),
        allow_upscale=bool(output.get("allow_upscale", True)),
    )
    delivered_info = _image_info(destination)
    native_pass = source_info["width"] == int(output["width"]) and source_info["height"] == int(output["height"])
    delivery_pass = delivered_info["width"] == int(output["width"]) and delivered_info["height"] == int(output["height"])
    gates = {
        "geometry_pass": geometry_pass,
        "resolution_native_pass": native_pass,
        "resolution_delivery_pass": delivery_pass,
        "visual_quality_pass": visual_pass,
        "contract_consistency_pass": True,
    }
    if geometry_pass and visual_pass and delivery_pass and native_pass:
        status = "complete"
    elif geometry_pass and visual_pass and delivery_pass and delivery["upscaled"]:
        status = "complete_exact_dimensions_upscaled"
    elif geometry_pass and visual_pass and delivery_pass:
        status = "complete_exact_dimensions_resampled"
    elif not geometry_pass:
        status = "complete_with_geometry_warning"
    else:
        status = "complete_with_visual_warning"
    resolution_report = {
        "schema_version": "1.0",
        "requested_native_size": contract.get("generation", {}).get("requested_native_size", "auto"),
        "actual_native_size": {"width": source_info["width"], "height": source_info["height"]},
        "requested_final_size": {"width": int(output["width"]), "height": int(output["height"])},
        "delivered_final_size": {"width": delivered_info["width"], "height": delivered_info["height"]},
        "source_megapixels": source_info["megapixels"],
        "delivered_megapixels": delivered_info["megapixels"],
        "resampled": delivery["resampled"],
        "upscaled": delivery["upscaled"],
        "target_met_natively": native_pass,
        "refinement_used": True,
        "final_anchor_size": dict(contract["anchor_policy"]["final_anchor_resolution"]),
        "fit_padding": delivery["fit_padding"],
        "final_path": str(destination),
    }
    final_qc = {
        **qc,
        "contract_id": contract.get("contract_id"),
        "contract_revision": contract.get("contract_revision"),
        "local_geometry_score": local_geometry,
        "visual_geometry_score": visual_geometry,
        "combined_geometry_score": round(combined_geometry, 3),
        "gates": gates,
        "status": status,
    }
    selection = _read_json(root / "final" / "selection.json")
    _write_json(root / "final" / "resolution_report.json", resolution_report)
    _write_json(root / "final" / "final_qc.json", final_qc)
    (root / "final" / "report.md").write_text(
        _final_report(
            contract=contract,
            selection=selection,
            final_qc=final_qc,
            resolution=resolution_report,
            status=status,
        ),
        encoding="utf-8",
    )
    _update_manifest(root, status=status, stage="complete", step_name="final_resolution_and_qc")
    return {
        "status": status,
        "best": str(destination),
        "resolution_report": str(root / "final" / "resolution_report.json"),
        "final_qc": str(root / "final" / "final_qc.json"),
        "report": str(root / "final" / "report.md"),
        "gates": gates,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True, help="Prepared per-view run directory")
    parser.add_argument("--master", help="F01=path returned by the official final-refinement generation")
    parser.add_argument("--final-qa", help="Host final-QC JSON")
    parser.add_argument("--stage-only", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.stage_only:
            if not args.master:
                raise ValueError("refine-stage requires --master F01=path")
            result = stage_final_master(args.run, args.master)
        else:
            if not args.final_qa:
                raise ValueError("finish requires --final-qa")
            result = finish_final_master(args.run, args.final_qa)
    except (FileNotFoundError, ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}")
        return 2
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
