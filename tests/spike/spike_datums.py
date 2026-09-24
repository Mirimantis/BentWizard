"""Spike: has 26.3 moved anything under the datums?

Brief section 3 (docs/freecad-26-3-compatibility-brief.md), "Datums":
`Part::LocalCoordinateSystem` placement and the child-axis scope
behaviour recorded in CLAUDE.md. Run on the 26.3 weekly and a 1.1.x
comparison build; a verdict that differs between them is the finding.

D1  the LCS itself: type, properties, child origin features (type, role)
D2  the child-axis scope failure behind Adam's second GUI round
    (`Link(s) to object(s) 'XZ_Plane005 ...' go out of the allowed
    scope`): a component Body whose Placement reads <<Datum>>.Placement
    DIRECTLY, created before and after the owning timber. Where are the
    datum's children filed, and does anything go Invalid? The
    production shape (a VarSet reads the datum, the Body reads the
    VarSet) is the control.
D3  what replaces getGlobalPlacement (deprecated 26.3, removed 27.2) for
    a datum in a Body in a Std Group: getGlobalPlacementOf with which
    root and subname, against the product of GeoFeatureGroup placements.

FreeCAD's console goes to stderr; each case prints a MARK line first so
the scope messages can be attributed. Run with the bundled python::

    <FreeCAD>/bin/python.exe tests/spike/spike_datums.py 2>&1
"""

import FreeCAD as App  # noqa: E402  FIRST: 26.3 strips names imported before it
import os  # noqa: E402
import sys  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "tests"))
import _repo_path  # noqa: E402

_repo_path.graft()

from freecad.bentwizard import datums  # noqa: E402
from freecad.bentwizard.timber import new_timber  # noqa: E402

V, R, P = App.Vector, App.Rotation, App.Placement


def mark(text):
    sys.stdout.flush()
    print(f"MARK: {text}", flush=True)
    sys.stderr.flush()


def build():
    ver = App.Version()
    return f"{ver[0]}.{ver[1]}.{ver[2]} git {ver[3] if len(ver) > 3 else '?'}"


def close(a, b, tol=1e-9):
    d = a.inverse().multiply(b)
    return d.Base.Length < tol and (abs(d.Rotation.Angle) < tol or
                                    abs(d.Rotation.Angle - 6.283185307179586) < tol)


# ---------------------------------------------------------------- D1
def d1():
    doc = App.newDocument("D1")
    body, _ = new_timber(doc, "T-Post-001", "8 in", "8 in", "96 in")
    d = datums.add_datum(body, "YPos", "48 in")
    print(f"  D1 datum TypeId {d.TypeId}, MapMode {d.MapMode!r}")
    print(f"  D1 properties: {sorted(d.PropertiesList)}")
    kids = getattr(d, "OriginFeatures", [])
    print(f"  D1 children: " + ", ".join(
        f"{k.Name}:{k.TypeId}:{getattr(k, 'Role', '?')}" for k in kids))
    print(f"  D1 child parent GeoFeatureGroup: "
          f"{sorted({(k.getParentGeoFeatureGroup() or doc).Name for k in kids})}")
    print(f"  D1 datum parent GeoFeatureGroup: {d.getParentGeoFeatureGroup().Name}")
    print(f"  D1 verify_datum: {datums.verify_datum(d) or 'clean'}")
    App.closeDocument(doc.Name)


# ---------------------------------------------------------------- D2
def health(doc):
    bad = [f"{o.Name}[{','.join(o.State)}]" for o in doc.Objects
           if {"Invalid", "Error", "Touched"} & set(o.State)]
    return bad or "all clean"


def filing(d):
    return sorted({(k.getParentGeoFeatureGroup().Name
                    if k.getParentGeoFeatureGroup() else "<root>")
                   for k in d.OriginFeatures})


def d2_case(tag, component_first, direct, boolean=False):
    mark(f"D2 {tag}")
    doc = App.newDocument("D2")
    comp = None
    if component_first:
        comp = doc.addObject("PartDesign::Body", "Comp")
    body, _ = new_timber(doc, "T-Beam-001", "6 in", "8 in", "144 in")
    d = datums.end_datum(body, "EndB")
    if comp is None:
        comp = doc.addObject("PartDesign::Body", "Comp")
    box = comp.newObject("PartDesign::AdditiveBox", "Box")
    box.Length = box.Width = box.Height = 10
    doc.recompute()
    if direct:
        comp.setExpression("Placement", f"<<{d.Label}>>.Placement")
    else:
        vs = doc.addObject("App::VarSet", "Acc")
        vs.addProperty("App::PropertyPlacement", "HostPlacement", "Accessors")
        vs.setExpression("HostPlacement", f"<<{d.Label}>>.Placement")
        comp.setExpression("Placement", "<<Acc>>.HostPlacement")
    if boolean:
        # Adam's shape: the component claimed by a Cut inside the timber
        from freecad.bentwizard.component import apply_boolean
        apply_boolean(body, comp, "Cutter")
    ok1 = doc.recompute()
    # an edit that recomputes the timber and its datum, as Adam's width edit did
    from freecad.bentwizard.timber import dims_varset
    dims_varset(body).WidthX = "7 in"
    ok2 = doc.recompute()
    in_list = [o.Name for o in d.InList]
    print(f"  D2 {tag}: datum InList {in_list}; children filed under "
          f"{filing(d)}; recompute -> {ok1}, {ok2}; {health(doc)}", flush=True)
    App.closeDocument(doc.Name)


def d2():
    d2_case("direct, component created FIRST", True, True)
    d2_case("direct, component created after", False, True)
    d2_case("control: through a VarSet, component FIRST", True, False)
    d2_case("control: through a VarSet, component after", False, False)
    d2_case("direct + Boolean, component FIRST", True, True, True)
    d2_case("direct + Boolean, component after", False, True, True)
    d2_case("control: VarSet + Boolean, component FIRST", True, False, True)
    d2_case("control: VarSet + Boolean, component after", False, False, True)


# ---------------------------------------------------------------- D3
def product_of_groups(obj):
    """What getGlobalPlacement computed: the GeoFeatureGroup chain."""
    plc = P(obj.Placement)
    grp = obj.getParentGeoFeatureGroup()
    while grp is not None:
        plc = grp.Placement.multiply(plc)
        grp = grp.getParentGeoFeatureGroup()
    return plc


def d3():
    doc = App.newDocument("D3")
    body, _ = new_timber(doc, "T-Post-001", "8 in", "8 in", "96 in")
    frame = doc.addObject("App::DocumentObjectGroup", "Frame")
    bent = doc.addObject("App::DocumentObjectGroup", "Bent")
    frame.addObject(bent)
    bent.addObject(body)
    body.Placement = P(V(100, -50, 20), R(V(1, 2, 3), 40))
    d = datums.add_datum(body, "XNeg", "30 in")
    doc.recompute()
    want = product_of_groups(d)
    gof = App.GeoFeature.getGlobalPlacementOf
    tries = {
        "(d, body, 'D.')": lambda: gof(d, body, d.Name + "."),
        "(d, frame, 'Bent.Body.D.')": lambda: gof(d, frame,
                                                  f"{bent.Name}.{body.Name}.{d.Name}."),
        "(d, d, '')": lambda: gof(d, d, ""),
        "(body, body, '')": lambda: gof(body, body, ""),
    }
    for name, fn in tries.items():
        try:
            got = fn()
            ref = want if "d," in name[:3] else body.Placement
            print(f"  D3 getGlobalPlacementOf{name}: "
                  f"{'== chain' if close(got, ref) else f'DIFFERS: {got}'}")
        except Exception as exc:
            print(f"  D3 getGlobalPlacementOf{name}: raised {exc}")
    print(f"  D3 chain product == body.Placement * d.Placement: "
          f"{close(want, body.Placement.multiply(d.Placement))}")
    App.closeDocument(doc.Name)


def main():
    print(f"FreeCAD {build()}  (python {sys.version.split()[0]})", flush=True)
    d1()
    d2()
    d3()


if __name__ == "__main__":
    main()
