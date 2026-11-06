# Desktop preview builds

This is an early **read-only monitor**, not yet the final Nxxt Level release.

## Preview builds

GitHub Actions workflow `Desktop preview builds` runs tests and produces:
- Windows: `NxxtLevel.exe` (portable executable, **not yet a setup installer**)
- Linux: a bundled executable directory (not yet an AppImage)

Open the workflow's successful run and download the appropriate artifact.
A preview artifact is not a production-signed release.

## Running locally

Install with `python -m pip install ".[desktop]"`, then launch
`nxxt-level`. Enter the controller WebSocket address and pairing token.

Start the controller with `zap serve --sync --sync-host <LAN-IP>` and a
random 32+ character `NXXT_SYNC_TOKEN` environment variable. Both clients
must use the same token. Do not commit or publish it.

The monitor displays the first connected strip's state. Remote relay controls
are deliberately disabled until the command/acknowledgement API is implemented
and validated against physical hardware.

## Security and limitations

The preview uses token authentication over unencrypted `ws://`; use only on
a trusted isolated LAN and do not forward its port. TLS and a real pairing
workflow are needed before untrusted-network deployment.

Hardware provisioning and network firewall configuration remain separate
steps. No strip protocol tests have been run on physical hardware.
