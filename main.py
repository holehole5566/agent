"""Entry point - run the full reference agent."""
import sys
import os

# Allow running from project root: python main.py
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "agents"))

from config import CFG
import log as log_setup
log_setup.setup(level=CFG.logging.level, log_file=CFG.logging.file or None)

from agent import agent_loop, TASK_MGR, TEAM, BUS, client, MODEL
from _bedrock import user_msg, get_text
from compression import auto_compact
from sessions import SessionManager
from hooks import emit, load_hooks, list_hooks
from pathlib import Path
import json


def main():
    # Load workspace hooks
    load_hooks(Path.cwd() / "hooks")
    emit("agent:bootstrap", {})

    session = SessionManager()
    history = []
    session.new_session()
    emit("session:start", {"session_id": session.current_id})

    print("Agent (Bedrock Converse API + Streaming) - type 'q' to quit")
    print("Commands: /clear /compact /tasks /team /team clear /inbox /sessions /resume <id> /hooks\n")

    while True:
        try:
            query = input("\033[36magent >> \033[0m")
        except (EOFError, KeyboardInterrupt):
            break
        if query.strip().lower() in ("q", "exit"):
            break
        if not query.strip():
            continue
        if query.strip() == "/clear":
            os.system("cls" if os.name == "nt" else "clear"); continue
        if query.strip() == "/compact":
            if history:
                print("[manual compact]")
                history[:] = auto_compact(history, client, MODEL)
            continue
        if query.strip() == "/tasks":
            print(TASK_MGR.list_all()); continue
        if query.strip() == "/team":
            print(TEAM.list_all()); continue
        if query.strip() == "/team clear":
            for name in TEAM.member_names():
                print(TEAM.remove(name))
            continue
        if query.strip() == "/inbox":
            print(json.dumps(BUS.read_inbox("lead"), indent=2)); continue
        if query.strip() == "/sessions":
            print(session.list_sessions()); continue
        if query.strip() == "/hooks":
            print(list_hooks()); continue
        if query.strip().startswith("/resume"):
            parts = query.strip().split(maxsplit=1)
            if len(parts) < 2:
                print("Usage: /resume <session_id>"); continue
            try:
                history = session.load(parts[1])
                print(f"Resumed session: {parts[1]} ({len(history)} messages)")
            except ValueError as e:
                print(f"Error: {e}")
            continue

        emit("message:received", {"query": query})
        history.append(user_msg(query))
        agent_loop(history)
        # Streaming already printed the response — just add spacing
        print()
        # Auto-save session
        session.save(history)

    emit("session:end", {"session_id": session.current_id, "messages": len(history)})


if __name__ == "__main__":
    main()
