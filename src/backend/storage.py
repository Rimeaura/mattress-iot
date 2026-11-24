"""SQLite 落库：按服务拆成宽表。

EnvService -> env_readings          (temperature / humidity / light / env_status)
BedMonitor -> bed_monitor_readings  (压力板 14 项 + 加速度板 8 项，按 device_id 区分)

存储位置默认是项目根目录的 data/iot.db，可用环境变量 SQLITE_PATH 覆盖。
"""

import logging
import os
import sqlite3
import threading
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("iot.storage")
#path（__file__ 是当前模块的文件路径, resolve() 解析为绝对路径, parents[2] 是上一级目录）
_DEFAULT_DB = Path(__file__).resolve().parents[2] / "data" / "iot.db"

#expanduser() 是展开 ~ 为用户目录，起到兼容不同平台的路径格式的作用
def _db_path() -> Path:
    """每次取路径，保证 .env / 环境变量在导入之后再加载也能生效。"""
    return Path(os.getenv("SQLITE_PATH", str(_DEFAULT_DB))).expanduser()


SCHEMA = """
CREATE TABLE IF NOT EXISTS env_readings (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id   TEXT    NOT NULL,
    temperature REAL,
    humidity    REAL,
    light       INTEGER,
    env_status  INTEGER,
    event_time  TEXT,
    received_at TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_env_device_time
    ON env_readings (device_id, received_at);

CREATE TABLE IF NOT EXISTS bed_monitor_readings (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id          TEXT    NOT NULL,
    bed_state          TEXT,
    load_presence      TEXT,
    confidence         TEXT,
    last_event         TEXT,
    alert_type         TEXT,
    sensor_status      TEXT,
    head_shoulder_raw  INTEGER,
    head_shoulder_net  INTEGER,
    waist_hip_raw      INTEGER,
    waist_hip_net      INTEGER,
    total_net_pressure INTEGER,
    waist_hip_ratio    REAL,
    last_event_sec     INTEGER,
    run_sec            INTEGER,
    accel_x            INTEGER,
    accel_y            INTEGER,
    accel_z            INTEGER,
    motion_peak_mg     INTEGER,
    motion_state       TEXT,
    motion_count_10s   INTEGER,
    event_time         TEXT,
    received_at        TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_bed_monitor_device_time
    ON bed_monitor_readings (device_id, received_at);
"""

# 指标名 -> (表名, 列名, 单位)；查询接口的 metric 白名单，为了
METRICS = {
    "temperature": ("env_readings", "temperature", "℃"),
    "humidity": ("env_readings", "humidity", "%RH"),
    "light": ("env_readings", "light", "lux"),
    "env_status": ("env_readings", "env_status", None),
    "accel_x": ("bed_monitor_readings", "accel_x", None),
    "accel_y": ("bed_monitor_readings", "accel_y", None),
    "accel_z": ("bed_monitor_readings", "accel_z", None),
    "motion_peak_mg": ("bed_monitor_readings", "motion_peak_mg", "0.001g"),
    "motion_count_10s": ("bed_monitor_readings", "motion_count_10s", "次"),
    "head_shoulder_raw": ("bed_monitor_readings", "head_shoulder_raw", "码"),
    "head_shoulder_net": ("bed_monitor_readings", "head_shoulder_net", "码"),
    "waist_hip_raw": ("bed_monitor_readings", "waist_hip_raw", "码"),
    "waist_hip_net": ("bed_monitor_readings", "waist_hip_net", "码"),
    "total_net_pressure": ("bed_monitor_readings", "total_net_pressure", "码"),
    "waist_hip_ratio": ("bed_monitor_readings", "waist_hip_ratio", None),
    "run_sec": ("bed_monitor_readings", "run_sec", "秒"),
    "last_event_sec": ("bed_monitor_readings", "last_event_sec", "秒"),
}

# 加速度板运动状态取值（FR-02），用于筛选体动事件
MOTION_STATES = ("MOVING",)


def _to_int(value):
    return int(float(value))


# 服务名 -> (表名, {属性名: (列名, 类型转换)})
SERVICE_TABLES = {
    "EnvService": (
        "env_readings",
        {
            "temperature": ("temperature", float),
            "humidity": ("humidity", float),
            "light": ("light", _to_int),
            "env_status": ("env_status", _to_int),
        },
    ),
    "BedMonitor": (
        "bed_monitor_readings",
        {
            "bedState": ("bed_state", str),
            "loadPresence": ("load_presence", str),
            "confidence": ("confidence", str),
            "lastEvent": ("last_event", str),
            "alertType": ("alert_type", str),
            "sensorStatus": ("sensor_status", str),
            "headShoulderRaw": ("head_shoulder_raw", _to_int),
            "headShoulderNet": ("head_shoulder_net", _to_int),
            "waistHipRaw": ("waist_hip_raw", _to_int),
            "waistHipNet": ("waist_hip_net", _to_int),
            "totalNetPressure": ("total_net_pressure", _to_int),
            "waistHipRatio": ("waist_hip_ratio", float),
            "lastEventSec": ("last_event_sec", _to_int),
            "runSec": ("run_sec", _to_int),
            "accelX": ("accel_x", _to_int),
            "accelY": ("accel_y", _to_int),
            "accelZ": ("accel_z", _to_int),
            "motionPeakMg": ("motion_peak_mg", _to_int),
            "motionState": ("motion_state", str),
            "motionCount10s": ("motion_count_10s", _to_int),
        },
    ),
}

_init_lock = threading.Lock()
_initialized = False


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path(), timeout=5)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _now() -> str:
    """本地时区的 ISO 8601 文本（与 received_at 一致）。"""
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="milliseconds")


def _normalize_ts(value) -> str | None:
    """统一时间格式：IoTDA 的 yyyyMMddTHHmmssZ 或 ISO 8601 都转成带时区的 ISO 8601。

    平台给的是紧凑 UTC 格式，直接存进 SQLite 后 datetime() 解析不了，
    会导致按时间范围查询漏数据。
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None

    if len(text) == 16 and text[8] == "T" and text.endswith("Z"):
        try:
            parsed = datetime.strptime(text, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
            return parsed.isoformat(timespec="seconds")
        except ValueError:
            pass

    try:
        parsed = datetime.fromisoformat(text.replace("z", "Z").replace("Z", "+00:00"))
    except ValueError:
        logger.warning("无法解析时间 %r，按原样存储", value)
        return text
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.isoformat(timespec="milliseconds")


def init_db() -> None:
    global _initialized
    if _initialized:
        return
    with _init_lock:
        if _initialized:
            return
        db_path = _db_path()
        # 确保目录存在
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(_connect()) as conn, conn:
            conn.executescript(SCHEMA)
        _initialized = True
        logger.info("SQLite 就绪: %s", db_path)


def _convert(value, conv):
    if value is None:
        return None
    try:
        return conv(value)
    except (TypeError, ValueError):
        logger.warning("属性值 %r 无法转换为 %s，存 NULL", value, conv.__name__)
        return None


def save_services(device_id: str, services: list[dict], event_time: str | None = None) -> int:
    """把一条推送里的各服务属性写入对应宽表，返回写入行数。"""
    if not device_id or not services:
        return 0

    init_db()
    now = _now()

    pending = []
    for service in services:
        service_id = service.get("service_id")
        mapping = SERVICE_TABLES.get(service_id)
        if mapping is None:
            logger.warning("未知服务 %s，跳过落库: %s", service_id, service.get("properties"))
            continue

        table, columns = mapping
        properties = service.get("properties") or {}
        # 过滤掉未映射的属性
        unknown = set(properties) - set(columns)
        if unknown:
            logger.warning("服务 %s 有未映射属性，已忽略: %s", service_id, ", ".join(sorted(unknown)))

        row = {
            col: _convert(properties.get(prop), conv)
            for prop, (col, conv) in columns.items()
        }
        row["device_id"] = device_id
        row["event_time"] = _normalize_ts(service.get("event_time") or event_time) or now
        row["received_at"] = now
        pending.append((table, row))

    if not pending:
        return 0

    with closing(_connect()) as conn, conn:
        for table, row in pending:
            placeholders = ", ".join("?" for _ in row)
            conn.execute(
                f"INSERT INTO {table} ({', '.join(row)}) VALUES ({placeholders})",
                list(row.values()),
            )
    logger.info("已写入 %d 条服务记录", len(pending))
    return len(pending)


# ---------------------------------------------------------------------------
# 查询接口（/api/v1）使用的只读函数
# ---------------------------------------------------------------------------

_ALLOWED_TABLES = ("env_readings", "bed_monitor_readings")


def _check_table(table: str) -> None:
    """表名会拼进 SQL，限定在白名单内。"""
    if table not in _ALLOWED_TABLES:
        raise ValueError(f"不支持的表: {table}")


def _rows_to_dicts(cursor, rows) -> list[dict]:
    columns = [item[0] for item in cursor.description]
    return [dict(zip(columns, row)) for row in rows]


def query_devices() -> list[dict]:
    """设备列表：汇总两张读数表中的 device_id、最后上报时间与数据类型。

    当前没有设备注册流程，设备清单由实际上报数据派生。
    """
    init_db()
    sql = """
        SELECT device_id,
               MAX(received_at) AS last_seen_at,
               MAX(src = 'env') AS has_env,
               MAX(src = 'bed') AS has_bed
        FROM (
            SELECT device_id, received_at, 'env' AS src FROM env_readings
            UNION ALL
            SELECT device_id, received_at, 'bed' AS src FROM bed_monitor_readings
        )
        GROUP BY device_id
        ORDER BY last_seen_at DESC
    """
    with closing(_connect()) as conn:
        rows = conn.execute(sql).fetchall()
    return [
        {
            "device_id": device_id,
            "last_seen_at": last_seen_at,
            "has_env": bool(has_env),
            "has_bed": bool(has_bed),
        }
        for device_id, last_seen_at, has_env, has_bed in rows
    ]


def query_latest(device_id: str, table: str) -> dict | None:
    """指定设备在某张宽表中最新的那条记录，不含自增 id。"""
    _check_table(table)
    init_db()
    with closing(_connect()) as conn:
        cursor = conn.execute(
            "SELECT * FROM "
            f"{table} WHERE device_id = ? "
            "ORDER BY datetime(COALESCE(event_time, received_at)) DESC, id DESC LIMIT 1",
            (device_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        columns = [item[0] for item in cursor.description]
    return {column: value for column, value in zip(columns, row) if column != "id"}


def query_latest_bed(device_id: str | None = None, marker: str = "bed_state") -> dict | None:
    """床体某一类设备的最新一帧。

    marker 用非空字段区分设备：压力板用 bed_state，加速度板用 accel_x。
    某一侧没有数据时返回 None，由接口层决定如何展示。
    """
    if marker not in ("bed_state", "accel_x"):
        raise ValueError(f"不支持的标记列: {marker}")
    init_db()
    sql = f"SELECT * FROM bed_monitor_readings WHERE {marker} IS NOT NULL"
    params: list = []
    if device_id:
        sql += " AND device_id = ?"
        params.append(device_id)
    sql += " ORDER BY datetime(COALESCE(event_time, received_at)) DESC, id DESC LIMIT 1"
    with closing(_connect()) as conn:
        cursor = conn.execute(sql, params)
        row = cursor.fetchone()
        if row is None:
            return None
        columns = [item[0] for item in cursor.description]
    return {column: value for column, value in zip(columns, row) if column != "id"}


def query_history(
    device_id: str,
    table: str,
    column: str,
    start: str | None = None,
    end: str | None = None,
) -> list[dict]:
    """按时间顺序返回某指标的历史点，时间取 event_time，缺失时回退 received_at。"""
    _check_table(table)
    init_db()
    ts_expr = "COALESCE(event_time, received_at)"
    sql = (
        f"SELECT {ts_expr} AS ts, {column} AS value FROM {table} "
        f"WHERE device_id = ? AND {column} IS NOT NULL"
    )
    params: list = [device_id]
    # 时间参数为 ISO 8601 文本，交给 SQLite 的 datetime() 统一时区后比较
    if start:
        sql += f" AND datetime({ts_expr}) >= datetime(?)"
        params.append(start)
    if end:
        sql += f" AND datetime({ts_expr}) <= datetime(?)"
        params.append(end)
    sql += f" ORDER BY datetime({ts_expr}), id"
    with closing(_connect()) as conn:
        rows = conn.execute(sql, params).fetchall()
    return [{"time": ts, "value": value} for ts, value in rows]


def query_bed_events(
    device_id: str | None = None,
    start: str | None = None,
    end: str | None = None,
    limit: int = 50,
) -> tuple[int, list[dict]]:
    """体动事件：motion_state 为 MOVING 的上报记录，返回 (总数, 当前页)。"""
    init_db()
    ts_expr = "COALESCE(event_time, received_at)"
    placeholders = ", ".join("?" for _ in MOTION_STATES)
    where = f"motion_state IN ({placeholders})"
    params: list = list(MOTION_STATES)
    if device_id:
        where += " AND device_id = ?"
        params.append(device_id)
    if start:
        where += f" AND datetime({ts_expr}) >= datetime(?)"
        params.append(start)
    if end:
        where += f" AND datetime({ts_expr}) <= datetime(?)"
        params.append(end)

    with closing(_connect()) as conn:
        total = conn.execute(
            f"SELECT COUNT(*) FROM bed_monitor_readings WHERE {where}", params
        ).fetchone()[0]
        cursor = conn.execute(
            "SELECT id, device_id, motion_state, motion_count_10s, motion_peak_mg, "
            f"event_time, received_at FROM bed_monitor_readings WHERE {where} "
            f"ORDER BY datetime({ts_expr}) DESC, id DESC LIMIT ?",
            [*params, limit],
        )
        items = _rows_to_dicts(cursor, cursor.fetchall())
    return total, items
