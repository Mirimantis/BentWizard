"""Spike: route (b) — components bound GLOBALLY, no UseLegacyBodyPlacement.

Builds the N-bent flat frame with production code (route (a)), records
volumes and solids, then converts it in place to route (b):

1. every timber gets a pose VarSet `TPos_<label>` (property
   `TimberPlacement`), nested in its Body like TDim_; whatever drove the
   Body's Placement (FrameOrigin, a seat, a literal) moves onto the pose,
   and the Body's Placement reads the pose;
2. every seat reads the anchor timber's POSE, never its Body;
3. every accessor reads `pose * datum`: HostPlacement =
   <<TPos_host>>.TimberPlacement * <<D_host>>.Placement;
4. every Boolean's UseLegacyBodyPlacement goes False.

Nothing may read a Body's Placement: a component of joint J on the host
reading the host Body is a cycle through the host's Boolean.

Then a Bay edit and a FrameOrigin move are measured on both forms (fresh
document each), with the set of objects recomputed.

Result (docs/spike-26-3-gui-results.md, finding 14): the conversion is
exact, but on route (b) a Bay edit or a FrameOrigin move leaves seated
timbers in two solids with nothing Touched. A Boolean runs before its
own Body, whose Placement expression is evaluated after its features, so
it resolves the moved component against the timber's old position — an
upstream defect of #30575, reproduced with stock objects. Uses production
modules but changes none.

    <FreeCAD>/bin/python.exe tests/spike/spike_route_b.py N
"""
import FreeCAD as App  # FIRST
import os
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "tests"))
import _repo_path  # noqa: E402

_repo_path.graft()

from freecad.bentwizard import apply as ap, datums, frame as fm, naming  # noqa: E402
from freecad.bentwizard.template import TemplateSpec  # noqa: E402
from freecad.bentwizard.timber import new_timber  # noqa: E402

LIB = os.path.join(REPO, "library", "Joint_HousedMT.FCStd")
POSE_PROP = "TimberPlacement"


class Recorder:
    def __init__(self):
        self.names = []

    def slotRecomputedObject(self, obj):
        self.names.append(obj.Name)


def build(doc, n_bents):
    spec = TemplateSpec(LIB)
    H, M = spec.host_role, spec.mate_role
    pv = fm.project_varset(doc)
    for name, val in (("Bay", "10 ft"), ("Span", "12 ft"),
                      ("GirtLine", "48 in"), ("PlateLine", "84 in")):
        pv.addProperty("App::PropertyLength", name, "Layout")
        setattr(pv, name, val)
    bents, ties = [], []
    for b in range(1, n_bents + 1):
        p1, _ = new_timber(doc, f"T-Post-{2*b-1:03d}", "8 in", "8 in", "10 ft")
        p2, _ = new_timber(doc, f"T-Post-{2*b:03d}", "8 in", "8 in", "10 ft")
        bm, _ = new_timber(doc, f"T-Beam-{b:03d}", "6 in", "8 in", "=<<ProjectVars>>.Span")
        bents.append((p1, p2, bm))
    for b in range(1, n_bents):
        pair = []
        for side in (1, 2):
            t, _ = new_timber(doc, f"T-Tie-{2*b-2+side:03d}", "6 in", "8 in",
                              "=<<ProjectVars>>.Bay")
            pair.append(t)
        ties.append(pair)
    doc.recompute()
    plan = []
    for i, (p1, p2, bm) in enumerate(bents):
        if i:
            q1, q2, _ = bents[i - 1]
            t1, t2 = ties[i - 1]
            plan += [(q1, "XPos", "=<<ProjectVars>>.GirtLine", t1, "EndA"),
                     (p1, "XNeg", "=<<ProjectVars>>.GirtLine", t1, "EndB")]
        plan += [(p1, "YPos", "=<<ProjectVars>>.PlateLine", bm, "EndA"),
                 (p2, "YNeg", "=<<ProjectVars>>.PlateLine", bm, "EndB")]
        if i:
            plan += [(q2, "XPos", "=<<ProjectVars>>.GirtLine", t2, "EndA"),
                     (p2, "XNeg", "=<<ProjectVars>>.GirtLine", t2, "EndB")]
    joints = []
    for k, (host, face, station, mate, end) in enumerate(plan, 1):
        doc.openTransaction("apply")
        vs = ap.apply_joint(doc, spec, f"{k:03d}", {
            H: {"body": host, "face": face, "station": station},
            M: {"body": mate, "face": end}}).varset
        fm.place_on_apply(doc, vs)
        doc.commitTransaction()
        joints.append(vs)
    doc.recompute()
    timbers = [o for trio in bents for o in trio] + [t for pr in ties for t in pr]
    return pv, timbers, joints


def pose_label(body):
    return f"TPos_{body.Label}"


def to_route_b(doc, timbers, joints):
    poses = {}
    for body in timbers:
        pose = doc.addObject("App::VarSet", "TPos")
        pose.Label = pose_label(body)
        pose.addProperty("App::PropertyPlacement", POSE_PROP, "Placement",
                         "Where this timber stands in the frame.")
        expr = fm.placement_expression(body)
        if expr:
            pose.setExpression(POSE_PROP, expr)
        else:
            setattr(pose, POSE_PROP, App.Placement(body.Placement))
        body.addObject(pose)
        poses[body.Name] = pose
    for body in timbers:
        body.setExpression("Placement", f"<<{pose_label(body)}>>.{POSE_PROP}")
    # seats read the anchor's pose
    for vs in joints:
        seat = fm.seat_of_joint(vs)
        if seat is None:
            continue
        for path, expr in seat.ExpressionEngine:
            new = expr
            for body in timbers:
                ref = f"{naming.label_ref(body.Label)}.Placement"
                if ref in new:
                    new = new.replace(ref, f"<<{pose_label(body)}>>.{POSE_PROP}")
            if new != expr:
                seat.setExpression(path, new)
    # accessors read pose * datum
    for vs in joints:
        holder = datums.accessors_varset(vs)
        host_d, mate_d = datums.datums_of_joint(vs)
        for side, d in (("Host", host_d), ("Mate", mate_d)):
            owner = datums.owner(d)
            holder.setExpression(
                naming.placement_accessor(side),
                f"<<{pose_label(owner)}>>.{POSE_PROP} * <<{d.Label}>>.Placement")
    n = 0
    for obj in doc.Objects:
        if obj.TypeId == "PartDesign::Boolean":
            obj.UseLegacyBodyPlacement = False
            n += 1
    return n


def state(timbers):
    out = {}
    for b in timbers:
        s = b.Shape
        out[b.Label] = (len(s.Solids), round(s.Volume, 3),
                        tuple(round(v, 4) for v in s.BoundBox.Center))
    return out


def bad(doc):
    return [o.Label for o in doc.Objects
            if "Invalid" in o.State or "Touched" in o.State or "Error" in o.State]


def edit(doc, setter):
    rec = Recorder()
    App.addDocumentObserver(rec)
    setter()
    t0 = time.perf_counter()
    doc.recompute()
    dt = time.perf_counter() - t0
    App.removeDocumentObserver(rec)
    return rec.names, dt


def kinds(doc, names):
    c = {}
    for n in names:
        t = doc.getObject(n).TypeId.split("::")[-1]
        c[t] = c.get(t, 0) + 1
    return c


def run(n, route):
    doc = App.newDocument(f"R{route}{n}")
    t0 = time.perf_counter()
    pv, timbers, joints = build(doc, n)
    t_build = time.perf_counter() - t0
    before = state(timbers)
    if route == "b":
        doc.openTransaction("route b")
        nb = to_route_b(doc, timbers, joints)
        doc.commitTransaction()
        doc.recompute()
        doc.recompute()
        after = state(timbers)
        diff = {k: (before[k], after[k]) for k in before if before[k] != after[k]}
        print(f"  route b: {nb} Booleans unflagged; changed timbers: {len(diff)}")
        for k, v in list(diff.items())[:6]:
            print(f"    {k}: {v[0]} -> {v[1]}")
    print(f"  build {t_build:.1f}s, objects {len(doc.Objects)}, bad {bad(doc)[:5]}")
    print(f"  solids != 1: {[k for k, v in state(timbers).items() if v[0] != 1]}")
    print(f"  worst misfit over every joint (mm): "
          f"{max(fm.joint_misfit(vs)[0] for vs in joints):.2e}")

    names, dt = edit(doc, lambda: setattr(pv, "Bay", "12 ft"))
    print(f"  Bay 10->12 ft: {len(names)} recomputed in {dt:.2f}s  {kinds(doc, names)}")
    print(f"    solids != 1: {[k for k, v in state(timbers).items() if v[0] != 1]}; bad {bad(doc)[:5]}")
    snap = state(timbers)
    names, dt = edit(doc, lambda: setattr(
        pv, "FrameOrigin", App.Placement(App.Vector(1000, 500, 0), App.Rotation(30, 0, 0))))
    print(f"  FrameOrigin move: {len(names)} recomputed in {dt:.2f}s  {kinds(doc, names)}")
    moved = state(timbers)
    vol_ok = all(abs(snap[k][1] - moved[k][1]) < 1e-3 and moved[k][0] == 1 for k in snap)
    print(f"    volumes kept, one solid each: {vol_ok}; bad {bad(doc)[:5]}")
    names, dt = edit(doc, lambda: setattr(joints[0], "TenonLength", "5 in")
                     if hasattr(joints[0], "TenonLength") else None)
    print(f"  joint 001 TenonLength edit: {len(names)} recomputed in {dt:.2f}s")
    App.closeDocument(doc.Name)


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    print(f"FreeCAD {App.Version()[:4]} {App.Version()[-1] if len(App.Version()) > 4 else ''}")
    for route in ("a", "b"):
        print(f"route ({route}), {n} bents")
        run(n, route)


main()
