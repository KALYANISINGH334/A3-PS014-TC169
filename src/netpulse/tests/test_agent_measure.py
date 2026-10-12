import asyncio
from uuid import uuid4
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from agent.config import Settings, Target
from agent.measure import measure, parse_ping_output, resolve, native_ping
from agent.network import network_label
from agent.upload import upload_observation, UploadError
from backend.main import app


@pytest.mark.parametrize('updates', [{"samples": 6}, {"interval_seconds": 1}, {"timeout_seconds": 6},
    {"throughput_enabled": True}, {"verification_source": "participant_attestation"}])
def test_configuration_limits(updates):
    with pytest.raises(ValidationError):
        Settings(**updates)


def test_ping_parser_does_not_invent_submillisecond_rtt():
    assert parse_ping_output(b'Reply time=12ms TTL=128', 'win32', 0) == (True, 12)
    assert parse_ping_output(b'Reply time<1ms TTL=128', 'win32', 0) == (True, None)
    assert parse_ping_output(b'Destination host unreachable', 'win32', 0) == (False, None)


def test_labels_are_confirmed_on_current_interface_only():
    settings = Settings(confirmed_interface='Wi-Fi', verification_source='participant_attestation')
    assert network_label(settings, 'Wi-Fi') == ('Wi-Fi', True, 'participant_attestation')
    assert network_label(settings, 'Ethernet') == ('Unknown', False, 'unverified')
    assert network_label(Settings(), 'Ethernet') == ('Wi-Fi', False, 'unverified')


def test_bounded_measurement_and_existing_api(tmp_path, monkeypatch):
    monkeypatch.setenv('NETPULSE_DB_PATH', str(tmp_path / 'test.sqlite3'))
    monkeypatch.setattr('agent.measure.resolve', AsyncMock(return_value=('127.0.0.1', 2)))
    ping = AsyncMock(side_effect=[(True, 10), (False, None), (True, 20)])
    monkeypatch.setattr('agent.measure.ping_once', ping)
    monkeypatch.setattr('agent.measure.active_interface', lambda *args: 'Wi-Fi')
    download = AsyncMock()
    monkeypatch.setattr('agent.measure.download', download)
    observation = asyncio.run(measure(Settings().targets[0], Settings(), uuid4(), uuid4()))
    assert observation.latency_ms == 15
    assert observation.packet_loss_pct == pytest.approx(100/3)
    assert observation.throughput_mbps is None
    assert observation.probe_count == 3 and observation.probe_replies == 2
    assert not observation.medium_verified
    assert ping.await_count == 3
    download.assert_not_called()
    with TestClient(app) as backend:
        def route(request):
            response = backend.request(request.method, str(request.url), headers=dict(request.headers), content=request.content)
            return httpx.Response(response.status_code, content=response.content)
        transport = httpx.MockTransport(route)
        saved = upload_observation(observation, 'http://testserver', transport)
        assert upload_observation(observation, 'http://testserver', transport).id == saved.id
        items = backend.get('/measurements').json()
        assert items['total'] == 1
        assert items['items'][0]['device_id'] == str(observation.device_id)
        changed = observation.model_copy(update={'dns_ms': 999})
        with pytest.raises(UploadError) as error:
            upload_observation(changed, 'http://testserver', transport)
        assert not error.value.retryable


def test_missing_probes_and_dns_remain_null(monkeypatch):
    monkeypatch.setattr('agent.measure.resolve', AsyncMock(side_effect=TimeoutError))
    monkeypatch.setattr('agent.measure.ping_once', AsyncMock(return_value=(None, None)))
    observation = asyncio.run(measure(Settings().targets[0], Settings(samples=1), uuid4(), uuid4()))
    assert observation.status == 'failed'
    assert observation.latency_ms is observation.dns_ms is observation.packet_loss_pct is None


def test_unapproved_target_never_measured():
    with pytest.raises(ValueError):
        asyncio.run(measure(Target(id='no', host='1.1.1.1'), Settings(), uuid4(), uuid4()))


def test_real_local_dns_and_icmp():
    async def check():
        address, elapsed = await resolve('localhost', 2)
        assert address == '127.0.0.1' and elapsed >= 0
        replied, rtt = await native_ping('127.0.0.1', 1)
        if replied is None:
            pytest.skip('OS does not permit unprivileged ping sockets')
        assert replied and rtt is not None and rtt > 0
    import sys
    if not sys.platform.startswith('linux'):
        pytest.skip('Linux ping socket check')
    asyncio.run(check())


def test_invalid_api_configuration_is_a_retriable_queue_error():
    from backend.models import MeasurementCreate
    observation = MeasurementCreate(timestamp='2026-01-01T00:00:00Z', latency_ms=12)
    with pytest.raises(UploadError) as error:
        upload_observation(observation, 'file:///not-an-api')
    assert error.value.retryable


def test_optional_download_is_bounded_and_rejects_redirects(monkeypatch):
    from agent.measure import download
    original = httpx.AsyncClient
    def handler(request):
        if request.url.path == '/redirect':
            return httpx.Response(302, headers={'location': 'http://unapproved.example/file'})
        return httpx.Response(200, stream=httpx.ByteStream(b'x' * 8192))
    monkeypatch.setattr('agent.measure.httpx.AsyncClient', lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs))
    result = asyncio.run(download('http://localhost/file', 1024, 2))
    assert result['bytes'] == 1024 and result['mbps'] > 0
    with pytest.raises(ValueError):
        asyncio.run(download('http://localhost/redirect', 1024, 2))
