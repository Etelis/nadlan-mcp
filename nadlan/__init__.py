"""An unofficial Python client and REST wrapper for nadlan.gov.il.

Quick start::

    from nadlan import NadlanClient

    with NadlanClient() as nadlan:
        hits = nadlan.search("רוטשילד תל אביב")
        summary = nadlan.settlement_summary(5000)  # Tel Aviv-Yafo
"""

from .client import (
    API_BASE,
    DATA_BASE,
    DealDataUnavailable,
    NadlanClient,
    SearchResult,
)
from .signing import decode_envelope, sign_payload

__all__ = [
    "NadlanClient",
    "SearchResult",
    "DealDataUnavailable",
    "sign_payload",
    "decode_envelope",
    "DATA_BASE",
    "API_BASE",
]

__version__ = "0.1.0"
