"""Skill scanner — detect suspicious patterns before loading skills."""

import logging
import re

log = logging.getLogger("scanner")

SUSPICIOUS_PATTERNS = [
    # Prompt injection
    (r"ignore\s+(all\s+)?previous\s+instructions", "prompt injection: ignore instructions"),
    (r"you\s+are\s+now\s+", "prompt injection: identity override"),
    (r"system\s*prompt\s*:", "prompt injection: system prompt extraction"),
    (r"<\s*system\s*>", "prompt injection: fake system tag"),
    (r"IMPORTANT:\s*disregard", "prompt injection: disregard directive"),

    # Code execution
    (r"\beval\s*\(", "code eval"),
    (r"\bexec\s*\(", "code exec"),
    (r"__import__\s*\(", "dynamic import"),
    (r"subprocess\.(run|call|Popen)", "subprocess call"),
    (r"os\.system\s*\(", "os.system call"),

    # Shell injection
    (r"curl\s+.*\|\s*(bash|sh|python)", "pipe to shell"),
    (r"wget\s+.*[;&|]\s*(bash|sh|python)", "download and execute"),
    (r"base64\s+(--decode|-d)\s*\|", "base64 decode pipe"),

    # Data exfiltration
    (r"curl\s+.*-d\s+.*\$", "data exfiltration via curl"),
    (r"nc\s+-[a-z]*\s+\d+", "netcat connection"),
]

_COMPILED = [(re.compile(p, re.IGNORECASE), desc) for p, desc in SUSPICIOUS_PATTERNS]


def scan_skill(name: str, content: str) -> list:
    """Scan skill content for suspicious patterns.

    Returns list of findings: [{"pattern": str, "line": int, "match": str}, ...]
    """
    findings = []
    lines = content.splitlines()
    for i, line in enumerate(lines, 1):
        # Skip code blocks (lines inside ``` fences are examples, not threats)
        stripped = line.strip()
        if stripped.startswith("```"):
            continue
        for regex, description in _COMPILED:
            match = regex.search(line)
            if match:
                findings.append({
                    "pattern": description,
                    "line": i,
                    "match": match.group()[:80],
                })
    return findings


def scan_and_report(name: str, content: str) -> str | None:
    """Scan a skill and return a warning string, or None if clean."""
    findings = scan_skill(name, content)
    if not findings:
        return None
    lines = [f"WARNING: Skill '{name}' has {len(findings)} suspicious pattern(s):"]
    for f in findings:
        lines.append(f"  line {f['line']}: {f['pattern']} — \"{f['match']}\"")
    warning = "\n".join(lines)
    log.warning(warning)
    return warning
