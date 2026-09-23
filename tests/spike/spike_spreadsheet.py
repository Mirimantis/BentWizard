"""Spike: does 26.3 track a Spreadsheet per cell, as it does a VarSet per property?

Re-runs flat-frame finding 16 (docs/spike-flat-frame-results.md), which
on 1.1.3 found a `Spreadsheet::Sheet` to be one node in the dependency
graph, like a VarSet then — so a sheet was no better a home for the
framer's variables. 26.3 tracks VarSets per property (findings 1 and 13);
whether that reaches spreadsheet cells decides whether a sheet is a
usable place to keep layout variables. Three measurements, as before:

A. Two boxes reading two aliased cells: does editing one cell recompute
   the reader of the other?
B. The flat frame with its four layout variables moved from ProjectVars
   into aliased cells: a `Bay` edit, compared BY SET with the same edit
   through the VarSet on the same document.
C. Typing a note into an empty cell — the everyday edit that on 1.1.3
   cost a full frame recompute.

Each fine-grained setting gets a fresh document; the user's preference
is restored after. Run with the bundled python (N defaults to 5)::

    <FreeCAD>/bin/python.exe tests/spike/spike_spreadsheet.py N
"""

import FreeCAD as App  # noqa: E402  FIRST: 26.3 strips names imported before it
import os  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import spike_expression_seat as es  # noqa: E402
from spike_overlap_scale import PREF, PREF_PATH, edit, health  # noqa: E402

SHEET = "Layout"
VARIABLES = ("Bay", "Span", "GirtLine", "PlateLine")


def set_cell(doc, sheet, cell, content):
    """Write a cell and recompute; returns (Names recomputed, seconds) —
    `edit` works on properties, and a cell is not one."""
    from spike_overlap_scale import Recorder
    rec = Recorder()
    App.addDocumentObserver(rec)
    sheet.set(cell, content)
    t0 = time.perf_counter()
    doc.recompute()
    dt = time.perf_counter() - t0
    App.removeDocumentObserver(rec)
    return set(rec.names), dt


def labels(doc, names):
    return sorted(doc.getObject(n).Label for n in names if doc.getObject(n))


def toy(fine_grained):
    """A: two boxes, two aliased cells. C, at toy scale: a note."""
    App.ParamGet(PREF_PATH).SetBool(PREF, fine_grained)
    doc = App.newDocument("SheetToy")
    sh = doc.addObject("Spreadsheet::Sheet", "Sheet")
    sh.Label = SHEET
    for cell, alias, value in (("A1", "Bay", "=10 ft"), ("A2", "Span", "=12 ft")):
        sh.set(cell, value)
        sh.setAlias(cell, alias)
    doc.recompute()
    bb = doc.addObject("Part::Box", "BoxBay")
    bb.setExpression("Length", f"<<{SHEET}>>.Bay")
    bs = doc.addObject("Part::Box", "BoxSpan")
    bs.setExpression("Length", f"<<{SHEET}>>.Span")
    doc.recompute()
    bay, _ = set_cell(doc, sh, "A1", "=11 ft")
    note, _ = set_cell(doc, sh, "C5", "remember the sill")
    tag = "ON " if fine_grained else "OFF"
    print(f"  A {tag} edit Bay cell  -> {labels(doc, bay)}"
          f"   BoxSpan {'RECOMPUTED' if bs.Name in bay else 'untouched'}")
    print(f"  C {tag} note in C5     -> {labels(doc, note)}"
          f"   boxes {'RECOMPUTED' if {bb.Name, bs.Name} & note else 'untouched'}")
    App.closeDocument(doc.Name)


def frame(n_bents, fine_grained):
    """B and C at frame scale, VarSet then sheet, on one document."""
    App.ParamGet(PREF_PATH).SetBool(PREF, fine_grained)
    tag = "ON " if fine_grained else "OFF"
    doc = App.newDocument(f"SheetFrame{n_bents}")
    pv, _frame, _bents, joints, _closing, timbers, _tb = es.build(doc, n_bents)
    print(f"\n== fine-grained {tag} | {n_bents} bents | {len(doc.Objects)} objects ==")

    vs_set, vs_t = edit(doc, (pv, "Bay"), "12 ft")
    edit(doc, (pv, "Bay"), "10 ft")
    print(f"   B via VarSet : {len(vs_set):4d} objects  {vs_t:.2f} s")

    # move the four layout variables into aliased cells; FrameOrigin
    # stays on ProjectVars (it is a Placement, not a layout number)
    sh = doc.addObject("Spreadsheet::Sheet", "Sheet")
    sh.Label = SHEET
    for row, name in enumerate(VARIABLES, 1):
        sh.set(f"A{row}", f"={getattr(pv, name).UserString}")
        sh.setAlias(f"A{row}", name)
    doc.recompute()
    for obj in doc.Objects:
        for path, expr in list(obj.ExpressionEngine):
            new = expr
            for name in VARIABLES:
                new = new.replace(f"<<ProjectVars>>.{name}", f"<<{SHEET}>>.{name}")
            if new != expr:
                obj.setExpression(path, new)
    for name in VARIABLES:
        pv.removeProperty(name)
    doc.recompute()
    print(f"   moved to sheet: {health(doc, joints, timbers)}")

    sh_set, sh_t = set_cell(doc, sh, "A1", "=12 ft")      # A1 is Bay
    set_cell(doc, sh, "A1", "=10 ft")
    # both directions: EXTRA would be a cost, MISSING a correctness
    # problem — an object the edit needed that the sheet path skipped
    own = {sh.Name, pv.Name}
    extra = (sh_set - vs_set) - own
    missing = (vs_set - sh_set) - own
    print(f"   B via sheet  : {len(sh_set):4d} objects  {sh_t:.2f} s | "
          f"{len(extra)} more than the VarSet, {len(missing)} fewer"
          + (f"  extra e.g. {labels(doc, extra)[:4]}" if extra else "")
          + (f"  missing e.g. {labels(doc, missing)[:4]}" if missing else ""))

    note, note_t = set_cell(doc, sh, "C9", "remember the sill")
    print(f"   C note in C9 : {len(note):4d} objects  {note_t:.2f} s"
          + (f"  e.g. {labels(doc, note)[:4]}" if len(note) > 1 else ""))
    print(f"   after edits  : {health(doc, joints, timbers)}")
    App.closeDocument(doc.Name)
    return {"fg": fine_grained, "vs": len(vs_set), "vs_t": vs_t,
            "sh": len(sh_set), "sh_t": sh_t, "extra": len(extra),
            "missing": len(missing),
            "note": len(note), "note_t": note_t}


def main(argv):
    n = int(argv[-1]) if argv and argv[-1].isdigit() else 5
    v = App.Version()
    print(f"FreeCAD {'.'.join(v[:3])} build {v[3]}")
    param = App.ParamGet(PREF_PATH)
    had = PREF in param.GetBools()
    was = param.GetBool(PREF, True) if had else None
    try:
        print("\n-- toy: two boxes, two aliased cells --")
        toy(True)
        toy(False)
        rows = [frame(n, True), frame(n, False)]
    finally:
        if had:
            param.SetBool(PREF, was)
        else:
            param.RemBool(PREF)
    print(f"\n{'':4}{'VarSet Bay':>12}{'sheet Bay':>11}{'extra':>7}"
          f"{'missing':>9}{'note':>7}")
    for r in rows:
        print(f"{'ON ' if r['fg'] else 'OFF':>4}"
              f"{r['vs']:>6} {r['vs_t']:>4.2f}s{r['sh']:>6} {r['sh_t']:>4.2f}s"
              f"{r['extra']:>7}{r['missing']:>9}{r['note']:>7}")


if __name__ == "__main__":
    main(sys.argv[1:])
