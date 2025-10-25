#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json
import sys
from pathlib import Path
from typing import Dict, List
import requests
from bs4 import BeautifulSoup

URL = "https://pr-underworld.com/website/"
STATE_PATH = Path("players.json")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "GuildTracker/1.1 (+https://github.com/yourrepo)"
})

def fetch_html(url: str) -> str:
    resp = SESSION.get(url, timeout=30)
    resp.raise_for_status()
    return resp.text

def parse_players(html: str) -> Dict[str, str]:
    """
    Returns mapping player_name -> guild_name
    Empty string if no guild is displayed
    """
    soup = BeautifulSoup(html, "html.parser")
    result: Dict[str, str] = {}

    for row in soup.find_all("tr"):
        th = row.find("th", {"scope": "row"})
        if not th:
            continue

        tds = row.find_all("td")
        if len(tds) < 4:
            continue

        name_cell = tds[0]
        guild_cell = tds[3]

        name = name_cell.get_text(strip=True)
        if not name:
            continue

        guild_text = guild_cell.get_text(" ", strip=True)
        guild = guild_text if guild_text else ""

        result[name] = guild

    return result

def load_state(path: Path) -> Dict[str, str]:
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_state(path: Path, data: Dict[str, str]) -> None:
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
    tmp.replace(path)

def diff_guilds(old: Dict[str, str], new: Dict[str, str]) -> List[str]:
    """
    Creates messages only for players present in the current snapshot.
    Missing players are ignored (offline players are not treated as guildless).
    """
    messages: List[str] = []
    for name, new_guild in new.items():
        old_guild = old.get(name, None)

        if old_guild is None:
            if new_guild:
                messages.append(f"🟢 **{name}** joined **{new_guild}**.")
            continue

        if old_guild == new_guild:
            continue

        if old_guild and not new_guild:
            messages.append(f"🔴 **{name}** left **{old_guild}**.")
        elif not old_guild and new_guild:
            messages.append(f"🟢 **{name}** joined **{new_guild}**.")
        else:
            messages.append(f"🟡 **{name}** changed guild from **{old_guild}** to **{new_guild}**.")

    return messages

def merge_state(old: Dict[str, str], snapshot: Dict[str, str]) -> Dict[str, str]:
    """
    Keeps old state for players not currently visible.
    Updates only those found in the current snapshot.
    """
    merged = dict(old)
    for name, guild in snapshot.items():
        merged[name] = guild
    return merged

def post_to_discord(webhook_url: str, messages: List[str]) -> None:
    if not messages:
        return
    content = "\n".join(messages)
    payload = {"content": content}
    resp = SESSION.post(webhook_url, json=payload, timeout=30)
    resp.raise_for_status()

def main() -> int:
    if not DISCORD_WEBHOOK_URL:
        print("Environment DISCORD_WEBHOOK_URL is missing", file=sys.stderr)

    try:
        html = fetch_html(URL)
        current = parse_players(html)
    except Exception as e:
        print(f"Error while fetching or parsing HTML. {e}", file=sys.stderr)
        return 1

    old = load_state(STATE_PATH)

    # First run: set baseline, no posts
    if not old:
        save_state(STATE_PATH, current)
        print("Baseline created")
        return 0

    messages = diff_guilds(old, current)

    try:
        if DISCORD_WEBHOOK_URL and messages:
            post_to_discord(DISCORD_WEBHOOK_URL, messages)
    except Exception as e:
        print(f"Discord Webhook error. {e}", file=sys.stderr)

    merged = merge_state(old, current)

    try:
        save_state(STATE_PATH, merged)
    except Exception as e:
        print(f"Error while saving players.json. {e}", file=sys.stderr)
        return 1

    if messages:
        print("Changes detected:")
        for m in messages:
            print(m)
    else:
        print("No changes")

    return 0

if __name__ == "__main__":
    sys.exit(main())
