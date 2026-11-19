# model-health.json 状态文件格式规范

本文档描述共享健康表 `model-health.json` 的完整 schema，供 skill 实现和手动维护时参考。

文件路径按以下优先级确定（不含任何写死的用户名或盘符）：

1. 若设置了 `OMB_DATA_DIR`，用 `$OMB_DATA_DIR/shared/model-health.json`
2. 否则用 `~/.openmausbot/shared/model-health.json`（Windows 即 `%USERPROFILE%\.openmausbot\shared\model-health.json`）

---

## Schema v1

```json
{
  "schema_version": 1,
  "last_updated": "2026-11-19T09:07:00+08:00",
  "available_free_models": [
    {
      "instanceId": "opencodeGo",
      "model": "opencode/deepseek-v4.1-flash-free"
    },
    {
      "instanceId": "opencodeGo",
      "model": "opencode/gemini-3.5-flash-lite"
    }
  ],
  "providers": {
    "opencodeGo/opencode/deepseek-v4.1-flash-free": {
      "status": "ok",
      "last_success": "2026-11-19T09:00:00+08:00",
      "last_fail": null,
      "fail_count": 0,
      "cool_until": null
    },
    "opencodeGo/opencode/gemini-3.5-flash-lite": {
      "status": "broken",
      "last_success": "2026-11-18T22:00:00+08:00",
      "last_fail": "2026-11-19T09:05:00+08:00",
      "fail_count": 5,
      "cool_until": "2026-11-19T09:40:00+08:00"
    }
  }
}
```

---

## 顶层字段

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `schema_version` | integer | 是 | 当前版本号为 `1`；升级时需递增 |
| `last_updated` | string (ISO 8601) | 是 | 最后一次写入的时间戳；超过 2 小时视为过期 |
| `available_free_models` | array of objects | 是 | 所有候选免费模型列表；从 `opencode models` 动态获取 |
| `providers` | object | 是 | key 为 `<instanceId>/<model>`，value 为该组合的健康状态 |

---

## available_free_models 元素

| 字段 | 类型 | 说明 |
|------|------|------|
| `instanceId` | string | config.json instances 中的确切 ID（如 `opencodeGo`、`deepseek`）|
| `model` | string | opencode models 列出的完整模型名（如 `opencode/deepseek-v4.1-flash-free`）|

注意：此列表**不写死在 SKILL.md 中**，应在技能启动时通过执行 `opencode models` 刷新，避免模型上下线后配置滞后。

---

## providers 条目字段

| 字段 | 类型 | 允许值 | 说明 |
|------|------|--------|------|
| `status` | string | `"ok"` / `"broken"` / `"cooldown"` | 当前健康状态 |
| `last_success` | string or null | ISO 8601 或 null | 最近一次成功时间；首次探测前为 null |
| `last_fail` | string or null | ISO 8601 或 null | 最近一次失败时间 |
| `fail_count` | integer | ≥0 | 连续失败次数；用于计算冷却时长 |
| `cool_until` | string or null | ISO 8601 或 null | 冷却截止时间；null 表示无冷却；到期后进入下一轮 PROBE，只有探测成功才恢复 ok（不自动变 ok） |

---

## 状态转换规则

```
ok ──[LLM错误分类为A类]──→ broken
                      └──[fail_count≥3]──→ broken
broken ──[PROBE成功]──→ ok
broken ──[PROBE仍失败]──→ cooldown（cool_until = now + 5×fail_count分钟）
cooldown ──[cool_until到期]──→ 进入下一次 PROBE
```

---

## 过期判定

每次读取文件时检查 `last_updated`：

```python
from datetime import datetime, timezone, timedelta

last = datetime.fromisoformat(data["last_updated"])
now = datetime.now(timezone.utc).astimezone()
if (now - last).total_seconds() > 7200:   # 2 小时
    treat_as_stale = True
```

过期后忽略旧数据，重新跑一轮 PROBE 初始化各条目状态。

---

## 常见操作示例

### 标记某个模型为 broken

```python
key = f"{instance_id}/{model}"
data["providers"][key] = {
    "status": "broken",
    "last_success": data["providers"].get(key, {}).get("last_success"),
    "last_fail": datetime.now(timezone.utc).isoformat(),
    "fail_count": data["providers"].get(key, {}).get("fail_count", 0) + 1,
    "cool_until": None
}
data["last_updated"] = datetime.now(timezone.utc).isoformat()
write_json(path, data)
```

### 解除 broken（PROBE 成功）

```python
data["providers"][key]["status"] = "ok"
data["providers"][key]["fail_count"] = 0
data["providers"][key]["last_success"] = datetime.now(timezone.utc).isoformat()
data["providers"][key]["last_fail"] = None
data["providers"][key]["cool_until"] = None
data["last_updated"] = datetime.now(timezone.utc).isoformat()
```

### 选择最优可用模型

```python
candidates = [
    m for m in data["available_free_models"]
    if data["providers"].get(
        f"{m['instanceId']}/{m['model']}", {}
    ).get("status") == "ok"
    and data["providers"].get(
        f"{m['instanceId']}/{m['model']}", {}
    ).get("cool_until") is None
]
best = candidates[0] if candidates else None   # None = 全部不可用
```
