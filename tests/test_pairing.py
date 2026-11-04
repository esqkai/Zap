import tempfile
import unittest
from pathlib import Path

from nxxt_level.pairing import CredentialStore


class TestCredentialStore(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = CredentialStore(str(Path(self.temp.name) / "auth.sqlite3"))

    def tearDown(self):
        self.temp.cleanup()

    def test_invite_can_be_redeemed_once_for_unique_member(self):
        invite = self.store.create_invite("sudo-member")
        token = self.store.redeem_invite(invite, "laptop-1")
        self.assertTrue(self.store.authenticate("laptop-1", token))
        with self.assertRaises(ValueError):
            self.store.redeem_invite(invite, "laptop-2")

    def test_wrong_member_or_token_does_not_authenticate(self):
        invite = self.store.create_invite("sudo-member")
        token = self.store.redeem_invite(invite, "laptop-1")
        self.assertFalse(self.store.authenticate("other-member", token))
        self.assertFalse(self.store.authenticate("laptop-1", "wrong-token"))

    def test_revocation_is_immediate_and_idempotent(self):
        invite = self.store.create_invite("sudo-member")
        token = self.store.redeem_invite(invite, "laptop-1")
        self.assertTrue(self.store.revoke("laptop-1"))
        self.assertFalse(self.store.authenticate("laptop-1", token))
        self.assertFalse(self.store.revoke("laptop-1"))

    def test_member_cannot_redeem_second_active_credential(self):
        first = self.store.create_invite("sudo-member")
        self.store.redeem_invite(first, "laptop-1")
        second = self.store.create_invite("sudo-member")
        with self.assertRaises(ValueError):
            self.store.redeem_invite(second, "laptop-1")

    def test_invite_expiration_is_enforced(self):
        invite = self.store.create_invite("sudo-member", ttl_seconds=30)
        with self.store._connect() as db:
            db.execute(
                "UPDATE pairing_invites SET expires_at = 0 WHERE code_hash = ?",
                (__import__("hashlib").sha256(invite.encode()).hexdigest(),),
            )
        with self.assertRaises(ValueError):
            self.store.redeem_invite(invite, "laptop-1")

    def test_database_contains_hashes_not_raw_secrets(self):
        invite = self.store.create_invite("sudo-member")
        token = self.store.redeem_invite(invite, "laptop-1")
        with self.store._connect() as db:
            invite_hash = db.execute("SELECT code_hash FROM pairing_invites").fetchone()[0]
            token_hash = db.execute("SELECT token_hash FROM member_credentials").fetchone()[0]
        self.assertNotEqual(invite_hash, invite)
        self.assertNotEqual(token_hash, token)
