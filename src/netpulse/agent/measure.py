"""Bounded real probes. Missing or failed measurements remain null."""

import asyncio
import json
import shutil
import sys
import time
import socket
import struct
import os
import re
import statistics
from datetime import datetime, timezone
from uuid import uuid4

from backend.models import MeasurementCreate
from agent.network import active_interface, interface_identity, network_label

import httpx

from agent.config import Settings, Target


async def resolve(host: str, timeout: float) -> tuple[str, float]:
    # A subprocess makes even a stuck OS resolver cancellable on Windows/Linux.
    code = (
        "import socket,time,json,sys; start=time.perf_counter(); "
        "addresses=socket.getaddrinfo(sys.argv[1],None,family=socket.AF_INET,type=socket.SOCK_STREAM); "
        "print(json.dumps([addresses[0][4][0],(time.perf_counter()-start)*1000]))"
    )
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-c", code, host,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout)
        if process.returncode:
            raise OSError("DNS resolution failed")
        address, elapsed = json.loads(stdout)
        return address, elapsed
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()


def parse_ping_output(output: bytes, platform: str, returncode: int):
    text = output.decode(errors="replace").lower()
    if platform == "win32":
        replied = "ttl=" in text
    elif returncode in (0, 1):
        replied = returncode == 0
    else:
        return None, None
    if not replied:
        return False, None
    # A tool's "<1ms" is an upper bound, not an invented 0 or 1ms sample.
    match = re.search(r"[=]\s*([0-9]+(?:[.,][0-9]+)?)\s*ms", text)
    return True, float(match.group(1).replace(",", ".")) if match else None


def checksum(data):
    if len(data) % 2:
        data += b"\x00"
    total = sum(struct.unpack(f"!{len(data)//2}H", data))
    total = (total >> 16) + (total & 0xffff)
    total += total >> 16
    return (~total) & 0xffff


async def native_ping(address: str, timeout: float):
    # Linux ping sockets avoid privileged raw sockets and external dependencies.
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_ICMP)
    except OSError:
        return None, None
    with sock:
        sock.setblocking(False)
        payload = b"NetPulse" + os.urandom(16)
        sequence = int.from_bytes(os.urandom(2), "big")
        header = struct.pack("!BBHHH", 8, 0, 0, 0, sequence)
        packet = struct.pack("!BBHHH", 8, 0, checksum(header + payload), 0, sequence) + payload
        loop = asyncio.get_running_loop()
        started = time.perf_counter()
        try:
            await loop.sock_sendto(sock, packet, (address, 0))
            while True:
                remaining = timeout - (time.perf_counter() - started)
                if remaining <= 0:
                    return False, None
                response = await asyncio.wait_for(loop.sock_recv(sock, 1024), remaining)
                if len(response) >= 8 and response[0] == 0 and response[6:8] == struct.pack("!H", sequence) and response[8:] == payload:
                    return True, (time.perf_counter() - started) * 1000
        except TimeoutError:
            return False, None
        except PermissionError:
            return None, None
        except OSError:
            return False, None


async def ping_once(address: str, timeout: float):
    if sys.platform.startswith("linux"):
        result = await native_ping(address, timeout)
        if result[0] is not None:
            return result
    executable = shutil.which("ping")
    if not executable:
        return None, None
    args = (["-n", "1", "-w", str(int(timeout * 1000))] if sys.platform == "win32"
            else ["-n", "-c", "1", "-W", str(int(timeout * 1000) if sys.platform == "darwin" else max(1, int(timeout)))])
    process = await asyncio.create_subprocess_exec(
        executable, *args, address, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout + 0.5)
        return parse_ping_output(stdout, sys.platform, process.returncode)
    except TimeoutError:
        return False, None
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()


async def download(url: str, limit: int, timeout: float) -> dict:
    async def transfer():
        start = time.perf_counter()
        count = 0
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False, trust_env=False) as client:
            async with client.stream("GET", url, headers={"Accept-Encoding": "identity"}) as response:
                if response.status_code != 200 or response.headers.get("content-encoding", "identity") != "identity":
                    raise ValueError("Unsupported download response")
                async for chunk in response.aiter_raw(chunk_size=1024):
                    count += min(len(chunk), limit - count)
                    if count >= limit:
                        break
        seconds = time.perf_counter() - start
        return {"bytes": count, "seconds": seconds, "mbps": count * 8 / seconds / 1_000_000 if count and seconds > 0 else None}

    return await asyncio.wait_for(transfer(), timeout)


async def measure(target: Target, settings: Settings, participant_id, device_id, previous_interface=None, allow_download=False):
    if not target.approved or not settings.enabled:
        raise ValueError("Collection is disabled or target is not approved")
    timestamp = datetime.now(timezone.utc)
    errors = []
    dns_ms = None
    address = None
    try:
        _, dns_ms = await resolve(settings.dns_hostname, settings.timeout_seconds)
    except (OSError, TimeoutError, ValueError):
        errors.append("dns_failed_or_timed_out")
    try:
        # IP-literal targets need no additional DNS query.
        socket.inet_aton(target.host)
        address = target.host
    except OSError:
        try:
            address, _ = await resolve(target.host, settings.timeout_seconds)
        except (OSError, TimeoutError, ValueError):
            errors.append("target_resolution_failed")
    name = active_interface(address, target.port) if address else None
    interface = interface_identity(name, device_id)
    medium, verified, source = network_label(settings, name)
    changed = (previous_interface != interface) if previous_interface and interface else None
    replies, latencies = [], []
    attempts = 0
    if address:
        for _ in range(settings.samples):
            replied, rtt = await ping_once(address, settings.timeout_seconds)
            if replied is not None:
                attempts += 1
                replies.append(replied)
            if replied and rtt is not None:
                latencies.append(rtt)
            await asyncio.sleep(0.2)
    loss = 100 * (1 - sum(replies) / len(replies)) if len(replies) == settings.samples else None
    if loss is None:
        errors.append("icmp_unavailable")
    if not latencies:
        errors.append("icmp_rtt_unavailable")
    throughput = None
    count = None
    if allow_download and settings.throughput_enabled and target.download_url:
        try:
            transfer = await download(target.download_url, settings.max_download_bytes, settings.timeout_seconds)
            throughput, count = transfer["mbps"], transfer["bytes"]
            if throughput is None:
                errors.append("download_empty")
        except (httpx.HTTPError, OSError, TimeoutError, ValueError):
            errors.append("download_failed_or_timed_out")
    metrics = [statistics.median(latencies) if latencies else None, loss, dns_ms, throughput]
    status = "failed" if all(value is None for value in metrics) else "partial" if errors else "success"
    return MeasurementCreate(
        timestamp=timestamp, observation_id=uuid4(), participant_id=participant_id, device_id=device_id,
        access_medium=medium, medium_verified=verified, verification_source=source,
        isp=settings.isp, location_category=settings.location_category, status=status,
        latency_ms=metrics[0], packet_loss_pct=loss, dns_ms=dns_ms, throughput_mbps=throughput,
        interface_id=interface, network_changed=changed, target_id=target.id,
        latency_method="icmp_echo", dns_method="system_resolver", probe_count=attempts,
        probe_replies=sum(replies) if len(replies) == attempts else None,
        throughput_bytes=count, collection_errors=errors, collection_interval_seconds=settings.interval_seconds,
    )
