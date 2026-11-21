#!/usr/bin/env python3
"""
Lyric Scrubber — run it, paste lyrics, get clean output.

  python lyric_scrub.py          ← interactive (this is what you want)
  python lyric_scrub.py raw.txt  ← one-shot on a file
  pbpaste | python lyric_scrub.py ← one-shot on stdin
"""

# ════════════════════════════════════════════════════════════════════════
#  ▼▼▼  DROP YOUR TOKEN HERE  ▼▼▼
API_KEY = "sk-58d0cf9cefbf4c398817c3672b283fc4"              # "sk-..."  — leave "" to be asked once at startup
# ════════════════════════════════════════════════════════════════════════

import getpass
import json
import os
import re 
import sys
import time
from urllib import error, request

DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
DEFAULT_MODEL = "deepseek-chat"

# ────────────────────────────────────────────────────────────────────────
SYSTEM_PROMPT = r"""You are a lyrics scrubber and formatter. The user gives you raw text copied from a lyrics website (usually Genius). It is usually polluted.

REMOVE — none of this is lyrics:
- Site furniture: "You might also like", "Embed", "123Embed", "Read More", "Get tickets", "Upcoming Concerts", "N Contributors", "Translations", "Share", "Copy Link", "Add to playlist", "Advertisement", cookie/GDPR notices, "Sign in", "Sign up".
- Metadata blocks: Writer(s): ..., Producer(s): ..., Release Date: ..., Label: ..., Duration: ..., Genres: ...
- Artist commentary, trivia, "About this song", interview quotes, footnotes, annotation numbers like [1] or ¹.
- Live-show spoken intros, banter, crowd chatter, thank-yous, stage directions like (spoken), (laughs), (crowd cheers).
- Anything that is not part of the song as sung.

REPAIR:
- If what you were given is a non-canonical version (live ad-libs, remix, misheard transcript, partial copy), restore the standard, most widely known original version of the song — the version an audience would sing.
- Never invent lyrics for a song you do not know. If you do not recognize it, clean and label exactly what is given.
- If the text contains no actual lyrics at all, reply with exactly: NO_LYRICS

FORMAT — output ONLY the formatted lyrics. No preamble, no explanation, no code fences.
- Each section is a label on its own line, then that section's lines on the following lines.
- Separate sections with exactly one blank line. Never put a blank line between a label and its contents.
- Preserve the source's line breaks, punctuation, capitalization and spelling inside a section.
- Verse labels are numbered sequentially in order of appearance: Verse 1, Verse 2, Verse 3, ...
- Match the source's terminology when it labels sections (Chorus / Refrain / Hook / Bridge / Vamp / Pre-Chorus / Post-Chorus / Intro / Outro / Interlude / Instrumental / Tag). If the source has no labels, use what the structure implies: "Refrain" for hymn-style repeated refrains, "Chorus" for pop-style repeated choruses.
- Keep sections in the order they occur. If a chorus recurs, repeat the label where it recurs — but if the source only wrote it once, do not duplicate it.

Shape of the output:

Verse 1
'Tis so sweet to trust in Jesus,
and to take him at his word;

Refrain
Jesus, Jesus, how I trust him!

Verse 2
O how sweet to trust in Jesus,
"""
# ────────────────────────────────────────────────────────────────────────

NOISE_PATTERNS = [
    r"you\s+(?:might|may)\s+also\s+like", r"^\d*\s*embed$", r"^read\s+more$",
    r"^get\s+tickets.*", r"^upcoming\s+concerts?.*", r"^\d+\s+contributors?$",
    r"^contributors?$", r"^translations?$", r"^lyrics$", r"^share$",
    r"^copy\s+link$", r"^add\s+to\s+playlist$", r"^(?:sign|log)\s+(?:in|up|out)$",
    r"^writer\(s\)\s*:.*", r"^producers?(?:\(s\))?\s*:.*", r"^release\s+date\s*:.*",
    r"^label\s*:.*", r"^duration\s*:.*", r"^genres?\s*:.*", r"^about$",
    r"^genius\s+verified$", r"^how\s+to\s+format\s+lyrics.*", r"^advertisement$",
    r"^\[\d+\]$", r"^[×x✕]$",
]
NOISE_RE = re.compile("|".join(f"(?:{p})" for p in NOISE_PATTERNS), re.I)
SECTION_RE = re.compile(
    r"^\[?\s*(intro|verse\s*\d*|pre[\s-]?chorus|chorus|refrain|post[\s-]?chorus|"
    r"bridge|vamp|interlude|instrumental|outro|hook|tag|breakdown|break)\s*\]?\s*:?\s*$",
    re.I,
)
BRACKET_LABEL_RE = re.compile(r"^\[([^\]]+)\]\s*$")
EMBED_SUFFIX_RE = re.compile(r"\d*\s*embed\s*$", re.I)
CANON = {
    "intro": "Intro", "pre-chorus": "Pre-Chorus", "prechorus": "Pre-Chorus",
    "pre chorus": "Pre-Chorus", "chorus": "Chorus", "refrain": "Refrain",
    "post-chorus": "Post-Chorus", "postchorus": "Post-Chorus",
    "post chorus": "Post-Chorus", "bridge": "Bridge", "vamp": "Vamp",
    "interlude": "Interlude", "instrumental": "Instrumental", "outro": "Outro",
    "hook": "Hook", "tag": "Tag", "breakdown": "Breakdown", "break": "Break",
}


def header_of(line):
    s = line.strip().strip("*_#` ").strip()
    m = SECTION_RE.match(s)
    return m.group(1) if m else None


def canonical_label(label):
    s = re.sub(r"\s+", " ", label.strip().strip("[]").strip()).lower().rstrip(":")
    if s.startswith("verse"):
        return "Verse"
    return CANON.get(s, s.title())


def preclean(text):
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\u200b", "").replace("\ufeff", "")
    out = []
    for raw in text.split("\n"):
        line = raw.rstrip()
        if NOISE_RE.match(line.strip()):
            continue
        line = EMBED_SUFFIX_RE.sub("", line).rstrip()
        m = BRACKET_LABEL_RE.match(line.strip())
        if m and SECTION_RE.match(m.group(1).split(":")[0].strip()):
            line = f"[{m.group(1).split(':')[0].strip()}]"
        out.append(line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip("\n")


def parse_sections(text):
    sections, label, body = [], None, []
    for line in text.split("\n"):
        h = header_of(line)
        if h:
            if label is not None or any(l.strip() for l in body):
                sections.append((label, body))
            label, body = h, []
        else:
            body.append(line)
    if label is not None or any(l.strip() for l in body):
        sections.append((label, body))
    return sections


def render(sections):
    blocks, verse_n = [], 0
    for label, body in sections:
        if label is None:
            continue
        lines = [l.rstrip() for l in body]
        while lines and not lines[0].strip():
            lines.pop(0)
        while lines and not lines[-1].strip():
            lines.pop()
        if not lines:
            continue
        lab = canonical_label(label)
        if lab == "Verse":
            verse_n += 1
            lab = f"Verse {verse_n}"
        blocks.append(lab + "\n" + "\n".join(lines))
    return ("\n\n".join(blocks) + "\n") if blocks else ""


def heuristic_label(text, repeat_label="Chorus"):
    if any(header_of(l) for l in text.split("\n")):
        return text
    stanzas, cur = [], []
    for line in text.split("\n"):
        if line.strip():
            cur.append(line)
        elif cur:
            stanzas.append(cur); cur = []
    if cur:
        stanzas.append(cur)
    if not stanzas:
        return text

    def key(st):
        return re.sub(r"[^a-z0-9]", "", " ".join(st).lower())

    keys = [key(s) for s in stanzas]
    counts = {k: keys.count(k) for k in keys}
    out, verse_n = [], 0
    for st, k in zip(stanzas, keys):
        if counts[k] > 1 and len(k) > 20:
            label = repeat_label
        else:
            verse_n += 1
            label = f"Verse {verse_n}"
        out.append(f"[{label}]"); out.extend(st); out.append("")
    return "\n".join(out).strip()


def format_local(text, repeat_label="Chorus"):
    if any(header_of(l) for l in text.split("\n")):
        return render(parse_sections(text))
    return render(parse_sections(heuristic_label(text, repeat_label)))


def strip_fences(s):
    s = s.strip()
    m = re.match(r"^```[a-zA-Z]*\n(.*?)\n```$", s, re.S)
    return m.group(1).strip() if m else s


def call_deepseek(text, api_key, model=DEFAULT_MODEL, timeout=180, retries=3):
    payload = json.dumps({
        "model": model,
        "temperature": 0.2,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ],
    }).encode()
    last = None
    for attempt in range(retries):
        req = request.Request(
            DEEPSEEK_URL, data=payload, method="POST",
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {api_key}"},
        )
        try:
            with request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode())["choices"][0]["message"]["content"].strip()
        except error.HTTPError as e:
            last = f"HTTP {e.code}: {e.read().decode(errors='replace')[:300]}"
            if e.code in (429, 500, 502, 503, 504):
                time.sleep(2 ** attempt); continue
            break
        except Exception as e:  # noqa: BLE001
            last = str(e); time.sleep(2 ** attempt)
    raise RuntimeError(f"DeepSeek request failed: {last}")


def scrub(raw, api_key, model=DEFAULT_MODEL, repeat_label="Chorus", verbose=False):
    cleaned = preclean(raw)
    if not cleaned.strip():
        raise ValueError("nothing left after pre-cleaning — no lyrics found")
    if api_key:
        try:
            out = strip_fences(call_deepseek(cleaned, api_key, model=model))
            if out.upper().startswith("NO_LYRICS"):
                raise ValueError("model reported no lyrics")
            rendered = render(parse_sections(out))
            if rendered.strip():
                return rendered
            raise ValueError("model output unparseable")
        except Exception as e:  # noqa: BLE001
            if verbose:
                print(f"[warn] API failed ({e}); using local heuristics.", file=sys.stderr)
    rendered = format_local(cleaned, repeat_label)
    if not rendered.strip():
        raise ValueError("could not extract any lyrics")
    return rendered


# ── token ───────────────────────────────────────────────────────────────
def resolve_key():
    key = API_KEY.strip() or os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if key:
        return key
    try:
        key = getpass.getpass("DeepSeek API key (hidden, blank = local only): ").strip()
    except Exception:
        key = ""
    return key


# ── interactive entry ──────────────────────────────────────────────────
def read_block():
    """Read lines until END / EOF. Blank lines are preserved."""
    lines = []
    while True:
        try:
            line = input()
        except (EOFError, KeyboardInterrupt):
            break
        if line.strip().upper() == "END":
            break
        lines.append(line)
    return "\n".join(lines)


def run_once(raw, key, model=DEFAULT_MODEL):
    try:
        out = scrub(raw, api_key=key, model=model, verbose=True)
    except Exception as e:  # noqa: BLE001
        print(f"\n⚠️  {e}\n", file=sys.stderr)
        return
    print()
    print("═" * 60)
    print(out.rstrip())
    print("═" * 60)


def playground():
    key = resolve_key()
    print()
    print("  Lyric Scrubber")
    print("  " + "─" * 46)
    print("  Paste lyrics below, then type  END  on its own line.")
    print("  (On Windows you can also press Ctrl-Z then Enter.)")
    print("  Ctrl-C to quit.")
    while True:
        print()
        print("┌─ paste lyrics ─────────────────────────────")
        block = read_block()
        if not block.strip():
            print("└─ (empty, done)")
            break
        print(f"└─ {len(block.splitlines())} lines received ─────────────")
        run_once(block, key)
        try:
            more = input("Another song? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            break
        if not more.startswith("y"):
            break
    print("\nbye.")


def main(argv):
    if len(argv) > 1 and argv[1] != "-":
        raw = open(argv[1], "r", encoding="utf-8").read()
        run_once(raw, resolve_key())
        return 0
    if not sys.stdin.isatty():
        run_once(sys.stdin.read(), resolve_key())
        return 0
    playground()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv))
    except KeyboardInterrupt:
        print("\nbye.")
        sys.exit(130)