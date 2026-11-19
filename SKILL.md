---
name: openmausbot-free-model-router
description: 本 skill 应在任一 OpenMausBot（OMB）bot 于 opencode 免费模型上撞到 429 / rate-limit / quota 限额错误时使用；也用于新建 OMB bot 时挑选可用免费模型，或用户询问哪些模型可用、要求切换到免费模型、执行 sync-free-models。通过 $OMB_DATA_DIR 或 ~/.openmausbot 下的共享健康表协调同一部门的所有 bot。仅适用于使用免费 tier、没有个人 API Key 的 OpenMausBot 用户；付费用户与其他 agent 框架不适用。触发词：切换免费模型 / 哪个模型可用 / sync-free-models / 429 / rate limit / quota exceeded。
agent_created: true
---

# OpenMausBot Free Model Router — 免费模型自动路由

**适用前提：本 skill 只服务 OpenMausBot（OMB）免费 tier 用户**——使用 opencode 免费套餐、没有个人 API Key。已有付费计划或自带 API Key 的用户不受本 skill 约束，直接用现有模型即可。

当部门内任一 bot 撞到限流墙时，自动探测、切换，并把健康状态广播给全部门的所有 bot，避免所有人重复撞同一堵墙。

---

## 核心机制：5 步原子操作

```
DETECT → BROADCAST → SWITCH → PROBE → CHOOSE
检测错误    写共享表+广播   改 modelSelection   定时恢复验证   为新 bot 选模型
```

---

## 第一步：DETECT — 错误分类（必须先判断再决定动作）

收到 LLM 错误后，按以下规则归类，再决定是换模型还是静默处理：

### A 类：立即标记 broken，发起切换

触发词出现在错误文本中任一即可（不区分大小写）：

- `429`
- `rate limit`
- `quota exceeded` / `quota limit`
- `too many requests`
- `insufficient_quota`
- `API rate limit for free users`

连续失败 ≥3 次同模型（即使错误文本不含上述词）→ 同样视为 broken。

### B 类：暂不标记，原模型重试或跳过

- `UnknownError`（服务端内部错，换一个模型大概率也挂）
- `timeout` / `ECONNRESET` / `ETIMEDOUT`（网络抖动，等一会用原模型重试一次即可）
- 内容审核拦截（与配额无关）
- 参数错误 / prompt too long

### C 类：告知用户，不做静默处理

- 所有免费模型同时处于 broken 状态（见 S6）
- 健康状态文件超过 2 小时未更新（视为过期，清除缓存重新探测）

---

## 第二步：BROADCAST — 更新共享健康表

一旦 DETECT 确认某组合为 broken，写入共享健康表。

**文件路径（跨平台，不含写死的用户名或盘符）：**

1. 若设置了环境变量 `OMB_DATA_DIR`，用 `$OMB_DATA_DIR/shared/model-health.json`
2. 否则用 `~/.openmausbot/shared/model-health.json`（Windows 即 `%USERPROFILE%\.openmausbot\shared\model-health.json`）

目录不存在时自动创建。

健康表示例（模型名仅为格式示意，实际以 `opencode models` 输出为准）：

```json
{
  "schema_version": 1,
  "last_updated": "2026-11-19T09:07:00+08:00",
  "available_free_models": [
    {"instanceId": "opencodeGo", "model": "<来自 opencode models 的模型 ID>"},
    {"instanceId": "opencode-go", "model": "<来自 opencode models 的模型 ID>"}
  ],
  "providers": {
    "opencodeGo/<model-id>": {
      "status": "ok",
      "last_success": "2026-11-19T09:00:00+08:00",
      "last_fail": null,
      "fail_count": 0,
      "cool_until": null
    },
    "opencodeGo/<other-model-id>": {
      "status": "broken",
      "last_success": "2026-11-18T22:00:00+08:00",
      "last_fail": "2026-11-19T09:05:00+08:00",
      "fail_count": 5,
      "cool_until": null
    }
  }
}
```

字段说明：

| 字段 | 含义 |
|------|------|
| `status` | `ok` / `broken` / `cooldown` |
| `cool_until` | ISO 时间戳；null = 无冷却。到期后**进入下一轮 PROBE 验证**，只有探测成功才恢复为 ok（不会自动变 ok） |
| `fail_count` | 连续失败次数；退避时长 = 5 × fail_count 分钟（线性增长，第 N 次失败等 5×N 分钟） |
| `last_updated` | 最后写入时间；超过 2 小时视为过期，放弃旧数据重探测 |

写完后立即通过 `coordinate_bots` 通知本部门所有活跃子 bot：

```
各子 bot 注意：<instanceId>/<model> 当前限额中，已停止使用。
请继续用你当前的正常模型工作；如需更换，查共享健康表（路径见上文）。
```

---

## 第三步：SWITCH — 切换该 bot 的 modelSelection

对撞限的 bot，用 `agents_propose_profile` 将其当前 modelSelection 改为健康的备选：

```python
for_bot_id: "<撞限的 bot id>"
model_selection: {instanceId: "<健康实例>", model: "<健康模型 ID>"}
reason: "原模型限额，自动切换到可用的免费模型（free-model-router）"
```

**必须遵守的规则：**

1. 切到的新模型必须来自 `available_free_models` 列表，且 status != "broken"
2. **以 instanceId 为粒度管理**——同一 instance 下任一 model 坏了，整实例标可疑，避免继续撞同一个 key
3. 每次 SWITCH 前必须读一遍健康表确认目标模型真的可用
4. `propose_profile` 返回 pending → 立刻停手并汇报，不等自动重试
5. 不要跨部门切换；只管理同 section 内的 bot

---

## 第四步：PROBE — 定时恢复验证

每 10 分钟或在 bot 启动时做一次轻量探测（软约束：由执行本 skill 的 agent 在会话中主动执行，非后台守护进程）：

1. 从健康表找出所有 `status != "ok"` 且（`cool_until` 为 null 或已过期）的项
2. 向每个候选发一条极简测试：`opencode run -m <model> "hi"`
3. 成功 → 状态改为 `ok`，清空 `fail_count`，写入 `last_success`
4. 仍失败 → 状态置为 `cooldown` 并延后 `cool_until`（线性退避：第 N 次失败后等 5×N 分钟）

探测请求必须轻量，避免加剧限额压力。

---

## 第五步：CHOOSE — 为新 bot 选模型

新建 bot 时先从 `opencode models` 动态读取当前可用免费模型清单，再按下面的**模型族偏好**排序挑选，不依赖写死的版本号。

**模型族优先级（P1 最高；仅表示偏好顺序，不是固定模型名）：**

| P | 偏好的模型族 | 选择理由 |
|---|-----------|---------|
| P1 | deepseek 系列 | 国内稳定，实测最可靠 |
| P2 | gemini flash 系列 | Google Gemini 免费版 |
| P3 | glm 系列 | 国产快响应 |
| P4 | 其他免费 flash 模型 | 兜底备选 |

读到的候选按上述偏好匹配，取第一个 `status=="ok"` 且 `cool_until==null` 的组合。全部不可用时直接告知用户，不做无效轮询。

> 注意：`opencode models` 返回的模型 ID（含版本号）会随时间变化，**不要在决策逻辑里写死具体版本**。偏好表只用于排序，实际候选始终来自动态清单。

---

## 20 个场景覆盖

| ID | 场景 | 处理方式 |
|----|------|----------|
| S1 | 新 bot 刚创建没设过模型 | CHOOSE：从健康表选最优免费组合写入 |
| S2 | 主 bot 对话中撞限额 | DETECT → BROADCAST → SWITCH 自身 + 通知其他 bot |
| S3 | 子 bot 被委托任务时撞限额 | 子 bot 上报 → 主 bot DETECT+BROADCAST → 全组对齐 |
| S4 | 多个子 bot 同时撞同一坏模型 | 任一检测到即 BROADCAST，其余下次运行时自动修正 |
| S5 | 多步流水线中途撞限 | 每步开始前检查健康表，不在可用列表则主动切换 |
| S6 | 所有免费模型都暂时不可用 | STOP，告知用户，不做无效重试 |
| S7 | 坏模型冷却期后恢复 | PROBE 定时探测，恢复后立即解除 broken 标记 |
| S8 | Opencode CLI 模型列表变动 | 技能启动时执行 `opencode models` 刷新缓存 |
| S9 | 用户手动指定了某个模型（override） | 尊重用户选择，照常记录健康状态但不强制切换 |
| S10 | 需降级到付费模型 | 仅在全部免费 broken 时触发；切换前明确告知 |
| S11 | 不同模型共用同一 API Key | 以 instanceId 粒度统一标记，不搞 per-bot 差异 |
| S12 | Sub-agent 执行中模型失效 | Sub-agent 回调给主 bot，由主 bot 决策，sub-agent 不自作 fallback |
| S13 | Bot 生成内容中途被撞限中断 | 无法续接；告知用户建议等新冷却周期后重试 |
| S14 | 健康表超 2 小时未更新 | 视为无有效状态，清除缓存各 bot 独立探测 |
| S15 | instance 对某 bot 限额但对另一 bot 正常 | 以 instance 为单位统一处理（保持简单） |
| S16 | 新建 bot 时从现有 bot 复制配置 | 继承当时最新健康状态对应的模型，不复制实时配置 |
| S17 | 不需要 LLM 的 bot（如纯 Browser 操作） | 排除在外，本 skill 只管实际发 LLM 请求的 bot |
| S18 | Cron 定时任务启动时撞限额 | 推迟 5 分钟后重试一次，仍损坏则 skip 本轮并记原因 |
| S19 | 多部门环境（未来扩展） | health 状态按 department scope 隔离 |
| S20 | 用户说「帮我切换到免费模型」 | 列出所有 status=="ok" 的免费组合供选择，或用 P1 偏好默认 |

---

## 常见陷阱（必看）

- **不要用 `limit-failovers.json` 作为主要决策依据。** 它只记录本 bot 线程级切换，且可能切到付费 codex。本 skill 用共享的 `model-health.json` 替代。
- **不要在报错时立刻切换。** 先做 DETECT 分类（A/B/C），UnknownError 和超时不要乱换模型。
- **不要跨部门切换。** 只管理同 section 内的 bot。
- **propose_profile 返回 pending 时停手汇报。** 不等自动重试。
- **不要写死模型名或本机路径。** 模型清单从 `opencode models` 动态读取，健康表路径用 `$OMB_DATA_DIR` 或 `~/.openmausbot`，不含任何用户名/盘符。
- **SWITCH 之后必须 BROADCAST。** 否则其他 bot 会继续撞同一堵墙。
- **不要让子 bot 自己做 fallback 决策。** 子 bot 撞限时上报，由统筹 bot 统一决策再广播。

---

## 与现有机制的关系

| 机制 | 本 skill 的姿态 |
|------|----------------|
| `limit-failovers.json` | 读作历史参考信号，不作为决策依据 |
| `sync-bot-models` skill | 互补关系：sync 解决「手动同步到同一模型」，router 解决「自动避开坏模型」。两者可同时存在 |
| `ai.backupModel` app 设置 | app 内置单次 fallback，只在引擎启动前失败时生效；本 skill 覆盖运行中限额场景 |

---

## 实现检查清单

落地新 bot 或调整本 skill 时逐一核对：

- [ ] 错误分类覆盖了 A/B/C 三类，UnknownError 不触发 switching
- [ ] 健康表路径用环境变量或 home 目录推导，不含写死的用户名/盘符
- [ ] 健康表文件不存在时自动创建
- [ ] 读文件前先检查 last_updated 是否超过 2 小时（过期则忽略）
- [ ] SWITCH 前验证目标模型的 status 确实是 ok
- [ ] BROADCAST 覆盖所有同级 bot（不只通知某一个）
- [ ] propose_profile 返回 pending 时停下来并向用户汇报
- [ ] 新 bot 创建路径调用了 CHOOSE 逻辑而非读静态配置
- [ ] 模型候选来自 `opencode models` 动态清单，偏好表只用于排序
- [ ] 用户手动指定的模型不被覆盖（S9）
- [ ] 全部 broken 时直接告知用户，不做无限重试（S6）
- [ ] 以 instanceId 为粒度存储状态，不按单 model 粒度
