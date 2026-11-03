"""State management and telemetry tracking for MTTL-W01 power strips."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from nxxt_level.device.protocol import (
    BootInfo,
    ButtonEvent,
    OutletAck,
    OutletReading,
    PowerReport,
    SignalReport,
)

logger = logging.getLogger(__name__)

# Default active power threshold (Watts) to consider an outlet under meaningful electrical load
DEFAULT_LOAD_THRESHOLD_WATTS: float = 2.0


@dataclass
class OutletState:
    """State and electrical metrics for a single physical outlet."""
    channel: int
    is_on: bool = False
    power_w: float = 0.0
    energy_kwh: float = 0.0
    temp_c: int = 0
    runtime_seconds: int = 0
    meaningful_load_threshold_w: float = DEFAULT_LOAD_THRESHOLD_WATTS

    @property
    def has_meaningful_load(self) -> bool:
        """Indicates whether an active electrical load is drawing power above the threshold."""
        return self.is_on and (self.power_w >= self.meaningful_load_threshold_w)


@dataclass
class PowerStripState:
    """Consolidated state representation of an MTTL-W01 smart power strip."""
    mac: str
    model: str = "Unknown"
    firmware: str = "Unknown"
    ip_address: str = ""
    is_online: bool = False
    voltage_v: Optional[float] = None
    rssi_dbm: Optional[int] = None
    outlets: Dict[int, OutletState] = field(default_factory=lambda: {
        n: OutletState(channel=n) for n in range(1, 5)
    })

    @property
    def total_power_w(self) -> float:
        """Total real-time active load across all outlets in Watts."""
        return round(sum(o.power_w for o in self.outlets.values()), 2)

    @property
    def total_energy_kwh(self) -> float:
        """Total cumulative energy consumed across all outlets in kWh."""
        return round(sum(o.energy_kwh for o in self.outlets.values()), 3)

    @property
    def estimated_current_a(self) -> float:
        """Estimated total current draw in Amperes based on total power and line voltage."""
        if not self.voltage_v or self.voltage_v <= 0:
            return 0.0
        return round(self.total_power_w / self.voltage_v, 2)

    @property
    def is_any_outlet_on(self) -> bool:
        """True if at least one outlet relay is energized."""
        return any(o.is_on for o in self.outlets.values())

    @property
    def all_outlets_on(self) -> bool:
        """True if all 4 outlets are energized."""
        return all(o.is_on for o in self.outlets.values())

    def apply_bootinfo(self, info: BootInfo, peer_ip: str) -> None:
        """Update device metadata upon initial connection."""
        self.mac = info.primary_mac
        self.model = info.model
        self.firmware = info.firmware_version
        self.ip_address = peer_ip
        self.is_online = True
        logger.info(
            "Device registered: MAC=%s Model=%s FW=%s IP=%s",
            self.mac,
            self.model,
            self.firmware,
            self.ip_address,
        )

    def apply_readings(self, readings: List[OutletReading]) -> None:
        """Update outlet states from telemetry response."""
        for r in readings:
            if 1 <= r.channel <= 4:
                outlet = self.outlets.get(r.channel)
                if not outlet:
                    outlet = OutletState(channel=r.channel)
                    self.outlets[r.channel] = outlet
                outlet.is_on = r.is_on
                outlet.power_w = r.power_w
                outlet.energy_kwh = r.energy_kwh
                outlet.temp_c = r.temp_c
                outlet.runtime_seconds = r.runtime_seconds

    def apply_power_report(self, report: PowerReport) -> None:
        """Update voltage or current measurement."""
        if report.voltage_v is not None:
            self.voltage_v = report.voltage_v

    def apply_signal_report(self, report: SignalReport) -> None:
        """Update Wi-Fi signal measurement."""
        self.rssi_dbm = report.rssi_dbm

    def apply_button_event(self, event: ButtonEvent) -> None:
        """Update state following physical button actuation."""
        if event.is_master_button:
            logger.info("Physical MASTER button triggered -> all %s", "ON" if event.is_on else "OFF")
            for outlet in self.outlets.values():
                outlet.is_on = event.is_on
        elif 1 <= event.channel <= 4:
            logger.info("Physical button outlet %d triggered -> %s", event.channel, "ON" if event.is_on else "OFF")
            if event.channel in self.outlets:
                self.outlets[event.channel].is_on = event.is_on

    def apply_outlet_ack(self, ack: OutletAck) -> None:
        """Update state when strip confirms a commanded toggle."""
        if 1 <= ack.channel <= 4:
            if ack.channel in self.outlets:
                self.outlets[ack.channel].is_on = ack.is_on

    def format_terminal_summary(self) -> str:
        """Generate a clean ASCII status block for console display."""
        status_sym = "[ONLINE]" if self.is_online else "[OFFLINE]"
        volt_str = f"{self.voltage_v} V" if self.voltage_v is not None else "-- V"
        curr_str = f"{self.estimated_current_a} A"
        rssi_str = f"{self.rssi_dbm} dBm" if self.rssi_dbm is not None else "-- dBm"

        lines = [
            f"+----------------------------------------------------------------+",
            f"| Zap Strip: {self.mac:<14}  {status_sym:<10}  IP: {self.ip_address:<15}|",
            f"| Model: {self.model:<14}  Firmware: {self.firmware:<10} Wi-Fi: {rssi_str:<10} |",
            f"| Power: {self.total_power_w:>6.2f} W  Energy: {self.total_energy_kwh:>6.3f} kWh  Line: {volt_str:<7}  I: {curr_str:<7}|",
            f"+---+---------+-----------+------------+----------+--------------+",
            f"| # | Relay   | Power (W) | Energy kWh | Temp (C) | Load Active? |",
            f"+---+---------+-----------+------------+----------+--------------+",
        ]
        for ch in range(1, 5):
            o = self.outlets.get(ch, OutletState(channel=ch))
            state_str = "ON " if o.is_on else "OFF"
            load_str = "LOADED " if o.has_meaningful_load else "idle   "
            lines.append(
                f"| {ch} | {state_str:<7} | {o.power_w:>9.2f} | {o.energy_kwh:>10.3f} | {o.temp_c:>8} | {load_str:<12} |"
            )
        lines.append(f"+---+---------+-----------+------------+----------+--------------+")
        return "\n".join(lines)
