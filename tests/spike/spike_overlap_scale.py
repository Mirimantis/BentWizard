"""Spike: is sharing a VarSet free on 26.3, and does it stay free at scale?

The compatibility brief's section 4 (docs/freecad-26-3-compatibility-brief.md).
Two questions, both about a `Bay` edit on the flat frame that
`spike_expression_seat.build` produces:

1. **Overlap.** On 1.1.3 a VarSet was one node in the dependency graph,
   so `Bay` sharing `ProjectVars` with `GirtLine`, `PlateLine` and
   `Span` meant a `Bay` edit also recomputed every reader of the other
   three (finding 15). 26.3's fine-grained recomputes track expression
   edges per property (finding 1), so the penalty should be zero — and
   the whole layout-variable design (group variables thematically, the
   way a framer expects) now rests on that. Measured by comparing the
   SET of objects a `Bay` edit recomputes with `Bay` shared (L1)
   against `Bay` on a VarSet of its own (L2). Equal counts could hide
   objects trading places; equal sets cannot.

2. **Scale.** Finding 3 found the recompute cost flat across B's split
   levels at five bents. Whether that holds at ten.

Each fine-grained setting gets a freshly built document, so nothing about
one run leaks into the other; the OFF column is the control that shows
the ON column is the feature and not the build. The user's own setting
is restored at the end.

B's L3-L5 rungs are gone on purpose: B is retired, and on current main
the accessors already live on their own VarSet, so `spike_recompute_
isolation`'s L4/L5 rewrite finds nothing to rewrite. That harness stays
as the record of what was measured before.

Run with the bundled python (N defaults to 5)::

    <FreeCAD>/bin/python.exe tests/spike/spike_overlap_scale.py N
"""

import FreeCAD as App  # noqa: E402  FIRST: 26.3 strips names imported before it
import os  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "tests", "spike"))

import spike_expression_seat as es  # noqa: E402
from freecad.bentwizard import datums  # noqa: E402

PREF_PATH = "User parameter:BaseApp/Preferences/General"
PREF = "FineGrainedRecompute"
OTHERS = ("GirtLine", "PlateLine", "Span")     # Bay's neighbours on ProjectVars


class Recorder:
    def __init__(self):
        self.names = []

    def slotRecomputedObject(self, obj):
        self.names.append(obj.Name)


def edit(doc, var, value):
    """Set var[0].var[1] = value, recompute, and return (set of object
    Names recomputed, seconds)."""
    rec = Recorder()
    App.addDocumentObserver(rec)
    setattr(var[0], var[1], value)
    t0 = time.perf_counter()
    doc.recompute()
    dt = time.perf_counter() - t0
    App.removeDocumentObserver(rec)
    return set(rec.names), dt


def direct_readers(doc, token):
    """Names of objects with an expression naming `token`."""
    return {o.Name for o in doc.Objects
            if any(token in e for _p, e in o.ExpressionEngine)}


def isolate_bay(doc, pv):
    """L2: Bay alone on a VarSet of its own."""
    bv = doc.addObject("App::VarSet", "BayVars")
    bv.Label = "BayVars"
    bv.addProperty("App::PropertyLength", "Bay", "Layout",
                   "bent spacing = tie length")
    bv.Bay = pv.Bay
    for obj in doc.Objects:
        for path, expr in list(obj.ExpressionEngine):
            if "<<ProjectVars>>.Bay" in expr:
                obj.setExpression(path, expr.replace("<<ProjectVars>>.Bay",
                                                     "<<BayVars>>.Bay"))
    pv.removeProperty("Bay")
    doc.recompute()
    return bv


def health(doc, joints, timbers):
    worst = max(datums.misfit(*es._host_mate(v))[0] for v in joints)
    whole = all(len(b.Shape.Solids) == 1 for b in timbers)
    bad = [o.Label for o in doc.Objects
           if {"Invalid", "Error", "Touched"} & set(o.State)]
    return f"misfit {worst:.1e} mm, one solid each {whole}, unhealthy {bad[:3] or 'none'}"


def run(n_bents, fine_grained):
    App.ParamGet(PREF_PATH).SetBool(PREF, fine_grained)
    tag = "ON " if fine_grained else "OFF"
    doc = App.newDocument(f"Overlap{tag.strip()}{n_bents}")
    t0 = time.perf_counter()
    pv, _frame, _bents, joints, _closing, timbers, _tb = es.build(doc, n_bents)
    built = time.perf_counter() - t0
    total = len(doc.Objects)
    print(f"\n== fine-grained {tag} | {n_bents} bents | {len(timbers)} timbers, "
          f"{len(joints)} joints, {total} objects, built in {built:.0f} s ==")
    print(f"   after build: {health(doc, joints, timbers)}")

    # who reads what, BEFORE anything is rewired
    reads_bay = direct_readers(doc, "<<ProjectVars>>.Bay")
    reads_others = set().union(*(direct_readers(doc, f"<<ProjectVars>>.{v}")
                                 for v in OTHERS))
    others_only = reads_others - reads_bay
    print(f"   direct readers: Bay {len(reads_bay)}, "
          f"{'/'.join(OTHERS)} {len(reads_others)} "
          f"({len(others_only)} of them read none of Bay)")

    # L1: Bay shared on ProjectVars. Edit away and back: a first
    # recompute can carry warm-up, the second is the steady state.
    l1a, t1a = edit(doc, (pv, "Bay"), "12 ft")
    l1b, t1b = edit(doc, (pv, "Bay"), "10 ft")
    leaked = others_only & l1a
    print(f"   L1 shared   : {len(l1a):4d} objects  {t1a:.2f} s | "
          f"back {len(l1b):4d}  {t1b:.2f} s | "
          f"readers of only {'/'.join(OTHERS)} recomputed: {len(leaked)}")

    # L2: Bay isolated
    bv = isolate_bay(doc, pv)
    l2a, t2a = edit(doc, (bv, "Bay"), "12 ft")
    l2b, t2b = edit(doc, (bv, "Bay"), "10 ft")
    print(f"   L2 isolated : {len(l2a):4d} objects  {t2a:.2f} s | "
          f"back {len(l2b):4d}  {t2b:.2f} s")

    # the overlap penalty, by set: everything L1 recomputed that L2 did
    # not, and vice versa, apart from the VarSet itself changing home
    varsets = {pv.Name, bv.Name}
    only_l1 = (l1a - l2a) - varsets
    only_l2 = (l2a - l1a) - varsets
    print(f"   overlap penalty: {len(only_l1)} objects recomputed only when "
          f"shared, {len(only_l2)} only when isolated"
          + (f"  e.g. {sorted(doc.getObject(n).Label for n in only_l1)[:4]}"
             if only_l1 else ""))
    print(f"   after edits: {health(doc, joints, timbers)}")
    App.closeDocument(doc.Name)
    return {"n": n_bents, "fg": fine_grained, "objects": total,
            "l1": len(l1a), "t1": t1b, "l2": len(l2a), "t2": t2b,
            "leaked": len(leaked), "only_l1": len(only_l1),
            "only_l2": len(only_l2)}


def main(argv):
    n = int(argv[-1]) if argv and argv[-1].isdigit() else 5
    v = App.Version()
    print(f"FreeCAD {'.'.join(v[:3])} build {v[3]} | {v[4:6]}")
    param = App.ParamGet(PREF_PATH)
    had = PREF in param.GetBools()
    was = param.GetBool(PREF, True) if had else None
    try:
        rows = [run(n, True), run(n, False)]
    finally:
        # never leave the user's preference changed
        if had:
            param.SetBool(PREF, was)
        else:
            param.RemBool(PREF)
    print(f"\n{'':4}{'bents':>6}{'objects':>9}{'L1 obj':>8}{'L1 s':>7}"
          f"{'L2 obj':>8}{'L2 s':>7}{'penalty':>9}")
    for r in rows:
        print(f"{'ON ' if r['fg'] else 'OFF':>4}{r['n']:>6}{r['objects']:>9}"
              f"{r['l1']:>8}{r['t1']:>7.2f}{r['l2']:>8}{r['t2']:>7.2f}"
              f"{r['only_l1']:>9}")


if __name__ == "__main__":
    main(sys.argv[1:])
