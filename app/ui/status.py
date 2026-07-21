#!/usr/bin/env python3
"""
MNXMC Design System — Header Status Collector

공통 헤더(AppHeader)의 Service/Alarm/Health 지표를 실제 시스템 상태로 채운다.
systemctl 로 MNX 핵심 서비스 상태를 수집하고, 다운 서비스 수로 알람/헬스를 계산한다.

- 짧은 캐시(기본 5초)로 화면 전환 시 중복 수집을 방지한다.
- 블로킹 호출이므로 호출부(AppHeader)에서 스레드로 오프로드한다.
"""

from __future__ import annotations

import subprocess
import time

# MNX 핵심 서비스 (service.py 의 SERVICES 유닛과 일치)
MNX_SERVICES = [
    "mnx_service_control.service",
    "eng_monitor.service",
    "mnx_payload.service",
    "mnx_payload_ai.service",
    "mnx_payload_scan.service",
    "mnxcapture.service",
    "mnxdpi.service",
    "suricata.service",
    "elasticsearch-node-1.service",
    "elasticsearch-node-2.service",
    "kafka.service",
    "zookeeper.service",
]

# 다운 시 즉시 CRITICAL 로 간주하는 데이터플레인 핵심 서비스
CRITICAL_SERVICES = {
    "mnxcapture.service",
    "mnxdpi.service",
    "elasticsearch-node-1.service",
    "kafka.service",
}

_CACHE: dict = {"ts": 0.0, "data": None}
_CACHE_TTL = 5.0  # seconds


def collect_service_status(force: bool = False) -> dict:
    """
    MNX 서비스 상태를 수집해 헤더 지표를 반환한다.

    Returns:
        {
          "svc_ok": int,      # active 서비스 수
          "svc_total": int,   # 전체 서비스 수
          "alarms": int,      # 비활성(다운) 서비스 수 = 알람 수
          "health": str,      # "ok" | "warn" | "crit"
          "down": list[str],  # 다운된 유닛
        }
    """
    now = time.monotonic()
    if not force and _CACHE["data"] is not None and (now - _CACHE["ts"]) < _CACHE_TTL:
        return _CACHE["data"]

    ok = 0
    down: list[str] = []
    for unit in MNX_SERVICES:
        try:
            r = subprocess.run(
                ["systemctl", "is-active", unit],
                capture_output=True, text=True, timeout=4,
            )
            active = r.stdout.strip() == "active"
        except Exception:
            active = False
        if active:
            ok += 1
        else:
            down.append(unit)

    total = len(MNX_SERVICES)
    alarms = len(down)
    if alarms == 0:
        health = "ok"
    elif any(u in CRITICAL_SERVICES for u in down):
        health = "crit"
    else:
        health = "warn"

    data = {
        "svc_ok": ok,
        "svc_total": total,
        "alarms": alarms,
        "health": health,
        "down": down,
    }
    _CACHE["ts"] = now
    _CACHE["data"] = data
    return data
