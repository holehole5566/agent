"""Entry point — start the gateway with configured channels."""
import sys
import os

# Allow running from project root: python main.py
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "agents"))

from config import CFG
import log as log_setup
log_setup.setup(level=CFG.logging.level, log_file=CFG.logging.file or None)

from hooks import load_hooks
from pathlib import Path
load_hooks(Path.cwd() / "hooks")

from gateway import Gateway
from channels.cli import CLIChannel


def main():
    gw = Gateway()

    # Register configured channels
    for ch_name in CFG.gateway.channels:
        if ch_name == "cli":
            gw.register_channel("cli", CLIChannel(gw))
        elif ch_name == "telegram":
            if not CFG.telegram.token:
                print("Error: telegram.token not set in config.toml")
                continue
            from channels.telegram import TelegramChannel
            gw.register_channel("telegram", TelegramChannel(gw, CFG.telegram.token))
        else:
            print(f"Warning: unknown channel '{ch_name}'")

    # Start gateway (CLI runs in foreground, others in background threads)
    try:
        gw.start()
    except KeyboardInterrupt:
        pass
    finally:
        gw.stop()


if __name__ == "__main__":
    main()
