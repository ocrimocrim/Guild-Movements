#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json
import sys
from pathlib import Path
from typing import Dict, Tuple, List
import requests
from bs4 import BeautifulSoup

URL = "https://pr-underworld.com/website/"
STATE_PATH = Path("players.json")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "GuildTracker/1.0 (+https://github.com/yourrepo)"
})

def fetch_html(url: str) -> str:
    resp = SESSION.get(url, timeout=30)
    resp.raise_for_status()
    return resp.text

def parse_players(html: str) -> Dict[str, str]:
    """
    Liefert ein Mapping Spielername -> Gildenname
    Leerer String wenn keine Gilde angezeigt wird
    """
    soup = BeautifulSoup(html, "html.parser")
    result: Dict[str, str] = {}

    # Suche alle Tabellenzeilen mit einem Rang-Th
    for row in soup.find_all("tr"):
        th = row.find("th", {"scope": "row"})
        if not th:
            continue

        tds = row.find_all("td")
        if len(tds) < 4:
            # Erwartet: Name, Level, Job, Guild
            continue

        name_cell = tds[0]
        guild_cell = tds[3]

        name = name_cell.get_text(strip=True)
        if not name:
            continue

        # Gilde extrahieren. Bild ignorieren, Text nehmen
        # Beispiel: <td><img ...> Momentum</td>
        guild_text = guild_cell.get_text(" ", strip=True)
        # Manche Zeilen enthalten nur ein Bild ohne Text
        guild = guild_text if guild_text else ""

        result[name] = guild

    return result

def load_state(path: Path) -> Dict[str, str]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)

def save_state(path: Path, data: Dict[str, str]) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)

def diff_guilds(old: Dict[str, str], new: Dict[str, str]) -> List[str]:
    """
    Erzeugt menschenlesbare Meldungen
    Join wenn alt leer und neu gesetzt
    Leave wenn alt gesetzt und neu leer
    Wechsel wenn alt gesetzt und neu gesetzt und verschieden
    Meldungen werden nur einmal erzeugt, weil der neue Zustand danach gespeichert wird
    """
    messages: List[str] = []

    # Relevante Spieler sind die, die im neuen Snapshot vorkommen
    # Wenn alte Spieler nicht mehr in der Liste stehen, wird nichts gemeldet
    # weil die Website vermutlich nur Top-Listen zeigt
    for name, new_guild in new.items():
        old_guild = old.get(name, "")
        if old_guild == new_guild:
            continue
        if old_guild == "" and new_guild != "":
            messages.append(f"🟢 {name} ist der Gilde {new_guild} beigetreten.")
        elif old_guild != "" and new_guild == "":
            messages.append(f"🔴 {name} hat die Gilde {old_guild} verlassen.")
        elif old_guild != "" and new_guild != "":
            messages.append(f"🟡 {name} ist von {old_guild} zu {new_guild} gewechselt.")

    return messages

def post_to_discord(webhook_url: str, messages: List[str]) -> None:
    if not messages:
        return
    # Discord Rate Limits respektieren, aber hier reicht ein Batch
    content = "\n".join(messages)
    payload = {"content": content}
    resp = SESSION.post(webhook_url, json=payload, timeout=30)
    resp.raise_for_status()

def main() -> int:
    if not DISCORD_WEBHOOK_URL:
        print("Environment DISCORD_WEBHOOK_URL fehlt", file=sys.stderr)
        # Trotzdem JSON aktualisieren, aber ohne Posts
        # Rückgabecode 0, damit der Workflow nicht fehlschlägt
    try:
        html = fetch_html(URL)
        current = parse_players(html)
    except Exception as e:
        print(f"Fehler beim Abruf oder Parsing. {e}", file=sys.stderr)
        return 1

    old = load_state(STATE_PATH)
    messages = diff_guilds(old, current)

    # Erst posten, dann speichern und commit im Workflow
    try:
        if DISCORD_WEBHOOK_URL and messages:
            post_to_discord(DISCORD_WEBHOOK_URL, messages)
    except Exception as e:
        # Falls Discord ausfällt, dennoch State aktualisieren, damit keine Flut entsteht
        print(f"Discord Webhook Fehler. {e}", file=sys.stderr)

    try:
        save_state(STATE_PATH, current)
    except Exception as e:
        print(f"Fehler beim Speichern von players.json. {e}", file=sys.stderr)
        return 1

    # Console Log für die Action
    if messages:
        print("Änderungen")
        for m in messages:
            print(m)
    else:
        print("Keine Änderungen")

    return 0

if __name__ == "__main__":
    sys.exit(main())
