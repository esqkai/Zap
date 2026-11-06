# Real-time synchronization foundation

This branch introduces a controller-owned, revisioned state hub and an
authenticated, **read-only** WebSocket stream on port 10087.

It is not yet wired to the MTTL-W01 server or exposed through the desktop GUI.
No physical outlet control is enabled through the WebSocket API.

## Design

- The physical strip has one controller connection.
- Windows and Linux clients subscribe to the same controller snapshot.
- Each update carries a monotonically increasing revision.
- Reconnecting clients receive a complete snapshot.
- Client authentication uses a high-entropy pairing token; do not commit tokens.
- The WebSocket listener defaults to loopback. Binding to a LAN interface requires
  explicit firewall restrictions and a secure pairing strategy.
- Only confirmed device state should be published once device integration is added.
- The controller, not individual desktop clients, will arbitrate charging automation.

## Next implementation steps

1. Wire device state callbacks to the hub with a safe serialization layer.
2. Add a controlled, authorized command API with hardware-state confirmation.
3. Add slow-subscriber recovery and network failure tests.
4. Add a PySide6 client, first-run pairing, and OS-specific installers.
5. Validate all protocol operations with real MTTL-W01 hardware.

## Preview controller startup

Install the optional dependency: `python -m pip install "websockets>=12"`.
Set `NXXT_SYNC_TOKEN` to a long, randomly generated secret in the controller
environment, then run `zap serve --sync --sync-host <controller-LAN-IP>`.
Port 10086 remains the strip's TCP connection; port 10087 is the read-only
client stream. Keep both ports restricted to trusted local networks.

The sync stream uses a shared secret but **no encryption** over `ws://`.
Use only on a trusted, isolated LAN; use TLS before deploying on untrusted
networks. Windows and Linux clients will share the same protocol.
