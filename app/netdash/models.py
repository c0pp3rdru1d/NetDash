from __future__ import annotations

from datetime import datetime
from typing import Optional, Dict, Any
from sqlmodel import SQLModel, Field, Column
from sqlalchemy import JSON


class Device(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    host: str  # IP or DNS
    site: str = "default"
    tags: str = ""  # comma-separated
    enabled: bool = True


class Check(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    device_id: int = Field(foreign_key="device.id", index=True)
    kind: str  # "ping" | "http" | "tcp" | ...
    interval_s: int = 30
    timeout_s: float = 2.0
    # You can store incident thresholds in here, e.g. open_after_downs/close_after_ups
    params: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))


class Result(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    check_id: int = Field(index=True)
    ts: datetime = Field(default_factory=datetime.utcnow, index=True)
    status: str  # "up" | "down" | "degraded"
    latency_ms: Optional[float] = None
    details: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))


class AlertEvent(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    ts: datetime = Field(default_factory=datetime.utcnow, index=True)
    device_id: int = Field(index=True)
    check_id: int = Field(index=True)
    severity: str = "warn"  # "info"|"warn"|"crit"
    message: str
    meta: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))


class Incident(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)

    device_id: int = Field(index=True)
    check_id: int = Field(index=True)

    state: str = Field(default="open", index=True)  # "open"|"closed"
    opened_ts: datetime = Field(default_factory=datetime.utcnow, index=True)
    closed_ts: Optional[datetime] = Field(default=None, index=True)

    open_reason: str = "down_streak"
    close_reason: str = "up_streak"

    meta: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))

