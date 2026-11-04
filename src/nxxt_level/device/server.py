"""Asynchronous TCP Device Server for MTTL-W01 smart power strips."""

from __future__ import annotations

import asyncio
import logging
from typing import Callable, Dict, List, Optional

from nxxt_level.device.protocol import (
    DEFAULT_DEVICE_PORT,
    BootInfo,
    ButtonEvent,
    OutletAck,
    OutletReading,
    PowerReport,
    SignalReport,
    build_getinfo_all,
    build_outlet_command,
    build_rssi_query,
    build_voltage_query,
    clean_raw_line,
    parse_line,
)
from nxxt_level.device.state import PowerStripState

logger = logging.getLogger(__name__)


class StripSession:
    """Manages an active TCP connection session with a physical MTTL-W01 power strip."""

    def __init__(
        self,
        peer_ip: str,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        state: Optional[PowerStripState] = None,
        on_state_updated: Optional[Callable[[PowerStripState], None]] = None,
        on_button_event: Optional[Callable[[ButtonEvent, PowerStripState], None]] = None,
    ) -> None:
        self.peer_ip = peer_ip
        self.reader = reader
        self.writer = writer
        self.state = state
        self.on_state_updated = on_state_updated
        self.on_button_event = on_button_event
        self._cmd_lock = asyncio.Lock()
        self._telemetry_received_event = asyncio.Event()
        self.last_sent: str = ""
        self.last_received: str = ""

    @property
    def is_active(self) -> bool:
        """True if the socket writer is not closing and state is online."""
        return not self.writer.is_closing() and (self.state.is_online if self.state else False)

    async def send_raw(self, cmd_bytes: bytes) -> None:
        """Send raw framed bytes to the strip."""
        self.last_sent = cmd_bytes.decode("ascii", errors="replace").strip()
        self.writer.write(cmd_bytes)
        await self.writer.drain()

    async def query_telemetry(self, timeout: float = 4.0) -> bool:
        """Query full outlet state and electrical telemetry."""
        async with self._cmd_lock:
            self._telemetry_received_event.clear()
            await self.send_raw(build_getinfo_all())
            try:
                await asyncio.wait_for(self._telemetry_received_event.wait(), timeout=timeout)
                return True
            except asyncio.TimeoutError:
                logger.warning("Telemetry query timed out for %s", self.peer_ip)
                return False

    async def query_diagnostics(self) -> None:
        """Query diagnostic measurements (line voltage and Wi-Fi RSSI)."""
        async with self._cmd_lock:
            await self.send_raw(build_voltage_query())
            await self.send_raw(build_rssi_query())

    async def set_outlet(self, channel: int, on: bool, settle_delay: float = 0.3) -> bool:
        """Command an individual outlet (1-4) ON or OFF and refresh state."""
        if channel not in (1, 2, 3, 4):
            raise ValueError(f"Invalid outlet channel: {channel} (must be 1-4)")

        async with self._cmd_lock:
            await self.send_raw(build_outlet_command(channel, on))
            if settle_delay > 0:
                await asyncio.sleep(settle_delay)
            self._telemetry_received_event.clear()
            await self.send_raw(build_getinfo_all())
            try:
                await asyncio.wait_for(self._telemetry_received_event.wait(), timeout=4.0)
                # A telemetry response is not enough: verify the requested relay state.
                return bool(self.state and self.state.outlets[channel].is_on == on)
            except asyncio.TimeoutError:
                return False

    async def set_all_outlets(self, on: bool, settle_delay: float = 0.3) -> bool:
        """Sequential command to energize or de-energize all 4 outlets."""
        async with self._cmd_lock:
            for ch in (1, 2, 3, 4):
                await self.send_raw(build_outlet_command(ch, on))
            if settle_delay > 0:
                await asyncio.sleep(settle_delay)
            self._telemetry_received_event.clear()
            await self.send_raw(build_getinfo_all())
            try:
                await asyncio.wait_for(self._telemetry_received_event.wait(), timeout=4.0)
                return True
            except asyncio.TimeoutError:
                return False

    def close(self) -> None:
        """Close connection socket."""
        if not self.writer.is_closing():
            self.writer.close()


class StripDeviceServer:
    """TCP server managing incoming connections from MTTL-W01 strips."""

    def __init__(
        self,
        bind_host: str = "0.0.0.0",
        port: int = DEFAULT_DEVICE_PORT,
        poll_interval: float = 5.0,
        diag_poll_frequency: int = 3,
        on_state_updated: Optional[Callable[[PowerStripState], None]] = None,
        on_button_event: Optional[Callable[[ButtonEvent, PowerStripState], None]] = None,
    ) -> None:
        self.bind_host = bind_host
        self.port = port
        self.poll_interval = poll_interval
        self.diag_poll_frequency = diag_poll_frequency
        self.on_state_updated = on_state_updated
        self.on_button_event = on_button_event

        self.devices: Dict[str, PowerStripState] = {}
        self.sessions: Dict[str, StripSession] = {}
        self._server: Optional[asyncio.Server] = None
        self._poll_task: Optional[asyncio.Task] = None

    def get_session(self, mac: str) -> Optional[StripSession]:
        """Retrieve active session by device MAC."""
        return self.sessions.get(mac.upper())

    def get_any_active_session(self) -> Optional[StripSession]:
        """Retrieve the first active strip session available."""
        for s in self.sessions.values():
            if s.is_active:
                return s
        return None

    async def start(self) -> None:
        """Start TCP listener and background polling loop."""
        self._server = await asyncio.start_server(
            self._handle_client_connection,
            self.bind_host,
            self.port,
        )
        logger.info("Zap device engine listening on %s:%d", self.bind_host, self.port)
        self._poll_task = asyncio.create_task(self._background_poll_loop())

    async def stop(self) -> None:
        """Stop TCP listener and close all active sessions."""
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass

        for session in list(self.sessions.values()):
            session.close()

        if self._server:
            self._server.close()
            await self._server.wait_closed()
        logger.info("Zap device engine stopped")

    async def _handle_client_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        peer = writer.get_extra_info("peername")
        peer_ip = peer[0] if peer else "unknown"
        logger.info("Incoming connection from %s", peer_ip)

        session = StripSession(
            peer_ip=peer_ip,
            reader=reader,
            writer=writer,
            on_state_updated=self.on_state_updated,
            on_button_event=self.on_button_event,
        )

        try:
            while True:
                raw_bytes = await reader.readline()
                if not raw_bytes:
                    break
                if len(raw_bytes) > 8192:
                    logger.warning("Line exceeds maximum length from %s, dropping frame", peer_ip)
                    continue

                line_str = clean_raw_line(raw_bytes)
                session.last_received = line_str

                msg = parse_line(line_str)
                if msg is None:
                    continue

                if isinstance(msg, BootInfo):
                    mac = msg.primary_mac
                    state = self.devices.get(mac)
                    if not state:
                        state = PowerStripState(mac=mac)
                        self.devices[mac] = state
                    state.apply_bootinfo(msg, peer_ip)
                    session.state = state

                    # Handle session re-binding / clean reconnection
                    old_session = self.sessions.get(mac)
                    if old_session and old_session is not session:
                        logger.info("Replacing previous stale session for MAC %s", mac)
                        old_session.close()
                    self.sessions[mac] = session

                    if self.on_state_updated:
                        self.on_state_updated(state)

                    # Solicit initial state immediately
                    asyncio.create_task(session.query_telemetry())
                    asyncio.create_task(session.query_diagnostics())

                elif isinstance(msg, list):  # List of OutletReading
                    if session.state:
                        session.state.apply_readings(msg)
                        session._telemetry_received_event.set()
                        if self.on_state_updated:
                            self.on_state_updated(session.state)

                elif isinstance(msg, PowerReport):
                    if session.state:
                        session.state.apply_power_report(msg)
                        if self.on_state_updated:
                            self.on_state_updated(session.state)

                elif isinstance(msg, SignalReport):
                    if session.state:
                        session.state.apply_signal_report(msg)
                        if self.on_state_updated:
                            self.on_state_updated(session.state)

                elif isinstance(msg, ButtonEvent):
                    if session.state:
                        session.state.apply_button_event(msg)
                        if self.on_button_event:
                            self.on_button_event(msg, session.state)
                        if self.on_state_updated:
                            self.on_state_updated(session.state)

                elif isinstance(msg, OutletAck):
                    if session.state:
                        session.state.apply_outlet_ack(msg)
                        if self.on_state_updated:
                            self.on_state_updated(session.state)

        except (ConnectionResetError, BrokenPipeError, asyncio.IncompleteReadError):
            logger.info("Connection closed by peer %s", peer_ip)
        except Exception as exc:
            logger.error("Error during session with %s: %s", peer_ip, exc, exc_info=True)
        finally:
            if session.state:
                mac = session.state.mac
                if self.sessions.get(mac) is session:
                    session.state.is_online = False
                    self.sessions.pop(mac, None)
                    logger.info("Device %s marked offline", mac)
                    if self.on_state_updated:
                        self.on_state_updated(session.state)
            session.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    async def _background_poll_loop(self) -> None:
        cycle_count = 0
        while True:
            try:
                await asyncio.sleep(self.poll_interval)
                cycle_count += 1
                for session in list(self.sessions.values()):
                    if session.is_active:
                        await session.query_telemetry()
                        if cycle_count % self.diag_poll_frequency == 0:
                            await session.query_diagnostics()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Error in background telemetry polling: %s", exc)
