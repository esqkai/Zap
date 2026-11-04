"""Command Line Interface for Zap - MTTL-W01 Desktop Control Center by Nxxt Level."""

from __future__ import annotations

import argparse
import asyncio
import getpass
import logging
import os
import socket
import sys
from typing import List, Optional

from nxxt_level import __app_name__, __vendor__, __version__
from nxxt_level.device.protocol import (
    DEFAULT_DEVICE_PORT,
    DEFAULT_SETUP_HOST,
    DEFAULT_SETUP_PORT,
)
from nxxt_level.device.provisioning import (
    ProvisioningError,
    provision_strip,
    validate_provision_params,
)
from nxxt_level.device.server import StripDeviceServer
from nxxt_level.device.state import PowerStripState
from nxxt_level.sync.hub import StateHub
from nxxt_level.sync.serialization import serialize_strip
from nxxt_level.group_store import GroupStore
from nxxt_level.group_service import PersistentGroupService
from nxxt_level.pairing import CredentialStore
from nxxt_level.sync.commands import GroupCommandHandler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("zap")


def get_candidate_ipv4s() -> List[str]:
    """Retrieve non-loopback local IPv4 addresses on this machine."""
    try:
        _, _, ips = socket.gethostbyname_ex(socket.gethostname())
    except OSError:
        ips = []
    candidates = [
        ip for ip in ips
        if not ip.startswith(("127.", "169.254.")) and ":" not in ip
    ]
    return candidates


def cmd_provision(args: argparse.Namespace) -> int:
    """Run device provisioning against the strip's SoftAP setup service."""
    print("=" * 66)
    print(f" {__app_name__} -- MTTL-W01 Strip Provisioning Tool ({__vendor__})")
    print("=" * 66)
    print("Run this tool while connected directly to the strip's Wi-Fi network:")
    print("  Setup SSID: TONLY_TAP_<7_HEX>   (e.g., TONLY_TAP_5602BCC)")
    print("  Setup Pass: LGU_<7_HEX>         (e.g., LGU_5602BCC)")
    print("  Strip Host: 192.168.1.1:30300")
    print("-" * 66)

    # 1. Target Controller IP
    server_ip = args.server_ip
    if not server_ip:
        candidates = get_candidate_ipv4s()
        prompt_suffix = f" [Detected on this PC: {', '.join(candidates)}]" if candidates else ""
        try:
            server_ip = input(f"Enter the LAN IPv4 address of the PC running Zap{prompt_suffix}: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nProvisioning cancelled.")
            return 1

    # 2. Wi-Fi SSID
    ssid = args.ssid
    if not ssid:
        try:
            ssid = input("Enter your 2.4 GHz home Wi-Fi SSID: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nProvisioning cancelled.")
            return 1

    # 3. Wi-Fi Password (secure input)
    password = args.password
    if not password:
        try:
            password = getpass.getpass("Enter your 2.4 GHz home Wi-Fi password (hidden): ")
        except (KeyboardInterrupt, EOFError):
            print("\nProvisioning cancelled.")
            return 1

    # Validate parameters locally
    try:
        validate_provision_params(ssid, password, server_ip)
    except ValueError as exc:
        print(f"\n[Validation Error] {exc}", file=sys.stderr)
        return 1

    # Display execution plan
    print("\nPROVISIONING PLAN:")
    print(f"  Strip Setup Endpoint : {args.host}:{args.port}")
    print(f"  Target Controller IP : {server_ip}")
    print(f"  Target Wi-Fi SSID    : {ssid}")
    print(f"  Password Length      : {len(password)} characters")
    print(f"  Dry Run Mode         : {'ENABLED (no commands will be sent)' if args.dry_run else 'DISABLED'}")
    print("-" * 66)

    if not args.yes and not args.dry_run:
        try:
            confirm = input("Confirm and proceed with provisioning? [y/N]: ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            print("\nProvisioning aborted.")
            return 1
        if confirm not in ("y", "yes"):
            print("Provisioning cancelled by user.")
            return 0

    print("\nExecuting provisioning...")
    try:
        result = provision_strip(
            ssid=ssid,
            password=password,
            server_ip=server_ip,
            host=args.host,
            port=args.port,
            dry_run=args.dry_run,
        )
        print("\nProvisioning completed successfully!")
        if args.dry_run:
            print("  Dry-run completed. All parameters verified.")
        else:
            print(f"  Controller IP Acknowledged: {result.get('ip_response', 'OK')}")
            print(f"  Wi-Fi Config Acknowledged: {result.get('connect_response', 'OK')}")
            print("\nNext steps:")
            print(f"  1. Reconnect this machine to your normal LAN / Wi-Fi.")
            print(f"  2. On the controller PC ({server_ip}), launch the Zap server:")
            print(f"     zap serve --port {DEFAULT_DEVICE_PORT}")
            print("  3. The strip will connect outbound to the controller shortly.")
        return 0
    except ProvisioningError as exc:
        print(f"\n[Provisioning Error]\n{exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"\n[Unexpected Error] {exc}", file=sys.stderr)
        return 3


async def _run_server(args: argparse.Namespace) -> int:
    """Run async device server with live terminal monitoring."""
    hub = StateHub()
    state_db = args.state_db or _default_state_database()
    group_store = GroupStore(state_db)
    credential_store = CredentialStore(state_db)
    group_service = await PersistentGroupService.open(args.group_id, group_store, hub)
    logger.info("Loaded Nxxt group '%s' from %s", args.group_id, state_db)
    pending_updates = set()

    def on_state_updated(state: PowerStripState) -> None:
        print("\n" + state.format_terminal_summary())
        # Snapshot immediately: the mutable state may change before the task runs.
        snapshot = serialize_strip(state)
        task = asyncio.create_task(hub.publish("devices", state.mac, snapshot))
        pending_updates.add(task)
        task.add_done_callback(pending_updates.discard)

    server = StripDeviceServer(
        bind_host=args.host,
        port=args.port,
        poll_interval=args.poll_interval,
        on_state_updated=on_state_updated,
    )

    print("=" * 66)
    print(f" {__app_name__} -- Device Engine v{__version__} ({__vendor__})")
    print("=" * 66)
    print(f" Listening on TCP {args.host}:{args.port}")
    candidates = get_candidate_ipv4s()
    if candidates:
        print(f" Local IPv4 addresses on this PC: {', '.join(candidates)}")
    print(f" Strip will connect here after being provisioned.")
    print(" Press Ctrl+C to terminate.")
    print("-" * 66)

    sync_server = None
    if args.sync:
        from nxxt_level.sync.websocket_server import serve_sync
        command_handler = GroupCommandHandler(group_service, server)
        sync_server = await serve_sync(
            hub, credential_store, args.sync_host, args.sync_port,
            command_handler, group_service
        )
        logger.info("Authenticated sync and command server on %s:%s", args.sync_host, args.sync_port)

    try:
        await server.start()
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        pass
    finally:
        await server.stop()
        if pending_updates:
            await asyncio.gather(*pending_updates, return_exceptions=True)
        if sync_server is not None:
            sync_server.close()
            await sync_server.wait_closed()
    return 0



def _default_state_database() -> str:
    """Return a per-user writable state database path on Windows/Linux."""
    if os.name == "nt":
        root = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        directory = os.path.join(root, "NxxtLevel")
    else:
        root = os.environ.get("XDG_STATE_HOME") or os.path.join(
            os.path.expanduser("~"), ".local", "state"
        )
        directory = os.path.join(root, "nxxt-level")
    os.makedirs(directory, exist_ok=True)
    return os.path.join(directory, "groups.sqlite3")


def cmd_serve(args: argparse.Namespace) -> int:
    """Entry point for `zap serve`."""
    try:
        return asyncio.run(_run_server(args))
    except KeyboardInterrupt:
        print("\nServer terminated by user.")
        return 0


def build_parser() -> argparse.ArgumentParser:
    """Build root CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="zap",
        description=f"{__app_name__} - MTTL-W01 Smart Strip Controller by {__vendor__}",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"{__app_name__} {__version__} ({__vendor__})",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Command: serve
    serve_parser = subparsers.add_parser("serve", help="Run the TCP device controller engine")
    serve_parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Host interface to bind the TCP server (default: 0.0.0.0)",
    )
    serve_parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_DEVICE_PORT,
        help=f"TCP port for the strip connection (default: {DEFAULT_DEVICE_PORT})",
    )
    serve_parser.add_argument(
        "--poll-interval",
        type=float,
        default=5.0,
        help="Interval in seconds between telemetry polling queries (default: 5.0)",
    )

    serve_parser.add_argument("--group-id", default="home", help="Persistent Nxxt group identifier (default: home)")
    serve_parser.add_argument("--state-db", help="SQLite state database path (default: OS user data directory)")
    serve_parser.add_argument("--sync", action="store_true",
                              help="Enable authenticated live synchronization and allow-listed commands")
    serve_parser.add_argument("--sync-host", default="127.0.0.1",
                              help="Sync interface (explicitly set LAN IP for remote clients)")
    serve_parser.add_argument("--sync-port", type=int, default=10087)

    # Command: provision
    prov_parser = subparsers.add_parser(
        "provision",
        help="Provision an MTTL-W01 strip over its setup Wi-Fi (SoftAP)",
    )
    prov_parser.add_argument(
        "--server-ip",
        help="IPv4 address of the controller PC that the strip should dial",
    )
    prov_parser.add_argument(
        "--ssid",
        help="2.4 GHz Wi-Fi network SSID for the strip to join",
    )
    prov_parser.add_argument(
        "--password",
        help="Wi-Fi network password (if omitted, prompts securely without echoing)",
    )
    prov_parser.add_argument(
        "--host",
        default=DEFAULT_SETUP_HOST,
        help=f"Strip setup SoftAP IP address (default: {DEFAULT_SETUP_HOST})",
    )
    prov_parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_SETUP_PORT,
        help=f"Strip setup TCP port (default: {DEFAULT_SETUP_PORT})",
    )
    prov_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate parameters and display execution plan without transmitting commands",
    )
    prov_parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Bypass interactive confirmation prompt",
    )

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    """CLI main entry point."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "serve":
        return cmd_serve(args)
    elif args.command == "provision":
        return cmd_provision(args)
    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    sys.exit(main())
