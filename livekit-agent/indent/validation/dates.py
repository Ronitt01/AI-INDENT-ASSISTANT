"""Turning a spoken date into a concrete one.

Two principles:

* **Resolve, don't reject.** "21 Sep" becomes a real date rather than an error —
  the caller said something meaningful and the system should meet them there.
* **Surface assumptions.** Every inference comes back as a warning attached to
  the field. Silently booking twelve months out is exactly the kind of thing
  nobody notices until it is expensive.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

try:  # zoneinfo needs the tzdata package on Windows
    from zoneinfo import ZoneInfo

    IST = ZoneInfo("Asia/Kolkata")
except Exception:  # pragma: no cover - environment dependent
    IST = timezone(timedelta(hours=5, minutes=30), name="IST")

from ..extraction.normalize import normalize

#: Beyond this, a date is more likely a mishearing than a real booking.
MAX_SCHEDULE_DAYS = 180

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

_RELATIVE_DAYS = {"today": 0, "tomorrow": 1, "day after tomorrow": 2}

_WEEKDAYS = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}


def today_ist() -> date:
    return datetime.now(IST).date()


@dataclass
class Resolved:
    """A validated value plus what had to be assumed to get there."""

    value: str
    warnings: list[str] = field(default_factory=list)
    iso: str | None = None
    ok: bool = True


def resolve_date(raw: str, *, reference: date | None = None) -> Resolved:
    """Resolve a spoken date.

    A bare "21 Sep" is ambiguous by a year. Bookings look forward, so a date
    already past is read as next year — and says so.
    """
    ref = reference or today_ist()
    text = normalize(raw)
    if not text:
        return Resolved(raw, ["empty date"], ok=False)

    if text in _RELATIVE_DAYS:
        d = ref + timedelta(days=_RELATIVE_DAYS[text])
        return Resolved(d.strftime("%d %b %Y"), [], d.isoformat())

    if text in _WEEKDAYS:
        # The next occurrence, today excluded.
        delta = (_WEEKDAYS[text] - ref.weekday()) % 7 or 7
        d = ref + timedelta(days=delta)
        return Resolved(
            d.strftime("%d %b %Y"), [f"'{raw}' read as the next {text.title()}"], d.isoformat()
        )

    if text in ("next week", "this week"):
        d = ref + timedelta(days=7 if text == "next week" else 1)
        return Resolved(d.strftime("%d %b %Y"), [f"'{raw}' is approximate"], d.isoformat())

    m = re.match(r"^(\d{1,2})\s+([a-z]{3,})\.?(?:\s+(\d{4}))?$", text)
    if m:
        month = _MONTHS.get(m.group(2)[:3])
        if month is None:
            return Resolved(raw, [f"unrecognised month in '{raw}'"], ok=False)
        year = int(m.group(3)) if m.group(3) else None
        return _assemble(int(m.group(1)), month, year, ref, raw)

    # Day-first, the Indian convention: 9/8 is 9 August.
    m = re.match(r"^(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?$", text)
    if m:
        year = m.group(3)
        if year and len(year) == 2:
            year = f"20{year}"
        return _assemble(int(m.group(1)), int(m.group(2)), int(year) if year else None, ref, raw)

    return Resolved(raw, [f"could not resolve '{raw}' to a date"], ok=False)


def _assemble(day: int, month: int, year: int | None, ref: date, raw: str) -> Resolved:
    if not 1 <= month <= 12 or not 1 <= day <= 31:
        return Resolved(raw, [f"'{raw}' is not a valid date"], ok=False)

    warnings: list[str] = []
    inferred = year is None
    year = year if year is not None else ref.year

    try:
        d = date(year, month, day)
    except ValueError:
        return Resolved(raw, [f"'{raw}' is not a valid calendar date"], ok=False)

    if inferred and d < ref:
        try:
            d = date(year + 1, month, day)
        except ValueError:
            return Resolved(raw, [f"'{raw}' is not a valid calendar date"], ok=False)
        warnings.append(
            f"year not stated - assumed {d.year} since {d.strftime('%d %b')} has passed"
        )
    elif inferred:
        warnings.append(f"year not stated - assumed {d.year}")

    if d > ref + timedelta(days=MAX_SCHEDULE_DAYS):
        warnings.append(f"{d.isoformat()} is more than {MAX_SCHEDULE_DAYS} days out - confirm")

    return Resolved(d.strftime("%d %b %Y"), warnings, d.isoformat())
