#!/usr/bin/env python3
"""
Lyric Scrubber — GUI edition (dark theme, no threads).

  python lyric_scrub.py     (or double-click the file)

Paste lyrics in the left box, Ctrl+Enter to scrub, output on the right.
"""

import json
import os
import re
import time
from urllib import error, request

import tkinter as tk
from tkinter import font as tkfont, messagebox

# ════════════════════════════════════════════════════════════════════════
#  ▼▼▼  DEFAULT API KEY (optional — you can also type it in the window) ▼
DEFAULT_API_KEY = "sk-58d0cf9cefbf4c398817c3672b283fc4"          # "sk-..." or leave "" and fill the field
# ════════════════════════════════════════════════════════════════════════

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


def scrub(raw, api_key, model=DEFAULT_MODEL, repeat_label="Chorus"):
    cleaned = preclean(raw)
    if not cleaned.strip():
        raise ValueError("nothing left after pre-cleaning — no lyrics found")
    if api_key:
        out = strip_fences(call_deepseek(cleaned, api_key, model=model))
        if out.upper().startswith("NO_LYRICS"):
            raise ValueError("model reported no lyrics")
        rendered = render(parse_sections(out))
        if rendered.strip():
            return rendered
        raise ValueError("model output unparseable")
    rendered = format_local(cleaned, repeat_label)
    if not rendered.strip():
        raise ValueError("could not extract any lyrics")
    return rendered


# ────────────────────────────────────────────────────────────────────────
#  GUI — synchronous (no threads; works in sandboxes that block them)
# ────────────────────────────────────────────────────────────────────────

class App:
    # Palette (VS Code-ish dark)
    BG        = "#1e1e1e"
    PANEL     = "#252526"
    FG        = "#d4d4d4"
    FG_DIM    = "#888888"
    BORDER    = "#3c3c3c"
    ACCENT    = "#0e639c"
    ENTRY_BG  = "#2d2d30"
    SEL_BG    = "#264f78"
    SEL_FG    = "#ffffff"

    def __init__(self, root):
        self.root = root
        self.busy = False
        root.title("Lyric Scrubber")
        root.geometry("1180x720")
        root.minsize(760, 480)
        root.configure(bg=self.BG)

        self.base_font = tkfont.nametofont("TkDefaultFont").copy()
        self.base_font.configure(size=12)
        self.bold_font = self.base_font.copy()
        self.bold_font.configure(weight="bold")

        # ── API key row ────────────────────────────────────────────────
        top = tk.Frame(root, bg=self.BG)
        top.pack(fill="x", padx=12, pady=(12, 0))
        tk.Label(top, text="DeepSeek API key:", bg=self.BG, fg=self.FG,
                 font=self.base_font).pack(side="left")

        self.key_var = tk.StringVar(
            value=os.environ.get("DEEPSEEK_API_KEY", DEFAULT_API_KEY).strip()
        )
        self.key_entry = tk.Entry(
            top, textvariable=self.key_var, show="•",
            bg=self.ENTRY_BG, fg=self.FG,
            insertbackground=self.FG,
            selectbackground=self.SEL_BG, selectforeground=self.SEL_FG,
            disabledbackground=self.ENTRY_BG, disabledforeground=self.FG_DIM,
            relief="flat", bd=0,
            highlightthickness=1,
            highlightbackground=self.BORDER,
            highlightcolor=self.ACCENT,
            font=self.base_font,
        )
        self.key_entry.pack(side="left", fill="x", expand=True,
                            padx=(10, 0), ipady=4, ipadx=6)

        # ── side-by-side panels ────────────────────────────────────────
        pane = tk.PanedWindow(
            root, orient="horizontal",
            bg=self.BORDER, bd=0, relief="flat",
            sashwidth=6, sashrelief="flat", sashpad=0,
        )
        pane.pack(fill="both", expand=True, padx=12, pady=12)

        left_frame, self.input = self._make_panel(pane, " Raw lyrics — paste here ")
        right_frame, self.output = self._make_panel(pane, " Scrubbed output ")
        pane.add(left_frame, minsize=200, stretch="always")
        pane.add(right_frame, minsize=200, stretch="always")

        # ── bottom bar ─────────────────────────────────────────────────
        bar = tk.Frame(root, bg=self.BG)
        bar.pack(fill="x", padx=12, pady=(0, 12))

        self.scrub_btn = self._make_button(bar, "Scrub  (Ctrl+Enter)", self.do_scrub)
        self.scrub_btn.pack(side="left")
        self._make_button(bar, "Copy output", self.copy_out).pack(side="left", padx=(8, 0))
        self._make_button(bar, "Clear", self.clear).pack(side="left", padx=(8, 0))

        self.status = tk.Label(bar, text="Ready.", bg=self.BG, fg=self.FG_DIM,
                               font=self.base_font, anchor="e")
        self.status.pack(side="right")

        for seq in ("<Control-Return>", "<Command-Return>"):
            self.input.bind(seq, self._on_shortcut)
        self.input.focus_set()

    # ── widget factories ──────────────────────────────────────────────
    def _make_panel(self, parent, title):
        lf = tk.LabelFrame(
            parent, text=title,
            bg=self.BG, fg=self.FG, font=self.bold_font,
            bd=0, highlightthickness=1, highlightbackground=self.BORDER,
        )
        text = tk.Text(
            lf, wrap="word", undo=True, font=self.base_font,
            bg=self.PANEL, fg=self.FG,
            insertbackground=self.FG,
            selectbackground=self.SEL_BG, selectforeground=self.SEL_FG,
            relief="flat", bd=0, padx=10, pady=10,
            highlightthickness=0,
            spacing1=2, spacing3=2,
        )
        sb = tk.Scrollbar(
            lf, command=text.yview, orient="vertical",
            bg=self.PANEL, troughcolor=self.BG,
            activebackground=self.ACCENT,
            highlightthickness=0, relief="flat", bd=0, width=12,
        )
        text.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y", padx=(0, 2), pady=2)
        text.pack(side="left", fill="both", expand=True, padx=2, pady=2)
        return lf, text

    def _make_button(self, parent, text, cmd):
        return tk.Button(
            parent, text=text, command=cmd,
            bg=self.PANEL, fg=self.FG,
            activebackground=self.ACCENT, activeforeground=self.SEL_FG,
            disabledforeground=self.FG_DIM,
            relief="flat", bd=0,
            padx=14, pady=5,
            highlightthickness=0,
            font=self.base_font, cursor="hand2",
        )

    def _on_shortcut(self, _event=None):
        self.do_scrub()
        return "break"

    # ── actions ───────────────────────────────────────────────────────
    def do_scrub(self):
        if self.busy:
            return
        raw = self.input.get("1.0", "end").strip()
        if not raw:
            self._set_status("Nothing to scrub.")
            return

        key = self.key_var.get().strip()
        self.busy = True
        self.scrub_btn.config(state="disabled")
        self._set_status("Scrubbing…  (this can take a few seconds)")
        # Force the "Scrubbing…" state onto the screen before we block.
        try:
            self.root.update()          # repaint now (safe; self.busy guards re-entry)
        except Exception:
            pass

        try:
            out, err = scrub(raw, api_key=key), None
        except Exception as e:  # noqa: BLE001
            out, err = "", str(e)

        self.busy = False
        self.scrub_btn.config(state="normal")

        if err:
            self._set_status("Error.")
            try:
                messagebox.showerror("Scrub failed", err)
            except Exception:
                # some IDE shims don't implement messagebox — fall back to the box
                self.output.delete("1.0", "end")
                self.output.insert("1.0", f"ERROR: {err}")
            return

        self.output.delete("1.0", "end")
        self.output.insert("1.0", out)
        self._set_status(f"Done — {len(out.splitlines())} lines.")

    def copy_out(self):
        txt = self.output.get("1.0", "end").rstrip("\n")
        if not txt:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(txt)
        self._set_status("Copied to clipboard.")

    def clear(self):
        self.input.delete("1.0", "end")
        self.output.delete("1.0", "end")
        self._set_status("Ready.")
        self.input.focus_set()

    def _set_status(self, s):
        self.status.config(text=s)


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()