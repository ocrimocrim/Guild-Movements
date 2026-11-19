#!/usr/bin/env python3
"""Track guild changes and checkpoint each confirmed Discord delivery."""
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, List

import requests
from bs4 import BeautifulSoup

URL = "https://pr-underworld.com/website/"
STATE_PATH = Path("players.json")
RECOVERY_PATH = Path("buffer-recovery.json")
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "GuildTracker/1.1 (+https://github.com/ocrimocrim/Guild-Movements)"})


def fetch_html(url: str) -> str:
    resp = SESSION.get(url, timeout=30)
    resp.raise_for_status()
    return resp.text


def parse_players(html: str) -> Dict[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    result = {}
    for row in soup.find_all("tr"):
        if not row.find("th", {"scope": "row"}):
            continue
        tds = row.find_all("td")
        if len(tds) >= 4:
            name = tds[0].get_text(strip=True)
            if name:
                result[name] = tds[3].get_text(" ", strip=True)
    return result


def load_state(path: Path) -> Dict[str, str]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in data.items()):
        raise ValueError("Invalid player state")
    return data


def save_json(path: Path, data) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")
    tmp.replace(path)


def message_for(name: str, old, new: str):
    if old is None:
        return f"🟢 **{name}** joined **{new}**." if new else None
    if old == new:
        return None
    if old and not new:
        return f"🔴 **{name}** left **{old}**."
    if not old:
        return f"🟢 **{name}** joined **{new}**."
    return f"🟡 **{name}** changed guild from **{old}** to **{new}**."


def diff_guilds(old: Dict[str, str], new: Dict[str, str]) -> List[str]:
    return [message for name, guild in new.items()
            if (message := message_for(name, old.get(name), guild))]


def merge_state(old: Dict[str, str], snapshot: Dict[str, str]) -> Dict[str, str]:
    return {**old, **snapshot}


def post_to_discord(webhook_url: str, messages: List[str]) -> None:
    if not webhook_url or not webhook_url.strip():
        raise ValueError("DISCORD_WEBHOOK_URL is missing")
    content = "\n".join(messages)
    # Discord's limit is 2000 UTF-16 code units. Never split an event.
    if len(content.encode("utf-16-le")) // 2 > 2000:
        raise ValueError("Discord message exceeds 2000 characters")
    response = SESSION.post(webhook_url, json={"content": content, "allowed_mentions": {"parse": []}}, timeout=30)
    response.raise_for_status()


def checkpoint(path: Path) -> None:
    """In Actions, persist each acknowledgement before sending the next event."""
    if os.getenv("GUILD_TRACKER_GIT_CHECKPOINT") == "1":
        subprocess.run(["git", "add", "--", str(path)], check=True)
        if subprocess.run(["git", "diff", "--cached", "--quiet"], check=False).returncode:
            subprocess.run(["git", "commit", "-m", "Checkpoint guild tracker state"], check=True)
            subprocess.run(["git", "push"], check=True)


def run_tracker(webhook_url: str) -> None:
    if not webhook_url or not webhook_url.strip():
        raise ValueError("DISCORD_WEBHOOK_URL is missing")
    old = load_state(STATE_PATH)
    current = parse_players(fetch_html(URL))
    if not current:
        raise ValueError("Player snapshot is empty")
    if not old:
        save_json(STATE_PATH, current)
        checkpoint(STATE_PATH)
        print("Baseline created")
        return
    for name, guild in current.items():
        message = message_for(name, old.get(name), guild)
        if message:
            post_to_discord(webhook_url, [message])
        if old.get(name) != guild or name not in old:
            old[name] = guild
            save_json(STATE_PATH, old)
            checkpoint(STATE_PATH)
        if message:
            print(message)


def replay_buffer(webhook_url: str) -> None:
    with RECOVERY_PATH.open(encoding="utf-8") as f:
        recovery = json.load(f)
    if recovery["delivered"]:
        print("BUFFER recovery already delivered")
        return
    post_to_discord(webhook_url, [recovery["message"]])
    recovery["delivered"] = True
    save_json(RECOVERY_PATH, recovery)
    checkpoint(RECOVERY_PATH)
    print("BUFFER recovery delivered")


def main() -> int:
    try:
        if len(sys.argv) == 2 and sys.argv[1] == "--replay-buffer":
            replay_buffer(os.getenv("DISCORD_WEBHOOK_URL", ""))
        elif len(sys.argv) == 1:
            run_tracker(os.getenv("DISCORD_WEBHOOK_URL", ""))
        else:
            raise ValueError("Usage: tracker.py [--replay-buffer]")
    except requests.RequestException as exc:
        # Exception strings can include the secret webhook URL.
        status = getattr(getattr(exc, "response", None), "status_code", None)
        print(f"Request failed (HTTP status: {status if status is not None else 'unavailable'})", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Tracker failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
