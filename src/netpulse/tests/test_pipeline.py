"""Collector → HTTP API contract → SQLite → dashboard, isolated from live data."""
import asyncio
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
from fastapi.testclient import TestClient
from streamlit.testing.v1 import AppTest

from agent.config import Settings
from agent.runtime import Agent
from agent.upload import upload_observation
from backend.main import app
from dashboard.api import APIClient


def test_collectors_to_database_and_dashboard(tmp_path, monkeypatch):
    monkeypatch.setenv('NETPULSE_DB_PATH', str(tmp_path / 'test.sqlite3'))
    monkeypatch.setattr('agent.measure.resolve', AsyncMock(return_value=('127.0.0.1', 3)))
    monkeypatch.setattr('agent.measure.ping_once', AsyncMock(return_value=(True, 15)))
    with TestClient(app) as backend:
        def route(request):
            response = backend.request(request.method, str(request.url), headers=dict(request.headers), content=request.content)
            return httpx.Response(response.status_code, content=response.content)
        transport = httpx.MockTransport(route)
        uploader = lambda record: upload_observation(record, 'http://testserver', transport)
        for device in ['volunteer-a', 'volunteer-b']:
            agent = Agent(tmp_path / device, Settings(), uploader=uploader)
            asyncio.run(agent.collect())
            assert agent.upload_one()
        result = backend.get('/measurements').json()
        assert result['total'] == 2
        assert len({item['participant_id'] for item in result['items']}) == 2
        assert all(item['throughput_mbps'] is None for item in result['items'])
        original = APIClient.__init__
        def init(self, base_url=None, transport=None):
            original(self, 'http://testserver', httpx.MockTransport(route))
        monkeypatch.setattr(APIClient, '__init__', init)
        from pathlib import Path
        at = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'dashboard/app.py'), default_timeout=15).run()
        assert not at.exception
        assert at.metric[0].value == '2'
        assert at.metric[1].value == '15.00 ms'
        assert at.metric[4].value == '—'
        assert any('not a process heartbeat' in item.value for item in at.caption)
        at.multiselect[1].set_value([result['items'][0]['participant_id']]).run()
        assert at.metric[0].value == '1'
        at.radio[0].set_value('Live Measurements').run()
        assert not at.exception
        assert any('Automatic device collection' in item.value for item in at.subheader)
        # Persistence after opening a new backend context.
    with TestClient(app) as restarted:
        assert restarted.get('/measurements').json()['total'] == 2


def test_genuine_local_resolver_through_existing_pipeline(tmp_path, monkeypatch):
    # A real resolver call, not a simulated metric. Local diagnostic only:
    # its records stay in the temporary test database, never the live pilot.
    monkeypatch.setenv('NETPULSE_DB_PATH', str(tmp_path / 'local-check.sqlite3'))
    from agent.config import Target
    from agent.measure import measure
    settings = Settings(samples=1, dns_hostname='localhost', access_medium='Unknown',
                        targets=[Target(id='local-diagnostic', host='127.0.0.1', approved=True)])
    observation = asyncio.run(measure(settings.targets[0], settings, uuid4(), uuid4()))
    assert observation.dns_ms is not None and observation.dns_ms >= 0
    with TestClient(app) as backend:
        saved = backend.post('/measurements', json=observation.model_dump(mode='json'))
        assert saved.status_code == 201
        records = backend.get('/measurements').json()['items']
        assert records[0]['dns_ms'] == observation.dns_ms
        from dashboard.analytics import summaries, to_frame
        assert summaries(to_frame(records))['dns_ms']['median'] == observation.dns_ms
