"""Skill loader for SKILL.md files."""

import logging
import re
from pathlib import Path

from scanner import scan_and_report

log = logging.getLogger("skills")


class SkillLoader:
    def __init__(self, skills_dir: Path):
        self.skills = {}
        self.warnings = {}
        if skills_dir.exists():
            for f in sorted(skills_dir.rglob("SKILL.md")):
                text = f.read_text(encoding="utf-8")
                match = re.match(r"^---\n(.*?)\n---\n(.*)", text, re.DOTALL)
                meta, body = {}, text
                if match:
                    for line in match.group(1).strip().splitlines():
                        if ":" in line:
                            k, v = line.split(":", 1)
                            meta[k.strip()] = v.strip()
                    body = match.group(2).strip()
                name = meta.get("name", f.parent.name)
                warning = scan_and_report(name, body)
                if warning:
                    self.warnings[name] = warning
                self.skills[name] = {"meta": meta, "body": body}

    def descriptions(self) -> str:
        if not self.skills:
            return "(no skills)"
        return "\n".join(f"  - {n}: {s['meta'].get('description', '-')}" for n, s in self.skills.items())

    def load(self, name: str) -> str:
        s = self.skills.get(name)
        if not s:
            return f"Error: Unknown skill '{name}'. Available: {', '.join(self.skills.keys())}"
        prefix = ""
        if name in self.warnings:
            prefix = f"<security-warning>\n{self.warnings[name]}\n</security-warning>\n"
        return f"{prefix}<skill name=\"{name}\">\n{s['body']}\n</skill>"
