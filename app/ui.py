from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from typing import Dict, Any, Deque

from nicegui import ui
import httpx


class DashboardState:
    def __init__(self) -> None:
        self.latest_by_device: Dict[int, Dict[str, Any]] = {}
        self.feed: Deque[Dict[str, Any]] = deque(maxlen=200)


async def build_ui(api_base: str, ws_url: str) -> None:
    state = DashboardState()

    ui.dark_mode().enable()

    ui.add_head_html("""
    <style>
      .card { border-radius: 16px; }
      .mono { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace; }
      .pill { padding: 2px 10px; border-radius: 999px; font-size: 12px; }
    </style>
    """)

    async def api_get(path: str):
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{api_base}{path}")
            r.raise_for_status()
            return r.json()

    with ui.row().classes("w-full items-center justify-between"):
        ui.label("NetDash").classes("text-2xl font-bold")
        ui.label("Network Monitoring Dashboard").classes("opacity-70")

    total_lbl = ui.label("0").classes("text-3xl font-bold")
    up_lbl = ui.label("0").classes("text-3xl font-bold")
    down_lbl = ui.label("0").classes("text-3xl font-bold")
    degr_lbl = ui.label("0").classes("text-3xl font-bold")

    def status_pill(status: str) -> str:
        if status == "up":
            return '<span class="pill bg-green-600 text-white">UP</span>'
        if status == "down":
            return '<span class="pill bg-red-600 text-white">DOWN</span>'
        if status == "degraded":
            return '<span class="pill bg-yellow-600 text-black">DEGRADED</span>'
        return '<span class="pill bg-gray-600 text-white">UNKNOWN</span>'

    with ui.row().classes("w-full gap-4"):
        with ui.card().classes("card p-4 w-1/4"):
            ui.label("Devices").classes("opacity-70")
            total_lbl
        with ui.card().classes("card p-4 w-1/4"):
            ui.label("Up").classes("opacity-70")
            up_lbl
        with ui.card().classes("card p-4 w-1/4"):
            ui.label("Down").classes("opacity-70")
            down_lbl
        with ui.card().classes("card p-4 w-1/4"):
            ui.label("Degraded").classes("opacity-70")
            degr_lbl

    columns = [
        {"name": "name", "label": "Device", "field": "name", "align": "left"},
        {"name": "host", "label": "Host", "field": "host", "align": "left"},
        {"name": "site", "label": "Site", "field": "site", "align": "left"},
        {"name": "status", "label": "Status", "field": "status_html", "align": "left"},
        {"name": "latency", "label": "Latency (ms)", "field": "latency", "align": "right"},
        {"name": "last", "label": "Last Seen", "field": "last_seen", "align": "left"},
    ]
    table = ui.table(columns=columns, rows=[], row_key="id").classes("w-full").props("dense flat")

    feed_box = ui.column().classes("w-full gap-2")
    alerts_box = ui.column().classes("w-full gap-2")
    incidents_box = ui.column().classes("w-full gap-2")
    uptime_box = ui.column().classes("w-full gap-2")

    def recompute_counts() -> None:
        total = len(state.latest_by_device)
        counts = defaultdict(int)
        for v in state.latest_by_device.values():
            counts[v.get("status", "unknown")] += 1
        total_lbl.set_text(str(total))
        up_lbl.set_text(str(counts["up"]))
        down_lbl.set_text(str(counts["down"]))
        degr_lbl.set_text(str(counts["degraded"]))

    def render_table() -> None:
        rows = []
        for dev_id, v in sorted(state.latest_by_device.items(), key=lambda kv: kv[1].get("name", "")):
            rows.append({
                "id": dev_id,
                "name": v.get("name", "?"),
                "host": v.get("host", "?"),
                "site": v.get("site", "default"),
                "status_html": status_pill(v.get("status", "unknown")),
                "latency": "" if v.get("latency_ms") is None else f"{v['latency_ms']:.0f}",
                "last_seen": v.get("ts", ""),
            })
        table.rows = rows
        table.update()

    def render_feed() -> None:
        feed_box.clear()
        for item in list(state.feed)[-12:][::-1]:
            ts = item.get("ts", "")
            msg = f"{item.get('device_name','?')} • {item.get('kind','?')} • {item.get('status','?')}"
            with feed_box:
                with ui.card().classes("card p-3 w-full"):
                    ui.html(f"<div class='mono opacity-70'>{ts}</div>")
                    ui.html(f"<div class='mono'>{msg}</div>")

    async def refresh_alerts() -> None:
        data = await api_get("/api/alerts?limit=50")
        alerts_box.clear()
        with alerts_box:
            for a in data[:10]:
                with ui.card().classes("card p-3 w-full"):
                    ui.html(f"<div class='mono opacity-70'>{a['ts']}</div>")
                    ui.html(f"<div class='mono'>{a['severity'].upper()} • {a['message']}</div>")

    async def refresh_incidents() -> None:
        data = await api_get("/api/incidents?state=open&limit=50")
        incidents_box.clear()
        with incidents_box:
            if not data:
                ui.label("No active incidents").classes("opacity-70")
                return
            for inc in data[:10]:
                with ui.card().classes("card p-3 w-full"):
                    ui.html(f"<div class='mono opacity-70'>Opened: {inc['opened_ts']}</div>")
                    ui.html(f"<div class='mono'>Device ID {inc['device_id']} • Check ID {inc['check_id']} • STATE: OPEN</div>")

    async def refresh_uptime() -> None:
        data = await api_get("/api/uptime/summary?minutes=1440")
        uptime_box.clear()
        with uptime_box:
            shown = 0
            for row in data:
                if row["total"] == 0:
                    continue
                with ui.card().classes("card p-3 w-full"):
                    ui.html(f"<div class='mono'>{row['device_name']} • {row['site']}</div>")
                    ui.html(f"<div class='mono opacity-70'>Uptime (24h): {row['uptime_pct']}% • samples: {row['total']}</div>")
                shown += 1
                if shown >= 10:
                    break
            if shown == 0:
                ui.label("Not enough data yet for uptime summary").classes("opacity-70")

    devices = await api_get("/api/devices")
    for d in devices:
        state.latest_by_device[d["id"]] = {"name": d["name"], "host": d["host"], "site": d["site"], "status": "unknown"}

    recompute_counts()
    render_table()
    await refresh_alerts()
    await refresh_incidents()
    await refresh_uptime()

    with ui.row().classes("w-full gap-4 mt-4"):
        with ui.card().classes("card p-4 w-1/2"):
            ui.label("Live Feed").classes("font-semibold")
            render_feed()
        with ui.card().classes("card p-4 w-1/2"):
            ui.label("Alerts").classes("font-semibold")
            await refresh_alerts()

    with ui.row().classes("w-full gap-4 mt-4"):
        with ui.card().classes("card p-4 w-1/2"):
            ui.label("Active Incidents").classes("font-semibold")
            await refresh_incidents()
        with ui.card().classes("card p-4 w-1/2"):
            ui.label("Worst Uptime (24h)").classes("font-semibold")
            await refresh_uptime()

    async def on_ws_message(msg: dict) -> None:
        t = msg.get("type")

        if t == "result":
            dev_id = msg["device_id"]
            state.latest_by_device[dev_id] = {
                "name": msg["device_name"],
                "host": msg["host"],
                "site": msg.get("site", "default"),
                "status": msg["status"],
                "latency_ms": msg.get("latency_ms"),
                "ts": msg["ts"],
            }
            state.feed.append(msg)
            recompute_counts()
            render_table()
            render_feed()

        elif t in ("incident_opened", "incident_closed"):
            await refresh_incidents()

    ui.run_javascript(f"""
    window.__netdash_ws = new WebSocket("{ws_url}");
    window.__netdash_ws.onmessage = (ev) => {{
        try {{
            const data = JSON.parse(ev.data);
            window.dispatchEvent(new CustomEvent("netdash_ws", {{ detail: data }}));
        }} catch (e) {{}}
    }};
    """)

    ui.on("netdash_ws", lambda e: asyncio.create_task(on_ws_message(e.args["detail"])))

    ui.timer(10.0, lambda: asyncio.create_task(refresh_alerts()))
    ui.timer(10.0, lambda: asyncio.create_task(refresh_incidents()))
    ui.timer(30.0, lambda: asyncio.create_task(refresh_uptime()))

