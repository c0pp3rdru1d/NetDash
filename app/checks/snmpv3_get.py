from __future__ import annotations

import os
import time
from typing import Any, Dict

from pysnmp.hlapi.asyncio import (
    SnmpEngine,
    UsmUserData,
    UdpTransportTarget,
    ContextData,
    ObjectType,
    ObjectIdentity,
    getCmd,
    usmHMACMD5AuthProtocol,
    usmHMACSHAAuthProtocol,
    usmNoAuthProtocol,
    usmNoPrivProtocol,
    usmDESPrivProtocol,
    usmAesCfb128Protocol,
)

from .base import BaseCheck, CheckOutcome


_AUTH = {
    "NONE": usmNoAuthProtocol,
    "MD5": usmHMACMD5AuthProtocol,
    "SHA": usmHMACSHAAuthProtocol,
}

_PRIV = {
    "NONE": usmNoPrivProtocol,
    "DES": usmDESPrivProtocol,
    "AES": usmAesCfb128Protocol,  # AES-128
}


def _resolve_secret(value: Any) -> Any:
    """
    Allows params like "env:SONICWALL_SNMP_AUTH" to pull from environment variables.
    """
    if isinstance(value, str) and value.startswith("env:"):
        key = value.split("env:", 1)[1].strip()
        return os.environ.get(key, "")
    return value


class SNMPv3GetCheck(BaseCheck):
    kind = "snmpv3_get"

    async def run(self, host: str, timeout_s: float, params: Dict[str, Any]) -> CheckOutcome:
        # NOTE: host should be an IP/DNS like "192.168.10.1" (not "https://...")
        port = int(params.get("port", 161))
        username = _resolve_secret(params.get("username", ""))
        auth_key = _resolve_secret(params.get("auth_key", ""))
        priv_key = _resolve_secret(params.get("priv_key", ""))
        auth_proto = _AUTH.get(str(params.get("auth_proto", "SHA")).upper(), usmHMACSHAAuthProtocol)
        priv_proto = _PRIV.get(str(params.get("priv_proto", "AES")).upper(), usmAesCfb128Protocol)

        # Minimal safe defaults: require auth+priv unless you explicitly set NONE
        if not username:
            return CheckOutcome("down", None, {"error": "missing username"})

        oids = params.get("oids") or [
            "1.3.6.1.2.1.1.3.0",   # sysUpTime.0
            "1.3.6.1.2.1.1.5.0",   # sysName.0
        ]
        context_name = params.get("context_name", "")

        # Build SNMPv3 user
        user = UsmUserData(
            userName=str(username),
            authKey=str(auth_key) if auth_key else None,
            privKey=str(priv_key) if priv_key else None,
            authProtocol=auth_proto if auth_key else usmNoAuthProtocol,
            privProtocol=priv_proto if priv_key else usmNoPrivProtocol,
        )

        t0 = time.perf_counter()
        try:
            engine = SnmpEngine()
            target = UdpTransportTarget((host, port), timeout=float(timeout_s), retries=0)
            context = ContextData(contextName=context_name) if context_name else ContextData()

            var_binds = [ObjectType(ObjectIdentity(str(oid))) for oid in oids]

            error_indication, error_status, error_index, binds = await getCmd(
                engine, user, target, context, *var_binds
            )

            latency_ms = (time.perf_counter() - t0) * 1000.0

            if error_indication:
                return CheckOutcome("down", None, {"error": str(error_indication)})

            if error_status:
                return CheckOutcome(
                    "degraded",
                    latency_ms,
                    {"error": f"{error_status.prettyPrint()} at {int(error_index)}"},
                )

            values: Dict[str, Any] = {}
            for oid, val in binds:
                values[str(oid)] = val.prettyPrint()

            return CheckOutcome("up", latency_ms, {"port": port, "values": values})

        except Exception as e:
            return CheckOutcome("down", None, {"error": str(e), "port": port})

