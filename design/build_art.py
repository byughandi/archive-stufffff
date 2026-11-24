"""Builds the original SVG art for Grail Radar into web/public/art/.

Everything is composed by hand from primitives. Lettering is set in Archivo (SIL Open Font
License) and converted to outlines here, so the files carry no font dependency. No brand
logos, monograms or trademarked graphics appear anywhere.

Run: python design/build_art.py
"""
from __future__ import annotations

import math
from pathlib import Path

from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

ROOT = Path(__file__).resolve().parent.parent
FONT = ROOT / "web/node_modules/@fontsource-variable/archivo/files/archivo-latin-standard-normal.woff2"
OUT = ROOT / "web/public/art"
INK, PAPER, RED, GREY = "#000000", "#FFFFFF", "#D8232A", "#8C8C8C"
_fonts: dict[tuple, TTFont] = {}


def font(wdth: float, wght: float) -> TTFont:
    key = (wdth, wght)
    if key not in _fonts:
        _fonts[key] = instancer.instantiateVariableFont(TTFont(FONT), {"wdth": wdth, "wght": wght})
    return _fonts[key]


def text_path(text: str, size: float, wdth=62, wght=900, tracking=0.0) -> tuple[str, float]:
    """Return (svg path data with baseline at y=0 and origin x=0, advance width)."""
    f = font(wdth, wght)
    gs, cmap, upm = f.getGlyphSet(), f.getBestCmap(), f["head"].unitsPerEm
    s = size / upm
    x, parts = 0.0, []
    for ch in text:
        name = cmap.get(ord(ch))
        if name is None:
            x += size * 0.25
            continue
        pen = SVGPathPen(gs, lambda v: f"{v:.1f}")
        gs[name].draw(pen)
        d = pen.getCommands()
        if d:
            parts.append(f'<path transform="translate({x:.2f} 0) scale({s:.5f} {-s:.5f})" d="{d}"/>')
        x += gs[name].width * s + tracking
    return "".join(parts), x - tracking


def svg(w, h, body, title, extra=""):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" role="img" '
            f'aria-label="{title}"{extra}><title>{title}</title>{body}</svg>\n')


def write(name, content):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(content, encoding="utf-8")


def polar(cx, cy, r, deg):
    a = math.radians(deg)
    return cx + r * math.cos(a), cy - r * math.sin(a)


def wedge(cx, cy, r, a0, a1):
    x0, y0 = polar(cx, cy, r, a0)
    x1, y1 = polar(cx, cy, r, a1)
    return f"M{cx} {cy}L{x0:.2f} {y0:.2f}A{r} {r} 0 0 0 {x1:.2f} {y1:.2f}Z"


# ------------------------------------------------------------------ logo
def mark(size=64, ink=INK, paper=PAPER, red=RED):
    """The scope: a black disc, two rings, a hatched sweep, one red blip."""
    c, r = size / 2, size / 2
    sweep = "".join(
        f'<path d="M{c} {c}L{polar(c, c, r * 0.94, a)[0]:.2f} {polar(c, c, r * 0.94, a)[1]:.2f}" stroke="{paper}" '
        f'stroke-width="{size * 0.012:.2f}" opacity="{0.18 + i * 0.12:.2f}"/>'
        for i, a in enumerate(range(52, 100, 8)))
    bx, by = polar(c, c, r * 0.56, 30)
    lead = polar(c, c, r * 0.94, 100)
    return (f'<circle cx="{c}" cy="{c}" r="{r}" fill="{ink}"/>'
            f'<circle cx="{c}" cy="{c}" r="{r * 0.62:.2f}" fill="none" stroke="{paper}" stroke-width="{size * 0.022:.2f}" opacity=".55"/>'
            f'<circle cx="{c}" cy="{c}" r="{r * 0.30:.2f}" fill="none" stroke="{paper}" stroke-width="{size * 0.022:.2f}" opacity=".55"/>'
            f'{sweep}'
            f'<path d="M{c} {c}L{lead[0]:.2f} {lead[1]:.2f}" stroke="{paper}" stroke-width="{size * 0.04:.2f}" stroke-linecap="round"/>'
            f'<circle cx="{bx:.2f}" cy="{by:.2f}" r="{size * 0.085:.2f}" fill="{red}"/>')


def build_logo():
    write("logo-mark.svg", svg(64, 64, mark(64), "Grail Radar"))
    # Favicon: fewer details so it holds at 16 px.
    c = 32
    bx, by = polar(c, c, 18, 30)
    fav = (f'<circle cx="32" cy="32" r="32" fill="{INK}"/>'
           f'<circle cx="32" cy="32" r="20" fill="none" stroke="{PAPER}" stroke-width="3" opacity=".6"/>'
           f'<path d="M32 32L{polar(c, c, 30, 100)[0]:.1f} {polar(c, c, 30, 100)[1]:.1f}" stroke="{PAPER}" stroke-width="4" stroke-linecap="round"/>'
           f'<circle cx="{bx:.1f}" cy="{by:.1f}" r="8" fill="{RED}"/>')
    write("favicon.svg", svg(64, 64, fav, "Grail Radar"))
    # Wordmark: mark + lettering, tight, on one baseline.
    p1, w1 = text_path("GRAIL", 46, 62, 900, 0.4)
    p2, w2 = text_path("RADAR", 46, 62, 300, 0.4)
    x0 = 50
    body = (f'<g transform="translate(2 2) scale(.625)">{mark(64)}</g>'
            f'<g fill="{INK}" transform="translate({x0} 38)">{p1}</g>'
            f'<g fill="{INK}" transform="translate({x0 + w1 + 7:.1f} 38)">{p2}</g>')
    write("logo-wordmark.svg", svg(round(x0 + w1 + 7 + w2 + 2), 44, body, "Grail Radar"))


# ------------------------------------------------------------------ tier glyphs
def build_tiers():
    """Signal strength: S is a full blip with a halo, C is a faint contact, X is struck out."""
    def letter(ch, fill):
        d, w = text_path(ch, 22, 80, 800)
        return f'<g fill="{fill}" transform="translate({20 - w / 2:.2f} 27.8)">{d}</g>'
    glyphs = {
        "s": (f'<circle cx="20" cy="20" r="19" fill="none" stroke="{INK}" stroke-width="1.5"/>'
              f'<circle cx="20" cy="20" r="15.5" fill="{INK}"/>' + letter("S", PAPER), "S tier: grail"),
        "a": (f'<circle cx="20" cy="20" r="15.5" fill="{INK}"/>' + letter("A", PAPER), "A tier: heat"),
        "b": (f'<circle cx="20" cy="20" r="14.5" fill="{PAPER}" stroke="{INK}" stroke-width="2"/>' + letter("B", INK), "B tier: solid"),
        "c": (f'<circle cx="20" cy="20" r="14.5" fill="{PAPER}" stroke="{INK}" stroke-width="1.5" stroke-dasharray="2.6 3.2"/>'
              + letter("C", INK), "C tier: filler"),
        "x": (f'<circle cx="20" cy="20" r="14.5" fill="{PAPER}" stroke="{GREY}" stroke-width="1.5"/>' + letter("X", GREY)
              + f'<path d="M8.5 31.5L31.5 8.5" stroke="{GREY}" stroke-width="1.5"/>', "Rejected"),
    }
    for k, (body, title) in glyphs.items():
        write(f"tier-{k}.svg", svg(40, 40, body, title))


# ------------------------------------------------------------------ deal stamps
INK_FILTER = ('<defs><filter id="ink" x="-5%" y="-10%" width="110%" height="120%">'
              '<feTurbulence type="fractalNoise" baseFrequency=".9" numOctaves="2" seed="{seed}" result="n"/>'
              '<feDisplacementMap in="SourceGraphic" in2="n" scale="1.1" result="d"/>'
              '<feTurbulence type="fractalNoise" baseFrequency=".055 .16" numOctaves="2" seed="{seed2}" result="w"/>'
              '<feColorMatrix in="w" type="matrix" values="0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 -3.4 3.05" result="m"/>'
              '<feComposite in="d" in2="m" operator="in"/></filter>{more}</defs>')


def stamp(word, style, seed):
    size, pad_x, h = 30, 14, 46
    d, tw = text_path(word, size, 62, 900, 1.6)
    w = round(tw + pad_x * 2)
    more, deco = "", ""
    if style == "solid":            # steal: a full plate of red ink, lettering knocked out
        frame = f'<rect x="1.5" y="1.5" width="{w - 3}" height="{h - 3}" rx="5" fill="{RED}"/>'
        text_fill = PAPER
    elif style == "red":            # great: red double rule
        frame = (f'<rect x="2" y="2" width="{w - 4}" height="{h - 4}" rx="5" fill="none" stroke="{RED}" stroke-width="3"/>'
                 f'<rect x="6.5" y="6.5" width="{w - 13}" height="{h - 13}" rx="2.5" fill="none" stroke="{RED}" stroke-width="1"/>')
        text_fill = RED
    elif style == "ink":            # good: black double rule
        frame = (f'<rect x="2" y="2" width="{w - 4}" height="{h - 4}" rx="5" fill="none" stroke="{INK}" stroke-width="3"/>'
                 f'<rect x="6.5" y="6.5" width="{w - 13}" height="{h - 13}" rx="2.5" fill="none" stroke="{INK}" stroke-width="1"/>')
        text_fill = INK
    elif style == "thin":           # fair: one quiet rule
        frame = f'<rect x="1.5" y="1.5" width="{w - 3}" height="{h - 3}" rx="5" fill="none" stroke="{GREY}" stroke-width="1.5"/>'
        text_fill = GREY
    elif style == "struck":         # overpriced: grey, struck through
        frame = f'<rect x="1.5" y="1.5" width="{w - 3}" height="{h - 3}" rx="5" fill="none" stroke="{GREY}" stroke-width="1.5"/>'
        deco = f'<path d="M{pad_x - 5} {h / 2 + 1}H{w - pad_x + 5}" stroke="{GREY}" stroke-width="2.5"/>'
        text_fill = GREY
    else:                           # suspicious: hazard hatch border, no red on purpose
        more = (f'<pattern id="hz" width="9" height="9" patternUnits="userSpaceOnUse" patternTransform="rotate(-45)">'
                f'<rect width="4.5" height="9" fill="{INK}"/></pattern>')
        frame = (f'<rect x="1" y="1" width="{w - 2}" height="{h - 2}" rx="5" fill="url(#hz)"/>'
                 f'<rect x="6" y="6" width="{w - 12}" height="{h - 12}" rx="2" fill="{PAPER}"/>')
        text_fill = INK
    defs = INK_FILTER.format(seed=seed, seed2=seed + 11, more=more)
    body = (f'{defs}<g filter="url(#ink)">{frame}'
            f'<g fill="{text_fill}" transform="translate({pad_x} {h / 2 + size * 0.355:.2f})">{d}</g>{deco}</g>')
    return svg(w, h, body, word.capitalize())


def build_stamps():
    for i, (key, word, style) in enumerate([
        ("steal", "STEAL", "solid"), ("great", "GREAT", "red"), ("good", "GOOD", "ink"), ("fair", "FAIR", "thin"),
        ("overpriced", "OVERPRICED", "struck"), ("suspicious", "SUSPICIOUS", "hazard"), ("unknown", "NO COMPS", "thin"),
    ]):
        write(f"stamp-{key}.svg", stamp(word, style, 7 + i * 5))


# ------------------------------------------------------------------ line illustrations
STROKE = f'fill="none" stroke="{INK}" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"'


def hanger(x, y, s=1.0, tag=False):
    """A wire hanger hanging from a rail at (x, y)."""
    p = (f"M{x} {y}c0 {-7 * s} {9 * s} {-7 * s} {9 * s} 0c0 {6 * s} {-9 * s} {5 * s} {-9 * s} {13 * s}"
         f"l{-34 * s} {19 * s}c{-5 * s} {3 * s} {-3 * s} {7 * s} {2 * s} {7 * s}h{64 * s}c{5 * s} 0 {7 * s} {-4 * s} {2 * s} {-7 * s}l{-34 * s} {-19 * s}")
    out = f'<path d="{p}" {STROKE}/>'
    if tag:
        tx, ty = x + 20 * s, y + 39 * s
        out += (f'<path d="M{tx} {ty}v{14 * s}" {STROKE}/>'
                f'<rect x="{tx - 8 * s}" y="{ty + 14 * s}" width="{16 * s}" height="{24 * s}" rx="1.5" fill="{PAPER}" stroke="{INK}" stroke-width="1.6"/>'
                f'<circle cx="{tx}" cy="{ty + 19 * s}" r="{1.6 * s}" fill="{INK}"/>'
                f'<circle cx="{tx}" cy="{ty + 29 * s}" r="{3 * s}" fill="{RED}"/>')
    return out


def build_illustrations():
    # Empty feed: a rail with three bare hangers.
    rail = f'<path d="M14 26H226" {STROKE}/><path d="M24 26V14M216 26V14" {STROKE}/>'
    body = rail + hanger(44, 26) + hanger(116, 26, tag=True) + hanger(188, 26)
    write("empty-rack.svg", svg(240, 124, body, "An empty clothes rail"))

    # Empty watchlist: a swing tag on a looped string.
    tag = (f'<path d="M92 22c-22 -16 -44 6 -22 22c12 9 30 2 36 -8" {STROKE} stroke-dasharray="1 5"/>'
           f'<g transform="rotate(14 120 78)"><rect x="92" y="34" width="56" height="88" rx="3" fill="{PAPER}" stroke="{INK}" stroke-width="1.6"/>'
           f'<circle cx="120" cy="46" r="4" fill="none" stroke="{INK}" stroke-width="1.6"/>'
           f'<path d="M102 66H138M102 76H130M102 86H138" {STROKE} opacity=".35"/>'
           f'<circle cx="120" cy="104" r="7" fill="{RED}"/></g>')
    write("empty-watchlist.svg", svg(240, 140, tag, "A blank swing tag"))

    # Quiet source: a scope with a sweep and nothing on it.
    c = 70
    rings = "".join(f'<circle cx="120" cy="{c}" r="{r}" {STROKE} opacity="{o}"/>' for r, o in ((58, 1), (38, .45), (18, .45)))
    lx, ly = polar(120, c, 58, 62)
    quiet = (rings + f'<path d="M62 {c}H178M120 12V128" {STROKE} opacity=".18"/>'
             f'<path d="{wedge(120, c, 58, 62, 98)}" fill="{INK}" opacity=".07"/>'
             f'<path d="M120 {c}L{lx:.1f} {ly:.1f}" {STROKE}/>')
    write("empty-quiet.svg", svg(240, 140, quiet, "A radar scope with no contacts"))

    # Loading: the sweep turns, blips answer. (Inline it and gate the animation on reduced motion.)
    sx, sy = polar(32, 32, 28, 90)
    load = (f'<circle cx="32" cy="32" r="29" {STROKE}/><circle cx="32" cy="32" r="17" {STROKE} opacity=".35"/>'
            f'<g><path d="{wedge(32, 32, 28, 90, 140)}" fill="{INK}" opacity=".1"/>'
            f'<path d="M32 32L{sx:.1f} {sy:.1f}" {STROKE}/>'
            f'<animateTransform attributeName="transform" type="rotate" from="0 32 32" to="360 32 32" dur="1.6s" repeatCount="indefinite"/></g>'
            f'<circle cx="46" cy="22" r="3" fill="{RED}"><animate attributeName="opacity" values="0;1;0;0" keyTimes="0;.15;.6;1" dur="1.6s" begin=".2s" repeatCount="indefinite"/></circle>'
            f'<circle cx="20" cy="42" r="2.4" fill="{INK}"><animate attributeName="opacity" values="0;1;0;0" keyTimes="0;.15;.6;1" dur="1.6s" begin="1s" repeatCount="indefinite"/></circle>')
    write("loading-sweep.svg", svg(64, 64, load, "Loading"))

    # Alert icon: a contact with two signal arcs.
    alert = (f'<circle cx="8" cy="16" r="3.4" fill="{RED}"/>'
             f'<path d="M12.5 8.5a8.5 8.5 0 0 1 0 15" {STROKE}/><path d="M16.5 4.5a13.5 13.5 0 0 1 0 23" {STROKE}/>')
    write("icon-alert.svg", svg(32, 32, alert, "Alert"))

    # Halftone tile: placeholder ground for listings with no photo.
    dots = "".join(f'<circle cx="{x}" cy="{y}" r="{1.1 + ((x + y) % 12) * .07:.2f}"/>' for y in range(3, 24, 6) for x in range(3 if (y // 6) % 2 == 0 else 6, 24, 6))
    write("halftone.svg", svg(24, 24, f'<rect width="24" height="24" fill="#EDEDED"/><g fill="{INK}" opacity=".16">{dots}</g>', "Halftone"))


if __name__ == "__main__":
    build_logo()
    build_tiers()
    build_stamps()
    build_illustrations()
    print("wrote", len(list(OUT.glob("*.svg"))), "files to", OUT.relative_to(ROOT))
