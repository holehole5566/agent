"""Event hook system — register and emit hooks at agent lifecycle points."""

import importlib.util
import logging
from pathlib import Path

log = logging.getLogger("hooks")

# Event name → list of callables
_registry: dict[str, list] = {}

# Valid hook events
EVENTS = {
    "agent:bootstrap",
    "session:start",
    "session:end",
    "message:received",
    "message:sent",
    "llm:before-request",
    "llm:after-response",
    "tool:before-execute",
    "tool:after-execute",
}

# Event name → function name convention
# e.g. "llm:before-request" → "on_llm_before_request"
def _event_to_func(event: str) -> str:
    return "on_" + event.replace(":", "_").replace("-", "_")


def register(event: str, func):
    """Register a hook function for an event."""
    if event not in EVENTS:
        log.warning("unknown hook event: %s", event)
        return
    _registry.setdefault(event, []).append(func)
    log.debug("registered hook %s → %s", event, func.__name__)


def emit(event: str, data: dict = None) -> dict:
    """Emit an event, calling all registered hooks in order.

    Hooks can modify data in-place. Returns the (possibly modified) data dict.
    """
    if data is None:
        data = {}
    for func in _registry.get(event, []):
        try:
            result = func(data)
            if isinstance(result, dict):
                data = result
        except Exception as e:
            log.error("hook %s failed on %s: %s", func.__name__, event, e)
    return data


def load_hooks(hooks_dir: Path):
    """Load hook modules from a directory.

    Each .py file is imported. Functions matching on_<event_name> are auto-registered.
    """
    if not hooks_dir.exists():
        return
    for path in sorted(hooks_dir.glob("*.py")):
        if path.name.startswith("_") or path.name.startswith("example_"):
            continue
        try:
            spec = importlib.util.spec_from_file_location(path.stem, path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            count = 0
            for event in EVENTS:
                func_name = _event_to_func(event)
                func = getattr(mod, func_name, None)
                if callable(func):
                    register(event, func)
                    count += 1
            if count:
                log.info("loaded %d hook(s) from %s", count, path.name)
        except Exception as e:
            log.error("failed to load hook %s: %s", path.name, e)


def list_hooks() -> str:
    """List all registered hooks."""
    if not _registry:
        return "No hooks registered."
    lines = []
    for event, funcs in sorted(_registry.items()):
        names = ", ".join(f.__name__ for f in funcs)
        lines.append(f"  {event}: {names}")
    return "Hooks:\n" + "\n".join(lines)


def clear():
    """Clear all hooks (useful for testing)."""
    _registry.clear()
