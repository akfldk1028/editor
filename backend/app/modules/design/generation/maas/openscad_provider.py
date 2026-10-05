"""OpenSCAD CLI wrapper adapted from the MAAS provider."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


def find_openscad() -> str:
    """Return an OpenSCAD executable path or raise FileNotFoundError."""
    env = os.environ.get("OPENSCAD_BIN")
    if env and Path(env).exists():
        return env

    found = shutil.which("openscad")
    if found:
        return found

    candidates = [
        r"C:\Program Files\OpenSCAD\openscad.exe",
        r"C:\Program Files (x86)\OpenSCAD\openscad.exe",
        os.path.expanduser(r"~\AppData\Local\Programs\OpenSCAD\openscad.exe"),
    ]
    for candidate in candidates:
        if Path(candidate).exists():
            return candidate

    raise FileNotFoundError(
        "OpenSCAD executable not found. Install OpenSCAD or set OPENSCAD_BIN."
    )


def render_scad(
    scad_path: str | Path,
    out_path: str | Path,
    *,
    image_size: tuple[int, int] = (800, 600),
    camera: tuple[float, ...] | None = None,
    timeout: int = 120,
) -> Path:
    """Render .scad to .stl/.off/.csg/.png with OpenSCAD CLI."""
    scad_path = Path(scad_path).resolve()
    out_path = Path(out_path).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [find_openscad(), "-o", str(out_path)]
    if out_path.suffix.lower() == ".png":
        width, height = image_size
        cmd.extend(["--imgsize", f"{width},{height}"])
        cmd.extend(["--camera", ",".join(str(v) for v in (camera or (3, 3, 3, 0, 0, 0)))])
        cmd.append("--colorscheme=Tomorrow")
    cmd.append(str(scad_path))

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(
            f"OpenSCAD failed with exit {result.returncode}: {result.stderr.strip()}"
        )
    if not out_path.exists():
        raise RuntimeError(f"OpenSCAD completed but did not create {out_path}")
    return out_path


__all__ = ["find_openscad", "render_scad"]
