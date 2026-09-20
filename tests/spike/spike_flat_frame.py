"""Spike harness: a FLAT frame — one Frame assembly, every timber a direct
member, bents as Std Groups (tree organisation only) — and whether
parametric bent spacing survives on it. Findings in
``docs/spike-flat-frame-results.md``.

**HISTORICAL — does not run against the current code.** This is round 1,
the version that drove spacing with the Assembly solver: closed loops of
Fixed joints returned a wrong answer at 4 bents and failed at 5, and even
loop-free the solver could not re-space 10. Workstream A removed
``assemble.py`` along with the whole Fixed-joint path, so this harness
has nothing left to call. It is kept as the record of what was measured
and why the solver was abandoned; to run it, check out a commit before
``assemble.py`` was deleted. Its successor is
``spike_expression_seat.py``.

Run with the bundled python (it reports with print)::

    <FreeCAD>/bin/python.exe tests/spike/spike_flat_frame.py [tree] N

``N`` is the bent count; ``tree`` leaves each bay's loop-closing tie
joint out of the solver (a timber joint with no Fixed assembly joint).
Builds the frame, edits ``Bay`` 10 ft -> 12 ft, solves, and reports the
solve status, the worst joint misfit and the bent positions.

Uses production modules but changes none — an evaluation only. The GUI
inspection file ``scratch/FlatFrame01.FCStd`` was built by calling
``build(doc, 3, tree=True)`` from a scripted FreeCAD GUI session, so
``apply.show_tip`` could make every Tip visible.
"""

import os
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "tests"))
import _repo_path  # noqa: E402
import FreeCAD as App  # noqa: E402

_repo_path.graft()

try:
    from freecad.bentwizard import assemble as asm_mod  # noqa: E402
except ImportError:                                     # pragma: no cover
    raise SystemExit(
        "spike_flat_frame is historical: it drives the Assembly solver "
        "through freecad/bentwizard/assemble.py, which workstream A "
        "removed with the rest of the Fixed-joint path. Check out a "
        "commit before that removal to run it, or use "
        "spike_expression_seat.py, which is how spacing works now.")

from freecad.bentwizard import apply as ap, joint_handle  # noqa: E402
from freecad.bentwizard.template import TemplateSpec  # noqa: E402
from freecad.bentwizard.timber import new_timber  # noqa: E402

LIB = os.path.join(REPO, "library", "Joint_HousedMT.FCStd")


def build(doc, n_bents=2, tree=False):
    """Posts 10 ft, beams = Span at PlateLine, two ties per bay = Bay at
    GirtLine. Joints are applied so each one attaches something new to
    what is already connected to the ground (post 1), which is what
    assimilate_joint's pre-seat needs."""
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
    serial = [0]

    def joint(host, face, station, mate, end):
        serial[0] += 1
        return ap.apply_joint(doc, spec, f"{serial[0]:03d}", {
            H: {"body": host, "face": face, "station": station},
            M: {"body": mate, "face": end}}).varset

    t0 = time.perf_counter()
    bents, ties, joints = [], [], []
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
    plan = []
    for i, (p1, p2, bm) in enumerate(bents):
        if i == 0:
            plan += [(p1, "YPos", "=<<ProjectVars>>.PlateLine", bm, "EndA"),
                     (p2, "YNeg", "=<<ProjectVars>>.PlateLine", bm, "EndB")]
        else:
            q1, q2, _ = bents[i - 1]
            t1, t2 = ties[i - 1]
            plan += [(q1, "XPos", "=<<ProjectVars>>.GirtLine", t1, "EndA"),
                     (p1, "XNeg", "=<<ProjectVars>>.GirtLine", t1, "EndB"),
                     (p1, "YPos", "=<<ProjectVars>>.PlateLine", bm, "EndA"),
                     (p2, "YNeg", "=<<ProjectVars>>.PlateLine", bm, "EndB"),
                     (q2, "XPos", "=<<ProjectVars>>.GirtLine", t2, "EndA"),
                     (p2, "XNeg", "=<<ProjectVars>>.GirtLine", t2, "EndB")]
    for k, step in enumerate(plan):
        vs = joint(*step)
        # the last joint of each bay closes a loop: both sides are
        # already connected to the ground
        closes_loop = tree and k >= 2 and (k - 2) % 6 == 5
        if closes_loop:
            doc.recompute()
            joint_handle.ensure_handle(vs)
        else:
            asm_mod.assimilate_joint(doc, vs)
        joints.append(vs)
    t_build = time.perf_counter() - t0
    timbers = [o for trio in bents for o in trio] + [t for pr in ties for t in pr]
    for body in timbers:
        ap.show_tip(body)           # GUI only; a no-op headless
    doc.recompute()
    return pv, frame, bents, joints, timbers, t_build


def report(frame, bents, joints):
    doc = frame.Document
    asms = [(a.Label, a.Placement.isIdentity()) for a in doc.Objects
            if a.TypeId == asm_mod.ASSEMBLY_TYPE]
    worst = max((asm_mod.joint_misfit(v) for v in joints), default=(0, 0))
    xs = [round(p1.getGlobalPlacement().Base.x / 25.4, 3) for p1, _, _ in bents]
    print(f"  assemblies (label, at identity): {asms}")
    print(f"  worst misfit: {worst[0]:.2e} mm / {worst[1]:.2e} deg over {len(joints)} joints")
    print(f"  bent X positions (in): {xs}")


def main(argv):
    n = int(argv[-1]) if argv and argv[-1].isdigit() else 2
    tree = "tree" in argv
    doc = App.newDocument("FlatFrame")
    pv, frame, bents, joints, timbers, t_build = build(doc, n, tree=tree)
    print(f"N={n} tree={tree}: {len(timbers)} timbers, {len(joints)} joints, "
          f"build {t_build:.0f}s")
    report(frame, bents, joints)
    pv.Bay = "12 ft"
    t0 = time.perf_counter()
    doc.recompute()
    status = frame.solve()
    doc.recompute()
    print(f"Bay 10 ft -> 12 ft: solve() = {status}, {time.perf_counter() - t0:.1f}s")
    report(frame, bents, joints)


if __name__ == "__main__":
    main(sys.argv[1:])
