from __future__ import annotations

from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException
from sqlmodel import select

from .db import session_scope
from .models import Device, Check, Result, AlertEvent, Incident

router = APIRouter(prefix="/api")


@router.get("/devices")
def list_devices():
    with session_scope() as s:
        return s.exec(select(Device)).all()


@router.post("/devices")
def create_device(device: Device):
    with session_scope() as s:
        s.add(device)
        s.commit()
        s.refresh(device)
        return device


@router.get("/devices/{device_id}/checks")
def list_checks(device_id: int):
    with session_scope() as s:
        dev = s.get(Device, device_id)
        if not dev:
            raise HTTPException(404, "device not found")
        return s.exec(select(Check).where(Check.device_id == device_id)).all()


@router.post("/checks")
def create_check(check: Check):
    with session_scope() as s:
        dev = s.get(Device, check.device_id)
        if not dev:
            raise HTTPException(404, "device not found")
        s.add(check)
        s.commit()
        s.refresh(check)
        return check


@router.get("/results/recent")
def recent_results(minutes: int = 60):
    since = datetime.utcnow() - timedelta(minutes=max(1, minutes))
    with session_scope() as s:
        return s.exec(
            select(Result).where(Result.ts >= since).order_by(Result.ts.desc()).limit(5000)
        ).all()


@router.get("/alerts")
def list_alerts(limit: int = 200):
    with session_scope() as s:
        return s.exec(
            select(AlertEvent).order_by(AlertEvent.ts.desc()).limit(min(1000, limit))
        ).all()


@router.get("/incidents")
def list_incidents(state: str = "open", limit: int = 200):
    state = state.lower()
    if state not in ("open", "closed", "all"):
        raise HTTPException(400, "state must be open|closed|all")

    with session_scope() as s:
        q = select(Incident).order_by(Incident.opened_ts.desc())
        if state != "all":
            q = q.where(Incident.state == state)
        return s.exec(q.limit(min(1000, limit))).all()


@router.get("/uptime/summary")
def uptime_summary(minutes: int = 1440):
    """
    Returns per-device availability over the last N minutes.
    Availability definition:
      - up/degraded count as available
      - down counts as unavailable
    """
    minutes = max(5, int(minutes))
    since = datetime.utcnow() - timedelta(minutes=minutes)

    with session_scope() as s:
        devices = s.exec(select(Device)).all()
        checks = s.exec(select(Check)).all()
        check_to_device = {c.id: c.device_id for c in checks}
        results = s.exec(select(Result).where(Result.ts >= since)).all()

    per_device = {
        d.id: {
            "device_id": d.id,
            "device_name": d.name,
            "site": d.site,
            "available": 0,
            "total": 0,
        }
        for d in devices
    }

    for r in results:
        dev_id = check_to_device.get(r.check_id)
        if dev_id is None:
            continue
        per_device[dev_id]["total"] += 1
        if r.status in ("up", "degraded"):
            per_device[dev_id]["available"] += 1

    rows = []
    for _, agg in per_device.items():
        total = agg["total"]
        avail = agg["available"]
        pct = (avail / total * 100.0) if total else 0.0
        rows.append({
            **agg,
            "uptime_pct": round(pct, 2),
            "window_minutes": minutes,
        })

    rows.sort(key=lambda x: (x["total"] == 0, x["uptime_pct"]))
    return rows

