"""Build the workbench and toolbar icons into freecad/bentwizard/resources/icons/.

Plain Python, no FreeCAD: every icon is drawn here from a few shared
primitives (a timber in oblique projection, badges, a datum triad), so
the set keeps one palette and one line weight. FreeCAD's artwork
conventions: a 64x64 SVG canvas, flat fills, a dark outline of the same
hue, nothing finer than a 2 px stroke, and the drawing filling the
canvas (it is read at 16-32 px). Every icon has to read on a dark theme
as well as a light one: no dark-only outline without a pale halo, no
transparency for a background copy.

The file name is the command's ID (`BentWizard_ApplyJoint.svg`), so the
commands find their icon by name. Run with any Python:

    python scripts/build_icons.py
"""

from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "freecad" / "bentwizard" / "resources" / "icons"

WOOD = {"top": "#f2c98a", "front": "#d99a45", "side": "#a96a28", "line": "#5c3a12"}
# a copy in the background: paler wood rather than transparency, which
# all but vanished on a dark theme
PALE = {"top": "#f8e6c8", "front": "#ecc995", "side": "#d2a46a", "line": "#8f6a3a"}
GREEN = ("#73d216", "#4e9a06")      # fill, outline: create
RED = ("#ef2929", "#a40000")        # remove
BLUE = ("#3465a4", "#204a87")       # save, move
INK = "#2e3436"
HALO = "#eeeeec"
END_BLUE = "#4a90d9"                # the face marks' end colour, darkened to read
FONT = "DejaVu Sans, Arial, Helvetica, sans-serif"


def _pts(points):
    return " ".join(f"{x:g},{y:g}" for x, y in points)


def poly(points, fill, stroke, width=2.0):
    return (f'<polygon points="{_pts(points)}" fill="{fill}" stroke="{stroke}" '
            f'stroke-width="{width:g}" stroke-linejoin="round"/>')


def line(x1, y1, x2, y2, stroke, width=2.0, extra=""):
    return (f'<line x1="{x1:g}" y1="{y1:g}" x2="{x2:g}" y2="{y2:g}" stroke="{stroke}" '
            f'stroke-width="{width:g}" stroke-linecap="round"{extra}/>')


def timber(x, y, w, h, d, grain=True, tone=WOOD):
    """A timber in oblique projection: front face (x, y, w, h), the top
    face and the right end receding up and to the right by `d`."""
    front = [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
    top = [(x, y), (x + d, y - d), (x + w + d, y - d), (x + w, y)]
    end = [(x + w, y), (x + w + d, y - d), (x + w + d, y + h - d), (x + w, y + h)]
    out = [poly(top, tone["top"], tone["line"]),
           poly(end, tone["side"], tone["line"]),
           poly(front, tone["front"], tone["line"])]
    faint = ' stroke-opacity="0.35"'
    if grain and w > 2.2 * h:          # a long stick: grain along it
        for f in (0.38, 0.68):
            gy = y + h * f
            out.append(line(x + 4, gy, x + w - 4, gy, tone["line"], 1, faint))
    elif grain and h > 2.2 * w:        # a post: grain up it
        for f in (0.38, 0.68):
            gx = x + w * f
            out.append(line(gx, y + 4, gx, y + h - 4, tone["line"], 1, faint))
    return "".join(out)


def bent(ox=0.0, oy=0.0, s=1.0, tone=WOOD):
    """Two posts and a beam: the workbench's own mark."""
    body = (timber(10, 22, 10, 36, 6, tone=tone) + timber(40, 22, 10, 36, 6, tone=tone)
            + timber(6, 12, 46, 10, 6, tone=tone))
    return f'<g transform="translate({ox:g},{oy:g}) scale({s:g})">{body}</g>'


def joint():
    """A post, and a beam whose tenon is about to enter it."""
    return (timber(4, 6, 16, 54, 6) + timber(26, 26, 7, 8, 4, grain=False)
            + timber(33, 22, 24, 16, 6))


def tenoned():
    """A timber with a tenon on its right end: a joint template."""
    return timber(2, 22, 34, 24, 8, grain=False) + timber(36, 28, 16, 12, 6, grain=False)


def badge(cx, cy, colours, glyph):
    fill, stroke = colours
    out = [f'<circle cx="{cx:g}" cy="{cy:g}" r="10" fill="{fill}" stroke="{stroke}" '
           f'stroke-width="2"/>']
    w = 'stroke="#ffffff" stroke-width="3" stroke-linecap="round" fill="none"'
    if glyph == "plus":
        d = f"M{cx - 5:g},{cy:g} H{cx + 5:g} M{cx:g},{cy - 5:g} V{cy + 5:g}"
    elif glyph == "cross":
        d = (f"M{cx - 4:g},{cy - 4:g} L{cx + 4:g},{cy + 4:g} "
             f"M{cx + 4:g},{cy - 4:g} L{cx - 4:g},{cy + 4:g}")
    else:                               # "save": an arrow down into a tray
        d = (f"M{cx:g},{cy - 6:g} V{cy + 1:g} M{cx - 4:g},{cy - 3:g} L{cx:g},{cy + 1:g} "
             f"L{cx + 4:g},{cy - 3:g} M{cx - 5:g},{cy + 5:g} H{cx + 5:g}")
    out.append(f'<path d="{d}" {w} stroke-linejoin="round"/>')
    return "".join(out)


def arrow(x1, y1, x2, y2, colour, width=3.0, head=5.0):
    """A line with a filled head at (x2, y2)."""
    dx, dy = x2 - x1, y2 - y1
    n = (dx * dx + dy * dy) ** 0.5
    ux, uy = dx / n, dy / n
    bx, by = x2 - ux * head * 1.4, y2 - uy * head * 1.4
    left = (bx - uy * head, by + ux * head)
    right = (bx + uy * head, by - ux * head)
    return line(x1, y1, bx, by, colour, width) + poly([(x2, y2), left, right], colour, colour, 1)


def tag(x, y, w, h, fill, text, size=11):
    return (f'<rect x="{x:g}" y="{y:g}" width="{w:g}" height="{h:g}" rx="3" '
            f'fill="{fill}" stroke="{INK}" stroke-width="1.5"/>'
            f'<text x="{x + w / 2:g}" y="{y + h / 2 + size * 0.36:g}" font-family="{FONT}" '
            f'font-size="{size:g}" font-weight="bold" fill="#ffffff" '
            f'text-anchor="middle">{text}</text>')


def magnifier(cx, cy):
    # a pale halo under the dark ring, so it reads on a dark theme too
    return (f'<circle cx="{cx:g}" cy="{cy:g}" r="13" fill="none" stroke="{HALO}" '
            f'stroke-width="7"/>'
            + line(cx + 9, cy + 9, cx + 17, cy + 17, HALO, 9)
            + f'<circle cx="{cx:g}" cy="{cy:g}" r="13" fill="#ffffff" fill-opacity="0.55" '
            f'stroke="{INK}" stroke-width="3.5"/>'
            + line(cx + 9, cy + 9, cx + 17, cy + 17, INK, 6))


def triad(ox, oy):
    """A datum's axes as FreeCAD colours them: X red, Y green, Z blue."""
    return (arrow(ox, oy, ox + 24, oy, "#cc0000")
            + arrow(ox, oy, ox, oy - 26, "#4e9a06")
            + arrow(ox, oy, ox - 14, oy + 14, "#3465a4")
            + f'<circle cx="{ox:g}" cy="{oy:g}" r="3" fill="{INK}"/>')


def variables_panel():
    out = [f'<rect x="4" y="5" width="56" height="54" rx="3" fill="#ffffff" '
           f'stroke="#555753" stroke-width="2"/>',
           f'<path d="M4,18 V8 a3,3 0 0 1 3,-3 H57 a3,3 0 0 1 3,3 V18 Z" '
           f'fill="{WOOD["front"]}" stroke="#555753" stroke-width="2"/>']
    for i, y in enumerate((24, 35, 46)):
        out.append(f'<rect x="10" y="{y:g}" width="9" height="8" fill="{WOOD["front"]}" '
                   f'stroke="{WOOD["line"]}" stroke-width="1"/>')
        bar = "#729fcf" if i == 2 else "#babdb6"   # the last row: a shared value
        out.append(f'<rect x="24" y="{y + 1.5:g}" width="{30 if i != 1 else 22:g}" '
                   f'height="5" rx="1" fill="{bar}"/>')
    return "".join(out)


ICONS = {
    "BentWizard": bent(),
    "BentWizard_NewTimber": timber(2, 22, 44, 20, 12) + badge(51, 51, GREEN, "plus"),
    "BentWizard_AddDatum": timber(2, 28, 46, 20, 12) + triad(22, 40),
    "BentWizard_ApplyJoint": joint(),
    "BentWizard_RemoveJoint": joint() + badge(51, 51, RED, "cross"),
    "BentWizard_DuplicateBent": bent(18, 0, 0.75, PALE) + bent(0, 16, 0.75),
    "BentWizard_AssembleTimbers": (timber(6, 38, 12, 22, 5) + timber(40, 38, 12, 22, 5)
                                   + timber(4, 8, 50, 11, 5)
                                   + arrow(30, 23, 30, 35, BLUE[0])),
    "BentWizard_ShowFaceMarks": (timber(2, 24, 38, 22, 10, grain=False)
                                 + tag(11, 28, 18, 15, WOOD["side"], "X", 13)
                                 + tag(41, 42, 21, 19, END_BLUE, "B", 15)),
    "BentWizard_AuditTimbers": timber(2, 34, 40, 18, 10) + magnifier(40, 24),
    "BentWizard_TimberVariables": variables_panel(),
    "BentWizard_NewJointTemplate": tenoned() + badge(51, 51, GREEN, "plus"),
    "BentWizard_SaveJointTemplate": tenoned() + badge(51, 51, BLUE, "save"),
}


def svg(body):
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" '
            f'viewBox="0 0 64 64">{body}</svg>\n')


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for name, body in ICONS.items():
        (OUT / f"{name}.svg").write_text(svg(body), encoding="utf-8")
    print(f"{len(ICONS)} icons written to {OUT}")


if __name__ == "__main__":
    main()
