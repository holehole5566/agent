"""DM policy — control who can talk to the agent."""

import json
import logging
import secrets
from pathlib import Path

from config import WORKDIR

log = logging.getLogger("dm_policy")

ALLOWLIST_FILE = WORKDIR / ".dm_allowlist.json"


class DMPolicy:
    def __init__(self, mode="open", allowlist=None, pairing_code=""):
        self.mode = mode
        # Auto-generate pairing code if mode is pairing and no code given
        if mode == "pairing" and not pairing_code:
            pairing_code = secrets.token_hex(4)  # 8-char hex code
        self.pairing_code = pairing_code
        # Load persistent allowlist from disk, merge with config
        self.allowlist = set(allowlist or [])
        self._load_allowlist()

    def _load_allowlist(self):
        if ALLOWLIST_FILE.exists():
            try:
                saved = json.loads(ALLOWLIST_FILE.read_text(encoding="utf-8"))
                self.allowlist.update(saved)
            except Exception:
                pass

    def _save_allowlist(self):
        ALLOWLIST_FILE.write_text(
            json.dumps(sorted(self.allowlist), indent=2), encoding="utf-8"
        )

    def check(self, user_id: str, text: str = "") -> tuple:
        """Check if a user is allowed to send messages.

        Returns (allowed: bool, reply: str).
        If not allowed, reply contains the rejection message.
        """
        if self.mode == "open":
            return True, ""

        if self.mode == "allowlist":
            if user_id in self.allowlist:
                return True, ""
            log.warning("blocked user %s (not in allowlist)", user_id)
            return False, "Access denied. You are not on the allowlist."

        if self.mode == "pairing":
            if user_id in self.allowlist:
                return True, ""
            if text.strip() == self.pairing_code and self.pairing_code:
                self.allowlist.add(user_id)
                self._save_allowlist()
                log.info("user %s paired and added to allowlist", user_id)
                return True, "Paired successfully! You are now on the allowlist."
            return False, "Send the pairing code to connect."

        return False, f"Unknown DM policy mode: {self.mode}"
