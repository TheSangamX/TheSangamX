"""Builds the profile's images from sangamgupta.in, so the README matches the site and never goes stale.

    pip install fonttools brotli
    python3 scripts/build_profile.py            # SITE=http://localhost:3000 for local tests

Reads /resume.json (skills, projects, credit, metrics) and /feed.xml (post count), writes light and dark SVGs
to profile/svg/ in the site's fonts (subset and embedded) and colours, and rewrites the README block between
<!-- PROJECTS:START --> and <!-- PROJECTS:END -->. Every number in config.json's text must appear in the
site's own data, or the build stops: nothing here may claim more than the site does.
"""

import base64
import html
import io
import json
import os
import random
import re
import sys
import urllib.request
from collections import defaultdict

from fontTools import subset
from fontTools.ttLib import TTFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROFILE = os.path.join(ROOT, "profile")
OUT = os.path.join(PROFILE, "svg")
CONFIG = json.load(open(os.path.join(PROFILE, "config.json")))
SITE = os.environ.get("SITE", CONFIG["site"]).rstrip("/")
RAW = f"https://raw.githubusercontent.com/{CONFIG['repo']}/main/profile/svg"

THEMES = {
    "light": dict(card="#f6f7f9", inset="#ffffff", ink="#16181d", graphite="#5a5f6a", rule="#dcdfe5",
                  accent="#2a3cdb", soft="#e6e8fb", on_accent="#ffffff", node="#c3c7d0"),
    "dark": dict(card="#151920", inset="#0d1117", ink="#e8eaef", graphite="#9198a5", rule="#272b34",
                 accent="#8d98ff", soft="#1d2140", on_accent="#0d1117", node="#3a404c"),
}

FONTS = {
    "serif": ("newsreader-latin-400-normal.woff", "'Newsreader', Georgia, serif", 400),
    "sans": ("schibsted-grotesk-latin-400-normal.woff", "'Schibsted Grotesk', Arial, sans-serif", 400),
    "sansm": ("schibsted-grotesk-latin-500-normal.woff", "'Schibsted Grotesk', Arial, sans-serif", 500),
    "mono": ("jetbrains-mono-latin-400-normal.woff", "'JetBrains Mono', Consolas, monospace", 400),
}


class Metrics:
    """Advance widths straight from the font files, so wrapping matches what the browser draws."""

    def __init__(self, path):
        f = TTFont(path)
        self.cmap = f.getBestCmap()
        self.hmtx = f["hmtx"].metrics
        self.upem = f["head"].unitsPerEm
        self.fallback = self.hmtx.get(self.cmap.get(ord("n")), (500, 0))[0]

    def width(self, text, size):
        total = 0
        for ch in text:
            g = self.cmap.get(ord(ch))
            total += self.hmtx[g][0] if g in self.hmtx else self.fallback
        return total / self.upem * size


METRICS = {k: Metrics(os.path.join(PROFILE, "fonts", v[0])) for k, v in FONTS.items()}


def width(text, font, size):
    return METRICS[font].width(text, size)


def wrap(text, font, size, max_w):
    lines, line = [], ""
    for word in text.split():
        test = f"{line} {word}".strip()
        if width(test, font, size) <= max_w or not line:
            line = test
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def fit(text, font, size, max_w):
    """Shorten a list-like line (a · b · c) at a separator so it fits, never mid-word."""
    if width(text, font, size) <= max_w:
        return text
    parts = text.split(" · ")
    while len(parts) > 1 and width(" · ".join(parts), font, size) > max_w:
        parts.pop()
    return " · ".join(parts)


def esc(s):
    return html.escape(s, quote=True)


class Svg:
    def __init__(self, w, h, theme, title):
        self.w, self.h, self.t, self.title = w, h, THEMES[theme], title
        self.parts, self.used, self.css = [], defaultdict(set), []

    def add(self, s):
        self.parts.append(s)

    def text(self, x, y, s, font, size, fill, anchor="start", attrs=""):
        self.used[font] |= set(s)
        self.add(f'<text x="{x:.1f}" y="{y:.1f}" class="{font}" font-size="{size}" fill="{fill}" text-anchor="{anchor}" {attrs}>{esc(s)}</text>')

    def card(self, x=0.5, y=0.5, w=None, h=None, r=20):
        w = (w if w is not None else self.w - 1)
        h = (h if h is not None else self.h - 1)
        self.add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{self.t["card"]}" stroke="{self.t["rule"]}"/>')

    def render(self):
        faces = []
        for key, chars in self.used.items():
            file, family, weight = FONTS[key]
            opts = subset.Options()
            opts.flavor = "woff2"
            opts.layout_features = ["kern", "liga"]
            font = subset.load_font(os.path.join(PROFILE, "fonts", file), opts)
            s = subset.Subsetter(opts)
            s.populate(text="".join(sorted(chars | {" "})))
            s.subset(font)
            buf = io.BytesIO()
            subset.save_font(font, buf, opts)
            data = base64.b64encode(buf.getvalue()).decode()
            name = f"p-{key}"
            faces.append(f"@font-face{{font-family:'{name}';src:url(data:font/woff2;base64,{data}) format('woff2');font-weight:{weight}}}")
            faces.append(f".{key}{{font-family:'{name}',{family};font-weight:{weight}}}")
        style = "".join(faces) + "".join(self.css) + "@media (prefers-reduced-motion: reduce){.motion{display:none}}"
        return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.w}" height="{self.h}" viewBox="0 0 {self.w} {self.h}" role="img" aria-label="{esc(self.title)}">'
                f"<title>{esc(self.title)}</title><style>{style}</style>{''.join(self.parts)}</svg>")


def get(path):
    req = urllib.request.Request(f"{SITE}{path}", headers={"user-agent": "TheSangamX-profile-build"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode()


def write(name, theme, svg):
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, f"{name}-{theme}.svg"), "w") as f:
        f.write(svg.render())


def picture(name, alt, width=None, height=None, href=None):
    size = (f' width="{width}"' if width else "") + (f' height="{height}"' if height else "")
    img = (f'<picture><source media="(prefers-color-scheme: dark)" srcset="{RAW}/{name}-dark.svg">'
           f'<img src="{RAW}/{name}-light.svg"{size} alt="{esc(alt)}"></picture>')
    return f'<a href="{href}">{img}</a>' if href else img


# ---------- pieces ----------

def header(theme, resume, availability):
    s = Svg(1200, 360, theme, f"{resume['basics']['name']}, {resume['basics']['label']}")
    t = s.t
    # A small network on the right with signals passing through it, like a forward pass. Fades toward the text.
    rnd = random.Random(7)
    layers = [3, 5, 6, 5, 3]
    xs = [720, 830, 940, 1050, 1150]
    nodes = []
    for x, n in zip(xs, layers):
        gap = 300 / (n + 1)
        nodes.append([(x + rnd.uniform(-10, 10), 30 + gap * (i + 1) + rnd.uniform(-8, 8)) for i in range(n)])
    s.add('<defs><linearGradient id="fade" x1="0" x2="1"><stop offset="0" stop-color="#fff" stop-opacity="0"/>'
          '<stop offset="0.32" stop-color="#fff" stop-opacity="1"/></linearGradient>'
          '<mask id="m"><rect x="640" y="0" width="560" height="360" fill="url(#fade)"/></mask></defs><g mask="url(#m)">')
    for a, b in zip(nodes, nodes[1:]):
        for (x1, y1) in a:
            for (x2, y2) in b:
                s.add(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{t["rule"]}" stroke-width="1.1"/>')
    for layer in nodes:
        for (x, y) in layer:
            s.add(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5" fill="{t["card"]}" stroke="{t["node"]}" stroke-width="1.6"/>')
    dur, travel = 6.0, 0.55
    for c in range(5):
        path = [rnd.choice(layer) for layer in nodes]
        d = "M" + " L".join(f"{x:.1f} {y:.1f}" for x, y in path)
        begin = f"{c * 1.2:.1f}s"
        for k, (x, y) in enumerate(path):
            at = travel * k / (len(path) - 1)
            kt = [0, max(0, at - 0.02), at, min(1, at + 0.09), 1]
            kt = ";".join(f"{v:.3f}" for v in sorted(set(kt)))
            vals = "0;0;0.9;0;0" if len(kt.split(";")) == 5 else "0;0.9;0;0"
            s.add(f'<circle class="motion" cx="{x:.1f}" cy="{y:.1f}" r="5" fill="{t["accent"]}" opacity="0">'
                  f'<animate attributeName="opacity" values="{vals}" keyTimes="{kt}" dur="{dur}s" begin="{begin}" repeatCount="indefinite"/></circle>')
        s.add(f'<g class="motion" opacity="0"><circle r="9" fill="{t["accent"]}" opacity="0.18"/><circle r="3.6" fill="{t["accent"]}"/>'
              f'<animateMotion path="{d}" keyPoints="0;1;1" keyTimes="0;{travel};1" calcMode="linear" dur="{dur}s" begin="{begin}" repeatCount="indefinite"/>'
              f'<animate attributeName="opacity" values="0;1;1;0;0" keyTimes="0;0.04;{travel - 0.02:.2f};{travel + 0.03:.2f};1" dur="{dur}s" begin="{begin}" repeatCount="indefinite"/></g>')
    s.add("</g>")
    s.text(0, 112, resume["basics"]["name"], "serif", 96, t["ink"], attrs='letter-spacing="-1.5"')
    s.text(2, 168, f"{resume['basics']['label'][0].upper()}{resume['basics']['label'][1:]} in Mumbai", "sansm", 30, t["ink"])
    y = 214
    for line in wrap(CONFIG["intro"], "sans", 23, 640):
        s.text(2, y, line, "sans", 23, t["graphite"])
        y += 33
    status = availability.split(":")[0]
    s.add(f'<circle cx="10" cy="{y + 22}" r="6" fill="{t["accent"]}"/>'
          f'<circle class="motion" cx="10" cy="{y + 22}" r="6" fill="none" stroke="{t["accent"]}" stroke-width="2">'
          f'<animate attributeName="r" values="6;15" dur="2.4s" repeatCount="indefinite"/>'
          f'<animate attributeName="opacity" values="0.7;0" dur="2.4s" repeatCount="indefinite"/></circle>')
    for i, line in enumerate(wrap(status, "sansm", 19, 620)):
        s.text(28, y + 29 + i * 26, line, "sansm", 19, t["ink"])
    return s


def pill(theme, label, primary):
    t = THEMES[theme]
    size, pad = 19, 26
    dot = 22 if primary else 0
    w = max(72, int(width(label, "sansm", size) + 2 * pad + dot))
    s = Svg(w, 48, theme, label)
    if primary:
        s.add(f'<rect x="0.5" y="0.5" width="{w - 1}" height="47" rx="23.5" fill="{t["accent"]}"/>')
        s.add(f'<circle cx="{pad + 4}" cy="24" r="4.5" fill="{t["on_accent"]}"/>'
              f'<circle class="motion" cx="{pad + 4}" cy="24" r="4.5" fill="none" stroke="{t["on_accent"]}" stroke-width="1.6">'
              f'<animate attributeName="r" values="4.5;10" dur="2.4s" repeatCount="indefinite"/>'
              f'<animate attributeName="opacity" values="0.8;0" dur="2.4s" repeatCount="indefinite"/></circle>')
        s.text(pad + dot, 31, label, "sansm", size, t["on_accent"])
    else:
        s.add(f'<rect x="0.75" y="0.75" width="{w - 1.5}" height="46.5" rx="23.25" fill="none" stroke="{t["rule"]}" stroke-width="1.5"/>')
        s.text(w / 2, 31, label, "sansm", size, t["ink"], "middle")
    return s


def ask_card(theme, projects):
    ask = CONFIG["ask"]
    answer = wrap(ask["answer"], "sans", 22, 1060)
    h = 268 + len(answer) * 33
    s = Svg(1200, h, theme, f"Ask Sangam, the AI agent on my site. Example: {ask['question']} {ask['answer']}")
    t = s.t
    s.card()
    s.text(48, 66, "Ask Sangam", "serif", 38, t["ink"])
    s.text(48 + width("Ask Sangam", "serif", 38) + 18, 64, "the AI agent on my site, answering from my own work", "sans", 20, t["graphite"])
    s.add(f'<rect x="48" y="96" width="1104" height="64" rx="14" fill="{t["inset"]}" stroke="{t["rule"]}"/>')
    q = f"> {ask['question']}"
    cw = width("a", "mono", 22)
    dur = 16
    typing = 0.16
    n = len(q)
    vals = ";".join(f"{cw * i:.1f}" for i in range(n + 1)) + f";{cw * n:.1f};0"
    kts = ";".join(f"{typing * i / n:.4f}" for i in range(n + 1)) + ";0.97;1"
    s.add(f'<clipPath id="type"><rect x="70" y="105" height="46" width="{cw * n:.1f}">'
          f'<animate attributeName="width" values="{vals}" keyTimes="{kts}" calcMode="discrete" dur="{dur}s" repeatCount="indefinite"/></rect></clipPath>')
    s.used["mono"] |= set(q)
    s.add(f'<text x="72" y="136" class="mono" font-size="22" fill="{t["ink"]}" clip-path="url(#type)">{esc(q)}</text>')
    s.add(f'<rect class="motion" x="{72 + cw * n + 4:.1f}" y="116" width="11" height="26" fill="{t["accent"]}">'
          f'<animate attributeName="opacity" values="1;0;1" dur="1.1s" repeatCount="indefinite"/></rect>')
    s.text(1132, 136, "Example", "mono", 15, t["graphite"], "end")
    y = 206
    for i, line in enumerate(answer):
        start = typing + 0.03 + i * 0.035
        s.add(f'<g opacity="1"><animate attributeName="opacity" values="0;0;1;1;0" keyTimes="0;{start:.3f};{start + 0.03:.3f};0.97;1" dur="{dur}s" repeatCount="indefinite"/>')
        s.text(48, y, line, "sans", 22, t["ink"])
        s.add("</g>")
        y += 33
    start = typing + 0.06 + len(answer) * 0.035
    s.add(f'<g><animate attributeName="opacity" values="0;0;1;1;0" keyTimes="0;{start:.3f};{start + 0.03:.3f};0.97;1" dur="{dur}s" repeatCount="indefinite"/>')
    x = 48
    s.text(x, y + 26, "Sources", "mono", 15, t["graphite"])
    x += width("Sources", "mono", 15) + 16
    for slug in ask["sources"]:
        label = f"/work/{slug}"
        w = width(label, "mono", 15) + 24
        s.add(f'<rect x="{x:.1f}" y="{y + 6}" width="{w:.1f}" height="30" rx="15" fill="none" stroke="{t["rule"]}"/>')
        s.text(x + 12, y + 26, label, "mono", 15, t["graphite"])
        x += w + 10
    s.add("</g>")
    s.text(1152, h - 34, "Ask your own question", "sansm", 20, t["accent"], "end")
    return s


def numbers(theme, items):
    s = Svg(1200, 176, theme, "; ".join(f"{v} {l}" for v, l in items))
    t = s.t
    s.card()
    cw = 1200 / len(items)
    for i, (value, label) in enumerate(items):
        x = i * cw + 34
        if i:
            s.add(f'<line x1="{i * cw:.1f}" y1="30" x2="{i * cw:.1f}" y2="146" stroke="{t["rule"]}"/>')
        s.text(x, 84, value, "serif", 54, t["ink"], attrs='letter-spacing="-1"')
        for j, line in enumerate(wrap(label, "sans", 17, cw - 60)[:2]):
            s.text(x, 118 + j * 23, line, "sans", 17, t["graphite"])
    return s


def credit_tag(p):
    c = p.get("credit")
    if not c:
        return "My own work"
    short = c["short"][0].upper() + c["short"][1:]
    return f"Mine · {c['short']}" if c["by"] == "mixed" else f"{short} · my idea and launch"


def where(p):
    out = []
    for l in p["links"]:
        h = l["href"]
        if h.startswith(SITE) or h.startswith(CONFIG["site"]):
            continue
        label = ("Code" if "github.com" in h else
                 "Android (closed testing)" if "play.google.com/apps/testing" in h else
                 "On Google Play" if "play.google.com/store" in h else
                 "On the Chrome Web Store" if "chromewebstore.google.com" in h else
                 "Demo on Hugging Face" if "huggingface.co/spaces" in h else "Web app")
        if label not in out:
            out.append(label)
    return out or ["Write-up on my site"]


def project_card(theme, p):
    s = Svg(600, 420, theme, f"{p['name']}: {p['impact']} ({credit_tag(p)})")
    t = s.t
    s.card()
    tag = credit_tag(p)
    own = not p.get("credit")
    tw = width(tag, "sansm", 15) + 28 + (12 if own else 0)
    s.add(f'<rect x="32" y="30" width="{tw:.1f}" height="32" rx="16" fill="{t["inset"]}" stroke="{t["rule"]}"/>')
    if own:
        s.add(f'<circle cx="47" cy="46" r="4" fill="{t["ink"]}"/>')
        s.text(58, 51, tag, "sansm", 15, t["ink"])
    else:
        s.text(46, 51, tag, "sansm", 15, t["graphite"])
    s.text(32, 116, p["name"], "serif", 42, t["ink"], attrs='letter-spacing="-0.5"')
    y = 154
    for line in wrap(p["impact"], "sans", 20, 536)[:3]:
        s.text(32, y, line, "sans", 20, t["graphite"])
        y += 28
    metrics = [m for m in p.get("metrics", [])][:2]
    shown = []
    for m in metrics:
        lines = wrap(m["label"], "sans", 16, 250)
        if len(lines) <= 3:
            shown.append((m["value"], lines))
    if shown:
        for i, (value, lines) in enumerate(shown):
            x = 32 + i * 272
            s.text(x, 290, value, "serif", 40, t["ink"], attrs='letter-spacing="-0.5"')
            for j, line in enumerate(lines):
                s.text(x, 316 + j * 20, line, "sans", 16, t["graphite"])
    else:
        x, yy = 32, 262
        for item in p["stack"][:7]:
            w = width(item, "sans", 15) + 26
            if x + w > 568:
                x, yy = 32, yy + 42
                if yy > 320:
                    break
            s.add(f'<rect x="{x:.1f}" y="{yy}" width="{w:.1f}" height="32" rx="16" fill="none" stroke="{t["rule"]}"/>')
            s.text(x + 13, yy + 21, item, "sans", 15, t["ink"])
            x += w + 8
    s.add(f'<line x1="32" y1="378" x2="568" y2="378" stroke="{t["rule"]}"/>')
    s.text(568, 405, "Case study", "sansm", 17, t["accent"], "end")
    # Cards with numbers list the stack here; cards that already show the stack as chips say where to find the project.
    foot = " · ".join(p["stack"]) if shown else " · ".join(where(p))
    s.text(32, 405, fit(foot, "sans", 16, 536 - width("Case study", "sansm", 17) - 24), "sans", 16, t["graphite"])
    return s


def toolkit(theme, groups):
    t = THEMES[theme]
    pad, gap, cols = 40, 36, 3
    colw = (1200 - 2 * pad - (cols - 1) * gap) / cols
    assisted = [g for g in groups if g["name"].lower().startswith("ai-assisted")]
    own = [g for g in groups if g not in assisted]

    def chips(items, maxw):
        rows, row, x = [], [], 0
        for it in items:
            w = width(it, "sans", 16) + 26
            if row and x + w > maxw:
                rows.append(row)
                row, x = [], 0
            row.append((it, x, w))
            x += w + 8
        if row:
            rows.append(row)
        return rows

    blocks = [(g["name"], chips(g["keywords"], colw)) for g in own]
    row_heights = []
    for r in range(0, len(blocks), cols):
        row_heights.append(max(46 + len(b[1]) * 42 for b in blocks[r:r + cols]))
    a_rows = [chips(g["keywords"], 1200 - 2 * pad) for g in assisted]
    h = 40 + sum(row_heights) + (len(row_heights) - 1) * 26
    if assisted:
        h += 40 + 62 + sum(len(r) * 42 for r in a_rows) + 6
    h += 34
    s = Svg(1200, int(h), theme, "Skills I use myself: " + "; ".join(f"{g['name']}: {', '.join(g['keywords'])}" for g in groups))
    s.card()
    y0 = 40
    for r, rh in enumerate(row_heights):
        for c, (name, rows) in enumerate(blocks[r * cols:(r + 1) * cols]):
            x0 = pad + c * (colw + gap)
            s.text(x0, y0 + 20, name, "sansm", 19, t["ink"])
            for i, row in enumerate(rows):
                for it, x, w in row:
                    yy = y0 + 38 + i * 42
                    s.add(f'<rect x="{x0 + x:.1f}" y="{yy}" width="{w:.1f}" height="33" rx="16.5" fill="{t["inset"]}" stroke="{t["rule"]}"/>')
                    s.text(x0 + x + 13, yy + 22, it, "sans", 16, t["ink"])
        y0 += rh + 26
    if assisted:
        s.add(f'<line x1="{pad}" y1="{y0 + 6}" x2="{1200 - pad}" y2="{y0 + 6}" stroke="{t["rule"]}"/>')
        y0 += 46
        g = assisted[0]
        s.text(pad, y0, g["name"], "sansm", 19, t["ink"])
        s.text(pad, y0 + 28, "How I ship with AI coding assistants: I decide what to build, test every feature and handle the launch; the assistant writes the code.", "sans", 16, t["graphite"])
        y0 += 48
        for rows in a_rows:
            for i, row in enumerate(rows):
                for it, x, w in row:
                    yy = y0 + i * 42
                    s.add(f'<rect x="{pad + x:.1f}" y="{yy}" width="{w:.1f}" height="33" rx="16.5" fill="none" stroke="{t["rule"]}" stroke-dasharray="4 3"/>')
                    s.text(pad + x + 13, yy + 22, it, "sans", 16, t["graphite"])
    return s


def footer(theme):
    s = Svg(1200, 150, theme, CONFIG["quote"])
    t = s.t
    s.add(f'<line x1="520" y1="28" x2="680" y2="28" stroke="{t["rule"]}"/>')
    s.text(600, 84, CONFIG["quote"], "serif", 34, t["ink"], "middle")
    s.text(600, 124, "This profile rebuilds itself every morning from sangamgupta.in.", "sans", 17, t["graphite"], "middle")
    return s


# ---------- data and checks ----------

def honest(text, corpus):
    """Every number written in config.json must also be in the site's data."""
    missing = [n for n in re.findall(r"\d[\d.,]*%?\+?", text) if n.rstrip(".,") not in corpus]
    if missing:
        sys.exit(f"config.json says {missing}, which the site's data doesn't: fix the text or the site first")


def main():
    resume = json.loads(get("/resume.json"))
    profile = resume["meta"]["profile"]
    corpus = json.dumps(resume, ensure_ascii=False)
    honest(CONFIG["intro"] + " " + CONFIG["ask"]["answer"], corpus)
    projects = {p["slug"]: p for p in profile["projects"]}
    featured = [projects[s] for s in CONFIG["featured"] if s in projects]
    for slug in CONFIG["ask"]["sources"]:
        if slug not in projects:
            sys.exit(f"ask source {slug} is not a project on the site")
    feed = get("/feed.xml")
    posts = len(re.findall(r"<item>", feed))

    links = [l["href"] for p in profile["projects"] for l in p["links"]]
    play = len({h for h in links if "play.google.com/store/apps/details" in h})
    chrome = len({h for h in links if "chromewebstore.google.com/detail" in h})
    pp = next((m for m in projects.get("profilepilot", {}).get("metrics", []) if "download" in m["label"]), None)
    site_tests = next((m for m in projects.get("sangamgupta-in", {}).get("metrics", []) if "test questions" in m["label"]), None)
    items = []
    if pp:
        items.append((pp["value"], "ProfilePilot downloads on Google Play"))
    if play:
        items.append((str(play), "apps on Google Play" if play > 1 else "app on Google Play"))
    if chrome:
        items.append((str(chrome), "extension on the Chrome Web Store" if chrome == 1 else "extensions on the Chrome Web Store"))
    items.append((str(posts), "posts on my blog"))
    if site_tests:
        items.append((site_tests["value"], "weekly test questions for my site's agent"))

    for theme in THEMES:
        write("header", theme, header(theme, resume, profile["availability"]))
        for l in CONFIG["links"]:
            write(f"link-{re.sub(r'[^a-z0-9]+', '-', l['label'].lower())}", theme, pill(theme, l["label"], l.get("primary")))
        write("ask", theme, ask_card(theme, projects))
        write("numbers", theme, numbers(theme, items))
        for p in featured:
            write(f"project-{p['slug']}", theme, project_card(theme, p))
        write("toolkit", theme, toolkit(theme, resume["skills"]))
        write("footer", theme, footer(theme))

    # README blocks that depend on the data: the project grid and the learning line.
    readme_path = os.path.join(ROOT, "README.md")
    readme = open(readme_path).read()
    rows = []
    for i in range(0, len(featured), 2):
        pair = featured[i:i + 2]
        rows.append("<p>\n" + "\n".join(picture(f"project-{p['slug']}", f"{p['name']}: {p['impact']} ({credit_tag(p)})", width="49%", href=p["caseStudy"]) for p in pair) + "\n</p>")
    blocks = {
        "PROJECTS": "\n".join(rows),
        "LEARNING": f"**Learning now:** {', '.join(profile['learning'])}.",
    }
    for name, body in blocks.items():
        pattern = re.compile(f"(<!-- {name}:START -->)[\\s\\S]*?(<!-- {name}:END -->)")
        if pattern.search(readme):
            readme = pattern.sub(lambda m: f"{m.group(1)}\n{body}\n{m.group(2)}", readme)
    open(readme_path, "w").write(readme)
    print(f"Built {len(os.listdir(OUT))} images from {SITE}: {len(featured)} projects, {posts} posts, {len(resume['skills'])} skill groups")


if __name__ == "__main__":
    main()
