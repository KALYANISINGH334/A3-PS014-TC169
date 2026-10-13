import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from backend.models import MeasurementCreate
from agent.config import Settings
from agent.runtime import Agent, AlreadyRunning, process_lock
from agent.upload import UploadError


def payload():
    return MeasurementCreate(timestamp='2026-01-01T00:00:00Z', observation_id=uuid4(), latency_ms=12)


def test_schedule_persists_and_does_not_catch_up(tmp_path):
    clock = [1000]
    probe = AsyncMock(return_value=payload())
    settings = Settings()
    first = Agent(tmp_path, settings, clock=lambda: clock[0], probe=probe)
    assert asyncio.run(first.collect())
    assert len(list(first.queue.glob('*.json'))) == 1
    ids = (first.state['participant_id'], first.state['device_id'])
    second = Agent(tmp_path, settings, clock=lambda: clock[0], probe=probe)
    assert ids == (second.state['participant_id'], second.state['device_id'])
    assert not asyncio.run(second.collect())
    clock[0] = 5000
    assert asyncio.run(second.collect())
    assert probe.await_count == 2  # No replay of missed five-minute intervals.


def test_outage_retains_queue_and_retries_with_backoff(tmp_path):
    now = [1000]
    uploads = []
    def upload(record):
        uploads.append(record.observation_id)
        if len(uploads) < 2:
            raise UploadError('offline')
        return SimpleNamespace(id=1)
    agent = Agent(tmp_path, Settings(), uploader=upload, clock=lambda: now[0], probe=AsyncMock(return_value=payload()))
    asyncio.run(agent.collect())
    assert not agent.upload_one()
    assert len(list(agent.queue.glob('*.json'))) == 1
    assert not agent.upload_one() and len(uploads) == 1
    now[0] += 5
    assert agent.upload_one()
    assert not list(agent.queue.glob('*.json'))
    assert uploads[0] == uploads[1]


def test_permanent_rejection_is_retained_separately(tmp_path):
    def reject(record):
        raise UploadError('invalid', retryable=False)
    agent = Agent(tmp_path, Settings(), uploader=reject, probe=AsyncMock(return_value=payload()))
    asyncio.run(agent.collect())
    assert not agent.upload_one()
    assert not list(agent.queue.glob('*.json'))
    assert len(list(agent.rejected.glob('*.json'))) == 1


def test_single_process_lock(tmp_path):
    with process_lock(tmp_path):
        with pytest.raises(AlreadyRunning):
            with process_lock(tmp_path):
                pytest.fail('Second process acquired the lock')
    with process_lock(tmp_path):
        pass


def test_stop_and_disabled_never_probe(tmp_path):
    probe = AsyncMock()
    agent = Agent(tmp_path, Settings(enabled=False), probe=probe)
    assert not asyncio.run(agent.collect())
    agent.settings = Settings()
    (tmp_path / 'stop').touch()
    assert not asyncio.run(agent.collect())
    probe.assert_not_called()


def test_throughput_rate_limit_survives_restart(tmp_path):
    from agent.config import Target
    settings = Settings(throughput_enabled=True, targets=[Target(id='owned', host='localhost', port=8000,
        approved=True, download_url='http://localhost:8000/file')])
    now = [1000]
    probe = AsyncMock(return_value=payload())
    agent = Agent(tmp_path, settings, clock=lambda: now[0], probe=probe)
    asyncio.run(agent.collect())
    assert probe.call_args.args[-1] is True
    now[0] += 300
    agent = Agent(tmp_path, settings, clock=lambda: now[0], probe=probe)
    asyncio.run(agent.collect())
    assert probe.call_args.args[-1] is False


def test_backoff_survives_restart(tmp_path):
    now = [1000]
    def offline(record):
        raise UploadError('offline')
    agent = Agent(tmp_path, Settings(), uploader=offline, clock=lambda: now[0], probe=AsyncMock(return_value=payload()))
    asyncio.run(agent.collect())
    agent.upload_one()
    restarted = Agent(tmp_path, Settings(), uploader=offline, clock=lambda: now[0])
    assert restarted.upload_due == 1005
    assert restarted.failures == 1
    assert not restarted.upload_one()


def test_seven_day_pilot_stops_new_probes_without_deleting_queue(tmp_path):
    now = [1000]
    probe = AsyncMock(return_value=payload())
    agent = Agent(tmp_path, Settings(), clock=lambda: now[0], probe=probe)
    asyncio.run(agent.collect())
    now[0] += 7 * 86400
    assert agent.pilot_finished()
    assert not asyncio.run(agent.collect())
    assert probe.await_count == 1
    assert len(list(agent.queue.glob('*.json'))) == 1


def test_schedule_keeps_five_minute_start_to_start_cadence(tmp_path):
    now = [1000]
    async def probe(*args):
        now[0] += 10
        return payload()
    agent = Agent(tmp_path, Settings(), clock=lambda: now[0], probe=probe)
    asyncio.run(agent.collect())
    assert agent.state['next_collection'] == 1300
