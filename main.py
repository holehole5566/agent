"""Entry point — serve the agent or run CLI subcommands."""
import sys
import os
import argparse

# Allow running from project root: python main.py
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "agents"))

from config import CFG
import log as log_setup


def cmd_serve(args):
    """Start the gateway with configured channels."""
    log_setup.setup(level=CFG.logging.level, log_file=CFG.logging.file or None)

    from hooks import load_hooks
    from pathlib import Path
    load_hooks(Path.cwd() / "hooks")

    from gateway import Gateway

    gw = Gateway()

    for ch_name in CFG.gateway.channels:
        if ch_name == "telegram":
            if not CFG.telegram.token:
                print("Error: telegram.token not set in config.toml")
                continue
            from channels.telegram import TelegramChannel
            gw.register_channel("telegram", TelegramChannel(gw, CFG.telegram.token, owner_id=CFG.telegram.owner_id))
        else:
            print(f"Warning: unknown channel '{ch_name}'")

    try:
        gw.start()
    except KeyboardInterrupt:
        pass
    finally:
        gw.stop()


def cmd_sessions(args):
    """List or load sessions."""
    from sessions import SessionManager
    sm = SessionManager()
    if args.session_id:
        try:
            messages = sm.load(args.session_id)
            print(f"Session: {args.session_id} ({len(messages)} messages)")
            for msg in messages:
                role = msg.get("role", "?")
                for block in msg.get("content", []):
                    if isinstance(block, dict) and "text" in block:
                        preview = block["text"][:200]
                        print(f"  [{role}] {preview}")
                        break
        except ValueError as e:
            print(f"Error: {e}")
    else:
        print(sm.list_sessions(limit=args.limit))


def cmd_tasks(args):
    """List tasks."""
    from tasks import TaskManager
    tm = TaskManager()
    print(tm.list_all())


def cmd_routines(args):
    """List, create, delete, or show history of routines."""
    from routines import RoutineManager
    rm = RoutineManager()

    if args.action == "list":
        print(rm.list_all())
    elif args.action == "create":
        if not args.name or not args.schedule or not args.prompt:
            print("Error: --name, --schedule, and --prompt are required")
            return
        print(rm.create(args.name, args.schedule, args.prompt,
                        description=args.description or "",
                        cooldown_secs=args.cooldown))
    elif args.action == "delete":
        if not args.name:
            print("Error: --name is required")
            return
        print(rm.delete(args.name))
    elif args.action == "history":
        if not args.name:
            print("Error: --name is required")
            return
        print(rm.history(args.name, limit=args.limit))
    elif args.action == "enable":
        if not args.name:
            print("Error: --name is required")
            return
        print(rm.toggle(args.name, True))
    elif args.action == "disable":
        if not args.name:
            print("Error: --name is required")
            return
        print(rm.toggle(args.name, False))


def main():
    parser = argparse.ArgumentParser(prog="agent", description="Agent CLI")
    sub = parser.add_subparsers(dest="command")

    # serve (default)
    sub.add_parser("serve", help="Start the agent")

    # sessions
    sp_sessions = sub.add_parser("sessions", help="List or inspect sessions")
    sp_sessions.add_argument("session_id", nargs="?", help="Session ID to inspect")
    sp_sessions.add_argument("-n", "--limit", type=int, default=20, help="Max sessions to list")

    # tasks
    sub.add_parser("tasks", help="List tasks")

    # routines
    sp_routines = sub.add_parser("routines", help="Manage routines")
    sp_routines.add_argument("action", nargs="?", default="list",
                             choices=["list", "create", "delete", "history", "enable", "disable"])
    sp_routines.add_argument("--name", help="Routine name")
    sp_routines.add_argument("--schedule", help="Cron expression (e.g. '0 9 * * *')")
    sp_routines.add_argument("--prompt", help="Task prompt")
    sp_routines.add_argument("--description", help="Description")
    sp_routines.add_argument("--cooldown", type=int, default=300, help="Cooldown seconds")
    sp_routines.add_argument("-n", "--limit", type=int, default=10, help="History limit")

    args = parser.parse_args()

    if args.command is None or args.command == "serve":
        cmd_serve(args)
    elif args.command == "sessions":
        cmd_sessions(args)
    elif args.command == "tasks":
        cmd_tasks(args)
    elif args.command == "routines":
        cmd_routines(args)


if __name__ == "__main__":
    main()
