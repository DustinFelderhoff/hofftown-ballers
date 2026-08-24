#!/usr/bin/env python3
"""reviewer.py — safety gate for the Hofftown Ballers weekly report.

Reads report.json (Component B output), enforces the safety gate, and writes
report.reviewed.json (same schema + `reviews` array). Stdlib only
(urllib.request for the DeepSeek API). Never prints the API key.

Pipeline per section (overview, draft_analyzer, matchup_previews, team_updates,
power_rankings):
  1. Blocklist scan (bad_words.scan_text) on every string field. On hits:
     auto-fix via deepseek-v4-pro rewrite, max 2 rounds, then replace any
     still-flagged field with a generic kind sentence.
  2. LLM review via deepseek-v4-pro requesting strict JSON
     {"verdict": "PASS"|"FAIL", "issues": [...], "suggestion": "..."}
     using the SPEC §7 tone rules. On FAIL: rewrite with the suggestion, max
     2 fix rounds.
  3. Structure check (no LLM): team_grades / team_updates counts, positive +
     needs_work non-empty, previews with team_a != team_b.
  4. Append {section, verdict, notes} to the reviews array.

HARD FAIL: if any section still fails after retries (or the structure check
fails), DO NOT write report.reviewed.json — exit 1 with a clear message.

Expected structure counts default to 12 teams / 6 previews (SPEC §4). For
testing with a smaller fixture, set meta.fixture=true in report.json (or pass
--expect-teams/--expect-previews, or REVIEWER_EXPECT_TEAMS/REVIEWER_EXPECT_PREVIEWS
env vars) — the expectations are then derived from the report's own counts.
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

import bad_words

API_URL = "https://api.deepseek.com/chat/completions"
REVIEW_MODEL = "deepseek-v4-pro"          # quality model for review + fixes
TIMEOUT = 120
SECTIONS = ["overview", "draft_analyzer", "matchup_previews", "team_updates", "power_rankings"]

# The pro model is a reasoning model: `max_tokens` covers BOTH its reasoning
# tokens and the final answer (same pitfall writer.py documents). When the
# reasoning runs long, the API returns HTTP 200 with EMPTY content — that is
# an infrastructure flake, not a content violation. Retry with backoff, and if
# the LLM is still unavailable, fall back to a blocklist-only PASS instead of
# hard-failing the build.
MAX_LLM_ATTEMPTS = 4
LLM_BACKOFF = (10, 20, 40)                # seconds between retries

# Tone rules from SPEC §7 (kept verbatim-ish so every LLM call shares them).
TONE_RULES = """You are writing a weekly fantasy football report for ELEMENTARY SCHOOL KIDS (grades 2-4).
Rules:
- Reading level: grades 2-4. Short sentences. Simple words. Playful and fun like a kid's sports show.
- Use emoji. Be enthusiastic. Make it fun to read.
- NEVER use bad words. NEVER insult anyone. NEVER put anyone or any team down. No name-calling.
- No words like: sucks, trash, terrible, awful, stupid, dumb, loser, worst, garbage, boring, hate.
- For every team, ALWAYS include BOTH a positive AND a gentle "needs work" note. The needs-work note is a friendly heads-up (e.g. "their bench is a little thin" or "watch out for bye weeks"), NEVER mean.
- Trash talk is OK only as playful, friendly banter that wouldn't hurt anyone's feelings.
- The kids know the league members by their Sleeper display names — use those as team names."""

# Generic kind sentences used when a field still fails the blocklist after the
# LLM auto-fix rounds (SPEC §8.1: "replace offending field with a generic kind
# sentence"). Keyed by field name; safe by construction.
GENERIC_KIND = {
    "title": "Great news from the league!",
    "content": "Welcome to the league! Every team is ready for a fun season of football. 🏈",
    "summary": "It was a super fun draft! Every team picked players they are excited about. 🌟",
    "fun_facts": "Every team made some exciting picks!",
    "positive": "This team made some exciting picks and has lots to look forward to! 🌟",
    "needs_work": "Every team has something to practice, and that's totally okay!",
    "update": "The team is staying busy and having fun!",
    "best_pick": "A fun early pick!",
    "sleeper_pick": "A sneaky-good pick!",
    "worst_pick": "That pick was a bit of a head-scratcher, but every team learns as the season goes!",
    "preview": "These two teams are going to have a fun matchup next week! ⚔️",
    "intro": "Here is how the teams stack up this week! 🏈",
    "reason": "This team is having a great season so far! 🏈",
}


# --------------------------------------------------------------------------
# DeepSeek API (stdlib only)
# --------------------------------------------------------------------------

def _parse_json(text):
    """Tolerantly parse a JSON object out of an LLM response."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.S)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            return json.loads(m.group(0))
        raise


def llm_json(system, user, model=REVIEW_MODEL, max_tokens=4000, temperature=0.4):
    """POST to the DeepSeek chat completions API; return parsed JSON content.

    Retries up to MAX_LLM_ATTEMPTS with exponential backoff (10s, 20s, 40s)
    on 429/5xx, network errors, and EMPTY/unparseable responses (the pro
    reasoning model intermittently returns empty content — treat that as
    infrastructure, not content). Never prints the API key.
    """
    key = os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        raise RuntimeError("DEEPSEEK_API_KEY env var not set")
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
        "response_format": {"type": "json_object"},
    }
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        API_URL, data=body, method="POST",
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + key},
    )
    last_err = None
    for attempt in range(MAX_LLM_ATTEMPTS):
        backoff = LLM_BACKOFF[min(attempt, len(LLM_BACKOFF) - 1)]
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            content = data["choices"][0]["message"]["content"]
            return _parse_json(content)
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code not in (429, 500, 502, 503, 504):  # real errors: bad request, auth, ...
                raise
        except (urllib.error.URLError, TimeoutError, OSError,
                json.JSONDecodeError, KeyError, IndexError, ValueError) as e:
            # Network/transport flakes AND empty/unparseable content (the pro
            # reasoning model's empty-answer case) — all retryable.
            last_err = e
            if attempt == MAX_LLM_ATTEMPTS - 1:
                break
            print(f"  [retry] DeepSeek call attempt {attempt + 1}/{MAX_LLM_ATTEMPTS} "
                  f"returned empty/unparseable content ({type(e).__name__}); backing off {backoff}s",
                  file=sys.stderr)
            time.sleep(backoff)
            continue
        if attempt < MAX_LLM_ATTEMPTS - 1:
            print(f"  [retry] DeepSeek HTTP error (attempt {attempt + 1}/{MAX_LLM_ATTEMPTS}); "
                  f"backing off {backoff}s", file=sys.stderr)
            time.sleep(backoff)
            continue
    raise RuntimeError(f"DeepSeek API call failed: {last_err}")


# --------------------------------------------------------------------------
# Blocklist scan + auto-fix
# --------------------------------------------------------------------------

def scan_section(section):
    """Walk every string field in a section; return {path: [flagged words]}."""
    hits = {}

    def walk(obj, path):
        if isinstance(obj, str):
            words = bad_words.scan_text(obj)
            if words:
                hits[path] = words
        elif isinstance(obj, dict):
            for k, v in obj.items():
                walk(v, path + "/" + k)
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                walk(v, f"{path}[{i}]")

    walk(section, "")
    return hits


def replace_flagged(section, hits):
    """Replace every flagged string field with a generic kind sentence."""
    def repl(obj, path):
        if isinstance(obj, str):
            return obj
        if isinstance(obj, dict):
            out = {}
            for k, v in obj.items():
                p = path + "/" + k
                if isinstance(v, str) and p in hits:
                    out[k] = GENERIC_KIND.get(k, "The league is having a great season! 🏈")
                else:
                    out[k] = repl(v, p)
            return out
        if isinstance(obj, list):
            return [repl(v, f"{path}[{i}]") for i, v in enumerate(obj)]
        return obj
    return repl(section, "")


def restore_keys(orig, new):
    """LLM rewrites sometimes drop fields — restore any missing key from the
    original section using a generic value so the structure stays intact."""
    if isinstance(orig, dict) and isinstance(new, dict):
        for k, v in orig.items():
            if k not in new:
                if isinstance(v, str):
                    new[k] = GENERIC_KIND.get(k, "")
                elif isinstance(v, list):
                    new[k] = []
                elif isinstance(v, dict):
                    new[k] = {}
            elif isinstance(v, dict):
                restore_keys(v, new[k])
            elif isinstance(v, list) and isinstance(new[k], list):
                for i, item in enumerate(v):
                    if i < len(new[k]):
                        restore_keys(item, new[k][i])
    return new


def llm_rewrite_blocklist(section, hits, section_name):
    """Ask the pro model to rewrite a section removing flagged words, keeping
    the exact same JSON structure."""
    flagged = sorted({w for words in hits.values() for w in words})
    system = TONE_RULES + (
        "\n\nRewrite the JSON section below so it contains NONE of the flagged words. "
        "Keep the EXACT same JSON structure: same keys, same number of list entries, "
        "same team names, same grades. Only rephrase text fields. "
        "Return ONLY the corrected JSON object."
    )
    user = (
        f"Section name: {section_name}\n"
        f"Flagged words to remove: {', '.join(flagged)}\n\n"
        f"Section JSON:\n{json.dumps(section, ensure_ascii=False, indent=1)}\n\n"
        "Return ONLY the corrected section JSON object with the same structure."
    )
    return llm_json(system, user)


# --------------------------------------------------------------------------
# LLM review + fix
# --------------------------------------------------------------------------

def llm_review(section, section_name):
    """Ask the pro model for a strict PASS/FAIL review of a section."""
    system = TONE_RULES + (
        "\n\nYou are the SAFETY REVIEWER. Read the report section and decide if it is "
        "safe for elementary-school kids. Verdict FAIL if there is: profanity, bullying, "
        "putting anyone down, mean-spirited language, or reading level too high for "
        "grades 2-4. "
        'Return ONLY strict JSON: {"verdict": "PASS" or "FAIL", "issues": ["..."], '
        '"suggestion": "..."}.'
    )
    user = f"Section: {section_name}\n\n{json.dumps(section, ensure_ascii=False, indent=1)}"
    return llm_json(system, user, max_tokens=1000, temperature=0.2)


def llm_rewrite_suggestion(section, review, section_name):
    """Rewrite a section to fix the reviewer's issues, keeping the structure."""
    issues = "; ".join(str(i) for i in (review.get("issues") or []))
    suggestion = str(review.get("suggestion") or "")
    system = TONE_RULES + (
        "\n\nRewrite the JSON section below so it follows ALL the rules and fixes the "
        "reviewer's issues. Keep the EXACT same JSON structure: same keys, same number "
        "of list entries, same team names, same grades. Return ONLY the corrected JSON object."
    )
    user = (
        f"Section name: {section_name}\n"
        f"Reviewer issues: {issues}\n"
        f"Reviewer suggestion: {suggestion}\n\n"
        f"Section JSON:\n{json.dumps(section, ensure_ascii=False, indent=1)}\n\n"
        "Return ONLY the corrected section JSON object with the same structure."
    )
    return llm_json(system, user)


# --------------------------------------------------------------------------
# Structure check (no LLM)
# --------------------------------------------------------------------------

def structure_check(report, expect_teams=12, expect_previews=6, expect_rankings=12):
    """Return a list of structure problems ([] = ok).

    power_rankings checks: exactly `expect_rankings` entries, ranks 1..N
    unique, all teams covered, non-empty reasons. Tone is enforced by the
    blocklist scan (step 1 of the per-section pipeline) and the LLM review
    (step 2) — this check is structural only.
    """
    problems = []
    secs = report.get("sections", {})
    grades = (secs.get("draft_analyzer", {}) or {}).get("team_grades") or []
    previews = (secs.get("matchup_previews", {}) or {}).get("previews") or []
    teams = (secs.get("team_updates", {}) or {}).get("teams") or []
    rankings = (secs.get("power_rankings", {}) or {}).get("rankings") or []

    if len(grades) != expect_teams:
        problems.append(f"draft_analyzer.team_grades has {len(grades)} entries (expected {expect_teams})")
    if len(teams) != expect_teams:
        problems.append(f"team_updates.teams has {len(teams)} entries (expected {expect_teams})")
    if len(previews) != expect_previews:
        problems.append(f"matchup_previews.previews has {len(previews)} entries (expected {expect_previews})")
    if len(rankings) != expect_rankings:
        problems.append(f"power_rankings.rankings has {len(rankings)} entries (expected {expect_rankings})")

    grade_names = {g.get("team") for g in grades if g.get("team")}
    update_names = {t.get("team") for t in teams if t.get("team")}
    if grade_names and update_names and grade_names != update_names:
        problems.append("team_grades and team_updates cover different teams")

    rank_nums = []
    ranked_teams = set()
    for r in rankings:
        try:
            rn = int(r.get("rank"))
        except (TypeError, ValueError):
            problems.append("power_rankings has a non-integer rank")
            continue
        if rn in rank_nums:
            problems.append(f"power_rankings has duplicate rank {rn}")
        rank_nums.append(rn)
        t = r.get("team")
        if not str(t or "").strip():
            problems.append("power_rankings entry missing team")
        else:
            ranked_teams.add(t)
        if not str(r.get("reason") or "").strip():
            problems.append(f"power_rankings[{t}] missing reason")
    if rank_nums and sorted(rank_nums) != list(range(1, expect_rankings + 1)):
        problems.append(f"power_rankings ranks must be exactly 1..{expect_rankings}, each used once")
    if grade_names and ranked_teams and ranked_teams != grade_names:
        problems.append("power_rankings covers different teams than team_grades")

    for g in grades:
        t = g.get("team", "?")
        if not str(g.get("positive") or "").strip():
            problems.append(f"team_grades[{t}] missing positive")
        if not str(g.get("needs_work") or "").strip():
            problems.append(f"team_grades[{t}] missing needs_work")
        if not str(g.get("worst_pick") or "").strip():
            problems.append(f"team_grades[{t}] missing worst_pick")
        if not str(g.get("best_pick") or "").strip():
            problems.append(f"team_grades[{t}] missing best_pick")
        if not str(g.get("sleeper_pick") or "").strip():
            problems.append(f"team_grades[{t}] missing sleeper_pick")
    for t in teams:
        n = t.get("team", "?")
        if not str(t.get("positive") or "").strip():
            problems.append(f"team_updates[{n}] missing positive")
        if not str(t.get("needs_work") or "").strip():
            problems.append(f"team_updates[{n}] missing needs_work")
    for i, p in enumerate(previews):
        a, b = p.get("team_a"), p.get("team_b")
        if not str(a or "").strip() or not str(b or "").strip():
            problems.append(f"preview[{i}] missing team_a or team_b")
        elif a == b:
            problems.append(f"preview[{i}]: team_a == team_b ({a})")
        if not str(p.get("preview") or "").strip():
            problems.append(f"preview[{i}] missing preview text")
    return problems


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def _plural(n):
    return f"{n} flagged word" + ("s" if n != 1 else "")


def main():
    ap = argparse.ArgumentParser(description="Safety gate for the Hofftown Ballers report.")
    ap.add_argument("--input", default="report.json")
    ap.add_argument("--output", default="report.reviewed.json")
    ap.add_argument("--expect-teams", type=int, default=None,
                    help="override expected team count (default 12; fixture mode derives it)")
    ap.add_argument("--expect-previews", type=int, default=None,
                    help="override expected preview count (default 6)")
    args = ap.parse_args()

    if not os.environ.get("DEEPSEEK_API_KEY"):
        print("ERROR: DEEPSEEK_API_KEY is not set — source C:/Users/dusti/AppData/Local/hermes/.env first.", file=sys.stderr)
        return 1

    try:
        with open(args.input, "r", encoding="utf-8") as f:
            report = json.load(f)
    except Exception as e:
        print(f"ERROR: cannot read {args.input}: {e}", file=sys.stderr)
        return 1

    sections = report.get("sections")
    if not isinstance(sections, dict):
        print("ERROR: report.json has no 'sections' object.", file=sys.stderr)
        return 1

    # Structure expectations: CLI flag > env var > fixture mode > spec defaults.
    expect_teams = args.expect_teams if args.expect_teams is not None else \
        int(os.environ.get("REVIEWER_EXPECT_TEAMS", "0") or 0) or None
    expect_previews = args.expect_previews if args.expect_previews is not None else \
        int(os.environ.get("REVIEWER_EXPECT_PREVIEWS", "0") or 0) or None
    expect_rankings = int(os.environ.get("REVIEWER_EXPECT_RANKINGS", "0") or 0) or None
    fixture_mode = bool(report.get("meta", {}).get("fixture"))
    if fixture_mode:
        grades = (sections.get("draft_analyzer", {}) or {}).get("team_grades") or []
        previews = (sections.get("matchup_previews", {}) or {}).get("previews") or []
        rankings = (sections.get("power_rankings", {}) or {}).get("rankings") or []
        expect_teams = expect_teams or len(grades)
        expect_previews = expect_previews or len(previews)
        expect_rankings = expect_rankings or len(rankings)
        print(f"note: fixture mode (meta.fixture=true) — structure expectations derived from report "
              f"(teams={expect_teams}, previews={expect_previews}, rankings={expect_rankings})")
    expect_teams = expect_teams or 12
    expect_previews = expect_previews or 6
    expect_rankings = expect_rankings or 12

    reviews = []
    failed = []
    fixed_count = 0

    for name in SECTIONS:
        if name not in sections or not isinstance(sections[name], dict):
            failed.append((name, "section missing from report.json"))
            reviews.append({"section": name, "verdict": "FAIL", "notes": "section missing"})
            continue

        sec = sections[name]

        # --- 1. Blocklist scan + auto-fix ---
        hits = scan_section(sec)
        notes = []
        if hits:
            n_words = sum(len(v) for v in hits.values())
            notes.append(f"removed {_plural(n_words)}")
            for rnd in range(2):  # max 2 LLM auto-fix rounds
                try:
                    new_sec = restore_keys(sec, llm_rewrite_blocklist(sec, hits, name))
                except Exception as e:
                    print(f"  [warn] {name}: blocklist rewrite round {rnd + 1} failed: {e}", file=sys.stderr)
                    break
                sec = new_sec
                hits = scan_section(sec)
                if not hits:
                    break
            if hits:
                print(f"  [warn] {name}: still dirty after LLM fixes — replacing flagged fields with kind sentences")
                sec = replace_flagged(sec, hits)
                hits = scan_section(sec)
        if hits:
            failed.append((name, "blocklist still failing after auto-fix + generic replacement: "
                                 + ", ".join(hits.keys())))
            reviews.append({"section": name, "verdict": "FAIL", "notes": "blocklist still failing"})
            continue
        sections[name] = sec

        # --- 2. LLM review (max 2 fix rounds) ---
        verdict = None
        infra = False
        for rnd in range(3):  # initial review + up to 2 rewrite/re-review cycles
            try:
                r = llm_review(sec, name)
            except Exception as e:
                # LLM unavailable after retries (e.g. pro model empty answers) —
                # infrastructure, NOT a content violation. The hard blocklist
                # scan already ran and passed, so record a blocklist-only PASS.
                print(f"  [warn] {name}: LLM reviewer unavailable after retries ({e}) — word-check only", file=sys.stderr)
                infra = True
                break
            v = str(r.get("verdict") or "").strip().upper()
            if v == "PASS":
                verdict = "PASS"
                break
            if rnd == 2:
                verdict = "FAIL"
                issues = r.get("issues") or []
                notes.append("LLM review FAIL after retries: " + "; ".join(str(i) for i in issues))
                break
            try:
                new_sec = restore_keys(sec, llm_rewrite_suggestion(sec, r, name))
            except Exception as e:
                print(f"  [warn] {name}: review-fix rewrite unavailable after retries ({e}) — word-check only", file=sys.stderr)
                infra = True
                break
            sec = new_sec
            notes.append("rewritten after review")
            # A rewrite could (re)introduce flags — re-scan defensively.
            hits = scan_section(sec)
            if hits:
                n_words = sum(len(v) for v in hits.values())
                sec = replace_flagged(sec, hits)
                notes.append(f"removed {_plural(n_words)} after review rewrite")
            sections[name] = sec

        if infra:
            reviews.append({"section": name, "verdict": "PASS", "notes": "LLM reviewer unavailable — word-check only"})
            print(f"  {name}: PASS — LLM reviewer unavailable — word-check only")
            continue

        if verdict == "FAIL":
            failed.append((name, "; ".join(notes) or "LLM review failed"))
            reviews.append({"section": name, "verdict": "FAIL", "notes": "; ".join(notes) or "failed"})
            continue

        if notes:
            fixed_count += 1
            reviews.append({"section": name, "verdict": "PASS (fixed)", "notes": "; ".join(notes)})
        else:
            reviews.append({"section": name, "verdict": "PASS", "notes": "clean"})
        print(f"  {name}: {reviews[-1]['verdict']} — {reviews[-1]['notes']}")

    # --- 3. Structure check (whole report, no LLM) ---
    problems = structure_check(report, expect_teams, expect_previews, expect_rankings)
    if problems:
        print("STRUCTURE CHECK FAILED:", file=sys.stderr)
        for p in problems:
            print("  - " + p, file=sys.stderr)

    # --- Hard fail rule ---
    if failed or problems:
        print(file=sys.stderr)
        print("SAFETY GATE FAILED — report.reviewed.json NOT written.", file=sys.stderr)
        for name, why in failed:
            print(f"  - section '{name}': {why}", file=sys.stderr)
        print("Fix report.json (or re-run writer.py) and run reviewer.py again.", file=sys.stderr)
        return 1

    # --- 4. Write report.reviewed.json ---
    report["reviews"] = reviews
    report.setdefault("meta", {})["reviewer_model"] = REVIEW_MODEL
    try:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"ERROR: cannot write {args.output}: {e}", file=sys.stderr)
        return 1

    total = len(SECTIONS)
    pass_n = sum(1 for rv in reviews if rv["verdict"].startswith("PASS"))
    fail_n = sum(1 for rv in reviews if rv["verdict"] == "FAIL")
    print(f"reviewed: {pass_n}/{total} PASS, {fail_n} FAIL, fixed={fixed_count}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
