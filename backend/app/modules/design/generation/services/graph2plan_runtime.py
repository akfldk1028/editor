"""Run the local Graph2Plan reference model in an isolated Python process."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

from backend.app.modules.design.generation import paths


MODEL_FILES = ("model.pth", "model.py", "box_utils.py", "graph.py", "layout.py", "layers.py", "utils.py")


def model_directory() -> Path:
    configured = os.environ.get("EDITOR_GRAPH2PLAN_MODEL_DIR", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return paths.editor_root() / "runtime/editor/design/reference-models/graph2plan"


def install_model(source: Path, destination: Path | None = None) -> dict:
    """Copy the exact inference closure without replacing existing local edits."""
    source = source.resolve()
    source = source / "model" if (source / "model").is_dir() else source
    destination = (destination or model_directory()).resolve()
    files = []
    for filename in MODEL_FILES:
        original = source / filename
        data = original.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        target = destination / "model" / filename
        if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            raise ValueError(f"Preserving modified model file: {target}")
        files.append((filename, data, digest))
    (destination / "model").mkdir(parents=True, exist_ok=True)
    for filename, data, _ in files:
        (destination / "model" / filename).write_bytes(data)
    manifest = {"schema": "editor.graph2plan-local-model.v1", "source": str(source),
                "files": [{"file": filename, "bytes": len(data), "sha256": digest} for filename, data, digest in files]}
    (destination / "installation.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return {"directory": str(destination), **manifest}


def infer(footprint, rooms, options) -> dict:
    directory = model_directory()
    if not (directory / "model/model.pth").is_file():
        raise FileNotFoundError(f"Graph2Plan model not found at {directory / 'model/model.pth'}")
    from shapely.geometry import mapping
    env = dict(os.environ, EDITOR_GRAPH2PLAN_MODEL_DIR=str(directory),
               EDITOR_GRAPH2PLAN_WORKER="1", PYTHONDONTWRITEBYTECODE="1",
               PYTHONIOENCODING="utf-8", PYTHONPATH=os.pathsep.join((str(paths.editor_root()), str(directory))))
    completed = subprocess.run(
        [sys.executable, "-m", __name__, "--worker"],
        input=json.dumps({"footprint": mapping(footprint), "rooms": rooms, "options": options}),
        text=True, encoding="utf-8", capture_output=True, env=env, cwd=paths.editor_root(),
        timeout=float(os.environ.get("EDITOR_GRAPH2PLAN_TIMEOUT_SECONDS", "120")),
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    if completed.returncode:
        raise RuntimeError(f"Graph2Plan worker failed: {completed.stderr[-2000:]}")
    try:
        result = json.loads(completed.stdout)
    except ValueError as exc:
        raise RuntimeError("Graph2Plan worker returned an invalid result") from exc
    if not isinstance(result, dict):
        raise RuntimeError("Graph2Plan worker returned a non-object result")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install", type=Path)
    parser.add_argument("--destination", type=Path)
    parser.add_argument("--worker", action="store_true")
    arguments = parser.parse_args()
    if arguments.install:
        print(json.dumps(install_model(arguments.install, arguments.destination)))
        return
    if not arguments.worker or os.environ.get("EDITOR_GRAPH2PLAN_WORKER") != "1":
        parser.error("Choose --install, or invoke the private worker through infer()")
    import torch
    torch.set_num_threads(max(1, int(os.environ.get("EDITOR_GRAPH2PLAN_THREADS", "2"))))
    from shapely.geometry import shape
    from backend.app.modules.design.generation.services.floor_graph2plan import generate_graph2plan
    body = json.load(sys.stdin)
    result = generate_graph2plan(shape(body["footprint"]), body["rooms"], body.get("options"))
    print(json.dumps(result, ensure_ascii=True, allow_nan=False))


if __name__ == "__main__":
    main()
