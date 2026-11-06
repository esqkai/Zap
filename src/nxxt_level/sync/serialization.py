"""Convert mutable device state into stable, JSON-safe wire snapshots."""
from __future__ import annotations

from nxxt_level.device.state import PowerStripState


def serialize_strip(state: PowerStripState) -> dict:
    """Serialize only public telemetry; never include provisioning credentials."""
    return {
        "mac": state.mac,
        "model": state.model,
        "firmware": state.firmware,
        "ip_address": state.ip_address,
        "online": state.is_online,
        "voltage_v": state.voltage_v,
        "rssi_dbm": state.rssi_dbm,
        "total_power_w": state.total_power_w,
        "total_energy_kwh": state.total_energy_kwh,
        "estimated_current_a": state.estimated_current_a,
        "outlets": {
            str(ch): {
                "on": outlet.is_on,
                "power_w": outlet.power_w,
                "energy_kwh": outlet.energy_kwh,
                "temp_c": outlet.temp_c,
                "runtime_seconds": outlet.runtime_seconds,
                "has_load": outlet.has_meaningful_load,
            }
            for ch, outlet in sorted(state.outlets.items())
        },
    }
