"""前端查询接口 /api/v1/*（FR-11）。

统一响应体：``{"code": 0, "message": "ok", "data": ...}``；
出错时 ``code`` 取 HTTP 状态码（400/404/500），``data`` 为 null。
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from backend import storage

logger = logging.getLogger("iot.api")

router = APIRouter(prefix="/api/v1", tags=["api"])

# NFR-02：超过 2 个上报周期（环境 ≤ 30 s）无数据即判离线
ONLINE_TIMEOUT_SECONDS = 60


def _ok(data) -> dict:
    return {"code": 0, "message": "ok", "data": data}


def _parse_ts(value: str) -> datetime:
    """解析 ISO 8601 时间文本，统一转成 UTC 时区。"""
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _is_online(last_seen_at: Optional[str]) -> bool:
    if not last_seen_at:
        return False
    try:
        last_seen = _parse_ts(last_seen_at)
    except ValueError:
        logger.warning("无法解析上报时间: %r", last_seen_at)
        return False
    return (datetime.now(timezone.utc) - last_seen).total_seconds() <= ONLINE_TIMEOUT_SECONDS


def _validate_time_range(start: Optional[str], end: Optional[str]) -> None:
    parsed = {}
    for name, value in (("start", start), ("end", end)):
        if value is None:
            continue
        try:
            parsed[name] = _parse_ts(value)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"{name} 不是合法的 ISO 8601 时间: {value}")
    if len(parsed) == 2 and parsed["start"] > parsed["end"]:
        raise HTTPException(status_code=400, detail="start 不能晚于 end")


def _downsample(rows: list[dict], points: int) -> list[dict]:
    """把历史点按数量分桶求均值，桶内时间取第一个点（降采样）。"""
    if len(rows) <= points:
        return rows
    result = []
    total = len(rows)
    for index in range(points):
        bucket = rows[index * total // points : (index + 1) * total // points]
        values = [row["value"] for row in bucket if row["value"] is not None]
        result.append(
            {
                "time": bucket[0]["time"],
                "value": sum(values) / len(values) if values else None,
            }
        )
    return result


@router.get("/devices")
def list_devices():
    """设备列表与在线状态。"""
    devices = []
    for item in storage.query_devices():
        if item["has_env"] and item["has_bed"]:
            device_type = "combined"
        elif item["has_env"]:
            device_type = "env"
        else:
            device_type = "bed"
        devices.append(
            {
                "device_id": item["device_id"],
                "device_type": device_type,
                "online": _is_online(item["last_seen_at"]),
                "last_seen_at": item["last_seen_at"],
            }
        )
    return _ok(devices)


@router.get("/devices/{device_id}/latest")
def latest_data(device_id: str):
    """设备最新一条环境数据与卧床数据。"""
    env = storage.query_latest(device_id, "env_readings")
    bed = storage.query_latest(device_id, "bed_monitor_readings")
    if env is None and bed is None:
        raise HTTPException(status_code=404, detail=f"设备 {device_id} 无上报数据")
    last_seen_at = max(
        record["received_at"] for record in (env, bed) if record is not None
    )
    return _ok(
        {
            "device_id": device_id,
            "online": _is_online(last_seen_at),
            "last_seen_at": last_seen_at,
            "env": env,
            "bed": bed,
        }
    )

# 支持历史曲线查询（降采样）
@router.get("/devices/{device_id}/history")
def history(
    device_id: str,
    metric: str = Query(..., description="指标名，见 storage.METRICS"),
    start: Optional[str] = Query(None, description="起始时间 ISO 8601"),
    end: Optional[str] = Query(None, description="结束时间 ISO 8601"),
    points: int = Query(200, ge=2, le=1000, description="降采样后的点数上限"),
):
    """历史曲线（降采样）。"""
    spec = storage.METRICS.get(metric)
    if spec is None:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的 metric: {metric}，可选: {', '.join(sorted(storage.METRICS))}",
        )
    table, column, unit = spec
    _validate_time_range(start, end)
    rows = storage.query_history(device_id, table, column, start, end)
    return _ok(
        {
            "device_id": device_id,
            "metric": metric,
            "unit": unit,
            "count": len(rows),
            "points": _downsample(rows, points),
        }
    )


@router.get("/bed/state")
def bed_state(device_id: Optional[str] = Query(None, description="设备 ID，缺省取最近上报")):
    """床位状态。

    压力板提供 bedState，加速度板提供运动信息。两台设备异步上报，
    这里各取最新一帧原样返回；某一侧没有数据时对应字段为 null。
    """
    pressure = storage.query_latest_bed(device_id, "bed_state")
    accel = storage.query_latest_bed(device_id, "accel_x")
    if pressure is None and accel is None:
        raise HTTPException(status_code=404, detail="无床体数据")
    records = [record for record in (pressure, accel) if record is not None]
    last_seen_at = max(record["received_at"] for record in records)
    return _ok(
        {
            "device_id": device_id or records[0]["device_id"],
            "bed_state": pressure["bed_state"] if pressure else None,
            "online": _is_online(last_seen_at),
            "last_seen_at": last_seen_at,
            "pressure": pressure,
            "accel": accel,
        }
    )


@router.get("/bed/events")
def bed_events(
    device_id: Optional[str] = Query(None, description="设备 ID，缺省查全部设备"),
    start: Optional[str] = Query(None, description="起始时间 ISO 8601"),
    end: Optional[str] = Query(None, description="结束时间 ISO 8601"),
    limit: int = Query(50, ge=1, le=500),
):
    """体动事件记录（FR-02）。"""
    _validate_time_range(start, end)
    total, items = storage.query_bed_events(device_id, start, end, limit)
    return _ok({"total": total, "items": items})
