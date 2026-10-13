import subprocess
import sys
from agent.config import Settings


def test_cli_help():
    result = subprocess.run([sys.executable, '-m', 'agent', '--help'], capture_output=True, text=True)
    assert result.returncode == 0
    assert '--stop' in result.stdout and '--new-pilot' in result.stdout


def test_disabled_cli_never_collects(tmp_path):
    config = tmp_path / 'config.json'
    config.write_text(Settings(enabled=False).model_dump_json())
    result = subprocess.run([sys.executable, '-m', 'agent', '--config', str(config), '--state-dir', str(tmp_path / 'state'), '--once'], capture_output=True, text=True)
    assert result.returncode == 0
    assert 'disabled' in result.stdout
    assert not (tmp_path / 'state' / 'queue').exists()


def test_cli_stop_is_persistent(tmp_path):
    result = subprocess.run([sys.executable, '-m', 'agent', '--stop', '--state-dir', str(tmp_path)], capture_output=True, text=True)
    assert result.returncode == 0 and (tmp_path / 'stop').exists()
