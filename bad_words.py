"""bad_words.py — profanity/bullying blocklist + scan for the Hofftown Ballers
weekly report.

Pure data + stdlib `re`. No LLM calls, no third-party deps.

scan_text(text) -> list[str]
    Case-insensitive, word-boundary-aware scan returning the unique blocklisted
    words found in `text` (lowercased, in order of first appearance).
    Also scans an emoji-stripped copy of the text so emoji never hides a word.
    Catches inflections via stem patterns, e.g. 'sucks' inside 'sucked',
    'sucking', 'suckiest', etc.
"""

import re

# Comprehensive blocklist: profanity + bullying/put-down words + the words the
# league's tone rules ban (SPEC §7: sucks, trash, terrible, awful, stupid,
# dumb, loser, worst, garbage, boring, hate). Includes common inflected
# variations so a plain word-boundary scan flags them.
BLOCKLIST = [
    # --- profanity ---
    "ass", "asses", "assed", "asshole", "assholes", "asshat", "asswipe",
    "bastard", "bastards", "bitch", "bitches", "bitched", "bitching", "bitchy",
    "blowjob", "blowjobs", "boner", "boob", "boobs", "bullshit",
    "clit", "cock", "cocksucker", "crap", "craps", "crappy", "crapped", "crapping",
    "cum", "cunt", "damn", "damned", "dammit", "damnit",
    "dick", "dicks", "dickhead", "dickheads", "dildo", "douche", "douchebag",
    "dyke", "fag", "fags", "faggot", "faggots", "fuck", "fucks", "fucked",
    "fucking", "fucker", "fuckers", "fuckface", "goddamn", "goddamned",
    "goddammit", "hell", "homo", "jackass", "jackasses", "jizz", "kike",
    "motherfucker", "nigga", "nigger", "piss", "pissed", "pissing", "pissant",
    "prick", "pricks", "pube", "pubes", "pussy", "queer", "retard", "retards",
    "retarded", "scumbag", "shit", "shits", "shitty", "shitted", "slut", "sluts",
    "sodomize", "sonofabitch", "spic", "tits", "titty", "turd", "turds",
    "twat", "wank", "wanker", "wankers", "whore", "whores",
    # --- put-downs / bullying ---
    "suck", "sucks", "sucked", "sucking", "sucker", "suckers",
    "loser", "losers", "dumb", "dumber", "dumbest", "dumbass", "dumbasses",
    "stupid", "stupider", "stupidest", "stupidity", "idiot", "idiots",
    "moron", "morons", "imbecile", "simpleton", "halfwit", "dimwit", "nitwit",
    "numbskull", "bonehead", "blockhead", "airhead", "dunce", "ignoramus",
    "trash", "trashed", "trashy", "trashing", "garbage", "terrible", "awful",
    "worthless", "pathetic", "weakling", "lame", "coward", "wimp", "wuss",
    "sissy", "freak", "weirdo", "fatso", "fatty", "doofus", "dipshit",
    "dipstick", "jerk", "jerks", "jerkoff", "jerkface", "butthead", "buttface",
    "dork", "dorks", "dorky", "meanie", "hate", "hates", "hated", "hating",
    "hater", "worst", "boring",
]

# Root words whose inflections must ALSO be caught even when not listed
# verbatim (e.g. 'sucked' contains 'suck'). Kept deliberately small to avoid
# false positives on ordinary words ('assist', 'Dickerson', 'assembly' must
# NOT be flagged).
_STEM_PATTERNS = {
    "suck", "shit", "fuck", "crap", "piss", "bitch", "retard",
}

# Treat letters, digits and underscore as word chars so "trash_talk" isn't
# split into two clean halves.
_ATOM = r"[a-z0-9_]"


def _compile():
    pats = []
    for w in BLOCKLIST:
        pats.append(r"(?<!{a}){w}(?!{a})".format(a=_ATOM, w=re.escape(w.lower())))
    for stem in sorted(_STEM_PATTERNS):
        pats.append(r"(?<!{a}){stem}[a-z]*(?!{a})".format(a=_ATOM, stem=re.escape(stem)))
    return re.compile("|".join(pats), re.IGNORECASE)


_SCAN_RE = _compile()
_EMOJI_FREE = re.compile(r"[^\x00-\x7F]+")  # strips emoji/unicode for a second pass


def scan_text(text):
    """Return unique blocklisted words found in `text` (lowercased).

    Case-insensitive word-boundary scan; also scans an emoji-stripped copy.
    Catches inflections (e.g. 'sucks' inside 'sucked'). Returns [] if clean.
    """
    if not text:
        return []
    found = []
    seen = set()
    for chunk in (text, _EMOJI_FREE.sub(" ", text)):
        for m in _SCAN_RE.finditer(chunk):
            w = m.group(0).lower()
            if w not in seen:
                seen.add(w)
                found.append(w)
    return found
