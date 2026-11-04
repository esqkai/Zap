"""Nxxt Level cross-platform desktop monitor (PySide6).

Read-only first release: relay controls require verified controller commands.
"""
from __future__ import annotations

import asyncio
import os
import sys

from PySide6.QtCore import QThread, Signal, Qt
from PySide6.QtWidgets import (
    QApplication, QFormLayout, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QLineEdit, QMainWindow, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from nxxt_level.sync.client import watch_controller


class SyncThread(QThread):
    event_received = Signal(object)
    connection_state = Signal(str)

    def __init__(self, uri: str, member_id: str, token: str) -> None:
        super().__init__()
        self.uri, self.member_id, self.token = uri, member_id, token

    def run(self) -> None:
        async def listen() -> None:
            self.connection_state.emit("Connecting…")
            async for event in watch_controller(self.uri, self.member_id, self.token):
                if self.isInterruptionRequested():
                    break
                self.connection_state.emit("Connected")
                self.event_received.emit(event)

        try:
            asyncio.run(listen())
        except Exception as exc:
            self.connection_state.emit(f"Disconnected: {type(exc).__name__}")


class OutletCard(QFrame):
    def __init__(self, channel: int) -> None:
        super().__init__()
        self.setObjectName("outletCard")
        layout = QVBoxLayout(self)
        heading = QLabel(f"OUTLET {channel}")
        heading.setObjectName("outletHeading")
        self.status = QLabel("UNKNOWN")
        self.status.setObjectName("outletStatus")
        self.power = QLabel("— W")
        self.energy = QLabel("— kWh")
        self.button = QPushButton("Control unavailable")
        self.button.setEnabled(False)
        self.button.setToolTip("Relay commands will be enabled after hardware validation.")
        for item in (heading, self.status, self.power, self.energy, self.button):
            layout.addWidget(item)

    def update_reading(self, reading: dict) -> None:
        self.status.setText("ON" if reading.get("on") else "OFF")
        self.power.setText(f"{reading.get('power_w', 0):.2f} W")
        self.energy.setText(f"{reading.get('energy_kwh', 0):.3f} kWh")


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Nxxt Level")
        self.resize(850, 590)
        self.devices = {}
        self.worker = None
        body = QWidget()
        self.setCentralWidget(body)
        layout = QVBoxLayout(body)
        title = QLabel("NXXT LEVEL")
        title.setObjectName("title")
        subtitle = QLabel("Cross-platform smart power control")
        subtitle.setObjectName("subtitle")
        layout.addWidget(title)
        layout.addWidget(subtitle)
        form = QFormLayout()
        self.endpoint = QLineEdit(os.environ.get("NXXT_SYNC_URL", "ws://127.0.0.1:10087"))
        self.member_id = QLineEdit(os.environ.get("NXXT_MEMBER_ID", ""))
        self.secret = QLineEdit(os.environ.get("NXXT_MEMBER_TOKEN", ""))
        self.secret.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("Controller URL", self.endpoint)
        form.addRow("Member ID", self.member_id)
        form.addRow("Member token", self.secret)
        layout.addLayout(form)
        row = QHBoxLayout()
        self.connect_button = QPushButton("Connect")
        self.connect_button.clicked.connect(self.connect_controller)
        self.connection = QLabel("Not connected")
        row.addWidget(self.connect_button)
        row.addWidget(self.connection, 1)
        layout.addLayout(row)
        self.summary = QLabel("No device state received")
        layout.addWidget(self.summary)
        grid = QGridLayout()
        self.cards = {}
        for channel in range(1, 5):
            card = OutletCard(channel)
            self.cards[channel] = card
            grid.addWidget(card, (channel - 1) // 2, (channel - 1) % 2)
        layout.addLayout(grid)
        layout.addStretch()
        self.setStyleSheet("""
            QMainWindow, QWidget { background: #111722; color: #eef3fb; }
            QLabel#title { font-size: 27px; font-weight: 800; color: #79baff; }
            QLabel#subtitle { color: #99a8be; margin-bottom: 10px; }
            QFrame#outletCard { background: #1d2939; border: 1px solid #35465c;
                                border-radius: 12px; padding: 12px; }
            QLabel#outletHeading { font-size: 13px; color: #8ca6c7; }
            QLabel#outletStatus { font-size: 22px; font-weight: bold; }
            QLineEdit, QPushButton { padding: 9px; border-radius: 7px;
                                    background: #27384d; }
            QPushButton:disabled { color: #77869a; }
        """)

    def connect_controller(self) -> None:
        if self.worker and self.worker.isRunning():
            return
        token = self.secret.text()
        member_id = self.member_id.text().strip()
        if not member_id or len(token) < 32:
            self.connection.setText("Enter your member ID and pairing token")
            return
        self.worker = SyncThread(self.endpoint.text().strip(), member_id, token)
        self.worker.event_received.connect(self.handle_event)
        self.worker.connection_state.connect(self.connection.setText)
        self.worker.start()
        self.connect_button.setEnabled(False)

    def handle_event(self, event: dict) -> None:
        if event.get("type") == "snapshot":
            self.devices = dict(event.get("state", {}).get("devices", {}))
        elif event.get("type") == "state_changed" and event.get("section") == "devices":
            self.devices[event["key"]] = event["value"]
        if not self.devices:
            self.summary.setText("Waiting for a strip to connect…")
            return
        device = next(iter(self.devices.values()))
        online = bool(device.get("online"))
        self.summary.setText(
            f"{device.get('model', 'Smart strip')}  •  "
            f"{'ONLINE' if online else 'OFFLINE'}  •  "
            f"{device.get('total_power_w', 0):.2f} W total  •  "
            f"Revision {event.get('revision', '?')}"
        )
        for channel, card in self.cards.items():
            reading = device.get("outlets", {}).get(str(channel))
            if reading and online:
                card.update_reading(reading)
            else:
                card.status.setText("OFFLINE / STALE")
                card.power.setText("— W")
                card.energy.setText("— kWh")

    def closeEvent(self, event) -> None:
        if self.worker and self.worker.isRunning():
            self.worker.requestInterruption()
            # Async WebSocket receive may take time; avoid blocking GUI shutdown.
        super().closeEvent(event)


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Nxxt Level")
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
