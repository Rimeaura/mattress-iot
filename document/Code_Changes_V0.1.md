# 代码变更记录

| 项目 | 内容 |
|------|------|
| 记录版本 | v0.1 |
| 变更日期 | 2026-11-21 |
| 记录人 | 成员4（后端） |
| 关联文档 | 《需求规格说明书》v0.3、`document/Known_Issues_V0.1.md` |
| 变更类型 | 移除未实现的风扇控制相关脚手架 |

---

## 1. 变更背景

风扇控制链路中的规则引擎、`fan_control` 命令下发、控制记录写入、手动控制接口均未实现，后端此前只交付了 `rule_config`、`control_record` 两张空表和对应读写接口，没有任何代码消费或写入，存在被误认为"风扇控制已交付"的风险。经确认后移除全部风扇相关代码，只保留环境与卧床数据查询接口。

## 2. 移除清单

### 2.1 `src/backend/storage.py`

| 移除内容 | 原位置 |
|----------|--------|
| `control_record` 表定义及 `idx_control_device_time` 索引 | `SCHEMA` |
| `rule_config` 表定义 | `SCHEMA` |
| `DEFAULT_RULES` 常量（rule-1：温度 ≥30℃ 开、≤28℃ 关） | 模块级常量 |
| `init_db()` 中写入默认规则的 `executemany` 语句 | `init_db` |
| `query_control_records()` | 查询函数区 |
| `_RULE_COLUMNS`、`_RULE_FIELDS`、`_rule_to_dict()`、`query_rules()`、`get_rule()`、`update_rule()` | 查询函数区 |

### 2.2 `src/backend/routers/api.py`

| 移除内容 | 说明 |
|----------|------|
| `GET /api/v1/control-records` | 控制记录查询 |
| `GET /api/v1/rules` | 规则配置列表 |
| `PUT /api/v1/rules/{rule_id}` | 规则阈值/启停修改 |
| `RuleUpdate` 模型及 `from pydantic import BaseModel` | 仅被规则接口使用 |
| 模块 docstring 中"与规则配置读写（FR-10）"字样 | 与实际能力不符 |

### 2.3 保留内容

- 数据表：`env_readings`、`bed_readings`
- 接口：`GET /api/v1/devices`、`/devices/{device_id}/latest`、`/devices/{device_id}/history`、`/bed/state`、`/bed/events`
- 统一响应 `{code, message, data}` 与 400/404/500 异常处理
- AMQP 入库、`POST /iot/callback`、`GET /` 健康检查

## 3. 变更影响

1. **接口数量**：`/api/v1` 由 8 个减为 5 个，`/rules`、`/control-records` 现在返回 404。
2. **数据库文件**：代码中移除 `CREATE TABLE` 不会删除已存在库中的旧表。若 `data/iot.db` 已生成过 `control_record`、`rule_config`，需手动 `DROP TABLE` 清理；不清理也不影响现有查询。
3. **文档需同步回退**（本次未改，待确认后处理）：
   - 需求规格 v0.3 第 6 章："已实现 4 张表"应改回 2 张，删除 `control_record`、`rule_config` 字段说明
   - FR-10："已实现（v0.3）"两条规则接口说明需删除
   - 7.1 接口表：删除 `GET /control-records`、`GET /rules`、`PUT /rules/{rule_id}` 三行
   - `Known_Issues_V0.1.md`：Q-05、Q-09、Q-17 中涉及 `rule_config`/`control_record` 的描述需改为"未来实现时处理"
4. **前端**：若成员5 已按 7.1 清单准备接入，需要确认删除规则与控制记录两项。

## 4. 验证结果

使用独立临时 SQLite 库执行 `TestClient` 验证：

- `GET /api/v1/rules` → 404
- `GET /api/v1/control-records` → 404
- `GET /api/v1/devices`、`/devices/{id}/latest`、`/devices/{id}/history`、`/bed/events` → 200 且 `code=0`
- `storage` 模块中 `query_control_records`、`query_rules`、`get_rule`、`update_rule`、`DEFAULT_RULES` 均已不存在
- 源码全文检索 `rule`、`fan`、`control_record`、`control-record` 无残留

## 5. 回滚方式

按第 2 节清单恢复对应表定义、函数与路由即可。数据库无需迁移，旧表若未删除可直接复用。

## 6. 后续约定

风扇控制正式开发时，必须把以下内容作为一组同时交付，避免再次出现"只有空表没有实现"：

1. `rule_config` 表与规则读写接口
2. 规则引擎（读规则、回差判断）
3. IoTDA `fan_control` 命令下发
4. `control_record` 表与写入方（含下发结果字段）
5. 如需手动控制，补充控制接口并在记录中区分 `source=rule/manual`
