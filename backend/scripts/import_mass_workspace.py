"""Relocate original Mass commands and workspace tools into their Editor owners."""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import re

from backend.scripts.import_design_runtime import rewrite, SPECIAL


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--refresh', action='store_true', help='Refresh only files still matching the previous import manifest')
    args = parser.parse_args()
    source_root = args.source.resolve()
    editor = Path(__file__).resolve().parents[2]
    manifest = editor / 'backend/app/modules/massing/workspace-source-manifest.json'
    previous = json.loads(manifest.read_text(encoding='utf-8')) if manifest.exists() else {'files': []}
    prior = {item['destination']: item['imported_sha256'] for item in previous['files']}
    tools_root = source_root / 'tmp_mass_check/_massv2/tools'
    tools = sorted(file for file in tools_root.glob('*.py') if file.name != 'fix_agent04.py')
    package = 'backend.app.modules.massing.workspace_tools'
    SPECIAL.update({file.stem: package + '.' + file.stem for file in tools})
    commands = ('generate_massv2', 'generate_maas_creative_100', 'audit_maas_agent_collaboration')
    items = [(file, editor / 'backend/app/modules/massing/workspace_tools' / file.name, True) for file in tools]
    items += [(source_root / 'design/management/commands' / (name + '.py'),
               editor / 'backend/app/modules/massing/commands' / (name + '.py'), False) for name in commands]
    records = []
    for source, target, workspace_tool in items:
        original = source.read_bytes()
        text = original.decode('utf-8-sig').replace('\r\n', '\n')
        if workspace_tool:
            text = re.sub(r'(?:_?Path|pathlib.Path)\(__file__\)(?:\.resolve\(\))?\.parents\[1\]',
                          '__MASS_WORKSPACE__', text)
            text = re.sub(r'^\s*(?:_?sys)\.path\.insert\(0, str\(Path\(__file__\)\.resolve\(\)\.parents\[3\]\)\)\s*$', '', text, flags=re.M)
            text = re.sub(r'os.environ.setdefault\(["\']DJANGO_SETTINGS_MODULE["\'], ["\']backend.settings["\']\)', '', text)
            text = text.replace('django.setup()', 'ensure_design_runtime()')
            text = text.replace('; ensure_design_runtime()', 'ensure_design_runtime()')
        else:
            text = text.replace('    tools_dir = Path(__file__).resolve().parents[3] / "tmp_mass_check" / "_massv2" / "tools"\n    if str(tools_dir) not in sys.path:\n        sys.path.insert(0, str(tools_dir))\n', '')
            text = text.replace('_Path(__file__).resolve().parents[2] / "maas"',
                                '_design_paths.package_root("design/maas")')
        text, changes = rewrite(text, source.relative_to(source_root), source_root)
        text = text.replace('__MASS_WORKSPACE__', '_mass_paths.workspace_root()')
        text = text.replace("_design_paths.package_root('tmp_mass_check/_massv2/tools')", '_mass_paths.tools_root()')
        text = text.replace("Path('tmp_mass_check/_massv2/tools')", '_mass_paths.tools_root()')
        text = re.sub(r'Path\(["\'](?:D:/Data/25_ACE/ARR/backend/)?tmp_mass_check/_massv2(?P<suffix>/[^"\']*)?["\']\)',
                      lambda match: '_mass_paths.workspace_root()' + (' / ' + repr(match.group('suffix').lstrip('/')) if match.group('suffix') else ''), text)
        text = re.sub(r'^\s*_?sys\.path\.insert\(0, str\(_mass_paths.tools_root\(\)\)\)\s*$', '', text, flags=re.M)
        text = text.replace('sys.path.insert(0, os.getcwd())', '')
        text = text.replace('; sys.path.insert(0, str(T))', '')
        prefix = ('from backend.app.modules.massing import paths as _mass_paths\n'
                  'from backend.app.modules.design.generation import paths as _design_paths\n'
                  'from backend.app.adapters.design_storage.bootstrap import ensure_design_runtime\n')
        tree = ast.parse(text)
        insert = 0
        for node in tree.body:
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str) and not insert:
                insert = node.end_lineno
            elif isinstance(node, ast.ImportFrom) and node.module == '__future__':
                insert = node.end_lineno
            else:
                break
        lines = text.splitlines(keepends=True)
        if 'from backend.app.modules.design.generation import paths as _design_paths' in text:
            prefix = prefix.replace('from backend.app.modules.design.generation import paths as _design_paths\n', '')
        lines.insert(insert, '\n' + prefix + '\n')
        output = ''.join(lines).encode('utf-8')
        ast.parse(output)
        if target.exists() and target.read_bytes() != output and not (
                args.refresh and hashlib.sha256(target.read_bytes()).hexdigest() == prior.get(target.relative_to(editor).as_posix())):
            raise RuntimeError(f'Refusing to overwrite changed file: {target}')
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(output)
        records.append({'source': source.relative_to(source_root).as_posix(),
                        'destination': target.relative_to(editor).as_posix(),
                        'source_sha256': hashlib.sha256(original).hexdigest(),
                        'imported_sha256': hashlib.sha256(output).hexdigest(),
                        'changes': changes})
    manifest.write_text(json.dumps({'schema': 'editor.mass-workspace-import.v1', 'files': records},
                                   ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'Imported {len(records)} original workspace tools and commands')


if __name__ == '__main__':
    main()
