"""Nxxt Level desktop controller for paired computers and MTTL-W01 strips."""
from __future__ import annotations

import asyncio
import os
import sys

from PySide6.QtCore import QThread, Signal, QSettings
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFormLayout, QFrame, QGridLayout, QHBoxLayout,
    QInputDialog, QLabel, QLineEdit, QMainWindow, QMessageBox, QPushButton,
    QTabWidget, QVBoxLayout, QWidget,
)

from nxxt_level.sync.client import issue_command, pair_with_controller, watch_controller


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
            self.connection_state.emit("Disconnected: " + type(exc).__name__)


class CommandThread(QThread):
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, uri: str, member_id: str, token: str, payload: dict) -> None:
        super().__init__()
        self.uri, self.member_id, self.token, self.payload = uri, member_id, token, payload

    def run(self) -> None:
        try:
            result = asyncio.run(issue_command(
                self.uri, self.member_id, self.token, self.payload
            ))
            self.completed.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))


class PairThread(QThread):
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, uri: str, code: str, member_id: str,
                 display_name: str, platform: str, battery_monitoring: bool) -> None:
        super().__init__()
        capabilities = ["battery_monitoring"] if battery_monitoring else []
        self.args = (uri, code, member_id, display_name, platform, capabilities)

    def run(self) -> None:
        try:
            result = asyncio.run(pair_with_controller(*self.args))
            self.completed.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))


class OutletCard(QFrame):
    def __init__(self, channel: int, callback) -> None:
        super().__init__()
        self.channel = channel
        self.callback = callback
        self.setObjectName("outletCard")
        layout = QVBoxLayout(self)
        self.heading = QLabel("OUTLET " + str(channel))
        self.heading.setObjectName("outletHeading")
        self.status = QLabel("UNKNOWN")
        self.status.setObjectName("outletStatus")
        self.power = QLabel("— W")
        self.energy = QLabel("— kWh")
        self.button = QPushButton("Unavailable")
        self.button.clicked.connect(lambda: self.callback(self.channel))
        for item in (self.heading, self.status, self.power, self.energy, self.button):
            layout.addWidget(item)

    def update_reading(self, reading: dict, name: str, enabled: bool) -> None:
        self.heading.setText(name.upper())
        self.status.setText("ON" if reading.get("on") else "OFF")
        self.power.setText(f"{reading.get('power_w', 0):.2f} W")
        self.energy.setText(f"{reading.get('energy_kwh', 0):.3f} kWh")
        self.button.setText("Turn OFF" if reading.get("on") else "Turn ON")
        self.button.setEnabled(enabled)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Nxxt Level")
        self.resize(980, 700)
        self.devices: dict = {}
        self.groups: dict = {}
        self.worker = None
        self.command_worker = None
        self.pair_worker = None
        self.member_id = ""
        self.token = ""
        self.pending_command = False
        self.settings = QSettings("NxxtLevel", "NxxtLevel")

        body = QWidget()
        self.setCentralWidget(body)
        root = QVBoxLayout(body)
        title = QLabel("NXXT LEVEL")
        title.setObjectName("title")
        subtitle = QLabel("Your devices. Your outlets. One live control plane.")
        subtitle.setObjectName("subtitle")
        root.addWidget(title)
        root.addWidget(subtitle)

        self.tabs = QTabWidget()
        root.addWidget(self.tabs, 1)
        self.control_page = QWidget()
        self.setup_page = QWidget()
        self.tabs.addTab(self.control_page, "Realtime control")
        self.tabs.addTab(self.setup_page, "Devices & assignments")
        self._build_control_page()
        self._build_setup_page()

        self.setStyleSheet("""
            QMainWindow, QWidget { background: #111722; color: #eef3fb; }
            QLabel#title { font-size: 27px; font-weight: 800; color: #79baff; }
            QLabel#subtitle { color: #99a8be; margin-bottom: 10px; }
            QFrame#outletCard { background: #1d2939; border: 1px solid #35465c;
                                border-radius: 12px; padding: 12px; }
            QLabel#outletHeading { font-size: 12px; color: #8ca6c7; }
            QLabel#outletStatus { font-size: 22px; font-weight: bold; }
            QLineEdit, QPushButton, QComboBox { padding: 9px; border-radius: 7px;
                                                background: #27384d; }
            QPushButton:disabled { color: #77869a; }
            QTabWidget::pane { border: 1px solid #35465c; border-radius: 8px; }
            QTabBar::tab { padding: 10px 16px; }
        """)

    def _build_control_page(self) -> None:
        layout = QVBoxLayout(self.control_page)
        form = QFormLayout()
        self.endpoint = QLineEdit(os.environ.get("NXXT_SYNC_URL", "ws://127.0.0.1:10087"))
        saved_member = os.environ.get("NXXT_MEMBER_ID") or self.settings.value("member_id", "")
        saved_token = os.environ.get("NXXT_MEMBER_TOKEN", "")
        if not saved_token and saved_member:
            try:
                import keyring
                saved_token = keyring.get_password("NxxtLevel", saved_member) or ""
            except Exception:
                saved_token = ""
        self.member_field = QLineEdit(saved_member)
        self.token_field = QLineEdit(saved_token)
        self.token_field.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("Controller URL", self.endpoint)
        form.addRow("This computer's member ID", self.member_field)
        form.addRow("Member token", self.token_field)
        layout.addLayout(form)

        connection_row = QHBoxLayout()
        self.connect_button = QPushButton("Connect")
        self.connect_button.clicked.connect(self.connect_controller)
        self.connection = QLabel("Not connected")
        connection_row.addWidget(self.connect_button)
        connection_row.addWidget(self.connection, 1)
        layout.addLayout(connection_row)

        role_row = QHBoxLayout()
        self.role_label = QLabel("Role: not connected")
        self.role_button = QPushButton("Claim Sudo")
        self.role_button.clicked.connect(self.toggle_sudo)
        self.role_button.setEnabled(False)
        role_row.addWidget(self.role_label, 1)
        role_row.addWidget(self.role_button)
        layout.addLayout(role_row)

        strip_row = QHBoxLayout()
        strip_row.addWidget(QLabel("Power strip"))
        self.strip_picker = QComboBox()
        self.strip_picker.currentIndexChanged.connect(self.refresh_controls)
        strip_row.addWidget(self.strip_picker, 1)
        layout.addLayout(strip_row)

        self.summary = QLabel("Connect to a controller to view live telemetry.")
        layout.addWidget(self.summary)
        grid = QGridLayout()
        self.cards = {}
        for channel in range(1, 5):
            card = OutletCard(channel, self.toggle_outlet)
            self.cards[channel] = card
            grid.addWidget(card, (channel - 1) // 2, (channel - 1) % 2)
        layout.addLayout(grid)
        layout.addStretch()

    def _build_setup_page(self) -> None:
        layout = QVBoxLayout(self.setup_page)
        layout.addWidget(QLabel("Group and strip configuration"))
        self.group_summary = QLabel("Connect to load your group.")
        layout.addWidget(self.group_summary)
        row = QHBoxLayout()
        self.rename_strip_button = QPushButton("Rename strip")
        self.rename_strip_button.clicked.connect(self.rename_strip)
        self.rename_outlet_button = QPushButton("Rename outlet")
        self.rename_outlet_button.clicked.connect(self.rename_outlet)
        self.invite_button = QPushButton("Add another computer")
        self.invite_button.clicked.connect(self.create_invitation)
        self.pair_button = QPushButton("Pair this computer")
        self.pair_button.clicked.connect(self.pair_this_computer)
        self.rename_strip_button.setEnabled(False)
        self.rename_outlet_button.setEnabled(False)
        self.invite_button.setEnabled(False)
        row.addWidget(self.rename_strip_button)
        row.addWidget(self.rename_outlet_button)
        row.addWidget(self.invite_button)
        layout.addLayout(row)
        layout.addWidget(self.pair_button)
        layout.addWidget(QLabel("Assign a computer to its charger outlet"))
        self.member_picker = QComboBox()
        self.assignment_picker = QComboBox()
        assignment_row = QHBoxLayout()
        assignment_row.addWidget(self.member_picker, 1)
        assignment_row.addWidget(self.assignment_picker, 1)
        layout.addLayout(assignment_row)
        assignment_actions = QHBoxLayout()
        self.assign_button = QPushButton("Assign charger")
        self.assign_button.clicked.connect(self.assign_charger)
        self.unassign_button = QPushButton("Remove assignment")
        self.unassign_button.clicked.connect(self.unassign_charger)
        self.push_button = QPushButton("Toggle Sudo notifications")
        self.push_button.clicked.connect(self.toggle_push_notifications)
        for button in (self.assign_button, self.unassign_button, self.push_button):
            button.setEnabled(False)
            assignment_actions.addWidget(button)
        layout.addLayout(assignment_actions)
        layout.addWidget(QLabel(
            "Battery monitoring is optional per computer. Push notification delivery "
            "is not yet connected; this setting controls the future recipient preference."
        ))
        layout.addStretch()

    def connect_controller(self) -> None:
        if self.worker and self.worker.isRunning():
            return
        self.member_id = self.member_field.text().strip()
        self.token = self.token_field.text()
        if not self.member_id or len(self.token) < 32:
            self.connection.setText("Enter your member ID and pairing token")
            return
        self.worker = SyncThread(self.endpoint.text().strip(), self.member_id, self.token)
        self.worker.event_received.connect(self.handle_event)
        self.worker.connection_state.connect(self.connection.setText)
        self.worker.start()
        self.connect_button.setEnabled(False)

    def send_command(self, payload: dict) -> None:
        if self.pending_command:
            return
        if not self.member_id or not self.token:
            return
        self.pending_command = True
        self.connection.setText("Sending command…")
        self.command_worker = CommandThread(
            self.endpoint.text().strip(), self.member_id, self.token, payload
        )
        self.command_worker.completed.connect(self.command_completed)
        self.command_worker.failed.connect(self.command_failed)
        self.command_worker.start()

    def command_completed(self, result: object) -> None:
        self.pending_command = False
        if isinstance(result, dict) and result.get("pairing_code"):
            QMessageBox.information(
                self, "Pairing invitation",
                "Share this one-time code with the computer you want to add. "
                "It expires in five minutes and can be used once:\n\n"
                + result["pairing_code"],
            )
            self.connection.setText("Invitation created")
        else:
            self.connection.setText("Command confirmed")
        self.refresh_controls()

    def command_failed(self, error: str) -> None:
        self.pending_command = False
        self.connection.setText("Command rejected: " + error)
        self.refresh_controls()

    def selected_strip(self) -> tuple[str, dict]:
        strip_id = self.strip_picker.currentData()
        return strip_id, self.groups.get(strip_id, {})

    def current_device(self) -> dict:
        _, strip = self.selected_strip()
        mac = strip.get("device_mac")
        return self.devices.get(mac, {}) if mac else {}

    def handle_event(self, event: dict) -> None:
        if event.get("type") == "snapshot":
            state = event.get("state", {})
            self.devices = dict(state.get("devices", {}))
            self.groups = dict(state.get("groups", {}).get("home", {}).get("strips", {}))
            self.group_state = state.get("groups", {}).get("home", {})
        elif event.get("type") == "state_changed":
            if event.get("section") == "devices":
                self.devices[event["key"]] = event["value"]
            elif event.get("section") == "groups" and event.get("key") == "home":
                value = event["value"]
                self.groups = dict(value.get("strips", {}))
                self.group_state = value
        self.refresh_controls()

    def refresh_controls(self) -> None:
        group = getattr(self, "group_state", {})
        members = group.get("members", {})
        sudo_id = group.get("sudo_member_id")
        mine_is_sudo = sudo_id == self.member_id
        role_name = "Sudo" if mine_is_sudo else "Endpoint"
        self.role_label.setText(
            f"Role: {role_name}  •  Current Sudo: {members.get(sudo_id, {}).get('display_name', 'Vacant')}"
        )
        self.role_button.setText("Release Sudo" if mine_is_sudo else "Claim Sudo")
        self.role_button.setEnabled(bool(self.member_id) and not self.pending_command)
        old_id = self.strip_picker.currentData()
        self.strip_picker.blockSignals(True)
        self.strip_picker.clear()
        for strip_id, strip in self.groups.items():
            self.strip_picker.addItem(strip.get("display_name", strip_id), strip_id)
        index = self.strip_picker.findData(old_id)
        if index >= 0:
            self.strip_picker.setCurrentIndex(index)
        self.strip_picker.blockSignals(False)

        strip_id, strip = self.selected_strip()
        device = self.current_device()
        online = bool(device.get("online"))
        assigned = members.get(self.member_id, {}).get("assigned_outlets", {}).get(strip_id, [])
        for channel, card in self.cards.items():
            reading = device.get("outlets", {}).get(str(channel), {})
            name = strip.get("outlet_names", {}).get(str(channel),
                   strip.get("outlet_names", {}).get(channel, f"Outlet {channel}"))
            allowed = mine_is_sudo or channel in assigned
            card.update_reading(
                reading if reading and online else {},
                name,
                online and allowed and not self.pending_command,
            )
            if not online:
                card.status.setText("OFFLINE / UNKNOWN")
                card.power.setText("— W")
                card.energy.setText("— kWh")
        if device:
            self.summary.setText(
                f"{strip.get('display_name', 'Power strip')}  •  "
                f"{'ONLINE' if online else 'OFFLINE'}  •  "
                f"{device.get('total_power_w', 0):.2f} W total"
            )
        else:
            self.summary.setText("No bound physical strip is currently reporting.")
        self.group_summary.setText(
            f"{len(members)} paired computer(s)  •  {len(self.groups)} strip(s)  •  "
            f"Push notifications: {'enabled for Sudo' if group.get('push_notifications_enabled') else 'disabled'}"
        )
        self.rename_strip_button.setEnabled(mine_is_sudo and bool(strip_id))
        self.rename_outlet_button.setEnabled(mine_is_sudo and bool(strip_id))
        self.invite_button.setEnabled(mine_is_sudo and not self.pending_command)
        self.assign_button.setEnabled(mine_is_sudo and bool(members) and bool(self.groups) and not self.pending_command)
        self.unassign_button.setEnabled(mine_is_sudo and bool(members) and not self.pending_command)
        self.push_button.setEnabled(mine_is_sudo and not self.pending_command)
        self.member_picker.blockSignals(True)
        old_member = self.member_picker.currentData()
        self.member_picker.clear()
        for member_id, member in members.items():
            self.member_picker.addItem(member.get("display_name", member_id), member_id)
        member_index = self.member_picker.findData(old_member)
        if member_index >= 0:
            self.member_picker.setCurrentIndex(member_index)
        self.member_picker.blockSignals(False)
        self.assignment_picker.clear()
        for sid, item in self.groups.items():
            for ch in range(1, 5):
                outlet_name = item.get("outlet_names", {}).get(str(ch), f"Outlet {ch}")
                self.assignment_picker.addItem(
                    f"{item.get('display_name', sid)} · {outlet_name}", (sid, ch)
                )

    def assign_charger(self) -> None:
        member_id = self.member_picker.currentData()
        assignment = self.assignment_picker.currentData()
        if member_id and assignment:
            strip_id, channel = assignment
            self.send_command({
                "command": "assign_charger", "member_id": member_id,
                "strip_id": strip_id, "channel": channel,
            })

    def unassign_charger(self) -> None:
        member_id = self.member_picker.currentData()
        assignment = self.assignment_picker.currentData()
        if member_id and assignment:
            strip_id, _ = assignment
            self.send_command({
                "command": "unassign_charger", "member_id": member_id,
                "strip_id": strip_id,
            })

    def toggle_push_notifications(self) -> None:
        enabled = not bool(getattr(self, "group_state", {}).get("push_notifications_enabled", True))
        self.send_command({"command": "set_push_notifications", "enabled": enabled})

    def create_invitation(self) -> None:
        self.send_command({"command": "create_pairing_invite", "ttl_seconds": 300})

    def pair_this_computer(self) -> None:
        code, ok = QInputDialog.getText(self, "Pair computer", "One-time invitation code:")
        if not ok or not code.strip():
            return
        member_id, ok = QInputDialog.getText(self, "Pair computer", "Unique member ID:")
        if not ok or not member_id.strip():
            return
        display_name, ok = QInputDialog.getText(self, "Pair computer", "Computer display name:")
        if not ok or not display_name.strip():
            return
        platform, ok = QInputDialog.getItem(
            self, "Pair computer", "Operating system:",
            ["windows", "linux", "macos"], 0, False
        )
        if not ok:
            return
        battery = QMessageBox.question(
            self, "Optional battery monitoring",
            "Enable optional battery monitoring on this computer?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        ) == QMessageBox.StandardButton.Yes
        self.pair_button.setEnabled(False)
        self.pair_worker = PairThread(
            self.endpoint.text().strip(), code.strip(), member_id.strip(),
            display_name.strip(), platform, battery,
        )
        self.pair_worker.completed.connect(self.pair_completed)
        self.pair_worker.failed.connect(self.pair_failed)
        self.pair_worker.start()

    def pair_completed(self, result: object) -> None:
        self.pair_button.setEnabled(True)
        self.member_field.setText(result.get("member_id", ""))
        self.token_field.setText(result.get("token", ""))
        QMessageBox.information(
            self, "Computer paired",
            "This computer has been paired. Save its member token in a password manager. "
            "The token is shown only in this session. Connect when ready.",
        )

    def pair_failed(self, error: str) -> None:
        self.pair_button.setEnabled(True)
        QMessageBox.warning(self, "Pairing failed", error)

    def toggle_sudo(self) -> None:
        group = getattr(self, "group_state", {})
        if group.get("sudo_member_id") == self.member_id:
            self.send_command({"command": "release_sudo"})
        else:
            self.send_command({"command": "claim_sudo"})

    def toggle_outlet(self, channel: int) -> None:
        strip_id, _ = self.selected_strip()
        device = self.current_device()
        reading = device.get("outlets", {}).get(str(channel), {})
        self.send_command({
            "command": "set_outlet", "strip_id": strip_id,
            "channel": channel, "on": not bool(reading.get("on")),
        })

    def rename_strip(self) -> None:
        strip_id, strip = self.selected_strip()
        name, ok = QInputDialog.getText(
            self, "Rename strip", "Strip name:",
            text=strip.get("display_name", ""),
        )
        if ok and name.strip():
            self.send_command({"command": "rename_strip", "strip_id": strip_id, "name": name.strip()})

    def rename_outlet(self) -> None:
        strip_id, strip = self.selected_strip()
        channel, ok = QInputDialog.getInt(self, "Select outlet", "Outlet number:", 1, 1, 4)
        if not ok:
            return
        current = strip.get("outlet_names", {}).get(str(channel), f"Outlet {channel}")
        name, ok = QInputDialog.getText(self, "Rename outlet", "Outlet name:", text=current)
        if ok and name.strip():
            self.send_command({
                "command": "rename_outlet", "strip_id": strip_id,
                "channel": channel, "name": name.strip(),
            })

    def closeEvent(self, event) -> None:
        if self.worker and self.worker.isRunning():
            self.worker.requestInterruption()
        super().closeEvent(event)


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Nxxt Level")
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
