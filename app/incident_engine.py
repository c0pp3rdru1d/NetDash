from __future__ import annotations

from datetime import datetime
from sqlmodel import select

from .db import session_scope
from .models import Incident


def _find_open_incident(check_id: int) -> Incident | None:
    with session_scope() as s:
        return s.exec(
            select(Incident)
            .where(Incident.check_id == check_id)
            .where(Incident.state == "open")
            .order_by(Incident.opened_ts.desc())
            .limit(1)
        ).first()


def open_incident(device_id: int, check_id: int, ts: datetime, reason: str, meta: dict) -> Incident:
    with session_scope() as s:
        inc = Incident(
            device_id=device_id,
            check_id=check_id,
            state="open",
            opened_ts=ts,
            open_reason=reason,
            meta=meta or {},
        )
        s.add(inc)
        s.commit()
        s.refresh(inc)
        return inc


def close_incident(incident_id: int, ts: datetime, reason: str, meta_update: dict | None = None) -> None:
    with session_scope() as s:
        inc = s.get(Incident, incident_id)
        if not inc:
            return
        inc.state = "closed"
        inc.closed_ts = ts
        inc.close_reason = reason
        if meta_update:
            inc.meta = {**(inc.meta or {}), **meta_update}
        s.add(inc)
        s.commit()


def process_status_transition(
    *,
    device_id: int,
    check_id: int,
    ts: datetime,
    status: str,
    down_streak: int,
    up_streak: int,
    open_after_downs: int,
    close_after_ups: int,
) -> dict:
    """
    Returns an event dict (or {}) so the scheduler can broadcast to UI.

    Rules:
    - Open incident when down_streak >= open_after_downs and no open incident exists.
    - Close incident when up_streak >= close_after_ups and an open incident exists.

    "up" and "degraded" both count as "available" for closing incidents.
    """
    event: dict = {}

    open_inc = _find_open_incident(check_id=check_id)

    if status == "down":
        if open_inc is None and down_streak >= open_after_downs:
            inc = open_incident(
                device_id=device_id,
                check_id=check_id,
                ts=ts,
                reason="down_streak",
                meta={
                    "open_after_downs": open_after_downs,
                    "down_streak": down_streak,
                },
            )
            event = {
                "type": "incident_opened",
                "incident_id": inc.id,
                "device_id": device_id,
                "check_id": check_id,
                "ts": ts.isoformat() + "Z",
            }
    else:
        if open_inc is not None and up_streak >= close_after_ups:
            close_incident(
                incident_id=open_inc.id,
                ts=ts,
                reason="up_streak",
                meta_update={
                    "close_after_ups": close_after_ups,
                    "up_streak": up_streak,
                },
            )
            event = {
                "type": "incident_closed",
                "incident_id": open_inc.id,
                "device_id": device_id,
                "check_id": check_id,
                "ts": ts.isoformat() + "Z",
            }

    return event

