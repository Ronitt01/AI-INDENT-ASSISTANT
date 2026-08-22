"""Cross-field rules — the checks that need more than one field at once.

Severity is the whole point of this module: a **warning** informs the operator
(a year was inferred), an **error** blocks submission (delivery before pickup).
Collapsing the two would either block on trivia or ship a broken booking.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from ..extraction.normalize import normalize
from .dates import resolve_date, today_ist
from .quantities import resolve_quantity


@dataclass
class Issue:
    field: str
    message: str
    severity: str  # "warning" blocks nothing; "error" blocks submission


def validate_indent(
    plain: dict[str, str | None], *, reference: date | None = None
) -> list[Issue]:
    ref = reference or today_ist()
    issues: list[Issue] = []

    for key in ("pickupDate", "deliveryDate"):
        raw = plain.get(key)
        if not raw:
            continue
        res = resolve_date(raw, reference=ref)
        if not res.ok:
            issues.append(Issue(key, res.warnings[0] if res.warnings else "unresolved date", "error"))
        else:
            issues.extend(Issue(key, w, "warning") for w in res.warnings)

    pickup, delivery = plain.get("pickupDate"), plain.get("deliveryDate")
    if pickup and delivery:
        p, d = resolve_date(pickup, reference=ref), resolve_date(delivery, reference=ref)
        if p.ok and d.ok and p.iso and d.iso and d.iso < p.iso:
            issues.append(
                Issue("deliveryDate", f"delivery ({d.value}) is before pickup ({p.value})", "error")
            )

    if plain.get("quantity"):
        q = resolve_quantity(plain["quantity"])
        if not q.ok:
            issues.append(Issue("quantity", q.warnings[0] if q.warnings else "unreadable", "error"))
        else:
            issues.extend(Issue("quantity", w, "warning") for w in q.warnings)

    origin, destination = plain.get("pickupLocation"), plain.get("deliveryLocation")
    if origin and destination and normalize(origin) == normalize(destination):
        issues.append(Issue("deliveryLocation", "pickup and delivery are the same place", "error"))

    return issues


def blocking(issues: list[Issue]) -> list[Issue]:
    return [i for i in issues if i.severity == "error"]
