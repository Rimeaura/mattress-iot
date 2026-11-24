# 前端接口文档（/api/v1）

| 项目 | 内容 |
|------|------|
| 文档版本 | v0.2 |
| 编写日期 | 2026-11-21 |
| 编写人 | 成员4（后端） |
| 适用范围 | 网页端查询后端数据、展示实时状态与历史曲线 |
| 实现位置 | `src/backend/routers/api.py` |
| 关联文档 | 《需求规格说明书》v0.3、`document/Known_Issues_V0.1.md` |

---

## 1. 通用约定

- **Base URL**：`http://<后端主机>:8000`，所有接口前缀为 `/api/v1`
- **数据格式**：请求与响应均为 JSON（UTF-8）
- **统一响应体**：

```json
{ "code": 0, "message": "ok", "data": {} }
```

| 字段 | 说明 |
|------|------|
| `code` | `0` 表示成功；失败时等于 HTTP 状态码（400/404/500） |
| `message` | `ok` 或错误说明，可直接展示给用户 |
| `data` | 成功时为业务数据；失败时为 `null` |

- **HTTP 状态码**：成功 200；参数错误 400；资源不存在 404；服务器内部错误 500
- **鉴权**：当前**没有任何鉴权**，请只在局域网内调用
- **时间格式**：所有时间字段为 ISO 8601 带时区文本（如 `2026-11-21T10:00:05+08:00`），前端传 `start`/`end` 时也必须使用该格式
- **在线判定**：超过 **60 秒**无数据即视为离线

## 2. 接口一览

| 方法 | 路径 | 用途 |
|------|------|------|
| GET | `/api/v1/devices` | 设备列表与在线状态 |
| GET | `/api/v1/devices/{device_id}/latest` | 设备最新环境数据与床体数据 |
| GET | `/api/v1/devices/{device_id}/history` | 单指标历史曲线（降采样） |
| GET | `/api/v1/bed/state` | 当前床位状态 |
| GET | `/api/v1/bed/events` | 体动事件列表 |

> 规则配置（`/rules`）与控制记录（`/control-records`）接口已从后端移除，当前不可用。

---

## 3. 接口详情

### 3.1 获取设备列表

```
GET /api/v1/devices
```

无参数。

**响应 `data`**：数组，每项为：

| 字段 | 类型 | 说明 |
|------|------|------|
| `device_id` | string | 设备 ID，如 `bed-pressure`、`bed-accel`、`env-01` |
| `device_type` | string | `env`（环境）/ `bed`（床体）/ `combined`（两者都有） |
| `online` | boolean | 是否有 60 秒内的上报 |
| `last_seen_at` | string | 最后一次上报时间 |

**示例**

```json
{
  "code": 0,
  "message": "ok",
  "data": [
    {
      "device_id": "bed-pressure",
      "device_type": "bed",
      "online": true,
      "last_seen_at": "2026-11-21T20:45:49.451+08:00"
    },
    {
      "device_id": "bed-accel",
      "device_type": "bed",
      "online": true,
      "last_seen_at": "2026-11-21T20:45:49.960+08:00"
    },
    {
      "device_id": "env-01",
      "device_type": "env",
      "online": false,
      "last_seen_at": "2026-11-21T20:40:10.120+08:00"
    }
  ]
}
```

> 设备清单由实际上报数据派生，不是注册表；从未上报过的设备不会出现。

---

### 3.2 获取设备最新数据

```
GET /api/v1/devices/{device_id}/latest
```

| 参数 | 位置 | 必填 | 说明 |
|------|------|------|------|
| `device_id` | path | 是 | 设备 ID |

**响应 `data`**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `device_id` | string | 设备 ID |
| `online` | boolean | 在线状态 |
| `last_seen_at` | string | 该设备最后一次上报时间 |
| `env` | object \| null | 最新环境数据；床体设备为 `null` |
| `bed` | object \| null | 最新床体数据；环境设备为 `null` |

`env` 对象字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `device_id` | string | 设备 ID |
| `temperature` | number \| null | 温度（℃） |
| `humidity` | number \| null | 湿度（%RH） |
| `light` | number \| null | 光照（lux） |
| `env_status` | number \| null | 环境节点状态 |
| `event_time` | string \| null | 平台事件时间 |
| `received_at` | string | 后端接收时间 |

`bed` 对象字段（两台设备共用同一结构，未上报的字段为 `null`）：

| 字段 | 类型 | 说明 |
|------|------|------|
| `device_id` | string | 设备 ID |
| `bed_state` | string \| null | 床位主状态，仅压力板有值 |
| `load_presence` | string \| null | 负载判定，仅压力板有值 |
| `confidence` | string \| null | 置信度，仅压力板有值 |
| `last_event` | string \| null | 最近一次状态事件，仅压力板有值 |
| `alert_type` | string \| null | 当前提示类型，仅压力板有值 |
| `sensor_status` | string \| null | 自检状态，两块板都有 |
| `head_shoulder_raw` | number \| null | 头肩路 ADC 原始码，仅压力板有值 |
| `head_shoulder_net` | number \| null | 头肩路净压，仅压力板有值 |
| `waist_hip_raw` | number \| null | 腰臀路 ADC 原始码，仅压力板有值 |
| `waist_hip_net` | number \| null | 腰臀路净压，仅压力板有值 |
| `total_net_pressure` | number \| null | 两路净压之和，仅压力板有值 |
| `waist_hip_ratio` | number \| null | 腰臀净压占比，0–1，仅压力板有值 |
| `last_event_sec` | number \| null | 最近事件发生在开机后第几秒，仅压力板有值 |
| `run_sec` | number \| null | 开机至今秒数，两块板都有 |
| `accel_x` / `accel_y` / `accel_z` | number \| null | 三轴加速度原始值，仅加速度板有值 |
| `motion_peak_mg` | number \| null | 近 10 秒运动峰值，单位 0.001g，仅加速度板有值 |
| `motion_state` | string \| null | `STILL` / `MOVING`，仅加速度板有值 |
| `motion_count_10s` | number \| null | 近 10 秒体动次数，仅加速度板有值 |
| `event_time` | string \| null | 平台事件时间，已统一为带时区的 ISO 8601 |
| `received_at` | string | 后端接收时间 |

**错误**：设备在两张表中都没有数据时返回 404。

```json
{ "code": 404, "message": "设备 unknown 无上报数据", "data": null }
```

---

### 3.3 获取历史曲线

```
GET /api/v1/devices/{device_id}/history
```

| 参数 | 位置 | 必填 | 说明 |
|------|------|------|------|
| `device_id` | path | 是 | 设备 ID |
| `metric` | query | 是 | 指标名，见下方白名单 |
| `start` | query | 否 | 起始时间，ISO 8601 |
| `end` | query | 否 | 结束时间，ISO 8601 |
| `points` | query | 否 | 降采样点数，2–1000，默认 200 |

**`metric` 白名单**：

| metric | 单位 | 说明 |
|---|---|---|
| `temperature` | ℃ | 温度 |
| `humidity` | %RH | 湿度 |
| `light` | lux | 光照 |
| `env_status` | 无 | 环境节点状态 |
| `accel_x` / `accel_y` / `accel_z` | 无 | 三轴加速度 |
| `motion_peak_mg` | 0.001g | 近 10 秒运动峰值 |
| `motion_count_10s` | 次 | 近 10 秒体动次数 |
| `head_shoulder_raw` / `head_shoulder_net` | 码 | 头肩路原始码 / 净压 |
| `waist_hip_raw` / `waist_hip_net` | 码 | 腰臀路原始码 / 净压 |
| `total_net_pressure` | 码 | 两路净压之和 |
| `waist_hip_ratio` | 无 | 腰臀净压占比，0–1 |
| `run_sec` | 秒 | 开机至今秒数 |
| `last_event_sec` | 秒 | 最近事件发生在开机后第几秒 |

**响应 `data`**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `device_id` | string | 设备 ID |
| `metric` | string | 指标名 |
| `unit` | string \| null | 单位，无单位时为 `null` |
| `count` | number | 原始数据点总数（降采样前） |
| `points` | array | 降采样后的点，`[{ "time": "...", "value": 26.5 }]` |

- `points` 超过 `points` 参数时按分桶均值降采样；点数不足时原样返回。
- 设备无数据时返回 200 + `count: 0` + 空数组，不报 404。
- `metric` 非法、时间格式错误、`start` 晚于 `end` 均返回 400。

**示例**

```
GET /api/v1/devices/env-01/history?metric=temperature&start=2026-11-21T00:00:00%2B08:00&points=3
```

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "device_id": "env-01",
    "metric": "temperature",
    "unit": "℃",
    "count": 10,
    "points": [
      { "time": "2026-11-21T10:00:00+08:00", "value": 26.0 },
      { "time": "2026-11-21T10:00:03+08:00", "value": 29.0 },
      { "time": "2026-11-21T10:00:06+08:00", "value": 32.5 }
    ]
  }
}
```

> 注意：URL 中的 `+` 会被解析成空格，时间里的 `+08:00` 需编码为 `%2B08:00`；也可以直接使用 `Z` 结尾的 UTC 时间。

---

### 3.4 获取床位状态

```
GET /api/v1/bed/state
```

| 参数 | 位置 | 必填 | 说明 |
|------|------|------|------|
| `device_id` | query | 否 | 不传时分别取压力板、加速度板各自最新一帧 |

**响应 `data`**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `device_id` | string | 设备 ID，缺省时取压力板设备 |
| `bed_state` | string \| null | 压力板上报的床位主状态原值：`OUT_BED` / `IN_BED_UNKNOWN` / `LYING` / `SITTING` / `UNKNOWN` |
| `online` | boolean | 在线状态，按较新一侧的接收时间判断 |
| `last_seen_at` | string | 较新一侧的最后上报时间 |
| `pressure` | object \| null | 压力板最新一帧，无数据时为 `null` |
| `accel` | object \| null | 加速度板最新一帧，无数据时为 `null` |

`pressure` 与 `accel` 的字段与 3.2 的 `bed` 对象一致，各自只填充本设备的字段，另一侧字段为 `null`。

**示例**

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "device_id": "bed-pressure",
    "bed_state": "IN_BED_UNKNOWN",
    "online": true,
    "last_seen_at": "2026-11-24T21:04:29.053+08:00",
    "pressure": {
      "device_id": "bed-pressure",
      "bed_state": "IN_BED_UNKNOWN",
      "load_presence": "PRESENT",
      "confidence": "MEDIUM",
      "last_event": "BED_IN",
      "alert_type": "NONE",
      "sensor_status": "OK",
      "head_shoulder_raw": 962,
      "head_shoulder_net": 810,
      "total_net_pressure": 810,
      "waist_hip_ratio": 0.0,
      "run_sec": 412,
      "event_time": "2026-11-24T10:10:10+00:00",
      "received_at": "2026-11-24T21:04:28.999+08:00"
    },
    "accel": {
      "device_id": "bed-accel",
      "sensor_status": "OK",
      "accel_x": 4120,
      "accel_y": -2380,
      "accel_z": 1640,
      "motion_peak_mg": 168,
      "motion_state": "MOVING",
      "motion_count_10s": 2,
      "run_sec": 417,
      "event_time": "2026-11-24T10:10:14+00:00",
      "received_at": "2026-11-24T21:04:29.053+08:00"
    }
  }
}
```

**错误**：两台设备都没有数据时返回 404。

> 说明：两台设备每 2 秒各自上报，周期不同步。当前实现各取最新一帧返回，不做时间窗合并；某一侧没有数据就是 `null`，前端需分别判空。

---

### 3.5 获取体动事件列表

```
GET /api/v1/bed/events
```

| 参数 | 位置 | 必填 | 说明 |
|------|------|------|------|
| `device_id` | query | 否 | 不传时查全部设备 |
| `start` | query | 否 | 起始时间，ISO 8601 |
| `end` | query | 否 | 结束时间，ISO 8601 |
| `limit` | query | 否 | 返回条数，1–500，默认 50 |

**响应 `data`**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `total` | number | 符合条件的总条数 |
| `items` | array | 事件列表，按时间倒序 |

`items` 单项字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | number | 记录 ID |
| `device_id` | string | 设备 ID |
| `motion_state` | string | 固定为 `MOVING` |
| `motion_count_10s` | number \| null | 近 10 秒体动次数 |
| `motion_peak_mg` | number \| null | 近 10 秒运动峰值，单位 0.001g |
| `event_time` | string \| null | 平台事件时间 |
| `received_at` | string | 后端接收时间 |

**示例**

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "total": 1,
    "items": [
      {
        "id": 1,
        "device_id": "bed-accel",
        "motion_state": "MOVING",
        "motion_count_10s": 2,
        "motion_peak_mg": 168,
        "event_time": "2026-11-24T10:10:14+00:00",
        "received_at": "2026-11-24T21:04:29.053+08:00"
      }
    ]
  }
}
```

> 当前事件按单条 `motion_state = MOVING` 的上报记录返回，同一段持续运动会生成多条；暂未做片段合并（见 Known Issues Q-17）。

---

## 4. 错误响应参考

```json
{ "code": 400, "message": "不支持的 metric: co2，可选: ...", "data": null }
{ "code": 400, "message": "参数校验失败: query.metric Field required", "data": null }
{ "code": 404, "message": "无床体数据", "data": null }
{ "code": 500, "message": "服务器内部错误", "data": null }
```

| 状态码 | 典型场景 |
|---|---|
| 400 | 缺少必填参数、`metric` 非法、时间格式错误、`start > end`、`points`/`limit` 越界 |
| 404 | 设备无任何数据、无床体数据、路径不存在 |
| 500 | 后端未捕获异常（详情只写后端日志） |

---

## 5. 前端联调注意事项

1. **CORS 未配置**：后端没有启用 CORS 中间件。若前端通过 `http://localhost:5173` 之类的独立端口访问后端，浏览器会拦截请求。解决方式二选一：
   - 前端开发服务器配置代理（推荐，见下方示例）
   - 由后端添加 `CORSMiddleware`（需要改后端代码）
2. **Vite 代理示例**：

```js
// vite.config.js
export default {
  server: {
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },
}
```

3. **轮询建议**：首页 3–5 秒刷新一次；历史曲线按需加载，不要每次轮询都拉全量。
4. **空数据处理**：`latest` 会 404；`history` 返回空数组；`events` 返回 `total: 0`。三种情况请分别展示"无数据/未上报"，不要显示 0 值或旧值。
5. **离线展示**：`online=false` 时必须显式提示离线，不要继续展示旧的实时值（对应 FR-13、NFR-07）。
6. **字段可空**：传感器某个属性未上报时对应字段为 `null`，渲染前需判空。
7. **两台设备**：`/bed/state` 的 `pressure` 与 `accel` 可能一侧为 `null`，表示该设备当前没有数据；不要把 `null` 当成 0。
8. **状态映射**：`bed_state` 返回固件原值（`IN_BED_UNKNOWN` 等），中文展示由前端自行映射。

---

## 6. 文档变更记录

| 版本 | 日期 | 变更 |
|------|------|------|
| v0.1 | 2026-11-21 | 首版；覆盖 5 个查询接口，移除规则与控制记录接口 |
| v0.2 | 2026-11-24 | 适配 `BedMonitor` 双设备模型：新增压力板字段与 `motion_peak_mg`，`/bed/state` 改为返回 `bedState` 原值及 `pressure` / `accel` 两块，体动事件改为 `MOVING`（文件名仍为 V0.1） |
