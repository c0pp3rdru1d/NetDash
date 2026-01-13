from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Dict

from sqlmodel import select

from .db import session_scope
from .models import Device, Check, Result
from .checks import CHECKS
from .ws import WebSocketHub
from .alerts import maybe_emit_down_alert
from .incident_engine import process_status_transition


class MonitorScheduler:
    def __init__(self, hub: WebSocketHub) -> None:
        self.hub = hub
        self._tasks: Dict[int, asyncio.Task] = {}
        self._stop = asyncio.Event()

        # check_id -> {"down": int, "up": int}
        self._streaks: Dict[int, Dict[str, int]] = {}

        # Defaults that work well for Wi-Fi-ish targets
        self.open_after_downs_default = 3
        self.close_after_ups_default = 2

    async def start(self) -> None:
        self._stop.clear()
        await self.reload()

    async def stop(self) -> None:
        self._stop.set()

        tasks = list(self._tasks.values())
        self._tasks.clear()

        for t in tasks:
            t.cancel()

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def reload(self) -> None:
        old = list(self._tasks.values())
        self._tasks.clear()
        for t in old:
            t.cancel()
        if old:
            await asyncio.gather(*old, return_exceptions=True)

        with session_scope() as s:
            checks = s.exec(select(Check)).all()
            devices = {d.id: d for d in s.exec(select(Device)).all()}

        for chk in checks:
            dev = devices.get(chk.device_id)
            if not dev or not dev.enabled:
                continue
            self._tasks[chk.id] = asyncio.create_task(self._run_check_loop(dev, chk))

    def _update_streaks(self, check_id: int, status: str) -> Dict[str, int]:
        st = self._streaks.setdefault(check_id, {"down": 0, "up": 0})

        if status == "down":
            st["down"] += 1
            st["up"] = 0
        else:
            st["up"] += 1
            st["down"] = 0

        return st

    async def _run_check_loop(self, dev: Device, chk: Check) -> None:
        checker = CHECKS.get(chk.kind)
        if not checker:
            return

        try:
            await asyncio.sleep(min(1.5, chk.interval_s / 10))
        except asyncio.CancelledError:
            return

        open_after_downs = int(chk.params.get("open_after_downs", self.open_after_downs_default))
        close_after_ups = int(chk.params.get("close_after_ups", self.close_after_ups_default))

        try:
            while not self._stop.is_set():
                outcome = await checker.run(dev.host, chk.timeout_s, chk.params)
                ts = datetime.utcnow()

                res = Result(
                    check_id=chk.id,
                    ts=ts,
                    status=outcome.status,
                    latency_ms=outcome.latency_ms,
                    details=outcome.details,
                )

                with session_scope() as s:
                    s.add(res)
                    s.commit()

                st = self._update_streaks(chk.id, outcome.status)

                inc_event = process_status_transition(
                    device_id=dev.id,
                    check_id=chk.id,
                    ts=ts,
                    status=outcome.status,
                    down_streak=st["down"],
                    up_streak=st["up"],
                    open_after_downs=open_after_downs,
                    close_after_ups=close_after_ups,
                )

                maybe_emit_down_alert(check_id=chk.id, device_id=dev.id)

                await self.hub.broadcast_json({
                    "type": "result",
                    "device_id": dev.id,
                    "device_name": dev.name,
                    "host": dev.host,
                    "site": dev.site,
                    "check_id": chk.id,
                    "kind": chk.kind,
                    "ts": ts.isoformat() + "Z",
                    "status": outcome.status,
                    "latency_ms": outcome.latency_ms,
                    "details": outcome.details,
                    "down_streak": st["down"],
                    "up_streak": st["up"],
                })

                if inc_event:
                    await self.hub.broadcast_json(inc_event)

                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=chk.interval_s)
                except asyncio.TimeoutError:
                    pass

        except asyncio.CancelledError:
            return
        except Exception as e:
            await self.hub.broadcast_json({
                "type": "scheduler_error",
                "device_id": dev.id,
                "check_id": chk.id,
                "kind": chk.kind,
                "error": str(e),
            })
            return

