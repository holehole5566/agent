"""Telegram channel — bot integration via HTTP API."""

import json
import logging
import threading
import time
import urllib.request
import urllib.error

from channels.base import Channel

log = logging.getLogger("channel.telegram")


class TelegramChannel(Channel):
    """Telegram bot channel using long polling."""

    def __init__(self, gateway, token: str):
        super().__init__(gateway)
        self.token = token
        self._running = False
        self._offset = 0
        self._typing = {}  # user_id → threading.Event (signals when to stop typing)

    @property
    def name(self) -> str:
        return "telegram"

    def _api(self, method: str, data: dict = None) -> dict:
        """Call Telegram Bot API."""
        url = f"https://api.telegram.org/bot{self.token}/{method}"
        if data:
            req = urllib.request.Request(
                url,
                json.dumps(data).encode("utf-8"),
                {"Content-Type": "application/json"},
            )
        else:
            req = urllib.request.Request(url)
        try:
            resp = urllib.request.urlopen(req, timeout=60)
            return json.loads(resp.read())
        except urllib.error.URLError as e:
            log.error("Telegram API error on %s: %s", method, e)
            return {"ok": False, "description": str(e)}

    def start(self):
        """Start long polling for updates."""
        # Verify token
        me = self._api("getMe")
        if not me.get("ok"):
            log.error("Telegram auth failed: %s", me.get("description", "unknown"))
            return
        bot_name = me["result"].get("username", "?")
        log.info("Telegram bot started: @%s", bot_name)
        print(f"  Telegram bot online: @{bot_name}")

        self._running = True
        while self._running:
            try:
                updates = self._api("getUpdates", {
                    "offset": self._offset,
                    "timeout": 30,
                })
                if not updates.get("ok"):
                    time.sleep(5)
                    continue
                for update in updates.get("result", []):
                    self._offset = update["update_id"] + 1
                    msg = update.get("message", {})
                    text = msg.get("text", "")
                    chat_id = str(msg.get("chat", {}).get("id", ""))
                    if text and chat_id:
                        user = msg.get("from", {})
                        user_id = str(user.get("id", chat_id))
                        username = user.get("username", user.get("first_name", user_id))
                        log.info("telegram msg from %s: %s", username, text[:80])
                        self._start_typing(user_id)
                        self.on_message(user_id, text)
            except Exception as e:
                log.error("Telegram polling error: %s", e)
                time.sleep(5)

    def stop(self):
        self._running = False

    def send_response(self, user_id: str, text: str):
        """Send a message back to the Telegram user."""
        self._stop_typing(user_id)
        if not text:
            return
        # Telegram max message length is 4096
        for i in range(0, len(text), 4000):
            chunk = text[i:i + 4000]
            result = self._api("sendMessage", {
                "chat_id": user_id,
                "text": chunk,
            })
            if not result.get("ok"):
                log.error("Failed to send to %s: %s", user_id, result.get("description"))

    def _start_typing(self, user_id: str):
        """Start sending typing indicator in a background thread."""
        stop_event = threading.Event()
        self._typing[user_id] = stop_event

        def loop():
            while not stop_event.is_set():
                self._api("sendChatAction", {"chat_id": user_id, "action": "typing"})
                stop_event.wait(4)  # Telegram typing expires after ~5s

        threading.Thread(target=loop, daemon=True).start()

    def _stop_typing(self, user_id: str):
        """Stop the typing indicator."""
        stop_event = self._typing.pop(user_id, None)
        if stop_event:
            stop_event.set()

    def on_text_chunk(self, user_id: str, chunk: str):
        """Telegram doesn't stream — chunks are ignored."""
        pass

    def on_response_done(self, user_id: str, full_text: str):
        """Stop typing and send the complete response."""
        self._stop_typing(user_id)
        self.send_response(user_id, full_text)
