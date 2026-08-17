#!/usr/bin/env python3
"""FreeCADCmd helper: export a STEP file to one STL for fallback conversion."""

from __future__ import annotations

import sys


def main() -> int:
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1 :]
    else:
        argv = argv[1:]
    if len(argv) != 2:
        print("Usage: FreeCADCmd freecad_step_export.py -- input.step output.stl", file=sys.stderr)
        return 2
    source, destination = argv
    try:
        import FreeCAD  # type: ignore
        import Import  # type: ignore
        import Mesh  # type: ignore
    except Exception as exc:
        print(f"FreeCAD Python modules unavailable: {exc}", file=sys.stderr)
        return 3
    document = FreeCAD.newDocument("cad_ai_renderer")
    Import.insert(source, document.Name)
    document.recompute()
    shapes = [obj for obj in document.Objects if hasattr(obj, "Shape") and not obj.Shape.isNull()]
    if not shapes:
        print("No exportable shapes found", file=sys.stderr)
        return 4
    Mesh.export(shapes, destination)
    print(destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
