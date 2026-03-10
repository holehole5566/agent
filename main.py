"""Entry point - run the full reference agent."""
import sys
import os

# Allow running from project root: python main.py
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "agents"))

from s_full import agent_loop, user_msg, TASK_MGR, TEAM, BUS, auto_compact, get_text
import json


def main():
    history = []
    print("Agent (Bedrock Converse API) - type 'q' to quit")
    print("Commands: /clear /compact /tasks /team /team clear /inbox\n")
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
                history[:] = auto_compact(history)
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
        history.append(user_msg(query))
        agent_loop(history)
        # Print the last assistant response
        if history and history[-1]["role"] == "assistant":
            text = get_text(history[-1]["content"])
            if text:
                print(text)
        print()


if __name__ == "__main__":
    main()
