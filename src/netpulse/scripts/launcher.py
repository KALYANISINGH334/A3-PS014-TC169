"""Windows service launcher. Tracks only processes it starts; never kills port owners."""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

import httpx
import psutil

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / 'data' / 'launcher.json'
sys.path.insert(0, str(ROOT))


def port_open(port):
    with socket.socket() as sock:
        sock.settimeout(0.3)
        return sock.connect_ex(('127.0.0.1', port)) == 0


def alive(record):
    try:
        process = psutil.Process(record['pid'])
        return process if abs(process.create_time() - record['created']) < 0.01 else None
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return None


def load_records():
    return json.loads(STATE.read_text()) if STATE.exists() else {}


def save_records(records):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    temp = STATE.with_suffix('.tmp')
    temp.write_text(json.dumps(records))
    os.replace(temp, STATE)


def launch(name, arguments, records):
    if name in records and alive(records[name]):
        print(f'{name}: already started by this launcher.')
        return
    flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NEW_CONSOLE if os.name == 'nt' else 0
    process = subprocess.Popen([sys.executable, *arguments], cwd=ROOT, creationflags=flags)
    records[name] = {'pid': process.pid, 'created': psutil.Process(process.pid).create_time()}
    save_records(records)
    print(f'{name}: started (PID {process.pid}).')


def start():
    config = ROOT / 'targets.json'
    if not config.exists():
        config.write_bytes((ROOT / 'targets.example.json').read_bytes())
    from agent.config import load_settings
    settings = load_settings(str(config))
    records = load_records()
    if port_open(8000):
        response = httpx.get('http://127.0.0.1:8000/openapi.json', timeout=5)
        schema = response.json()
        if response.status_code != 200 or schema.get('info', {}).get('title') != 'NetPulse' or not {'observation_id', 'participant_id', 'device_id'}.issubset(schema.get('components', {}).get('schemas', {}).get('MeasurementCreate', {}).get('properties', {})):
            raise RuntimeError('Port 8000 is occupied by an incompatible backend. Leave it running; stop it manually or use the documented separate-terminal configuration.')
        print('backend: existing compatible NetPulse API retained.')
    else:
        launch('backend', ['-m', 'uvicorn', 'backend.main:app', '--host', '127.0.0.1', '--port', '8000'], records)
        for _ in range(50):
            if port_open(8000):
                break
            time.sleep(0.1)
        if not port_open(8000):
            raise RuntimeError('Backend did not start. Check its console; collector was not started.')
    if settings.enabled:
        launch('collector', ['-m', 'agent', '--resume'], records)
    else:
        print('collector: disabled in targets.json.')
    if port_open(8501):
        print('dashboard: port 8501 already occupied; existing service left unchanged.')
    else:
        launch('dashboard', ['-m', 'streamlit', 'run', 'dashboard/app.py', '--server.address', '127.0.0.1', '--server.port', '8501'], records)
    print('Dashboard: http://localhost:8501 | API: http://localhost:8000/docs')
    print('Stop with stop_netpulse.bat. Close the individual consoles with Ctrl+C if preferred.')


def stop():
    directory = Path(os.environ.get('NETPULSE_AGENT_STATE_DIR', str(ROOT / 'data' / 'agent')))
    directory.mkdir(parents=True, exist_ok=True)
    (directory / 'stop').touch()
    records = load_records()
    collector = alive(records['collector']) if 'collector' in records else None
    # Wait for bounded probes/upload to finish; do not delete the persistent outbox.
    if collector:
        try:
            collector.wait(timeout=50)
        except psutil.TimeoutExpired:
            print('Collector still finishing: stop requested; its queue remains intact.')
    for name in ['dashboard', 'backend']:
        process = alive(records[name]) if name in records else None
        if not process:
            continue
        try:
            if os.name == 'nt':
                # A detached helper signals only this service's console. The
                # launcher keeps its own console and output handles intact.
                code = ("import ctypes,sys,time; k=ctypes.windll.kernel32; "
                        "k.FreeConsole(); ok=k.AttachConsole(int(sys.argv[1])); "
                        "k.SetConsoleCtrlHandler(None,True); "
                        "sent=k.GenerateConsoleCtrlEvent(0,0) if ok else False; "
                        "time.sleep(0.2); k.FreeConsole(); sys.exit(0 if sent else 1)")
                result = subprocess.run([sys.executable, '-c', code, str(process.pid)],
                                        creationflags=subprocess.CREATE_NO_WINDOW, timeout=5)
                if result.returncode:
                    print(f'{name}: could not signal console; use Ctrl+C in its window.')
            else:
                process.terminate()
            process.wait(timeout=10)
        except (psutil.TimeoutExpired, psutil.NoSuchProcess):
            print(f'{name}: stop requested; check its console if still running.')
    remaining = {name: record for name, record in records.items() if alive(record)}
    save_records(remaining)
    print('Stop completed for launcher-owned services. Pre-existing backend/dashboard services were preserved.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--stop', action='store_true')
    args = parser.parse_args()
    os.chdir(ROOT)
    try:
        stop() if args.stop else start()
    except (OSError, ValueError, RuntimeError, httpx.HTTPError) as exc:
        message = str(exc) if isinstance(exc, RuntimeError) else f'{type(exc).__name__}: check targets.json, ports and service consoles.'
        print(f'Launcher error: {message}')
        sys.exit(1)
