"""DM policy — control who can talk to the agent."""

import logging

log = logging.getLogger("dm_policy")


class DMPolicy:
    def __init__(self, mode="open", allowlist=None, pairing_code=""):
        self.mode = mode
        self.allowlist = set(allowlist or [])
        self.pairing_code = pairing_code
        self._paired = set()

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
            if user_id in self._paired or user_id in self.allowlist:
                return True, ""
            if text.strip() == self.pairing_code and self.pairing_code:
                self._paired.add(user_id)
                log.info("user %s paired successfully", user_id)
                return True, "Paired successfully! You can now send messages."
            return False, "Send the pairing code to connect."

        return False, f"Unknown DM policy mode: {self.mode}"
