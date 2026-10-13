"""Durable JSON outbox, stable pseudonyms, and bounded scheduling."""
import asyncio
import json
import logging
import os
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from backend.models import MeasurementCreate
from agent.measure import measure
from agent.upload import upload_observation, UploadError

LOG = logging.getLogger('netpulse.agent')


def atomic_json(path, body):
    temporary = path.with_suffix('.tmp')
    with temporary.open('w', encoding='utf-8') as output:
        json.dump(body, output, separators=(',', ':'))
        output.flush()
        os.fsync(output.fileno())
    os.replace(temporary, path)


class AlreadyRunning(Exception):
    pass


@contextmanager
def process_lock(directory):
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / 'collector.lock').open('a+b') as handle:
        handle.seek(0)
        if not handle.read(1):
            handle.write(b'1')
            handle.flush()
        handle.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise AlreadyRunning('A collector already holds this device state directory.') from exc
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == 'nt':
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


class Agent:
    def __init__(self, directory, settings, uploader=upload_observation, clock=time.time, probe=measure):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.queue = self.directory / 'queue'
        self.queue.mkdir(exist_ok=True)
        self.rejected = self.directory / 'rejected'
        self.rejected.mkdir(exist_ok=True)
        self.state_path = self.directory / 'state.json'
        if self.state_path.exists():
            self.state = json.loads(self.state_path.read_text(encoding='utf-8'))
        else:
            self.state = {'participant_id': str(settings.participant_id or uuid4()), 'device_id': str(uuid4()),
                          'pilot_started': clock(), 'next_collection': 0, 'download_due': {}, 'interfaces': {}}
        # One participant can explicitly reuse their random UUID across devices.
        if settings.participant_id:
            self.state['participant_id'] = str(settings.participant_id)
        self.settings, self.uploader, self.clock, self.probe = settings, uploader, clock, probe
        self.failures = self.state.get("upload_failures", 0)
        self.upload_due = self.state.get("upload_due", 0)
        self.save_state()

    def save_state(self):
        if hasattr(self, "upload_due"):
            self.state["upload_due"] = self.upload_due
            self.state["upload_failures"] = self.failures
        atomic_json(self.state_path, self.state)

    def stopped(self):
        return (self.directory / 'stop').exists() or not self.settings.enabled

    def pilot_finished(self):
        days = self.settings.pilot_days
        return days is not None and self.clock() >= self.state['pilot_started'] + days * 86400

    async def collect(self):
        if self.pilot_finished():
            return False
        if self.stopped() or self.clock() < self.state['next_collection']:
            return False
        if len(list(self.queue.glob('*.json'))) >= 10000:
            LOG.error('Outbox is full; collection paused to avoid losing observations.')
            self.state['next_collection'] = self.clock() + self.settings.interval_seconds
            self.save_state()
            return False
        # Persist a reservation first: restart/crash cannot cause an immediate probe burst.
        self.state['next_collection'] = self.clock() + self.settings.interval_seconds
        self.save_state()
        for target in self.settings.targets:
            if not target.approved or self.stopped() or len(list(self.queue.glob("*.json"))) >= 10000:
                continue
            due = self.state['download_due'].get(target.id, 0)
            allow_download = bool(self.settings.throughput_enabled and target.download_url and self.clock() >= due)
            if allow_download:
                self.state['download_due'][target.id] = self.clock() + self.settings.throughput_interval_seconds
                self.save_state()
            try:
                observation = await asyncio.wait_for(self.probe(target, self.settings,
                    self.state['participant_id'], self.state['device_id'],
                    self.state['interfaces'].get(target.id), allow_download), 45)
            except (OSError, TimeoutError, ValueError) as exc:
                LOG.error('Collection failed safely (%s); no substitute values generated.', type(exc).__name__)
                continue
            # Queue must reach disk before any upload. No central database is duplicated here.
            atomic_json(self.queue / f'{observation.observation_id}.json', observation.model_dump(mode='json'))
            if observation.interface_id:
                self.state['interfaces'][target.id] = observation.interface_id
            self.save_state()
            LOG.info('Collected observation %s: %s; latency=%s, loss=%s, dns=%s; queued.',
                     observation.observation_id, observation.status, observation.latency_ms,
                     observation.packet_loss_pct, observation.dns_ms)
        if self.clock() >= self.state['next_collection']:
            # Only postpone an overrun; normally keep start-to-start cadence.
            self.state['next_collection'] = self.clock() + self.settings.interval_seconds
        self.save_state()
        return True

    def upload_one(self):
        if self.clock() < self.upload_due:
            return False
        files = sorted(self.queue.glob('*.json'), key=lambda item: item.stat().st_mtime)
        if not files:
            return False
        path = files[0]
        try:
            payload = MeasurementCreate.model_validate_json(path.read_text(encoding='utf-8'))
            saved = self.uploader(payload)
        except UploadError as exc:
            if not exc.retryable:
                os.replace(path, self.rejected / path.name)
                LOG.error('Observation rejected permanently; retained in rejected folder for review.')
                self.upload_due = self.clock() + 5
            else:
                self.failures += 1
                self.upload_due = self.clock() + min(300, 5 * 2 ** min(self.failures - 1, 6))
                LOG.warning('Upload unavailable; queued observation retained. Retry in %ss.', self.upload_due - self.clock())
            self.save_state()
            return False
        except (ValueError, OSError):
            # Damaged local files remain available for recovery; do not block healthy files.
            os.replace(path, self.rejected / path.name)
            LOG.error('Invalid local queue file retained in rejected folder.')
            self.upload_due = self.clock() + 5
            self.save_state()
            return False
        path.unlink()
        self.failures = 0
        self.upload_due = self.clock() + 1  # Never send more than one upload per second.
        self.save_state()
        LOG.info('Uploaded observation %s as database record %s.', payload.observation_id, saved.id)
        return True
