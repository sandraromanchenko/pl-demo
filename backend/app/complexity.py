"""Complexity bands.

Documents carry BoardGameGeek's `complexity` weight (1-5), which means nothing
to most people, so the API tags every result with a band and the card renders it
as a badge ("Easy", "~15 min to learn").

Bands are half-open [min, max) so every weight falls in exactly one.
"""
from typing import Any

BANDS = [
    {
        "id": "easy",
        "label": "Easy",
        "learn": "~15 min to learn",
        "min": None,
        "max": 2.5,
    },
    {
        "id": "medium",
        "label": "Medium",
        "learn": "~30 min to learn",
        "min": 2.5,
        "max": 3.5,
    },
    {
        "id": "complex",
        "label": "Complex",
        "learn": "45 min+ to learn",
        "min": 3.5,
        "max": None,
    },
]

def band_for(weight: Any) -> dict[str, Any] | None:
    """The band a document's weight falls into, for display on the card."""
    if not isinstance(weight, (int, float)):
        return None
    for band in BANDS:
        if (band["min"] is None or weight >= band["min"]) and (
            band["max"] is None or weight < band["max"]
        ):
            return {"id": band["id"], "label": band["label"], "learn": band["learn"]}
    return None
