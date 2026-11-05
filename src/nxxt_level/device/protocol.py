"""Protocol parsing, framing, validation, and command generation for MTTL-W01."""

from __future__ import annotations

import ipaddress
import logging
import re
from dataclasses import dataclass
from typing import List, Optional, Tuple, Union

logger = logging.getLogger(__name__)

# Standard protocol constants
DEFAULT_DEVICE_PORT: int = 10086
DEFAULT_SETUP_HOST: str = "192.168.1.1"
DEFAULT_SETUP_PORT: int = 30300

# Regex patterns for line parsing
_BOOTINFO_PATTERN = re.compile(
    r"^up:bootinfo:([^;\r\n]+);([0-9A-Fa-f]{12});([0-9A-Fa-f]{12});([^;\r\n]+);connect$",
    re.IGNORECASE,
)

_GETINFO_CHANNEL_PATTERN = re.compile(
    r"(?P<ch>[1-5]):(?P<runtime>-?\d+);(?P<relay>on|off);(?P<state>-?\d+);"
    r"(?P<overload>[^;:]+);(?P<overheat>[^;:]+);(?P<power>-?\d+);"
    r"(?P<energy>[0-9A-Fa-f]{8});(?P<previous>[0-9A-Fa-f]{8});"
    r"(?P<config>[0-9A-Fa-f]{8});(?P<status>[^;:]+);"
    r"(?P<event>[0-9A-Fa-f]{2});(?P<temperature>-?\d+)",
    re.IGNORECASE,
)

_BUTTON_EVENT_PATTERN = re.compile(r"^up:event:onoff:([0-4]):(on|off)$", re.IGNORECASE)
_POWER_REPORT_PATTERN = re.compile(r"^up:power_report:([1-5]):(-?\d+)$", re.IGNORECASE)
_RSSI_QUERY_PATTERN = re.compile(r"^up:query:(-?\d+)$", re.IGNORECASE)
_ONOFF_ACK_PATTERN = re.compile(r"^up:onoff:([1-4]):(on|off)$", re.IGNORECASE)


@dataclass(frozen=True)
class BootInfo:
    """Device registration emitted by the strip upon initial TCP connection."""
    model: str
    primary_mac: str
    secondary_mac: str
    firmware_version: str


@dataclass(frozen=True)
class OutletReading:
    """Parsed telemetry record for an individual outlet (1-4) or aggregate (5)."""
    channel: int
    is_on: bool
    runtime_seconds: int
    raw_state: int
    overload_flag: str
    overheat_flag: str
    power_w: float
    energy_kwh: float
    temp_c: int
    is_aggregate: bool = False


@dataclass(frozen=True)
class PowerReport:
    """Voltage or current measurement report from the strip."""
    channel: int
    raw_value: int
    voltage_v: Optional[float] = None
    current_ma: Optional[int] = None


@dataclass(frozen=True)
class ButtonEvent:
    """Hardware tactile button event triggered on the physical power strip."""
    channel: int
    is_on: bool

    @property
    def is_master_button(self) -> bool:
        """True if the master all-outlets button was pressed."""
        return self.channel == 0


@dataclass(frozen=True)
class SignalReport:
    """Wi-Fi signal strength indication in dBm."""
    rssi_dbm: int


@dataclass(frozen=True)
class OutletAck:
    """Confirmation acknowledgement sent by the strip after switching an outlet."""
    channel: int
    is_on: bool


class ProtocolError(Exception):
    """Raised when protocol validation fails."""


def clean_raw_line(raw: Union[bytes, bytearray, memoryview, str]) -> str:
    """Clean raw wire bytes or string.

    Strips null bytes (a known hardware quirk of the MTTL-W01), carriage returns,
    newlines, and surrounding whitespace.
    """
    if isinstance(raw, (bytes, bytearray, memoryview)):
        raw = bytes(raw).replace(b"\x00", b"").decode("utf-8", errors="replace")
    elif isinstance(raw, str):
        raw = raw.replace("\x00", "")
    return raw.strip("\r\n ")


def build_outlet_command(channel: int, on: bool) -> bytes:
    """Generate wire frame to toggle an outlet (channel 1-4)."""
    if channel not in (1, 2, 3, 4):
        raise ValueError(f"Channel must be between 1 and 4, got {channel}")
    state = "on" if on else "off"
    return f"up:onoff:{channel}:{state}\r\n".encode("ascii")


def build_getinfo_all() -> bytes:
    """Generate wire frame to poll status and telemetry of all outlets."""
    return b"up:getinfo:all\r\n"


def build_voltage_query() -> bytes:
    """Generate wire frame to poll line voltage."""
    return b"up:power_report:1:vol\r\n"


def build_rssi_query() -> bytes:
    """Generate wire frame to poll Wi-Fi RSSI."""
    return b"up:query:wifirssi\r\n"


def build_provision_ip_command(server_ip: str) -> bytes:
    """Generate wire frame to configure the strip's target controller IP."""
    try:
        ip = str(ipaddress.IPv4Address(server_ip.strip()))
    except ValueError as exc:
        raise ValueError(f"Invalid IPv4 address: {server_ip}") from exc
    return f"up:ip:{ip}\r\n".encode("ascii")


def build_provision_connect_command(ssid: str, password: str) -> bytes:
    """Generate wire frame to configure the strip's Wi-Fi network credentials."""
    for val, name in ((ssid, "SSID"), (password, "Password")):
        if any(c in val for c in (":", "\r", "\n")):
            raise ValueError(f"{name} cannot contain ':' or newline characters due to strip framing limits")
    return f"up:connect:{ssid}:{password}\r\n".encode("utf-8")


def parse_bootinfo(line: str) -> Optional[BootInfo]:
    """Parse registration bootinfo frame."""
    match = _BOOTINFO_PATTERN.match(line)
    if not match:
        return None
    model, mac1, mac2, fw = match.groups()
    return BootInfo(
        model=model,
        primary_mac=mac1.upper(),
        secondary_mac=mac2.upper(),
        firmware_version=fw,
    )


def parse_getinfo(line: str) -> List[OutletReading]:
    """Parse telemetry payload from `up:getinfo:...` into structured outlet records."""
    text = clean_raw_line(line)
    if text.startswith("up:getinfo:"):
        text = text[len("up:getinfo:"):]

    readings: List[OutletReading] = []
    for match in _GETINFO_CHANNEL_PATTERN.finditer(text):
        g = match.groupdict()
        ch = int(g["ch"])
        is_on = g["relay"].lower() == "on"
        runtime = int(g["runtime"])
        raw_state = int(g["state"])
        overload = g["overload"]
        overheat = g["overheat"]
        power_raw = int(g["power"])
        power_w = round(power_raw / 1000.0, 2)
        try:
            energy_wh = int(g["energy"], 16)
            energy_kwh = round(energy_wh / 1000.0, 3)
        except ValueError:
            energy_kwh = 0.0
        temp_c = int(g["temperature"])

        readings.append(
            OutletReading(
                channel=ch,
                is_on=is_on,
                runtime_seconds=runtime,
                raw_state=raw_state,
                overload_flag=overload,
                overheat_flag=overheat,
                power_w=power_w,
                energy_kwh=energy_kwh,
                temp_c=temp_c,
                is_aggregate=(ch == 5),
            )
        )
    return readings


def parse_power_report(line: str) -> Optional[PowerReport]:
    """Parse voltage or current report."""
    match = _POWER_REPORT_PATTERN.match(line)
    if not match:
        return None
    ch = int(match.group(1))
    val = int(match.group(2))
    if val >= 50000:
        # Values >= 50,000 are line voltage in mV
        return PowerReport(channel=ch, raw_value=val, voltage_v=round(val / 1000.0, 1))
    # Sub-50,000 values are current in mA
    return PowerReport(channel=ch, raw_value=val, current_ma=val)


def parse_button_event(line: str) -> Optional[ButtonEvent]:
    """Parse physical button press event."""
    match = _BUTTON_EVENT_PATTERN.match(line)
    if not match:
        return None
    ch = int(match.group(1))
    is_on = match.group(2).lower() == "on"
    return ButtonEvent(channel=ch, is_on=is_on)


def parse_rssi_query(line: str) -> Optional[SignalReport]:
    """Parse Wi-Fi signal report."""
    match = _RSSI_QUERY_PATTERN.match(line)
    if not match:
        return None
    return SignalReport(rssi_dbm=int(match.group(1)))


def parse_onoff_ack(line: str) -> Optional[OutletAck]:
    """Parse outlet toggle acknowledgement."""
    match = _ONOFF_ACK_PATTERN.match(line)
    if not match:
        return None
    ch = int(match.group(1))
    is_on = match.group(2).lower() == "on"
    return OutletAck(channel=ch, is_on=is_on)


def parse_line(raw_line: Union[bytes, str]) -> Optional[Union[BootInfo, List[OutletReading], PowerReport, ButtonEvent, SignalReport, OutletAck]]:
    """Clean and parse any incoming line from the strip into a structured message."""
    try:
        line = clean_raw_line(raw_line)
        if not line:
            return None

        if line.startswith("up:bootinfo:"):
            return parse_bootinfo(line)
        if line.startswith("up:getinfo:"):
            return parse_getinfo(line)
        if line.startswith("up:event:onoff:"):
            return parse_button_event(line)
        if line.startswith("up:power_report:"):
            return parse_power_report(line)
        if line.startswith("up:query:"):
            return parse_rssi_query(line)
        if line.startswith("up:onoff:"):
            return parse_onoff_ack(line)

        logger.debug("Ignored unhandled strip message: %r", line)
        return None
    except Exception as exc:
        logger.warning("Error parsing protocol message %r: %s", raw_line, exc)
        return None
