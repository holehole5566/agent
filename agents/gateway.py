"""Gateway — session management and message routing between channels and agent."""

import logging
import threading

from _bedrock import user_msg, get_text
from agent import agent_loop
from sessions import SessionManager
from dm_policy import DMPolicy
from hooks import emit
from config import CFG

log = logging.getLogger("gateway")


class Session:
    """Per-user-per-channel conversation state."""

    def __init__(self, session_id: str, channel_name: str, user_id: str):
        self.session_id = session_id
        self.channel_name = channel_name
        self.user_id = user_id
        self.history = []
        self.lock = threading.Lock()


class Gateway:
    """Routes messages from channels to the agent and back."""

    def __init__(self):
        self.channels = {}
        self.sessions = {}  # (channel_name, user_id) → Session
        self.session_mgr = SessionManager()
        self.dm_policy = DMPolicy(
            mode=CFG.dm_policy.mode,
            allowlist=CFG.dm_policy.allowlist,
            pairing_code=CFG.dm_policy.pairing_code,
        )
        self._lock = threading.Lock()

    def register_channel(self, name: str, channel):
        self.channels[name] = channel
        log.info("registered channel: %s", name)

    def _get_session(self, channel_name: str, user_id: str) -> Session:
        key = (channel_name, user_id)
        with self._lock:
            if key not in self.sessions:
                sid = self.session_mgr.new_session()
                self.sessions[key] = Session(sid, channel_name, user_id)
                log.info("new session %s for %s/%s", sid, channel_name, user_id)
            return self.sessions[key]

    def handle_message(self, channel, user_id: str, text: str):
        """Route an incoming message through DM policy → agent → response."""
        # DM policy check
        allowed, reply = self.dm_policy.check(user_id, text)
        if not allowed:
            if reply:
                channel.send_response(user_id, reply)
            return

        # If pairing just succeeded, reply was set but allowed is True
        if reply:
            channel.send_response(user_id, reply)
            return

        session = self._get_session(channel.name, user_id)

        emit("message:received", {"query": text, "channel": channel.name, "user_id": user_id})

        # Collect streamed chunks for non-streaming channels
        chunks = []

        def on_text(chunk):
            chunks.append(chunk)
            channel.on_text_chunk(user_id, chunk)

        with session.lock:
            session.history.append(user_msg(text))
            agent_loop(session.history, on_text=on_text)

        full_text = "".join(chunks)
        channel.on_response_done(user_id, full_text)

        # Auto-save
        self.session_mgr.current_id = session.session_id
        self.session_mgr.save(session.history)

    def start(self):
        """Start all channels. The last one registered as 'cli' runs in foreground."""
        emit("agent:bootstrap", {})

        # Start non-CLI channels in background threads
        for name, channel in self.channels.items():
            if name != "cli":
                t = threading.Thread(target=channel.start, daemon=True, name=f"channel-{name}")
                t.start()
                log.info("started channel '%s' in background", name)

        # Start CLI in foreground (blocks)
        if "cli" in self.channels:
            self.channels["cli"].start()

    def stop(self):
        for name, channel in self.channels.items():
            try:
                channel.stop()
            except Exception as e:
                log.error("error stopping channel %s: %s", name, e)
