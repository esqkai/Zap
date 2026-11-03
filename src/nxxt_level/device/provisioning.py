"""Device provisioning routines for the MTTL-W01 setup access point."""

from __future__ import annotations

import ipaddress
import logging
import socket
import time
from typing import Dict, Optional

from nxxt_level.device.protocol import (
    DEFAULT_SETUP_HOST,
    DEFAULT_SETUP_PORT,
    build_provision_connect_command,
    build_provision_ip_command,
    clean_raw_line,
)

logger = logging.getLogger(__name__)


class ProvisioningError(Exception):
    """Raised when device provisioning fails."""


def validate_provision_params(ssid: str, password: str, server_ip: str) -> None:
    """Validate Wi-Fi and controller parameters before transmission."""
    if not ssid or not ssid.strip():
        raise ValueError("SSID cannot be empty")
    if not password:
        raise ValueError("Password cannot be empty")

    if any(c in ssid for c in (":", "\r", "\n")):
        raise ValueError("SSID contains ':' or newline characters, which are forbidden by the strip protocol")
    if any(c in password for c in (":", "\r", "\n")):
        raise ValueError("Password contains ':' or newline characters, which are forbidden by the strip protocol")

    try:
        parsed_ip = ipaddress.IPv4Address(server_ip.strip())
    except ValueError as exc:
        raise ValueError(f"Invalid server IPv4 address '{server_ip}': {exc}") from exc

    if parsed_ip.is_loopback:
        raise ValueError(f"Server IP {server_ip} is a loopback address; the strip must reach a real LAN or WAN IP")
    if parsed_ip.is_link_local:
        raise ValueError(f"Server IP {server_ip} is an autoconfigured link-local address (169.254.x.x)")


def send_setup_command(
    host: str,
    port: int,
    command_bytes: bytes,
    expected_substring: str,
    timeout: float = 6.0,
) -> str:
    """Send a single setup command to the strip SoftAP setup port and verify acknowledgment."""
    with socket.create_connection((host, port), timeout=timeout) as sock:
        sock.settimeout(timeout)
        sock.sendall(command_bytes)

        buffer = bytearray()
        deadline = time.monotonic() + timeout
        while b"\n" not in buffer and time.monotonic() < deadline:
            try:
                chunk = sock.recv(1024)
            except socket.timeout:
                break
            if not chunk:
                break
            buffer.extend(chunk)

    response_text = clean_raw_line(buffer)
    if expected_substring and expected_substring not in response_text:
        raise ProvisioningError(
            f"Strip replied with {response_text!r}, expected to contain {expected_substring!r}"
        )
    return response_text


def check_setup_ap_reachable(
    host: str = DEFAULT_SETUP_HOST,
    port: int = DEFAULT_SETUP_PORT,
    timeout: float = 2.0,
) -> bool:
    """Check whether the strip's setup AP port is reachable."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def provision_strip(
    ssid: str,
    password: str,
    server_ip: str,
    host: str = DEFAULT_SETUP_HOST,
    port: int = DEFAULT_SETUP_PORT,
    timeout: float = 6.0,
    dry_run: bool = False,
) -> Dict[str, str]:
    """Execute end-to-end strip provisioning against the SoftAP setup service."""
    validate_provision_params(ssid, password, server_ip)

    plan = {
        "target_setup_host": host,
        "target_setup_port": str(port),
        "configured_controller_ip": server_ip.strip(),
        "configured_wifi_ssid": ssid,
        "dry_run": str(dry_run),
    }

    if dry_run:
        logger.info("[DRY-RUN] Validated provisioning configuration successfully")
        return {**plan, "status": "dry_run_success"}

    logger.info("Attempting connection to strip setup service at %s:%d...", host, port)
    if not check_setup_ap_reachable(host, port, timeout=3.0):
        raise ProvisioningError(
            f"Unable to reach strip setup service at {host}:{port}.\n"
            "Ensure that:\n"
            "1. The strip is in setup mode (long-press main button ~10s until LED flashes rapidly)\n"
            "2. Your machine is connected to the 'TONLY_TAP_...' Wi-Fi network\n"
            f"3. Ping to {host} succeeds"
        )

    # Step 1: Set controller IP
    logger.info("Setting controller IPv4 address to %s...", server_ip.strip())
    ip_cmd = build_provision_ip_command(server_ip.strip())
    ip_resp = send_setup_command(host, port, ip_cmd, expected_substring="up:ip:ip_ok", timeout=timeout)
    logger.info("Controller IP configured successfully: %s", ip_resp)

    # Step 2: Set Wi-Fi credentials
    logger.info("Configuring 2.4 GHz Wi-Fi SSID '%s'...", ssid)
    conn_cmd = build_provision_connect_command(ssid, password)
    conn_resp = send_setup_command(host, port, conn_cmd, expected_substring="up:connect:connect_ok", timeout=timeout)
    logger.info("Wi-Fi credentials configured successfully: %s", conn_resp)

    return {
        **plan,
        "ip_response": ip_resp,
        "connect_response": conn_resp,
        "status": "success",
    }
