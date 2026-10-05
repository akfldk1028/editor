"""Execute an installed Mass workspace tool using explicit caller-owned data."""
import importlib.util
import re
import runpy
import sys


def main():
    if len(sys.argv) < 2 or not re.fullmatch(r'[a-z][a-z0-9_]*(?:\.py)?', sys.argv[1]):
        raise SystemExit('Expected a Mass workspace tool name')
    name = sys.argv[1].removesuffix('.py')
    module = 'backend.app.modules.massing.workspace_tools.' + name
    if importlib.util.find_spec(module) is None:
        raise SystemExit('Unknown Mass workspace tool: ' + name)
    sys.argv = [name + '.py', *sys.argv[2:]]
    runpy.run_module(module, run_name='__main__')


if __name__ == '__main__':
    main()
