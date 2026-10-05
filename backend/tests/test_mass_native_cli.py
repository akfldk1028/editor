import subprocess
import sys
import pytest


def test_native_mass_cli_lists_original_commands_without_arr():
    result = subprocess.run([sys.executable, '-m', 'backend.domain_cli', '--help'],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert 'generate_massv2' in result.stdout
    assert 'audit_maas_agent_collaboration' in result.stdout


@pytest.mark.parametrize('command', ['generate_massv2', 'generate_maas_creative_100', 'audit_maas_agent_collaboration'])
def test_each_command_can_load_in_a_fresh_interpreter(command):
    result = subprocess.run([sys.executable, '-m', 'backend.domain_cli', command, '--help'],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert '--pnu' in result.stdout
