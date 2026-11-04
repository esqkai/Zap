"""SQLite persistence for Nxxt group configuration.

Stores group metadata, member capabilities/assignments, strip labels and Sudo
ownership. Does not store Wi-Fi credentials, pairing tokens, or other secrets.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Optional

from nxxt_level.group import GroupError, GroupRegistry, Member, Strip


class GroupStore:
    """Small transactional SQLite store for a single local Nxxt group."""

    def __init__(self, database_path: str) -> None:
        self.database_path = str(database_path)
        if self.database_path != ":memory:":
            Path(self.database_path).expanduser().parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as db:
            db.execute("PRAGMA journal_mode = WAL")
            db.execute("""
                CREATE TABLE IF NOT EXISTS nxxt_groups (
                    group_id TEXT PRIMARY KEY,
                    revision INTEGER NOT NULL,
                    sudo_member_id TEXT,
                    push_notifications_enabled INTEGER NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
            db.execute("""
                CREATE TABLE IF NOT EXISTS nxxt_group_state (
                    group_id TEXT PRIMARY KEY REFERENCES nxxt_groups(group_id)
                        ON DELETE CASCADE,
                    payload TEXT NOT NULL
                )
            """)

    def save(self, group: GroupRegistry) -> None:
        """Atomically replace a group's persisted configuration."""
        payload = {
            "members": [
                {
                    "member_id": m.member_id,
                    "display_name": m.display_name,
                    "platform": m.platform,
                    "capabilities": sorted(m.capabilities),
                    "online": m.online,
                    "assigned_outlets": {
                        strip_id: sorted(channels)
                        for strip_id, channels in m.assigned_outlets.items()
                    },
                    "charger_assignments": dict(m.charger_assignments),
                }
                for m in group.members.values()
            ],
            "strips": [
                {
                    "strip_id": s.strip_id,
                    "display_name": s.display_name,
                    "outlet_names": {str(ch): name for ch, name in s.outlet_names.items()},
                }
                for s in group.strips.values()
            ],
        }
        encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("""
                INSERT INTO nxxt_groups
                    (group_id, revision, sudo_member_id, push_notifications_enabled)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(group_id) DO UPDATE SET
                    revision=excluded.revision,
                    sudo_member_id=excluded.sudo_member_id,
                    push_notifications_enabled=excluded.push_notifications_enabled,
                    updated_at=CURRENT_TIMESTAMP
            """, (group.group_id, group.revision, group.sudo_member_id,
                  int(group.push_notifications_enabled)))
            db.execute("""
                INSERT INTO nxxt_group_state (group_id, payload) VALUES (?, ?)
                ON CONFLICT(group_id) DO UPDATE SET payload=excluded.payload
            """, (group.group_id, encoded))

    def load(self, group_id: str) -> Optional[GroupRegistry]:
        """Load a group or return None when it has not been saved."""
        with self._connect() as db:
            row = db.execute("""
                SELECT g.revision, g.sudo_member_id, g.push_notifications_enabled,
                       s.payload
                FROM nxxt_groups AS g
                JOIN nxxt_group_state AS s USING (group_id)
                WHERE g.group_id = ?
            """, (group_id,)).fetchone()
        if row is None:
            return None
        payload = json.loads(row["payload"])
        group = GroupRegistry(group_id)
        for item in payload["members"]:
            member = Member(
                member_id=item["member_id"],
                display_name=item["display_name"],
                platform=item["platform"],
                capabilities=set(item["capabilities"]),
                # Presence is ephemeral; every installation must rejoin after restart.
                online=False,
                assigned_outlets={
                    key: set(value) for key, value in item["assigned_outlets"].items()
                },
                charger_assignments={
                    key: int(value) for key, value in item["charger_assignments"].items()
                },
            )
            group.add_member(member)
        for item in payload["strips"]:
            names = {int(ch): name for ch, name in item["outlet_names"].items()}
            if set(names) != {1, 2, 3, 4}:
                raise GroupError("Persisted strip must contain exactly four outlet names")
            group.add_strip(Strip(item["strip_id"], item["display_name"], names))
        sudo = row["sudo_member_id"]
        if sudo is not None and sudo not in group.members:
            raise GroupError("Persisted Sudo member does not exist")
        # Sudo is an active-session role, never silently restored after restart.
        # The previous identity remains registered but must manually claim again.
        group.sudo_member_id = None
        group.push_notifications_enabled = bool(row["push_notifications_enabled"])
        group.revision = int(row["revision"])
        return group

    def delete(self, group_id: str) -> bool:
        with self._connect() as db:
            cursor = db.execute("DELETE FROM nxxt_groups WHERE group_id = ?", (group_id,))
            return cursor.rowcount > 0
