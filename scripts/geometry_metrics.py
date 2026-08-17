#!/usr/bin/env python3
"""Local geometry-drift metrics for AI-rendered candidates."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Sequence

import cv2
import numpy as np
from PIL import Image


def _read_gray(path: str | Path, size: tuple[int, int] | None = None) -> np.ndarray:
    image = Image.open(path).convert("L")
    if size and image.size != size:
        image = image.resize(size, Image.Resampling.LANCZOS)
    return np.asarray(image)


def _read_rgb(path: str | Path, size: tuple[int, int] | None = None) -> np.ndarray:
    image = Image.open(path).convert("RGB")
    if size and image.size != size:
        image = image.resize(size, Image.Resampling.LANCZOS)
    return np.asarray(image)


def _anchor_edges(lineart: np.ndarray, mask: np.ndarray) -> np.ndarray:
    dark = (lineart < 180).astype(np.uint8) * 255
    if np.count_nonzero(dark) < 50:
        dark = cv2.Canny(lineart, 50, 140)
    boundary = cv2.morphologyEx(mask, cv2.MORPH_GRADIENT, np.ones((3, 3), np.uint8))
    return np.maximum(dark, boundary)


def _candidate_edges(rgb: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    gray = cv2.bilateralFilter(gray, 5, 35, 35)
    median = float(np.median(gray))
    low = max(8, int(0.45 * median))
    high = max(low + 8, int(1.2 * median))
    return cv2.Canny(gray, low, min(high, 255))


def _estimate_foreground(rgb: np.ndarray) -> np.ndarray | None:
    height, width = rgb.shape[:2]
    border = max(2, int(round(min(height, width) * 0.035)))
    border_pixels = np.concatenate(
        [
            rgb[:border].reshape(-1, 3),
            rgb[-border:].reshape(-1, 3),
            rgb[:, :border].reshape(-1, 3),
            rgb[:, -border:].reshape(-1, 3),
        ],
        axis=0,
    ).astype(np.float32)
    background = np.median(border_pixels, axis=0)
    distance = np.linalg.norm(rgb.astype(np.float32) - background[None, None, :], axis=2)
    threshold = max(18.0, float(np.percentile(distance, 62)))
    foreground = (distance > threshold).astype(np.uint8)
    foreground = cv2.morphologyEx(foreground, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    foreground = cv2.morphologyEx(foreground, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    count, labels, stats, _ = cv2.connectedComponentsWithStats(foreground, connectivity=8)
    if count <= 1:
        return None
    areas = stats[1:, cv2.CC_STAT_AREA]
    largest = int(np.argmax(areas)) + 1
    component = (labels == largest).astype(np.uint8)
    ratio = float(component.mean())
    if ratio < 0.01 or ratio > 0.92:
        return None
    return component


def _iou(a: np.ndarray, b: np.ndarray) -> float:
    a_bool = a.astype(bool)
    b_bool = b.astype(bool)
    union = np.logical_or(a_bool, b_bool).sum()
    if union == 0:
        return 0.0
    return float(np.logical_and(a_bool, b_bool).sum() / union)


def score_candidate(
    lineart_path: str | Path,
    mask_path: str | Path,
    candidate_path: str | Path,
    max_edge_distance_px: float = 18.0,
) -> dict[str, Any]:
    mask_image = Image.open(mask_path).convert("L")
    size = mask_image.size
    mask = np.asarray(mask_image)
    mask_binary = (mask > 127).astype(np.uint8)
    lineart = _read_gray(lineart_path, size)
    candidate = _read_rgb(candidate_path, size)

    anchor = _anchor_edges(lineart, mask)
    candidate_edge = _candidate_edges(candidate)
    max_distance = max(float(max_edge_distance_px), 1.0)
    dilate_radius = max(3, int(round(max_distance * 1.6)))
    kernel = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE,
        (dilate_radius * 2 + 1, dilate_radius * 2 + 1),
    )
    region = cv2.dilate(mask_binary, kernel, iterations=1).astype(bool)
    candidate_relevant = (candidate_edge > 0) & region
    anchor_bool = anchor > 0

    dist_to_candidate = cv2.distanceTransform((candidate_edge == 0).astype(np.uint8), cv2.DIST_L2, 5)
    dist_to_anchor = cv2.distanceTransform((anchor == 0).astype(np.uint8), cv2.DIST_L2, 5)

    anchor_distances = dist_to_candidate[anchor_bool]
    candidate_distances = dist_to_anchor[candidate_relevant]
    if anchor_distances.size:
        edge_coverage = float(np.mean(anchor_distances <= max_distance))
        anchor_mean_distance = float(np.mean(np.minimum(anchor_distances, max_distance * 2.0)))
    else:
        edge_coverage = 0.0
        anchor_mean_distance = max_distance * 2.0
    if candidate_distances.size:
        edge_precision = float(np.mean(candidate_distances <= max_distance))
        candidate_mean_distance = float(np.mean(np.minimum(candidate_distances, max_distance * 2.0)))
    else:
        edge_precision = 0.0
        candidate_mean_distance = max_distance * 2.0

    distance_quality = 1.0 - min(
        1.0,
        ((anchor_mean_distance + candidate_mean_distance) * 0.5) / max_distance,
    )
    foreground = _estimate_foreground(candidate)
    silhouette_iou = _iou(mask_binary, foreground) if foreground is not None else None
    silhouette_term = silhouette_iou if silhouette_iou is not None else edge_coverage

    score = 100.0 * (
        0.42 * edge_coverage
        + 0.24 * edge_precision
        + 0.16 * distance_quality
        + 0.18 * silhouette_term
    )
    return {
        "candidate": str(Path(candidate_path).resolve()),
        "geometry_score_local": round(float(np.clip(score, 0.0, 100.0)), 3),
        "edge_coverage": round(edge_coverage, 5),
        "edge_precision": round(edge_precision, 5),
        "distance_quality": round(distance_quality, 5),
        "anchor_mean_distance_px": round(anchor_mean_distance, 4),
        "candidate_mean_distance_px": round(candidate_mean_distance, 4),
        "silhouette_iou_estimate": round(silhouette_iou, 5) if silhouette_iou is not None else None,
        "candidate_edge_pixels": int(np.count_nonzero(candidate_relevant)),
        "anchor_edge_pixels": int(np.count_nonzero(anchor_bool)),
        "note": "Local metrics are heuristic and should be blended with the host model's visual review.",
    }


def score_candidates(
    lineart_path: str | Path,
    mask_path: str | Path,
    candidate_paths: Sequence[str | Path],
    max_edge_distance_px: float = 18.0,
) -> list[dict[str, Any]]:
    results = [
        score_candidate(lineart_path, mask_path, path, max_edge_distance_px=max_edge_distance_px)
        for path in candidate_paths
    ]
    return sorted(results, key=lambda item: item["geometry_score_local"], reverse=True)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lineart", required=True)
    parser.add_argument("--mask", required=True)
    parser.add_argument("--candidate", action="append", required=True)
    parser.add_argument("--max-distance", type=float, default=18.0)
    parser.add_argument("--output")
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    results = score_candidates(
        args.lineart,
        args.mask,
        args.candidate,
        max_edge_distance_px=args.max_distance,
    )
    text = json.dumps(results, indent=2)
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
