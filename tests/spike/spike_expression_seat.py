"""Spike harness: bent spacing by EXPRESSION, not by the Assembly solver.

The flat frame of ``spike_flat_frame.py`` (one Frame assembly, bents and
bays as Std Groups), but with no Fixed assembly joints and no solve.
Every timber except the grounded first post is placed by an expression:
the timber joint that first connects it carries a ``SeatPlacement``
property computing the seat from its two datums, and the timber's
``Placement`` reads it::

    mate placed:  <<Host>>.Placement * HostPlacement * FLIP * minvert(MatePlacement)
    host placed:  <<Mate>>.Placement * MatePlacement * FLIP * minvert(HostPlacement)

— the same seat ``datums.seat_delta`` computes (FLIP = 180 deg about the
datum's Y, its own inverse), written where FreeCAD recomputes it. The
placing joints form a spanning tree from the grounded post; a joint
whose two timbers are already placed (the second tie of a bay) places
nothing and is only checked. A ``Bay`` edit is then a plain recompute.

Run with the bundled python (it reports with print)::

    <FreeCAD>/bin/python.exe tests/spike/spike_expression_seat.py N

Findings in ``docs/spike-flat-frame-results.md``. Uses production
modules but changes none.
"""

import os
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "tests"))
import _repo_path  # noqa: E402
import FreeCAD as App  # noqa: E402

_repo_path.graft()

from freecad.bentwizard import apply as ap, assemble as asm_mod, datums, joint_handle  # noqa: E402
from freecad.bentwizard.template import TemplateSpec  # noqa: E402
from freecad.bentwizard.timber import new_timber  # noqa: E402

LIB = os.path.join(REPO, "library", "Joint_HousedMT.FCStd")
FLIP = "placement(vector(0; 0; 0); rotation(vector(0; 1; 0); 180))"
SEAT_PROP = "SeatPlacement"


def seat_by_expression(varset, host_body, mate_body, placed):
    """Place whichever of the joint's two timbers is not yet placed, by
    an expression on a per-joint seat VarSet. Returns the timber placed,
    or None for a loop-closing joint (both already placed).

    The seat cannot live on the joint VarSet itself: FreeCAD's
    dependency graph is per object, and each timber's component bodies
    already read the joint VarSet (HostPlacement/MatePlacement), so the
    joint VarSet reading a timber's Placement is a cycle. The seat
    VarSet is read by the placed timber alone and reads the anchor
    timber and the two datums directly (a VarSet may link a datum; a
    Body may not — the scope rule)."""
    if mate_body not in placed:
        mover, anchor = mate_body, host_body
    elif host_body not in placed:
        mover, anchor = host_body, mate_body
    else:
        return None
    host_d, mate_d = _host_mate(varset)
    near, far = (host_d, mate_d) if anchor is host_body else (mate_d, host_d)
    doc = varset.Document
    seat = doc.addObject("App::VarSet", "Seat")
    seat.Label = f"Seat_{varset.Label}"
    seat.addProperty("App::PropertyPlacement", SEAT_PROP, "Seat",
                     "Where the timber this timber joint places sits, computed "
                     "from the two datums — the seat, as an expression.")
    seat.setExpression(SEAT_PROP, f"<<{anchor.Label}>>.Placement * <<{near.Label}>>.Placement"
                                  f" * {FLIP} * minvert(<<{far.Label}>>.Placement)")
    mover.setExpression("Placement", f"<<{seat.Label}>>.{SEAT_PROP}")
    # tree home: beside the joint's parameter VarSet, under its handle
    # (not a property OF the handle: deleting a handle must stay
    # harmless to geometry, and a nested VarSet survives it)
    joint_handle.find_handle(varset).addObject(seat)
    placed.add(mover)
    return mover


def build(doc, n_bents=2):
    spec = TemplateSpec(LIB)
    H, M = spec.host_role, spec.mate_role
    pv = doc.addObject("App::VarSet", "ProjectVars")
    pv.Label = "ProjectVars"
    for name, val, tip in (("Bay", "10 ft", "bent spacing = tie length"),
                           ("Span", "12 ft", "beam length"),
                           ("GirtLine", "48 in", "tie station on the posts"),
                           ("PlateLine", "84 in", "beam station on the posts")):
        pv.addProperty("App::PropertyLength", name, "Layout", tip)
        setattr(pv, name, val)
    frame = asm_mod.new_assembly(doc, "Frame-001", base="Frame")

    t0 = time.perf_counter()
    bents, ties = [], []
    for b in range(1, n_bents + 1):
        grp = frame.newObject("App::DocumentObjectGroup", "Bent")
        grp.Label = f"Bent-{b:03d}"
        p1, _ = new_timber(doc, f"T-Post-{2*b-1:03d}", "8 in", "8 in", "10 ft")
        p2, _ = new_timber(doc, f"T-Post-{2*b:03d}", "8 in", "8 in", "10 ft")
        bm, _ = new_timber(doc, f"T-Beam-{b:03d}", "6 in", "8 in", "=<<ProjectVars>>.Span")
        for o in (p1, p2, bm):
            grp.addObject(o)
        bents.append((p1, p2, bm))
    for b in range(1, n_bents):
        tg = frame.newObject("App::DocumentObjectGroup", "Bay")
        tg.Label = f"Bay-{b:03d}"
        pair = []
        for side in (1, 2):
            t, _ = new_timber(doc, f"T-Tie-{2*b-2+side:03d}", "6 in", "8 in",
                              "=<<ProjectVars>>.Bay")
            tg.addObject(t)
            pair.append(t)
        ties.append(pair)
    doc.recompute()

    asm_mod.ground(frame, bents[0][0])
    placed = {bents[0][0]}
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
    joints, closing = [], []
    for k, (host, face, station, mate, end) in enumerate(plan, 1):
        vs = ap.apply_joint(doc, spec, f"{k:03d}", {
            H: {"body": host, "face": face, "station": station},
            M: {"body": mate, "face": end}}).varset
        if seat_by_expression(vs, host, mate, placed) is None:
            closing.append(vs)
        joints.append(vs)
    doc.recompute()
    t_build = time.perf_counter() - t0
    timbers = [o for trio in bents for o in trio] + [t for pr in ties for t in pr]
    for body in timbers:
        ap.show_tip(body)           # GUI only; a no-op headless
    return pv, frame, bents, joints, closing, timbers, t_build


def report(doc, bents, joints, closing):
    worst = max((datums.misfit(*_host_mate(v)) for v in joints), default=(0, 0))
    worst_closing = max((datums.misfit(*_host_mate(v)) for v in closing), default=(0, 0))
    xs = [round(p1.getGlobalPlacement().Base.x / 25.4, 3) for p1, _, _ in bents]
    bad = [o.Label for o in doc.Objects
           if "Invalid" in o.State or "Error" in o.State or "Touched" in o.State]
    asms = [a.Placement.isIdentity() for a in doc.Objects
            if a.TypeId == asm_mod.ASSEMBLY_TYPE]
    print(f"  worst misfit, all {len(joints)} joints: {worst[0]:.2e} mm / {worst[1]:.2e} deg;"
          f" loop-closing {len(closing)}: {worst_closing[0]:.2e} mm")
    print(f"  bent X positions (in): {xs}")
    print(f"  assemblies at identity: {asms}; unhealthy objects: {bad[:5]}")


def _host_mate(varset):
    pair = datums.datums_of_joint(varset)
    host = datums.host_datum(varset)
    mate = pair[1] if host is pair[0] else pair[0]
    return host, mate


def main(argv):
    n = int(argv[-1]) if argv and argv[-1].isdigit() else 2
    doc = App.newDocument("ExprSeat")
    pv, frame, bents, joints, closing, timbers, t_build = build(doc, n)
    print(f"N={n}: {len(timbers)} timbers, {len(joints)} joints "
          f"({len(closing)} loop-closing), build {t_build:.1f}s")
    report(doc, bents, joints, closing)
    for value in ("12 ft", "8 ft"):
        pv.Bay = value
        t0 = time.perf_counter()
        doc.recompute()
        print(f"Bay -> {value}: recompute {time.perf_counter() - t0:.2f}s (no solve)")
        report(doc, bents, joints, closing)
    if len(argv) > 1 and argv[0].endswith(".FCStd"):
        pv.Bay = "10 ft"
        doc.recompute()
        doc.saveAs(argv[0])
        print(f"saved {argv[0]}")


if __name__ == "__main__":
    main(sys.argv[1:])
