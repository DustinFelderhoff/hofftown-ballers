#!/usr/bin/env python3
"""
scrape.py — Sleeper API puller for Hofftown Ballers (Component A).

Stdlib-only (urllib.request). Refreshes data/*.json from the Sleeper API.
Idempotent: if a fetch fails, the existing data file is kept untouched and
the script continues with the rest. Data files are never deleted.

CLI:  python scrape.py
Prints a one-line summary, e.g.  week=2 teams=12 picks=180
Exits 0 even if some files were kept stale.
"""

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

API_BASE = "https://api.sleeper.app/v1"
LEAGUE_ID = "1392697506835472384"
DRAFT_ID = "1392697507577868288"

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")

TIMEOUT = 120
RETRY_DELAY = 10
PLAYERS_MAX_AGE_SECONDS = 24 * 60 * 60

UA = "hofftown-ballers-weekly-report/1.0"


def fetch_json(url):
    """GET a URL and parse the JSON body. Retries once with a 10s backoff."""
    last_error = None
    for attempt in (1, 2):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:  # noqa: BLE001 - any network/parse error
            last_error = exc
            if attempt == 1:
                time.sleep(RETRY_DELAY)
    raise last_error


def save_json(filename, data):
    """Atomically write data to data/<filename> (tmp file + os.replace).

    Never deletes existing data: the original file is only swapped in after
    the new content is fully written to disk.
    """
    os.makedirs(DATA_DIR, exist_ok=True)
    path = os.path.join(DATA_DIR, filename)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)
    return path


def fetch_and_save(url, filename):
    """Fetch url and write data/<filename>. On failure keep the existing file."""
    try:
        data = fetch_json(url)
        save_json(filename, data)
        print(f"  ok  {filename} ({len(data)} items)")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"  !!  {filename}: fetch failed ({exc}); keeping existing file")
        return False


def read_data_file(filename):
    """Read data/<filename>; returns None if missing or corrupt."""
    path = os.path.join(DATA_DIR, filename)
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def fallback_week():
    """If the state endpoint failed, guess the week from existing matchups files."""
    best = 1
    if os.path.isdir(DATA_DIR):
        for name in os.listdir(DATA_DIR):
            m = re.match(r"matchups_w(\d+)\.json$", name)
            if m:
                best = max(best, int(m.group(1)))
    return best


def main():
    print("scrape.py — Hofftown Ballers data refresh")
    kept_stale = 0

    # 1. State endpoint -> week / season / season_type
    week = None
    season = None
    season_type = None
    try:
        state = fetch_json(f"{API_BASE}/state/nfl")
        week = int(state.get("week") or 0)
        season = state.get("season")
        season_type = state.get("season_type")
        print(f"  ok  state/nfl (week={week} season={season} {season_type})")
    except Exception as exc:  # noqa: BLE001
        kept_stale += 1
        print(f"  !!  state/nfl: fetch failed ({exc}); deriving week from existing files")
        week = fallback_week()
        league = read_data_file("league.json")
        if league:
            season = league.get("season")
            season_type = league.get("season_type")

    if not week:
        week = 1

    # 2. League / draft / matchup fetches (always run)
    league_url = f"{API_BASE}/league/{LEAGUE_ID}"
    jobs = [
        (f"{league_url}", "league.json"),
        (f"{league_url}/users", "users.json"),
        (f"{league_url}/rosters", "rosters.json"),
        (f"{league_url}/drafts", "drafts.json"),
        (f"{API_BASE}/draft/{DRAFT_ID}/picks", "draft_picks.json"),
        (f"{API_BASE}/draft/{DRAFT_ID}/traded_picks", "traded_picks.json"),
        (f"{league_url}/matchups/{week}", f"matchups_w{week}.json"),
        (f"{league_url}/matchups/{week + 1}", f"matchups_w{week + 1}.json"),
    ]
    for url, filename in jobs:
        if not fetch_and_save(url, filename):
            kept_stale += 1

    # 3. players.json — huge; only refresh if missing or older than 24h
    players_path = os.path.join(DATA_DIR, "players.json")
    if os.path.exists(players_path) and (
        time.time() - os.path.getmtime(players_path)
    ) < PLAYERS_MAX_AGE_SECONDS:
        age_h = int((time.time() - os.path.getmtime(players_path)) // 3600)
        print(f"  --  players.json fresh ({age_h}h old); skipped")
    else:
        if not fetch_and_save(f"{API_BASE}/players/nfl", "players.json"):
            kept_stale += 1

    # 4. One-line summary from the on-disk data files
    users = read_data_file("users.json") or []
    picks = read_data_file("draft_picks.json") or []
    teams = len(users) if isinstance(users, list) else 0
    n_picks = len(picks) if isinstance(picks, list) else 0

    summary = f"week={week} teams={teams} picks={n_picks}"
    if kept_stale:
        summary += f" kept_stale={kept_stale}"
    print(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
