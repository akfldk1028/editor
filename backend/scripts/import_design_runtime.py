"""Reproduce the namespaced design runtime import from a source checkout.

The manifest records both original bytes and the exact textual transformations.
Locally modified destinations are protected; use a separate output directory to
review a fresh import without overwriting integration changes.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path
import re

EDITOR = Path(__file__).resolve().parents[2]
GEN = "backend.app.modules.design.generation"
STORE = "backend.app.adapters.design_storage"
API = "backend.app.api.design_runtime"
LAND = "backend.app.modules.land.reference"
LAW = "backend.app.modules.law.reference"
SPECIAL = {
    **{f"design.{name}": f"{STORE}.{name}" for name in ("models", "apps", "persistence", "migrations")},
    **{f"design.{name}": f"{API}.{name}" for name in ("views", "urls", "delivered_mass_views", "masterplan_operations_views", "program_floor_plan_views")},
    "graph_db.services.neo4j_service": f"{STORE}.neo4j_service",
}
LAND_MODULES = {
    "land", "land.config", "land.services", "land.data.regulation_prompts",
    *{f"land.services.{name}" for name in (
        "land_api", "law_enricher", "legal_use", "ordinance_evidence", "overlay_resolver",
        "pnu_resolver", "regulation_calculator", "road_frontage", "setback_geometry",
        "zone_geometry", "zoning_mapper", "envelopes", "envelopes.sunlight", "datum",
        "datum.calculator", "datum.cases", "datum.elevation_api",
    )},
}


def mapped(module: str) -> str:
    for old, new in SPECIAL.items():
        if module == old or module.startswith(old + "."):
            return new + module[len(old):]
    for old, new in (("design", GEN), ("land", LAND), ("law", LAW)):
        if module == old or module.startswith(old + "."):
            return new + module[len(old):]
    return module


def module_name(relative: Path) -> str:
    return ".".join(relative.with_suffix("").parts).removesuffix(".__init__")


def destination(relative: Path) -> Path:
    if relative.suffix != ".py":
        parent = mapped(".".join(relative.parent.parts))
        return EDITOR.joinpath(*parent.split("."), relative.name)
    name = mapped(module_name(relative))
    if relative.name == "__init__.py":
        return EDITOR.joinpath(*name.split("."), "__init__.py")
    return EDITOR.joinpath(*name.split(".")).with_suffix(relative.suffix)


def rewrite(source: str, relative: Path, source_root: Path):
    tree = ast.parse(source)
    old_module = module_name(relative)
    lines = source.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))

    def offset(line, column):
        # Python AST columns are UTF-8 byte offsets, including Korean strings.
        return offsets[line - 1] + len(lines[line - 1].encode("utf-8")[:column].decode("utf-8"))

    changes = []
    spans = []
    needs_paths = False

    def replace(node, value, reason):
        start = offset(node.lineno, node.col_offset)
        end = offset(node.end_lineno, node.end_col_offset)
        if source[start:end] == value:
            return
        spans.append((start, end, value))
        changes.append({"line": node.lineno, "reason": reason, "before": source[start:end], "after": value})

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.level:
                parts = old_module.split(".") if relative.name == "__init__.py" else old_module.split(".")[:-1]
                base = ".".join(parts[:len(parts) - node.level + 1] + ([node.module] if node.module else []))
            else:
                base = node.module or ""
            if mapped(base) == base and not any(mapped(base + "." + a.name) != base + "." + a.name for a in node.names):
                continue
            statements = []
            groups = {}
            for alias in node.names:
                child = mapped(base + "." + alias.name)
                new_base = mapped(base)
                if child != new_base + "." + alias.name:
                    parent, _, leaf = child.rpartition(".")
                    groups.setdefault(parent, []).append(ast.alias(name=leaf, asname=alias.asname))
                else:
                    groups.setdefault(new_base, []).append(alias)
            for parent, names in groups.items():
                statements.append(ast.unparse(ast.ImportFrom(module=parent, names=names, level=0)))
            replace(node, ("\n" + " " * node.col_offset).join(statements), "namespace import")
        elif isinstance(node, ast.Import):
            aliases = []
            for alias in node.names:
                name = mapped(alias.name)
                if name != alias.name and not alias.asname and "." in alias.name:
                    raise ValueError(f"Unaliased dotted import needs explicit review: {relative}:{node.lineno}")
                aliases.append(ast.alias(name=name, asname=alias.asname or (alias.name if name != alias.name else None)))
            replace(node, ast.unparse(ast.Import(names=aliases)), "namespace import")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            value = node.value
            if value in {"design.optimizationjob", "design.designresult", "design.maasrevisionevent"}:
                continue
            if re.fullmatch(r"(?:design|land|law|graph_db)(?:\.[A-Za-z_][A-Za-z_0-9]*)+", value):
                new = mapped(value)
                if new != value:
                    replace(node, repr(new), "dynamic module name")

    # Replace directory ancestry by its original semantic location, not depth in
    # the relocated namespace. Package-local data remains adjacent to its owner.
    pattern = re.compile(r"(?:pathlib\.)?Path\(__file__\)(?:\.resolve\(\))?(?:(?:\.parents\[(\d+)\])|((?:\.parent)+))")
    for match in pattern.finditer(source):
        count = int(match.group(1)) + 1 if match.group(1) is not None else match.group(2).count(".parent")
        directory = source_root / relative
        for _ in range(count):
            directory = directory.parent
        if directory == source_root:
            value = "_design_paths.backend_root()"
        elif directory == source_root.parent:
            value = "_design_paths.arr_root()"
        elif directory == source_root.parent.parent or directory in source_root.parent.parent.parents:
            value = "_design_paths.workspace_root()"
        elif directory.is_relative_to(source_root):
            rel = directory.relative_to(source_root)
            value = f"_design_paths.package_root({str(rel).replace(chr(92), '/')!r})"
        else:
            raise ValueError(f"Unrecognized source directory: {directory}")
        if any(start <= match.start() < end for start, end, _ in spans):
            continue
        spans.append((match.start(), match.end(), value))
        changes.append({"line": source.count("\n", 0, match.start()) + 1, "reason": "owned runtime path", "before": match.group(0), "after": value})
        needs_paths = True

    for start, end, replacement in sorted(spans, reverse=True):
        source = source[:start] + replacement + source[end:]
    if needs_paths:
        parsed = ast.parse(source)
        insert_line = 0
        for node in parsed.body:
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str) and insert_line == 0:
                insert_line = node.end_lineno
            elif isinstance(node, ast.ImportFrom) and node.module == "__future__":
                insert_line = node.end_lineno
            else:
                break
        output_lines = source.splitlines(keepends=True)
        output_lines.insert(insert_line, f"\nfrom {GEN} import paths as _design_paths\n")
        source = "".join(output_lines)
    if old_module == "design.apps":
        source = source.replace("name = 'design'", f"name = '{STORE}'\n    label = 'design'")
        changes.append({"reason": "Django application ownership", "label": "design", "name": STORE})
    if old_module == "design.maas.book_language.execution.canonical":
        before = 'workspace = _design_paths.workspace_root()\n    return workspace / "agents" / "MassAgent" / "book-language"'
        after = 'return _design_paths.package_root("design/maas/book_language/data")'
        if before not in source:
            raise ValueError("Canonical book language lookup changed; review the import")
        source = source.replace(before, after)
        changes.append({"reason": "owned book dictionaries", "before": before, "after": after})
    if old_module in {"design.maas.research_backends.maas_clone_bridge", "design.maas.research_backends.d4descent_bridge"}:
        before = source
        source = re.sub(r"    inserted = False\n    if str\(src\) not in sys.path:\n        sys.path.insert\(0, str\(src\)\)\n        inserted = True\n", "", source)
        source = re.sub(r"    finally:\n        if inserted:\n            try:\n                sys.path.remove\(str\(src\)\)\n            except ValueError:\n                pass\n", "", source)
        if source != before:
            changes.append({"reason": "optional reference libraries must be installed; never mutate global import search paths"})
    if old_module == "design.services.floor_graph2plan":
        before = '    # Add Graph2Plan model dir to path for imports\n    model_dir = str(_G2P_ROOT)\n    if model_dir not in sys.path:\n        sys.path.insert(0, model_dir)\n\n'
        if before not in source:
            raise ValueError("Graph2Plan import changed; review the import")
        source = source.replace(before, '')
        changes.append({"reason": "Graph2Plan model library must be installed; never mutate global import search paths", "before": before, "after": ""})
        source = source.replace('except (FileNotFoundError, RuntimeError) as e:', 'except (FileNotFoundError, RuntimeError, ImportError) as e:')
        source = source.replace('_G2P_ROOT = _design_paths.workspace_root() / "clone" / "Graph2Plan" / "Interface"', '_G2P_ROOT = Path(os.environ.get("EDITOR_GRAPH2PLAN_MODEL_DIR", str(_design_paths.data_root() / "reference-models" / "graph2plan")))')
        changes.append({"reason": "explicit optional model installation directory and missing-library response"})
    owned_asset_paths = {
        "design.maas.language_memory": ('root / "ARR" / "frontend" / "maas-language-flow-final.png"', 'root / "previews" / "maas-language-flow-final.png"'),
        "design.maas.interactive.reference_intent": ('workspace / "ARR" / "backend" / "media"', '_design_paths.backend_root() / "media"'),
    }
    if old_module in owned_asset_paths:
        before, after = owned_asset_paths[old_module]
        if before not in source:
            raise ValueError(f"Asset lookup changed: {old_module}")
        source = source.replace(before, after)
        changes.append({"reason": "Editor-owned runtime artifact location", "before": before, "after": after})
    if old_module in {"design.maas.book_language.catalog", "design.maas.book_language.source_bundle"}:
        pattern = r'_design_paths.workspace_root\(\)\s*/\s*"docs"\s*/\s*"260506"\s*/\s*"BOOK"'
        source, count = re.subn(pattern, '_design_paths.package_root("design/maas/book_language/data/source")', source)
        if count != 1:
            raise ValueError(f"BOOK reference lookup changed: {old_module}")
        changes.append({"reason": "packaged authored BOOK reference documents"})
    ast.parse(source)
    return source, changes


def selected_files(root):
    for file in sorted((root / "design").rglob("*")):
        rel = file.relative_to(root)
        if not file.is_file() or any(part in {"__pycache__", "research", "management", "scripts", "aua_reference", "test_fixtures", "tests", "fixtures"} for part in rel.parts):
            continue
        if file.name.startswith("test") or file.suffix not in {".py", ".json", ".yaml", ".yml"}:
            continue
        yield file
    for module in sorted(LAND_MODULES | {"law.scripts.check_parking_counts", "graph_db.services.neo4j_service"}):
        file = root.joinpath(*module.split(".")).with_suffix(".py")
        if not file.exists():
            file = root.joinpath(*module.split("."), "__init__.py")
        if file.exists():
            yield file
    yield from sorted((root / "land" / "data").rglob("*.json"))


def reference_assets(root):
    workspace = root.parent.parent
    language = workspace / "agents/MassAgent/book-language"
    for category in ("verbs", "base-volumes", "massv2-verbs"):
        for file in sorted((language / category).glob("*.json")):
            yield file, "../../" + file.relative_to(workspace).as_posix(), EDITOR / "backend/app/modules/design/generation/maas/book_language/data" / category / file.name
    source = workspace / "docs/260506/BOOK"
    for filename in ("BOOK_건축언어_전체목록.csv", "BOOK_건축언어_전체추출.md", "BOOK_건축용어_단어목록.md", "BOOK_페이지별_건축용어_정리.md"):
        file = source / filename
        yield file, "../../" + file.relative_to(workspace).as_posix(), EDITOR / "backend/app/modules/design/generation/maas/book_language/data/source" / filename


def main():
    global EDITOR
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--only", action="append", help="Reimport only this source path; preserve other imported files")
    parser.add_argument("--output-dir", type=Path, help="Write a separate review tree instead of the current Editor checkout")
    args = parser.parse_args()
    helper = EDITOR / "backend/app/modules/design/generation/paths.py"
    helper_bytes = helper.read_bytes()
    if args.output_dir:
        EDITOR = args.output_dir.resolve()
    root = args.source.resolve()
    manifest_path = EDITOR / "backend/app/modules/design/generation/source-manifest.json"
    previous = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {"schema": "editor.design-runtime-import.v1", "source_layout": "ARR/backend", "files": []}
    imported = {record["destination"]: record for record in previous["files"]}
    selected = [file for file in selected_files(root) if not args.only or file.relative_to(root).as_posix() in args.only]
    protected = []
    for file in selected:
        target = destination(file.relative_to(root))
        if target.exists():
            record = imported.get(target.relative_to(EDITOR).as_posix())
            if record is None or hashlib.sha256(target.read_bytes()).hexdigest() != record["imported_sha256"]:
                protected.append(target.relative_to(EDITOR).as_posix())
    for file, _, target in reference_assets(root):
        if not file.is_file():
            parser.error(f"Required reference source is missing: {file}")
        if target.exists():
            record = imported.get(target.relative_to(EDITOR).as_posix())
            if record is None or hashlib.sha256(target.read_bytes()).hexdigest() != record["imported_sha256"]:
                protected.append(target.relative_to(EDITOR).as_posix())
    if protected:
        parser.error("Refusing to overwrite modified or untracked destinations; use --output-dir:\n" + "\n".join(protected))
    manifest = previous if args.only else {"schema": "editor.design-runtime-import.v1", "source_layout": "ARR/backend", "files": []}
    for file in selected:
        relative = file.relative_to(root)
        if args.only and relative.as_posix() not in args.only:
            continue
        target = destination(relative)
        original = file.read_bytes()
        changes = []
        if file.suffix == ".py":
            rewritten, changes = rewrite(original.decode("utf-8-sig").replace("\r\n", "\n"), relative, root)
            output = rewritten.encode("utf-8")
        else:
            output = original
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(output)
        directory = target.parent
        while directory != EDITOR / "backend":
            initializer = directory / "__init__.py"
            if not initializer.exists():
                initializer.write_text("", encoding="utf-8")
            directory = directory.parent
        manifest["files"] = [record for record in manifest["files"] if record["source"] != relative.as_posix()]
        manifest["files"].append({"source": relative.as_posix(), "destination": target.relative_to(EDITOR).as_posix(), "source_sha256": hashlib.sha256(original).hexdigest(), "imported_sha256": hashlib.sha256(output).hexdigest(), "changes": changes})
    for file, source_name, target in reference_assets(root):
        target.parent.mkdir(parents=True, exist_ok=True)
        original = file.read_bytes()
        target.write_bytes(original)
        manifest["files"] = [record for record in manifest["files"] if record["source"] != source_name]
        manifest["files"].append({"source": source_name, "destination": target.relative_to(EDITOR).as_posix(), "source_sha256": hashlib.sha256(original).hexdigest(), "imported_sha256": hashlib.sha256(original).hexdigest(), "changes": []})
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    target_helper = EDITOR / "backend/app/modules/design/generation/paths.py"
    if not target_helper.exists():
        target_helper.write_bytes(helper_bytes)
    print(f"Imported {len(manifest['files'])} files; manifest: {manifest_path}")


if __name__ == "__main__":
    main()
