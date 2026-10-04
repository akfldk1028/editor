import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).with_name('arr_import_inventory.py')


class ImportInventoryTests(unittest.TestCase):
    def test_missing_app_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            spec = importlib.util.spec_from_file_location('inventory', SCRIPT)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            result = module.inventory(Path(directory), [], ['absent_app'])
            self.assertEqual(result['missing_seeds'], ['absent_app'])

    def test_builtin_import_fromlist(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'pkg').mkdir()
            (root / 'entry.py').write_text(
                "__import__('pkg', fromlist=['child'])\n"
                "__import__('pkg', globals(), locals(), ('other',), 0)\n"
                "__import__('pkg', fromlist=variable)\n", encoding='utf-8')
            (root / 'pkg/__init__.py').write_text('', encoding='utf-8')
            (root / 'pkg/child.py').write_text('', encoding='utf-8')
            (root / 'pkg/other.py').write_text('', encoding='utf-8')
            spec = importlib.util.spec_from_file_location('inventory', SCRIPT)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            result = module.inventory(root, ['entry'], [])
            names = {f['module'] for f in result['source_files']}
            self.assertTrue({'pkg.child', 'pkg.other'} <= names)
            self.assertTrue(any(e.get('resolution') == 'computed-fromlist'
                                for e in result['dynamic_import_and_path_evidence']))

    def test_static_closure_and_aliases_without_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sources = {
                'entry.py': 'raise RuntimeError("must not execute")\nfrom pkg import public\nfrom pkg import sibling\nimport importlib\nimportlib.import_module("pkg.literal")\nimportlib.import_module(variable)\nimport presentation\nimport runtime.tools.helper\nimportlib.import_module(".relative", "pkg")\nimportlib.import_module(".computed", package_name)\n',
                'pkg/__init__.py': '_EXPORT_MODULES = {"public": ".leaf"}\nfrom . import init_dependency\n',
                'pkg/leaf.py': 'from .nested import child\n',
                'pkg/nested/__init__.py': '',
                'pkg/nested/child.py': 'from .. import sibling\n',
                'pkg/sibling.py': 'import json\nimport missing_vendor\nfrom pkg import absent_attribute\nfrom pkg.missing import value\n',
                'pkg/init_dependency.py': '',
                'pkg/literal.py': '',
                'pkg/relative.py': '',
                'runtime/tools/presentation.py': 'from helper import render\n',
                'runtime/tools/helper.py': 'render = None\n',
            }
            for relative, text in sources.items():
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding='utf-8')
            spec = importlib.util.spec_from_file_location('inventory', SCRIPT)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            result = module.inventory(root, ['entry'], [], [root / 'runtime/tools'])
            names = {f['module'] for f in result['source_files']}
            self.assertTrue({'pkg', 'pkg.leaf', 'pkg.nested', 'pkg.nested.child',
                             'pkg.sibling', 'pkg.init_dependency', 'pkg.literal',
                             'presentation', 'helper', 'pkg.relative'} <= names)
            self.assertFalse(result['parse_errors'])
            self.assertTrue(any(e['kind'] == 'lazy-export' for e in result['import_edges']))
            self.assertTrue(any(e['kind'] == 'package-init' for e in result['import_edges']))
            self.assertTrue(any('variable' in e['expression'] for e in result['dynamic_import_and_path_evidence']))
            self.assertTrue(any(e.get('resolution') == 'computed-package' for e in result['dynamic_import_and_path_evidence']))
            self.assertEqual(result['counts']['unique_physical_files'], len({f['source'] for f in result['source_files']}))
            self.assertGreater(result['counts']['module_identities'], result['counts']['unique_physical_files'])
            groups = result['nonlocal_imports']
            self.assertTrue(any(e['module'] == 'json' for e in groups['stdlib']))
            self.assertTrue(any(e['module'] == 'missing_vendor' for e in groups['third_party_candidate']))
            self.assertEqual([e['module'] for e in groups['unresolved_local']], ['pkg.missing'])

    def test_output_requires_explicit_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'entry.py').write_text('import json\n', encoding='utf-8')
            output = root / 'inventory.json'
            command = [sys.executable, str(SCRIPT), '--source-root', str(root),
                       '--entry', 'entry', '--output', str(output)]
            first = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(first.returncode, 0, first.stderr)
            before = output.read_bytes()
            second = subprocess.run(command, capture_output=True, text=True)
            self.assertNotEqual(second.returncode, 0)
            self.assertEqual(output.read_bytes(), before)
            third = subprocess.run(command + ['--overwrite'], capture_output=True, text=True)
            self.assertEqual(third.returncode, 0, third.stderr)
            self.assertEqual(json.loads(output.read_text())['source_files'][0]['module'], 'entry')


if __name__ == '__main__':
    unittest.main()
