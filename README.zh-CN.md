# OpenMausBot Free Model Router

> [English](./README.md) · 简体中文

> OpenMausBot 专用 Agent Skill。当部门内任一 bot 撞到 opencode 免费模型的 429 / rate-limit / quota 限额错误时，自动探测、切换并把健康状态广播给所有同级 bot，确保全组不重复撞同一堵墙。

[![Skill](https://img.shields.io/badge/type-agent%20skill-blueviolet)](./SKILL.md)
[![OpenMausBot](https://img.shields.io/badge/scope-OpenMausBot%20ONLY-red)](#适用范围)
[![Free-tier](https://img.shields.io/badge/target-free%20tier-yellow)](#适用用户)
[![License](https://img.shields.io/badge/license-MIT-green)](./LICENSE)

## 适用范围

**仅服务 OpenMausBot（OMB）生态。** 读取 `$OMB_DATA_DIR` 或 `~/.openmausbot` 下的 bot 配置与共享健康表，调用 OpenMausBot 内置工具（`agents_propose_profile`、`coordinate_bots`）及 `opencode` CLI 完成模型路由决策。不适用于 WorkBuddy、Claude Code 或其他 agent 框架。

## 解决什么问题

免费用户在 opencode 免费套餐下常遇三个问题：

1. **单点限流无感知**：一个 bot 撞限额后只切了它自己的线程，其他子 bot 继续跑在同一个坏模型上。
2. **内置兜底切到付费模型**：`limit-failovers.json` 可能把 bot 切到 codex（付费），而非另一个免费模型，产生意外费用。
3. **新 bot 盲目继承**：新建的 bot 不知道当前哪些模型可用，直接套旧配置容易踩坑。

本 skill 通过**共享健康状态表**（`model-health.json`）让全部门的模型可用性透明可见：撞了就切、切完就广播。

## 适用用户

**OpenMausBot 免费 tier 用户**：使用 opencode 免费套餐、没有个人 Claude / GPT / Codex API Key、完全依赖平台免费额度。

已有付费套餐或个人 API Key 的用户不需要此 skill，直接用现有模型即可。

## 5 步原子操作

```
DETECT → BROADCAST → SWITCH → PROBE → CHOOSE
```

| 步骤 | 作用 |
|------|------|
| DETECT | 收到 LLM 错误后分类：真限额 → broken；UnknownError / 超时 → 不标记 |
| BROADCAST | 写共享 `model-health.json`，通知所有同级 bot |
| SWITCH | 用 `agents_propose_profile` 将撞限 bot 切到健康备选 |
| PROBE | 每 10 分钟对 broken 模型发轻量探测，恢复后自动解封 |
| CHOOSE | 新 bot 创建时从健康表选最优免费组合，不依赖静态配置 |

## 安装

克隆仓库后，把整个文件夹复制到你的 OpenMausBot skills 目录：

```bash
git clone https://github.com/gunjianpanxdd/openmausbot-free-model-router.git
```

**macOS / Linux / Git Bash：**

```bash
cp -R openmausbot-free-model-router "$HOME/.openmausbot/skills/"
```

**Windows（PowerShell）：**

```powershell
Copy-Item -Recurse openmausbot-free-model-router "$env:USERPROFILE\.openmausbot\skills\"
```

如果你的部署设置了 `OMB_DATA_DIR`，则改为放到 `$OMB_DATA_DIR/skills/` 下。然后在任意 bot 会话中加载：

```
/learn <skills 路径>/openmausbot-free-model-router/SKILL.md
```

## 何时触发

- 任一 bot 报出 `429` / `rate limit` / `quota exceeded` 错误
- 你新建 bot 并询问应选什么模型
- 你说「哪个模型还能用」「切换到免费模型」「sync-free-models」

## 状态文件

首次触发后按以下优先级（先命中先用）生成：

```
$OMB_DATA_DIR/shared/model-health.json     # 设置了 OMB_DATA_DIR 时
~/.openmausbot/shared/model-health.json    # 否则
```

记录所有已知免费模型的健康状态（ok / broken / cooldown）、失败计数和冷却截止时间。超过 2 小时未更新的条目视为过期，自动作废并重探测。文件中不含任何用户名、盘符或机器相关路径。

## 目录结构

```
openmausbot-free-model-router/
├── SKILL.md              # 主 skill 入口（中文）
├── SKILL.en.md           # 英文镜像
├── README.md             # 英文说明
├── README.zh-CN.md       # 中文说明（本文件）
├── references/
│   └── state-format.md   # model-health.json 完整格式说明
├── scripts/
│   └── health-check.py   # 可选：命令行健康表查看器
├── .gitignore
└── LICENSE
```

## 与现有机制的关系

| 现有机制 | 与本 skill 的关系 |
|---------|----------------|
| `limit-failovers.json` | 读作历史信号参考，不作为决策唯一来源 |
| `sync-bot-models` skill | 互补：sync 负责手动对齐模型，router 负责自动避开坏模型 |
| `ai.backupModel` 应用设置 | 内置单次 fallback 只在引擎启动前生效；本 skill 覆盖运行中限额场景 |

## License

MIT — 见 [LICENSE](./LICENSE)。
