#!/usr/bin/env python3
"""humanize.py — post-review humanizer pass for the Hofftown Ballers report.

Reads report.reviewed.json (the safety-gated report) and rewrites every prose
string field through DeepSeek deepseek-v4-flash to strip AI writing tells
(filler phrases, hedging, rule-of-three overuse, em-dash overuse, generic
positive conclusions, signposting, forced metaphors, reassurance kickers,
sentence-opener tics — per the humanizer skill, adapted for kid content).

After rewriting, RE-RUNS bad_words.scan_text on every rewritten field as a
hard gate: a flagged field gets one more rewrite with the flagged words
called out; if it still hits, the field is replaced with a generic kind
sentence. Unsafe text is never written.

Writes report.humanized.json — SAME schema as report.reviewed.json (reviews
array kept), with meta.humanized = true.

Stdlib only (urllib.request) — GitHub Actions runners have no third-party
deps. Timeout 120s; retry once on 429/5xx/empty with 10s backoff.
Never prints the API key.

Usage:
    set -a; source <path-to-hermes>/.env; set +a
    python humanize.py
"""

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

import bad_words

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INPUT_PATH = os.path.join(BASE_DIR, "report.reviewed.json")
OUTPUT_PATH = os.path.join(BASE_DIR, "report.humanized.json")

API_URL = "https://api.deepseek.com/chat/completions"
MODEL_FLASH = "deepseek-v4-flash"
TIMEOUT_SEC = 120
TEMP = 0.7
MAX_TOKENS = 1000

# Keys whose values are structural (exact display names, grades, ranks,
# section titles, emoji) and must pass through unchanged — downstream
# rendering depends on them verbatim.
SKIP_KEYS = {"title", "team", "team_a", "team_b", "rank", "grade", "emoji"}

# Generic kind sentences used when a field still fails the blocklist after
# both rewrite rounds (same spirit as reviewer.py GENERIC_KIND; safe by
# construction). Keyed by field name.
GENERIC_KIND = {
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

SYSTEM_HUMANIZE = """You are the friendly editor for a kid-friendly fantasy football report written for ELEMENTARY SCHOOL KIDS (grades 2-4).
Rewrite the text below to remove AI writing tells:
- Filler phrases: "in order to", "due to the fact that", "at this point in time", "it is important to note"
- Hedging: "could potentially", "might want to", "may need"
- Rule-of-three overuse and elegant synonym cycling (repeating the same idea with different fancy words)
- Em-dash overuse (—)
- Generic positive conclusions ("the future looks bright", "exciting times lie ahead")
- Signposting ("let's dive in", "here's what you need to know")
- Forced metaphors and reassurance kickers ("and that's okay")
- Sentence-opener tics ("So,", "Interestingly,", "Notably,")
KEEP:
- Emojis, short sentences, the playful kid voice
- Team names, player names, and exact picks (player/position/round references like "Bijan Robinson (RB, 1.05)")
- The positive + needs-work structure and the meaning
Make it sound like a fun human wrote it, not a robot. Keep the same meaning.
Return ONLY the rewritten text. No explanations, no quotes around the whole text, no JSON."""


def clean_response(text):
    """Tolerantly extract plain text from a flash response."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    # Tolerate a JSON wrapper if the model returns one anyway.
    if text.startswith("{") and text.endswith("}"):
        try:
            obj = json.loads(text)
            if isinstance(obj, dict):
                for k in ("text", "content", "rewritten"):
                    if isinstance(obj.get(k), str) and obj[k].strip():
                        text = obj[k].strip()
                        break
        except json.JSONDecodeError:
            pass
    # Strip a single pair of wrapping quotes.
    if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
        try:
            text = json.loads(text)
        except json.JSONDecodeError:
            text = text[1:-1]
    return text.strip()


def call_rewrite(text):
    """One DeepSeek flash rewrite → rewritten plain-text string.

    Timeout 120s; retry once on 429/5xx/empty/network errors with 10s
    backoff. Never prints the API key.
    """
    key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not key:
        raise RuntimeError("DEEPSEEK_API_KEY environment variable is not set")
    payload = {
        "model": MODEL_FLASH,
        "messages": [
            {"role": "system", "content": SYSTEM_HUMANIZE},
            {"role": "user", "content": f"Rewrite this text:\n\n{text}"},
        ],
        "max_tokens": MAX_TOKENS,
        "temperature": TEMP,
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
            out = clean_response(content)
            if out:
                return out
            raise ValueError("empty rewrite response")
        except urllib.error.HTTPError as e:
            last_error = f"HTTP {e.code}"
            retryable = e.code == 429 or 500 <= e.code < 600
            if retryable and attempt == 1:
                time.sleep(10)
                continue
            raise RuntimeError(f"DeepSeek API error: {last_error}")
        except (urllib.error.URLError, TimeoutError, ConnectionError,
                json.JSONDecodeError, KeyError, ValueError) as e:
            last_error = f"{type(e).__name__}: {e}"
            if attempt == 1:
                time.sleep(10)
                continue
            raise RuntimeError(f"DeepSeek API call failed: {last_error}")
    raise RuntimeError(f"DeepSeek API call failed: {last_error}")


# ── Field walking (every prose string field in sections) ───────────────────

def _field_key(path):
    """'draft_analyzer.team_grades[0].best_pick' -> 'best_pick'."""
    return path.rsplit(".", 1)[-1].split("[")[0]


def collect_fields(sections):
    """Return [(path, value)] for every non-empty prose string field."""
    fields = []

    def walk(obj, path):
        if isinstance(obj, dict):
            for k, v in obj.items():
                walk(v, f"{path}.{k}" if path else k)
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                walk(v, f"{path}[{i}]")
        elif isinstance(obj, str):
            if obj.strip() and _field_key(path) not in SKIP_KEYS:
                fields.append((path, obj))

    walk(sections, "")
    return fields


def parse_path(path):
    """'a.b[2].c' -> ['a', 'b', 2, 'c']"""
    parts = []
    for m in re.finditer(r"([^.\[\]]+)|\[(\d+)\]", path):
        if m.group(1) is not None:
            parts.append(m.group(1))
        else:
            parts.append(int(m.group(2)))
    return parts


def set_value(obj, path, value):
    parts = parse_path(path)
    cur = obj
    for p in parts[:-1]:
        cur = cur[p]
    cur[parts[-1]] = value


def rewrite_fields(sections):
    """Rewrite every prose field; hard-gate each with bad_words.

    Returns the number of fields that had to fall back to a generic kind
    sentence (the "flags" count).
    """
    n_flags = 0
    for path, value in collect_fields(sections):
        try:
            text = call_rewrite(value)
        except Exception as e:
            print(f"  [warn] humanize: {path} failed ({e}) — keeping original", file=sys.stderr)
            continue
        if not text:
            continue
        # Hard gate: never write unsafe text.
        hits = bad_words.scan_text(text)
        if hits:
            try:
                text2 = call_rewrite(
                    text + "\n\nRewrite again and remove these words completely: "
                    + ", ".join(hits)
                )
                if text2 and not bad_words.scan_text(text2):
                    set_value(sections, path, text2)
                    continue
            except Exception:
                pass
            text = GENERIC_KIND.get(_field_key(path), "The league is having a great season! 🏈")
            n_flags += 1
        set_value(sections, path, text)
    return n_flags


def main():
    if not os.environ.get("DEEPSEEK_API_KEY"):
        print("ERROR: DEEPSEEK_API_KEY is not set — source C:/Users/dusti/AppData/Local/hermes/.env first.", file=sys.stderr)
        return 1
    if not os.path.exists(INPUT_PATH):
        print(f"ERROR: {INPUT_PATH} not found — run reviewer.py first.", file=sys.stderr)
        return 1
    try:
        with open(INPUT_PATH, "r", encoding="utf-8") as f:
            report = json.load(f)
    except Exception as e:
        print(f"ERROR: cannot read {INPUT_PATH}: {e}", file=sys.stderr)
        return 1

    sections = report.get("sections")
    if not isinstance(sections, dict):
        print("ERROR: report has no 'sections' object.", file=sys.stderr)
        return 1

    fields = collect_fields(sections)
    print(f"humanize: rewriting {len(fields)} fields...")
    n_flags = rewrite_fields(sections)

    report["sections"] = sections
    report.setdefault("meta", {})["humanized"] = True
    try:
        with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"ERROR: cannot write {OUTPUT_PATH}: {e}", file=sys.stderr)
        return 1

    print(f"humanized: {len(fields)} fields, {n_flags} flags")
    return 0


if __name__ == "__main__":
    sys.exit(main())
