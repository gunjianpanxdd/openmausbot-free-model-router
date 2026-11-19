---
name: openmausbot-free-model-router
description: This skill should be used when any OpenMausBot (OMB) bot hits a 429 / rate-limit / quota error on an opencode free model, when creating a new OMB bot that needs an available free model, or when the user asks which models are healthy, requests switching to a free model, or runs sync-free-models. It coordinates all bots in a department through a shared health table under $OMB_DATA_DIR or ~/.openmausbot. Only for OpenMausBot free-tier users without a personal API key; not for paid users or other agent frameworks. Triggers: switch to free model / which model is available / sync-free-models / 429 / rate limit / quota exceeded.
agent_created: true
---

# OpenMausBot Free Model Router — Automatic Free Model Routing

**Scope: OpenMausBot (OMB) free-tier users only.** Users on the opencode free plan with no personal API key. Users with a paid plan or their own API key are not governed by this skill — keep using the existing model.

When any bot in a department hits a rate limit, this skill auto-detects the failure, switches to a healthy alternative, and broadcasts the health state to every sibling bot so nobody hits the same wall twice.

---

## Core Mechanism: 5 Atomic Operations

```
DETECT → BROADCAST → SWITCH → PROBE → CHOOSE
detect error  write+notify  swap modelSelection  periodic probe  pick model for new bot
```

---

## Step 1: DETECT — Classify the Error (always classify before acting)

After any LLM error, determine which category it falls into:

### Category A: Mark as broken immediately (trigger switch)

Triggered by any of these keywords in the error text (case-insensitive):

- `429`
- `rate limit`
- `quota exceeded` / `quota limit`
- `too many requests`
- `insufficient_quota`
- `API rate limit for free users`

Also mark broken after **≥3 consecutive failures** on the same model, even without the above keywords.

### Category B: Do not mark broken; retry same model or skip

- `UnknownError` (server-side internal error — another model will likely fail identically)
- `timeout` / `ECONNRESET` / `ETIMEDOUT` (network glitch; brief wait + retry same model)
- Content moderation blocks (unrelated to quotas)
- Parameter errors / prompt too long

### Category C: Escalate to the user directly; do not handle silently

- All known free models are simultaneously broken (see S6)
- Health state file has not been updated for over 2 hours (stale; clear cache and re-probe)

---

## Step 2: BROADCAST — Write Shared Health Table

Once DETECT confirms a combination is broken, update the shared health table.

**File path (cross-platform, no hardcoded username or drive letter):**

1. If the `OMB_DATA_DIR` environment variable is set, use `$OMB_DATA_DIR/shared/model-health.json`
2. Otherwise use `~/.openmausbot/shared/model-health.json` (on Windows: `%USERPROFILE%\.openmausbot\shared\model-health.json`)

Auto-create the directory if missing.

Example health table (model names are format illustrations only — the real values come from `opencode models`):

```json
{
  "schema_version": 1,
  "last_updated": "2026-11-19T09:07:00+08:00",
  "available_free_models": [
    {"instanceId": "opencodeGo", "model": "<model ID from opencode models>"},
    {"instanceId": "opencode-go", "model": "<model ID from opencode models>"}
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

Field meanings:

| Field | Meaning |
|-------|---------|
| `status` | `ok` / `broken` / `cooldown` |
| `cool_until` | ISO timestamp; null = no cooldown. When expired the entry **enters the next PROBE round**; it returns to ok only after a successful probe (never automatically) |
| `fail_count` | Consecutive failure count; back-off = 5 × fail_count minutes (linear growth: wait 5×N minutes after the Nth failure) |
| `last_updated` | Last write time; stale if older than 2 hours — discard and re-probe |

After writing, notify all active sibling bots via `coordinate_bots`:

```
Attention: <instanceId>/<model> is currently rate-limited and disabled.
Continue using your current working model. For alternatives, check the shared health table (path above).
```

---

## Step 3: SWITCH — Swap the Bot's modelSelection

For the bot that hit the limit, use `agents_propose_profile` to set its modelSelection to a healthy alternative:

```python
for_bot_id: "<bot-id-that-hit-the-limit>"
model_selection: {instanceId: "<healthy-instance>", model: "<healthy-model-ID>"}
reason: "Original model rate-limited; switching to available free model via free-model-router"
```

**Rules you must follow:**

1. The target model must appear in `available_free_models` AND have status != "broken"
2. **Manage at instanceId granularity** — if any model under one instance fails, the whole instance is flagged suspicious to avoid hammering the same API key
3. Re-read the health table before every SWITCH to confirm the target is actually ok
4. If `propose_profile` returns `pending` → stop and report to the user; do NOT auto-retry
5. Do NOT cross department boundaries; only manage bots within the same section

---

## Step 4: PROBE — Periodic Recovery Check

Every 10 minutes (or on bot startup), run lightweight probes (soft constraint: executed proactively by the agent running this skill during a session, not a background daemon):

1. Find all entries where `status != "ok"` and (`cool_until` is null or has expired)
2. Send a minimal test request: `opencode run -m <model> "hi"`
3. Success → update to `status: "ok"`, reset `fail_count`, record `last_success`
4. Still failing → set `status: "cooldown"` and push `cool_until` further out (linear back-off: wait 5×N minutes after the Nth failure)

Probe requests must be lightweight to avoid worsening the rate limit situation.

---

## Step 5: CHOOSE — Pick a Model for a New Bot

When creating a new bot, first read the current free-model list dynamically from `opencode models`, then rank it by the **model-family preferences** below. Never rely on hardcoded version strings.

**Model-family priority (P1 is best; preference order only, not fixed model names):**

| P | Preferred model family | Rationale |
|---|-----------------------|-----------|
| P1 | deepseek family | Most stable for domestic Chinese traffic |
| P2 | gemini flash family | Google Gemini free tier |
| P3 | glm family | Fast GLM response in China |
| P4 | other free flash models | Last-resort fallback |

Match the discovered candidates against these preferences and pick the first with `status=="ok"` and `cool_until==null`. If none are available, tell the user directly — do not loop infinitely.

> Note: model IDs returned by `opencode models` (including versions) change over time. **Never hardcode a specific version in the decision logic.** The preference table is for sorting only; candidates always come from the dynamic list.

---

## 20 Scenarios Covered

| ID | Scenario | Action |
|----|----------|--------|
| S1 | New bot created without a model set | CHOOSE from health table |
| S2 | Main bot hits limit mid-conversation | DETECT → BROADCAST → SWITCH self + notify others |
| S3 | Child bot hits limit during delegated task | Child reports → main bot runs DETECT+BROADCAST → full group aligns |
| S4 | Multiple child bots hit same broken model | First detection triggers BROADCAST; others self-correct on next run |
| S5 | Multi-step pipeline breaks mid-way | Check health table before each step; switch proactively if needed |
| S6 | All known free models are down | STOP; tell the user; no infinite retry |
| S7 | Broken model recovers after cooldown | PROBE detects recovery; clears broken marker |
| S8 | opencode models list changes (new/removed) | Run `opencode models` on startup to refresh cache |
| S9 | User manually specified a model (override) | Respect choice; log health state but do not force-switch |
| S10 | Must downgrade to a paid model | Only when ALL free models are broken; announce explicitly before switching |
| S11 | Different models share the same API key | InstanceId-level management; flag whole instance, not individual models |
| S12 | Sub-agent hits limit mid-execution | Sub-agent callbacks to main bot; main bot decides the switch |
| S13 | Bot interrupted mid-generation by limit | Cannot resume; tell user to retry after the cooldown period |
| S14 | Health table stale (>2h old) | Treat as no state; clear cache; every bot re-probes independently |
| S15 | Same instance limited for bot-A but fine for bot-B | Unified instance-level handling; no per-bot differentiation (keep simple) |
| S16 | New bot cloned from existing bot config | Inherits the latest health-state-appropriate model, not the source bot's live config |
| S17 | Bots that make no LLM calls (e.g. pure browser ops) | Excluded; this skill only manages bots that actually send LLM requests |
| S18 | Cron job starts and hits a limit | Retry once after 5-minute delay; if still broken, skip that run and log reason |
| S19 | Multi-department environment (future) | Isolate health state by department scope |
| S20 | User says "switch to free models" | List all ok free combinations; default to P1 preference |

---

## Common Pitfalls (read carefully)

- **Do not use `limit-failovers.json` as your primary decision source.** It only records per-thread switches on the main bot and may route to a paid codex. This skill uses the shared `model-health.json` instead.
- **Do not switch models immediately on every error.** Classify first (A/B/C). UnknownError and timeouts should NOT trigger switches.
- **Do not cross department boundaries.** Only manage bots in the same section.
- **Stop and report when propose_profile returns pending.** Do not auto-retry.
- **Do not hardcode model names or local paths.** Read the model list dynamically from `opencode models`; derive the health table path from `$OMB_DATA_DIR` or `~/.openmausbot` — never include a username or drive letter.
- **Always BROADCAST after SWITCH.** Otherwise sibling bots keep hitting the same wall.
- **Never let child bots make their own fallback decisions.** They report up; the coordinator bot decides and broadcasts.

---

## Relationship with Existing Mechanisms

| Mechanism | This skill's posture |
|-----------|---------------------|
| `limit-failovers.json` | Read for historical signals; never use as sole decision basis |
| `sync-bot-models` skill | Complementary: sync handles manual alignment; router handles automatic failure avoidance |
| `ai.backupModel` app setting | App-level single-attempt fallback only kicks in before engine init; this skill covers mid-run limit scenarios |

---

## Implementation Checklist

Verify these items whenever deploying or adjusting this skill:

- [ ] Error classification covers all three categories (A/B/C); UnknownError does not trigger switching
- [ ] Health table path is derived from env var or home dir, with no hardcoded username/drive letter
- [ ] Auto-creates the health table directory if missing
- [ ] Checks whether last_updated exceeds 2 hours before trusting the file
- [ ] Verifies target model status is ok before every SWITCH
- [ ] BROADCAST reaches all peer bots, not just one
- [ ] Stops and reports to user when propose_profile returns pending
- [ ] New bot creation path invokes CHOOSE logic rather than reading static config
- [ ] Model candidates come from the dynamic `opencode models` list; preference table is for sorting only
- [ ] Does not override a user-manually-selected model (S9)
- [ ] Stops immediately and notifies the user when all models are broken (S6)
- [ ] Stores state at instanceId granularity, not per-individual-model granularity
