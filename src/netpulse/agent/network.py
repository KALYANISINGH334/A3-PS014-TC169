"""Observe the routed interface locally. Never upload addresses or interface names."""
import hashlib
import socket

import psutil


def active_interface(address, port=443):
    try:
        # UDP connect selects a route; no datagram is sent.
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect((address, port))
            local = sock.getsockname()[0]
        for name, addresses in psutil.net_if_addrs().items():
            if any(item.family == socket.AF_INET and item.address == local for item in addresses):
                return name
    except OSError:
        pass
    return None


def interface_identity(name, device_id):
    if name is None:
        return None
    return hashlib.sha256(f"{device_id}:{name}".encode()).hexdigest()[:24]


def network_label(settings, detected_name):
    verified = bool(settings.verification_source != "unverified" and detected_name
                    and settings.confirmed_interface == detected_name)
    if settings.verification_source != "unverified" and not verified:
        return "Unknown", False, "unverified"
    return settings.access_medium.value, verified, settings.verification_source if verified else "unverified"
