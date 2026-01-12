from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from .db import init_db, add_host, list_hosts, write_ping, latest_status
from .ping import ping_once


def _default_db_path() -> Path:
    # project-root-ish default: ./data/netdash.db
    return Path("data") / "netdash.db"


async def cmd_init(args: argparse.Namespace) -> int:
    await init_db(args.db)
    print(f"Initialized DB at {args.db}")
    return 0


async def cmd_add_host(args: argparse.Namespace) -> int:
    await init_db(args.db)
    await add_host(args.db, args.host)
    print(f"Added host: {args.host}")
    return 0


async def cmd_list_hosts(args: argparse.Namespace) -> int:
    await init_db(args.db)
    hosts = await list_hosts(args.db)
    if not hosts:
        print("(no hosts yet)")
        return 0
    for h in hosts:
        print(h)
    return 0


async def cmd_ping(args: argparse.Namespace) -> int:
    await init_db(args.db)
    result = await ping_once(args.host, timeout_s=args.timeout)
    await write_ping(args.db, result.host, result.ok, result.rtt_ms, result.error)

    status = "OK" if result.ok else "FAIL"
    rtt = f"{result.rtt_ms:.1f}ms" if result.rtt_ms is not None else "-"
    err = f" | {result.error}" if result.error else ""
    print(f"{result.host}: {status} rtt={rtt}{err}")
    return 0 if result.ok else 2


async def cmd_run(args: argparse.Namespace) -> int:
    await init_db(args.db)
    hosts = await list_hosts(args.db)
    if not hosts:
        print("No hosts in DB. Add one with: netdash add-host <hostname>")
        return 1

    print(f"Monitoring {len(hosts)} hosts every {args.interval}s. Ctrl+C to stop.")
    try:
        while True:
            # fan out pings concurrently
            results = await asyncio.gather(*(ping_once(h, timeout_s=args.timeout) for h in hosts))
            for r in results:
                await write_ping(args.db, r.host, r.ok, r.rtt_ms, r.error)
                status = "OK" if r.ok else "FAIL"
                rtt = f"{r.rtt_ms:.1f}ms" if r.rtt_ms is not None else "-"
                print(f"{r.host:30} {status:4}  rtt={rtt}")
            print("-" * 60)
            await asyncio.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nStopped.")
        return 0


async def cmd_status(args: argparse.Namespace) -> int:
    await init_db(args.db)
    rows = await latest_status(args.db, limit=args.limit)
    if not rows:
        print("(no results yet)")
        return 0

    for host, ok, rtt_ms, ts, error in rows:
        status = "OK" if ok else "FAIL"
        rtt = f"{rtt_ms:.1f}ms" if rtt_ms is not None else "-"
        err = f" | {error}" if error else ""
        print(f"{ts}  {host:30} {status:4} rtt={rtt}{err}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="netdash", description="NetDash - minimal network monitor scaffold")
    p.add_argument("--db", type=Path, default=_default_db_path(), help="Path to SQLite DB (default: data/netdash.db)")

    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init-db", help="Initialize the SQLite DB")
    s.set_defaults(func=cmd_init)

    s = sub.add_parser("add-host", help="Add a host to monitor")
    s.add_argument("host", help="Hostname or IP")
    s.set_defaults(func=cmd_add_host)

    s = sub.add_parser("list-hosts", help="List monitored hosts")
    s.set_defaults(func=cmd_list_hosts)

    s = sub.add_parser("ping", help="Ping a host once and store the result")
    s.add_argument("host", help="Hostname or IP")
    s.add_argument("--timeout", type=int, default=1, help="Ping timeout seconds (default 1)")
    s.set_defaults(func=cmd_ping)

    s = sub.add_parser("run", help="Run the monitor loop (ping all hosts repeatedly)")
    s.add_argument("--interval", type=int, default=10, help="Seconds between checks (default 10)")
    s.add_argument("--timeout", type=int, default=1, help="Ping timeout seconds (default 1)")
    s.set_defaults(func=cmd_run)

    s = sub.add_parser("status", help="Show latest stored results")
    s.add_argument("--limit", type=int, default=30, help="Rows to show (default 30)")
    s.set_defaults(func=cmd_status)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return asyncio.run(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())

