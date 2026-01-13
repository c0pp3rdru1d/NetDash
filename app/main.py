from __future__ import annotations

import asyncio
from fastapi import FastAPI, WebSocket
from nicegui import ui
import uvicorn
from sqlmodel import select

from .db import init_db, session_scope
from .models import Device, Check
from .api import router as api_router
from .ws import WebSocketHub
from .scheduler import MonitorScheduler

hub = WebSocketHub()
scheduler = MonitorScheduler(hub)

app = FastAPI(title="NetDash")
app.include_router(api_router)


@app.on_event("startup")
async def startup() -> None:
    init_db()

    with session_scope() as s:
        if not s.exec(select(Device)).first():
            d1 = Device(name="Localhost", host="127.0.0.1", site="Lab", tags="demo")
            d2 = Device(name="Google DNS", host="8.8.8.8", site="WAN", tags="public")
            s.add(d1)
            s.add(d2)
            s.commit()
            s.refresh(d1)
            s.refresh(d2)

            s.add(Check(device_id=d1.id, kind="ping", interval_s=10, timeout_s=2, params={"count": 1}))
            s.add(Check(device_id=d2.id, kind="ping", interval_s=10, timeout_s=2, params={"count": 1}))
            s.commit()

    await scheduler.start()


@app.on_event("shutdown")
async def shutdown() -> None:
    await scheduler.stop()


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await hub.connect(ws)
    try:
        while True:
            await ws.receive_text()
    except asyncio.CancelledError:
        pass
    except Exception:
        pass
    finally:
        await hub.disconnect(ws)


@ui.page("/")
async def index():
    from .ui import build_ui
    await build_ui(api_base="http://localhost:8000", ws_url="ws://localhost:8000/ws")


def main() -> None:
    ui.run_with(app)

    config = uvicorn.Config(
        app=app,
        host="0.0.0.0",
        port=8000,
        log_level="info",
        ws="auto",
    )
    server = uvicorn.Server(config)

    try:
        server.run()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

