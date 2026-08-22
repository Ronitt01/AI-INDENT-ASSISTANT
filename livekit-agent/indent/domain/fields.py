"""The eight fields that make up a transport indent.

Single source of truth for their keys, labels, grouping and fallback prompts.
The operator console mirrors these keys; ``tests`` assert the two stay in step.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FieldDef:
    key: str
    label: str
    group: str
    #: Asked only when the model has not already covered it in conversation.
    prompt: str
    #: Free text rather than a closed vocabulary — affects how hard we validate.
    open_ended: bool = False


FIELDS: tuple[FieldDef, ...] = (
    FieldDef("pickupLocation", "Pickup location", "Route",
             "Where should we pick this up from?", open_ended=True),
    FieldDef("deliveryLocation", "Delivery location", "Route",
             "And where is it being delivered to?", open_ended=True),
    FieldDef("material", "Material", "Cargo",
             "What material are we moving?"),
    FieldDef("quantity", "Quantity", "Cargo",
             "How much of it - give me a quantity and unit, like '20 tons'."),
    FieldDef("vehicleType", "Vehicle type", "Cargo",
             "What kind of vehicle do you need - truck, trailer, tanker?"),
    FieldDef("pickupDate", "Pickup date", "Schedule",
             "What date should pickup happen?"),
    FieldDef("deliveryDate", "Delivery date", "Schedule",
             "And what date is delivery expected?"),
    FieldDef("procurementType", "Procurement type", "Terms",
             "Is this spot, rate contract, or tender-based procurement?"),
)

FIELD_KEYS: tuple[str, ...] = tuple(f.key for f in FIELDS)
FIELD_BY_KEY: dict[str, FieldDef] = {f.key: f for f in FIELDS}

#: Display order for the console, grouped.
GROUPS: tuple[str, ...] = ("Route", "Cargo", "Schedule", "Terms")


def fields_in(group: str) -> tuple[FieldDef, ...]:
    return tuple(f for f in FIELDS if f.group == group)
