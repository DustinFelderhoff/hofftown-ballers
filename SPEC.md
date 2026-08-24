# Hofftown Ballers — Weekly Kid-Friendly Fantasy Report System

Architecture specification (spec-as-contract). Three parallel builders implement components A, B, C against THIS document. All file paths are absolute. All JSON contracts are exact — do not rename fields.

## 1. Overview

Automated weekly fantasy football report for the Sleeper league **Hofftown Ballers** (12 teams, 2026 season), hosted on GitHub Pages. Pipeline runs **weekly via GitHub Actions cron**:

```
scrape.py  →  writer.py  →  reviewer.py  →  build_site.py  →  GitHub Pages deploy
(Sleeper API)  (DeepSeek LLM)  (safety gate)    (HTML render)
```

The report is written for **elementary-school kids** (grades 2-4 reading level): playful banter, zero profanity, zero bullying, never puts anyone down. Every team gets a **positive** AND a gentle **negative/needs-work** note every week.

**Repo:** `C:/Users/dusti/Projects/hofftown-ballers` (git repo, `main` branch, remote `origin` = github.com/DustinFelderhoff/hofftown-ballers)
**Pages URL:** `https://dustinfelderhoff.github.io/hofftown-ballers/`
**Pages mode:** `build_type: workflow` (already enabled — deploy via `actions/deploy-pages`)
**Secret:** `DEEPSEEK_API_KEY` already stored in repo secrets.

## 2. File Layout (exact paths)

```
C:/Users/dusti/Projects/hofftown-ballers/
├── scrape.py                      # A: Sleeper API puller
├── writer.py                      # B: LLM report writer
├── reviewer.py                    # C: safety gate (blocklist + LLM review + auto-fix)
├── build_site.py                  # C: HTML site renderer
├── bad_words.py                   # C: blocklist data + scan function
├── requirements.txt               # A: empty or stdlib-only note
├── README.md                      # A: what this is, how to run
├── data/                          # scraped JSON (git-committed)
│   ├── league.json                # league metadata (already present)
│   ├── users.json                 # user_id → display_name (already present)
│   ├── rosters.json               # roster_id → owner_id, starters, settings (already present)
│   ├── drafts.json                # draft metadata (already present)
│   ├── draft_picks.json           # 180 picks, full metadata (already present)
│   ├── traded_picks.json          # (already present)
│   ├── matchups_w1.json           # week 1 matchups (already present)
│   ├── matchups_w2.json           # week 2 matchups (already present)
│   └── players.json               # full NFL player dump (already present, ~12k players)
├── report.json                    # B output / C input (generated, gitignored)
├── report.reviewed.json           # C final output (generated, gitignored)
├── site/
│   ├── index.html                 # current week's report (C output, gitignored, deployed)
│   └── archive/index.html         # list of past reports (C output, gitignored, deployed)
└── .github/workflows/weekly-report.yml   # A: cron + Pages deploy
```

`.gitignore` additions (Agent A): `report.json`, `report.reviewed.json`, `site/`, `__pycache__/`.

## 3. Data Files (read-only inputs for writer)

All already present in `data/`. Writer must read these, never modify.

- `league.json`: `{name, season, total_rosters, roster_positions, settings, status}` — 12 teams.
- `users.json`: array of `{user_id, display_name, avatar}` — 12 users. **Team name = `display_name`** (e.g. "Stinger005", "TheBrodinators"). This is what the report calls each team.
- `rosters.json`: array of `{roster_id, owner_id, settings:{wins,losses,fpts,waiver_budget,...}, players:[...], starters:[...]}`.
- `draft_picks.json`: 180 picks, each `{pick_no, round, roster_id, player_id, metadata:{first_name,last_name,position,team,years_exp}}`. Pick 1 = round 1, pick_no 1 (1.01).
- `matchups_w1.json` / `matchups_w2.json`: array per roster `{roster_id, matchup_id, points, starters, players}`. Group by `matchup_id` to get pairings.
- `players.json`: dict player_id → `{full_name, position, team, fantasy_positions, ...}`.

**Important:** the league is in PRESEASON week 2. All fantasy points are 0. This week's report is a **Draft Analyzer special** — no real game results yet. Matchups exist for week 2 (next week's previews).

## 4. Report JSON Contract (writer output / reviewer input / site input)

`report.json` (writer → reviewer) and `report.reviewed.json` (reviewer → site) share this shape. Reviewer adds `reviews` array and may rewrite any string field. **Exact schema:**

```json
{
  "meta": {
    "league": "Hofftown Ballers",
    "season": 2026,
    "week": 2,
    "season_type": "pre",
    "generated_at": "2026-08-24T00:00:00Z",
    "special": "draft_analyzer",
    "report_title": "Week 2: The Big Draft Recap!",
    "writer_model": "deepseek-v4-flash",
    "reviewer_model": "deepseek-v4-pro"
  },
  "sections": {
    "overview": {
      "title": "Welcome to the League!",
      "content": "kid-friendly markdown/plain text (may contain **bold**, emoji)"
    },
    "draft_analyzer": {
      "title": "Draft Analyzer",
      "summary": "paragraph summarizing the draft",
      "fun_facts": ["fact one", "fact two"],
      "team_grades": [
        {
          "team": "Stinger005",
          "grade": "A-",
          "best_pick": "Bijan Robinson (RB, 1.05)",
          "sleeper_pick": "A kicker in round 14!",
          "positive": "why this draft was good",
          "needs_work": "gentle note on a weakness, never mean"
        }
      ]
    },
    "matchup_previews": {
      "title": "Next Week's Matchups!",
      "previews": [
        {
          "team_a": "TeamNameA",
          "team_b": "TeamNameB",
          "preview": "kid-friendly paragraph about the matchup"
        }
      ]
    },
    "team_updates": {
      "title": "Team News & Updates",
      "teams": [
        {
          "team": "TeamName",
          "positive": "something going well",
          "needs_work": "gentle something to watch out for",
          "update": "one-line news/update about this team"
        }
      ]
    }
  },
  "reviews": [
    {
      "section": "overview",
      "verdict": "PASS",
      "notes": "clean"
    }
  ]
}
```

**Hard rules for writer output:**
- ALL 12 teams appear in `draft_analyzer.team_grades` AND in `team_updates.teams` (12 entries each). No team left out.
- `matchup_previews.previews` = exactly 6 entries (12 teams / 2). Pair from `matchups_w2.json` by `matchup_id`.
- Every team entry has BOTH `positive` AND `needs_work` — always both, always gentle.
- `meta.week` comes from Sleeper state (week 2). `meta.special` = `"draft_analyzer"` this week.
- Content is grades-2-4 reading level. Short sentences. Fun. Playful. Emoji ok. **No profanity, no insults, no name-calling, no 'sucks', no 'trash', no 'worst ever', no putting anyone down.**

## 5. DeepSeek API Contract

OpenAI-compatible chat completions. Endpoint: `POST https://api.deepseek.com/chat/completions`
Auth: `Authorization: Bearer $DEEPSEEK_API_KEY` (env var; present locally in `C:/Users/dusti/AppData/Local/hermes/.env`, and as GitHub secret).

Models (verified available):
- `deepseek-v4-flash` — general writing (cheap)
- `deepseek-v4-pro` — draft analyzer + reviewer (quality)

Request:
```json
{"model": "deepseek-v4-flash", "messages": [{"role": "system", "content": "..."}, {"role": "user", "content": "..."}], "max_tokens": 4000, "temperature": 0.8, "response_format": {"type": "json_object"}}
```
Response: `.choices[0].message.content` (JSON string when `response_format` set).

**Implementation requirement:** use ONLY Python stdlib (`urllib.request`), no third-party deps — GitHub Actions runners won't have requests. Timeout 120s, retry once on 429/5xx with 10s backoff. Never print the API key.

## 6. Component A — scrape.py + workflow + README

### scrape.py
Stdlib-only. Pulls Sleeper API and refreshes `data/` files (idempotent; if a fetch fails, keep the existing file and continue — never delete data). Endpoints:
- `https://api.sleeper.app/v1/state/nfl` → derive `week`, `season`, `season_type`
- `https://api.sleeper.app/v1/league/1392697506835472384` → `data/league.json`
- `.../league/1392697506835472384/users` → `data/users.json`
- `.../league/1392697506835472384/rosters` → `data/rosters.json`
- `.../league/1392697506835472384/drafts` → `data/drafts.json`
- `.../draft/1392697507577868288/picks` → `data/draft_picks.json`
- `.../draft/1392697507577868288/traded_picks` → `data/traded_picks.json`
- `.../league/1392697506835472384/matchups/{week}` for week and week+1 → `data/matchups_w{week}.json`
- `https://api.sleeper.app/v1/players/nfl` → `data/players.json` (large; only if missing or older than 24h)

CLI: `python scrape.py` — writes files, prints a one-line summary (`week=2 teams=12 picks=180`). Exit 0 on success even if some files were kept stale.

### .github/workflows/weekly-report.yml
- Trigger: `schedule` cron `0 14 * * 2` (Tue 14:00 UTC = 8am MT) + `workflow_dispatch`.
- Job `report` on `ubuntu-latest`:
  1. checkout (fetch-depth 1)
  2. `actions/setup-python@v5` python 3.11
  3. `python scrape.py`
  4. `python writer.py` with `env: DEEPSEEK_API_KEY: ${{ secrets.DEEPSEEK_API_KEY }}`
  5. `python reviewer.py`
  6. `python build_site.py`
  7. `actions/configure-pages@v5`, `actions/upload-pages-artifact@v3` with `path: site/`, `actions/deploy-pages@v4`
- `permissions: contents: read, pages: write, id-token: write`
- `concurrency: group: pages, cancel-in-progress: true`
- If writer.py fails (LLM down), the run fails and Pages keeps the last good deploy (upload artifact step never runs) — acceptable.

### README.md
Brief: what it is, pipeline diagram, how to run locally (`python scrape.py && python writer.py && python reviewer.py && python build_site.py`), how to trigger manually (Actions → Run workflow).

## 7. Component B — writer.py

Reads `data/*.json`, calls DeepSeek, writes `report.json`.

### Steps
1. Build a **context digest** (plain text) from the data: league name, 12 teams with display names + roster_ids, each team's draft picks (pick_no, round, player name/pos/team) grouped by team, draft order highlights (who had pick 1.01 etc.), week-2 matchups as team-vs-team pairs.
2. Call DeepSeek **once per section** (4 calls total: overview, draft_analyzer, matchup_previews, team_updates). Draft analyzer call uses `deepseek-v4-pro`; other three use `deepseek-v4-flash`. Each call requests strict JSON matching the section's contract shape (see §4). System prompt for every call includes the **tone rules** (below).
3. Merge section JSONs into `report.json` per §4 schema, write with `json.dump(..., indent=2)`.
4. Validate: exactly 12 team grades, exactly 12 team updates, exactly 6 previews. If validation fails, retry that section once, then fill missing teams with generic kind entries (never crash).
5. Print one-line summary: `report.json written: sections=4 teams=12 previews=6`.

### Tone rules (MUST be in every system prompt, verbatim-ish)
```
You are writing a weekly fantasy football report for ELEMENTARY SCHOOL KIDS (grades 2-4).
Rules:
- Reading level: grades 2-4. Short sentences. Simple words. Playful and fun like a kid's sports show.
- Use emoji. Be enthusiastic. Make it fun to read.
- NEVER use bad words. NEVER insult anyone. NEVER put anyone or any team down. No name-calling.
- No words like: sucks, trash, terrible, awful, stupid, dumb, loser, worst, garbage, boring, hate.
- For every team, ALWAYS include BOTH a positive AND a gentle "needs work" note. The needs-work note is a friendly heads-up (e.g. "their bench is a little thin" or "watch out for bye weeks"), NEVER mean.
- Trash talk is OK only as playful, friendly banter that wouldn't hurt anyone's feelings.
- The kids know the league members by their Sleeper display names — use those as team names.
```
### Pitfalls
- The context digest for 180 picks is big — keep player info terse (`Bijan Robinson (RB)`, `Aubrey (K DAL)`).
- The draft pick 1.01 was a KICKER (Brandon Aubrey, K DAL, roster 12) — that's a fun fact for the analyzer, treat it playfully, not as an insult to that team.
- `rosters.json` `players` arrays are player_ids; resolve names via `players.json`. Draft picks already carry `metadata` with names — prefer that (cheaper).

## 8. Component C — reviewer.py + bad_words.py + build_site.py

### bad_words.py
- `BLOCKLIST`: list of profanity + bullying-adjacent words/phrases (asshole, bitch, crap, damn, dick, dumbass, fag, fuck, idiot, jerk, loser, moron, piss, retard, shit, suck(s), trash, stupid, turd, etc. — comprehensive; include variations like 'sucks', 'sucked').
- `scan_text(text) -> list[str]`: case-insensitive word-boundary scan returning matched words. Also scans emoji-free ASCII. Must catch 'sucks' inside 'sucked'.

### reviewer.py
Reads `report.json`, enforces the safety gate, writes `report.reviewed.json`.

Pipeline per section (overview, draft_analyzer, matchup_previews, team_updates — and each nested text field):
1. **Blocklist scan** (`bad_words.scan_text` on every string field). If hits → **FAIL**, auto-fix: call DeepSeek `deepseek-v4-pro` asking to rewrite that section removing the flagged words, keeping the same JSON structure. Re-scan. Max 2 auto-fix rounds; if still failing, replace offending field with a generic kind sentence.
2. **LLM review** with `deepseek-v4-pro`: send the section + tone rules (§7) and ask for strict JSON: `{"verdict": "PASS"|"FAIL", "issues": ["..."], "suggestion": "..."}`. Verdict FAIL if: profanity, bullying, putting anyone down, mean-spirited, or reading level too high. If FAIL → rewrite via pro model with the suggestion → re-review. Max 2 rounds.
3. **Structure check** (no LLM): all 12 teams in team_grades and team_updates; both positive+needs_work present and non-empty; 6 previews with team_a≠team_b.
4. Append to `reviews` array: `{section, verdict, notes}` — one entry per section (4 entries).
5. If any section FAILed and was rewritten, the review entry notes it: `{"section": "draft_analyzer", "verdict": "PASS (fixed)", "notes": "removed 2 flagged words"}`.
6. Write `report.reviewed.json` (same schema, `reviews` populated, possibly rewritten fields). Print summary: `reviewed: 4/4 PASS, 0 FAIL, fixed=2`.

**Hard fail rule:** if after all retries a section still FAILs, DO NOT write report.reviewed.json — exit 1 with a clear message (prevents deploying unsafe content). The Actions run will fail and last week's site stays live.

### build_site.py
Reads `report.reviewed.json`, renders a **fun, colorful, kid-friendly** static site:
- `site/index.html` — full current report. Design: bright gradient header (e.g. #FF6B35 → #FFD166 → #06D6A0), big rounded cards, emoji everywhere, friendly rounded font (system stack: `'Comic Sans MS', 'Chalkboard SE', 'Comic Neue', cursive, sans-serif`), section headings with emoji, team cards with green ⬆ positive / orange ⬇ needs-work, draft grades as big letter badges (green A, yellow B, orange C), matchup cards as "Team A vs Team B" with ⚔️. Footer: "Made with ❤️ for Hofftown Ballers · Updated {date}".
- `site/archive/index.html` — list of past reports (for now: just the current one, labeled "Week 2 — Draft Analyzer Special"; link back to index.html). Structure it so future weeks append (build_site.py reads a `site/archive/reports.json` if present; if absent, creates one with this week).
- Self-contained: single HTML file, inline CSS, no external fonts/CDNs (must render offline).
- Print: `site built: index.html + archive`.

## 9. Verification (each builder runs these before reporting done)

- **A:** `python scrape.py` → prints summary line; `git status` shows only data/ changes at most; workflow YAML parses (`python -c "import yaml"` may not exist — instead check with a simple grep for `on:` / `schedule:` / `deploy-pages`).
- **B:** run `python writer.py` with key sourced from `C:/Users/dusti/AppData/Local/hermes/.env`; verify `report.json` exists, has 12 team_grades + 12 teams + 6 previews (`python -c "import json; r=json.load(open('report.json')); print(len(r['sections']['draft_analyzer']['team_grades']), len(r['sections']['team_updates']['teams']), len(r['sections']['matchup_previews']['previews']))"` → `12 12 6`).
- **C:** run `python reviewer.py` on the report.json B produced; verify `report.reviewed.json` exists with 4 reviews, all PASS. Then `python build_site.py`; verify `site/index.html` exists and contains `<html` and `Hofftown`.

## 10. Do NOT touch

- `data/*.json` content (read-only inputs) — A may refresh via scrape.py, B/C never write there.
- The DeepSeek API key — never print it, never commit it.
- GitHub Pages settings (already configured correctly).
- Other repos/projects.
