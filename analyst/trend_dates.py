"""Resolve explicit IST calendar ranges before asking the live planner."""
import re
from datetime import date, timedelta

from .plan import Window


MONTHS = "January February March April May June July August September October November December".split()
MONTH_NUMBER = {alias.lower(): i for i, name in enumerate(MONTHS, 1) for alias in (name, name[:3])}
MONTH = r"(?:" + "|".join(MONTH_NUMBER) + r")\b"
ISO = r"\d{4}-\d{2}-\d{2}"
JOIN = r"\s*(?:\b(?:through|to|until|and)\b|[-–—])\s*"
MONTH_RANGE = re.compile(
    rf"\b({MONTH})\s+(\d{{1,2}})(?:,?\s+(\d{{4}}))?{JOIN}"
    rf"(?:({MONTH})\s+)?(\d{{1,2}})(?:,?\s+(\d{{4}}))?\b", re.I)
ISO_RANGE = re.compile(rf"(?<!\d)({ISO}){JOIN}({ISO})(?!\d)", re.I)
DATE_HINT = re.compile(rf"\d|\b{MONTH}|\b(?:today|yesterday|tomorrow|last|next|instead|except)\b", re.I)


def resolve_window(question: str) -> Window | None:
    """Return None for incomplete or ambiguous ranges; raise for invalid windows."""
    match = ISO_RANGE.search(question) or MONTH_RANGE.search(question)
    if not match or DATE_HINT.search(question[:match.start()] + " " + question[match.end():]):
        return None
    if match.re is ISO_RANGE:
        start, final = map(date.fromisoformat, match.groups())
    else:
        m1, d1, y1, m2, d2, y2 = match.groups()
        if not (y1 or y2):
            return None
        start_month = MONTH_NUMBER[m1.lower()]
        final_month = MONTH_NUMBER[(m2 or m1).lower()]
        start_year, final_year = int(y1 or y2), int(y2 or y1)
        if final_month < start_month:
            if not y1:
                start_year -= 1
            elif not y2:
                final_year += 1
        start = date(start_year, start_month, int(d1))
        final = date(final_year, final_month, int(d2))
    return Window(start=start, end=final + timedelta(days=1))
