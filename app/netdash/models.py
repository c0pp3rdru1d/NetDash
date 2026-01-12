from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime

@dataclass(frozen=True)
class PingResult:
    host: str
    ok: bool
    rtt_ms: float | None
    ts: datetime
    error: str | None = None

