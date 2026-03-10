"""Example hook: track real token usage per session.

Rename this file to remove the 'example_' prefix to activate it.
Hook functions are named on_<event> where event uses underscores.
"""

_total_input = 0
_total_output = 0
_total_calls = 0


def on_llm_after_response(data):
    global _total_input, _total_output, _total_calls
    _total_calls += 1
    usage = data.get("usage", {})
    inp = usage.get("inputTokens", 0)
    out = usage.get("outputTokens", 0)
    _total_input += inp
    _total_output += out
    print(f"  [tokens] call #{_total_calls}: {inp} in / {out} out  (total: {_total_input} in / {_total_output} out)")


def on_session_end(data):
    total = _total_input + _total_output
    print(f"  [tokens] Session total: {_total_input} input + {_total_output} output = {total} tokens across {_total_calls} calls")
