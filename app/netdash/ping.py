from __future__ import annotations

import asyncio
import sys
import re
from datetime import datetime
from .models import PingResult


_RTT_RE = re.compile(r"time[=<]\s*(\d+(?:\.\d+)?)\s*ms", re.IGNORECASE)


async def ping_once(host: str, timeout_s: int = 1) -> PingResult:
    host = host.strip()
    if not host:
        return PingResult(host=host, ok=False, rtt_ms=None, ts=datetime.utcnow(), error="empty host")

    if sys.platform.startswith("win"):
        # -n 1 = one echo request, -w timeout(ms)
        cmd = ["ping", "-n", "1", "-w", str(timeout_s * 1000), host]
    else:
        # -c 1 = one packet, -W timeout(s) (Linux). macOS uses -W in ms; we can refine later.
        cmd = ["ping", "-c", "1", "-W", str(timeout_s), host]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out_b, err_b = await proc.communicate()
        out = (out_b or b"").decode(errors="replace")
        err = (err_b or b"").decode(errors="replace").strip()

        ok = proc.returncode == 0

        rtt = None
        m = _RTT_RE.search(out)
        if m:
            try:
                rtt = float(m.group(1))
            except ValueError:
                rtt = None

        return PingResult(
            host=host,
            ok=ok,
            rtt_ms=rtt,
            ts=datetime.utcnow(),
            error=err if (err and not ok) else None,
        )
    except FileNotFoundError:
        return PingResult(host=host, ok=False, rtt_ms=None, ts=datetime.utcnow(), error="ping command not found")
    except Exception as e:
        return PingResult(host=host, ok=False, rtt_ms=None, ts=datetime.utcnow(), error=str(e))



