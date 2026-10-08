"""Agent tab labels: "<Display>•<effort>", suffixed "-2", "-3"... for more
tabs of the same model and effort in one workspace.

Tabs made by earlier tooling may use the spaced form "Display • effort";
everything here parses both.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

BULLET = "•"
EFFORT_SHORT = {
    "minimal": "min",
    "low": "lo",
    "medium": "med",
    "high": "hi",
    "xhigh": "xhi",
    "ultra": "ult",
}

_RIGHT = re.compile(r"(.+?)(?:-(\d+))?")
_SPACED = re.compile(r"\s*" + BULLET + r"\s*")


@dataclass(frozen=True)
class AgentLabel:
    display: str
    effort: str
    n: int = 1

    def __str__(self) -> str:
        return tab_label(self.display, self.effort, self.n)

    def same_kind(self, other: AgentLabel) -> bool:
        return self.display.lower() == other.display.lower() and self.effort == other.effort


def tab_label(display: str, effort: str, n: int = 1) -> str:
    return f"{display}{BULLET}{effort}" + ("" if n == 1 else f"-{n}")


def parse(label: str) -> AgentLabel | None:
    left, sep, right = label.partition(BULLET)
    if not sep or not left.strip():
        return None
    m = _RIGHT.fullmatch(right.strip())
    if not m:
        return None
    return AgentLabel(left.strip(), m.group(1), int(m.group(2) or 1))


def normalize(label: str) -> str:
    """ "Sonnet • medium" -> "Sonnet•medium"; other labels unchanged."""
    return _SPACED.sub(BULLET, label)


def short(label: str) -> str:
    """ "Opus•xhigh-2" -> "Opus xhi-2", for tight table cells."""
    a = parse(label)
    if not a:
        return label
    suffix = "" if a.n == 1 else f"-{a.n}"
    return f"{a.display} {EFFORT_SHORT.get(a.effort, a.effort)}{suffix}"


def next_free(existing: list[str], display: str, effort: str) -> str:
    """The label for one more tab of display/effort, given the labels already
    in the workspace: the bare label if unused, else the lowest free -N."""
    want = AgentLabel(display, effort)
    used = {a.n for a in map(parse, existing) if a and a.same_kind(want)}
    n = 1
    while n in used:
        n += 1
    return tab_label(display, effort, n)


def agent_name(tool: str, label: str) -> str:
    """herdr agent names must match [a-z][a-z0-9_-]{0,31}."""
    s = re.sub(r"[^a-z0-9_-]", "-", f"{tool}-{label}".lower())
    s = re.sub(r"-+", "-", s)
    s = re.sub(r"^[^a-z]*", "", s)[:32]
    return s.rstrip("-_")
