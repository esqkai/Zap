# Zap

Desktop Control Center for the Jinheung Electric / LG U+ **MTTL-W01** 4-Outlet Smart Power Strip.

Developed by **Nxxt Level**.

---

## Overview

**Zap** provides complete local control of the MTTL-W01 smart strip over your local network. It operates independently without cloud dependencies, vendor gateways, router DNS/NAT tampering, or firmware modification.

The strip communicates natively via plain text frames over outbound TCP port `10086`. Once provisioned, the power strip connects directly to the machine running Zap.

### Core Capabilities (Minimal Device Engine Phase)
- **Local SoftAP Provisioning CLI:** Interactive setup tool with secure password masking, execution planning, parameter validation, and dry-run simulation.
- **Asynchronous TCP Server:** Listens on port `10086` for outbound strip connections.
- **Telemetry Ingestion:** Realtime monitoring of per-outlet power (W), cumulative energy (kWh), relay temperature (°C), line voltage (V), estimated total current (A), and Wi-Fi signal (dBm).
- **Relay Control:** Discrete switching for outlets 1, 2, 3, and 4, as well as coordinated all-outlets switching.
- **Physical Button Event Tracking:** Live detection of physical button presses on the hardware strip, including individual outlet buttons (1-4) and the master button (0).
- **Electrical Load Detection:** Identifies meaningful electrical loads on individual outlets to support smart charging automation.
- **Clean Reconnection:** Automatically recovers state when the physical strip power-cycles or reconnects.

---

## Project Structure

```
nxxt-level/
├── docs/
│   └── protocol.md          # Internal protocol & hardware specification
├── src/
│   └── nxxt_level/
│       ├── __init__.py      # Package metadata
│       ├── cli.py           # CLI entry points (zap serve, zap provision)
│       └── device/
│           ├── __init__.py  # Device module exports
│           ├── protocol.py  # Pure protocol parser and command generator
│           ├── server.py    # Asynchronous TCP server & session engine
│           ├── state.py     # Power strip and outlet state models
│           └── provisioning.py # SoftAP TCP setup client
├── tests/
│   ├── __init__.py
│   ├── test_protocol.py     # Unit tests for protocol parsing and framing
│   ├── test_state.py        # Unit tests for state updates and calculations
│   └── test_integration.py  # Full async session lifecycle & provisioning tests
├── pyproject.toml           # Standard Python package configuration
├── README.md
└── .gitignore
```

---

## Getting Started

### Prerequisites
- Python 3.9+ (tested with Python 3.12)
- No external dependencies are required for the core engine or CLI.

### Installation

Clone the repository and install in editable mode:

```bash
cd nxxt-level
pip install -e .
```

Alternatively, run directly with `python -m nxxt_level.cli`:

```bash
# Set PYTHONPATH to src
export PYTHONPATH="src"   # On Linux/macOS
$env:PYTHONPATH="src"     # On Windows PowerShell
python -m nxxt_level.cli --help
```

---

## Provisioning the Strip

When first configuring the strip (or when moving it to a new controller IP / Wi-Fi network), use the provisioning tool from a Wi-Fi-enabled machine (such as a laptop):

1. **Put the strip into Setup Mode:**
   - Press and hold the strip's physical master button for ~10 seconds until the status LED blinks rapidly.

2. **Connect your machine to the strip's setup Wi-Fi:**
   - **SSID:** `TONLY_TAP_<7_HEX>` (e.g., `TONLY_TAP_5602BCC`)
   - **Password:** `LGU_<7_HEX>` (e.g., `LGU_5602BCC`)
   - The strip will assign your machine an IP like `192.168.1.2`, with gateway `192.168.1.1`.

3. **Run the provisioning command:**

```bash
# Dry run verification first (optional):
zap provision --server-ip 192.168.1.100 --ssid "MyHomeWiFi" --dry-run

# Interactive provisioning:
zap provision --server-ip 192.168.1.100 --ssid "MyHomeWiFi"
```

The tool will:
- Prompt securely for your Wi-Fi password (masked, not stored in shell history).
- Validate that neither the SSID nor password contains forbidden characters (`:` or line breaks).
- Validate the IPv4 address format.
- Display a full execution plan and request explicit user confirmation.
- Transmit the controller address (`up:ip:<IP>`) and Wi-Fi credentials (`up:connect:<SSID>:<PASS>`).
- Await confirmation from the strip (`up:ip:ip_ok` and `up:connect:connect_ok`).

4. Reconnect your machine to your normal network.

---

## Running the Device Server

On the controller PC whose IP address was provisioned into the strip:

```bash
zap serve --port 10086
```

When the strip connects, Zap will log the registration, poll initial metrics, and display a formatted live ASCII summary in the terminal:

```
+----------------------------------------------------------------+
| Zap Strip: 88D0391C0C4C    [ONLINE]    IP: 192.168.1.120      |
| Model: lgutap          Firmware: 0.1.54-1.0.66 Wi-Fi: -58 dBm  |
| Power: 145.20 W  Energy:  4.120 kWh  Line: 221.0 V  I: 0.66 A |
+---+---------+-----------+------------+----------+--------------+
| # | Relay   | Power (W) | Energy kWh | Temp (C) | Load Active? |
+---+---------+-----------+------------+----------+--------------+
| 1 | ON      |     42.50 |      1.210 |       31 | LOADED       |
| 2 | OFF     |      0.00 |      0.000 |       28 | idle         |
| 3 | ON      |    102.70 |      2.800 |       34 | LOADED       |
| 4 | OFF     |      0.00 |      0.110 |       27 | idle         |
+---+---------+-----------+------------+----------+--------------+
```

---

## Running the Test Suite

All tests execute completely offline without requiring physical hardware:

```bash
# Run with Python unittest
python -m unittest discover -s tests -p "test_*.py" -v
```

All 27 unit and integration tests verify:
- Message framing and null-byte cleanup
- Command generation and syntax constraints
- Robust protocol parsing and error resilience
- Meaningful electrical load detection thresholds
- Live asynchronous mock strip socket sessions and reconnection handling

---

## Documentation

For low-level wire formats, channel definitions, timing requirements, and hardware quirks, see:
- [docs/protocol.md](docs/protocol.md)
