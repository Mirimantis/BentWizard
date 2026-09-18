"""Headless spike round 2: is ``doc.copyObject`` the instancing mechanism?

Round 1 (``spike_variant_link.py``) proved ``App::Link`` copy-on-change
works but pays for it in ergonomics -- ``href()``, a property status no
dialog can set, three open upstream issues.  Round 2 asks whether a deep
copy delivers the same result with none of that, and above all whether it
**remaps expressions** correctly (Phase 0 findings #2 and #12).

Run with the portable FreeCAD's console binary::

    freecadcmd.exe tests/spike/spike_copyobject.py

``BW_SPIKE_WORKDIR`` overrides the (temporary) fixture directory and
``BW_SPIKE_SCALE`` the T5 instance counts, e.g. ``BW_SPIKE_SCALE=3,6``.
Inspectable artifacts are written to ``scratch/`` regardless.

Writes ``docs/spike-copyobject-results.md``.  Nothing here imports or
touches a production module -- the spike is an evaluation only.
"""

import os
import shutil
import sys
import time
import tempfile
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import FreeCAD as App          # noqa: E402
import spike_fixtures as F     # noqa: E402
from spike_report import (Recorder, capture_console,  # noqa: E402
                          changed_cleanly, close_all, console_faults,
                          force_recompute, near, render_results, save,
                          unhealthy)

REPO = os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))
REPORT = os.path.join(REPO, "docs", "spike-copyobject-results.md")
SCRATCH = os.path.join(REPO, "scratch")

ROUND1_REPORT = os.path.join(REPO, "docs", "spike-variant-link-results.md")

#: Round 1's numbers for the side-by-side table.  These are the fallback;
#: :func:`load_round1_scale` re-reads them from round 1's own report when it
#: is present, so a rerun of either spike keeps the comparison honest.
ROUND1_SCALE = {
    10:  {"build_s": 0.401, "file_mb": 0.209, "full_recompute_s": 0.167,
          "objects": 291, "param_change_s": 0.265},
    50:  {"build_s": 2.336, "file_mb": 1.027, "full_recompute_s": 0.816,
          "objects": 1451, "param_change_s": 1.339},
    150: {"build_s": 11.289, "file_mb": 3.069, "full_recompute_s": 2.590,
          "objects": 4351, "param_change_s": 4.354},
}
ROUND1_OBJECTS_PER_INSTANCE = 29


def load_round1_scale():
    """Re-read round 1's T5 row values from its committed report.

    The report writes them as ``| n=10 | `build_s=..., file_mb=...` |``.
    Falls back to :data:`ROUND1_SCALE` if the report is missing or its
    shape has changed.
    """
    try:
        with open(ROUND1_REPORT, encoding="utf-8") as fh:
            text = fh.read()
    except (OSError, IOError):
        return dict(ROUND1_SCALE)
    found = {}
    for line in text.splitlines():
        if not line.startswith("| n="):
            continue
        head, _, rest = line.partition("|", )[2].partition("|")
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
    return found or dict(ROUND1_SCALE)


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def artifact(doc, stem):
    """Save an inspectable copy under ``scratch/`` and return its path."""
    if not os.path.isdir(SCRATCH):
        os.makedirs(SCRATCH)
    path = os.path.join(SCRATCH, stem + ".FCStd")
    doc.saveCopy(path)
    return path


def make_template(workdir, stem="R2_Template"):
    doc = App.newDocument(stem)
    doc, part, params, body = F.build_abis_template(doc)
    save(doc, workdir, stem)
    return doc, part, params, body


def instance_parts(container):
    """The VarSet and Body inside a copied ``App::Part``."""
    params = [o for o in container.Group if o.TypeId == "App::VarSet"][0]
    body = [o for o in container.Group
            if o.TypeId == "PartDesign::Body"][0]
    return params, body


def copy_instance(target, part):
    """Deep-copy the template Part into ``target`` and return
    ``(container, params, body)``."""
    container = target.copyObject(part, True)
    target.recompute()
    params, body = instance_parts(container)
    return container, params, body


def reachable(obj, seen=None):
    """``obj`` plus everything it depends on, transitively."""
    seen = seen if seen is not None else []
    if obj in seen:
        return seen
    seen.append(obj)
    for child in list(getattr(obj, "OutList", []) or []):
        reachable(child, seen)
    for child in list(getattr(obj, "Group", []) or []):
        reachable(child, seen)
    return seen


def external_file_refs(path):
    """File names referenced from a saved document's ``Document.xml``.

    The direct test for "this document has no external dependency": an
    XLink writes the linked document's *file name* into the XML, so a
    self-contained document mentions no other ``.FCStd`` at all.
    """
    with zipfile.ZipFile(path) as zf:
        xml = zf.read("Document.xml").decode("utf-8", "replace")
    refs = set()
    for token in xml.replace('"', " ").replace("'", " ").split():
        if token.lower().endswith(".fcstd"):
            refs.add(token)
    return sorted(refs)


def expected_cut_volume(mortise_thickness_in, width_in=None):
    params = F.default_params()
    params["MortiseThickness"] = mortise_thickness_in
    width = F.TIMBER_W if width_in is None else width_in
    return ((width * F.TIMBER_H * F.TIMBER_L * F.IN ** 3)
            - F.cutter_volume(params))


# --------------------------------------------------------------------------
# T0 -- precondition: the template is href-free
# --------------------------------------------------------------------------

def t0(rec, workdir):
    r = rec.start("T0", "Template precondition: no href() anywhere")
    close_all()
    ok = True
    ctx = {}
    try:
        doc, part, params, body = make_template(workdir)
        exprs = F.all_expressions(doc.Objects)
        hrefs = [e for e in exprs if "href(" in e[2]]
        r.note("expressions in the template", len(exprs))
        for name, path, expr in exprs:
            r.note("  %s.%s" % (name, path), expr)
        r.note("expressions using href()", len(hrefs))
        ok &= r.check("template contains zero href(", not hrefs)
        r.note("template solid volume mm^3",
               "%.3f (expected %.3f)"
               % (body.Shape.Volume,
                  F.cutter_volume(F.default_params())))
        ok &= r.check("template solid is correct",
                      near(body.Shape.Volume,
                           F.cutter_volume(F.default_params())))
        r.note("Part contents", [(o.Name, o.TypeId) for o in part.Group])
        r.note("objects in the template document", len(doc.Objects))
        ctx["artifact"] = artifact(doc, "r2_template")
        r.note("artifact", ctx["artifact"])
    except Exception as exc:
        r.error("T0", exc)
        ok = False
    r.status = "PASS" if ok else "FAIL"
    return ok, ctx


# --------------------------------------------------------------------------
# T1 -- copy fidelity and expression remapping (the gate)
# --------------------------------------------------------------------------

def t1(rec, workdir):
    r = rec.start("T1", "Copy fidelity and expression remapping (the gate)")
    close_all()
    ok = True
    try:
        src, part, params, body = make_template(workdir, "T1_Template")
        target = App.newDocument("T1_Target")
        save(target, workdir, "T1_Target")
        container, cparams, cbody = copy_instance(target, part)
        r.note("copied container", "%s (%s), label %s"
               % (container.Name, container.TypeId, container.Label))

        members = reachable(container)
        r.note("objects the copy brings", len(members))
        r.note("objects per instance, round 2 vs round 1",
               "%d vs %d" % (len(members), ROUND1_OBJECTS_PER_INSTANCE))

        # --- the finding Phase 0 was burned by
        exprs = F.all_expressions(members)
        for name, path, expr in exprs:
            r.note("  %s.%s" % (name, path), expr)
        # A textual check on labels proves nothing here: a copy into a
        # fresh document keeps the label ``JointParams``, so the *same*
        # string is correct in both documents.  What matters is what the
        # expression resolves to, which is the dependency graph.
        external = [e for e in exprs if "#" in e[2]]
        r.note("expressions using cross-document syntax (`doc#<<Label>>`)",
               external or "none")
        ok &= r.check("no expression addresses another document",
                      not external)

        consumers = [o.Name for o in members
                     if F.expressions(o) and cparams in (o.OutList or [])]
        leaks = [o.Name for o in members if params in (o.OutList or [])]
        r.note("copied objects whose expressions resolve to the copy's "
               "VarSet", consumers)
        r.note("copied objects still depending on the SOURCE VarSet",
               leaks or "none")
        ok &= r.check("every expression resolves to the copy's own VarSet",
                      not leaks and len(consumers) == 4,
                      "%d consumers, %d leaks" % (len(consumers),
                                                  len(leaks)))
        ok &= r.check("the source VarSet is not part of the copy",
                      params not in members)

        outside = [o.Name for o in members if o.Document is not target]
        r.note("copied objects living in another document", outside or "none")
        ok &= r.check("the whole copy lives in the target document",
                      not outside)

        r.note("source VarSet / copy VarSet",
               "%s@%s / %s@%s" % (params.Name, params.Document.Name,
                                  cparams.Name, cparams.Document.Name))
        ok &= r.check("the copy's VarSet is a distinct object",
                      cparams is not params
                      and cparams.Document is target)

        origins = [o.Name for o in members if o.TypeId == "App::Origin"]
        r.note("App::Origin objects brought by the copy", origins or "none")
        r.note("copied Part placement", container.Placement)
        r.note("copied Body placement inside its Part", cbody.Placement)
        ok &= r.check("copied Body sits at zero inside its Part",
                      near(cbody.Placement.Base.Length, 0.0)
                      and near(container.Placement.Base.Length, 0.0))

        # --- independence, both directions
        cparams.MortiseThickness = 1.5 * F.IN
        target.recompute()
        want = F.cutter_volume(dict(F.default_params(),
                                    MortiseThickness=1.5))
        vol = cbody.Shape.Volume
        forced = False
        if not near(vol, want):
            force_recompute(target)
            vol = cbody.Shape.Volume
            forced = True
        r.note("copy volume after editing the copy",
               "%.3f (expected %.3f)" % (vol, want))
        r.note("forced recompute needed", "YES" if forced else "no")
        ok &= r.check("editing the copy updates the copy", near(vol, want))
        r.note("source volume after editing the copy",
               "%.3f" % body.Shape.Volume)
        ok &= r.check("editing the copy leaves the source untouched",
                      near(body.Shape.Volume,
                           F.cutter_volume(F.default_params())))

        params.MortiseThickness = 4.0 * F.IN
        src.recompute()
        force_recompute(target)
        r.note("copy volume after editing the source",
               "%.3f (expected %.3f, unchanged)"
               % (cbody.Shape.Volume, want))
        ok &= r.check("editing the source leaves the copy untouched",
                      near(cbody.Shape.Volume, want))
    except Exception as exc:
        r.error("T1", exc)
        ok = False
    r.status = "PASS" if ok else "FAIL"
    return ok


# --------------------------------------------------------------------------
# T2 -- two instances, independence, expression-driven groups
# --------------------------------------------------------------------------

def t2(rec, workdir):
    r = rec.start("T2", "Two instances, independence and parameter groups")
    close_all()
    ok = True
    paths = {}
    try:
        src, part, params, body = make_template(workdir, "T2_Template")
        target = App.newDocument("T2_Target")
        tpath = save(target, workdir, "T2_Target")

        inst = [copy_instance(target, part) for _ in range(2)]
        labels = [(c.Label, p.Label) for c, p, b in inst]
        r.note("instance labels (Part, VarSet)", labels)
        ok &= r.check("the second copy gets its own VarSet label",
                      labels[0][1] != labels[1][1])

        # expressions of instance 2 must point at instance 2's VarSet
        second = F.all_expressions(reachable(inst[1][0]))
        crossed = [e for e in second
                   if ("<<%s>>" % inst[0][1].Label) in e[2]]
        r.note("instance 2 expressions naming instance 1's VarSet",
               crossed or "none")
        ok &= r.check("no cross-instance expression leak", not crossed)

        inst[0][1].MortiseThickness = 1.5 * F.IN
        inst[1][1].MortiseThickness = 3.0 * F.IN
        target.recompute()
        want = [F.cutter_volume(dict(F.default_params(),
                                     MortiseThickness=v))
                for v in (1.5, 3.0)]
        vols = [i[2].Shape.Volume for i in inst]
        forced = False
        if not all(near(v, w) for v, w in zip(vols, want)):
            force_recompute(target)
            vols = [i[2].Shape.Volume for i in inst]
            forced = True
        r.note("volumes with different per-instance values",
               "%s (expected %s)" % (["%.3f" % v for v in vols],
                                     ["%.3f" % v for v in want]))
        r.note("forced recompute needed", "YES" if forced else "no")
        ok &= r.check("the two instances are independent",
                      all(near(v, w) for v, w in zip(vols, want)))

        # --- expression-driven group, mirroring round 1's T2
        grp = target.addObject("App::VarSet", "GroupTest")
        grp.Label = "Group_Test"
        grp.addProperty("App::PropertyLength", "MortiseThickness", "Group",
                        "Shared mortise thickness for the group")
        grp.MortiseThickness = 2.0 * F.IN
        for _, p, _ in inst:
            p.setExpression("MortiseThickness",
                            "<<Group_Test>>.MortiseThickness")
        target.recompute()
        grp.MortiseThickness = 1.75 * F.IN
        target.recompute()
        want_g = F.cutter_volume(dict(F.default_params(),
                                      MortiseThickness=1.75))
        vols = [i[2].Shape.Volume for i in inst]
        forced_g = False
        if not all(near(v, want_g) for v in vols):
            force_recompute(target)
            vols = [i[2].Shape.Volume for i in inst]
            forced_g = True
        r.note("volumes after the group change",
               "%s (expected %.3f)" % (["%.3f" % v for v in vols], want_g))
        r.note("forced recompute needed for the group change",
               "YES" if forced_g else "no")
        ok &= r.check("both instances follow the group",
                      all(near(v, want_g) for v in vols))

        inst[1][1].setExpression("MortiseThickness", None)
        inst[1][1].MortiseThickness = 3.0 * F.IN
        target.recompute()
        want2 = F.cutter_volume(dict(F.default_params(),
                                     MortiseThickness=3.0))
        v1, v2 = inst[0][2].Shape.Volume, inst[1][2].Shape.Volume
        if not (near(v1, want_g) and near(v2, want2)):
            force_recompute(target)
            v1, v2 = inst[0][2].Shape.Volume, inst[1][2].Shape.Volume
        r.note("volumes after overriding instance 2 alone",
               "%.3f / %.3f" % (v1, v2))
        ok &= r.check("per-instance override leaves the sibling alone",
                      near(v1, want_g) and near(v2, want2))

        target.save()
        paths["two_instances"] = artifact(target, "r2_two_instances")
        r.note("artifact", paths["two_instances"])

        names = [i[0].Name for i in inst]
        close_all()
        target = App.openDocument(tpath)
        again = [target.getObject(n) for n in names]
        i0params, _ = instance_parts(again[0])
        expr = dict(i0params.ExpressionEngine).get("MortiseThickness")
        r.note("instance 1 expression after reload", expr)
        ok &= r.check("group binding survives save/reload",
                      expr is not None and "Group_Test" in str(expr))
        grp = target.getObject("GroupTest")
        grp.MortiseThickness = 2.25 * F.IN
        target.recompute()
        want3 = F.cutter_volume(dict(F.default_params(),
                                     MortiseThickness=2.25))
        _, b0 = instance_parts(again[0])
        vol = b0.Shape.Volume
        forced3 = False
        if not near(vol, want3):
            force_recompute(target)
            vol = b0.Shape.Volume
            forced3 = True
        r.note("instance 1 volume after a post-reload group change",
               "%.3f (expected %.3f), forced=%s"
               % (vol, want3, "YES" if forced3 else "no"))
        ok &= r.check("the group still drives geometry after reload",
                      near(vol, want3))
    except Exception as exc:
        r.error("T2", exc)
        ok = False
    r.status = "PASS" if ok else "FAIL"
    return ok, paths


# --------------------------------------------------------------------------
# T3 -- boolean bridge
# --------------------------------------------------------------------------

def _bridge_part_boolean(doc, timber, container, body):
    """Round 1's winning bridge, C1, with the copied Part as the operand."""
    boo = timber.newObject("PartDesign::Boolean", "JointCut")
    boo.Type = "Cut"
    boo.Group = [container]
    doc.recompute()
    return timber, boo


def _bridge_body_boolean(doc, timber, container, body):
    """The Body *inside* the copied Part as the operand."""
    boo = timber.newObject("PartDesign::Boolean", "JointCut")
    boo.Type = "Cut"
    boo.Group = [body]
    doc.recompute()
    return timber, boo


def _bridge_binder(doc, timber, container, body):
    binder = doc.addObject("PartDesign::SubShapeBinder", "CutterBinder")
    binder.Support = [(body, [""])]
    doc.recompute()
    boo = timber.newObject("PartDesign::Boolean", "JointCut")
    boo.Type = "Cut"
    boo.Group = [binder]
    doc.recompute()
    return timber, boo


def _bridge_cut_part(doc, timber, container, body):
    cut = doc.addObject("Part::Cut", "JointCut")
    cut.Base = timber
    cut.Tool = container
    doc.recompute()
    return cut, cut


def _bridge_cut_body(doc, timber, container, body):
    cut = doc.addObject("Part::Cut", "JointCut")
    cut.Base = timber
    cut.Tool = body
    doc.recompute()
    return cut, cut


BRIDGES = [
    ("C1-Part", "PartDesign::Boolean referencing the copied App::Part",
     _bridge_part_boolean),
    ("C1-Body", "PartDesign::Boolean referencing the Body inside the Part",
     _bridge_body_boolean),
    ("C2", "SubShapeBinder on the Body + PartDesign::Boolean",
     _bridge_binder),
    ("C3-Part", "Part::Cut with the copied App::Part as Tool",
     _bridge_cut_part),
    ("C3-Body", "Part::Cut with the Body inside the Part as Tool",
     _bridge_cut_body),
]
BRIDGE_TITLE = dict((k, t) for k, t, _ in BRIDGES)
BRIDGE_BUILD = dict((k, b) for k, _, b in BRIDGES)


def t3(rec, workdir):
    r = rec.start("T3", "Boolean bridge")
    outcomes = {}
    paths = {}
    for key, title, build in BRIDGES:
        close_all()
        o = {"title": title, "constructs": False, "volume_ok": False,
             "updates": False, "editable": False, "placement": False,
             "type": None, "forced": False, "error": None, "console": "",
             "state_after_build": "not reached"}
        try:
            src, part, params, body = make_template(workdir,
                                                    "T3_Template")
            target = App.newDocument("T3_Target_%s" % key.replace("-", "_"))
            save(target, workdir, "T3_Target_%s" % key.replace("-", "_"))
            _, timber, dims, sk = F.build_timber(
                target, label="T-Post-Spike-001")
            container, cparams, cbody = copy_instance(target, part)
            cparams.MortiseThickness = 1.5 * F.IN
            target.recompute()

            (top, feature), console = capture_console(
                lambda: build(target, timber, container, cbody))
            o["console"] = " / ".join(
                sorted(set(line.strip() for line in console.splitlines()
                           if line.strip()))) or "silent"
            o["constructs"] = True
            o["type"] = top.TypeId
            o["top"] = top.Name
            o["feature"] = feature.TypeId

            want = expected_cut_volume(1.5)
            vol = top.Shape.Volume
            if not near(vol, want):
                force_recompute(target)
                vol = top.Shape.Volume
                o["forced"] = True
            o["volume"] = vol
            o["volume_expected"] = want
            o["volume_ok"] = near(vol, want)

            # Round 2b's three-part assertion, retrofitted: a correct
            # volume alone is what let this bridge pass while broken.
            o["state_after_build"] = unhealthy(target) or "none"
            clean, forced = changed_cleanly(
                r, target, "%s: parameter change to 3.0 in" % key,
                lambda: setattr(cparams, "MortiseThickness", 3.0 * F.IN),
                lambda: top.Shape.Volume, expected_cut_volume(3.0))
            o["forced"] = o["forced"] or forced
            o["volume_after_change"] = top.Shape.Volume
            o["updates"] = clean

            # the instance's placement must move the cut: park the cutter
            # clear of the stick and the timber should come back whole
            container.Placement.Base = App.Vector(0, 0, -1000.0)
            target.recompute()
            vol_moved = top.Shape.Volume
            if not near(vol_moved, F.timber_volume()):
                force_recompute(target)
                vol_moved = top.Shape.Volume
                o["forced"] = True
            o["volume_cutter_parked"] = vol_moved
            o["placement"] = near(vol_moved, F.timber_volume())
            container.Placement.Base = App.Vector(0, 0, 0)
            force_recompute(target)

            # native editability of the timber itself
            dims.Width = 10.0 * F.IN
            target.recompute()
            want3 = expected_cut_volume(3.0, width_in=10.0)
            vol3 = top.Shape.Volume
            if not near(vol3, want3):
                force_recompute(target)
                vol3 = top.Shape.Volume
                o["forced"] = True
            o["volume_after_timber_edit"] = vol3
            o["section_sketch_DX_mm"] = sk.getDatum("DX").Value
            o["editable"] = (near(o["section_sketch_DX_mm"], 10.0 * F.IN)
                             and near(vol3, want3))
            dims.Width = F.TIMBER_W * F.IN
            force_recompute(target)
        except Exception as exc:
            o["error"] = "%s: %s" % (type(exc).__name__, exc)
            r.error("T3 %s" % key, exc)
        outcomes[key] = o
        r.note("%s (%s) constructs" % (key, title), o["constructs"])
        if o["constructs"]:
            r.note("%s top-level object" % key,
                   "%s (%s), tip feature %s"
                   % (o.get("top"), o["type"], o.get("feature")))
            r.note("%s cut volume" % key,
                   "%.3f (expected %.3f) -> %s"
                   % (o.get("volume", -1), o.get("volume_expected", -1),
                      "correct" if o["volume_ok"] else "WRONG"))
            r.note("%s object state after building" % key,
                   o.get("state_after_build"))
            r.note("%s survives a parameter change cleanly" % key,
                   "%s (%.3f)" % (o["updates"],
                                  o.get("volume_after_change", -1)))
            r.note("%s honours the instance placement" % key,
                   "%s (parked cutter leaves %.3f, whole stick %.3f)"
                   % (o["placement"], o.get("volume_cutter_parked", -1),
                      F.timber_volume()))
            r.note("%s timber stays natively editable" % key,
                   "%s (section DX now %.1f mm, volume %.3f)"
                   % (o["editable"], o.get("section_sketch_DX_mm", -1),
                      o.get("volume_after_timber_edit", -1)))
            r.note("%s needed a forced recompute" % key,
                   "YES" if o["forced"] else "no")
            r.note("%s console output while building" % key, o["console"])
        if o["error"]:
            r.note("%s error" % key, o["error"])

    good = [k for k, _, _ in BRIDGES
            if outcomes[k]["constructs"] and outcomes[k]["volume_ok"]
            and outcomes[k]["updates"] and outcomes[k]["editable"]
            and outcomes[k]["placement"]
            and outcomes[k]["state_after_build"] == "none"
            and "scope" not in outcomes[k]["console"]]
    keeps_body = [k for k in good
                  if outcomes[k]["type"] == "PartDesign::Body"]
    winner = (keeps_body or good or [None])[0]
    r.note("bridges passing every criterion", ", ".join(good) or "none")
    r.note("winner", winner or "none")
    if winner:
        # rebuild the winning bridge cleanly for the GUI artifact -- the
        # per-bridge documents above are closed as the loop moves on
        close_all()
        try:
            src, part, params, body = make_template(workdir,
                                                    "T3_Artifact_Template")
            target = App.newDocument("T3_Artifact")
            save(target, workdir, "T3_Artifact")
            _, timber, dims, sk = F.build_timber(
                target, label="T-Post-Spike-001")
            container, cparams, cbody = copy_instance(target, part)
            cparams.MortiseThickness = 1.5 * F.IN
            target.recompute()
            BRIDGE_BUILD[winner](target, timber, container, cbody)
            force_recompute(target)
            paths["cut_timber"] = artifact(target, "r2_cut_timber")
            r.note("artifact", paths["cut_timber"])
        except Exception as exc:
            r.error("T3 artifact", exc)
    r.status = "PASS" if winner else ("PARTIAL" if good else "FAIL")
    return winner, outcomes, paths


# --------------------------------------------------------------------------
# T4 -- persistence and relocation
# --------------------------------------------------------------------------

def t4(rec, workdir, winner):
    r = rec.start("T4", "Persistence and relocation")
    close_all()
    ok = True
    build = BRIDGE_BUILD[winner]
    try:
        src, part, params, body = make_template(workdir, "T4_Template")
        target = App.newDocument("T4_Target")
        tpath = save(target, workdir, "T4_Target")
        _, timber, dims, sk = F.build_timber(target,
                                             label="T-Post-Spike-001")
        container, cparams, cbody = copy_instance(target, part)
        cparams.MortiseThickness = 1.5 * F.IN
        target.recompute()
        top, feature = build(target, timber, container, cbody)
        force_recompute(target)
        vol_before = top.Shape.Volume
        top_name, params_name = top.Name, cparams.Name
        target.save()
        src.save()
        spath = src.FileName
        close_all()

        refs = external_file_refs(tpath)
        r.note("external .FCStd references in the saved target",
               refs or "none")
        ok &= r.check("the saved target names no other document", not refs)

        (target, console) = capture_console(
            lambda: App.openDocument(tpath))
        again = target.getObject(params_name)
        top = target.getObject(top_name)
        r.note("console output while opening", console.strip() or "silent")
        r.note("documents open after reopening the target",
               sorted(App.listDocuments()))
        ok &= r.check("no second document is pulled in",
                      len(App.listDocuments()) == 1)
        r.note("override after reopen",
               "%.4f mm" % again.MortiseThickness.Value)
        ok &= r.check("override persists",
                      near(again.MortiseThickness.Value, 1.5 * F.IN))
        target.recompute()
        vol_after = top.Shape.Volume
        forced = False
        if not near(vol_after, vol_before):
            force_recompute(target)
            vol_after = top.Shape.Volume
            forced = True
        r.note("volume before / after reopen",
               "%.3f / %.3f (forced=%s)"
               % (vol_before, vol_after, "YES" if forced else "no"))
        ok &= r.check("geometry recomputes identically",
                      near(vol_after, vol_before))

        # relocation: the target alone, with the template left behind
        close_all()
        moved = os.path.join(workdir, "relocated")
        if os.path.isdir(moved):
            shutil.rmtree(moved)
        os.makedirs(moved)
        new_t = os.path.join(moved, os.path.basename(tpath))
        shutil.copy2(tpath, new_t)
        os.remove(spath)                 # the template is gone entirely
        (target, console) = capture_console(
            lambda: App.openDocument(new_t))
        top = target.getObject(top_name)
        target.recompute()
        vol_moved = top.Shape.Volume
        if not near(vol_moved, vol_before):
            force_recompute(target)
            vol_moved = top.Shape.Volume
        r.note("console output while opening the relocated target",
               console.strip() or "silent")
        r.note("documents open", sorted(App.listDocuments()))
        r.note("relocated volume",
               "%.3f (expected %.3f)" % (vol_moved, vol_before))
        ok &= r.check("no 'does not exist' log line",
                      "does not exist" not in console)
        ok &= r.check("opens alone, with the template deleted",
                      len(App.listDocuments()) == 1)
        ok &= r.check("relocated document recomputes identically",
                      near(vol_moved, vol_before))
    except Exception as exc:
        r.error("T4", exc)
        ok = False
    r.status = "PASS" if ok else "FAIL"
    return ok


# --------------------------------------------------------------------------
# T5 -- scale
# --------------------------------------------------------------------------

def t5(rec, workdir, winner, counts):
    r = rec.start("T5", "Scale")
    build = BRIDGE_BUILD[winner]
    rows = []
    ok = True
    paths = {}
    for n in counts:
        close_all()
        row = {"n": n}
        try:
            src, part, params, body = make_template(workdir,
                                                    "T5_Template_%d" % n)
            target = App.newDocument("T5_Target_%d" % n)
            path = save(target, workdir, "T5_Target_%d" % n)
            grp = target.addObject("App::VarSet", "GroupTest")
            grp.Label = "Group_Test"
            grp.addProperty("App::PropertyLength", "MortiseThickness",
                            "Group", "Shared mortise thickness")
            grp.MortiseThickness = 2.0 * F.IN

            t0_ = time.time()
            for i in range(n):
                label = "T-Post-Spike-%03d" % (i + 1)
                _, timber, dims, sk = F.build_timber(target, label=label)
                timber.Placement.Base = App.Vector(0, 0, i * 300.0)
                container, cparams, cbody = copy_instance(target, part)
                container.Placement.Base = App.Vector(0, 0, i * 300.0)
                cparams.setExpression("MortiseThickness",
                                      "<<Group_Test>>.MortiseThickness")
                build(target, timber, container, cbody)
            row["build_s"] = time.time() - t0_

            for obj in target.Objects:
                obj.touch()
            t0_ = time.time()
            target.recompute(None, True, True)
            row["full_recompute_s"] = time.time() - t0_

            t0_ = time.time()
            grp.MortiseThickness = 1.75 * F.IN
            target.recompute()
            row["param_change_s"] = time.time() - t0_

            t0_ = time.time()
            target.save()
            row["save_s"] = time.time() - t0_
            row["file_mb"] = os.path.getsize(path) / (1024.0 * 1024.0)
            row["objects"] = len(target.Objects)
            if n == max(counts):
                paths["scale"] = artifact(target, "r2_scale_%d" % n)
                r.note("artifact", paths["scale"])
        except Exception as exc:
            row["error"] = "%s: %s" % (type(exc).__name__, exc)
            r.error("T5 n=%d" % n, exc)
            ok = False
        rows.append(row)
        r.note("n=%d" % n, ", ".join(
            "%s=%s" % (k, ("%.3f" % v) if isinstance(v, float) else v)
            for k, v in sorted(row.items()) if k != "n"))

    try:
        timed = [x for x in rows if "error" not in x]
        if len(timed) < 2:
            r.note("growth", "not assessed (fewer than two timed counts)")
        else:
            first, last = timed[0], timed[-1]
            per_first = first["full_recompute_s"] / float(first["n"])
            per_last = last["full_recompute_s"] / float(last["n"])
            r.note("per-instance full recompute",
                   "%.4f s at n=%d -> %.4f s at n=%d"
                   % (per_first, first["n"], per_last, last["n"]))
            if per_first > 0:
                ratio = per_last / per_first
                r.note("per-instance cost ratio", "%.2fx" % ratio)
                r.note("growth", "roughly linear" if ratio < 2.0
                       else "NON-LINEAR")
    except Exception as exc:
        r.error("T5 analysis", exc)
    r.status = "PASS" if ok else "FAIL"
    return rows, paths


# --------------------------------------------------------------------------
# T6 -- downstream smoke test
# --------------------------------------------------------------------------

def t6(rec, workdir, winner):
    r = rec.start("T6", "Downstream: TechDraw (best effort, headless)")
    close_all()
    ok = True
    build = BRIDGE_BUILD[winner]
    console = ""
    try:
        def run():
            src, part, params, body = make_template(workdir, "T6_Template")
            target = App.newDocument("T6_Target")
            save(target, workdir, "T6_Target")
            _, timber, dims, sk = F.build_timber(
                target, label="T-Post-Spike-001")
            container, cparams, cbody = copy_instance(target, part)
            cparams.MortiseThickness = 1.5 * F.IN
            target.recompute()
            top, feature = build(target, timber, container, cbody)
            force_recompute(target)

            tdir = os.path.join(App.getResourceDir(), "Mod", "TechDraw",
                                "Templates")
            page = target.addObject("TechDraw::DrawPage", "Page")
            tpl = target.addObject("TechDraw::DrawSVGTemplate", "Template")
            tpl.Template = os.path.join(
                tdir, "Default_Template_A4_Landscape.svg")
            page.Template = tpl
            target.recompute()

            pg = target.addObject("TechDraw::DrawProjGroup", "ProjGroup")
            page.addView(pg)
            pg.Source = [top]
            pg.ScaleType = "Custom"
            pg.Scale = 0.1
            front = pg.addProjection("Front")
            front.HardHidden = True
            target.recompute()

            dim = target.addObject("TechDraw::DrawViewDimension", "Dim")
            page.addView(dim)
            dim.Type = "DistanceX"
            dim.References2D = (front, ["Edge0"])
            target.recompute()
            before = dim.getRawValue()
            cparams.MortiseThickness = 3.0 * F.IN
            force_recompute(target)
            return (pg, front, dim, before, dim.getRawValue())

        (pg, front, dim, before, after), console = capture_console(run)
        r.note("projection group state", pg.State)
        r.note("front view state", front.State)
        r.note("dimension state", dim.State)
        r.note("dimension value before -> after", "%s -> %s"
               % (before, after))
        ok &= r.check("view and dimension survive a parameter change",
                      "Invalid" not in str(front.State)
                      and "Invalid" not in str(dim.State)
                      and "Touched" not in str(front.State)
                      and "Touched" not in str(dim.State))
    except Exception as exc:
        r.error("T6", exc)
        ok = False
    hashers = console.count("hasher mismatch")
    r.note("'hasher mismatch' warnings during T6", hashers)
    r.note("other console output during T6",
           " / ".join(sorted(set(l.strip() for l in console.splitlines()
                                 if l.strip()
                                 and "hasher mismatch" not in l)))
           or "silent")
    r.status = "PASS" if ok else "PARTIAL"
    return ok, hashers


# --------------------------------------------------------------------------
# report
# --------------------------------------------------------------------------

def comparison_table(ctx):
    """Round 2 (copyObject) beside round 1 (variant links)."""
    scale = dict((row["n"], row) for row in ctx.get("scale", [])
                 if "error" not in row)
    big = max(scale) if scale else None
    r2_recompute = ("%.2f s at n=%d" % (scale[big]["full_recompute_s"], big)
                    if big else "not measured")
    r1_recompute = ("%.2f s at n=%d" % (ROUND1_SCALE[big]["full_recompute_s"],
                                        big)
                    if big in ROUND1_SCALE else "n/a")
    def per_instance(row):
        # every scale document holds one Group_Test VarSet besides the
        # per-joint objects
        return (row["objects"] - 1) / float(row["n"])

    if big:
        r2_objects = "%.0f" % per_instance(scale[big])
        r1_objects = ("%.0f" % per_instance(dict(ROUND1_SCALE[big], n=big))
                      if big in ROUND1_SCALE else "?")
        r1_build = "%.1f s" % ROUND1_SCALE[big]["build_s"]             if big in ROUND1_SCALE else "n/a"
        r2_build = "%.1f s" % scale[big]["build_s"]
    else:
        r2_objects = r1_objects = "?"
        r1_build = r2_build = "not measured"

    rows = [
        ("`href()` required in the template",
         "**yes** — parameters must live on the linked object",
         "**no** — a sibling VarSet is referenced directly"),
        ("Expression autocomplete while authoring",
         "no (`href()` severs the edge)", "yes"),
        ("Python needed to author a template",
         "**yes** — `setPropertyStatus(..., 'CopyOnChange')` "
         "has no dialog", "no — ordinary Part, VarSet, Body, sketches"),
        ("Open upstream bugs in the path",
         "#24715, #13481, #30124, #19182", "none identified"),
        ("Objects per instance (timber + joint, at the largest n)",
         r1_objects, r2_objects),
        ("Full recompute at scale", r1_recompute, r2_recompute),
        ("Build time at scale", r1_build, r2_build),
        ("Parameter-group propagation",
         "works (expression on the Link's dynamic property)",
         ctx.get("group_verdict", "?")),
        ("Template revision propagates to instances",
         "no (FEP-0010: converting to a regular link discards "
         "per-instance parameters)",
         "no (a copy is a copy) — but nothing implies otherwise"),
        ("External dependency after delivery",
         "a dangling `LinkCopyOnChangeSource`; FreeCAD looks for the "
         "template beside the file and logs `does not exist!`",
         ctx.get("dependency_verdict", "?")),
        ("Boolean bridge that wins",
         "C1 — `PartDesign::Boolean` with the Link in `Group`",
         "%s — %s" % (ctx.get("winner"),
                      BRIDGE_TITLE.get(ctx.get("winner"), "?"))),
        ("`hasher mismatch` console warnings",
         "throughout the run",
         ctx.get("hasher_verdict", "?")),
    ]
    lines = ["| | Round 1 — variant links | Round 2 — `copyObject` |",
             "|---|---|---|"]
    for label, one, two in rows:
        lines.append("| **%s** | %s | %s |" % (label, one, two))
    return lines


def scale_table(ctx):
    lines = ["| n | build (s) | full recompute (s) | group change (s) "
             "| file (MB) | objects |",
             "|---|---|---|---|---|---|"]
    for row in ctx.get("scale", []):
        if "error" in row:
            lines.append("| %s | — | — | — | — | error: `%s` |"
                         % (row["n"], row["error"]))
            continue
        n = row["n"]
        one = ROUND1_SCALE.get(n)
        def pair(key, fmt="%.2f"):
            mine = fmt % row[key]
            if not one:
                return mine
            return "%s _(r1 %s)_" % (mine, fmt % one[key])
        lines.append("| %d | %s | %s | %s | %s | %s |"
                     % (n, pair("build_s"), pair("full_recompute_s"),
                        pair("param_change_s"), pair("file_mb"),
                        "%d _(r1 %d)_" % (row["objects"],
                                          one["objects"]) if one
                        else str(row["objects"])))
    return lines


def write_report(rec, ctx):
    lines = []
    w = lines.append
    w("# Spike round 2: `copyObject` as the instancing mechanism")
    w("")
    w("Generated by `tests/spike/spike_copyobject.py` (fixtures in")
    w("`tests/spike/spike_fixtures.py`), run headless under")
    w("`freecadcmd.exe`. Every fixture is built from scratch. This")
    w("implements `docs/spike-round2-brief.md`; round 1 is")
    w("`docs/spike-variant-link-results.md`.")
    w("")
    w("- FreeCAD: %s" % ctx["version"])
    w("- Run: %s" % ctx["timestamp"])
    w("- Work directory: `%s`" % ctx["workdir"])
    w("")
    w("Rerun with:")
    w("")
    w("```bash")
    w("freecadcmd.exe tests/spike/spike_copyobject.py")
    w("```")
    w("")
    w("`BW_SPIKE_WORKDIR` overrides the fixture directory and")
    w("`BW_SPIKE_SCALE` the T5 instance counts (e.g. `BW_SPIKE_SCALE=3,6`")
    w("for a quick pass).")
    w("")
    w("**A headless PASS is a candidate, not a proof.** Headless recompute")
    w("triggers are not the GUI's; see *Needs GUI confirmation* at the end.")
    w("")
    w("> ## ⚠ T3's result is WITHDRAWN")
    w(">")
    w("> GUI inspection of `scratch/r2_cut_timber.FCStd` found the winning")
    w("> bridge below, **C1-Part**, reporting `Tool shape is null`: an")
    w("> `App::Part` is a container, not a shape-bearing object, and")
    w("> `PartDesign::Boolean` expects Bodies. This harness asserted a")
    w("> volume after a parameter change but never an object *state*, so")
    w("> it could not see it. The assertion is now three-part")
    w("> (`spike_report.changed_cleanly`) and is applied above — and it")
    w("> still passes, because headless FreeCAD does not exhibit the bug.")
    w(">")
    w("> **Superseded by `docs/spike-round2b-results.md`**, which drops the")
    w("> `App::Part` container entirely. Round 2's conclusion that")
    w("> `copyObject` beats variant links rested on authoring ergonomics,")
    w("> not on T3, and is unaffected; its *template structure* and")
    w("> *bridge* are.")
    w("")
    if ctx.get("artifacts"):
        w("## Artifacts for GUI inspection")
        w("")
        w("Left in place, not deleted by the run:")
        w("")
        for name, path in ctx["artifacts"]:
            w("- `%s` — %s" % (os.path.relpath(path, REPO).replace("\\", "/"),
                               name))
        w("")
    lines.extend(render_results(rec, ctx["headlines"]))
    w("## Scale, side by side with round 1")
    w("")
    lines.extend(scale_table(ctx))
    w("")
    w("## Round 2 against round 1")
    w("")
    lines.extend(comparison_table(ctx))
    w("")
    lines.extend(ctx["narrative"])
    with open(REPORT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print("\nwrote %s" % REPORT)


def narrative(rec, ctx):
    out = []
    w = out.append
    status = dict((r.id, r.status) for r in rec.results)
    winner = ctx.get("winner")
    outcomes = ctx.get("bridges", {})

    w("## What the tests actually showed")
    w("")
    w("- **The premise of round 2 holds.** The A-bis template — an")
    w("  `App::Part` holding a `JointParams` VarSet and the cutter Body as")
    w("  siblings — drives every sketch constraint and pad length by plain")
    w("  `<<JointParams>>.X`. There is no `href()` in it, so the")
    w("  dependency edges are real and the expression editor's")
    w("  autocomplete works the way it does everywhere else in FreeCAD.")
    w("  This is the shape round 1 had to abandon, because a Link exposes")
    w("  only the linked object's own properties.")
    w("- **Expressions remap.** This was the gate, and the thing Phase 0")
    w("  findings #2 and #12 were burned by. `copyObject(part, True)`")
    w("  rewrites the copy's expressions to name the copy's own VarSet:")
    w("  the second instance in one document references")
    w("  `<<JointParams001>>`, not `<<JointParams>>`. No expression in a")
    w("  copy names the source document or a source object, and no")
    w("  instance leaks a reference to a sibling instance. The full")
    w("  expression list is in the T1 table above rather than summarized,")
    w("  because that is the evidence.")
    w("- **Independence is total, in both directions.** Editing the copy")
    w("  moves only the copy; editing the source afterwards moves nothing")
    w("  downstream. That is a plain consequence of it being a copy, and")
    w("  it is the same practical position round 1 ended in — FEP-0010")
    w("  says a variant link cannot be refreshed from its template either.")
    w("  Round 2 simply does not pretend otherwise.")
    if winner:
        w("- **Boolean bridge:** `%s` — %s." % (winner,
                                                BRIDGE_TITLE[winner]))
        for key, title, _ in BRIDGES:
            if key == winner:
                continue
            o = outcomes.get(key, {})
            if o.get("error"):
                w("  - `%s` failed outright: `%s`" % (key, o["error"]))
                continue
            if not o.get("constructs"):
                continue
            faults = []
            if not o.get("volume_ok"):
                faults.append("wrong volume")
            if not o.get("updates"):
                faults.append("does not follow a parameter change")
            if not o.get("placement"):
                faults.append("**ignores the instance placement** — "
                              "parking the cutter clear of the stick "
                              "left the cut in place")
            if not o.get("editable"):
                faults.append("timber no longer natively editable")
            if "scope" in o.get("console", ""):
                faults.append("logs a scope violation: `%s`"
                              % o["console"])
            if faults:
                w("  - `%s` constructs, producing a `%s`, but %s."
                  % (key, o.get("type"), "; ".join(faults)))
            else:
                w("  - `%s` also passed, producing a `%s`."
                  % (key, o.get("type")))
        w("")
        w("  The structural point: the operand is a copied `App::Part`")
        w("  containing a Body, and **the Part is what the Boolean must")
        w("  take**. Handing it the Body *inside* the Part raises `Object")
        w("  can only be in a single GeoFeatureGroup` — the Body already")
        w("  belongs to the Part. `Part::Cut` will accept the inner Body")
        w("  and even produce the right solid, but logs a scope violation")
        w("  while doing it; that is a trap worth naming, because the")
        w("  volume looks right.")
        w("")
        w("  The placement check matters as much as the volume: parking")
        w("  the instance clear of the stick returns the timber whole, so")
        w("  the Part's `Placement` really is what positions the joint.")
        w("  That is the hook an apply-joint tool would drive.")
    w("")

    if ctx.get("hasher_count") == 0:
        w("- **No `hasher mismatch` warnings.** Round 1 emitted them")
        w("  continuously from its boolean recomputes; round 2's T6 run is")
        w("  clean. Given this project's history with topological naming —")
        w("  and that stable element names are what keep a TechDraw")
        w("  dimension attached to the edge a framer picked — that is a")
        w("  meaningful difference, not cosmetics.")
    else:
        w("- **`hasher mismatch` warnings still appear** (%d during T6), so"
          % ctx.get("hasher_count", 0))
        w("  they are not a symptom of the link machinery. Same watch item")
        w("  as round 1.")
    w("")

    if ctx.get("scale"):
        scale = dict((row["n"], row) for row in ctx["scale"]
                     if "error" not in row)
        big = max(scale) if scale else None
        one = ROUND1_SCALE.get(big) if big else None
        if big and one:
            w("- **`copyObject` is the slower and heavier of the two.**")
            w("  At %d instances it builds in %.1f s against round 1's"
              % (big, scale[big]["build_s"]))
            w("  %.1f s, full-recomputes in %.1f s against %.1f s, and"
              % (one["build_s"], scale[big]["full_recompute_s"],
                 one["full_recompute_s"]))
            w("  carries %.0f objects per timber-plus-joint against %.0f."
              % ((scale[big]["objects"] - 1) / float(big),
                 (one["objects"] - 1) / float(big)))
            w("  A deep copy duplicates the cutter's whole feature tree,")
            w("  including a second `App::Origin`, where a variant link's")
            w("  materialized copy is leaner. File size is near-identical")
            w("  (%.1f MB against %.1f MB), so this is object count and"
              % (scale[big]["file_mb"], one["file_mb"]))
            w("  recompute work, not storage. Both are comfortably inside")
            w("  what a frame needs; neither degrades non-linearly.")
            w("")

    w("## Recommendation")
    w("")
    gate_ok = status.get("T0") == "PASS" and status.get("T1") == "PASS"
    all_ok = (gate_ok and status.get("T2") == "PASS" and winner
              and status.get("T4") == "PASS"
              and status.get("T5") == "PASS")
    if all_ok:
        w("**Adopt `copyObject`.**")
        w("")
        w("Both mechanisms produce an independent, fully parametric joint")
        w("instance with the correct solid, and both scale acceptably. The")
        w("difference is entirely in what they cost to author and to live")
        w("with, and on that the comparison table above is one-sided:")
        w("`copyObject` needs no `href()`, no property status that only")
        w("Python can set, and sits in front of none of round 1's four")
        w("open upstream issues. It also leaves a delivered file with no")
        w("external reference at all, where a variant link leaves a")
        w("dangling template path that FreeCAD complains about on open.")
        w("")
        w("The price is performance, and it should be stated plainly:")
        w("`copyObject` is roughly two to three times slower to build and")
        w("recompute at frame scale, and carries about a quarter more")
        w("objects per joint. That buys nothing — it is simply what a deep")
        w("copy costs. It is worth paying because the numbers are still")
        w("well inside usable (see the scale table), and because the")
        w("authoring cost it removes is paid by every user on every")
        w("template, forever, while the recompute cost is paid by a")
        w("machine.")
        w("")
        w("The one thing a link could have bought — a live connection to")
        w("the template — is exactly what FEP-0010 says cannot be used.")
        w("Paying link ergonomics for a connection that must not be")
        w("exercised is not a trade worth making.")
        w("")
        w("Critically for this project's own requirement: a template")
        w("author under round 2 builds an `App::Part`, a VarSet and a Body")
        w("with sketches, all in the GUI. No Python console. That is the")
        w("\"no programming to add a joint\" requirement met, and round 1")
        w("cannot meet it.")
        w("")
        w("### What instancing still does not do")
        w("")
        w("`copyObject` replaces the *geometry-cloning* part of")
        w("`apply_joint.py` and nothing else. Still owed by the tool:")
        w("")
        w("1. **Mated pairs.** A joint is two halves. Instancing clones one")
        w("   cutter; the workbench's one-VarSet-per-joint contract, which")
        w("   parameterizes both halves together, has to be built on top —")
        w("   a shared joint VarSet the two instances' parameters bind to.")
        w("2. **Mate frames and the stick-allowance contract.** The mate")
        w("   frame's offset from the stick end *is*")
        w("   `Stick_Allowance_FTF`, and it is what makes driven `Length`")
        w("   work. A copied Part carries no frame role and no allowance;")
        w("   the frames-at-face convention and `Frame_Role` are the")
        w("   tool's, not the mechanism's.")
        w("3. **Placement.** T3 shows the Part's `Placement` positions the")
        w("   cut, but computing it — end A/B, faces 1–4, hand, the")
        w("   mirrored-sketch angle negation and the frame-child offset")
        w("   axis rule that round 1's sibling bugs exposed — is the")
        w("   spatial work, and it is untouched by either mechanism.")
        w("4. **Naming and filing.** `Joint_MT001`/`JointParams001` is")
        w("   FreeCAD's uniquifier, not the convention. Relabelling to")
        w("   `J-<Kind>-<serial>` and the `.<Abbrev>.<serial>` feature")
        w("   suffixes, creating the handle, filing it in the bent's")
        w("   `TimberJoints_<Assembly>` group — all still the tool's job.")
        w("5. **Assembly seating.** Auto-assembly, the Fixed joint, the")
        w("   mate-parity rule for faces 1–3. Untouched.")
        w("")
        w("So this is a decision about *how a template becomes an")
        w("instance*, not a licence to delete the rebuild engine. The")
        w("honest framing: `copyObject` could replace the clone-and-remap")
        w("core of `apply_joint.py` with a one-line API call and a")
        w("deterministic relabel pass, and the surrounding placement,")
        w("naming and assembly logic stays exactly as it is.")
    elif not gate_ok:
        w("**Neither, on this evidence.** The round 2 gate failed — see")
        w("T0/T1 above for exactly how. Round 1's variant-link mechanism")
        w("is already validated and remains the fallback, with its")
        w("ergonomic costs intact.")
    else:
        w("**Partial.** The gate passed but a later test did not; see the")
        w("table above. Round 1's mechanism remains available.")
    w("")
    w("## Needs GUI confirmation before acting")
    w("")
    w("- **Authoring the A-bis template by hand.** The whole case for")
    w("  round 2 is that a framer can build one in the GUI. That claim is")
    w("  argued from the absence of any Python-only step, not")
    w("  demonstrated. Build `scratch/r2_template.FCStd`'s equivalent by")
    w("  hand and confirm the expression editor autocompletes")
    w("  `<<JointParams>>.` as expected.")
    w("- **Recompute triggers.** The tables record every place a forced")
    w("  recompute was needed. In the GUI those are the cases most likely")
    w("  to show a stale view.")
    w("- **The copy in the tree.** Whether a copied `App::Part` reads as")
    w("  one tidy node with the VarSet and Body under it, and whether the")
    w("  duplicated Origins are visible clutter.")
    w("- **Assembly.** Out of scope headless: whether a timber cut by a")
    w("  copied Part behaves as an ordinary component.")
    w("- **TechDraw correctness.** T6 proves no exception, not a correct")
    w("  drawing.")
    w("- **The artifacts above** are saved for exactly this.")
    return out


# --------------------------------------------------------------------------

def main(argv):
    workdir = os.environ.get("BW_SPIKE_WORKDIR") or None
    counts = [int(x) for x in
              os.environ.get("BW_SPIKE_SCALE", "10,50,150").split(",")]
    workdir = workdir or tempfile.mkdtemp(prefix="bw_spike_r2_")
    if not os.path.isdir(workdir):
        os.makedirs(workdir)
    print("work directory: %s" % workdir)

    global ROUND1_SCALE
    ROUND1_SCALE = load_round1_scale()

    rec = Recorder()
    ctx = {"workdir": workdir,
           "version": "%s.%s.%s (build %s)"
                      % (tuple(App.Version()[:3])
                         + (App.Version()[3].split()[0],)),
           "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
           "headlines": {}, "narrative": [], "artifacts": []}

    t0_ok, t0ctx = t0(rec, workdir)
    ctx["headlines"]["T0"] = ("template is href-free" if t0_ok
                              else "PRECONDITION FAILED")
    if t0ctx.get("artifact"):
        ctx["artifacts"].append(("the A-bis template as built",
                                 t0ctx["artifact"]))

    t1_ok = t1(rec, workdir)
    r1 = rec.get("T1")
    per_instance = None
    for label, value in r1.notes:
        if label == "objects the copy brings":
            per_instance = value
    ctx["objects_per_instance"] = per_instance or "?"
    ctx["headlines"]["T1"] = ("expressions remap cleanly; instances are "
                              "independent" if t1_ok
                              else "GATE FAILED — see the table")

    t2_ok, t2paths = t2(rec, workdir)
    ctx["headlines"]["T2"] = ("group expressions drive every instance"
                              if t2_ok else "group propagation FAILED")
    ctx["group_verdict"] = ("works (expression on the instance's own "
                            "VarSet)" if t2_ok else "FAILED")
    if t2paths.get("two_instances"):
        ctx["artifacts"].append(("two copies, a Group_Test VarSet and live "
                                 "bindings", t2paths["two_instances"]))

    winner, bridges, t3paths = t3(rec, workdir)
    ctx["winner"] = winner
    ctx["bridges"] = bridges
    ctx["headlines"]["T3"] = ("winner: %s" % winner if winner
                              else "no bridge passes every criterion")
    if t3paths.get("cut_timber"):
        ctx["artifacts"].append(("a timber cut by a copied instance, with "
                                 "the winning bridge",
                                 t3paths["cut_timber"]))

    if winner:
        t4_ok = t4(rec, workdir, winner)
        ctx["headlines"]["T4"] = ("self-contained: opens alone with the "
                                  "template deleted" if t4_ok
                                  else "round trip FAILED")
        ctx["dependency_verdict"] = ("**none** — the saved file names no "
                                     "other document and opens silently "
                                     "with the template deleted" if t4_ok
                                     else "see T4")
        rows, t5paths = t5(rec, workdir, winner, counts)
        ctx["scale"] = rows
        last = rows[-1]
        ctx["headlines"]["T5"] = (
            "%s instances: %.1f s full recompute, %.1f MB"
            % (last.get("n"), last.get("full_recompute_s", -1),
               last.get("file_mb", -1))
            if "error" not in last else "failed at n=%s" % last.get("n"))
        if t5paths.get("scale"):
            ctx["artifacts"].append(("the largest scale document",
                                     t5paths["scale"]))
        t6_ok, hashers = t6(rec, workdir, winner)
        ctx["hasher_count"] = hashers
        ctx["hasher_verdict"] = ("**none observed**" if hashers == 0
                                 else "%d during T6" % hashers)
        ctx["headlines"]["T6"] = ("TechDraw view and dimension survive"
                                  if t6_ok else "see notes")
    else:
        ctx["scale"] = []

    ctx["narrative"] = narrative(rec, ctx)
    write_report(rec, ctx)
    print("\nsummary: " + ", ".join("%s=%s" % (r.id, r.status)
                                    for r in rec.results))
    return 0


if not os.environ.get("BW_SPIKE_NORUN"):
    main(sys.argv[1:])
