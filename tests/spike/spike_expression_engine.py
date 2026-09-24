"""Spike: has 26.3 moved anything in the expression engine BentWizard is built on?

Brief section 3 (docs/freecad-26-3-compatibility-brief.md), "Expression
engine". The suite is green on 26.3, so the everyday paths work; this
probes the contract underneath them one clause at a time, each against a
value computed in Python rather than against another expression, so a
drift in the engine cannot agree with itself. Run it on the 26.3 weekly
and on a 1.1.x comparison build: a check whose verdict differs between
the two is the finding.

E1  minvert() is Placement.inverse()
E2  `*` on placements is Placement.multiply, left to right
E3  the seat's FLIP literal: placement(); rotation(); degrees; ';' vs ','
E4  <<Datum>>.Placement inside a moved Body is the LOCAL placement
E5  the whole seat, frame.py's own expression, seats exactly
E6  labels: every character naming.py says survives <<Label>>.Prop
    still does, and the reserved ones are still reserved
E7  relabel rewrites <<Label>> references (template_library, duplicate)
E8  cross-document copyObject: the bare Label.Prop rewrite apply matches
E9  ExpressionEngine path spellings the code lstrip('.')s
E10 PropertyLength clamps a negative literal, not an expression
E11 finding #15: undo restores an expression but not its dependency
E12 object-granular cycles: are property-disjoint cycles still refused?
    (why the seat and accessors are separate VarSets, and why datums
    never read each other)

Run with the bundled python::

    <FreeCAD>/bin/python.exe tests/spike/spike_expression_engine.py
"""

import FreeCAD as App  # noqa: E402  FIRST: 26.3 strips names imported before it
import os  # noqa: E402
import sys  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "tests"))
import _repo_path  # noqa: E402

_repo_path.graft()

from freecad.bentwizard import datums, frame, naming  # noqa: E402
from freecad.bentwizard.timber import new_timber  # noqa: E402

V, R, P = App.Vector, App.Rotation, App.Placement
RESULTS = []


def check(tag, ok, detail=""):
    verdict = {True: "PASS", False: "FAIL", None: "INFO"}[ok]
    RESULTS.append((tag, verdict, detail))
    print(f"  {verdict}  {tag}  {detail}", flush=True)


def close(a, b, tol=1e-9):
    """Two placements equal (q and -q are the same rotation)."""
    d = a.inverse().multiply(b)
    return d.Base.Length < tol and abs(d.Rotation.Angle) < tol or \
        abs(d.Rotation.Angle - 2 * 3.141592653589793) < tol


def build():
    ver = App.Version()
    return f"{ver[0]}.{ver[1]}.{ver[2]} git {ver[3] if len(ver) > 3 else '?'}"


def placements_vs(doc, label, **plcs):
    vs = doc.addObject("App::VarSet", "PV")
    vs.Label = label
    for name, plc in plcs.items():
        vs.addProperty("App::PropertyPlacement", name, "P")
        setattr(vs, name, plc)
    return vs


def result_vs(doc, expr):
    out = doc.addObject("App::VarSet", "Out")
    out.addProperty("App::PropertyPlacement", "Result", "P")
    out.setExpression("Result", expr)
    doc.recompute()
    return out


# ---------------------------------------------------------------- E1–E3
def e1_e3(doc):
    A = P(V(10, -20, 30), R(V(1, 2, 3), 37))
    B = P(V(-5, 7, 11), R(V(0, 1, -1), 110))
    C = P(V(1, 1, -4), R(V(3, -1, 2), -64))
    placements_vs(doc, "Src", PlcA=A, PlcB=B, PlcC=C)

    out = result_vs(doc, "minvert(<<Src>>.PlcA)")
    check("E1 minvert == inverse", close(out.Result, A.inverse()),
          f"got {out.Result}")

    out = result_vs(doc, "<<Src>>.PlcA * <<Src>>.PlcB * <<Src>>.PlcC")
    want = A.multiply(B).multiply(C)
    check("E2 A*B*C == A.multiply(B).multiply(C)", close(out.Result, want),
          "" if close(out.Result, want) else
          f"got {out.Result}; C·B·A would be "
          f"{close(out.Result, C.multiply(B).multiply(A))}")

    flip = P(V(), R(V(0, 1, 0), 180))
    out = result_vs(doc, frame.FLIP_EXPR)
    check("E3 FLIP_EXPR is 180 deg about Y", close(out.Result, flip),
          f"got {out.Result}")
    out = result_vs(doc, "rotation(vector(0; 1; 0); 90)")
    out2 = result_vs(doc, "placement(vector(0; 0; 0); rotation(vector(0; 1; 0); 90 deg))")
    check("E3 bare angle is degrees (== '90 deg')",
          close(out2.Result, P(V(), R(V(0, 1, 0), 90))), f"{out2.Result}")
    for sep_name, expr in (("','", "placement(vector(0, 0, 0), rotation(vector(0, 1, 0), 180))"),):
        try:
            out = result_vs(doc, expr)
            check(f"E3 {sep_name} as argument separator", None,
                  f"accepted -> {out.Result}")
        except Exception as exc:
            check(f"E3 {sep_name} as argument separator", None,
                  f"refused: {exc}")
    del out


# ---------------------------------------------------------------- E4–E5
def e4_e5(doc):
    host, _ = new_timber(doc, "T-Post.Balcony.001", "8 in", "8 in", "96 in")
    mate, _ = new_timber(doc, "T-Tie Ø <2-001", "6 in", "8 in", "144 in")
    doc.recompute()
    host.Placement = P(V(100, 200, 300), R(V(1, 1, 0), 33))
    near = datums.add_datum(host, "XPos", "48 in")
    far = datums.end_datum(mate, "EndA")
    doc.recompute()

    out = result_vs(doc, f"<<{near.Label}>>.Placement")
    glob = App.GeoFeature.getGlobalPlacementOf(near, host, near.Name + ".")
    check("E4 <<Datum>>.Placement is local, not global",
          close(out.Result, near.Placement) and not close(out.Result, glob),
          f"local={close(out.Result, near.Placement)} "
          f"global={close(out.Result, glob)}")

    seat = doc.addObject("App::VarSet", "Seat")
    seat.Label = "Seat_J-HousedMT-001"
    seat.addProperty("App::PropertyPlacement", frame.SEAT_PROP, "Seat")
    seat.setExpression(
        frame.SEAT_PROP,
        f"<<{host.Label}>>.Placement * <<{near.Label}>>.Placement"
        f" * {frame.FLIP_EXPR} * minvert(<<{far.Label}>>.Placement)")
    mate.setExpression("Placement", f"<<{seat.Label}>>.{frame.SEAT_PROP}")
    doc.recompute()
    mm, deg = datums.misfit(near, far)
    check("E5 frame.py's seat expression seats exactly",
          mm < 1e-6 and deg < 1e-6, f"misfit {mm:.2e} mm, {deg:.2e} deg")
    return host, mate, near, far, seat


# ---------------------------------------------------------------- E6
SURVIVORS = ["T-Post.Balcony.001", "T Post 001", "T-Post'1'", 'T-Post"1"',
             "T<Post", "T<<Post", "Poteau-Été-ØÅ-001", "柱-001", "T-(Post)+1",
             "T-Post#1", "T-Post$1", "T-Post=1", "123-Post", "T-Post,1"]
RESERVED = [">", "\\", ";", "\n"]


def e6():
    doc = App.newDocument("E6")   # fresh: a duplicate label would be renamed
    bad, escaped = [], []
    for i, label in enumerate(SURVIVORS):
        vs = doc.addObject("App::VarSet", f"L{i}")
        vs.Label = label
        vs.addProperty("App::PropertyLength", "L", "P")
        vs.L = 10 + i
        rd = doc.addObject("App::VarSet", f"R{i}")
        rd.addProperty("App::PropertyLength", "L", "P")
        try:
            if vs.Label != label:
                bad.append(f"{label!r} relabelled to {vs.Label!r}")
                continue
            rd.setExpression("L", f"<<{label}>>.L")
            doc.recompute()
            stored = rd.ExpressionEngine[0][1]
            if stored != f"{naming.label_ref(label)}.L":
                escaped.append(f"{label!r} stored as {stored!r}")
            if abs(rd.L.Value - (10 + i)) > 1e-9:
                bad.append(f"{label!r}: read {rd.L}")
        except Exception as exc:
            bad.append(f"{label!r}: {exc}")
    check("E6 labels naming.py says survive <<Label>>.Prop", not bad,
          "; ".join(bad) or f"all {len(SURVIVORS)}")
    check("E6 <<Label>> stored exactly as naming.label_ref writes it "
          "(finding 18: quotes escaped)", not escaped, "; ".join(escaped))

    still = []
    for i, ch in enumerate(RESERVED):
        label = f"T{ch}Post"
        vs = doc.addObject("App::VarSet", f"X{i}")
        vs.Label = label
        vs.addProperty("App::PropertyLength", "L", "P")
        vs.L = 5
        rd = doc.addObject("App::VarSet", f"Y{i}")
        rd.addProperty("App::PropertyLength", "L", "P")
        try:
            rd.setExpression("L", f"<<{vs.Label}>>.L")
            doc.recompute()
            works = abs(rd.L.Value - 5) < 1e-9
        except Exception:
            works = False
        if works:
            still.append(repr(ch))
    check("E6 reserved characters still break a reference", None,
          f"now WORK: {', '.join(still)}" if still else
          "all four still break (reservation still needed)")
    App.closeDocument(doc.Name)


# ---------------------------------------------------------------- E7
def e7(doc, host, mate, near, far, seat):
    old = far.Label
    far.Label = "D_Renamed_EndA"
    doc.recompute()
    expr = dict((p.lstrip("."), e) for p, e in seat.ExpressionEngine)[frame.SEAT_PROP]
    ok = "<<D_Renamed_EndA>>" in expr and f"<<{old}>>" not in expr
    mm, deg = datums.misfit(near, far)
    check("E7 relabel rewrites <<Label>> in a dependent expression",
          ok and mm < 1e-6, f"{expr!r}; misfit {mm:.1e}")
    seat.Label = "Seat_Renamed"
    doc.recompute()
    expr = frame.placement_expression(mate)
    check("E7 relabelling the seat rewrites the mover's binding",
          expr == f"<<Seat_Renamed>>.{frame.SEAT_PROP}", repr(expr))


# ---------------------------------------------------------------- E8
def e8():
    src = App.newDocument("E8Src")
    j = src.addObject("App::VarSet", "J")
    j.Label = "J-Kind-000"
    j.addProperty("App::PropertyLength", "Depth", "Joint")
    j.Depth = 7
    d = src.addObject("App::VarSet", "D")
    d.Label = "D_Template_EndB"
    d.addProperty("App::PropertyLength", "Wd", "P")
    d.Wd = 3
    box = src.addObject("Part::Box", "Box")
    box.setExpression("Length", "<<J-Kind-000>>.Depth + <<D_Template_EndB>>.Wd")
    src.recompute()
    dst = App.newDocument("E8Dst")
    # apply.py's shape: the VarSet and the reader together, the datum left behind
    copies = dst.copyObject([j, box], False)
    cbox = copies[1]
    expr = dict((p.lstrip("."), e) for p, e in cbox.ExpressionEngine).get("Length")
    check("E8 cross-doc copy: copied VarSet ref", None,
          f"copied VarSet labelled {copies[0].Label!r}; box reads {expr!r}")
    App.closeDocument(src.Name)
    App.closeDocument(dst.Name)


# ---------------------------------------------------------------- E9, E10
def e9_e10(doc):
    vs = doc.addObject("App::VarSet", "Paths")
    vs.addProperty("App::PropertyLength", "L", "P")
    vs.addProperty("App::PropertyLength", "Neg", "P")
    lcs = doc.addObject("Part::LocalCoordinateSystem", "LCS")
    lcs.setExpression("Placement.Base.z", "<<Paths>>.L")
    box = doc.addObject("Part::Box", "PBox")
    box.setExpression("Placement", "<<Paths>>.Placement")
    box.setExpression("Length", "<<Paths>>.L")
    doc.recompute()
    check("E9 ExpressionEngine path spellings", None,
          f"LCS {[p for p, _ in lcs.ExpressionEngine]}, "
          f"Box {[p for p, _ in box.ExpressionEngine]}")

    vs.Neg = -5
    lit = vs.Neg.Value
    vs.setExpression("Neg", "-5 mm")
    doc.recompute()
    check("E10 PropertyLength: literal clamps, expression does not",
          lit == 0 and vs.Neg.Value == -5,
          f"literal -> {lit}, expression -> {vs.Neg.Value}")


# ---------------------------------------------------------------- E11
def _undo_boxes(tag, delete):
    """Finding #15's own repro: bind Follower to Driver, delete `delete`
    in one transaction, undo, edit the driver. Live means 60."""
    doc = App.newDocument("E11")
    doc.UndoMode = 1
    driver = doc.addObject("Part::Box", "Driver")
    follower = doc.addObject("Part::Box", "Follower")
    follower.setExpression("Length", "Driver.Length * 2")
    doc.recompute()
    doc.openTransaction("delete")
    for name in delete:
        doc.removeObject(name)
    doc.commitTransaction()
    doc.undo()
    driver, follower = doc.getObject("Driver"), doc.getObject("Follower")
    driver.Length = 30
    doc.recompute()
    live = abs(follower.Length.Value - 60) < 1e-9
    in_list = "Follower" in [o.Name for o in driver.InList]
    check(tag, None,
          f"Follower.Length = {follower.Length.Value} (live: 60), in "
          f"Driver.InList: {in_list} -> "
          f"{'dependency survives' if live else 'BUG PRESENT: fossil'}")
    App.closeDocument(doc.Name)


def e11():
    _undo_boxes("E11a finding #15 repro: delete both, undo",
                ["Follower", "Driver"])
    _undo_boxes("E11b delete the carrier only, undo", ["Follower"])

    # the case that matters: undo Remove Timber Joint WITHOUT undo_repair
    from freecad.bentwizard import undo_repair
    from freecad.bentwizard.apply import apply_joint, remove_joint
    from freecad.bentwizard.template import TemplateSpec
    undo_repair.uninstall()
    doc = App.newDocument("E11c")
    doc.UndoMode = 1
    spec = TemplateSpec(os.path.join(REPO, "library", "Joint_HousedMT.FCStd"))
    doc.openTransaction("timbers")
    post, _ = new_timber(doc, "T-Post-001", "8 in", "8 in", "8 ft")
    girt, _ = new_timber(doc, "T-Girt-001", "6 in", "8 in", "6 ft")
    doc.commitTransaction()
    doc.openTransaction("apply")
    vs = apply_joint(doc, spec, "001", {
        spec.host_role: {"body": post, "face": "YPos", "station": "48 in"},
        spec.mate_role: {"body": girt, "face": "EndB"}}).varset
    doc.commitTransaction()
    jointed = post.Shape.Volume
    doc.openTransaction("remove")
    remove_joint(vs)
    doc.commitTransaction()
    doc.undo()
    doc.recompute()
    vs = doc.getObjectsByLabel("J-HousedMT-001")[0]
    post = doc.getObjectsByLabel("T-Post-001")[0]
    back = abs(post.Shape.Volume - jointed) < 1e-3
    vs.HousingDepth = "1 in"
    doc.recompute()
    live = post.Shape.Volume < jointed - 1
    check("E11c undo Remove Timber Joint, repair NOT installed", None,
          f"geometry back: {back}; HousingDepth edit reaches the post: "
          f"{live} -> {'dependency survives' if live else 'BUG PRESENT: fossil'}")
    App.closeDocument(doc.Name)


# ---------------------------------------------------------------- E12
def try_cycle(tag, doc, setup):
    try:
        setup()
        doc.recompute()
        bad = [o.Label for o in doc.Objects
               if "Invalid" in o.State or "Error" in o.State]
        check(tag, None, f"ACCEPTED; invalid after recompute: {bad or 'none'}")
    except Exception as exc:
        check(tag, None, f"refused: {str(exc).splitlines()[0][:140]}")


def e12():
    doc = App.newDocument("E12a")
    # names, not single letters: 'A' is the ampere and 'J' the joule
    a = doc.addObject("App::VarSet", "VsOne")
    b = doc.addObject("App::VarSet", "VsTwo")
    for o in (a, b):
        for n in ("PropX", "PropY"):
            o.addProperty("App::PropertyLength", n, "P")
    a.PropY, b.PropY = 3, 4

    def s():
        a.setExpression("PropX", "VsTwo.PropY")
        b.setExpression("PropX", "VsOne.PropY")
    try_cycle("E12a VsOne.X<-VsTwo.Y and VsTwo.X<-VsOne.Y (disjoint props)",
              doc, s)
    App.closeDocument(doc.Name)

    # the seat-on-the-joint-VarSet shape: a Body reads J.Param, J.Seat
    # reads that Body's Placement
    doc = App.newDocument("E12b")
    body, _ = new_timber(doc, "T-Post-001", "8 in", "8 in", "96 in")
    j = doc.addObject("App::VarSet", "JointVs")
    j.addProperty("App::PropertyLength", "Param", "Joint")
    j.addProperty("App::PropertyPlacement", "Seat", "Seat")
    j.Param = 50
    pad = next(o for o in body.Group if o.TypeId == "PartDesign::Pad")

    def s2():
        pad.setExpression("Length", "JointVs.Param * 20")
        j.setExpression("Seat", f"<<{body.Label}>>.Placement")
    try_cycle("E12b joint VarSet reads a timber that reads it", doc, s2)
    App.closeDocument(doc.Name)

    # two datums reading each other's accessor properties
    doc = App.newDocument("E12c")
    t1, _ = new_timber(doc, "T-A-001", "8 in", "8 in", "96 in")
    t2, _ = new_timber(doc, "T-B-001", "6 in", "8 in", "96 in")
    d1, d2 = datums.end_datum(t1, "EndB"), datums.end_datum(t2, "EndA")
    for d in (d1, d2):
        d.addProperty("App::PropertyLength", "MateWidthU", "Datum")

    def s3():
        d1.setExpression("MateWidthU", f"<<{d2.Label}>>.WidthU")
        d2.setExpression("MateWidthU", f"<<{d1.Label}>>.WidthU")
    try_cycle("E12c datums read each other's WidthU", doc, s3)
    App.closeDocument(doc.Name)


PREF_PATH = "User parameter:BaseApp/Preferences/General"
PREF = "FineGrainedRecompute"


def main():
    """Optional argument `on` / `off` forces 26.3's fine-grained
    recompute preference for the run (restored after); absent on 1.1.x."""
    print(f"FreeCAD {build()}", flush=True)
    print(f"  (python {sys.version.split()[0]})", flush=True)
    grp = App.ParamGet(PREF_PATH)
    saved = grp.GetBool(PREF, True) if PREF in grp.GetBools() else None
    if len(sys.argv) > 1:
        grp.SetBool(PREF, sys.argv[1] == "on")
    print(f"  fine-grained: {grp.GetBool(PREF, True) if PREF in grp.GetBools() else 'default'}",
          flush=True)
    try:
        doc = App.newDocument("ExprEngine")
        e1_e3(doc)
        e7(doc, *e4_e5(doc))
        e6()
        e9_e10(doc)
        App.closeDocument(doc.Name)
        e8()
        e11()
        e12()
    finally:
        if saved is None:
            grp.RemBool(PREF)
        else:
            grp.SetBool(PREF, saved)
    fails = [r for r in RESULTS if r[1] == "FAIL"]
    print(f"\n{len(RESULTS)} checks, {len(fails)} FAIL", flush=True)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
