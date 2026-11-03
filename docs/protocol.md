# MTTL-W01 Device Communication & Provisioning Protocol Specification

**Application:** Zap  
**Organization:** Nxxt Level  
**Target Hardware:** Jinheung Electric / LG U+ MTTL-W01 4-Outlet Smart Power Strip  
**Firmware Observed:** 0.1.54-1.0.66 (Model identified in telemetry as `lgutap` or `LGU+-TAP-HW002`)

---

## 1. System Architecture Overview

The MTTL-W01 strip operates as an outbound TCP client connecting directly to a local or remote controller. It does not run an inbound HTTP or MQTT server during normal operation, nor does it require any cloud connection.

The communication lifecycle consists of two independent phases:
1. **Provisioning Phase:** A temporary SoftAP configuration session where the strip is told which Wi-Fi network to join and which controller IPv4 address to dial.
2. **Operational Phase:** The strip joins the provisioned Wi-Fi network and persistently connects outbound to the controller on TCP port `10086`.

```
Operational Phase:
+-------------------+                    +----------------------+
|  MTTL-W01 Strip   | --- TCP:10086 ---> | Zap Controller Engine |
|  (Outbound Client)|                    | (Inbound Server)     |
+-------------------+                    +----------------------+

Provisioning Phase (SoftAP):
+-------------------+                    +----------------------+
|  MTTL-W01 Strip   | <--- TCP:30300 --- | Nxxt Level Provision |
| (AP: 192.168.1.1) |                    | CLI (Laptop/Client)  |
+-------------------+                    +----------------------+
```

---

## 2. Framing, Encoding & Hardware Quirks

### 2.1 Transport Framing
- **Transport:** Raw TCP streaming sockets.
- **Line Encoding:** UTF-8 / ASCII text strings.
- **Line Terminator:** `\r\n` (CRLF) for commands sent from controller to strip. Strips generally send `\r\n` or `\n`.
- **Command Prefix:** All device protocol messages begin with the prefix `up:`.
- **Field Separators:** Colons (`:`) and semicolons (`;`) are used as hierarchical field delimiters.

### 2.2 Observed Hardware Quirks
- **Null-Byte Padding:** Strip responses frequently contain embedded or leading/trailing null bytes (`\x00`). Any protocol reader **must** strip null bytes (`b"\x00"`) prior to string decoding or parsing.
- **Delimiter Collision Limitation:** Because `:` and `\r\n` are fundamental framing delimiters in the strip's setup parser, Wi-Fi SSID and Wi-Fi password **must not** contain colons (`:`) or line breaks (`\r`, `\n`).
- **Single Server Storage:** The strip retains exactly one controller IPv4 address in non-volatile flash. Re-provisioning overwrites this address.
- **Fixed Outbound Port:** The firmware's outbound destination port is hardcoded to TCP `10086`. The controller must listen on port 10086.
- **Fixed Outlets:** Exactly 4 physical relay-switched outlets (numbered 1 through 4).

---

## 3. Provisioning Phase (SoftAP Setup Mode)

### 3.1 Strip SoftAP Behavior
- **Trigger:** Long-press the physical master power button on the strip for approximately 10 seconds until the status LED flashes rapidly.
- **Access Point SSID:** `TONLY_TAP_<7_HEX_CHARS>` (e.g., `TONLY_TAP_5602BCC`).
- **Access Point WPA2 Password:** `LGU_<7_HEX_CHARS>` (e.g., `LGU_5602BCC`, matching the identical 7 characters from the SSID).
- **Setup IP Configuration:**
  - Strip IP: `192.168.1.1` (Default Gateway)
  - Client DHCP Allocation: Typically assigns `192.168.1.2` / 24 to the connected client.
  - Setup Service Port: TCP `30300`.

### 3.2 Provisioning Handshake
Provisioning requires two sequential TCP transactions to `192.168.1.1:30300`. Each transaction can be performed over a discrete connection or sequentially.

#### 1. Set Controller Server IPv4 Address
- **Controller sends:**  
  `up:ip:<CONTROLLER_IPV4>\r\n`  
  *Example:* `up:ip:192.168.1.50\r\n`
- **Strip responds:**  
  `up:ip:ip_ok` (followed by CRLF / null padding)

#### 2. Set Home 2.4 GHz Wi-Fi Credentials & Connect
- **Controller sends:**  
  `up:connect:<SSID>:<PASSWORD>\r\n`  
  *Example:* `up:connect:MyHomeNet:SecretKey123\r\n`
- **Strip responds:**  
  `up:connect:connect_ok` (followed by CRLF / null padding)

Once `up:connect:connect_ok` is issued, the strip shuts down its SoftAP, associates with the specified 2.4 GHz BSSID, acquires a DHCP lease on the local network, and immediately initiates a TCP connection to `<CONTROLLER_IPV4>:10086`.

---

## 4. Operational Phase (Device to Server Protocol)

### 4.1 Connection Initiation & Boot Information (`up:bootinfo`)
Immediately upon establishing a TCP connection to the controller port 10086, the strip transmits a single registration frame:

`up:bootinfo:<model>;<mac_primary>;<mac_secondary>;<firmware>;connect\r\n`

- **Fields:**
  - `model`: Device model identifier (e.g., `lgutap` or `LGU+-TAP-HW002`).
  - `mac_primary`: 12-character hexadecimal MAC address (e.g., `88D0391C0C4C`).
  - `mac_secondary`: 12-character secondary identifier / MAC (often mirrors primary or reports interface MAC).
  - `firmware`: Firmware version string (e.g., `0.1.54-1.0.66`).
  - `connect`: Literal handshake keyword.

### 4.2 Telemetry & Channel Query (`up:getinfo:all`)
The controller polls the full strip state by dispatching:
`up:getinfo:all\r\n`

The strip replies with a composite record containing 5 channel records separated by colons:
`up:getinfo:<CH1_RECORD>:<CH2_RECORD>:<CH3_RECORD>:<CH4_RECORD>:<CH5_RECORD>`

#### Channel Record Format:
`<ch>:<runtime>;<relay>;<state>;<overload>;<overheat>;<power>;<energy>;<previous>;<config>;<status>;<event>;<temp>`

| Field | Type | Description | Units / Format |
|---|---|---|---|
| `ch` | Int (1-5) | Channels 1-4 correspond to physical outlets 1-4. Channel 5 is the internal aggregate. | 1 to 5 |
| `runtime` | Int | Outlet operational uptime or timer counter. | Seconds / Ticks |
| `relay` | String | Relay power state. | `on` or `off` |
| `state` | Int | Internal relay state flag. | Typically `1` (on) or `0` (off) |
| `overload` | String | Overload warning flag. | Alphanumeric (typically `0`) |
| `overheat` | String | Overheating warning flag. | Alphanumeric (typically `0`) |
| `power` | Int | Realtime active load power. | **Milliwatts (mW)** (divide by 1000 for Watts) |
| `energy` | Hex (8 chars) | Cumulative energy consumption. | **Hexadecimal Watt-hours (Wh)** (parse hex, divide by 1000 for kWh) |
| `previous` | Hex (8 chars) | Previous period energy register. | Hexadecimal |
| `config` | Hex (8 chars) | Channel configuration flags. | Hexadecimal |
| `status` | String | Operational status flag. | Alphanumeric |
| `event` | Hex (2 chars) | Event code. | Hexadecimal |
| `temp` | Int | Onboard thermal sensor reading for the outlet relay area. | **Degrees Celsius (°C)** |

### 4.3 Relay Control Commands (`up:onoff`)
To toggle an individual outlet:
- **Controller sends:**  
  `up:onoff:<channel>:<on|off>\r\n`  
  *Where `<channel>` is `1`, `2`, `3`, or `4`.*
- **Strip acknowledgement:**  
  `up:onoff:<channel>:<on|off>\r\n`

#### All-On / All-Off Behavior:
*Fact:* The MTTL-W01 hardware does **not** recognize `up:onoff:0` or an aggregate batch command over TCP.  
*Implementation Strategy:* To toggle all outlets, the controller sequentially issues `up:onoff:<ch>:<state>` for channels 1, 2, 3, and 4 in order, allowing a brief settling delay (~300ms) before querying updated telemetry with `up:getinfo:all`.

### 4.4 Diagnostic Telemetry Queries
The controller can solicit line voltage and wireless signal strength:

#### 1. Voltage Telemetry
- **Controller sends:**  
  `up:power_report:1:vol\r\n`
- **Strip responds:**  
  `up:power_report:1:<val>\r\n`  
  *Interpretation:* Values $\ge 50000$ represent RMS mains voltage in **millivolts (mV)**. E.g., `224500` corresponds to $224.5\text{ V}$.

#### 2. Wi-Fi Signal Telemetry
- **Controller sends:**  
  `up:query:wifirssi\r\n`
- **Strip responds:**  
  `up:query:<rssi>\r\n`  
  *Interpretation:* Signed integer representing Received Signal Strength Indicator in **dBm** (e.g. `-52`).

### 4.5 Unsolicited Physical Button Events
When a user presses a physical tactile button on the power strip, the strip autonomously emits an event message to the open TCP session:

`up:event:onoff:<ch>:<on|off>\r\n`

- **`<ch>` = `1` to `4`:** An individual outlet button was pressed; the indicated outlet changed state.
- **`<ch>` = `0`:** The master button was pressed, affecting the aggregate state of all outlets.

---

## 5. Facts vs. Assumptions

| Item | Status | Basis / Verification |
|---|---|---|
| SoftAP IP (`192.168.1.1`) and port (`30300`) | **Fact** | Verified by user ping test (0% loss) and reference codebase. |
| Inbound controller port `10086` | **Fact** | Hardcoded in strip firmware outbound connection routine. |
| Delimiters `:` and `\r\n` invalid in Wi-Fi SSID/password | **Fact** | Parser splits fields on `:`; presence causes corrupt command payload. |
| Power measurement unit is mW | **Fact** | Confirmed by reference values (e.g., 5300 mW = 5.3 W). |
| Energy register is hex Wh | **Fact** | Confirmed by reference parsing (`0000000A` hex = 10 Wh = 0.01 kWh). |
| Master all-on/all-off over TCP | **Fact** | `up:onoff:0` is rejected or ignored; sequential 1-4 is required. |
| Physical master button event (`up:event:onoff:0:<state>`) | **Fact** | Emitted directly by strip firmware upon physical button actuation. |
| Sub-50,000 `power_report` values are current (mA) | **Assumption** | Inferred from comments; voltage report returns $>50000$ mV. Controller computes current via $I = P / V$ to remain robust. |
| Channel 5 is aggregate power/energy | **Fact** | Channel 5 is received with cumulative values from internal strip MCU. |
| No cryptographic authentication on TCP 10086 | **Fact** | Plaintext protocol; transport isolation / private LAN required. |

---

## 6. Connection Management & Resilience Requirements

1. **Serialized Command Queue:** Commands must be serialized per connection using an asynchronous lock to avoid interleaved request/response frames.
2. **Graceful Reconnection:** When the physical strip resets or drops Wi-Fi, it reconnects and issues `up:bootinfo:...`. The controller must detect stale sessions, cleanly terminate old sockets, and re-bind state to the new session.
3. **Resilient Parsing:** Unrecognized lines, garbage bytes, or extra delimiters must be logged and discarded without raising unhandled exceptions or terminating the TCP loop.
