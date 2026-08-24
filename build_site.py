#!/usr/bin/env python3
"""build_site.py — renders the Hofftown Ballers kid-friendly static site.

Reads report.reviewed.json (Component C reviewer output) and renders:
  - site/index.html          — full current-week report
  - site/draft.html          — Draft Board: all 180 picks (data/draft_picks.json
                               joined with data/rosters.json + data/users.json)
  - site/archive/index.html  — list of past reports (+ site/archive/reports.json)

Self-contained: single HTML files, inline CSS only, no external fonts/CDNs
(must render offline). Prints: `site built: index.html + archive` and
`draft board: site/draft.html`.
"""

import html
import json
import os
import re
import shutil
import sys
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.join(BASE, "site")
ARCHIVE = os.path.join(SITE, "archive")
INDEX = os.path.join(SITE, "index.html")
DRAFT_HTML = os.path.join(SITE, "draft.html")
ARCHIVE_HTML = os.path.join(ARCHIVE, "index.html")
ARCHIVE_JSON = os.path.join(ARCHIVE, "reports.json")
DRAFT_PICKS_JSON = os.path.join(BASE, "data", "draft_picks.json")
ROSTERS_JSON = os.path.join(BASE, "data", "rosters.json")
USERS_JSON = os.path.join(BASE, "data", "users.json")
OWNERS_JSON = os.path.join(BASE, "owners.json")
STORIES_JSON = os.path.join(BASE, "stories.json")
HUMANIZED_REPORT = os.path.join(BASE, "report.humanized.json")

FONT = "'Comic Neue', 'Comic Sans MS', 'Chalkboard SE', cursive, sans-serif"

OWNERS = {}          # display_name -> {first_name, team_name}; loaded in main()
HUMANIZED_NOTE = ""  # footer note when report.humanized.json was used

CSS_TEMPLATE = """
@font-face{font-family:'Comic Neue';src:url('fonts/comic-neue-regular.woff2') format('woff2');font-weight:400;font-display:swap;}
@font-face{font-family:'Comic Neue';src:url('fonts/comic-neue-bold.woff2') format('woff2');font-weight:700;font-display:swap;}
:root{
  --orange:#FF6B35; --yellow:#FFD166; --green:#06D6A0; --red:#ef476f;
  --ink:#2b2d42; --card:#ffffff; --bg:#fff6ec;
}
*{box-sizing:border-box; margin:0; padding:0;}
html{scroll-behavior:smooth;}
body{
  font-family:__FONT__;
  background:var(--bg); color:var(--ink);
  line-height:1.55; font-size:1.02rem;
}
header{
  background:linear-gradient(90deg, #FF6B35, #FFD166 55%, #06D6A0);
  padding:34px 20px 38px; text-align:center;
  border-radius:0 0 36px 36px; box-shadow:0 4px 18px rgba(43,45,66,.18);
}
header .big-emoji{font-size:2.6rem; letter-spacing:.35em; margin-bottom:6px;}
header h1{font-size:2.6rem; color:var(--ink); text-shadow:0 2px 0 rgba(255,255,255,.55);}
header .sub{font-size:1.35rem; font-weight:bold; margin-top:4px; color:#5a2d0e;}
header .chip{
  display:inline-block; margin-top:12px; background:rgba(255,255,255,.75);
  border-radius:999px; padding:6px 18px; font-size:.98rem; font-weight:bold;
  box-shadow:0 2px 6px rgba(0,0,0,.12);
}
header .tabs{display:flex; justify-content:center; gap:12px; margin-top:18px; flex-wrap:wrap;}
header .tab{
  display:inline-block; background:rgba(255,255,255,.6); color:var(--ink);
  border-radius:999px; padding:8px 22px; font-weight:bold; font-size:1.05rem;
  text-decoration:none; box-shadow:0 2px 6px rgba(0,0,0,.12);
  border:3px solid transparent; transition:background .15s, border-color .15s;
}
header .tab:hover{background:#fff;}
header .tab.active{background:#fff; border-color:var(--ink); box-shadow:0 3px 0 rgba(0,0,0,.2);}
main{max-width:1080px; margin:0 auto; padding:20px 14px 10px;}
section{margin:18px 0 26px;}
section > h2{font-size:1.75rem; margin:6px 10px 12px; display:flex; align-items:center; gap:.45em;}
.card{
  background:var(--card); border-radius:24px; padding:20px 22px; margin:0 0 14px;
  box-shadow:0 6px 18px rgba(43,45,66,.12); border:3px solid #ffe3c4;
}
.grid{display:grid; grid-template-columns:repeat(auto-fill, minmax(270px, 1fr)); gap:16px;}
.grid .card{margin:0;}
.team-card{display:flex; flex-direction:column; gap:9px;}
.team-head{display:flex; align-items:center; gap:12px;}
.team-head h3{font-size:1.25rem; flex:1;}
.badge{
  display:inline-block; min-width:46px; text-align:center;
  font-size:1.7rem; font-weight:bold; border-radius:14px;
  padding:4px 10px; box-shadow:0 3px 0 rgba(0,0,0,.18); color:#fff;
}
.grade-a{background:var(--green);}
.grade-b{background:var(--yellow); color:var(--ink);}
.grade-c{background:var(--orange);}
.grade-d,.grade-f{background:var(--red);}
.tag{font-size:.98rem; color:#5b5b66;}
.pos{
  background:#e4faf2; color:#0a8f6a; border-radius:12px; padding:9px 12px;
  font-weight:bold; border-left:5px solid var(--green);
}
.neg{
  background:#fff0e4; color:#c2540a; border-radius:12px; padding:9px 12px;
  font-weight:bold; border-left:5px solid var(--orange);
}
.matchup{border:3px solid #ffd6c0; background:#fffdf9;}
.vs{font-size:1.35rem; font-weight:bold; text-align:center; padding:2px 0 8px;}
.vs .sword{font-size:1.5rem;}
.story-card{text-align:center; border-width:3px;}
.story-card .story-emoji{font-size:2.6rem; line-height:1;}
.story-card h3{font-size:1.3rem; margin:8px 0 6px;}
.story-card:nth-child(odd){border-color:var(--orange); background:#fff7f0;}
.story-card:nth-child(even){border-color:var(--green); background:#f1fdf8;}
.rank-card{display:flex; flex-direction:column; gap:8px;}
.rank-num{font-size:1.9rem; font-weight:bold; color:var(--orange); letter-spacing:.02em;}
.rank-card h3{font-size:1.2rem;}
ul.fun{list-style:none; padding-left:4px;}
ul.fun li{padding:4px 0 4px 26px; position:relative;}
ul.fun li::before{content:"🎉"; position:absolute; left:0;}
.reviews{margin-top:22px; background:#eafff7; border-color:#b8ecd9; font-weight:bold; text-align:center;}
.reviews a{color:var(--ink);}
.backlink{display:inline-block; margin-bottom:16px; font-weight:bold; color:#c2540a;
  text-decoration:none; background:#fff; padding:9px 16px; border-radius:999px;
  box-shadow:0 3px 8px rgba(43,45,66,.15);}
.draft-wrap{overflow-x:auto;}
.draft-table{width:100%; border-collapse:collapse; font-size:.98rem;}
.draft-table thead th{
  position:sticky; top:0; z-index:1; background:var(--orange); color:#fff;
  padding:10px 8px; text-align:left; font-size:1rem; white-space:nowrap;
}
.draft-table tbody td{padding:8px; border-bottom:1px solid #ffe3c4; white-space:nowrap;}
.draft-table tbody tr:nth-child(even){background:#fff6ec;}
.draft-table tbody tr:hover{background:#fff0e4;}
a{color:#0a8f6a;}
footer{text-align:center; padding:26px 16px 44px; color:#6b6b76; font-size:.98rem;}
footer .heart{color:var(--orange);}
@media (max-width: 640px){
  body{font-size:1.05rem;}
  header{padding:22px 14px 26px;}
  header .big-emoji{font-size:2rem; letter-spacing:.22em;}
  header h1{font-size:1.8rem;}
  header .sub{font-size:1.15rem;}
  header .chip{font-size:.85rem; padding:5px 12px;}
  header .tabs{gap:8px;}
  header .tab{padding:7px 14px; font-size:.95rem;}
  main{padding:14px 10px 8px;}
  section > h2{font-size:1.4rem;}
  .grid{grid-template-columns:1fr;}
  .card{padding:14px 14px;}
  .badge{min-width:38px; font-size:1.4rem;}
  .vs{font-size:1.15rem;}
  .draft-wrap{overflow-x:auto;}
  .draft-table{font-size:.85rem;}
  .draft-table thead th{font-size:.88rem; padding:8px 6px;}
  .draft-table tbody td{padding:6px;}
}
"""

CSS = CSS_TEMPLATE.replace("__FONT__", FONT)
# Archive pages live at site/archive/, so their font URLs need ../fonts/.
CSS_ARCHIVE = CSS.replace("url('fonts/", "url('../fonts/")

PAGE_HEAD = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>{css}</style>
</head>
<body>
"""

PAGE_TAIL = """
<footer>
  <p>Made with <span class="heart">❤️</span> for Hofftown Ballers · Updated {date}</p>
  {humanized_note}
  <p style="margin-top:6px;">🏈 <a href="archive/index.html">Past Reports</a></p>
</footer>
</body>
</html>
"""


def esc(s):
    return html.escape(str(s) if s is not None else "", quote=False)


def inline(s):
    """Escape text, then render **bold** spans. No other markup is trusted."""
    s = esc(s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    return s


def fmt_date(iso):
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        return dt.strftime("%B %d, %Y")
    except Exception:
        return str(iso) if iso else ""


def grade_class(grade):
    g = str(grade or "?").strip().upper()
    if g.startswith("A"):
        return "grade-a"
    if g.startswith("B"):
        return "grade-b"
    if g.startswith("C"):
        return "grade-c"
    if g.startswith("D"):
        return "grade-d"
    return "grade-f"


# --------------------------------------------------------------------------
# Owners (real names) + League Stories
# --------------------------------------------------------------------------

def copy_fonts():
    """Copy bundled Comic Neue woff2 files into site/fonts/ so the deployed
    Pages site serves them. Never crashes — warns and falls back if missing."""
    dest_dir = os.path.join(SITE, "fonts")
    copied = 0
    missing = []
    try:
        os.makedirs(dest_dir, exist_ok=True)
        for fn in ("comic-neue-regular.woff2", "comic-neue-bold.woff2"):
            src = os.path.join(BASE, "fonts", fn)
            if os.path.exists(src):
                shutil.copy2(src, os.path.join(dest_dir, fn))
                copied += 1
            else:
                missing.append(fn)
    except Exception as e:
        print(f"  [warn] font copy failed: {e}", file=sys.stderr)
        return
    if missing:
        print(f"  [warn] fonts: missing {', '.join(missing)} — site falls back to Comic Sans", file=sys.stderr)
    else:
        print(f"fonts: copied {copied}")


def load_owners():
    """Return {display_name: {first_name, team_name}} — {} if missing/broken.

    Never crashes: a missing or malformed owners.json just means the site
    renders display names without the extras.
    """
    try:
        with open(OWNERS_JSON, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def owner_parts(display_name):
    """(first_name, team_name) for a display name; ('', '') when unknown."""
    rec = OWNERS.get(display_name)
    if isinstance(rec, dict):
        return (str(rec.get("first_name") or "").strip(),
                str(rec.get("team_name") or "").strip())
    return "", ""


def display_label(display_name):
    """'Stinger005' -> 'Stinger005 (Dustin)' when a first_name exists."""
    first, _ = owner_parts(display_name)
    return f"{display_name} ({first})" if first else display_name


def load_stories():
    """Return the stories dict from stories.json, or None if missing/broken."""
    try:
        with open(STORIES_JSON, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get("stories"), list) and data["stories"]:
            return data
    except Exception:
        pass
    return None


def render_stories(data):
    title = data.get("title") or "League Stories!"
    cards = []
    for s in data.get("stories") or []:
        emoji = esc(s.get("emoji") or "📖")
        stitle = esc(s.get("title") or "")
        text = inline(s.get("text") or "")
        cards.append(
            '<div class="card story-card">'
            f'<div class="story-emoji">{emoji}</div>'
            f"<h3>{stitle}</h3>"
            f"<p>{text}</p></div>"
        )
    grid = f'<div class="grid">{"".join(cards)}</div>' if cards else ""
    return f'<section><h2>📖 {esc(title)}</h2>{grid}</section>'


MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}


def render_power_rankings(sec):
    title = sec.get("title", "Power Rankings!")
    intro = inline(sec.get("intro") or "")
    rankings = sec.get("rankings") or []
    cards = []
    for r in rankings:
        try:
            rank = int(r.get("rank"))
        except (TypeError, ValueError):
            rank = 0
        medal = MEDALS.get(rank, "")
        team = r.get("team", "?")
        first, tname = owner_parts(team)
        label = f"{team} ({first})" if first else team
        reason = inline(r.get("reason") or "")
        card = [f'<div class="card rank-card">']
        card.append(f'<div class="rank-num">{medal} #{rank}</div>')
        card.append(f"<h3>{esc(label)}</h3>")
        if tname:
            card.append(f'<p class="tag">🎪 {esc(tname)}</p>')
        card.append(f"<p>{reason}</p>")
        card.append("</div>")
        cards.append("".join(card))
    cards_html = "\n".join(cards)
    grid = f'<div class="grid">\n{cards_html}\n</div>' if cards else ""
    intro_html = f'<div class="card"><p>{intro}</p></div>' if intro else ""
    return (
        f'<section><h2>🏆 {esc(title)}</h2>'
        f"{intro_html}{grid}</section>"
    )


# --------------------------------------------------------------------------
# Page sections
# --------------------------------------------------------------------------

def render_header(meta, date, emoji="🏈⭐🌟", active_tab="report"):
    title = esc(meta.get("report_title") or "Hofftown Ballers Weekly Report")
    week = meta.get("week")
    season = meta.get("season")
    week_label = meta.get("week_label")
    if week_label:
        chip = str(week_label)
        if date:
            chip += f" · {esc(date)}"
        chip_html = f'<div class="chip">{chip}</div>'
    elif week is not None and week != "":
        chip = f"Season {season} · Week {week}"
        if date:
            chip += f" · {esc(date)}"
        chip_html = f'<div class="chip">{chip}</div>'
    elif date:
        chip_html = f'<div class="chip">{esc(date)}</div>'
    else:
        chip_html = ""
    report_active = " active" if active_tab == "report" else ""
    draft_active = " active" if active_tab == "draft" else ""
    tabs = (
        '<nav class="tabs">'
        f'<a class="tab{report_active}" href="index.html">📋 Report</a>'
        f'<a class="tab{draft_active}" href="draft.html">🏈 Draft Board</a>'
        "</nav>"
    )
    return (
        f'<header><div class="big-emoji">{emoji}</div>'
        f"<h1>Hofftown Ballers</h1>"
        f'<p class="sub">{title}</p>'
        f"{chip_html}{tabs}</header>"
    )


def render_overview(sec):
    title = sec.get("title", "Welcome!")
    content = inline(sec.get("content", ""))
    return f'<section><h2>👋 {esc(title)}</h2><div class="card">{content}</div></section>'


def render_draft_analyzer(sec):
    title = sec.get("title", "Draft Analyzer")
    summary = inline(sec.get("summary", ""))
    facts = sec.get("fun_facts") or []
    facts_html = "".join(f"<li>{inline(f)}</li>" for f in facts) or "<li>No fun facts this week!</li>"
    grades = sec.get("team_grades") or []
    cards = []
    for g in grades:
        team = g.get("team", "?")
        first, tname = owner_parts(team)
        label = f"{team} ({first})" if first else team
        grade = esc(g.get("grade", "?"))
        badge = f'<span class="badge {grade_class(g.get("grade"))}">{grade}</span>'
        best = inline(g.get("best_pick") or "—")
        sleep = inline(g.get("sleeper_pick") or "—")
        worst = inline(g.get("worst_pick") or "—")
        pos = inline(g.get("positive") or "")
        neg = inline(g.get("needs_work") or "")
        head_html = f'<div class="team-head">{badge}<h3>{esc(label)}</h3></div>'
        if tname:
            head_html += f'<p class="tag">🎪 {esc(tname)}</p>'
        cards.append(
            '<div class="card team-card">\n'
            f"{head_html}\n"
            f'<p class="tag">🎯 Best pick: {best}</p>\n'
            f'<p class="tag">😴 Sleeper pick: {sleep}</p>\n'
            f'<p class="tag">🤔 Head-scratcher pick: {worst}</p>\n'
            f'<div class="pos">⬆ {pos}</div>\n'
            f'<div class="neg">⬇ {neg}</div>\n'
            f"</div>"
        )
    cards_html = "\n".join(cards)
    grid = f'<div class="grid">\n{cards_html}\n</div>' if cards else ""
    return (
        f'<section><h2>📝 {esc(title)}</h2>'
        f'<div class="card"><p>{summary}</p>'
        f'<h3 style="margin-top:14px;">🎉 Fun Facts</h3>'
        f'<ul class="fun">{facts_html}</ul></div>'
        f"{grid}</section>"
    )


def render_matchups(sec):
    title = sec.get("title", "Next Week's Matchups!")
    previews = sec.get("previews") or []
    cards = []
    for p in previews:
        a = esc(p.get("team_a", "?"))
        b = esc(p.get("team_b", "?"))
        text = inline(p.get("preview", ""))
        cards.append(
            f'<div class="card matchup">'
            f'<div class="vs">{a} <span class="sword">⚔️</span> {b}</div>'
            f"<p>{text}</p></div>"
        )
    grid = f'<div class="grid">{"".join(cards)}</div>' if cards else ""
    return f'<section><h2>⚔️ {esc(title)}</h2>{grid}</section>'


def render_team_updates(sec):
    title = sec.get("title", "Team News & Updates")
    teams = sec.get("teams") or []
    cards = []
    for t in teams:
        team = t.get("team", "?")
        first, tname = owner_parts(team)
        label = f"{team} ({first})" if first else team
        update = inline(t.get("update") or "")
        pos = inline(t.get("positive") or "")
        neg = inline(t.get("needs_work") or "")
        name_html = f"<h3>{esc(label)}</h3>"
        if tname:
            name_html += f'<p class="tag">🎪 {esc(tname)}</p>'
        cards.append(
            f'<div class="card team-card">{name_html}'
            f'<p class="tag">📰 {update}</p>'
            f'<div class="pos">⬆ {pos}</div>'
            f'<div class="neg">⬇ {neg}</div></div>'
        )
    grid = f'<div class="grid">{"".join(cards)}</div>' if cards else ""
    return f'<section><h2>📰 {esc(title)}</h2>{grid}</section>'


def render_reviews(reviews):
    if not reviews:
        return ""
    ok = sum(1 for r in reviews if str(r.get("verdict", "")).startswith("PASS"))
    total = len(reviews)
    return (
        f'<div class="card reviews">✅ Safety Checked: {ok}/{total} sections passed '
        f"review — ready for the kids! 🏈</div>"
    )


def render_index(report, meta, sections, date):
    parts = [
        PAGE_HEAD.format(title=esc(meta.get("report_title") or "Hofftown Ballers"), css=CSS),
        render_header(meta, date),
        "<main>",
    ]
    order = ["overview", "draft_analyzer", "stories", "power_rankings", "matchup_previews", "team_updates"]
    renderers = {
        "overview": render_overview,
        "draft_analyzer": render_draft_analyzer,
        "power_rankings": render_power_rankings,
        "matchup_previews": render_matchups,
        "team_updates": render_team_updates,
    }
    for name in order:
        if name == "stories":
            stories = load_stories()
            if stories is not None:
                parts.append(render_stories(stories))
            continue
        sec = sections.get(name)
        if isinstance(sec, dict):
            parts.append(renderers[name](sec))
    parts.append(render_reviews(report.get("reviews")))
    parts.append("</main>")
    parts.append(PAGE_TAIL.format(date=esc(date), humanized_note=HUMANIZED_NOTE))
    return "".join(parts)


# --------------------------------------------------------------------------
# Draft Board (site/draft.html — all 180 picks)
# --------------------------------------------------------------------------

def load_draft_rows():
    """Join data/draft_picks.json × data/rosters.json × data/users.json into
    pick rows sorted by pick_no. Returns [] (with a warning) if any data file
    is missing or broken — the build never crashes on bad data."""
    try:
        with open(DRAFT_PICKS_JSON, "r", encoding="utf-8") as f:
            picks = json.load(f)
        with open(ROSTERS_JSON, "r", encoding="utf-8") as f:
            rosters = json.load(f)
        with open(USERS_JSON, "r", encoding="utf-8") as f:
            users = json.load(f)
    except Exception as e:
        print(f"  [warn] draft board data unavailable ({e}) — draft.html will show a placeholder", file=sys.stderr)
        return []
    owner_by_roster = {int(r.get("roster_id")): r.get("owner_id") for r in rosters if r.get("roster_id") is not None}
    name_by_user = {u.get("user_id"): u.get("display_name") for u in users}
    rows = []
    for p in picks:
        try:
            pick_no = int(p.get("pick_no"))
        except (TypeError, ValueError):
            continue
        rid = p.get("roster_id")
        owner = owner_by_roster.get(int(rid)) if rid is not None else None
        team = name_by_user.get(owner) or (f"Team {rid}" if rid is not None else "—")
        md = p.get("metadata") or {}
        first = str(md.get("first_name") or "").strip()
        last = str(md.get("last_name") or "").strip()
        rows.append({
            "pick_no": pick_no,
            "round": p.get("round"),
            "team": team,
            "first": "",  # resolved from owners.json below
            "player": (f"{first} {last}".strip() or "Unknown"),
            "pos": str(md.get("position") or "").strip() or "—",
            "nfl": str(md.get("team") or "").strip() or "—",
        })
    # Resolve real first names from owners.json (best-effort).
    for r in rows:
        r["first"] = owner_parts(r["team"])[0]
    rows.sort(key=lambda r: r["pick_no"])
    return rows


def render_draft_board(rows):
    if not rows:
        return (
            '<section><h2>🏈 Draft Board</h2>'
            '<div class="card">The draft board is not ready yet — check back soon! ⏳</div></section>'
        )
    body = []
    for r in rows:
        team_label = f"{r['team']} ({r['first']})" if r.get("first") else r["team"]
        body.append(
            f"<tr><td>{r['pick_no']}</td><td>{esc(r['round'])}</td>"
            f"<td>{esc(team_label)}</td><td>{esc(r['player'])}</td>"
            f"<td>{esc(r['pos'])}</td><td>{esc(r['nfl'])}</td></tr>"
        )
    return (
        '<section><h2>🏈 Hofftown Ballers Draft Board</h2>'
        '<p class="tag" style="margin:0 10px 12px;">All 180 picks — the whole draft at a glance, from 1.01 to the very last pick!</p>'
        '<div class="card draft-wrap" style="padding:8px 10px;">'
        '<table class="draft-table">'
        '<thead><tr><th>Pick #</th><th>Round</th><th>Team</th><th>Player</th><th>Pos</th><th>NFL Team</th></tr></thead>'
        f"<tbody>{''.join(body)}</tbody></table></div></section>"
    )


def render_draft_page(report, meta, date):
    rows = load_draft_rows()
    parts = [
        PAGE_HEAD.format(title="Draft Board — Hofftown Ballers", css=CSS),
        render_header(meta, date, active_tab="draft"),
        "<main>",
        render_draft_board(rows),
        "</main>",
        PAGE_TAIL.format(date=esc(date), humanized_note=HUMANIZED_NOTE),
    ]
    return "".join(parts)


# --------------------------------------------------------------------------
# Archive
# --------------------------------------------------------------------------

def load_archive():
    if os.path.exists(ARCHIVE_JSON):
        try:
            with open(ARCHIVE_JSON, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                return data
        except Exception:
            pass
    return []


def upsert_archive(reports, meta):
    entry = {
        "season": meta.get("season"),
        "week": meta.get("week"),
        "special": meta.get("special"),
        "generated_at": meta.get("generated_at"),
        "title": meta.get("report_title", ""),
    }
    special = str(meta.get("special") or "")
    if special == "draft_analyzer":
        entry["label"] = f"Week {entry.get('week')} — Draft Analyzer Special"
    else:
        entry["label"] = f"Week {entry.get('week')}"
    # Upsert: replace any previous entry for the same season+week.
    reports = [r for r in reports if not (
        r.get("season") == entry.get("season") and r.get("week") == entry.get("week")
    )]
    reports.append(entry)
    reports.sort(key=lambda r: (r.get("season") or 0, r.get("week") or 0), reverse=True)
    return reports


def render_archive(reports, date):
    parts = [PAGE_HEAD.format(title="Past Reports — Hofftown Ballers", css=CSS_ARCHIVE)]
    parts.append(render_header({"report_title": "Past Reports 🗂️", "season": "", "week": "", "generated_at": ""}, "", emoji="🗂️🏈"))
    parts.append("<main>")
    parts.append('<a class="backlink" href="../index.html">← Back to this week\'s report</a>')
    if not reports:
        parts.append('<div class="card">No reports yet!</div>')
    else:
        cards = []
        for i, r in enumerate(reports):
            label = esc(r.get("label") or f"Week {r.get('week')}")
            d = fmt_date(r.get("generated_at"))
            # Newest report lives at index.html; older ones will get their own
            # file (structure ready for future weeks to append).
            href = "../index.html" if i == 0 else f"week-{r.get('season')}-{r.get('week')}.html"
            cards.append(
                f'<div class="card team-card"><h3>{label}</h3>'
                f'<p class="tag">{esc(d)}</p>'
                f'<a href="{href}">Read it →</a></div>'
            )
        parts.append(f'<div class="grid">{"".join(cards)}</div>')
    parts.append("</main>")
    parts.append(PAGE_TAIL.format(date=esc(date), humanized_note=HUMANIZED_NOTE))
    return "".join(parts)


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def main():
    global OWNERS, HUMANIZED_NOTE
    OWNERS = load_owners()
    # Prefer the humanized report; fall back to the reviewed one (robustness).
    src = HUMANIZED_REPORT
    humanized = False
    if os.path.exists(src):
        humanized = True
        print("build_site: using report.humanized.json (humanized)")
    else:
        src = os.path.join(BASE, "report.reviewed.json")
        if not os.path.exists(src):
            print(f"ERROR: {src} not found — run reviewer.py first.", file=sys.stderr)
            return 1
    try:
        with open(src, "r", encoding="utf-8") as f:
            report = json.load(f)
    except Exception as e:
        print(f"ERROR: cannot read {src}: {e}", file=sys.stderr)
        return 1
    HUMANIZED_NOTE = '<p style="margin-top:6px;">✨ Humanized for a friendly read</p>' if humanized else ""

    meta = report.get("meta", {})
    sections = report.get("sections", {})
    date = fmt_date(meta.get("generated_at"))

    os.makedirs(ARCHIVE, exist_ok=True)

    with open(INDEX, "w", encoding="utf-8") as f:
        f.write(render_index(report, meta, sections, date))

    try:
        with open(DRAFT_HTML, "w", encoding="utf-8") as f:
            f.write(render_draft_page(report, meta, date))
    except Exception as e:
        print(f"  [warn] could not write {DRAFT_HTML}: {e}", file=sys.stderr)

    reports = upsert_archive(load_archive(), meta)
    with open(ARCHIVE_JSON, "w", encoding="utf-8") as f:
        json.dump(reports, f, indent=2, ensure_ascii=False)

    with open(ARCHIVE_HTML, "w", encoding="utf-8") as f:
        f.write(render_archive(reports, date))

    copy_fonts()
    print("site built: index.html + archive")
    print("draft board: site/draft.html")
    return 0


if __name__ == "__main__":
    sys.exit(main())
