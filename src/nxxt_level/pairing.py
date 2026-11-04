"""Per-member pairing credentials and one-time invitation codes.

Only salted hashes are persisted. Raw pairing codes and member tokens are returned
once to the caller and must be delivered over a trusted local pairing flow.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
import time
from pathlib import Path
from typing import Optional


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class CredentialStore:
    def __init__(self, database_path: str) -> None:
        self.database_path = str(database_path)
        if self.database_path != ":memory:":
            Path(self.database_path).expanduser().parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS member_credentials (
                    member_id TEXT PRIMARY KEY,
                    token_hash TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    revoked_at INTEGER
                )
            """)
            db.execute("""
                CREATE TABLE IF NOT EXISTS pairing_invites (
                    code_hash TEXT PRIMARY KEY,
                    created_by TEXT NOT NULL,
                    expires_at INTEGER NOT NULL,
                    used_at INTEGER
                )
            """)

    def _connect(self):
        db = sqlite3.connect(self.database_path, timeout=10)
        db.execute("PRAGMA foreign_keys = ON")
        return db

    def create_invite(self, created_by: str, ttl_seconds: int = 300) -> str:
        if not created_by or not 30 <= ttl_seconds <= 900:
            raise ValueError("Invite creator is required and TTL must be 30–900 seconds")
        code = secrets.token_urlsafe(24)
        with self._connect() as db:
            db.execute(
                "INSERT INTO pairing_invites(code_hash, created_by, expires_at) VALUES (?, ?, ?)",
                (_digest(code), created_by, int(time.time()) + ttl_seconds),
            )
        return code

    def redeem_invite(self, code: str, member_id: str) -> str:
        if not code or not member_id:
            raise ValueError("Pairing code and member ID are required")
        token = secrets.token_urlsafe(48)
        now = int(time.time())
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT expires_at, used_at FROM pairing_invites WHERE code_hash = ?",
                (_digest(code),),
            ).fetchone()
            if row is None or row[1] is not None or row[0] < now:
                raise ValueError("Pairing invitation is invalid, expired or already used")
            existing = db.execute(
                "SELECT 1 FROM member_credentials WHERE member_id = ? AND revoked_at IS NULL",
                (member_id,),
            ).fetchone()
            if existing:
                raise ValueError("This member already has an active credential")
            db.execute(
                "UPDATE pairing_invites SET used_at = ? WHERE code_hash = ? AND used_at IS NULL",
                (now, _digest(code)),
            )
            db.execute(
                "INSERT INTO member_credentials(member_id, token_hash, created_at) VALUES (?, ?, ?)",
                (member_id, _digest(token), now),
            )
        return token

    def authenticate(self, member_id: str, token: str) -> bool:
        if not member_id or not token:
            return False
        with self._connect() as db:
            row = db.execute(
                "SELECT token_hash FROM member_credentials WHERE member_id = ? AND revoked_at IS NULL",
                (member_id,),
            ).fetchone()
        return bool(row and hmac.compare_digest(row[0], _digest(token)))

    def revoke(self, member_id: str) -> bool:
        with self._connect() as db:
            cursor = db.execute(
                "UPDATE member_credentials SET revoked_at = ? WHERE member_id = ? AND revoked_at IS NULL",
                (int(time.time()), member_id),
            )
            return cursor.rowcount == 1
