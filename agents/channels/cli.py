"""CLI channel — terminal-based interface."""

import json
import os
import logging

from channels.base import Channel
from _bedrock import _default_print
from agent import TASK_MGR, TEAM, BUS, client, MODEL
from compression import auto_compact
from hooks import list_hooks

log = logging.getLogger("channel.cli")


class CLIChannel(Channel):
    """Interactive terminal channel with streaming output."""

    @property
    def name(self) -> str:
        return "cli"

    def start(self):
        print("Agent (Bedrock + Gateway) - type 'q' to quit")
        print("Commands: /clear /compact /tasks /team /team clear /inbox /hooks\n")

        while True:
            try:
                query = input("\033[36magent >> \033[0m")
            except (EOFError, KeyboardInterrupt):
                break
            if query.strip().lower() in ("q", "exit"):
                break
            if not query.strip():
                continue

            # Local commands (handled by CLI, not routed to agent)
            if self._handle_command(query.strip()):
                continue

            # Route to gateway → agent
            self.on_message("cli_user", query)

    def stop(self):
        pass

    def on_text_chunk(self, user_id: str, chunk: str):
        """Print streaming text to terminal in real-time."""
        _default_print(chunk)

    def on_response_done(self, user_id: str, full_text: str):
        """Add spacing after response (text was already streamed)."""
        print()

    def send_response(self, user_id: str, text: str):
        """Send a non-streamed response (e.g. DM policy rejection)."""
        print(text)

    def _handle_command(self, cmd: str) -> bool:
        """Handle CLI-only commands. Returns True if handled."""
        if cmd == "/clear":
            os.system("cls" if os.name == "nt" else "clear")
            return True
        if cmd == "/compact":
            # Access session history via gateway
            session = self.gateway.sessions.get(("cli", "cli_user"))
            if session and session.history:
                print("[manual compact]")
                session.history[:] = auto_compact(session.history, client, MODEL)
            return True
        if cmd == "/tasks":
            print(TASK_MGR.list_all())
            return True
        if cmd == "/team":
            print(TEAM.list_all())
            return True
        if cmd == "/team clear":
            for name in TEAM.member_names():
                print(TEAM.remove(name))
            return True
        if cmd == "/inbox":
            print(json.dumps(BUS.read_inbox("lead"), indent=2))
            return True
        if cmd == "/hooks":
            print(list_hooks())
            return True
        return False
