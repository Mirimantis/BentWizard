"""Spike: how close to the 0.7 s floor can a Bay edit get?

FreeCAD's dependency graph is per OBJECT. A Bay edit recomputes 514 of
1676 objects because three objects each mix values with different
lifetimes. Split them, one level at a time, and re-measure:

  L1 baseline        - as built
  L2 project vars    - Bay on a VarSet of its own
  L3 + Dims split    - LengthZ moves to TLen_<timber>, leaving the
                       section (WidthX/WidthY) alone on TDim_<timber>
  L4 + accessors     - the joint VarSet keeps ONLY parameters; its eight
                       datum-reading accessors move to four per-joint
                       VarSets: Plc_<side> (that datum's Placement) and
                       Sec_<side> (that timber's section, read from the
                       Dims VarSet, not through the datum). A component
                       then reads: its own side's Plc, the parameters,
                       and the OTHER side's Sec - never the other
                       timber's datum or length.

  L5 + DepthW       - DepthW off the Sec VarSets: at an END datum it IS
                       the timber's length, so leaving it beside
                       WidthU/WidthV leaks the length into every reader
                       of the section. This is the level that pays.

Each level rewires the document that `spike_expression_seat.build`
produced, then profiles a `Bay` edit; geometry is re-verified after
every level (volumes back at `Bay` = 10 ft, every joint still seated,
one solid each). Findings in ``docs/spike-flat-frame-results.md``.

Run with the bundled python::

    <FreeCAD>/bin/python.exe tests/spike/spike_recompute_isolation.py N
"""

import os
import sys
import time
from collections import Counter

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "tests", "spike"))

import FreeCAD as App  # noqa: E402
import spike_expression_seat as es  # noqa: E402
from freecad.bentwizard import datums, naming  # noqa: E402

SIDES = ("Host", "Mate")
SECTION = ("WidthU", "WidthV", "DepthW")


class Timer:
    def __init__(self):
        self.events = []

    def slotRecomputedObject(self, obj):
        self.events.append((time.perf_counter(), obj))


def exprs(obj):
    return {p.lstrip("."): e for p, e in obj.ExpressionEngine}


def rewrite(doc, mapping):
    """Replace expression substrings document-wide."""
    for obj in doc.Objects:
        for path, expr in list(obj.ExpressionEngine):
            new = expr
            for old, repl in mapping.items():
                new = new.replace(old, repl)
            if new != expr:
                obj.setExpression(path, new)


def level2_project_vars(doc, pv):
    """Bay alone on its own VarSet."""
    bv = doc.addObject("App::VarSet", "BayVars")
    bv.Label = "BayVars"
    bv.addProperty("App::PropertyLength", "Bay", "Layout", "bent spacing = tie length")
    bv.Bay = pv.Bay
    rewrite(doc, {"<<ProjectVars>>.Bay": "<<BayVars>>.Bay"})
    pv.removeProperty("Bay")
    doc.recompute()
    return bv


def level3_dims_split(doc):
    """LengthZ onto TLen_<timber>; the section stays on TDim_<timber>."""
    made = 0
    for dims in [o for o in doc.Objects if o.TypeId == "App::VarSet"
                 and o.Label.startswith("TDim_")]:
        timber = dims.Label[len("TDim_"):]
        length = doc.addObject("App::VarSet", "TLen")
        length.Label = f"TLen_{timber}"
        length.addProperty("App::PropertyLength", "LengthZ", "Dims",
                           "Design length, bearing face to bearing face.")
        own = exprs(dims).get("LengthZ")
        if own:
            length.setExpression("LengthZ", own)
        else:
            length.LengthZ = dims.LengthZ
        rewrite(doc, {f"<<{dims.Label}>>.LengthZ": f"<<{length.Label}>>.LengthZ"})
        dims.removeProperty("LengthZ")
        made += 1
    doc.recompute()
    return made


def level4_accessor_split(doc, joints, pairs):
    """The joint VarSet keeps only parameters; Plc_<side>/Sec_<side>
    carry the datum placement and the timber's section."""
    made = 0
    for vs, (host, mate) in zip(joints, pairs):
        for side, datum in (("Host", host), ("Mate", mate)):
            de = exprs(datum)
            plc = doc.addObject("App::VarSet", "Plc")
            plc.Label = f"Plc_{side}_{vs.Label}"
            plc.addProperty("App::PropertyPlacement", "Placement", "Datums",
                            f"The {side.lower()} datum's placement.")
            plc.setExpression("Placement", f"<<{datum.Label}>>.Placement")
            sec = doc.addObject("App::VarSet", "Sec")
            sec.Label = f"Sec_{side}_{vs.Label}"
            for name in SECTION:
                sec.addProperty("App::PropertyLength", name, "Datums",
                                f"The {side.lower()} timber's {name}, at this datum.")
                # the datum's own binding: straight to the Dims/TLen VarSet,
                # so a station or a length change does not touch it
                if name in de:
                    sec.setExpression(name, de[name])
                else:
                    setattr(sec, name, getattr(datum, name))
            rewrite(doc, {f"<<{vs.Label}>>.{side}Placement": f"<<{plc.Label}>>.Placement",
                          **{f"<<{vs.Label}>>.{side}{n}": f"<<{sec.Label}>>.{n}"
                             for n in SECTION}})
            made += 2
        for side in SIDES:
            for name in (naming.PLACEMENT_ACCESSOR,) + SECTION:
                prop = side + name
                if hasattr(vs, prop):
                    vs.setExpression(prop, None)
                    vs.removeProperty(prop)
    doc.recompute()
    return made


def level5_depth_split(doc):
    """DepthW off the Sec VarSets. At an END datum DepthW *is* the
    timber's length, so leaving it beside WidthU/WidthV makes every
    reader of the section recompute on a length change — the same
    per-object leak one level down."""
    made = 0
    for sec in [o for o in doc.Objects if o.TypeId == "App::VarSet"
                and o.Label.startswith("Sec_")]:
        dep = doc.addObject("App::VarSet", "Dep")
        dep.Label = "Dep_" + sec.Label[len("Sec_"):]
        dep.addProperty("App::PropertyLength", "DepthW", "Datums",
                        "The timber's depth through this datum.")
        own = exprs(sec).get("DepthW")
        if own:
            dep.setExpression("DepthW", own)
        else:
            dep.DepthW = sec.DepthW
        rewrite(doc, {f"<<{sec.Label}>>.DepthW": f"<<{dep.Label}>>.DepthW"})
        sec.removeProperty("DepthW")
        made += 1
    doc.recompute()
    return made


def verify(doc, pairs, timbers, before=None):
    vols = [round(b.Shape.Volume, 6) for b in timbers]
    # pairs are cached up front: L4 removes the HostPlacement accessor
    # that datums.host_datum resolves the pairing through
    worst = max(datums.misfit(h, m)[0] for h, m in pairs)
    whole = all(len(b.Shape.Solids) == 1 for b in timbers)
    bad = [o.Label for o in doc.Objects
           if "Invalid" in o.State or "Error" in o.State or "Touched" in o.State]
    same = "n/a" if before is None else ("same" if vols == before else "CHANGED")
    print(f"   verify: volumes {same}, worst misfit {worst:.1e} mm, "
          f"all one solid {whole}, unhealthy {bad[:3]}")
    return vols


def profile(doc, var, value, label):
    t = Timer()
    App.addDocumentObserver(t)
    setattr(var[0], var[1], value)
    t0 = time.perf_counter()
    n = doc.recompute()
    dt = time.perf_counter() - t0
    App.removeDocumentObserver(t)
    kinds = Counter(o.TypeId.split("::")[-1] for _, o in t.events)
    heavy = {k: v for k, v in kinds.items() if k in ("Pad", "Boolean", "SketchObject")}
    print(f"{label}: {n} of {len(doc.Objects)} objects in {dt:.2f}s  "
          f"heavy: {heavy or 'none'}")
    return dt, n


def main(n_bents):
    doc = App.newDocument("Isolation")
    pv, frame, bents, joints, closing, timbers, tb = es.build(doc, n_bents)
    print(f"built {n_bents} bents: {len(timbers)} timbers, {len(joints)} joints, "
          f"{len(doc.Objects)} objects, {tb:.0f}s")
    pairs = [es._host_mate(v) for v in joints]
    # the baseline for "did the geometry change?" is taken at Bay = 10 ft,
    # the value every level returns to at the end
    base = verify(doc, pairs, timbers)
    var = (pv, "Bay")

    profile(doc, var, "12 ft", "L1 baseline               ")
    verify(doc, pairs, timbers, base)

    bv = level2_project_vars(doc, pv)
    var = (bv, "Bay")
    profile(doc, var, "8 ft", "L2 Bay on its own VarSet  ")
    verify(doc, pairs, timbers, base)

    made = level3_dims_split(doc)
    profile(doc, var, "12 ft", f"L3 + Dims split ({made} timbers)")
    verify(doc, pairs, timbers, base)

    made = level4_accessor_split(doc, joints, pairs)
    profile(doc, var, "8 ft", f"L4 + accessor split ({made} VarSets)")
    verify(doc, pairs, timbers, base)
    made = level5_depth_split(doc)
    profile(doc, var, "12 ft", f"L5 + DepthW split ({made} VarSets)")
    verify(doc, pairs, timbers, base)
    profile(doc, var, "8 ft", "L5 again (warm)           ")
    verify(doc, pairs, timbers, base)
    # geometry sanity at a common Bay: volumes must match the baseline's
    setattr(*var, "10 ft")
    doc.recompute()
    print("at Bay = 10 ft again:")
    verify(doc, pairs, timbers, base)
    print(f"objects now: {len(doc.Objects)}")


if __name__ == "__main__":
    main(int(sys.argv[-1]) if sys.argv[-1].isdigit() else 5)
