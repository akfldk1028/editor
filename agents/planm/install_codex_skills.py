from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path


CONTRACT_VERSION = "planm-skill-install/v1"


def _tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _read_manifest(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if data.get("contract_version") == CONTRACT_VERSION else {}


def _remove_managed_target(target: Path) -> None:
    if target.is_symlink():
        target.unlink()
    elif target.is_dir():
        shutil.rmtree(target)
    elif target.exists():
        target.unlink()


def install(codex_home: Path, mode: str = "link") -> Path:
    if mode not in {"link", "copy"}:
        raise ValueError("mode must be 'link' or 'copy'")

    source_root = Path(__file__).resolve().parent / "skills"
    target_root = codex_home.expanduser().resolve() / "skills"
    manifest_path = codex_home.expanduser().resolve() / "planm-skills-install.json"
    previous = _read_manifest(manifest_path).get("skills", {})
    sources = sorted(path for path in source_root.iterdir() if (path / "SKILL.md").is_file())

    target_root.mkdir(parents=True, exist_ok=True)
    for source in sources:
        target = target_root / source.name
        if target.exists() or target.is_symlink():
            managed = previous.get(source.name)
            managed_target = (
                Path(managed.get("target", "")).resolve() if managed else None
            )
            if not managed or managed_target != target.resolve():
                raise FileExistsError(f"refusing to replace unmanaged skill: {target}")

    records: dict[str, dict[str, str]] = {}
    for source in sources:
        target = target_root / source.name
        if target.exists() or target.is_symlink():
            _remove_managed_target(target)
        if mode == "link":
            target.symlink_to(source.resolve(), target_is_directory=True)
        else:
            shutil.copytree(source, target)
        records[source.name] = {
            "source": str(source.resolve()),
            "target": str(target),
            "mode": mode,
            "sha256": _tree_hash(source),
        }

    manifest = {"contract_version": CONTRACT_VERSION, "skills": records}
    temporary = manifest_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(manifest_path)
    return manifest_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Install PLANM Skills into Codex")
    parser.add_argument("--codex-home", type=Path, default=Path.home() / ".codex")
    parser.add_argument("--mode", choices=("link", "copy"), default="link")
    args = parser.parse_args()
    print(install(args.codex_home, args.mode))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
