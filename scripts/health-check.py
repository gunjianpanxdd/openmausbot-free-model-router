#!/usr/bin/env python3
"""
OpenMausBot free-model-router health table viewer.

Usage:
    python health-check.py                  # show current state, color-coded
    python health-check.py --watch          # watch mode: refresh every 30s
    python health-check.py --path <file>    # custom path to model-health.json

Reads $OMB_DATA_DIR/shared/model-health.json if OMB_DATA_DIR is set,
otherwise ~/.openmausbot/shared/model-health.json.
Requires Python 3.10+.
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

DEFAULT_PATH = (
    Path(os.environ["OMB_DATA_DIR"]) / "shared" / "model-health.json"
    if os.environ.get("OMB_DATA_DIR")
    else Path.home() / ".openmausbot" / "shared" / "model-health.json"
)

STATUS_COLOR = {
    "ok":      "\033[32m",   # green
    "broken":  "\033[31m",   # red
    "cooldown":"\033[33m",   # yellow
}
RESET = "\033[0m"
BOLD  = "\033[1m"


def load(path: Path) -> dict:
    if not path.exists():
        print(f"[WARN] file not found: {path}", file=sys.stderr)
        sys.exit(1)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def fmt_time(iso_str: str | None) -> str:
    if iso_str is None:
        return "—"
    try:
        dt = datetime.fromisoformat(iso_str)
        return dt.strftime("%H:%M:%S")
    except Exception:
        return iso_str[:19]


def stale_since(data: dict) -> str | None:
    try:
        last = datetime.fromisoformat(data["last_updated"])
        age = datetime.now(last.tzinfo or timezone.utc) - last
        if age > timedelta(hours=2):
            mins = int(age.total_seconds() / 60)
            return f"{mins}min ago (过期)"
        return None
    except Exception:
        return None


def render_table(data: dict) -> None:
    print(BOLD + f"\n{'='*72}" + RESET)
    print(BOLD + f"  model-health.json  ({data.get('last_updated', '?')})" + RESET)
    age_note = stale_since(data)
    if age_note:
        print(f"  ⚠  {age_note}")
    print("  " + "-" * 70)
    print(f"  {'模型':<48} {'状态':<8} {'失败':<5} {'冷却截止'}")
    print("  " + "-" * 70)

    providers = data.get("providers", {})
    available = data.get("available_free_models", [])
    model_set = {(m["instanceId"], m["model"]) for m in available}

    for inst_id, entry in sorted(providers.items()):
        status = entry.get("status", "?")
        col = STATUS_COLOR.get(status, "\033[0m")
        fc = entry.get("fail_count", 0)
        cool = fmt_time(entry.get("cool_until"))
        # instance/model → display model name only
        parts = inst_id.split("/", 1)
        short_model = parts[1] if len(parts) > 1 else inst_id
        # truncate long model names
        display = short_model[:45] + ("…" if len(short_model) > 45 else "")
        print(f"  {col}{display:<48}{status:<8}{fc:<5}{cool or '—'}{RESET}")

    # summary
    ok_count = sum(1 for e in providers.values() if e.get("status") == "ok")
    broken_count = sum(1 for e in providers.values() if e.get("status") == "broken")
    total = len(providers)
    print("  " + "-" * 70)
    print(f"  合计: {ok_count} ok  ·  {broken_count} broken  ·  {total} tracked\n")


def main():
    parser = argparse.ArgumentParser(description="View OpenMausBot free-model-router health table")
    parser.add_argument("--path", default=str(DEFAULT_PATH), help="Path to model-health.json")
    parser.add_argument("--watch", action="store_true", help="Refresh every 30 seconds")
    args = parser.parse_args()

    path = Path(args.path)

    while True:
        try:
            data = load(path)
            render_table(data)
        except json.JSONDecodeError as e:
            print(f"[ERROR] invalid JSON in {path}: {e}", file=sys.stderr)
            break
        if not args.watch:
            break
        print("  (press Ctrl+C to stop)\n", end="", flush=True)
        time.sleep(30)


if __name__ == "__main__":
    main()
