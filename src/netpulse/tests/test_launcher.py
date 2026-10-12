import json
from types import SimpleNamespace

from agent.config import Settings
from scripts import launcher


def test_launcher_reuses_existing_services_without_overwriting_config(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher, 'ROOT', tmp_path)
    monkeypatch.setattr(launcher, 'STATE', tmp_path / 'launcher.json')
    config = Settings(enabled=True).model_dump(mode='json')
    path = tmp_path / 'targets.json'
    path.write_text(json.dumps(config))
    monkeypatch.setattr(launcher, 'port_open', lambda port: True)
    schema = {'info': {'title': 'NetPulse'}, 'components': {'schemas': {'MeasurementCreate': {'properties': {'observation_id': {}, 'participant_id': {}, 'device_id': {}}}}}}
    monkeypatch.setattr(launcher.httpx, 'get', lambda *args, **kwargs: SimpleNamespace(status_code=200, json=lambda: schema))
    launched = []
    monkeypatch.setattr(launcher, 'launch', lambda name, args, records: launched.append(name))
    launcher.start()
    assert launched == ['collector']
    assert json.loads(path.read_text()) == config


def test_pid_reuse_does_not_stop_unrelated_process(monkeypatch):
    monkeypatch.setattr(launcher.psutil, 'Process', lambda pid: SimpleNamespace(create_time=lambda: 999))
    assert launcher.alive({'pid': 123, 'created': 100}) is None


def test_disabled_collection_does_not_launch_agent(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher, 'ROOT', tmp_path)
    monkeypatch.setattr(launcher, 'STATE', tmp_path / 'launcher.json')
    (tmp_path / 'targets.json').write_text(Settings(enabled=False).model_dump_json())
    monkeypatch.setattr(launcher, 'port_open', lambda port: True)
    schema = {'info': {'title': 'NetPulse'}, 'components': {'schemas': {'MeasurementCreate': {'properties': {'observation_id': {}, 'participant_id': {}, 'device_id': {}}}}}}
    monkeypatch.setattr(launcher.httpx, 'get', lambda *args, **kwargs: SimpleNamespace(status_code=200, json=lambda: schema))
    launched = []
    monkeypatch.setattr(launcher, 'launch', lambda name, args, records: launched.append(name))
    launcher.start()
    assert launched == []
