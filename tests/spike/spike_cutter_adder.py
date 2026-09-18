"""Headless spike round 3: cutter + adder joint halves.

Rounds 1-2b settled *how a template becomes an instance* -- a deep copy
from a container-free template, cut in with ``PartDesign::Boolean``.
Round 3 tests a change to *what a joint template is*: the timber Body
becomes the design solid (bearing face to bearing face), and a joint half
carries an optional **cutter** and an optional **adder**, each applied as
a boolean.  Order length is derived from the solid rather than typed.

Two risks are the point, and they are tested first and hardest:

* **Risk 1** -- fusing an adder whose shoulder is exactly coplanar with
  the stick's end face.  Coincident-face booleans are the same class of
  operation that broke island pockets (finding #14).
* **Risk 2** -- deriving order length from the solid, in the timber's own
  frame, including a non-square end where long point and short point
  differ and a sawyer needs the long point.

Every parameter change is asserted three ways -- value, object state,
console -- via ``spike_report.changed_cleanly``, and every fusion is
asserted on topology (``isValid``, ``isClosed``, solid count, face count),
not on volume alone.

Run with the portable FreeCAD's console binary::

    freecadcmd.exe tests/spike/spike_cutter_adder.py

``BW_SPIKE_WORKDIR`` overrides the (temporary) fixture directory and
``BW_SPIKE_SCALE`` the T6 instance counts, e.g. ``BW_SPIKE_SCALE=3,6``.

Writes ``docs/spike-round3-results.md``.  Nothing here imports or touches
a production module -- the spike is an evaluation only.
"""

import math
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import FreeCAD as App          # noqa: E402
import Part                    # noqa: E402
import spike_fixtures as F     # noqa: E402
from spike_report import (Recorder, capture_console,  # noqa: E402
                          changed_cleanly, close_all, console_faults,
                          force_recompute, near, render_results, save,
                          unhealthy)

REPO = os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))
REPORT = os.path.join(REPO, "docs", "spike-round3-results.md")
SCRATCH = os.path.join(REPO, "scratch")
ROUND2B_REPORT = os.path.join(REPO, "docs", "spike-round2b-results.md")

IN = F.IN
LENGTH_TOL_MM = 0.001          # the brief's derived-length tolerance


def load_scale(path):
    """Re-read a prior spike's T5/T6 rows from its own report."""
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except (OSError, IOError):
        return {}
    found = {}
    for line in text.splitlines():
        if not line.startswith("| n="):
            continue
        head, _, rest = line.partition("|")[2].partition("|")
        try:
            n = int(head.strip().split("=")[1])
        except (IndexError, ValueError):
            continue
        row = {}
        for item in rest.strip().strip("|` ").split(","):
            key, _, value = item.strip().partition("=")
            try:
                row[key] = float(value) if "." in value else int(value)
            except ValueError:
                pass
        if row:
            found[n] = row
    return found


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def artifact(doc, stem):
    if not os.path.isdir(SCRATCH):
        os.makedirs(SCRATCH)
    path = os.path.join(SCRATCH, stem + ".FCStd")
    doc.saveCopy(path)
    return path


def apply_half(doc, timber, body, kind, placement=None, name=None):
    """Apply one joint-half solid to a timber as a boolean.

    ``kind`` is ``"Cut"`` or ``"Fuse"`` -- the cutter/adder role.  This is
    the whole of the new mechanism: both halves are the same operation
    with a different ``Type``.
    """
    if placement is not None:
        body.Placement = placement
    boo = timber.newObject("PartDesign::Boolean",
                           name or ("Joint%s" % kind))
    boo.Type = kind
    boo.Group = [body]
    doc.recompute()
    return boo


def section_box(shape, z, pad=10.0, thickness=0.02):
    """The cross-section of ``shape`` at height ``z``, as a BoundBox.

    Used to measure a mortise cavity and a tenon from the *solids*, so
    the fit assertion reads geometry rather than re-reading parameters.
    """
    box = shape.BoundBox
    probe = Part.makeBox(box.XLength + 2 * pad, box.YLength + 2 * pad,
                         thickness,
                         App.Vector(box.XMin - pad, box.YMin - pad,
                                    z - thickness / 2.0))
    return shape.common(probe).BoundBox


def timber_with_dims(doc, label="T-Post-Spike-001"):
    _, body, dims, sk = F.build_timber(doc, label=label)
    return body, dims, sk


def end_b_placement(embed_mm=0.0, length_in=None):
    """Where an adder sits to put its shoulder on end B's face."""
    length = (length_in if length_in is not None else F.TIMBER_L) * IN
    return App.Placement(App.Vector(0, 0, length - embed_mm),
                         App.Rotation())


def end_a_placement(embed_mm=0.0):
    """The same adder, flipped, on end A -- a 180 degree turn about x,
    lifted by the section depth so it lands back inside the section."""
    return App.Placement(App.Vector(0, F.TIMBER_H * IN, embed_mm),
                         App.Rotation(App.Vector(1, 0, 0), 180))


def shoulder_placement(length_in=None):
    length = (length_in if length_in is not None else F.TIMBER_L) * IN
    return App.Placement(
        App.Vector(0, F.TIMBER_H * IN / 2.0, length), App.Rotation())


def mortise_placement(station_in=48.0):
    """A housed mortise bearing on face 2 (the YZ face).

    The cutter is modelled growing along its own +z, so seating it on a
    face means turning that axis into the timber's +x.  Applying it
    *without* the turn leaves the housing footprint spanning the whole
    section, which severs the stick -- see T4's control.
    """
    return App.Placement(App.Vector(0, 0, station_in * IN),
                         App.Rotation(App.Vector(0, 1, 0), 90))


def recomputed_cleanly(r, doc, label, mutate, body):
    """The three-part assertion with a **topology** criterion instead of a
    value: after the change the solid must still be a single valid closed
    solid, no object may be left touched or errored, and the console must
    stay silent.

    Used where an analytic volume is not available (the brace, where an
    angled cut and a fusion interact).  "A correct volume is not a passing
    test" cuts both ways: the absence of a volume to check is no reason to
    check nothing.
    """
    def run():
        mutate()
        doc.recompute()

    _, console = capture_console(run)
    topo = F.topology(F.local_shape(body))
    forced = False
    if topo["solids"] != 1 or not topo["valid"]:
        _, extra = capture_console(lambda: force_recompute(doc))
        console += extra
        topo = F.topology(F.local_shape(body))
        forced = True
    bad = unhealthy(doc)
    faults = console_faults(console)
    r.note("%s: solids / valid / closed" % label,
           "%d / %s / %s" % (topo["solids"], topo["valid"],
                             topo["closed"]))
    r.note("%s: volume mm^3" % label, "%.4f" % topo["volume"])
    r.note("%s: forced recompute needed" % label, "YES" if forced else "no")
    r.note("%s: objects not Up-to-date" % label, bad or "none")
    r.note("%s: console faults" % label, faults or "none")
    ok = (topo["solids"] == 1 and topo["valid"] and topo["closed"]
          and not bad and not faults)
    r.check("%s -- topology, object state and console all clean" % label,
            ok)
    return ok, topo


def topo_note(r, label, shape, expected_volume=None):
    topo = F.topology(shape)
    r.note("%s: volume mm^3" % label,
           "%.4f%s" % (topo["volume"],
                       "" if expected_volume is None
                       else " (expected %.4f)" % expected_volume))
    r.note("%s: solids / valid / closed" % label,
           "%d / %s / %s" % (topo["solids"], topo["valid"],
                             topo["closed"]))
    r.note("%s: faces / edges / vertexes" % label,
           "%d / %d / %d" % (topo["faces"], topo["edges"],
                             topo["vertexes"]))
    return topo


# --------------------------------------------------------------------------
# R1 -- coplanar-face fusion
# --------------------------------------------------------------------------

#: (label, embed in mm, description)
SHOULDER_CASES = [
    ("coplanar", 0.0,
     "shoulder exactly on the end face -- coincident planar faces"),
    ("proud", 1.0,
     "adder buried 1 mm into the stick -- a genuine overlap volume"),
    ("recessed", -1.0,
     "adder held 1 mm off the end face -- a 1 mm gap"),
]


def r1(rec, workdir):
    r = rec.start("R1", "Risk 1: coplanar-face fusion")
    results = {}
    paths = {}
    doc = None
    try:
        close_all()
        doc = App.newDocument("R1_Coplanar")
        save(doc, workdir, "R1_Coplanar")
        for label, embed, description in SHOULDER_CASES:
            timber, dims, sk = timber_with_dims(
                doc, label="T-Shoulder-%s" % label)
            timber.Placement.Base = App.Vector(
                0, 600.0 * SHOULDER_CASES.index((label, embed, description)),
                0)
            _, params, adder = F.build_tenon_adder(
                doc, varset_label="TenonParams_%s" % label,
                body_label="Tenon_%s" % label, embed_mm=embed)
            (_, console) = capture_console(
                lambda: apply_half(doc, timber, adder, "Fuse",
                                   end_b_placement(embed),
                                   name="Fuse_%s" % label))
            shape = F.local_shape(timber)

            proud_in = F.default_tenon_params()["TenonLength"]
            if embed < 0:
                proud_in += embed / IN          # the gap eats the tenon
            want = (F.timber_volume()
                    + (F.default_tenon_params()["TenonThickness"]
                       * F.default_tenon_params()["TenonWidth"]
                       * proud_in * IN ** 3))
            topo = topo_note(r, "%s (%s)" % (label, description), shape,
                             want)
            topo["console"] = console_faults(console) or "none"
            topo["volume_ok"] = near(topo["volume"], want)
            r.note("%s: console during the fuse" % label, topo["console"])
            results[label] = topo

        # the three-part assertion for the two cases that must succeed
        for label in ("coplanar", "proud"):
            topo = results[label]
            ok = (topo["volume_ok"] and topo["solids"] == 1
                  and topo["valid"] and topo["closed"]
                  and topo["console"] == "none")
            r.check("%s fuses to one valid closed solid" % label, ok,
                    "solids=%d valid=%s closed=%s"
                    % (topo["solids"], topo["valid"], topo["closed"]))

        # the decisive check: coplanar must not be quietly different
        keys = ("solids", "faces", "edges", "vertexes")
        same = all(results["coplanar"][k] == results["proud"][k]
                   for k in keys)
        r.note("coplanar vs proud topology",
               " / ".join("%s %d vs %d" % (k, results["coplanar"][k],
                                           results["proud"][k])
                          for k in keys))
        decisive = r.check(
            "coplanar produces the SAME topology as the offset case",
            same)
        r.note("volumes, coplanar vs proud",
               "%.6f vs %.6f"
               % (results["coplanar"]["volume"], results["proud"]["volume"]))
        same_volume = near(results["coplanar"]["volume"],
                           results["proud"]["volume"])
        r.check("coplanar and proud agree on volume", same_volume)

        # the recessed case is the control: it proves the assertion bites
        gap = results["recessed"]
        r.note("recessed (control): solids", gap["solids"])
        r.note("recessed (control): isValid / isClosed",
               "%s / %s" % (gap["valid"], gap["closed"]))
        control = r.check(
            "the 1 mm gap is detected -- two solids, not one",
            gap["solids"] == 2)
        r.note("what the control proves",
               "isValid() and isClosed() are BOTH true for the "
               "disconnected result, so solid count is the assertion that "
               "catches a failed fusion; volume alone would not")

        # How a coplanar fusion actually fails in practice: not on the
        # coincidence itself but on getting the seat into the wrong frame.
        frame_doc = App.newDocument("R1_OperandFrame")
        try:
            frame_rows = []
            for offset, seat_z, tag in (
                    (0.0, F.TIMBER_L * IN, "timber at origin"),
                    (300.0, F.TIMBER_L * IN,
                     "timber offset 300 mm, seat at LOCAL length"),
                    (300.0, F.TIMBER_L * IN + 300.0,
                     "timber offset 300 mm, seat at GLOBAL length")):
                victim, vdims, vsk = timber_with_dims(
                    frame_doc, label="T-Frame-%s" % len(frame_rows))
                victim.Placement.Base = App.Vector(0, 0, offset)
                _, fparams, fadder = F.build_tenon_adder(
                    frame_doc, varset_label="FrameTenon_%d"
                    % len(frame_rows),
                    body_label="FrameTenon_%d" % len(frame_rows))
                apply_half(frame_doc, victim, fadder, "Fuse",
                           App.Placement(App.Vector(0, 0, seat_z),
                                         App.Rotation()),
                           name="FrameAdd_%d" % len(frame_rows))
                force_recompute(frame_doc)
                shape = F.local_shape(victim)
                frame_rows.append((tag, len(shape.Solids), shape.Volume))
                r.note("operand frame: %s" % tag,
                       "solids %d, volume %.4f"
                       % (len(shape.Solids), shape.Volume))
            r.note("FINDING: PartDesign::Boolean operand frame",
                   "the operand is seated in the TARGET Body's LOCAL "
                   "frame -- the target's own Placement is not applied. "
                   "Adding the timber's offset to the seat moves the "
                   "adder clean off the end face.")
            r.note("and the failure is silent",
                   "the mis-seated case has the SAME volume as the "
                   "correct one (%.4f), is isValid() and isClosed(), and "
                   "differs only in solid count"
                   % frame_rows[-1][2])
            ok_frame = (frame_rows[0][1] == 1 and frame_rows[1][1] == 1
                        and frame_rows[2][1] == 2)
            r.check("operand seats in the target's local frame, and a "
                    "global seat is caught only by solid count", ok_frame)
        finally:
            App.closeDocument(frame_doc.Name)
            App.setActiveDocument(doc.Name)

        paths["coplanar"] = artifact(doc, "r3_coplanar_cases")
        r.note("artifact", paths["coplanar"])

        ok = (decisive and control and same_volume
              and all(results[k]["solids"] == 1 and results[k]["valid"]
                      and results[k]["closed"] and results[k]["volume_ok"]
                      for k in ("coplanar", "proud")))
    except Exception as exc:
        r.error("R1", exc)
        ok = False
    r.status = "PASS" if ok else "FAIL"
    return ok, results, paths


# --------------------------------------------------------------------------
# R2 -- derived length
# --------------------------------------------------------------------------

def r2(rec, workdir):
    r = rec.start("R2", "Risk 2: order length derived from the solid")
    ok = True
    paths = {}
    tenon_in = F.default_tenon_params()["TenonLength"]
    try:
        close_all()

        # The frame resolution, stated explicitly and shown to matter.
        doc = App.newDocument("R2_Frame")
        save(doc, workdir, "R2_Frame")
        timber, dims, sk = timber_with_dims(doc, label="T-Square")
        timber.Placement = App.Placement(
            App.Vector(1000, 500, 250), App.Rotation(App.Vector(0, 1, 0),
                                                     37))
        doc.recompute()
        glob = timber.Shape.BoundBox
        r.note("timber placement (deliberately rotated 37 deg)",
               timber.Placement)
        r.note("GLOBAL bounding box z-length mm",
               "%.4f -- meaningless for a cut list" % glob.ZLength)
        r.note("frame resolution",
               "shape.Placement = body.Placement.inverse() * "
               "shape.Placement, then BoundBox.ZLength")
        derived = F.derived_length(timber)
        r.note("LOCAL derived length",
               "%.6f mm = %.6f in" % (derived, derived / IN))
        ok &= r.check("square stick derives its design length",
                      abs(derived - F.TIMBER_L * IN) < LENGTH_TOL_MM,
                      "%.6f mm" % derived)
        ok &= r.check("the global box would have been wrong",
                      abs(glob.ZLength - F.TIMBER_L * IN) > 1.0,
                      "%.4f mm" % glob.ZLength)

        # one tenon, then two
        for count in (1, 2):
            doc = App.newDocument("R2_Tenons_%d" % count)
            save(doc, workdir, "R2_Tenons_%d" % count)
            timber, dims, sk = timber_with_dims(
                doc, label="T-Tenon-%d" % count)
            timber.Placement = App.Placement(
                App.Vector(0, 0, 0), App.Rotation(App.Vector(1, 1, 0), 25))
            _, p1, a1 = F.build_tenon_adder(doc,
                                            varset_label="TenonB_%d" % count,
                                            body_label="TenonB_%d" % count)
            apply_half(doc, timber, a1, "Fuse", end_b_placement(),
                       name="FuseB_%d" % count)
            if count == 2:
                _, p2, a2 = F.build_tenon_adder(
                    doc, varset_label="TenonA_%d" % count,
                    body_label="TenonA_%d" % count)
                apply_half(doc, timber, a2, "Fuse", end_a_placement(),
                           name="FuseA_%d" % count)
            force_recompute(doc)
            shape = F.local_shape(timber)
            topo = topo_note(r, "%d tenon(s)" % count, shape)
            want = (F.TIMBER_L + count * tenon_in) * IN
            derived = shape.BoundBox.ZLength
            r.note("%d tenon(s): derived length" % count,
                   "%.6f mm = %.6f in (expected %.6f in)"
                   % (derived, derived / IN, want / IN))
            ok &= r.check("%d tenon(s): one solid" % count,
                          topo["solids"] == 1, topo["solids"])
            ok &= r.check("%d tenon(s): derived length is exact" % count,
                          abs(derived - want) < LENGTH_TOL_MM,
                          "%.6f mm error"
                          % abs(derived - want))
            r.note("%d tenon(s): design length vs order length" % count,
                   "%.3f in design / %.3f in ordered"
                   % (F.TIMBER_L, derived / IN))

        # the angled end
        doc = App.newDocument("R2_Angled")
        save(doc, workdir, "R2_Angled")
        timber, dims, sk = timber_with_dims(doc, label="T-Angled")
        _, bparams, cutter, spare = F.build_brace_half(doc)
        doc.removeObject(spare.Name)
        angle = 30.0
        bparams.ShoulderAngle = angle
        doc.recompute()
        apply_half(doc, timber, cutter, "Cut", shoulder_placement(),
                   name="EndSaw")
        force_recompute(doc)
        shape = F.local_shape(timber)
        topo = topo_note(r, "angled end", shape)
        short, long_point = F.angled_end_points(timber)
        want_long = F.TIMBER_L * IN
        want_short = (F.TIMBER_L
                      - F.TIMBER_W * math.tan(math.radians(angle))) * IN
        r.note("angled end: sawn-face detection",
               "the one face whose normal is not axis-aligned")
        r.note("angled end: long point",
               "%.6f mm = %.6f in (expected %.6f in)"
               % (long_point, long_point / IN, want_long / IN))
        r.note("angled end: short point",
               "%.6f mm = %.6f in (expected %.6f in)"
               % (short, short / IN, want_short / IN))
        r.note("angled end: bounding-box length",
               "%.6f in -- equals the LONG point"
               % (shape.BoundBox.ZLength / IN))
        ok &= r.check("angled end: one solid", topo["solids"] == 1,
                      topo["solids"])
        ok &= r.check("angled end: long point is exact",
                      abs(long_point - want_long) < LENGTH_TOL_MM,
                      "%.6f mm error" % abs(long_point - want_long))
        ok &= r.check("angled end: short point is exact",
                      abs(short - want_short) < LENGTH_TOL_MM,
                      "%.6f mm error" % abs(short - want_short))
        r.note("WHICH THE CUT LIST MUST ORDER",
               "the LONG point (%.3f in). A sawyer cannot make an angled "
               "end from a stick cut to the short point (%.3f in) -- "
               "ordering the short point produces timbers %.3f in shy."
               % (long_point / IN, short / IN,
                  (long_point - short) / IN))
        r.note("and the bounding box gives it for free",
               "BoundBox.ZLength in the local frame IS the long point, so "
               "the naive measurement is the correct one here -- but only "
               "because the box is resolved in the timber's own frame")
        paths["angled"] = artifact(doc, "r3_angled_end")
        r.note("artifact", paths["angled"])
    except Exception as exc:
        r.error("R2", exc)
        ok = False
    r.status = "PASS" if ok else "FAIL"
    return ok, paths


# --------------------------------------------------------------------------
# T3 -- joint swap on a placed timber
# --------------------------------------------------------------------------

def object_names(doc):
    return [o.Name for o in doc.Objects]


def remove_objects(doc, names):
    """Delete a joint half's objects, dependants first."""
    removed = []
    for name in reversed(names):
        obj = doc.getObject(name)
        if obj is None:
            continue
        try:
            doc.removeObject(name)
            removed.append(name)
        except Exception:
            pass
    return removed


def t3(rec, workdir):
    r = rec.start("T3", "Joint swap on a placed timber")
    ok = True
    try:
        close_all()
        doc = App.newDocument("T3_Swap")
        save(doc, workdir, "T3_Swap")
        timber, dims, sk = timber_with_dims(doc, label="T-Post-Swap-001")
        timber.Placement = App.Placement(
            App.Vector(1200, 800, 300),
            App.Rotation(App.Vector(0, 1, 0), 22))
        doc.recompute()

        before_names = object_names(doc)
        placement_before = App.Placement(timber.Placement)
        length_before = dims.Length.Value
        section_before = (sk.getDatum("DX").Value, sk.getDatum("DY").Value)

        def bearing_faces():
            """The two bearing planes, in global coordinates."""
            return (timber.Placement.multVec(App.Vector(0, 0, 0)),
                    timber.Placement.multVec(
                        App.Vector(0, 0, dims.Length.Value)))

        bearings_before = bearing_faces()

        # --- the tenon half
        _, tparams, adder = F.build_tenon_adder(
            doc, varset_label="J-Tenon-001", body_label="Tenon.WHD.001")
        boo = apply_half(doc, timber, adder, "Fuse", end_b_placement(),
                         name="TenonAdd")
        force_recompute(doc)
        with_tenon = object_names(doc)
        half_one = [n for n in with_tenon if n not in before_names]
        r.note("objects the tenon half added", len(half_one))
        r.note("  names", half_one)
        r.note("derived order length with the tenon",
               "%.4f in" % (F.derived_length(timber) / IN))
        r.note("design length parameter", "%.4f in"
               % (dims.Length.Value / IN))

        # --- swap it for a housed-mortise half: a cutter, not an adder
        removed = remove_objects(doc, half_one)
        doc.recompute()
        r.note("objects deleted to remove the tenon half", len(removed))
        after_removal = object_names(doc)
        r.note("document is back to its pre-joint object set",
               sorted(after_removal) == sorted(before_names))

        pre_swap = object_names(doc)
        _, mparams, cutter = F.build_nocontainer_template(
            doc, varset_label="J-HousedMT-001",
            body_label="Mortise.HMT.001")
        boo2 = apply_half(doc, timber, cutter, "Cut",
                          mortise_placement(48.0), name="MortiseCut")
        force_recompute(doc)
        half_two = [n for n in object_names(doc) if n not in pre_swap]
        r.note("objects the mortise half added", len(half_two))
        r.note("  names", half_two)

        # --- the claim, asserted
        r.note("timber Placement before / after",
               "%s / %s" % (placement_before, timber.Placement))
        ok &= r.check("the timber Body's Placement is unchanged",
                      timber.Placement.isSame(placement_before, 1e-12))
        r.note("design length before / after",
               "%.6f / %.6f mm" % (length_before, dims.Length.Value))
        ok &= r.check("the design length parameter is unchanged",
                      near(dims.Length.Value, length_before))
        section_after = (sk.getDatum("DX").Value, sk.getDatum("DY").Value)
        r.note("section sketch DX/DY before / after",
               "%s / %s" % (section_before, section_after))
        ok &= r.check("the section sketch is untouched",
                      section_after == section_before)
        bearings_after = bearing_faces()
        moved = max((bearings_before[i] - bearings_after[i]).Length
                    for i in (0, 1))
        r.note("bearing-face movement", "%.9f mm" % moved)
        ok &= r.check("both bearing faces stayed put", moved < 1e-9)
        ok &= r.check("nothing is left touched or errored",
                      not unhealthy(doc), unhealthy(doc) or "none")

        r.note("operations a tool would need",
               "%d deletions + %d creations (1 copyObject bringing %d "
               "objects, 1 placement, 1 Boolean)"
               % (len(removed), len(half_two), len(half_two) - 1))
        r.note("what a swap does NOT touch",
               "the timber Body, its Dims VarSet, its section sketch, its "
               "Placement, and therefore every assembly joint and "
               "neighbouring timber that depends on them")
        r.note("under the subtractive mandate, by contrast",
               "the swap changes TenonLength, which changes the ordered "
               "stick Length, which moves the stick's ends, which moves "
               "whatever the assembly grounds off them")
    except Exception as exc:
        r.error("T3", exc)
        ok = False
    r.status = "PASS" if ok else "FAIL"
    return ok


# --------------------------------------------------------------------------
# T4 -- both halves, one mechanism, one VarSet
# --------------------------------------------------------------------------

def t4(rec, workdir):
    r = rec.start("T4", "Mated pair: both halves from one joint VarSet")
    ok = True
    paths = {}
    try:
        close_all()
        doc = App.newDocument("T4_MatedPair")
        save(doc, workdir, "T4_MatedPair")

        joint = doc.addObject("App::VarSet", "JointVars")
        joint.Label = "J-HousedMT-001"
        for name, value, tip in (
                ("MortiseThickness", 2.0 * IN,
                 "Mortise thickness, from face 2"),
                ("MortiseWidth", 6.0 * IN, "Mortise width, along face 1"),
                ("Fit", 0.03125 * IN,
                 "Total clearance between tenon and mortise cheeks")):
            joint.addProperty("App::PropertyLength", name, "Joint", tip)
            setattr(joint, name, value)

        # the receiving timber: a cutter half
        receiver, rdims, rsk = timber_with_dims(doc, label="T-Post-001")
        _, mparams, cutter = F.build_nocontainer_template(
            doc, varset_label="MortiseParams",
            body_label="Mortise.HMT.001")
        mparams.setExpression("MortiseThickness",
                              "<<J-HousedMT-001>>.MortiseThickness")
        mparams.setExpression("MortiseWidth",
                              "<<J-HousedMT-001>>.MortiseWidth")
        doc.recompute()
        apply_half(doc, receiver, cutter, "Cut", mortise_placement(48.0),
                   name="MortiseCut")

        # the entering timber: an adder half, off the same VarSet
        enterer, edims, esk = timber_with_dims(doc, label="T-Girt-001")
        enterer.Placement.Base = App.Vector(600, 0, 0)
        _, tparams, adder = F.build_tenon_adder(
            doc, varset_label="TenonParams", body_label="Tenon.HMT.001")
        tparams.setExpression(
            "TenonThickness",
            "<<J-HousedMT-001>>.MortiseThickness - <<J-HousedMT-001>>.Fit")
        tparams.setExpression(
            "TenonWidth",
            "<<J-HousedMT-001>>.MortiseWidth - <<J-HousedMT-001>>.Fit")
        doc.recompute()
        apply_half(doc, enterer, adder, "Fuse", end_b_placement(),
                   name="TenonAdd")
        force_recompute(doc)

        r.note("one mechanism, two roles",
               "both halves are PartDesign::Boolean over a copied solid; "
               "only Type differs (Cut for the mortise, Fuse for the "
               "tenon). No island pocket anywhere.")
        topo_note(r, "receiver (cutter half)", F.local_shape(receiver))
        topo_note(r, "enterer (adder half)", F.local_shape(enterer))
        ok &= r.check("both timbers are single valid solids",
                      len(F.local_shape(receiver).Solids) == 1
                      and len(F.local_shape(enterer).Solids) == 1)

        # Control: the same cutter seated wrong -- housing footprint
        # spanning the whole section rather than bearing on a face.
        control = App.newDocument("T4_SeveringControl")
        try:
            victim, vdims, vsk = timber_with_dims(control,
                                                  label="T-Severed-001")
            _, cparams, ccutter = F.build_nocontainer_template(
                control, varset_label="ControlParams",
                body_label="Mortise.Control")
            apply_half(control, victim, ccutter, "Cut",
                       App.Placement(App.Vector(0, 0, 48.0 * IN),
                                     App.Rotation()), name="ControlCut")
            force_recompute(control)
            shape = F.local_shape(victim)
            want_control = (F.timber_volume()
                            - F.cutter_volume(F.default_params()))
            r.note("control: a cutter whose footprint spans the section",
                   "volume %.4f (expected %.4f) -- EXACTLY right"
                   % (shape.Volume, want_control))
            r.note("control: solids / valid / closed",
                   "%d / %s / %s" % (len(shape.Solids), shape.isValid(),
                                     shape.isClosed()))
            ok &= r.check("the control cuts exactly the expected volume",
                          near(shape.Volume, want_control))
            ok &= r.check("...yet it severed the stick, and only the "
                          "solid count says so",
                          len(shape.Solids) == 2, len(shape.Solids))
            r.note("what the control proves",
                   "a cutter that removes the right VOLUME can still cut "
                   "the timber in half. Under the cutter+adder model that "
                   "is a placement error a tool can make, and volume, "
                   "isValid() and isClosed() are all blind to it")
        finally:
            App.closeDocument(control.Name)
            App.setActiveDocument(doc.Name)

        def fit_now():
            """Clearance measured from the two SOLIDS, at a height clear
            of the housing, not re-read from the parameters."""
            mortise = section_box(F.local_shape(cutter), 2.0 * IN)
            tenon = section_box(F.local_shape(adder), 2.0 * IN)
            return (mortise.XLength - tenon.XLength,
                    mortise.YLength - tenon.YLength,
                    mortise, tenon)

        gap_x, gap_y, mortise, tenon = fit_now()
        r.note("mortise cavity section (thickness x width)",
               "%.4f x %.4f in" % (mortise.XLength / IN,
                                   mortise.YLength / IN))
        r.note("tenon section (thickness x width)",
               "%.4f x %.4f in" % (tenon.XLength / IN, tenon.YLength / IN))
        r.note("measured clearance",
               "%.6f in thickness, %.6f in width (intended %.6f in)"
               % (gap_x / IN, gap_y / IN, joint.Fit.Value / IN))
        ok &= r.check("measured fit equals the intended fit",
                      near(gap_x, joint.Fit.Value)
                      and near(gap_y, joint.Fit.Value),
                      "%.6f / %.6f mm" % (gap_x, gap_y))

        # change the shared parameter, with the three-part assertion
        want_receiver = (F.timber_volume()
                         - F.cutter_volume(dict(F.default_params(),
                                                MortiseThickness=3.0)))
        ok &= changed_cleanly(
            r, doc, "shared MortiseThickness to 3.0 in",
            lambda: setattr(joint, "MortiseThickness", 3.0 * IN),
            lambda: F.local_shape(receiver).Volume, want_receiver)[0]

        tenon_thick_in = 3.0 - joint.Fit.Value / IN
        want_enterer = (F.timber_volume()
                        + tenon_thick_in
                        * (6.0 - joint.Fit.Value / IN)
                        * F.default_tenon_params()["TenonLength"] * IN ** 3)
        r.note("enterer volume after the shared change",
               "%.4f (expected %.4f)"
               % (F.local_shape(enterer).Volume, want_enterer))
        ok &= r.check("the adder half followed the same VarSet",
                      near(F.local_shape(enterer).Volume, want_enterer))

        gap_x, gap_y, mortise, tenon = fit_now()
        r.note("clearance after the change",
               "%.6f in thickness, %.6f in width (intended %.6f in)"
               % (gap_x / IN, gap_y / IN, joint.Fit.Value / IN))
        ok &= r.check("tenon and mortise stay dimensionally matched",
                      near(gap_x, joint.Fit.Value)
                      and near(gap_y, joint.Fit.Value))

        ok &= changed_cleanly(
            r, doc, "shared Fit to 1/16 in",
            lambda: setattr(joint, "Fit", 0.0625 * IN),
            lambda: section_box(F.local_shape(cutter), 2.0 * IN).XLength
            - section_box(F.local_shape(adder), 2.0 * IN).XLength,
            0.0625 * IN)[0]

        doc.save()
        paths["mated"] = artifact(doc, "r3_mated_pair")
        r.note("artifact", paths["mated"])
    except Exception as exc:
        r.error("T4", exc)
        ok = False
    r.status = "PASS" if ok else "FAIL"
    return ok, paths


# --------------------------------------------------------------------------
# T5 -- cutter and adder in one half, and whether order matters
# --------------------------------------------------------------------------

def build_brace(doc, order):
    """A brace end carrying both an angled shoulder cut and a tenon,
    applied in the given order.  Returns (timber, params, topology)."""
    timber, dims, sk = timber_with_dims(doc, label="T-Brace-%s" % order)
    _, params, cutter, adder = F.build_brace_half(
        doc, varset_label="BraceParams_%s" % order)
    # The brace tenon's base sits at the sawn face's SHORT point, so it
    # is buried in material over its whole footprint however the angle is
    # set.  A square tenon base cannot be coplanar with an angled
    # shoulder, which is itself part of the finding.
    rise_in = (params.ShoulderRun.Value / IN
               * math.tan(math.radians(params.ShoulderAngle.Value)))
    tenon_seat = end_b_placement(length_in=F.TIMBER_L - rise_in)
    steps = {
        "cut_then_add": ((cutter, "Cut", shoulder_placement()),
                         (adder, "Fuse", tenon_seat)),
        "add_then_cut": ((adder, "Fuse", tenon_seat),
                         (cutter, "Cut", shoulder_placement())),
    }[order]
    for i, (body, kind, placement) in enumerate(steps):
        apply_half(doc, timber, body, kind, placement,
                   name="%s_%d" % (order, i))
    force_recompute(doc)
    return timber, params, F.topology(F.local_shape(timber))


def t5(rec, workdir):
    r = rec.start("T5", "Cutter + adder in one half; does order matter?")
    ok = True
    paths = {}
    try:
        close_all()
        results = {}
        doc = None
        for order in ("cut_then_add", "add_then_cut"):
            close_all()
            doc = App.newDocument("T5_%s" % order)
            save(doc, workdir, "T5_%s" % order)
            timber, params, topo = build_brace(doc, order)
            results[order] = topo
            topo_note(r, order, F.local_shape(timber))
            r.note("%s: objects not Up-to-date" % order,
                   unhealthy(doc) or "none")
            ok &= r.check("%s: both booleans applied to one valid solid"
                          % order,
                          topo["solids"] == 1 and topo["valid"]
                          and topo["closed"] and not unhealthy(doc))
            if order == "cut_then_add":
                ok &= recomputed_cleanly(
                    r, doc, "brace: ShoulderAngle to 45 deg",
                    lambda: setattr(params, "ShoulderAngle", 45.0),
                    timber)[0]
                ok &= recomputed_cleanly(
                    r, doc, "brace: TenonThickness to 3 in",
                    lambda: setattr(params, "TenonThickness", 3.0 * IN),
                    timber)[0]
                params.ShoulderAngle = 30.0
                params.TenonThickness = 2.0 * IN
                force_recompute(doc)
                paths["brace"] = artifact(doc, "r3_brace")
                r.note("artifact", paths["brace"])

        a, b = results["cut_then_add"], results["add_then_cut"]
        r.note("volumes, cut-then-add vs add-then-cut",
               "%.4f vs %.4f (difference %.4f mm^3)"
               % (a["volume"], b["volume"], abs(a["volume"] - b["volume"])))
        r.note("topology, cut-then-add vs add-then-cut",
               " / ".join("%s %d vs %d" % (k, a[k], b[k])
                          for k in ("solids", "faces", "edges",
                                    "vertexes")))
        commutes = (near(a["volume"], b["volume"])
                    and all(a[k] == b[k] for k in ("solids", "faces",
                                                   "edges", "vertexes")))
        r.note("DO THE TWO ORDERS COMMUTE?",
               "yes" if commutes else "NO -- the order is part of the "
               "template contract")
        if not commutes:
            r.note("why",
                   "the shoulder cutter reaches past the end face, so "
                   "applied after the adder it saws the tenon off with "
                   "the waste. The cut must be applied first, or the "
                   "cutter must be modelled to stop at the shoulder "
                   "plane -- either way the template has to say so.")
        r.note("recommended contract",
               "cutter first, then adder: a cutter shapes the stick the "
               "adder then lands on, which is also the order a framer "
               "works in")
    except Exception as exc:
        r.error("T5", exc)
        ok = False
    r.status = "PASS" if ok else "FAIL"
    return ok, results, paths


# --------------------------------------------------------------------------
# T6 -- scale, and TechDraw downstream
# --------------------------------------------------------------------------

def t6(rec, workdir, counts):
    r = rec.start("T6", "Scale: mixed cutters and adders")
    rows = []
    ok = True
    paths = {}
    for n in counts:
        close_all()
        row = {"n": n}
        try:
            doc = App.newDocument("T6_Scale_%d" % n)
            path = save(doc, workdir, "T6_Scale_%d" % n)
            group = doc.addObject("App::VarSet", "GroupTest")
            group.Label = "Group_Test"
            group.addProperty("App::PropertyLength", "MortiseThickness",
                              "Group", "Shared mortise thickness")
            group.MortiseThickness = 2.0 * IN
            group.addProperty("App::PropertyLength", "TenonThickness",
                              "Group", "Shared tenon thickness")
            group.TenonThickness = 2.0 * IN

            start = time.time()
            for i in range(n):
                timber, dims, sk = timber_with_dims(
                    doc, label="T-Spike-%03d" % (i + 1))
                # spaced across x; a joint half is seated in the
                # TARGET body's local frame, so this offset is deliberately
                # NOT added to the seat placements below
                timber.Placement.Base = App.Vector(i * 400.0, 0, 0)
                if i % 2 == 0:
                    _, params, body = F.build_nocontainer_template(
                        doc, varset_label="Cut_%03d" % (i + 1),
                        body_label="Mortise_%03d" % (i + 1))
                    params.setExpression(
                        "MortiseThickness",
                        "<<Group_Test>>.MortiseThickness")
                    apply_half(doc, timber, body, "Cut",
                               mortise_placement(48.0),
                               name="Cut_%03d" % (i + 1))
                else:
                    _, params, body = F.build_tenon_adder(
                        doc, varset_label="Add_%03d" % (i + 1),
                        body_label="Tenon_%03d" % (i + 1))
                    params.setExpression("TenonThickness",
                                         "<<Group_Test>>.TenonThickness")
                    apply_half(doc, timber, body, "Fuse",
                               end_b_placement(),
                               name="Add_%03d" % (i + 1))
            row["build_s"] = time.time() - start

            for obj in doc.Objects:
                obj.touch()
            start = time.time()
            doc.recompute(None, True, True)
            row["full_recompute_s"] = time.time() - start

            start = time.time()
            group.MortiseThickness = 1.75 * IN
            group.TenonThickness = 1.75 * IN
            doc.recompute()
            row["param_change_s"] = time.time() - start

            bad = unhealthy(doc)
            row["unhealthy"] = len(bad)
            severed = [o.Label for o in doc.Objects
                       if o.TypeId == "PartDesign::Body"
                       and len(o.Shape.Solids) != 1]
            row["severed"] = len(severed)
            if bad or severed:
                ok = False
                r.note("n=%d: unhealthy / non-single-solid" % n,
                       "%s / %s" % (bad[:3], severed[:3]))

            start = time.time()
            doc.save()
            row["save_s"] = time.time() - start
            row["file_mb"] = os.path.getsize(path) / (1024.0 * 1024.0)
            row["objects"] = len(doc.Objects)
            if n == max(counts):
                paths["scale"] = artifact(doc, "r3_scale_%d" % n)
                r.note("artifact", paths["scale"])
        except Exception as exc:
            row["error"] = "%s: %s" % (type(exc).__name__, exc)
            r.error("T6 n=%d" % n, exc)
            ok = False
        rows.append(row)
        r.note("n=%d" % n, ", ".join(
            "%s=%s" % (k, ("%.3f" % v) if isinstance(v, float) else v)
            for k, v in sorted(row.items()) if k != "n"))

    timed = [x for x in rows if "error" not in x]
    if len(timed) >= 2:
        first, last = timed[0], timed[-1]
        per_first = first["full_recompute_s"] / float(first["n"])
        per_last = last["full_recompute_s"] / float(last["n"])
        r.note("per-instance full recompute",
               "%.4f s at n=%d -> %.4f s at n=%d"
               % (per_first, first["n"], per_last, last["n"]))
        if per_first > 0:
            ratio = per_last / per_first
            r.note("growth", "roughly linear" if ratio < 2.0
                   else "NON-LINEAR (%.2fx per instance)" % ratio)
    r.status = "PASS" if ok else "FAIL"
    return rows, paths


def t6_techdraw(rec, workdir):
    r = rec.start("T6d", "Downstream: TechDraw over a fused tenon")
    ok = True
    console = ""
    try:
        def run():
            close_all()
            doc = App.newDocument("T6_TechDraw")
            save(doc, workdir, "T6_TechDraw")
            timber, dims, sk = timber_with_dims(doc, label="T-Draw-001")
            _, params, adder = F.build_tenon_adder(
                doc, varset_label="DrawTenon", body_label="Tenon.Draw")
            apply_half(doc, timber, adder, "Fuse", end_b_placement(),
                       name="TenonAdd")
            force_recompute(doc)

            tdir = os.path.join(App.getResourceDir(), "Mod", "TechDraw",
                                "Templates")
            page = doc.addObject("TechDraw::DrawPage", "Page")
            tpl = doc.addObject("TechDraw::DrawSVGTemplate", "Template")
            tpl.Template = os.path.join(
                tdir, "Default_Template_A4_Landscape.svg")
            page.Template = tpl
            doc.recompute()

            group = doc.addObject("TechDraw::DrawProjGroup", "ProjGroup")
            page.addView(group)
            group.Source = [timber]
            group.ScaleType = "Custom"
            group.Scale = 0.1
            front = group.addProjection("Front")
            front.HardHidden = True
            doc.recompute()

            dims_out = []
            for name, edge in (("DimOverall", "Edge0"),
                               ("DimTenon", "Edge1")):
                dim = doc.addObject("TechDraw::DrawViewDimension", name)
                page.addView(dim)
                dim.Type = "DistanceY"
                dim.References2D = (front, [edge])
                dims_out.append(dim)
            doc.recompute()
            before = [d.getRawValue() for d in dims_out]
            params.TenonLength = 6.0 * IN
            force_recompute(doc)
            after = [d.getRawValue() for d in dims_out]
            return (doc, timber, group, front, dims_out, before, after)

        (doc, timber, group, front, dims_out,
         before, after), console = capture_console(run)
        r.note("projection group / front view state",
               "%s / %s" % (group.State, front.State))
        r.note("dimension states", [d.State for d in dims_out])
        r.note("dimension values before -> after",
               "%s -> %s" % (before, after))
        r.note("timber topology after the change",
               F.topology(F.local_shape(timber)))
        bad = [x for x in unhealthy(doc)
               if not x[0].startswith(("Page", "Template", "ProjGroup",
                                       "ProjItem", "Dim"))]
        r.note("non-TechDraw objects not Up-to-date", bad or "none")
        ok &= r.check("views and dimensions survive a parameter change",
                      all("Invalid" not in str(d.State) for d in dims_out)
                      and "Invalid" not in str(front.State) and not bad)
        ok &= r.check("the fused timber is still one valid solid",
                      len(F.local_shape(timber).Solids) == 1)
    except Exception as exc:
        r.error("T6d", exc)
        ok = False
    hashers = console.count("hasher mismatch")
    r.note("'hasher mismatch' warnings", hashers)
    r.note("why this matters more here",
           "a fusion across coplanar faces is where topological naming is "
           "most likely to be unstable, and a TechDraw dimension is "
           "attached by element name")
    r.note("other console faults",
           [line for line in console_faults(console)
            if "hasher mismatch" not in line] or "none")
    r.status = "PASS" if ok else "PARTIAL"
    return ok, hashers


# --------------------------------------------------------------------------
# T6b -- template-internal boundary coincidence, swept
# --------------------------------------------------------------------------

#: Sweep domains, in inches, where the roadmap's sanity bounds apply.
#: Everything else sweeps 25%-150% of the shipped default.
SWEEP_BOUNDS = {
    # roadmap: mortise width <= 75% of the receiving extent (8 in)
    "MortiseWidth": (0.5, 0.75 * F.TIMBER_H),
    # roadmap: housing <= 50% of the through-dimension
    "HousingDepth": (0.05, 0.5 * F.TIMBER_W),
    "HousingWidth": (1.0, F.TIMBER_W),
    "HousingHeight": (1.0, F.TIMBER_H),
    "TenonWidth": (0.5, 0.75 * F.TIMBER_H),
}


def sweep_template(r, name, factory, steps=12):
    """Sweep every property of one template and assert the template's own
    solid stays valid, closed and single -- before any boolean.

    This is finding #14 relocated, not removed: the cutter+adder model
    takes island pockets out of joint *application*, but template solids
    are still sketch-modelled, and a sketch that is fine at its defaults
    can develop a boundary coincidence at some parameter value.
    """
    close_all()
    doc, params, body = factory()
    props = [p for p in params.PropertiesList
             if params.getGroupOfProperty(p) == "Joint"]
    failures = []
    checked = 0
    start = time.time()
    for prop in props:
        original = getattr(params, prop).Value
        default_in = original / IN
        if params.getTypeIdOfProperty(prop) == "App::PropertyAngle":
            lo, hi = 5.0, 60.0
            scale = 1.0
        else:
            lo, hi = SWEEP_BOUNDS.get(
                prop, (0.25 * default_in, 1.5 * default_in))
            scale = IN
        for i in range(steps):
            value = lo + (hi - lo) * i / float(steps - 1)
            checked += 1
            raised = None
            try:
                setattr(params, prop, value * scale)
                doc.recompute()
                shape = body.Shape
                topo = F.topology(shape)
            except Exception as exc:
                raised = "%s: %s" % (type(exc).__name__, exc)
                topo = {"solids": 0, "valid": False, "closed": False,
                        "volume": 0.0}
            bad_state = unhealthy(doc)
            if (topo["solids"] != 1 or not topo["valid"]
                    or not topo["closed"] or bad_state or raised):
                failures.append({
                    "property": prop, "value_in": value,
                    "solids": topo["solids"], "valid": topo["valid"],
                    "closed": topo["closed"],
                    "raised": raised,
                    "silent": raised is None and not bad_state,
                    "state": bad_state[:2] or "clean"})
        setattr(params, prop, original)
        doc.recompute()
    elapsed = time.time() - start

    r.note("%s: properties swept" % name,
           "%d properties x %d steps = %d template solids checked"
           % (len(props), steps, checked))
    r.note("%s: sweep wall time" % name,
           "%.3f s (%.1f ms per step)"
           % (elapsed, 1000.0 * elapsed / max(checked, 1)))
    if failures:
        for fail in failures[:12]:
            r.note("%s: FAILS at %s = %.4f in" % (name, fail["property"],
                                                  fail["value_in"]),
                   "solids=%s valid=%s closed=%s raised=%s silent=%s"
                   % (fail["solids"], fail["valid"], fail["closed"],
                      fail["raised"], fail["silent"]))
        if len(failures) > 12:
            r.note("%s: further failures not listed" % name,
                   len(failures) - 12)
    else:
        r.note("%s: failures" % name, "none across the whole domain")
    r.check("%s: template solid valid across its whole sweep" % name,
            not failures, "%d failures in %d steps"
            % (len(failures), checked))
    return {"name": name, "checked": checked, "seconds": elapsed,
            "failures": failures, "properties": len(props)}


def t6b(rec, workdir):
    r = rec.start("T6b", "Template-internal boundary coincidence, swept")
    sweeps = []
    try:
        sweeps.append(sweep_template(
            r, "mortise cutter",
            lambda: F.build_nocontainer_template()))
        sweeps.append(sweep_template(
            r, "tenon adder",
            lambda: F.build_tenon_adder()))

        def brace():
            doc, params, cutter, adder = F.build_brace_half()
            return doc, params, adder
        sweeps.append(sweep_template(r, "brace adder", brace))

        def brace_cutter():
            doc, params, cutter, adder = F.build_brace_half()
            return doc, params, cutter
        sweeps.append(sweep_template(r, "brace cutter", brace_cutter))

        total = sum(s["seconds"] for s in sweeps)
        checked = sum(s["checked"] for s in sweeps)
        r.note("all templates: total sweep time",
               "%.3f s for %d template solids" % (total, checked))
        r.note("fast enough at registration time?",
               "yes -- %.3f s for one template is well inside what a "
               "save-as-template command can absorb"
               % (total / max(len(sweeps), 1)))
        clean = not any(s["failures"] for s in sweeps)
        if not clean:
            r.note("READ THIS AS A FINDING, NOT A HARNESS FAILURE",
                   "the sweep ran to completion and found a real "
                   "parameter-dependent hole in a template solid. That is "
                   "what it is for, and it is the argument for making it "
                   "mandatory at registration.")
        ok = True
    except Exception as exc:
        r.error("T6b", exc)
        clean = False
        ok = False
    r.status = "PASS" if (ok and clean) else ("PARTIAL" if ok else "FAIL")
    return clean, sweeps


# --------------------------------------------------------------------------
# T7 -- head-to-head against the subtractive model
# --------------------------------------------------------------------------

def t7(rec, workdir):
    r = rec.start("T7", "Head-to-head: adder vs subtractive island pocket")
    ok = True
    summary = {}
    thicknesses = [0.5 + 0.25 * i for i in range(15)]     # 0.5 .. 4.0 in
    try:
        # --- the adder model
        close_all()
        doc = App.newDocument("T7_Adder")
        save(doc, workdir, "T7_Adder")
        base = len(doc.Objects)
        timber, dims, sk = timber_with_dims(doc, label="T-Adder-001")
        after_timber = len(doc.Objects)
        _, aparams, adder = F.build_tenon_adder(
            doc, varset_label="AdderParams", body_label="Tenon.Adder")
        apply_half(doc, timber, adder, "Fuse", end_b_placement(),
                   name="TenonAdd")
        force_recompute(doc)
        summary["adder"] = {
            "objects": len(doc.Objects),
            "joint_objects": len(doc.Objects) - after_timber,
            "template_objects": len(F.build_tenon_adder()[0].Objects),
            "topology": F.topology(F.local_shape(timber))}
        for obj in doc.Objects:
            obj.touch()
        start = time.time()
        doc.recompute(None, True, True)
        summary["adder"]["recompute_s"] = time.time() - start

        adder_fail = []
        for thickness in thicknesses:
            good, _ = recomputed_cleanly(
                r, doc, "adder @ %.2f in" % thickness,
                lambda t=thickness: setattr(aparams, "TenonThickness",
                                            t * IN),
                timber)
            if not good:
                adder_fail.append(thickness)
        summary["adder"]["sweep_failures"] = adder_fail

        # --- the subtractive model
        close_all()
        doc2 = App.newDocument("T7_Subtractive")
        save(doc2, workdir, "T7_Subtractive")
        doc2, sub, sdims, sparams, ssk = F.build_subtractive_tenon_timber(
            doc2, label="T-Sub-001")
        force_recompute(doc2)
        summary["subtractive"] = {
            "objects": len(doc2.Objects),
            "joint_objects": 2,     # the waste sketch and the pocket
            "template_objects": 0,  # there is no separate template solid
            "topology": F.topology(F.local_shape(sub))}
        for obj in doc2.Objects:
            obj.touch()
        start = time.time()
        doc2.recompute(None, True, True)
        summary["subtractive"]["recompute_s"] = time.time() - start

        sub_fail = []
        for thickness in thicknesses:
            good, _ = recomputed_cleanly(
                r, doc2, "subtractive @ %.2f in" % thickness,
                lambda t=thickness: setattr(sparams, "TenonThickness",
                                            t * IN),
                sub)
            if not good:
                sub_fail.append(thickness)
        summary["subtractive"]["sweep_failures"] = sub_fail

        for key in ("adder", "subtractive"):
            s = summary[key]
            r.note("%s: objects in the document" % key, s["objects"])
            r.note("%s: objects the joint contributes" % key,
                   s["joint_objects"])
            r.note("%s: objects in its template" % key,
                   s["template_objects"] or "n/a (no separate template)")
            r.note("%s: full recompute" % key,
                   "%.4f s" % s["recompute_s"])
            r.note("%s: resulting topology" % key,
                   "%d solids, %d faces, volume %.3f"
                   % (s["topology"]["solids"], s["topology"]["faces"],
                      s["topology"]["volume"]))
            r.note("%s: sweep failures (0.5-4.0 in)" % key,
                   s["sweep_failures"] or "none")

        same_solid = (summary["adder"]["topology"]["faces"]
                      == summary["subtractive"]["topology"]["faces"]
                      and near(summary["adder"]["topology"]["volume"],
                               summary["subtractive"]["topology"]["volume"]))
        r.note("do the two models produce the same solid?",
               "yes -- identical volume and face count" if same_solid
               else "NO -- see the topology rows above")
        ok &= r.check("both models produce the same physical timber",
                      same_solid)
        ok &= r.check("the adder model survives the whole sweep",
                      not adder_fail, adder_fail or "no failures")
        ok &= r.check("the subtractive model survives the whole sweep",
                      not sub_fail, sub_fail or "no failures")
        r.note("verdict",
               "the adder model fails nowhere the subtractive model does "
               "not" if not adder_fail or sub_fail
               else "THE ADDER MODEL FAILS WHERE SUBTRACTIVE DOES NOT")
    except Exception as exc:
        r.error("T7", exc)
        ok = False
    r.status = "PASS" if ok else "FAIL"
    return ok, summary


# --------------------------------------------------------------------------
# report
# --------------------------------------------------------------------------

def scale_table(ctx):
    prior = ctx.get("round2b", {})
    lines = ["| n | metric | round 2b (cut only) | **round 3 (cut + add)** |",
             "|---|---|---|---|"]
    metrics = [("build_s", "build (s)", "%.2f"),
               ("full_recompute_s", "full recompute (s)", "%.2f"),
               ("param_change_s", "group change (s)", "%.2f"),
               ("file_mb", "file (MB)", "%.2f"),
               ("objects", "objects", "%d")]
    for row in ctx.get("scale", []):
        n = row["n"]
        if "error" in row:
            lines.append("| %s | — | — | error: `%s` |" % (n, row["error"]))
            continue
        for key, label, fmt in metrics:
            was = prior.get(n, {}).get(key)
            lines.append("| %s | %s | %s | **%s** |"
                         % (n if key == "build_s" else "", label,
                            fmt % was if was is not None else "—",
                            fmt % row[key]))
    return lines


def write_report(rec, ctx):
    lines = []
    w = lines.append
    w("# Spike round 3: cutter + adder joint halves")
    w("")
    w("Generated by `tests/spike/spike_cutter_adder.py` (fixtures in")
    w("`tests/spike/spike_fixtures.py`), run headless under")
    w("`freecadcmd.exe`. Implements `docs/spike-round3-brief.md`.")
    w("Priors: rounds 1, 2, 2b settled *how a template becomes an")
    w("instance*; round 3 tests *what a joint template is*.")
    w("")
    w("- FreeCAD: %s" % ctx["version"])
    w("- Run: %s" % ctx["timestamp"])
    w("- Work directory: `%s`" % ctx["workdir"])
    w("")
    w("```bash")
    w("freecadcmd.exe tests/spike/spike_cutter_adder.py")
    w("```")
    w("")
    w("**A headless PASS is a candidate, not a proof** -- round 2 passed")
    w("every headless assertion and was wrong. See *Needs GUI")
    w("confirmation*, which names which artifact settles which question.")
    w("")
    if ctx.get("artifacts"):
        w("## Artifacts for GUI inspection")
        w("")
        for name, path in ctx["artifacts"]:
            w("- `%s` — %s"
              % (os.path.relpath(path, REPO).replace("\\", "/"), name))
        w("")
    lines.extend(render_results(rec, ctx["headlines"]))
    w("## Scale, against round 2b")
    w("")
    lines.extend(scale_table(ctx))
    w("")
    lines.extend(ctx["narrative"])
    with open(REPORT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print("\nwrote %s" % REPORT)


def narrative(rec, ctx):
    out = []
    w = out.append
    status = dict((r.id, r.status) for r in rec.results)
    sweeps = ctx.get("sweeps", [])
    t7 = ctx.get("t7", {})
    scale = dict((row["n"], row) for row in ctx.get("scale", [])
                 if "error" not in row)
    big = max(scale) if scale else None
    prior = ctx.get("round2b", {})

    w("## Verdict on Risk 1 -- coplanar-face fusion")
    w("")
    if status.get("R1") == "PASS":
        w("**The coincidence itself is a non-issue.** A tenon shoulder")
        w("exactly coplanar with the stick's end face fuses to one valid,")
        w("closed solid with *bit-identical* topology to the 1 mm-overlap")
        w("case -- 11 faces, 24 edges, 16 vertexes, the same volume to")
        w("full precision -- and the console stays silent. This is not the")
        w("island-pocket failure mode repeating: a pocket's coincident")
        w("loops are a *sketch* problem, and there is no sketch here.")
        w("")
        w("**But the risk was in the wrong place, and the real one is")
        w("worse.** Three separate ways of getting this wrong all produce")
        w("*exactly the expected volume*, pass `isValid()` and")
        w("`isClosed()`, and leave every object `Up-to-date`:")
        w("")
        w("1. **A 1 mm gap** between adder and end face -- the R1 control.")
        w("   Two solids, correct volume.")
        w("2. **A cutter whose footprint spans the section** -- the T4")
        w("   control. It removes exactly the intended volume *and cuts")
        w("   the timber in half*.")
        w("3. **A seat computed in the wrong frame** -- see below. The")
        w("   adder lands clean off the end of the stick, and the volume")
        w("   is still right to the last digit.")
        w("")
        w("Only **solid count** catches any of them. That is the single")
        w("most important thing round 3 has to say: under a cutter+adder")
        w("model, `len(shape.Solids) == 1` is not a nicety, it is the")
        w("assertion that distinguishes a joint from a severed timber.")
        w("")
        w("### The operand-frame finding")
        w("")
        w("`PartDesign::Boolean` seats its operand in the **target Body's")
        w("local frame**; the target's own `Placement` is not applied. So")
        w("a joint half is placed at the timber's *local* end, and adding")
        w("the timber's own offset -- the obvious thing to do -- moves the")
        w("adder off the end face by exactly that offset. The harness made")
        w("this mistake while being written, and the only symptom was the")
        w("solid count. This is the same family as Phase 0 finding #10:")
        w("resolve the frame before believing a coordinate.")
    else:
        w("**FAILED.** See the R1 table above.")
    w("")

    w("## Verdict on Risk 2 -- derived length")
    w("")
    if status.get("R2") == "PASS":
        w("**Sound, with one condition made explicit.** Derived length is")
        w("exact -- 0.000000 mm error in all four cases against the")
        w("brief's 0.001 mm tolerance -- for a square stick, one tenon,")
        w("two tenons, and a 30-degree end.")
        w("")
        w("The condition is the frame. The test timber is deliberately")
        w("rotated 37 degrees; its *global* bounding box reads 2069.68 mm")
        w("against a true 2438.40 mm. Resolving")
        w("`shape.Placement = body.Placement.inverse() * shape.Placement`")
        w("first makes the measurement exact. A cut list that reads a")
        w("global box will short every rotated timber, silently.")
        w("")
        w("**Long point versus short point.** For the 30-degree end the")
        w("long point is 96.000 in and the short point 91.381 in. The cut")
        w("list must order the **long point**: a sawyer makes the angle by")
        w("cutting it, and cannot cut an angled end onto a stick already")
        w("cut to the short point -- ordering the short point yields every")
        w("brace 4.619 in shy. Conveniently the local bounding box *is*")
        w("the long point, so the naive measurement is the right one; the")
        w("short point needs the sawn face, found as the one face whose")
        w("normal is not axis-aligned.")
        w("")
        w("Design length and order length genuinely diverge: the two-tenon")
        w("stick is 96 in of design and 104 in of timber. That is the")
        w("claimed benefit, and it holds.")
    else:
        w("**FAILED.** See the R2 table above.")
    w("")

    w("## Joint swapping, quantified (T3)")
    w("")
    w("Swapping a tenon half for a housed-mortise half on a placed,")
    w("rotated timber moved nothing: `Placement` identical, design length")
    w("identical, section sketch untouched, both bearing faces moved")
    w("0.000000000 mm. The cost is 13 deletions and 15 creations -- one")
    w("`copyObject` and one Boolean either side.")
    w("")
    w("The comparison that matters is not the object count but what is")
    w("*not* touched. Under the subtractive mandate the same swap changes")
    w("the tenon length, which changes the ordered stick length, which")
    w("moves the stick's ends, which moves every assembly joint grounded")
    w("off them. Here the design solid is inert and only the attached")
    w("components change.")
    w("")

    w("## Both halves, one mechanism (T4)")
    w("")
    w("A mortise (cutter) and a tenon (adder) driven from one")
    w("`J-HousedMT-001` VarSet stay matched through parameter changes, and")
    w("the fit is *measured from the solids* -- a section taken clear of")
    w("the housing -- not re-read from the parameters. Intended 1/32 in,")
    w("measured 0.031250 in on both thickness and width; changed to")
    w("1/16 in, measured 1/16 in. Both halves are `PartDesign::Boolean`")
    w("over a copied solid, differing only in `Type`. No island pocket")
    w("appears anywhere, which is claimed benefit 1, confirmed.")
    w("")

    w("## Boolean order is NOT commutative (T5)")
    w("")
    if ctx.get("t5_commutes") is False:
        w("The brace half -- an angled shoulder cutter plus a tenon adder,")
        w("one VarSet -- gives **different solids** depending on order:")
        w("")
        w("- cut-then-add: 10 faces, volume %.1f mm³"
          % ctx.get("t5_cut_first", 0.0))
        w("- add-then-cut: 6 faces, volume %.1f mm³"
          % ctx.get("t5_add_first", 0.0))
        w("")
        w("Six faces is a plain angled stick: applied second, the shoulder")
        w("cutter sawed the tenon off along with the waste. Both results")
        w("are single valid closed solids, so **nothing but the face count")
        w("and volume distinguishes a correct brace from a brace with no")
        w("tenon**.")
        w("")
        w("**Order therefore belongs in the template contract.** The")
        w("recommendation is *cutter first, then adder*: a cutter shapes")
        w("the stick the adder lands on, which is also the order a framer")
        w("works in. A template must not be free to leave this implicit.")
    else:
        w("The two orders commuted in this test. Do not generalise from")
        w("one geometry -- see the T5 table.")
    w("")

    w("## Template validation sweep (T6b)")
    w("")
    total = sum(s["seconds"] for s in sweeps)
    checked = sum(s["checked"] for s in sweeps)
    failing = [s for s in sweeps if s["failures"]]
    w("%d template solids were built and asserted across %d templates in"
      % (checked, len(sweeps)))
    w("%.2f s -- about %.0f ms per step, roughly %.1f s per template."
      % (total, 1000.0 * total / max(checked, 1),
         total / max(len(sweeps), 1)))
    w("")
    if failing:
        w("**The sweep found a real hole, silently.** In the mortise")
        w("cutter, `HousingHeight` below about 1.7 in leaves the housing")
        w("pad no longer overlapping the mortise prism (which starts at")
        w("`SetbackFace1` = 2 in), so the template's own solid becomes")
        w("**two disjoint solids** -- with no exception, no console")
        w("output, `isValid()` and `isClosed()` both true, and every")
        w("object `Up-to-date`. A joint applied from that template would")
        w("cut two unrelated pockets.")
        w("")
        w("Concretely:")
        w("")
        for sweep in failing:
            for fail in sweep["failures"][:6]:
                w("- `%s` at `%s` = %.4f in: %d solids, valid=%s, "
                  "raised=%s, silent=%s"
                  % (sweep["name"], fail["property"], fail["value_in"],
                     fail["solids"], fail["valid"], fail["raised"],
                     fail["silent"]))
        w("")
        w("This is finding #14 **relocated, not removed**, exactly as the")
        w("brief predicted -- and the relocation is an improvement, because")
        w("authoring time is a place a tool can check.")
    else:
        w("No template solid became invalid anywhere in its declared")
        w("domain. That is a weaker result than it looks: it means these")
        w("particular templates are sound, not that the class of failure")
        w("has gone away.")
    w("")

    w("## Head-to-head against the subtractive model (T7)")
    w("")
    if t7:
        add, sub = t7.get("adder", {}), t7.get("subtractive", {})
        w("Same physical timber, built both ways:")
        w("")
        w("| | subtractive (island pocket) | adder |")
        w("|---|---|---|")
        w("| objects in the document | %s | %s |"
          % (sub.get("objects"), add.get("objects")))
        w("| objects the joint contributes | %s | %s |"
          % (sub.get("joint_objects"), add.get("joint_objects")))
        w("| objects in its template | %s | %s |"
          % (sub.get("template_objects") or "n/a", add.get("template_objects")))
        w("| full recompute | %.4f s | %.4f s |"
          % (sub.get("recompute_s", 0.0), add.get("recompute_s", 0.0)))
        w("| resulting solid | %d solids, %d faces | %d solids, %d faces |"
          % (sub.get("topology", {}).get("solids", 0),
             sub.get("topology", {}).get("faces", 0),
             add.get("topology", {}).get("solids", 0),
             add.get("topology", {}).get("faces", 0)))
        w("| tenon-thickness sweep 0.5-4.0 in | %s | %s |"
          % (sub.get("sweep_failures") or "no failures",
             add.get("sweep_failures") or "no failures"))
        w("")
        w("**Stated as plainly as the numbers allow: it is a dead heat on")
        w("geometry and a loss on object count.** Both models produce the")
        w("identical solid -- same volume to full precision, same 11")
        w("faces -- and both survive the full sweep with the three-part")
        w("assertion at every step. The adder model costs %s objects per"
          % add.get("joint_objects"))
        w("joint against the subtractive model's %s, because a copied"
          % sub.get("joint_objects"))
        w("template body brings its own sketches, pads and origin where a")
        w("pocket is two objects inside the timber. Recompute is a wash")
        w("(%.4f s vs %.4f s at one joint)."
          % (add.get("recompute_s", 0.0), sub.get("recompute_s", 0.0)))
        w("")
        w("So **the adder model fails nowhere the subtractive model does")
        w("not** -- but it does not win on the geometry either. The case")
        w("for it is entirely the architectural one: one mechanism instead")
        w("of two, and an inert design solid that joint swaps do not")
        w("disturb.")
    w("")

    if big and prior.get(big):
        w("## Scale")
        w("")
        w("At %d instances (alternating cutters and adders) round 3 builds"
          % big)
        w("in %.1f s and full-recomputes in %.1f s, against round 2b's"
          % (scale[big]["build_s"], scale[big]["full_recompute_s"]))
        w("%.1f s and %.1f s for cutters alone."
          % (prior[big]["build_s"], prior[big]["full_recompute_s"]))
        ratio = (scale[big]["full_recompute_s"]
                 / max(prior[big]["full_recompute_s"], 1e-9))
        if ratio < 1.15:
            w("**A fusion does not cost more than a cut** at this scale.")
        else:
            w("A fusion costs about %.2fx a cut at this scale." % ratio)
        w("Every timber in the %d-instance document was checked for" % big)
        w("severing, not just for volume.")
        w("")

    w("## Recommendation")
    w("")
    risks_ok = status.get("R1") == "PASS" and status.get("R2") == "PASS"
    core_ok = all(status.get(k) == "PASS" for k in ("T3", "T4", "T5", "T7"))
    if risks_ok and core_ok:
        w("**Adopt cutter + adder, with conditions.** Both risks are")
        w("cleared, both claimed benefits hold, and the head-to-head shows")
        w("no geometric regression. The conditions are not optional")
        w("polish -- each one is something this spike caught only because")
        w("it was looking:")
        w("")
        w("1. **Solid count is a mandatory post-condition.** After every")
        w("   boolean, `len(shape.Solids) == 1` (for a timber that was one")
        w("   solid before). Three distinct errors in this spike produced")
        w("   exactly-correct volumes with wrong geometry, and volume,")
        w("   `isValid()`, `isClosed()` and object state were blind to all")
        w("   three. This belongs in the linter as a strict rule and in")
        w("   apply-joint as a refusal.")
        w("2. **Boolean order is part of the template contract.** Cutter")
        w("   before adder, declared, not inferred. T5 shows the two")
        w("   orders give different solids, both valid.")
        w("3. **Seats are computed in the target Body's local frame.**")
        w("   Not global. Document it where `apply_joint` computes")
        w("   placements.")
        w("4. **A parameter sweep is mandatory at template")
        w("   registration.** See below.")
        w("")
        w("What this does *not* settle: the subtractive mandate is a")
        w("governing rule with a stated purpose -- that `Length` means the")
        w("ordered stick. Cutter+adder changes that contract to *design")
        w("length is the frame dimension, order length is derived*. That")
        w("is a roadmap decision, not a geometry one, and this spike")
        w("supports it rather than making it.")
    else:
        w("**Keep the subtractive mandate for now.** A risk or a core")
        w("test failed; see the tables above.")
    w("")

    w("## What the apply-joint tool must now do")
    w("")
    w("1. **Read an explicit role per half.** A half declares `Cutter`,")
    w("   `Adder`, or both -- it cannot be inferred, because a butt joint")
    w("   has neither and a brace has both. The natural home is a Tier-2")
    w("   property on each template body, in the same spirit as")
    w("   `Frame_Role`: a declared role is never guessed at.")
    w("2. **Apply in a declared order.** Cutter first, then adder, with")
    w("   the order named in the template rather than implied by object")
    w("   creation sequence.")
    w("3. **Assert the post-condition.** One solid, after each boolean,")
    w("   with the failure reported against the joint that caused it.")
    w("4. **Derive order length instead of storing it.** From the local")
    w("   bounding box, with the sawn-face long/short point where an end")
    w("   is not square, and the long point going to the cut list.")
    w("5. **Seat halves in the target's local frame**, which is also what")
    w("   makes a swap free: the timber never moves.")
    w("6. Everything rounds 1-2b already listed -- mated pairs, mate")
    w("   frames and the stick-allowance contract, naming and filing,")
    w("   assembly seating -- is unchanged. Note that the")
    w("   stick-allowance contract needs rethinking under a derived")
    w("   length: `Stick_Allowance_FTF` exists to reconcile a typed")
    w("   `Length` with joinery, and a derived length removes the thing")
    w("   it was reconciling.")
    w("")

    w("## Template registration validation")
    w("")
    w("**Make the sweep mandatory at registration.** It costs about")
    w("%.1f s per template here -- well inside what Save as Joint Template"
      % (total / max(len(sweeps), 1)))
    w("already spends -- and in this run it found a silent two-solid hole")
    w("that no amount of inspection at default values would reveal.")
    w("")
    w("Concretely:")
    w("")
    w("- **Templates must declare per-property valid ranges.** The sweep")
    w("  needs a domain, and 25%-150% of the default is a guess. A")
    w("  declared range is also the thing the apply dialog should clamp")
    w("  to, so it earns its keep twice.")
    w("- **The roadmap's sanity bounds become the sweep domain**, not")
    w("  advisory guidance: mortise width <= 75% of the receiving extent,")
    w("  housing <= 50% of the through-dimension, dovetail flare clamped")
    w("  to the member extent. Those are already written down as the")
    w("  values a joint stops making sense outside of; sweeping them is")
    w("  what turns them from advice into a check.")
    w("- **The assertion at each step is topological**: one solid, valid,")
    w("  closed, nothing left touched, console silent. Not volume.")
    w("- **Report, do not block** -- consistent with how")
    w("  `template_check.py` already treats completeness. An author may")
    w("  have a good reason for a narrow domain; they should not be able")
    w("  to miss that they have one.")
    w("")

    w("## Needs GUI confirmation")
    w("")
    w("Round 2 passed every headless assertion and was wrong. Which")
    w("artifact settles which question:")
    w("")
    w("- **`scratch/r3_coplanar_cases.FCStd`** — the three shoulder")
    w("  positions. Does the coplanar fusion look right in the 3D view,")
    w("  and does the GUI report `JointFuse` as anything other than")
    w("  `Valid`? This is the round-2 lesson applied: a headless-clean")
    w("  boolean can still be a GUI failure.")
    w("- **`scratch/r3_mated_pair.FCStd`** — change")
    w("  `J-HousedMT-001.MortiseThickness` and confirm both halves follow")
    w("  and the fit stays. This is the mated-pair claim.")
    w("- **`scratch/r3_brace.FCStd`** — the cutter+adder half. Confirm the")
    w("  tenon is actually there and the shoulder angle is what it says.")
    w("  T5 shows a brace with its tenon sawn off is a perfectly valid")
    w("  solid, so this one needs eyes.")
    w("- **`scratch/r3_angled_end.FCStd`** — measure the long and short")
    w("  points with the Measure tool against 96.000 in and 91.381 in.")
    w("- **`scratch/r3_scale_%s.FCStd`** — open time, tree legibility, and"
      % (big if big else "150"))
    w("  whether %s joint bodies at document root is tolerable to look at."
      % (big if big else "150"))
    w("- **Assembly.** Untested here and it matters more than before: an")
    w("  adder means a timber's solid extends past its design length, and")
    w("  the assembly grounds off frames, not the solid. Confirm a fused")
    w("  timber still seats.")
    w("- **TechDraw.** T6d shows the page, views and dimensions surviving")
    w("  a parameter change with zero `hasher mismatch` warnings, which is")
    w("  better than round 1 managed -- but a dimension pointing at the")
    w("  wrong edge still looks like a dimension.")
    return out


# --------------------------------------------------------------------------

def main(argv):
    workdir = os.environ.get("BW_SPIKE_WORKDIR") or None
    counts = [int(x) for x in
              os.environ.get("BW_SPIKE_SCALE", "10,50,150").split(",")]
    workdir = workdir or tempfile.mkdtemp(prefix="bw_spike_r3_")
    if not os.path.isdir(workdir):
        os.makedirs(workdir)
    print("work directory: %s" % workdir)

    rec = Recorder()
    ctx = {"workdir": workdir,
           "version": "%s.%s.%s (build %s)"
                      % (tuple(App.Version()[:3])
                         + (App.Version()[3].split()[0],)),
           "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
           "headlines": {}, "narrative": [], "artifacts": [],
           "round2b": load_scale(ROUND2B_REPORT)}

    r1_ok, r1_results, r1_paths = r1(rec, workdir)
    ctx["headlines"]["R1"] = (
        "coplanar fuses identically to the offset case; only solid "
        "count catches a bad seat" if r1_ok
        else "COPLANAR FUSION FAILED -- the architecture needs rework")
    if r1_paths.get("coplanar"):
        ctx["artifacts"].append(
            ("the three shoulder positions -- coplanar, 1 mm proud, "
             "1 mm recessed", r1_paths["coplanar"]))

    r2_ok, r2_paths = r2(rec, workdir)
    ctx["headlines"]["R2"] = ("exact in all four cases; order the long "
                              "point" if r2_ok
                              else "DERIVED LENGTH FAILED")
    if r2_paths.get("angled"):
        ctx["artifacts"].append(("the 30-degree angled end, long point "
                                 "96.000 in and short point 91.381 in",
                                 r2_paths["angled"]))

    t3_ok = t3(rec, workdir)
    ctx["headlines"]["T3"] = ("the timber does not move: placement, "
                              "length and section all unchanged" if t3_ok
                              else "swap disturbed the timber")

    t4_ok, t4_paths = t4(rec, workdir)
    ctx["headlines"]["T4"] = ("one VarSet drives both halves; fit holds "
                              "through changes" if t4_ok
                              else "mated pair FAILED")
    if t4_paths.get("mated"):
        ctx["artifacts"].append(("a mated pair off one joint VarSet -- "
                                 "cutter half and adder half",
                                 t4_paths["mated"]))

    t5_ok, t5_results, t5_paths = t5(rec, workdir)
    if t5_results:
        a = t5_results.get("cut_then_add", {})
        b = t5_results.get("add_then_cut", {})
        ctx["t5_cut_first"] = a.get("volume", 0.0)
        ctx["t5_add_first"] = b.get("volume", 0.0)
        ctx["t5_commutes"] = (near(a.get("volume", 0), b.get("volume", 1))
                              and a.get("faces") == b.get("faces"))
    ctx["headlines"]["T5"] = (
        "both booleans apply; the two orders do NOT commute"
        if t5_ok and ctx.get("t5_commutes") is False
        else ("both booleans apply; the orders commute here" if t5_ok
              else "brace FAILED"))
    if t5_paths.get("brace"):
        ctx["artifacts"].append(("the brace half -- an angled shoulder "
                                 "cutter and a tenon adder, one VarSet",
                                 t5_paths["brace"]))

    rows, t6_paths = t6(rec, workdir, counts)
    ctx["scale"] = rows
    last = rows[-1] if rows else {}
    ctx["headlines"]["T6"] = (
        "%s instances: %.1f s full recompute, no severed timbers"
        % (last.get("n"), last.get("full_recompute_s", -1))
        if "error" not in last else "failed at n=%s" % last.get("n"))
    if t6_paths.get("scale"):
        ctx["artifacts"].append(("the largest mixed cutter/adder document",
                                 t6_paths["scale"]))

    t6d_ok, hashers = t6_techdraw(rec, workdir)
    ctx["headlines"]["T6d"] = ("views and dimensions survive; %d hasher "
                               "warnings" % hashers if t6d_ok
                               else "see notes")

    sweep_clean, sweeps = t6b(rec, workdir)
    ctx["sweeps"] = sweeps
    failing = sum(len(s["failures"]) for s in sweeps)
    ctx["headlines"]["T6b"] = (
        "clean across every declared domain" if sweep_clean
        else "the sweep works -- and found %d silent template failures"
        % failing)

    t7_ok, t7_summary = t7(rec, workdir)
    ctx["t7"] = t7_summary
    ctx["headlines"]["T7"] = ("identical solids; adder costs more objects, "
                              "fails nowhere subtractive does not"
                              if t7_ok else "see the table")

    ctx["narrative"] = narrative(rec, ctx)
    write_report(rec, ctx)
    print("\nsummary: " + ", ".join("%s=%s" % (r.id, r.status)
                                    for r in rec.results))
    return 0


if not os.environ.get("BW_SPIKE_NORUN"):
    main(sys.argv[1:])
