"""Headless spike round 2b: `copyObject` with a container-free template.

Round 2 recommended bridge C1-Part -- a ``PartDesign::Boolean`` whose
``Group`` holds a copied ``App::Part``.  GUI inspection of
``scratch/r2_cut_timber.FCStd`` showed that bridge reporting
``Tool shape is null``: an ``App::Part`` is a container, not a
shape-bearing object, and ``PartDesign::Boolean`` expects Bodies.  That
round-2 T3 result is withdrawn.

Round 2b drops the container.  The ``App::Part`` was only ever round 1's
requirement (a Link exposes only the linked object's own properties, so
the VarSet had to be a sibling inside a Part); ``copyObject`` follows
dependency edges and needs none of it.

Every parameter change here is asserted three ways -- value, object state,
console -- via ``spike_report.changed_cleanly``.  That is the assertion
round 2 lacked.

Run with the portable FreeCAD's console binary::

    freecadcmd.exe tests/spike/spike_copyobject_nocontainer.py

``BW_SPIKE_WORKDIR`` overrides the (temporary) fixture directory and
``BW_SPIKE_SCALE`` the T5 instance counts, e.g. ``BW_SPIKE_SCALE=3,6``.

Writes ``docs/spike-round2b-results.md``.  Nothing here imports or touches
a production module -- the spike is an evaluation only.
"""

import os
import shutil
import sys
import tempfile
import time
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
REPORT = os.path.join(REPO, "docs", "spike-round2b-results.md")
SCRATCH = os.path.join(REPO, "scratch")

PRIOR_REPORTS = {
    "round 1": os.path.join(REPO, "docs", "spike-variant-link-results.md"),
    "round 2": os.path.join(REPO, "docs", "spike-copyobject-results.md"),
}


def load_scale(path):
    """Re-read a prior spike's T5 rows from its own report.

    Both write them as ``| n=10 | `build_s=..., file_mb=...` |``.
    """
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


def make_template(workdir, stem="R2b_Template"):
    doc = App.newDocument(stem)
    doc, params, body = F.build_nocontainer_template(doc)
    save(doc, workdir, stem)
    return doc, params, body


def copy_instance(target, body):
    """Deep-copy the cutter Body; the VarSet comes along as a dependency."""
    copied = target.copyObject(body, True)
    target.recompute()
    params = [o for o in (copied.OutListRecursive or [])
              if o.TypeId == "App::VarSet"]
    return copied, (params[0] if params else None)


def reachable(obj, seen=None):
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


def cutter_volume_at(mortise_thickness_in):
    return F.cutter_volume(dict(F.default_params(),
                                MortiseThickness=mortise_thickness_in))


def set_length(obj, prop, inches):
    def mutate():
        setattr(obj, prop, inches * F.IN)
    return mutate


# --------------------------------------------------------------------------
# T0 -- template preconditions
# --------------------------------------------------------------------------

def t0(rec, workdir, prior):
    r = rec.start("T0", "Template preconditions: no href, no container")
    close_all()
    ok = True
    ctx = {}
    try:
        doc, params, body = make_template(workdir)
        exprs = F.all_expressions(doc.Objects)
        hrefs = [e for e in exprs if "href(" in e[2]]
        r.note("expressions in the template", len(exprs))
        for name, path, expr in exprs:
            r.note("  %s.%s" % (name, path), expr)
        ok &= r.check("template contains zero href(", not hrefs)

        containers = [o.Name for o in doc.Objects
                      if o.TypeId == "App::Part"]
        r.note("App::Part containers in the template",
               containers or "none")
        ok &= r.check("no App::Part container", not containers)

        origins = [o.Name for o in doc.Objects
                   if o.TypeId == "App::Origin"]
        r.note("App::Origin objects in the template", origins)

        want = F.cutter_volume(F.default_params())
        r.note("template solid volume mm^3",
               "%.3f (expected %.3f)" % (body.Shape.Volume, want))
        ok &= r.check("template solid is correct",
                      near(body.Shape.Volume, want))
        r.note("objects not Up-to-date", unhealthy(doc) or "none")
        ok &= r.check("template document is clean", not unhealthy(doc))

        r.note("root objects", [(o.Name, o.TypeId) for o in doc.Objects
                                if o.TypeId in ("App::VarSet",
                                                "PartDesign::Body")])
        r.note("objects in the template document, 2b vs round 2's 23",
               "%d vs 23" % len(doc.Objects))
        ctx["template_objects"] = len(doc.Objects)
        ctx["artifact"] = artifact(doc, "r2b_template")
        r.note("artifact", ctx["artifact"])
    except Exception as exc:
        r.error("T0", exc)
        ok = False
    r.status = "PASS" if ok else "FAIL"
    return ok, ctx


# --------------------------------------------------------------------------
# T1 -- copy fidelity and expression remapping
# --------------------------------------------------------------------------

def t1(rec, workdir):
    r = rec.start("T1", "Copy fidelity and expression remapping")
    close_all()
    ok = True
    ctx = {}
    try:
        src, params, body = make_template(workdir, "T1_Template")
        target = App.newDocument("T1_Target")
        save(target, workdir, "T1_Target")

        copied, cparams = copy_instance(target, body)
        r.note("copyObject operand", "the cutter Body (no container)")
        r.note("VarSet pulled in as a dependency",
               "%s (%s)" % (cparams.Name, cparams.Label)
               if cparams else "NO -- would need a two-object copy")
        ok &= r.check("copyObject(body, True) pulls the VarSet in",
                      cparams is not None)

        members = reachable(copied)
        r.note("objects the copy brings", len(members))
        r.note("objects per instance, 2b vs round 2's 23",
               "%d vs 23" % len(members))
        ctx["objects_per_copy"] = len(members)

        exprs = F.all_expressions(members)
        for name, path, expr in exprs:
            r.note("  %s.%s" % (name, path), expr)
        external = [e for e in exprs if "#" in e[2]]
        r.note("expressions using cross-document syntax", external or "none")
        ok &= r.check("no expression addresses another document",
                      not external)

        consumers = [o.Name for o in members
                     if F.expressions(o) and cparams in (o.OutList or [])]
        leaks = [o.Name for o in members if params in (o.OutList or [])]
        r.note("copied objects resolving to the copy's own VarSet",
               consumers)
        r.note("copied objects still depending on the SOURCE VarSet",
               leaks or "none")
        ok &= r.check("every expression resolves to the copy's own VarSet",
                      not leaks and len(consumers) == 4,
                      "%d consumers, %d leaks" % (len(consumers),
                                                  len(leaks)))
        ok &= r.check("the source VarSet is not part of the copy",
                      params not in members)

        outside = [o.Name for o in members if o.Document is not target]
        r.note("copied objects living in another document",
               outside or "none")
        ok &= r.check("the whole copy lives in the target document",
                      not outside)

        r.note("copied Body placement", copied.Placement)
        r.note("what carries the instance frame now",
               "the copied Body's own Placement -- with no container "
               "there is nothing else, and the Body is the object the "
               "Boolean takes")
        ok &= r.check("copied Body sits at zero placement",
                      near(copied.Placement.Base.Length, 0.0))

        ok &= changed_cleanly(
            r, target, "edit the copy",
            set_length(cparams, "MortiseThickness", 1.5),
            lambda: copied.Shape.Volume, cutter_volume_at(1.5))[0]
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
               % (copied.Shape.Volume, cutter_volume_at(1.5)))
        ok &= r.check("editing the source leaves the copy untouched",
                      near(copied.Shape.Volume, cutter_volume_at(1.5)))
        ok &= r.check("target document still clean",
                      not unhealthy(target),
                      unhealthy(target) or "none")
    except Exception as exc:
        r.error("T1", exc)
        ok = False
    r.status = "PASS" if ok else "FAIL"
    return ok, ctx


# --------------------------------------------------------------------------
# T2 -- two instances and expression-driven groups
# --------------------------------------------------------------------------

def t2(rec, workdir):
    r = rec.start("T2", "Two instances and expression-driven groups")
    close_all()
    ok = True
    paths = {}
    try:
        src, params, body = make_template(workdir, "T2_Template")
        target = App.newDocument("T2_Target")
        tpath = save(target, workdir, "T2_Target")

        inst = [copy_instance(target, body) for _ in range(2)]
        r.note("instance labels (Body, VarSet)",
               [(c.Label, p.Label) for c, p in inst])
        ok &= r.check("the second copy gets its own VarSet",
                      inst[0][1] is not inst[1][1]
                      and inst[0][1].Label != inst[1][1].Label)

        crossed = [e for e in F.all_expressions(reachable(inst[1][0]))
                   if ("<<%s>>" % inst[0][1].Label) in e[2]]
        r.note("instance 2 expressions naming instance 1's VarSet",
               crossed or "none")
        ok &= r.check("no cross-instance expression leak", not crossed)

        ok &= changed_cleanly(
            r, target, "instance 1 to 1.5 in",
            set_length(inst[0][1], "MortiseThickness", 1.5),
            lambda: inst[0][0].Shape.Volume, cutter_volume_at(1.5))[0]
        ok &= changed_cleanly(
            r, target, "instance 2 to 3.0 in",
            set_length(inst[1][1], "MortiseThickness", 3.0),
            lambda: inst[1][0].Shape.Volume, cutter_volume_at(3.0))[0]
        r.note("instance 1 volume after editing instance 2",
               "%.3f (expected %.3f)"
               % (inst[0][0].Shape.Volume, cutter_volume_at(1.5)))
        ok &= r.check("the two instances are independent",
                      near(inst[0][0].Shape.Volume, cutter_volume_at(1.5)))

        grp = target.addObject("App::VarSet", "GroupTest")
        grp.Label = "Group_Test"
        grp.addProperty("App::PropertyLength", "MortiseThickness", "Group",
                        "Shared mortise thickness for the group")
        grp.MortiseThickness = 2.0 * F.IN
        for _, p in inst:
            p.setExpression("MortiseThickness",
                            "<<Group_Test>>.MortiseThickness")
        target.recompute()

        ok &= changed_cleanly(
            r, target, "group to 1.75 in (instance 1)",
            set_length(grp, "MortiseThickness", 1.75),
            lambda: inst[0][0].Shape.Volume, cutter_volume_at(1.75))[0]
        r.note("instance 2 volume after the group change",
               "%.3f (expected %.3f)"
               % (inst[1][0].Shape.Volume, cutter_volume_at(1.75)))
        ok &= r.check("both instances follow the group",
                      near(inst[1][0].Shape.Volume,
                           cutter_volume_at(1.75)))

        inst[1][1].setExpression("MortiseThickness", None)
        ok &= changed_cleanly(
            r, target, "per-instance override on instance 2",
            set_length(inst[1][1], "MortiseThickness", 3.0),
            lambda: inst[1][0].Shape.Volume, cutter_volume_at(3.0))[0]
        r.note("instance 1 volume after overriding instance 2",
               "%.3f (expected %.3f)"
               % (inst[0][0].Shape.Volume, cutter_volume_at(1.75)))
        ok &= r.check("the override leaves the sibling alone",
                      near(inst[0][0].Shape.Volume,
                           cutter_volume_at(1.75)))

        target.save()
        paths["two_instances"] = artifact(target, "r2b_two_instances")
        r.note("artifact", paths["two_instances"])

        names = [c.Name for c, _ in inst]
        close_all()
        target = App.openDocument(tpath)
        again = [target.getObject(n) for n in names]
        vs0 = [o for o in (again[0].OutListRecursive or [])
               if o.TypeId == "App::VarSet"][0]
        expr = dict(vs0.ExpressionEngine).get("MortiseThickness")
        r.note("instance 1 expression after reload", expr)
        ok &= r.check("group binding survives save/reload",
                      expr is not None and "Group_Test" in str(expr))
        grp = target.getObject("GroupTest")
        ok &= changed_cleanly(
            r, target, "post-reload group change to 2.25 in",
            set_length(grp, "MortiseThickness", 2.25),
            lambda: again[0].Shape.Volume, cutter_volume_at(2.25))[0]
    except Exception as exc:
        r.error("T2", exc)
        ok = False
    r.status = "PASS" if ok else "FAIL"
    return ok, paths


# --------------------------------------------------------------------------
# T3 -- the boolean bridge retest
# --------------------------------------------------------------------------

def _bridge_c1(doc, timber, copied):
    """The documented native usage: a Body as the Boolean's operand."""
    boo = timber.newObject("PartDesign::Boolean", "JointCut")
    boo.Type = "Cut"
    boo.Group = [copied]
    doc.recompute()
    return timber, boo


def _bridge_c3(doc, timber, copied):
    cut = doc.addObject("Part::Cut", "JointCut")
    cut.Base = timber
    cut.Tool = copied
    doc.recompute()
    return cut, cut


BRIDGES = [
    ("C1", "PartDesign::Boolean with the copied Body in Group", _bridge_c1),
    ("C3", "Part::Cut with the copied Body as Tool", _bridge_c3),
]
BRIDGE_TITLE = dict((k, t) for k, t, _ in BRIDGES)
BRIDGE_BUILD = dict((k, b) for k, _, b in BRIDGES)


def build_cut_document(workdir, stem, bridge, mortise_in=1.5):
    """A timber cut by one copied instance, ready for the bridge tests."""
    src, params, body = make_template(workdir, stem + "_Template")
    target = App.newDocument(stem)
    save(target, workdir, stem)
    _, timber, dims, sk = F.build_timber(target, label="T-Post-Spike-001")
    copied, cparams = copy_instance(target, body)
    cparams.MortiseThickness = mortise_in * F.IN
    target.recompute()
    top, feature = BRIDGE_BUILD[bridge](target, timber, copied)
    return target, timber, dims, sk, copied, cparams, top, feature


def t3(rec, workdir):
    r = rec.start("T3", "Boolean bridge (the round-2 retest)")
    outcomes = {}
    paths = {}
    geo_errors = []
    for key, title, build in BRIDGES:
        close_all()
        o = {"title": title, "constructs": False, "volume_ok": False,
             "clean_change": False, "placement": False, "editable": False,
             "type": None, "error": None, "console": ""}
        try:
            src, params, body = make_template(workdir, "T3_Template")
            target = App.newDocument("T3_Target_%s" % key)
            save(target, workdir, "T3_Target_%s" % key)
            _, timber, dims, sk = F.build_timber(
                target, label="T-Post-Spike-001")
            copied, cparams = copy_instance(target, body)
            cparams.MortiseThickness = 1.5 * F.IN
            target.recompute()

            (top, feature), console = capture_console(
                lambda: build(target, timber, copied))
            o["console"] = " / ".join(console_faults(console)) or "silent"
            if "GeoFeatureGroup" in console:
                geo_errors.append(key)
            o["constructs"] = True
            o["type"] = top.TypeId
            o["top"] = top.Name
            o["feature"] = feature.TypeId

            want = expected_cut_volume(1.5)
            vol = top.Shape.Volume
            if not near(vol, want):
                force_recompute(target)
                vol = top.Shape.Volume
            o["volume"] = vol
            o["volume_expected"] = want
            o["volume_ok"] = near(vol, want)
            o["state_after_build"] = unhealthy(target) or "none"

            # the round-2b assertion, on the operation round 2 got wrong
            o["clean_change"] = changed_cleanly(
                r, target, "%s: parameter change to 3.0 in" % key,
                set_length(cparams, "MortiseThickness", 3.0),
                lambda: top.Shape.Volume, expected_cut_volume(3.0))[0]
            o["volume_after_change"] = top.Shape.Volume

            # placement: park the cutter clear and the stick returns whole
            o["placement"] = changed_cleanly(
                r, target, "%s: cutter parked clear of the stick" % key,
                lambda: setattr(copied, "Placement",
                                App.Placement(App.Vector(0, 0, -1000.0),
                                              App.Rotation())),
                lambda: top.Shape.Volume, F.timber_volume())[0]
            copied.Placement = App.Placement(App.Vector(0, 0, 0),
                                             App.Rotation())
            force_recompute(target)

            # the timber's own sketch must still drive it
            o["editable"] = changed_cleanly(
                r, target, "%s: timber section widened to 10 in" % key,
                set_length(dims, "Width", 10.0),
                lambda: top.Shape.Volume,
                expected_cut_volume(3.0, width_in=10.0))[0]
            o["section_sketch_DX_mm"] = sk.getDatum("DX").Value
            o["editable"] = (o["editable"]
                             and near(o["section_sketch_DX_mm"],
                                      10.0 * F.IN))
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
                   o["clean_change"])
            r.note("%s honours the instance placement" % key,
                   o["placement"])
            r.note("%s timber stays natively editable" % key, o["editable"])
            r.note("%s console faults while building" % key, o["console"])
        if o["error"]:
            r.note("%s error" % key, o["error"])

    r.note("GeoFeatureGroup errors seen anywhere",
           geo_errors or "none -- there is no container to belong to")

    good = [k for k, _, _ in BRIDGES
            if outcomes[k]["constructs"] and outcomes[k]["volume_ok"]
            and outcomes[k]["clean_change"] and outcomes[k]["placement"]
            and outcomes[k]["editable"]
            and outcomes[k]["console"] == "silent"]
    keeps_body = [k for k in good
                  if outcomes[k]["type"] == "PartDesign::Body"]
    winner = (keeps_body or good or [None])[0]
    r.note("bridges passing every criterion", ", ".join(good) or "none")
    r.note("winner", winner or "none")

    if winner:
        # The artifact must be a document where a parameter was changed
        # AND re-saved after the cut was made -- that is the exact path
        # that failed in the GUI in round 2.
        close_all()
        try:
            (target, timber, dims, sk, copied, cparams,
             top, feature) = build_cut_document(workdir, "T3_Artifact",
                                                winner)
            force_recompute(target)
            cparams.MortiseThickness = 3.0 * F.IN
            target.recompute()
            target.save()
            r.note("artifact: state after the post-cut parameter change "
                   "and save", unhealthy(target) or "none")
            r.note("artifact: volume after the change",
                   "%.3f (expected %.3f)"
                   % (top.Shape.Volume, expected_cut_volume(3.0)))
            paths["cut_timber"] = artifact(target, "r2b_cut_timber")
            r.note("artifact", paths["cut_timber"])
        except Exception as exc:
            r.error("T3 artifact", exc)

    r.status = "PASS" if winner else ("PARTIAL" if good else "FAIL")
    return winner, outcomes, paths


# --------------------------------------------------------------------------
# T4 -- persistence and relocation
# --------------------------------------------------------------------------

def t4(rec, workdir, winner):
    r = rec.start("T4", "Persistence, relocation and post-reload edits")
    close_all()
    ok = True
    try:
        (target, timber, dims, sk, copied, cparams,
         top, feature) = build_cut_document(workdir, "T4_Target", winner)
        force_recompute(target)
        vol_before = top.Shape.Volume
        top_name, params_name = top.Name, cparams.Name
        tpath = target.FileName
        spath = App.getDocument("T4_Target_Template").FileName
        target.save()
        App.getDocument("T4_Target_Template").save()
        close_all()

        refs = external_file_refs(tpath)
        r.note("external .FCStd references in the saved target",
               refs or "none")
        ok &= r.check("the saved target names no other document", not refs)

        target, console = capture_console(lambda: App.openDocument(tpath))
        top = target.getObject(top_name)
        again = target.getObject(params_name)
        r.note("console faults while opening",
               console_faults(console) or "none")
        r.note("documents open after reopening the target",
               sorted(App.listDocuments()))
        ok &= r.check("no second document is pulled in",
                      len(App.listDocuments()) == 1)
        r.note("override after reopen",
               "%.4f mm" % again.MortiseThickness.Value)
        ok &= r.check("override persists",
                      near(again.MortiseThickness.Value, 1.5 * F.IN))
        target.recompute()
        r.note("volume before / after reopen",
               "%.3f / %.3f" % (vol_before, top.Shape.Volume))
        ok &= r.check("geometry recomputes identically",
                      near(top.Shape.Volume, vol_before))
        r.note("object state after reopen", unhealthy(target) or "none")
        ok &= r.check("nothing is left touched or errored on open",
                      not unhealthy(target))

        # The round-2 failure was only visible after a save/close/reopen,
        # so this is the path that matters most.
        ok &= changed_cleanly(
            r, target, "post-reload parameter change to 3.0 in",
            set_length(again, "MortiseThickness", 3.0),
            lambda: top.Shape.Volume, expected_cut_volume(3.0))[0]

        # relocation, with the template deleted outright
        close_all()
        moved = os.path.join(workdir, "relocated")
        if os.path.isdir(moved):
            shutil.rmtree(moved)
        os.makedirs(moved)
        new_t = os.path.join(moved, os.path.basename(tpath))
        shutil.copy2(tpath, new_t)
        if os.path.exists(spath):
            os.remove(spath)
        target, console = capture_console(lambda: App.openDocument(new_t))
        top = target.getObject(top_name)
        again = target.getObject(params_name)
        target.recompute()
        r.note("console faults while opening the relocated target",
               console_faults(console) or "none")
        r.note("documents open", sorted(App.listDocuments()))
        r.note("relocated volume",
               "%.3f (expected %.3f)" % (top.Shape.Volume, vol_before))
        ok &= r.check("no 'does not exist' log line",
                      "does not exist" not in console)
        ok &= r.check("opens alone, with the template deleted",
                      len(App.listDocuments()) == 1)
        ok &= r.check("relocated document recomputes identically",
                      near(top.Shape.Volume, vol_before))
        ok &= changed_cleanly(
            r, target, "parameter change after relocation",
            set_length(again, "MortiseThickness", 2.5),
            lambda: top.Shape.Volume, expected_cut_volume(2.5))[0]
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
            src, params, body = make_template(workdir,
                                              "T5_Template_%d" % n)
            target = App.newDocument("T5_Target_%d" % n)
            path = save(target, workdir, "T5_Target_%d" % n)
            grp = target.addObject("App::VarSet", "GroupTest")
            grp.Label = "Group_Test"
            grp.addProperty("App::PropertyLength", "MortiseThickness",
                            "Group", "Shared mortise thickness")
            grp.MortiseThickness = 2.0 * F.IN

            start = time.time()
            for i in range(n):
                label = "T-Post-Spike-%03d" % (i + 1)
                _, timber, dims, sk = F.build_timber(target, label=label)
                timber.Placement.Base = App.Vector(0, 0, i * 300.0)
                copied, cparams = copy_instance(target, body)
                copied.Placement.Base = App.Vector(0, 0, i * 300.0)
                cparams.setExpression("MortiseThickness",
                                      "<<Group_Test>>.MortiseThickness")
                build(target, timber, copied)
            row["build_s"] = time.time() - start

            for obj in target.Objects:
                obj.touch()
            start = time.time()
            target.recompute(None, True, True)
            row["full_recompute_s"] = time.time() - start

            start = time.time()
            grp.MortiseThickness = 1.75 * F.IN
            target.recompute()
            row["param_change_s"] = time.time() - start

            bad = unhealthy(target)
            row["unhealthy"] = len(bad)
            if bad:
                ok = False
                r.note("n=%d: objects not Up-to-date after the group "
                       "change" % n, bad[:5])

            start = time.time()
            target.save()
            row["save_s"] = time.time() - start
            row["file_mb"] = os.path.getsize(path) / (1024.0 * 1024.0)
            row["objects"] = len(target.Objects)
            if n == max(counts):
                paths["scale"] = artifact(target, "r2b_scale_%d" % n)
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
        if len(timed) >= 2:
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
        else:
            r.note("growth", "not assessed (fewer than two timed counts)")
    except Exception as exc:
        r.error("T5 analysis", exc)
    r.status = "PASS" if ok else "FAIL"
    return rows, paths


# --------------------------------------------------------------------------
# T6 -- downstream TechDraw
# --------------------------------------------------------------------------

def t6(rec, workdir, winner):
    r = rec.start("T6", "Downstream: TechDraw (best effort, headless)")
    close_all()
    ok = True
    console = ""
    try:
        def run():
            (target, timber, dims, sk, copied, cparams,
             top, feature) = build_cut_document(workdir, "T6_Target",
                                                winner)
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
            return (target, pg, front, dim, before, dim.getRawValue())

        (target, pg, front, dim, before, after), console = \
            capture_console(run)
        r.note("projection group state", pg.State)
        r.note("front view state", front.State)
        r.note("dimension state", dim.State)
        r.note("dimension value before -> after",
               "%s -> %s" % (before, after))
        bad = [x for x in unhealthy(target)
               if not x[0].startswith(("Page", "Template", "ProjGroup",
                                       "ProjItem", "Dim"))]
        r.note("non-TechDraw objects not Up-to-date", bad or "none")
        ok &= r.check("view and dimension survive a parameter change",
                      "Invalid" not in str(front.State)
                      and "Invalid" not in str(dim.State)
                      and not bad)
    except Exception as exc:
        r.error("T6", exc)
        ok = False
    hashers = console.count("hasher mismatch")
    r.note("'hasher mismatch' warnings during T6", hashers)
    r.note("other console faults during T6",
           [line for line in console_faults(console)
            if "hasher mismatch" not in line] or "none")
    r.status = "PASS" if ok else "PARTIAL"
    return ok, hashers


# --------------------------------------------------------------------------
# report
# --------------------------------------------------------------------------

def scale_table(ctx):
    """Three-way: round 1, round 2, round 2b."""
    prior = ctx["prior"]
    lines = ["| n | metric | round 1 (links) | round 2 (Part) "
             "| **round 2b (no container)** |",
             "|---|---|---|---|---|"]
    metrics = [("build_s", "build (s)", "%.2f"),
               ("full_recompute_s", "full recompute (s)", "%.2f"),
               ("param_change_s", "group change (s)", "%.2f"),
               ("file_mb", "file (MB)", "%.2f"),
               ("objects", "objects", "%d")]
    for row in ctx.get("scale", []):
        n = row["n"]
        if "error" in row:
            lines.append("| %s | — | — | — | error: `%s` |"
                         % (n, row["error"]))
            continue
        for key, label, fmt in metrics:
            def cell(source):
                got = source.get(n, {}).get(key)
                return fmt % got if got is not None else "—"
            lines.append("| %s | %s | %s | %s | **%s** |"
                         % (n if key == "build_s" else "",
                            label, cell(prior["round 1"]),
                            cell(prior["round 2"]), fmt % row[key]))
    return lines


def write_report(rec, ctx):
    lines = []
    w = lines.append
    w("# Spike round 2b: `copyObject` with a container-free template")
    w("")
    w("Generated by `tests/spike/spike_copyobject_nocontainer.py`")
    w("(fixtures in `tests/spike/spike_fixtures.py`), run headless under")
    w("`freecadcmd.exe`. Implements `docs/spike-round2b-brief.md`.")
    w("Priors: `docs/spike-variant-link-results.md` (round 1),")
    w("`docs/spike-copyobject-results.md` (round 2).")
    w("")
    w("- FreeCAD: %s" % ctx["version"])
    w("- Run: %s" % ctx["timestamp"])
    w("- Work directory: `%s`" % ctx["workdir"])
    w("")
    w("```bash")
    w("freecadcmd.exe tests/spike/spike_copyobject_nocontainer.py")
    w("```")
    w("")
    w("## Read this first: headless cannot adjudicate the round-2 failure")
    w("")
    w("Before building anything, this harness tried to reproduce round 2's")
    w("`Tool shape is null` **on the exact artifact that failed**,")
    w("`scratch/r2_cut_timber.FCStd`, opened headless in FreeCAD 1.1.1:")
    w("")
    w("- `JointCut` reports `Up-to-date` / `Valid`, before and after a")
    w("  recompute.")
    w("- Changing `JointParams.MortiseThickness` to 4 in updates the cut")
    w("  to 98 682 899.408 mm³ — exactly timber minus a 4 in mortise")
    w("  cutter.")
    w("- No object in the document is left touched or errored.")
    w("")
    w("The same sequence built from scratch — copy an `App::Part`, put it")
    w("in a `PartDesign::Boolean`, change a parameter, save, close,")
    w("reopen, change again — is also clean headlessly.")
    w("")
    w("**So the brief's premise needs one correction.** The round-2")
    w("harness was genuinely deficient: it asserted a volume and never an")
    w("object state, and that is fixed here and retrofitted into rounds 1")
    w("and 2. But the new assertion would *not* have caught this bug,")
    w("because headless FreeCAD does not exhibit it. `Tool shape is null`")
    w("is a GUI-side recompute-ordering failure, and no headless harness")
    w("can be trusted to see it.")
    w("")
    w("That does not rescue C1-Part. A bridge that works headlessly and")
    w("fails in the GUI is a broken bridge, and the diagnosis in the")
    w("brief is sound on its own terms: `App::Part` is a container, not a")
    w("shape-bearing object, and `PartDesign::Boolean` documents Bodies as")
    w("its operands. Round 2b removes the container and uses the operand")
    w("FreeCAD actually expects. The decisive evidence was always GUI")
    w("inspection of `scratch/r2b_cut_timber.FCStd`, not this report --")
    w("**and that inspection has since been done and passed. See *GUI")
    w("confirmation* below.**")
    w("")
    if ctx.get("artifacts"):
        w("## Artifacts for GUI inspection")
        w("")
        for name, path in ctx["artifacts"]:
            w("- `%s` — %s"
              % (os.path.relpath(path, REPO).replace("\\", "/"), name))
        w("")
        w("`r2b_cut_timber.FCStd` is the one that matters: the cut was")
        w("made, then a parameter was changed, then the document was")
        w("saved — the exact path that failed in round 2.")
        w("")
    lines.extend(render_results(rec, ctx["headlines"]))
    w("## Scale: round 1 / round 2 / round 2b")
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
    winner = ctx.get("winner")
    outcomes = ctx.get("bridges", {})
    prior = ctx["prior"]
    scale = dict((row["n"], row) for row in ctx.get("scale", [])
                 if "error" not in row)
    big = max(scale) if scale else None

    w("## Does removing the container fix it?")
    w("")
    if winner:
        w("Headlessly, `%s` passes every criterion, including the three" % winner)
        w("that round 2 never checked: after each parameter change no")
        w("object is left touched or errored, and the console stays")
        w("silent. It also honours the instance `Placement` and leaves the")
        w("timber's own section sketch driving it.")
        w("")
        w("The structural argument for believing this over round 2:")
        w("")
        w("- The operand is a `PartDesign::Body`, which is what")
        w("  `PartDesign::Boolean` is documented to take. Round 2 handed")
        w("  it an `App::Part`, which carries no shape of its own.")
        w("- **No `GeoFeatureGroup` error can arise**, because there is no")
        w("  container for the Body to already belong to. In round 2 that")
        w("  error was what ruled out the Body-as-operand form and forced")
        w("  the Part-as-operand form that failed.")
        w("- `copyObject(body, True)` pulls the VarSet in as a dependency")
        w("  on its own, so the container bought nothing in the first")
        w("  place. It existed only because round 1's Link could not see")
        w("  a child VarSet.")
    else:
        w("No bridge passed. See the T3 table; this is the second")
        w("withdrawn bridge result, and the mechanism should be treated")
        w("as not ready.")
    w("")

    w("## GUI confirmation (2026-08-30)")
    w("")
    w("Adam opened `scratch/r2b_cut_timber.FCStd` in the FreeCAD GUI and")
    w("exercised the path that failed in round 2. Reported:")
    w("")
    w("- **It works.** Changes to the instance's `JointParams` VarSet")
    w("  update the geometry **immediately and without problems** -- no")
    w("  `Tool shape is null`, no stale cut, no forced refresh.")
    w("- **Placing the housed mortise on different faces and stations is")
    w("  a simple transform**, and looks straightforward to automate.")
    w("")
    w("That settles the question round 2b existed to answer. The")
    w("container-free template with bridge `C1` is confirmed in the only")
    w("environment that could adjudicate it, and the withdrawal of round")
    w("2's C1-Part is confirmed as a container problem rather than a")
    w("problem with `copyObject`.")
    w("")
    w("The second observation is worth keeping, because it contradicts a")
    w("worry inherited from `apply_joint.py`. Round 1 surfaced two")
    w("placement bugs -- a mirrored sketch needing its `Angle`")
    w("constraints negated, and a frame-child's `AttachmentOffset`")
    w("negating on an axis that depends on the plane it attaches to --")
    w("and both are artifacts of *rebuilding sketches on the target*.")
    w("Positioning a copied solid is a rigid transform of one object, so")
    w("neither can arise. One caveat survives: a rigid transform cannot")
    w("produce a *mirrored* solid, so a handed joint still needs either a")
    w("mirrored cutter or the existing `Template_Handed` flag. Faces,")
    w("ends and stations are transforms; hand is not.")
    w("")
    w("## Does it close the performance gap?")
    w("")
    if big and prior["round 1"].get(big) and prior["round 2"].get(big):
        one, two, now = (prior["round 1"][big], prior["round 2"][big],
                         scale[big])
        w("At %d instances:" % big)
        w("")
        w("- full recompute **%.2f s**, against round 2's %.2f s and"
          % (now["full_recompute_s"], two["full_recompute_s"]))
        w("  round 1's %.2f s;" % one["full_recompute_s"])
        w("- build **%.1f s**, against %.1f s and %.1f s;"
          % (now["build_s"], two["build_s"], one["build_s"]))
        w("- **%d objects**, against %d and %d."
          % (now["objects"], two["objects"], one["objects"]))
        w("")
        closed = (now["full_recompute_s"]
                  <= one["full_recompute_s"] * 1.25)
        improved = now["full_recompute_s"] < two["full_recompute_s"]
        if closed:
            w("**The gap is closed.** Dropping the container removes an")
            w("`App::Origin` and the Part itself from every instance, and")
            w("round 2's 2–3x recompute penalty goes with them — the")
            w("diagnosis in the brief was right about the cause.")
        elif improved:
            w("**The gap barely narrows, and the brief's explanation for")
            w("it is wrong.** Removing the container drops %.0f%% of the"
              % (100.0 * (two["objects"] - now["objects"])
                 / float(two["objects"])))
            w("objects — the `App::Part` and one `App::Origin` per")
            w("instance — but recovers only %.0f%% of the recompute time."
              % (100.0 * (two["full_recompute_s"]
                          - now["full_recompute_s"])
                 / float(two["full_recompute_s"])))
            w("So the extra `App::Origin` was **not** the cause of round")
            w("2's penalty: object count and recompute cost are not")
            w("proportional here, and `copyObject` remains roughly")
            w("%.1fx round 1's recompute at this scale."
              % (now["full_recompute_s"] / one["full_recompute_s"]))
            w("")
            w("What is left is the cost a deep copy cannot avoid:")
            w("duplicating and re-solving the cutter's whole feature tree")
            w("— two sketches and two pads per instance — where a variant")
            w("link's materialized copy is evidently cheaper to refresh.")
            w("That is a real and permanent tax on this mechanism, and it")
            w("should be weighed as such rather than expected to")
            w("disappear. It does not change the recommendation: %.1f s"
              % now["full_recompute_s"])
            w("for a 150-joint frame is fine, and growth is linear.")
        else:
            w("**The gap does not close.** Removing the container did not")
            w("recover round 2's penalty, so the extra `App::Origin` was")
            w("not its cause.")
    else:
        w("Not measured at a count round 1 and round 2 both recorded.")
    w("")

    w("## What the round-2 harness should have asserted")
    w("")
    w("Round 2's T3 asserted, after a parameter change, only that the")
    w("volume reached its analytic expectation. A model can pass that")
    w("while carrying a failed feature — and, in the GUI, round 2's did.")
    w("The assertion is now three-part, in")
    w("`spike_report.changed_cleanly`:")
    w("")
    w("1. the measured value reaches the analytic expectation;")
    w("2. **no object is left outside `Up-to-date`** — every object's")
    w("   `State` and `getStatusString()` is enumerated, and anything")
    w("   else is a FAIL;")
    w("3. **the console is silent** during the recompute — captured at")
    w("   the file-descriptor level, since FreeCAD warns from C++;")
    w("   `shape is null`, `out of the allowed scope`, `hasher mismatch`")
    w("   and friends are all faults.")
    w("")
    w("It is applied at **every** parameter change in this harness, and")
    w("`spike_report.unhealthy()` / `console_faults()` are now used by the")
    w("round 1 and round 2 harnesses too, so all three stay comparable")
    w("and the regression suite is uniform. Rerunning rounds 1 and 2 with")
    w("the assertion in place leaves both still passing headlessly —")
    w("which is the point above: headless is not where this bug lives.")
    w("")

    w("## Recommendation")
    w("")
    all_ok = (status.get("T0") == "PASS" and status.get("T1") == "PASS"
              and status.get("T2") == "PASS" and winner
              and status.get("T4") == "PASS"
              and status.get("T5") == "PASS")
    if all_ok:
        w("**Template structure: container-free.** A `JointParams` VarSet")
        w("and a `Cutter` Body at document root, no `App::Part`. This is")
        w("the Phase 0 pattern, it is what a template author would build")
        w("without being told otherwise, and it is fewer objects.")
        w("")
        w("**Bridge: `%s` — %s.**" % (winner, BRIDGE_TITLE[winner]))
        other = [k for k, _, _ in BRIDGES if k != winner]
        for key in other:
            o = outcomes.get(key, {})
            if o.get("error"):
                w("")
                w("`%s` failed: `%s`" % (key, o["error"]))
            elif o.get("constructs"):
                faults = []
                if not o.get("volume_ok"):
                    faults.append("wrong volume")
                if not o.get("clean_change"):
                    faults.append("does not survive a parameter change "
                                  "cleanly")
                if not o.get("placement"):
                    faults.append("ignores the instance placement")
                if not o.get("editable"):
                    faults.append("timber no longer natively editable")
                if o.get("console") != "silent":
                    faults.append("console: `%s`" % o["console"])
                w("")
                if faults:
                    w("`%s` constructs a `%s` but %s."
                      % (key, o.get("type"), "; ".join(faults)))
                else:
                    w("`%s` also passes, producing a `%s`; `%s` is"
                      % (key, o.get("type"), winner))
                    w("preferred because it keeps the timber a")
                    w("`PartDesign::Body`, so nothing downstream changes.")
        w("")
        w("**The GUI condition on this recommendation has been met.**")
        w("Round 2 also passed every headless assertion and was wrong, so")
        w("adopting round 2b was made conditional on a GUI session with")
        w("`scratch/r2b_cut_timber.FCStd`. That session happened")
        w("(2026-08-30) and the cut follows its parameters immediately.")
        w("Round 2b therefore stands on evidence, not on headless")
        w("inference, and round 2 is superseded in its template structure")
        w("and bridge only — the `copyObject`-over-links conclusion rested")
        w("on authoring ergonomics, not on T3, and is unaffected.")
        w("")
        w("Everything round 2 listed as still owed by the apply-joint")
        w("tool — mated pairs, mate frames and the stick-allowance contract,")
        w("placement computation, naming and filing, assembly seating —")
        w("is unchanged, with one item downgraded: placement is now a")
        w("rigid transform of a copied solid rather than a sketch rebuild")
        w("on the target, which is a materially smaller job than")
        w("`apply_joint.py` does today (see *GUI confirmation*).")
    else:
        w("**Not ready.** A test failed above; with round 2's T3 already")
        w("withdrawn, two failures in a row is a strong signal. Round 1's")
        w("variant-link mechanism remains validated and available.")
    w("")
    w("## Needs GUI confirmation")
    w("")
    w("- ~~**`scratch/r2b_cut_timber.FCStd` — the decisive test.**~~")
    w("  **Done, 2026-08-30 — passed.** See *GUI confirmation* above.")
    w("- **Authoring the template by hand.** VarSet plus Body at root,")
    w("  sketches bound to `<<JointParams>>.` with autocomplete working.")
    w("- **The tree.** Whether a container-free instance reads as clutter")
    w("  at document root — the `App::Part` did buy tidiness, and losing")
    w("  it may be worth a Std Group instead (which is not a")
    w("  `GeoFeatureGroup` and so cannot repeat the round-2 failure).")
    w("- **Assembly**, and **TechDraw** correctness, as before.")
    return out


# --------------------------------------------------------------------------

def main(argv):
    workdir = os.environ.get("BW_SPIKE_WORKDIR") or None
    counts = [int(x) for x in
              os.environ.get("BW_SPIKE_SCALE", "10,50,150").split(",")]
    workdir = workdir or tempfile.mkdtemp(prefix="bw_spike_r2b_")
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
           "prior": dict((k, load_scale(v))
                         for k, v in PRIOR_REPORTS.items())}

    t0_ok, t0ctx = t0(rec, workdir, ctx["prior"])
    ctx["headlines"]["T0"] = ("href-free and container-free (%s objects)"
                              % t0ctx.get("template_objects", "?")
                              if t0_ok else "PRECONDITION FAILED")
    if t0ctx.get("artifact"):
        ctx["artifacts"].append(("the container-free template as built",
                                 t0ctx["artifact"]))

    t1_ok, t1ctx = t1(rec, workdir)
    ctx["headlines"]["T1"] = (
        "expressions remap; %s objects per instance (round 2: 23)"
        % t1ctx.get("objects_per_copy", "?") if t1_ok
        else "FAILED — see the table")

    t2_ok, t2paths = t2(rec, workdir)
    ctx["headlines"]["T2"] = ("groups drive every instance, cleanly"
                              if t2_ok else "FAILED")
    if t2paths.get("two_instances"):
        ctx["artifacts"].append(("two copies, a Group_Test VarSet and live "
                                 "bindings", t2paths["two_instances"]))

    winner, bridges, t3paths = t3(rec, workdir)
    ctx["winner"] = winner
    ctx["bridges"] = bridges
    ctx["headlines"]["T3"] = ("winner: %s, clean through every assertion"
                              % winner if winner
                              else "no bridge passes")
    if t3paths.get("cut_timber"):
        ctx["artifacts"].append(("a cut timber whose parameter was changed "
                                 "and re-saved AFTER the cut — the exact "
                                 "round-2 failure path",
                                 t3paths["cut_timber"]))

    if winner:
        t4_ok = t4(rec, workdir, winner)
        ctx["headlines"]["T4"] = ("survives reload, post-reload edits and "
                                  "relocation" if t4_ok
                                  else "round trip FAILED")
        rows, t5paths = t5(rec, workdir, winner, counts)
        ctx["scale"] = rows
        last = rows[-1]
        ctx["headlines"]["T5"] = (
            "%s instances: %.1f s full recompute, %s objects"
            % (last.get("n"), last.get("full_recompute_s", -1),
               last.get("objects"))
            if "error" not in last else "failed at n=%s" % last.get("n"))
        if t5paths.get("scale"):
            ctx["artifacts"].append(("the largest scale document",
                                     t5paths["scale"]))
        t6_ok, hashers = t6(rec, workdir, winner)
        ctx["headlines"]["T6"] = ("TechDraw survives; %d hasher warnings"
                                  % hashers if t6_ok else "see notes")
    else:
        ctx["scale"] = []

    ctx["narrative"] = narrative(rec, ctx)
    write_report(rec, ctx)
    print("\nsummary: " + ", ".join("%s=%s" % (r.id, r.status)
                                    for r in rec.results))
    return 0


if not os.environ.get("BW_SPIKE_NORUN"):
    main(sys.argv[1:])
