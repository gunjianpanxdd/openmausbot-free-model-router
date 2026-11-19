# OpenMausBot Free Model Router

> English · [中文文档](./README.zh-CN.md)

> An OpenMausBot-only agent skill. When any bot in a department hits an opencode free-model rate limit, it auto-detects the failure, switches to a healthy model, and broadcasts the health state to every sibling bot so nobody hits the same wall twice.

[![Skill](https://img.shields.io/badge/type-agent%20skill-blueviolet)](./SKILL.md)
[![OpenMausBot](https://img.shields.io/badge/scope-OpenMausBot%20ONLY-red)](#scope)
[![Free-tier](https://img.shields.io/badge/target-free%20tier-yellow)](#who-it-is-for)
[![License](https://img.shields.io/badge/license-MIT-green)](./LICENSE)

## Scope

**This skill works exclusively with OpenMausBot (OMB).** It reads bot config under `$OMB_DATA_DIR` or `~/.openmausbot`, and drives OpenMausBot's own tools (`agents_propose_profile`, `coordinate_bots`) plus the `opencode` CLI. It does **not** apply to WorkBuddy, Claude Code, or any other agent framework.

## What problem it solves

Free-tier users on the opencode free plan run into three recurring problems:

1. **Rate limits go unnoticed across bots.** One bot hits a limit and only its own thread switches; sibling bots keep running on the same broken model.
2. **The built-in fallback switches to a paid model.** `limit-failovers.json` can route a bot to codex (paid) instead of another free model, causing unexpected charges.
3. **New bots inherit stale config blindly.** A newly created bot has no idea which models work right now.

This skill makes model health transparent across the whole department through a **shared health table** (`model-health.json`): detect a limit, switch, then broadcast.

## Who it is for

**OpenMausBot free-tier users** — using the opencode free plan, with no personal Claude / GPT / Codex API key, relying entirely on the platform's free quota.

If you are on a paid plan or have your own API key, you do not need this skill — keep using your existing model.

## The 5 atomic operations

```
DETECT → BROADCAST → SWITCH → PROBE → CHOOSE
```

| Step | What it does |
|------|-------------|
| DETECT | Classify LLM errors: a real quota hit → broken; `UnknownError` / timeout → do not mark |
| BROADCAST | Write the shared `model-health.json` and notify all sibling bots |
| SWITCH | Use `agents_propose_profile` to move the limited bot to a healthy alternative |
| PROBE | Send lightweight probes to broken models every 10 minutes; unblock on recovery |
| CHOOSE | Pick the best free model from the health table when creating a new bot |

## Install

Clone the repository, then copy the whole folder into your OpenMausBot skills directory:

```bash
git clone https://github.com/gunjianpanxdd/openmausbot-free-model-router.git
```

**macOS / Linux / Git Bash:**

```bash
cp -R openmausbot-free-model-router "$HOME/.openmausbot/skills/"
```

**Windows (PowerShell):**

```powershell
Copy-Item -Recurse openmausbot-free-model-router "$env:USERPROFILE\.openmausbot\skills\"
```

If your deployment sets `OMB_DATA_DIR`, place the folder under `$OMB_DATA_DIR/skills/` instead. Then load the skill in any bot session:

```
/learn <path-to-skills>/openmausbot-free-model-router/SKILL.md
```

## When it triggers

- Any bot reports `429` / `rate limit` / `quota exceeded`
- You create a new bot and ask which model to use
- You say "which model is still available", "switch to free models", or "sync-free-models"

## State file

Created on first trigger at one of these paths (in order of precedence):

```
$OMB_DATA_DIR/shared/model-health.json     # if OMB_DATA_DIR is set
~/.openmausbot/shared/model-health.json    # otherwise
```

It records the health of every known free model (`ok` / `broken` / `cooldown`), failure counts, and cooldown deadlines. Entries not updated for over 2 hours are treated as stale and re-probed. No username, drive letter, or machine-specific path is hardcoded.

## Repository layout

```
openmausbot-free-model-router/
├── SKILL.md              # Main skill entry (Chinese)
├── SKILL.en.md           # English mirror of SKILL.md
├── README.md             # English readme (this file)
├── README.zh-CN.md       # Chinese readme
├── references/
│   └── state-format.md   # Full model-health.json schema
├── scripts/
│   └── health-check.py   # Optional CLI viewer for the health table
├── .gitignore
└── LICENSE
```

## Relationship with existing mechanisms

| Mechanism | Relationship |
|-----------|-------------|
| `limit-failovers.json` | Read as a historical signal only, never the sole decision source |
| `sync-bot-models` skill | Complementary: sync handles manual alignment; router handles automatic failure avoidance |
| `ai.backupModel` app setting | Built-in single-attempt fallback only fires before engine init; this skill covers mid-run rate limits |

## License

MIT — see [LICENSE](./LICENSE).
