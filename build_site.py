#!/usr/bin/env python3
"""build_site.py — renders the Hofftown Ballers kid-friendly static site.

Reads report.reviewed.json (Component C reviewer output) and renders:
  - site/index.html          — full current-week report
  - site/archive/index.html  — list of past reports (+ site/archive/reports.json)

Self-contained: single HTML files, inline CSS only, no external fonts/CDNs
(must render offline). Prints: `site built: index.html + archive`.
"""

import html
import json
import os
import re
import sys
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.join(BASE, "site")
ARCHIVE = os.path.join(SITE, "archive")
INDEX = os.path.join(SITE, "index.html")
ARCHIVE_HTML = os.path.join(ARCHIVE, "index.html")
ARCHIVE_JSON = os.path.join(ARCHIVE, "reports.json")

FONT = "'Comic Sans MS', 'Chalkboard SE', 'Comic Neue', cursive, sans-serif"

CSS_TEMPLATE = """
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
ul.fun{list-style:none; padding-left:4px;}
ul.fun li{padding:4px 0 4px 26px; position:relative;}
ul.fun li::before{content:"🎉"; position:absolute; left:0;}
.reviews{margin-top:22px; background:#eafff7; border-color:#b8ecd9; font-weight:bold; text-align:center;}
.reviews a{color:var(--ink);}
.backlink{display:inline-block; margin-bottom:16px; font-weight:bold; color:#c2540a;
  text-decoration:none; background:#fff; padding:9px 16px; border-radius:999px;
  box-shadow:0 3px 8px rgba(43,45,66,.15);}
a{color:#0a8f6a;}
footer{text-align:center; padding:26px 16px 44px; color:#6b6b76; font-size:.98rem;}
footer .heart{color:var(--orange);}
"""

CSS = CSS_TEMPLATE.replace("__FONT__", FONT)

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
# Page sections
# --------------------------------------------------------------------------

def render_header(meta, date, emoji="🏈⭐🌟"):
    title = esc(meta.get("report_title") or "Hofftown Ballers Weekly Report")
    week = meta.get("week")
    season = meta.get("season")
    if week is not None and week != "":
        chip = f"Season {season} · Week {week}"
        if date:
            chip += f" · {esc(date)}"
        chip_html = f'<div class="chip">{chip}</div>'
    elif date:
        chip_html = f'<div class="chip">{esc(date)}</div>'
    else:
        chip_html = ""
    return (
        f'<header><div class="big-emoji">{emoji}</div>'
        f"<h1>Hofftown Ballers</h1>"
        f'<p class="sub">{title}</p>'
        f"{chip_html}</header>"
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
        team = esc(g.get("team", "?"))
        grade = esc(g.get("grade", "?"))
        badge = f'<span class="badge {grade_class(g.get("grade"))}">{grade}</span>'
        best = inline(g.get("best_pick") or "—")
        sleep = inline(g.get("sleeper_pick") or "—")
        pos = inline(g.get("positive") or "")
        neg = inline(g.get("needs_work") or "")
        cards.append(
            f'<div class="card team-card">'
            f'<div class="team-head">{badge}<h3>{team}</h3></div>'
            f'<p class="tag">🎯 Best pick: {best}</p>'
            f'<p class="tag">😴 Sleeper pick: {sleep}</p>'
            f'<div class="pos">⬆ {pos}</div>'
            f'<div class="neg">⬇ {neg}</div>'
            f"</div>"
        )
    grid = f'<div class="grid">{"".join(cards)}</div>' if cards else ""
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
        team = esc(t.get("team", "?"))
        update = inline(t.get("update") or "")
        pos = inline(t.get("positive") or "")
        neg = inline(t.get("needs_work") or "")
        cards.append(
            f'<div class="card team-card"><h3>{team}</h3>'
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
    order = ["overview", "draft_analyzer", "matchup_previews", "team_updates"]
    renderers = {
        "overview": render_overview,
        "draft_analyzer": render_draft_analyzer,
        "matchup_previews": render_matchups,
        "team_updates": render_team_updates,
    }
    for name in order:
        sec = sections.get(name)
        if isinstance(sec, dict):
            parts.append(renderers[name](sec))
    parts.append(render_reviews(report.get("reviews")))
    parts.append("</main>")
    parts.append(PAGE_TAIL.format(date=esc(date)))
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
    parts = [PAGE_HEAD.format(title="Past Reports — Hofftown Ballers", css=CSS)]
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
    parts.append(PAGE_TAIL.format(date=esc(date)))
    return "".join(parts)


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def main():
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

    meta = report.get("meta", {})
    sections = report.get("sections", {})
    date = fmt_date(meta.get("generated_at"))

    os.makedirs(ARCHIVE, exist_ok=True)

    with open(INDEX, "w", encoding="utf-8") as f:
        f.write(render_index(report, meta, sections, date))

    reports = upsert_archive(load_archive(), meta)
    with open(ARCHIVE_JSON, "w", encoding="utf-8") as f:
        json.dump(reports, f, indent=2, ensure_ascii=False)

    with open(ARCHIVE_HTML, "w", encoding="utf-8") as f:
        f.write(render_archive(reports, date))

    print("site built: index.html + archive")
    return 0


if __name__ == "__main__":
    sys.exit(main())
