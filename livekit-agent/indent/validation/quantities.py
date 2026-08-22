"""Quantity normalisation and sanity bounds."""

from __future__ import annotations

import re

from ..extraction.normalize import normalize
from ..extraction.values import unit_canonical
from .dates import Resolved

#: Indian road transport: below this is not a truck movement, above it is a
#: mishearing or a typo. Both ends are advisory — flagged, never rejected,
#: because an unusual load is still a load.
MIN_TONS = 0.1
MAX_TONS = 5000.0

#: Everything folds to tonnes so quantities can be compared and bounded.
_TO_TONNES = {"ton": 1.0, "mt": 1.0, "quintal": 0.1, "kg": 0.001}


def resolve_quantity(raw: str) -> Resolved:
    text = normalize(raw)
    m = re.match(r"^(\d+(?:\.\d+)?)\s*(.+)$", text)
    if not m:
        return Resolved(raw, [f"could not read a number from '{raw}'"], ok=False)

    amount = float(m.group(1))
    unit_raw = m.group(2).strip()
    canonical = unit_canonical(unit_raw)
    if canonical is None:
        return Resolved(raw, [f"unrecognised unit '{unit_raw}'"], ok=False)

    warnings: list[str] = []
    factor = _TO_TONNES.get(canonical.lower())
    if factor is not None:
        tonnes = amount * factor
        if tonnes < MIN_TONS:
            warnings.append(f"{amount:g} {canonical} is unusually small for a truck load")
        elif tonnes > MAX_TONS:
            warnings.append(f"{amount:g} {canonical} exceeds {MAX_TONS:.0f} t - confirm this is right")

    return Resolved(f"{amount:g} {canonical}", warnings)
