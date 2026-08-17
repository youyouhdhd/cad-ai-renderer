#!/usr/bin/env python3
"""Generic ComfyUI local API runner for optional depth/canny geometry guards."""

from __future__ import annotations

import argparse
import json
import mimetypes
import time
import uuid
from pathlib import Path
from typing import Any, Mapping

import requests


class ComfyUIError(RuntimeError):
    pass


def _replace_placeholders(value: Any, replacements: Mapping[str, Any]) -> Any:
    if isinstance(value, dict):
        return {key: _replace_placeholders(item, replacements) for key, item in value.items()}
    if isinstance(value, list):
        return [_replace_placeholders(item, replacements) for item in value]
    if isinstance(value, str):
        if value in replacements:
            return replacements[value]
        out = value
        for token, replacement in replacements.items():
            if isinstance(replacement, (str, int, float)):
                out = out.replace(token, str(replacement))
        return out
    return value


class ComfyUIClient:
    def __init__(self, server_url: str = "http://127.0.0.1:8188", timeout_seconds: int = 900) -> None:
        self.server_url = server_url.rstrip("/")
        self.timeout_seconds = int(timeout_seconds)
        self.session = requests.Session()

    def upload_image(self, path: str | Path, overwrite: bool = True) -> str:
        image_path = Path(path)
        if not image_path.exists():
            raise FileNotFoundError(image_path)
        mime = mimetypes.guess_type(image_path.name)[0] or "image/png"
        with image_path.open("rb") as handle:
            response = self.session.post(
                f"{self.server_url}/upload/image",
                files={"image": (image_path.name, handle, mime)},
                data={"overwrite": "true" if overwrite else "false", "type": "input"},
                timeout=120,
            )
        if response.status_code >= 400:
            raise ComfyUIError(f"ComfyUI upload failed: HTTP {response.status_code} {response.text[:1000]}")
        body = response.json()
        name = body.get("name")
        subfolder = body.get("subfolder")
        if not name:
            raise ComfyUIError(f"ComfyUI upload returned no filename: {body}")
        return f"{subfolder}/{name}" if subfolder else name

    def queue_prompt(self, workflow: Mapping[str, Any], client_id: str | None = None) -> str:
        identifier = client_id or str(uuid.uuid4())
        response = self.session.post(
            f"{self.server_url}/prompt",
            json={"prompt": workflow, "client_id": identifier},
            timeout=120,
        )
        if response.status_code >= 400:
            raise ComfyUIError(f"ComfyUI queue failed: HTTP {response.status_code} {response.text[:2000]}")
        body = response.json()
        prompt_id = body.get("prompt_id")
        if not prompt_id:
            raise ComfyUIError(f"ComfyUI returned no prompt_id: {body}")
        return str(prompt_id)

    def wait_for_history(self, prompt_id: str, poll_seconds: float = 1.0) -> dict[str, Any]:
        deadline = time.time() + self.timeout_seconds
        while time.time() < deadline:
            response = self.session.get(f"{self.server_url}/history/{prompt_id}", timeout=60)
            if response.status_code >= 400:
                raise ComfyUIError(f"ComfyUI history failed: HTTP {response.status_code}")
            body = response.json()
            if prompt_id in body:
                item = body[prompt_id]
                status = item.get("status", {})
                if status.get("status_str") == "error":
                    raise ComfyUIError(f"ComfyUI workflow failed: {json.dumps(status)}")
                if item.get("outputs"):
                    return item
            time.sleep(poll_seconds)
        raise ComfyUIError(f"Timed out waiting for ComfyUI prompt {prompt_id}")

    def download_outputs(self, history_item: Mapping[str, Any], output_dir: str | Path) -> list[Path]:
        output = Path(output_dir)
        output.mkdir(parents=True, exist_ok=True)
        downloaded: list[Path] = []
        for node_id, node_output in (history_item.get("outputs", {}) or {}).items():
            for image in node_output.get("images", []) or []:
                params = {
                    "filename": image.get("filename"),
                    "subfolder": image.get("subfolder", ""),
                    "type": image.get("type", "output"),
                }
                response = self.session.get(f"{self.server_url}/view", params=params, timeout=120)
                if response.status_code >= 400:
                    raise ComfyUIError(f"ComfyUI output download failed: HTTP {response.status_code}")
                filename = Path(str(params["filename"])).name
                path = output / f"node_{node_id}_{filename}"
                path.write_bytes(response.content)
                downloaded.append(path)
        return downloaded

    def run(
        self,
        workflow_path: str | Path,
        output_dir: str | Path,
        replacements: Mapping[str, Any] | None = None,
    ) -> tuple[list[Path], dict[str, Any]]:
        raw = json.loads(Path(workflow_path).read_text(encoding="utf-8"))
        workflow = raw.get("prompt", raw)
        if not isinstance(workflow, dict):
            raise ComfyUIError("Workflow must be API-format JSON object")
        prepared = _replace_placeholders(workflow, replacements or {})
        prompt_id = self.queue_prompt(prepared)
        history = self.wait_for_history(prompt_id)
        paths = self.download_outputs(history, output_dir)
        metadata = {"prompt_id": prompt_id, "outputs": [str(path) for path in paths]}
        return paths, metadata


def run_geometry_guard(
    server_url: str,
    workflow_path: str | Path,
    output_dir: str | Path,
    lineart_path: str | Path,
    depth_path: str | Path,
    color_preview_path: str | Path,
    prompt: str,
    timeout_seconds: int = 900,
) -> tuple[list[Path], dict[str, Any]]:
    client = ComfyUIClient(server_url, timeout_seconds=timeout_seconds)
    replacements = {
        "__LINEART_IMAGE__": client.upload_image(lineart_path),
        "__DEPTH_IMAGE__": client.upload_image(depth_path),
        "__COLOR_PREVIEW_IMAGE__": client.upload_image(color_preview_path),
        "__PROMPT__": prompt,
        "__OUTPUT_PREFIX__": "cad_ai_geometry_guard",
    }
    return client.run(workflow_path, output_dir, replacements=replacements)


def _parse_replacement(text: str) -> tuple[str, Any]:
    if "=" not in text:
        raise argparse.ArgumentTypeError("Replacement must use TOKEN=VALUE")
    key, value = text.split("=", 1)
    try:
        parsed: Any = json.loads(value)
    except json.JSONDecodeError:
        parsed = value
    return key, parsed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workflow")
    parser.add_argument("output_dir")
    parser.add_argument("--server-url", default="http://127.0.0.1:8188")
    parser.add_argument("--replace", action="append", default=[], type=_parse_replacement)
    args = parser.parse_args()
    client = ComfyUIClient(args.server_url)
    paths, metadata = client.run(args.workflow, args.output_dir, dict(args.replace))
    print(json.dumps({"paths": [str(path) for path in paths], "metadata": metadata}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
