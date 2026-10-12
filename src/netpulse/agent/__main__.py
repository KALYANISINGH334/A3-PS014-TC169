"""python -m agent [--once | --stop | --resume | --show-interface]."""
import argparse
import asyncio
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import sys

from agent.config import load_settings
from agent.measure import resolve
from agent.network import active_interface
from agent.runtime import Agent, AlreadyRunning, process_lock


async def run(args, directory):
    config_path = Path(args.config)
    settings = load_settings(args.config)
    if args.show_interface:
        target = next((item for item in settings.targets if item.approved), None)
        if not target:
            raise ValueError('No approved target configured.')
        address, _ = await resolve(target.host, settings.timeout_seconds)
        print('Active interface:', active_interface(address, target.port) or 'Unable to detect')
        print('No IP address or interface name is uploaded.')
        return 0
    if not settings.enabled:
        print('Collection is disabled in configuration. No probes or uploads sent.')
        return 0
    if not any(target.approved for target in settings.targets):
        raise ValueError('No approved target configured; no probes will be sent.')
    with process_lock(directory):
        if args.resume:
            (directory / 'stop').unlink(missing_ok=True)
        agent = Agent(directory, settings)
        if args.new_pilot:
            import time
            agent.state['pilot_started'] = time.time()
            agent.save_state()
        if agent.stopped():
            print('Collector is stopped. Use --resume to explicitly re-enable it.')
            return 0
        handler = RotatingFileHandler(directory / 'collector.log', maxBytes=1048576, backupCount=3, encoding='utf-8')
        logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s', handlers=[handler, logging.StreamHandler()])
        logging.info('Collector enabled: %ss interval, %s ICMP probes/target, throughput %s.', settings.interval_seconds, settings.samples, settings.throughput_enabled)
        logging.info('IDs are random pseudonyms. Ctrl+C or stop_netpulse.bat stops collection.')
        logging.getLogger('httpx').setLevel(logging.WARNING)
        last_config = config_path.stat().st_mtime_ns
        while not agent.stopped():
            try:
                if config_path.stat().st_mtime_ns != last_config:
                    # Invalid edits fail closed; never keep probing with obsolete approval.
                    agent.settings = load_settings(args.config)
                    last_config = config_path.stat().st_mtime_ns
                if agent.stopped():
                    break
                await agent.collect()
                agent.upload_one()
                if agent.pilot_finished() and not list(agent.queue.glob('*.json')):
                    logging.info('Seven-day/configured pilot window complete; no further probes scheduled.')
                    break
            except (ValueError, OSError) as exc:
                logging.error('Settings/state unavailable (%s); paused until repaired.', type(exc).__name__)
            if args.once:
                return 0 if not list(agent.queue.glob('*.json')) and not list(agent.rejected.glob('*.json')) else 1
            await asyncio.sleep(1)
        logging.info('Collector stopped; pending observations remain on disk.')
    return 0


def main():
    parser = argparse.ArgumentParser(description='Consenting-device NetPulse collector. Only approved targets are probed.')
    parser.add_argument('--config', default=os.environ.get('NETPULSE_CONFIG', 'targets.json'))
    parser.add_argument('--state-dir', default=os.environ.get('NETPULSE_AGENT_STATE_DIR', 'data/agent'))
    parser.add_argument('--new-pilot', action='store_true', help='Explicitly start a new pilot window, preserving IDs and previous observations.')
    parser.add_argument('--once', action='store_true', help='Run a due collection and one queued upload; honor persisted schedule.')
    parser.add_argument('--stop', action='store_true', help='Request a clean stop; preserves queue and stable IDs.')
    parser.add_argument('--resume', action='store_true', help='Explicitly clear the stop marker.')
    parser.add_argument('--show-interface', action='store_true', help='Show the routed interface locally for confirmation.')
    args = parser.parse_args()
    directory = Path(args.state_dir)
    directory.mkdir(parents=True, exist_ok=True)
    if args.stop:
        (directory / 'stop').touch()
        print('Stop requested. Collection exits after the current bounded operation.')
        return 0
    try:
        return asyncio.run(run(args, directory))
    except AlreadyRunning as exc:
        print(str(exc))
        return 0
    except KeyboardInterrupt:
        print('Collector stopped; queued observations retained.')
        return 0
    except (ValueError, OSError) as exc:
        print(f'Setup error ({type(exc).__name__}). Check targets.json and the state directory; no data was fabricated.')
        return 1


if __name__ == '__main__':
    sys.exit(main())
