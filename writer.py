#!/usr/bin/env python3
"""writer.py — Component B of the Hofftown Ballers weekly report system.

Reads data/*.json, builds a terse plain-text context digest, calls the DeepSeek
API once per section (4 calls: overview, draft_analyzer, matchup_previews,
team_updates), and merges the section JSONs into report.json per SPEC section 4.

Stdlib only (urllib.request) — GitHub Actions runners have no third-party deps.

Usage:
    set -a; source <path-to-hermes>/.env; set +a
    python writer.py

Never prints or commits the API key. Never modifies data/*.json.
"""

import json
import os
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
REPORT_PATH = os.path.join(BASE_DIR, "report.json")

API_URL = "https://api.deepseek.com/chat/completions"
MODEL_FLASH = "deepseek-v4-flash"
MODEL_PRO = "deepseek-v4-pro"
TIMEOUT_SEC = 120
TEMP = 0.8
# deepseek-v4-pro is a reasoning model: max_tokens covers BOTH its reasoning
# tokens and the final answer. A small budget gets eaten entirely by reasoning
# and the answer comes back empty, so pro gets a much larger budget.
MAX_TOKENS_BY_MODEL = {MODEL_FLASH: 4000, MODEL_PRO: 20000}

# Report week: the league is in PRESEASON week 2 and this week's report is the
# Draft Analyzer special (SPEC §3, §4). Week-2 matchups (matchups_w2.json) are
# the upcoming games the previews are written for.
REPORT_WEEK = 2

# ── Tone rules (SPEC section 7) — MUST be in every system prompt ────────────

TONE_RULES = """You are writing a weekly fantasy football report for ELEMENTARY SCHOOL KIDS (grades 2-4).
Rules:
- Reading level: grades 2-4. Short sentences. Simple words. Playful and fun like a kid's sports show.
- Use emoji. Be enthusiastic. Make it fun to read.
- NEVER use bad words. NEVER insult anyone. NEVER put anyone or any team down. No name-calling.
- No words like: sucks, trash, terrible, awful, stupid, dumb, loser, worst, garbage, boring, hate.
- For every team, ALWAYS include BOTH a positive AND a gentle "needs work" note. The needs-work note is a friendly heads-up (e.g. "their bench is a little thin" or "watch out for bye weeks"), NEVER mean.
- Trash talk is OK only as playful, friendly banter that wouldn't hurt anyone's feelings.
- The kids know the league members by their Sleeper display names — use those as team names."""

SYSTEM_OVERVIEW = TONE_RULES + """

You are writing the "overview" section of this week's kid-friendly fantasy football report.
It is PRESEASON week 2, and this week is the DRAFT ANALYZER SPECIAL: no real games have been played yet, all fantasy points are 0.
Write a warm, exciting welcome (2-4 short sentences) that tells the kids this week is all about the draft recap, and name one fun draft detail.
Use emoji. Keep every sentence short and simple (grades 2-4 reading level).
Respond ONLY with valid JSON in exactly this shape: {"content": "the welcome text"}.
Do not add any other fields."""

SYSTEM_DRAFT = TONE_RULES + """

You are the "Draft Analyzer" of a kid-friendly fantasy football report.
The league is in PRESEASON week 2 — no real games yet, so the draft is the whole story.
Grade ALL 12 teams' drafts. Be fair, kind, and playful. Every team entry MUST have BOTH a "positive" AND a gentle "needs_work" note.
Use the EXACT Sleeper display names given for each team — the kids know these names.
- "grade": a letter grade like A+, A, A-, B+, B, B-, C+ (be encouraging, no one gets an F).
- "best_pick": the team's best pick, formatted like "Bijan Robinson (RB, 1.05)".
- "sleeper_pick": a sneaky late-round gem or a fun pick (e.g. "A kicker in round 14!").
- "fun_facts": 2-4 short playful facts about the draft overall.
The 1.01 pick was a KICKER (Brandon Aubrey, K DAL) — that is a silly, playful fun fact, NOT something to make fun of any team for.
Respond ONLY with valid JSON in exactly this shape:
{"summary": "one paragraph about the draft", "fun_facts": ["fact one", "fact two"], "team_grades": [{"team": "exact display name", "grade": "A-", "best_pick": "Player (POS, round.pick)", "sleeper_pick": "fun pick note", "positive": "why this draft was good", "needs_work": "gentle heads-up, never mean"}]}
Include ALL 12 teams in team_grades. Do not add any other fields."""

SYSTEM_MATCHUPS = TONE_RULES + """

You are writing the "Next Week's Matchups" section of a kid-friendly fantasy football report.
It is PRESEASON week 2, so these are the WEEK 2 games coming up (next week). All fantasy points are 0 so far — no results yet.
Write exactly 6 matchup previews, team vs team. For each matchup write 1-3 short, fun, hype sentences.
Friendly banter only — never mean, never putting a team down.
Use the EXACT team_a and team_b display names given for each pairing.
Respond ONLY with valid JSON in exactly this shape:
{"previews": [{"team_a": "exact name", "team_b": "exact name", "preview": "kid-friendly paragraph"}]}
Exactly 6 previews. Do not add any other fields."""

SYSTEM_TEAMS = TONE_RULES + """

You are writing the "Team News & Updates" section of a kid-friendly fantasy football report.
It is PRESEASON week 2 — the Draft Analyzer special. No real games yet.
Write exactly 12 team entries, one per team, in kid-friendly language.
For every team include ALL three fields:
- "positive": something going well for this team (e.g. a great pick, a fun squad).
- "needs_work": a gentle heads-up about something to watch (e.g. "their bench is a little thin" or "watch out for bye weeks") — NEVER mean.
- "update": one short newsy line about the team (a draft highlight or their week 2 matchup).
Use the EXACT Sleeper display names given. Use emoji. Short sentences.
Respond ONLY with valid JSON in exactly this shape:
{"teams": [{"team": "exact display name", "positive": "something going well", "needs_work": "gentle something to watch", "update": "one-line news"}]}
Exactly 12 entries — ALL 12 teams. Do not add any other fields."""

# ── Generic kind fallbacks (never mean, grades 2-4) ─────────────────────────

GENERIC_OVERVIEW = (
    "Welcome to the Hofftown Ballers! 🏈 This week is our Draft Analyzer Special. "
    "No real games yet — but our draft was a blast! Every team has a fun squad. Let's go! ⭐"
)

GENERIC_GRADE = {
    "grade": "B",
    "best_pick": "The whole squad is ready to go!",
    "sleeper_pick": "This team is full of fun players!",
    "positive": "This team has a great group of players and lots of team spirit! 🏈",
    "needs_work": "We will know more once the real games start. Watch out for bye weeks!",
}

GENERIC_UPDATE = {
    "positive": "This team is ready to play and have fun! 🏈",
    "needs_work": "Watch for bye weeks later in the season.",
    "update": "This team is all set for week 2!",
}


# ── Data loading & context digest (SPEC section 7, step 1) ──────────────────

def load_json(name):
    with open(os.path.join(DATA_DIR, name), "r", encoding="utf-8") as f:
        return json.load(f)


def _normalize(name):
    return re.sub(r"\s+", " ", str(name or "")).strip().casefold()


def build_context():
    """Load data/*.json into a small plain structure. Never modifies data."""
    league = load_json("league.json")
    users = load_json("users.json")
    rosters = load_json("rosters.json")
    drafts = load_json("drafts.json")
    picks = load_json("draft_picks.json")
    matchups_w2 = load_json("matchups_w2.json")
    user_name = {u["user_id"]: u["display_name"] for u in users}
    rosters_sorted = sorted(rosters, key=lambda r: int(r["roster_id"]))
    teams = []  # [(roster_id:int, display_name:str)] in roster order
    for r in rosters_sorted:
        owner = r["owner_id"]
        name = user_name.get(owner) or f"Team {r['roster_id']}"
        teams.append((int(r["roster_id"]), name))

    # draft slot per owner (1..12) from draft_order, plus per-roster picks
    draft_order = {}
    for d in drafts:
        draft_order.update(d.get("draft_order") or {})
    slot_by_roster = {
        int(r["roster_id"]): int(draft_order.get(r["owner_id"], 0)) or None
        for r in rosters_sorted
    }

    by_roster = {rid: [] for rid, _ in teams}
    by_pickno = {}
    for p in picks:
        rid = int(p.get("roster_id"))
        if rid in by_roster:
            by_roster[rid].append(p)
        by_pickno[int(p.get("pick_no"))] = p
    for rid in by_roster:
        by_roster[rid].sort(key=lambda p: int(p["pick_no"]))

    # Report week is fixed by the pipeline state: preseason week 2, Draft
    # Analyzer special (SPEC §3, §4). Previews use matchups_w2.json.
    week = REPORT_WEEK

    # week-2 pairings grouped by matchup_id, ordered by matchup_id
    groups = {}
    for m in matchups_w2:
        groups.setdefault(m["matchup_id"], []).append(int(m["roster_id"]))
    team_by_roster = {rid: name for rid, name in teams}
    pairs = []
    for mid in sorted(groups):
        rids = sorted(groups[mid])
        if len(rids) >= 2 and rids[0] != rids[1]:
            pairs.append({"team_a": team_by_roster[rids[0]], "team_b": team_by_roster[rids[1]]})

    return {
        "league_name": league.get("name", "Hofftown Ballers"),
        "season": int(league.get("season", 2026)),
        "week": week,
        "teams": teams,
        "by_roster": by_roster,
        "by_pickno": by_pickno,
        "slot_by_roster": slot_by_roster,
        "draft_order": draft_order,
        "pairs": pairs,
    }


def pick_label(p, n_teams):
    """Terse player label, preferring draft-pick metadata (SPEC §7 pitfalls)."""
    md = p.get("metadata") or {}
    first = (md.get("first_name") or "").strip()
    last = (md.get("last_name") or "").strip()
    pos = (md.get("position") or "").strip()
    team = (md.get("team") or "").strip()
    name = f"{first} {last}".strip() if (first or last) else "Unknown"
    tag = " ".join(x for x in (pos, team) if x)
    return f"{name} ({tag})" if tag else name


def pick_notation(pick_no, n_teams):
    r = (int(pick_no) - 1) // n_teams + 1
    p = (int(pick_no) - 1) % n_teams + 1
    return f"{r}.{p:02d}"


def build_digest(ctx):
    n_teams = len(ctx["teams"])
    lines = []
    lines.append(f"{ctx['league_name'].upper()} — {ctx['season']} SEASON, PRESEASON WEEK {ctx['week']}")
    lines.append("DRAFT ANALYZER SPECIAL: no real games have been played yet (all fantasy points are 0).")
    lines.append("Draft: snake draft, 15 rounds, 180 picks total, complete.")

    lines.append("")
    lines.append("DRAFT ORDER (pick slot -> team):")
    slot_to_team = {}
    for rid, name in ctx["teams"]:
        slot = ctx["slot_by_roster"].get(rid)
        if slot:
            slot_to_team[slot] = name
    for slot in sorted(slot_to_team):
        lines.append(f"  {slot}. {slot_to_team[slot]}")

    lines.append("")
    lines.append("TEAMS (roster_id | draft slot | display name):")
    for rid, name in ctx["teams"]:
        slot = ctx["slot_by_roster"].get(rid)
        lines.append(f"  roster {rid} (slot {slot if slot else '?'}): {name}")

    lines.append("")
    lines.append("TEAM DRAFT PICKS (pick = round.pick-in-round, player (position NFL-team)); mix = position counts:")
    for rid, name in ctx["teams"]:
        plist = ctx["by_roster"].get(rid, [])
        parts = [f"{pick_notation(p['pick_no'], n_teams)} {pick_label(p, n_teams)}" for p in plist]
        counts = {}
        for p in plist:
            pos = (p.get("metadata") or {}).get("position") or "?"
            counts[pos] = counts.get(pos, 0) + 1
        mix = " ".join(f"{pos}{n}" for pos, n in sorted(counts.items()))
        lines.append(f"  {name}: " + "; ".join(parts) + f"  | mix: {mix}")

    lines.append("")
    lines.append("WEEK 2 MATCHUPS (next week's games, team vs team):")
    for i, pr in enumerate(ctx["pairs"], 1):
        lines.append(f"  matchup {i}: {pr['team_a']} vs {pr['team_b']}")

    lines.append("")
    lines.append("FUN FACTS FOR THE ANALYZER:")
    p1 = ctx["by_pickno"].get(1)
    if p1:
        rid = int(p1["roster_id"])
        tname = dict(ctx["teams"]).get(rid, f"roster {rid}")
        md = p1.get("metadata") or {}
        lines.append(f"  - The very first pick of the draft (1.01) was {md.get('first_name','?')} {md.get('last_name','?')}, a KICKER ({md.get('position','?')}, {md.get('team','?')}), taken by {tname} (who had the #1 pick). Playful fun fact — NOT an insult to that team.")
    plast = ctx["by_pickno"].get(len(ctx["by_pickno"]))
    if plast:
        md = plast.get("metadata") or {}
        lines.append(f"  - The last pick of the draft ({pick_notation(plast['pick_no'], n_teams)}) was {md.get('first_name','?')} {md.get('last_name','?')} ({md.get('position','?')}, {md.get('team','?')}).")
    lines.append("  - All 180 picks are in. No real games yet, so draft grades are the whole show this week.")

    return "\n".join(lines)


# ── DeepSeek calls (SPEC section 5) ─────────────────────────────────────────

def parse_json(text):
    text = text.strip()
    if text.startswith("```"):  # strip accidental markdown fences
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            return json.loads(text[start:end + 1])
        raise


def call_deepseek(model, system, user):
    """One DeepSeek chat completion → parsed JSON dict.

    Timeout 120s; retry once on 429/5xx/network errors with 10s backoff
    (SPEC section 5). Never prints the API key.
    """
    key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not key:
        raise RuntimeError("DEEPSEEK_API_KEY environment variable is not set")
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "max_tokens": MAX_TOKENS_BY_MODEL.get(model, 4000),
        "temperature": TEMP,
        "response_format": {"type": "json_object"},
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        API_URL, data=data, method="POST",
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + key},
    )
    last_error = None
    for attempt in (1, 2):
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_SEC) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            content = body["choices"][0]["message"]["content"]
            return parse_json(content)
        except urllib.error.HTTPError as e:
            last_error = f"HTTP {e.code}"
            retryable = e.code == 429 or 500 <= e.code < 600
            if retryable and attempt == 1:
                time.sleep(10)
                continue
            raise RuntimeError(f"DeepSeek API error ({model}): {last_error}")
        except (urllib.error.URLError, TimeoutError, ConnectionError,
                json.JSONDecodeError, KeyError, ValueError) as e:
            last_error = f"{type(e).__name__}: {e}"
            if attempt == 1:
                time.sleep(10)
                continue
            raise RuntimeError(f"DeepSeek API call failed ({model}): {last_error}")
    raise RuntimeError(f"DeepSeek API call failed ({model}): {last_error}")


def gen_section(section_key, model, system, build_user, validate, generic):
    """Call the LLM, validate, retry once with a nudge, then generic-fill (never crash)."""
    for nudge in (None, "nudge"):
        try:
            user = build_user(nudge)
            parsed = call_deepseek(model, system, user)
            if validate(parsed):
                return parsed
            print(f"  writer: {section_key} failed validation; {'retrying once' if nudge is None else 'filling generic entries'}")
        except Exception as e:
            print(f"  writer: {section_key} call failed ({e}); {'retrying once' if nudge is None else 'filling generic entries'}")
    return generic()


# ── Section builders ────────────────────────────────────────────────────────

def gen_overview(ctx, digest):
    def build_user(nudge):
        msg = digest + "\n\nWrite the overview section now. Respond with ONLY the JSON object."
        if nudge:
            msg += " Your previous answer was missing or empty. Make sure \"content\" is a non-empty string of 2-4 short sentences."
        return msg

    def validate(parsed):
        return isinstance(parsed, dict) and isinstance(parsed.get("content"), str) and parsed["content"].strip()

    def generic():
        return {"content": GENERIC_OVERVIEW}

    parsed = gen_section("overview", MODEL_FLASH, SYSTEM_OVERVIEW, build_user, validate, generic)
    return {"title": "Welcome to the League!", "content": parsed["content"].strip()}


def gen_draft_analyzer(ctx, digest):
    team_names = [name for _, name in ctx["teams"]]

    def build_user(nudge):
        msg = digest + (
            "\n\nNow write the Draft Analyzer section. There are exactly 12 teams. "
            "Include ALL 12 of them in team_grades, using these EXACT display names: "
            + ", ".join(team_names) + ". "
            "Remember: pick 1.01 was a KICKER (Brandon Aubrey, K DAL) — treat it as a silly playful fun fact, never as an insult. "
            "Respond with ONLY the JSON object."
        )
        if nudge:
            msg += " Your previous answer did not cover all 12 teams. You MUST include every one of these exact display names: " + ", ".join(team_names) + "."
        return msg

    def validate(parsed):
        if not isinstance(parsed, dict):
            return False
        grades = parsed.get("team_grades")
        if not isinstance(grades, list) or len(grades) != len(team_names):
            return False
        seen = set()
        for g in grades:
            if not isinstance(g, dict):
                return False
            key = _normalize(g.get("team"))
            if not key or key in seen:
                return False
            seen.add(key)
            if not str(g.get("positive") or "").strip() or not str(g.get("needs_work") or "").strip():
                return False
        return seen == {_normalize(t) for t in team_names}

    def generic():
        grades = []
        for _, name in ctx["teams"]:
            entry = {"team": name}
            entry.update(GENERIC_GRADE)
            grades.append(entry)
        return {"summary": "The draft is done and every team has a fun new squad! No real games yet, so the draft is the whole story this week. 🏈", "fun_facts": ["The very first pick of the draft (1.01) was a KICKER — Brandon Aubrey of the Cowboys! 🏈", "All 180 picks are in — every team is ready for the season!"], "team_grades": grades}

    parsed = gen_section("draft_analyzer", MODEL_PRO, SYSTEM_DRAFT, build_user, validate, generic)

    # Reconcile whatever the model returned against the 12 known teams (order = roster order).
    by_team = {}
    for g in parsed.get("team_grades") or []:
        if isinstance(g, dict) and _normalize(g.get("team")):
            by_team[_normalize(g["team"])] = g
    grades = []
    for _, name in ctx["teams"]:
        g = by_team.get(_normalize(name))
        if not isinstance(g, dict):
            g = dict(GENERIC_GRADE)
        grades.append({
            "team": name,
            "grade": str(g.get("grade") or GENERIC_GRADE["grade"]).strip() or GENERIC_GRADE["grade"],
            "best_pick": str(g.get("best_pick") or "").strip(),
            "sleeper_pick": str(g.get("sleeper_pick") or "").strip(),
            "positive": str(g.get("positive") or "").strip() or GENERIC_GRADE["positive"],
            "needs_work": str(g.get("needs_work") or "").strip() or GENERIC_GRADE["needs_work"],
        })
    fun_facts = [str(x).strip() for x in (parsed.get("fun_facts") or []) if str(x).strip()]
    if not fun_facts:
        fun_facts = ["The very first pick of the draft (1.01) was a KICKER — Brandon Aubrey of the Cowboys! 🏈"]
    return {
        "title": "Draft Analyzer",
        "summary": str(parsed.get("summary") or "").strip() or "The draft is done and every team has a fun new squad! 🏈",
        "fun_facts": fun_facts[:6],
        "team_grades": grades,
    }


def gen_matchup_previews(ctx, digest):
    pairs = ctx["pairs"]

    def build_user(nudge):
        pairing_lines = "\n".join(f"  {i}. {pr['team_a']} vs {pr['team_b']}" for i, pr in enumerate(pairs, 1))
        msg = digest + (
            "\n\nNow write the WEEK 2 matchup previews (next week's games — do NOT use week 1 matchups). "
            f"There are exactly {len(pairs)} matchups. Use these EXACT pairings and team names:\n" + pairing_lines +
            "\nRespond with ONLY the JSON object containing exactly " + str(len(pairs)) + " previews."
        )
        if nudge:
            msg += " Your previous answer was wrong. You MUST return exactly " + str(len(pairs)) + " previews using these EXACT pairings: " + "; ".join(f"{pr['team_a']} vs {pr['team_b']}" for pr in pairs) + "."
        return msg

    def validate(parsed):
        if not isinstance(parsed, dict):
            return False
        previews = parsed.get("previews")
        if not isinstance(previews, list) or len(previews) != len(pairs):
            return False
        for pv in previews:
            if not isinstance(pv, dict):
                return False
            a, b = _normalize(pv.get("team_a")), _normalize(pv.get("team_b"))
            if not a or not b or a == b:
                return False
            if not str(pv.get("preview") or "").strip():
                return False
        return True

    def generic():
        previews = []
        for pr in pairs:
            previews.append({
                "team_a": pr["team_a"], "team_b": pr["team_b"],
                "preview": f"{pr['team_a']} vs {pr['team_b']}! Two fun teams meet in week 2. Who will win? Let's find out! 🏆",
            })
        return {"previews": previews}

    parsed = gen_section("matchup_previews", MODEL_FLASH, SYSTEM_MATCHUPS, build_user, validate, generic)

    by_pair = {}
    for pv in parsed.get("previews") or []:
        if isinstance(pv, dict) and _normalize(pv.get("team_a")) and _normalize(pv.get("team_b")):
            by_pair[frozenset((_normalize(pv["team_a"]), _normalize(pv["team_b"])))] = pv
    previews = []
    for pr in pairs:
        pv = by_pair.get(frozenset((_normalize(pr["team_a"]), _normalize(pr["team_b"]))))
        if not isinstance(pv, dict):
            pv = {"team_a": pr["team_a"], "team_b": pr["team_b"], "preview": f"{pr['team_a']} vs {pr['team_b']}! Two fun teams meet in week 2. Who will win? Let's find out! 🏆"}
        previews.append({
            "team_a": pr["team_a"], "team_b": pr["team_b"],
            "preview": str(pv.get("preview") or "").strip() or f"{pr['team_a']} vs {pr['team_b']}! Two fun teams meet in week 2. Who will win? Let's find out! 🏆",
        })
    return {"title": "Next Week's Matchups!", "previews": previews}


def gen_team_updates(ctx, digest):
    team_names = [name for _, name in ctx["teams"]]

    def build_user(nudge):
        msg = digest + (
            "\n\nNow write the Team News & Updates section. There are exactly 12 teams. "
            "Include ALL 12 of them, using these EXACT display names: " + ", ".join(team_names) + ". "
            "Every team needs positive, needs_work, AND update. Respond with ONLY the JSON object."
        )
        if nudge:
            msg += " Your previous answer did not cover all 12 teams. You MUST include every one of these exact display names: " + ", ".join(team_names) + "."
        return msg

    def validate(parsed):
        if not isinstance(parsed, dict):
            return False
        teams = parsed.get("teams")
        if not isinstance(teams, list) or len(teams) != len(team_names):
            return False
        seen = set()
        for t in teams:
            if not isinstance(t, dict):
                return False
            key = _normalize(t.get("team"))
            if not key or key in seen:
                return False
            seen.add(key)
            if not str(t.get("positive") or "").strip() or not str(t.get("needs_work") or "").strip():
                return False
        return seen == {_normalize(t) for t in team_names}

    def generic():
        teams = []
        for _, name in ctx["teams"]:
            entry = {"team": name}
            entry.update(GENERIC_UPDATE)
            teams.append(entry)
        return {"teams": teams}

    parsed = gen_section("team_updates", MODEL_FLASH, SYSTEM_TEAMS, build_user, validate, generic)

    by_team = {}
    for t in parsed.get("teams") or []:
        if isinstance(t, dict) and _normalize(t.get("team")):
            by_team[_normalize(t["team"])] = t
    teams = []
    for _, name in ctx["teams"]:
        t = by_team.get(_normalize(name))
        if not isinstance(t, dict):
            t = dict(GENERIC_UPDATE)
        teams.append({
            "team": name,
            "positive": str(t.get("positive") or "").strip() or GENERIC_UPDATE["positive"],
            "needs_work": str(t.get("needs_work") or "").strip() or GENERIC_UPDATE["needs_work"],
            "update": str(t.get("update") or "").strip() or GENERIC_UPDATE["update"],
        })
    return {"title": "Team News & Updates", "teams": teams}


def build_meta(ctx):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "league": ctx["league_name"],
        "season": ctx["season"],
        "week": ctx["week"],
        "season_type": "pre",
        "generated_at": now,
        "special": "draft_analyzer",
        "report_title": f"Week {ctx['week']}: The Big Draft Recap!",
        "writer_model": MODEL_FLASH,
        "reviewer_model": MODEL_PRO,
    }


def main():
    print("writer: loading data and building context digest...")
    ctx = build_context()
    digest = build_digest(ctx)

    sections = {}
    print("writer: generating overview (flash)...")
    sections["overview"] = gen_overview(ctx, digest)
    print("writer: generating draft_analyzer (pro)...")
    sections["draft_analyzer"] = gen_draft_analyzer(ctx, digest)
    print("writer: generating matchup_previews (flash)...")
    sections["matchup_previews"] = gen_matchup_previews(ctx, digest)
    print("writer: generating team_updates (flash)...")
    sections["team_updates"] = gen_team_updates(ctx, digest)

    report = {"meta": build_meta(ctx), "sections": sections, "reviews": []}
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    n_grades = len(sections["draft_analyzer"]["team_grades"])
    n_teams = len(sections["team_updates"]["teams"])
    n_previews = len(sections["matchup_previews"]["previews"])
    print(f"report.json written: sections=4 teams={n_teams} previews={n_previews}")

    # sanity: fail loudly if the hard rules were somehow violated
    if n_grades != 12 or n_teams != 12 or n_previews != 6:
        raise SystemExit(f"FATAL: report shape wrong (grades={n_grades}, teams={n_teams}, previews={n_previews})")


if __name__ == "__main__":
    main()
