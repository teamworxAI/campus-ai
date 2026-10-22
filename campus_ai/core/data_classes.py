"""Data classes P/I/S/R (plan section 2), checked before any model sees data.

Every LLM router call and every embedding declares the class of its data.
R (restricted: e.g. items with access limits or TK Labels, Indigenous
materials under OCAP) is never embedded or sent to any model.
"""

DATA_CLASSES = {
    "P": "public",
    "I": "institutional",
    "S": "sensitive",
    "R": "restricted",
}


class RestrictedDataError(PermissionError):
    """Raised before a model call or embedding when the data is class R."""


def check(data_class: str) -> str:
    """Return `data_class` if a model may process it; refuse R and unknown classes."""
    if data_class not in DATA_CLASSES:
        raise ValueError(f"Unknown data class {data_class!r}; expected one of {sorted(DATA_CLASSES)}")
    if data_class == "R":
        raise RestrictedDataError("Class R (restricted) data is never embedded or sent to any model")
    return data_class
