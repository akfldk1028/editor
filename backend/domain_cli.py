"""Run the original domain commands from the installed Editor package."""
import importlib
import sys

COMMANDS = ('generate_massv2', 'generate_maas_creative_100', 'audit_maas_agent_collaboration')


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ('--help', '-h'):
        print('Editor domain commands:\n' + '\n'.join(COMMANDS))
        return
    name = sys.argv[1]
    if name not in COMMANDS:
        raise SystemExit('Unknown Editor domain command: ' + name)
    from backend.app.adapters.design_storage.bootstrap import ensure_design_runtime
    ensure_design_runtime()
    module = importlib.import_module('backend.app.modules.massing.commands.' + name)
    module.Command().run_from_argv(sys.argv)


if __name__ == '__main__':
    main()
