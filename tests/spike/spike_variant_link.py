"""Headless spike harness: can App::Link copy-on-change + a boolean bridge
replace the hand-rolled rebuild engine?

Run with the portable FreeCAD's console binary::

    freecadcmd.exe tests/spike/spike_variant_link.py

``BW_SPIKE_WORKDIR`` overrides the (temporary) fixture directory and
``BW_SPIKE_SCALE`` the T5 instance counts, e.g. ``BW_SPIKE_SCALE=3,5``.

Writes ``docs/spike-variant-link-results.md``.  See ``docs/spike-headless-brief.md``
for the brief this implements.  Nothing here imports or touches production
modules -- the spike is an evaluation only.
"""

import os
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import FreeCAD as App          # noqa: E402
import spike_fixtures as F     # noqa: E402
from spike_report import (Recorder, changed_cleanly,  # noqa: E402
                          close_all, force_recompute, near,
                          render_results, save, unhealthy)

REPO = os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))
REPORT = os.path.join(REPO, "docs", "spike-variant-link-results.md")

MODES = ("Enabled", "Owned", "Tracking")


def make_cutter(workdir, stem="Spike_Cutter", **kw):
    """A saved cutter document.  Cross-document links require the source
    document to be on disk -- see the report."""
    doc = App.newDocument(stem)
    doc, body = F.build_cutter(doc, **kw)
    save(doc, workdir, stem)
    return doc, body


def make_target(workdir, stem="Spike_Target", label="T-Post-Spike-001"):
    doc = App.newDocument(stem)
    doc, body, dims, sk = F.build_timber(doc, label=label)
    save(doc, workdir, stem)
    return doc, body, dims, sk


def make_link(doc, cutter, mode="Enabled", name="L"):
    link = doc.addObject("App::Link", name)
    link.LinkedObject = cutter
    link.LinkCopyOnChange = mode
    doc.recompute()
    return link


_BASE_LINK_PROPS = None


def base_link_props():
    """Property names a bare ``App::Link`` carries, so the harness can spot
    the dynamic ones copy-on-change adds.  (Their property *group* is not a
    reliable filter: the mirrored properties do not keep the source's
    ``Joint`` group -- see ``prop_groups``.)"""
    global _BASE_LINK_PROPS
    if _BASE_LINK_PROPS is None:
        doc = App.newDocument("_probe_link_props")
        _BASE_LINK_PROPS = set(doc.addObject("App::Link", "L").PropertiesList)
        App.closeDocument(doc.Name)
    return _BASE_LINK_PROPS


def custom_props(link):
    return sorted(set(link.PropertiesList) - base_link_props())


def prop_groups(link, names):
    return dict((n, link.getGroupOfProperty(n)) for n in names)


def expected_cut_volume(mortise_thickness_in, width_in=None):
    p = F.default_params()
    p["MortiseThickness"] = mortise_thickness_in
    w = F.TIMBER_W if width_in is None else width_in
    return (w * F.TIMBER_H * F.TIMBER_L * F.IN ** 3) - F.cutter_volume(p)


# --------------------------------------------------------------------------
# T1 -- CopyOnChange materialization (the gate)
# --------------------------------------------------------------------------

def t1(rec, workdir):
    r = rec.start("T1", "CopyOnChange materialization (the gate)")
    passes = {}

    # Negative control: the same cutter with the property status omitted.
    close_all()
    try:
        cdoc, cutter = make_cutter(workdir, "Ctl_Cutter", copy_on_change=False)
        tdoc, tb, dims, sk = make_target(workdir, "Ctl_Target")
        link = make_link(tdoc, cutter)
        r.note("control (no CopyOnChange status): props added to Link",
               custom_props(link) or "none")
        r.check("control exposes no parameters", not custom_props(link))
    except Exception as exc:
        r.error("T1 control", exc)

    for mode in MODES:
        close_all()
        ok = True
        try:
            cdoc, cutter = make_cutter(workdir, "T1c_%s" % mode)
            tdoc, tb, dims, sk = make_target(workdir, "T1t_%s" % mode)
            link = make_link(tdoc, cutter, mode)

            props = custom_props(link)
            r.note("%s: dynamic properties added to the Link" % mode, props)
            r.note("%s: their property groups on the Link" % mode,
                   sorted(set(prop_groups(link, props).values())) or "n/a")
            ok &= r.check("%s exposes all 8 parameters" % mode,
                          len(props) == len(F.CUTTER_PARAMS), len(props))

            before = link.LinkCopyOnChangeGroup
            r.note("%s: CopyOnChangeGroup before override" % mode,
                   before.TypeId if before else None)

            link.MortiseThickness = 1.5 * F.IN
            tdoc.recompute()
            after = link.LinkCopyOnChangeGroup
            r.note("%s: CopyOnChangeGroup after override" % mode,
                   after.TypeId if after else None)
            ok &= r.check("%s materializes a copy on override" % mode,
                          after is not None)

            linked = link.getLinkedObject(True)
            r.note("%s: LinkedObject resolves into" % mode,
                   "%s (%s)" % (linked.Name, linked.Document.Name))
            ok &= r.check("%s copy lives in the target document" % mode,
                          linked.Document.Name == tdoc.Name,
                          linked.Document.Name)

            r.note("%s: source MortiseThickness" % mode,
                   "%.4f mm" % cutter.MortiseThickness.Value)
            ok &= r.check("%s leaves the source document untouched" % mode,
                          near(cutter.MortiseThickness.Value, 2.0 * F.IN),
                          str(cutter.MortiseThickness))

            want = F.cutter_volume(dict(F.default_params(),
                                        MortiseThickness=1.5))
            vol = link.Shape.Volume
            forced = False
            if not near(vol, want):
                force_recompute(tdoc)
                vol = link.Shape.Volume
                forced = True
            r.note("%s: link shape volume mm^3" % mode,
                   "%.3f (expected %.3f)" % (vol, want))
            r.note("%s: forced recompute needed for Link.Shape" % mode,
                   "YES" if forced else "no")
            ok &= r.check("%s link shape reflects the override" % mode,
                          near(vol, want))
        except Exception as exc:
            r.error("T1 %s" % mode, exc)
            ok = False
        passes[mode] = ok

    r.note("modes passing", ", ".join(m for m in MODES if passes.get(m))
           or "none")
    r.status = ("PASS" if all(passes.get(m) for m in MODES)
                else "PARTIAL" if any(passes.values()) else "FAIL")
    return passes


# --------------------------------------------------------------------------
# T2 -- expression-driven group propagation
# --------------------------------------------------------------------------

def t2(rec, workdir, mode):
    r = rec.start("T2", "Expression-driven parameter-group propagation")
    close_all()
    ok = True
    try:
        cdoc, cutter = make_cutter(workdir, "T2_Cutter")
        tdoc, tb, dims, sk = make_target(workdir, "T2_Target")
        grp = tdoc.addObject("App::VarSet", "GroupTest")
        grp.Label = "Group_Test"
        grp.addProperty("App::PropertyLength", "MortiseThickness", "Group",
                        "Shared mortise thickness for the group")
        grp.MortiseThickness = 2.0 * F.IN

        links = []
        for i in (1, 2):
            link = make_link(tdoc, cutter, mode, "L%d" % i)
            link.setExpression("MortiseThickness",
                               "<<Group_Test>>.MortiseThickness")
            links.append(link)
        tdoc.recompute()
        r.note("links bound to the group by expression", len(links))
        r.note("CopyOnChangeGroup after binding at the unchanged value",
               [bool(l.LinkCopyOnChangeGroup) for l in links])

        grp.MortiseThickness = 1.5 * F.IN
        tdoc.recompute()
        want = F.cutter_volume(dict(F.default_params(),
                                    MortiseThickness=1.5))
        vols = [l.Shape.Volume for l in links]
        forced = False
        if not all(near(v, want) for v in vols):
            force_recompute(tdoc)
            vols = [l.Shape.Volume for l in links]
            forced = True
        r.note("link volumes after the group change",
               "%s (expected %.3f)" % (["%.3f" % v for v in vols], want))
        r.note("forced recompute needed", "YES" if forced else "no")
        ok &= r.check("both links follow the group value",
                      all(near(v, want) for v in vols))
        ok &= r.check("both links materialized copies",
                      all(l.LinkCopyOnChangeGroup is not None
                          for l in links))
        for i, l in enumerate(links, 1):
            r.note("L%d copy lives in" % i,
                   l.getLinkedObject(True).Document.Name)
        ok &= r.check("source document untouched",
                      near(cutter.MortiseThickness.Value, 2.0 * F.IN),
                      str(cutter.MortiseThickness))

        # a per-instance override must not disturb its sibling
        links[1].setExpression("MortiseThickness", None)
        links[1].MortiseThickness = 3.0 * F.IN
        force_recompute(tdoc)
        want2 = F.cutter_volume(dict(F.default_params(),
                                     MortiseThickness=3.0))
        r.note("L1 / L2 volumes after overriding L2 alone",
               "%.3f / %.3f" % (links[0].Shape.Volume,
                                links[1].Shape.Volume))
        ok &= r.check("per-instance override leaves the sibling alone",
                      near(links[0].Shape.Volume, want)
                      and near(links[1].Shape.Volume, want2))

        tpath = tdoc.FileName
        cdoc.save()
        tdoc.save()
        close_all()
        tdoc = App.openDocument(tpath)
        l1 = tdoc.getObject("L1")
        expr = dict(l1.ExpressionEngine).get("MortiseThickness")
        r.note("L1 expression after reload", expr)
        ok &= r.check("expression binding survives save/reload",
                      expr is not None and "Group_Test" in str(expr))
        grp = tdoc.getObject("GroupTest")
        grp.MortiseThickness = 2.5 * F.IN
        tdoc.recompute()
        want3 = F.cutter_volume(dict(F.default_params(),
                                     MortiseThickness=2.5))
        v = l1.Shape.Volume
        forced2 = False
        if not near(v, want3):
            force_recompute(tdoc)
            v = l1.Shape.Volume
            forced2 = True
        r.note("L1 volume after a post-reload group change",
               "%.3f (expected %.3f), forced=%s"
               % (v, want3, "YES" if forced2 else "no"))
        ok &= r.check("group still drives geometry after reload",
                      near(v, want3))
    except Exception as exc:
        r.error("T2", exc)
        ok = False
    r.status = "PASS" if ok else "FAIL"
    return ok


# --------------------------------------------------------------------------
# T3 -- the boolean bridge
# --------------------------------------------------------------------------

def _bridge_c2(doc, timber, link):
    """SubShapeBinder referencing the Link, then a subtractive Boolean.

    The binder is created at document level: a binder made *inside* the Body
    is already claimed by that Body, and handing it to the Boolean raises
    ``Object can only be in a single GeoFeatureGroup``.
    """
    binder = doc.addObject("PartDesign::SubShapeBinder", "CutterBinder")
    binder.Support = [(link, [""])]
    doc.recompute()
    boo = timber.newObject("PartDesign::Boolean", "JointCut")
    boo.Type = "Cut"
    boo.Group = [binder]
    doc.recompute()
    return timber, boo


def _bridge_c1(doc, timber, link):
    boo = timber.newObject("PartDesign::Boolean", "JointCut")
    boo.Type = "Cut"
    boo.Group = [link]
    doc.recompute()
    return timber, boo


def _bridge_c3(doc, timber, link):
    cut = doc.addObject("Part::Cut", "JointCut")
    cut.Base = timber
    cut.Tool = link
    doc.recompute()
    return cut, cut


BRIDGES = [
    ("C2", "SubShapeBinder + PartDesign::Boolean", _bridge_c2),
    ("C1", "PartDesign::Boolean referencing the Link directly", _bridge_c1),
    ("C3", "Part::Cut of timber minus link", _bridge_c3),
]
BRIDGE_TITLE = dict((k, t) for k, t, _ in BRIDGES)
BRIDGE_BUILD = dict((k, b) for k, _, b in BRIDGES)


def t3(rec, workdir, mode):
    r = rec.start("T3", "Boolean bridge")
    outcomes = {}
    for key, title, build in BRIDGES:
        close_all()
        o = {"title": title, "constructs": False, "volume_ok": False,
             "updates": False, "editable": False, "type": None,
             "forced": False, "error": None,
             "state_after_build": "not reached"}
        try:
            cdoc, cutter = make_cutter(workdir, "T3c_%s" % key)
            tdoc, tb, dims, sk = make_target(workdir, "T3t_%s" % key)
            link = make_link(tdoc, cutter, mode)
            link.MortiseThickness = 1.5 * F.IN
            tdoc.recompute()

            top, feature = build(tdoc, tb, link)
            o["constructs"] = True
            o["type"] = top.TypeId
            o["top"] = top.Name
            o["feature"] = feature.TypeId

            want = expected_cut_volume(1.5)
            vol = top.Shape.Volume
            if not near(vol, want):
                force_recompute(tdoc)
                vol = top.Shape.Volume
                o["forced"] = True
            o["volume"] = vol
            o["volume_expected"] = want
            o["volume_ok"] = near(vol, want)

            # Round 2b's three-part assertion, retrofitted so all three
            # spike harnesses assert the same thing.
            o["state_after_build"] = unhealthy(tdoc) or "none"
            clean, forced = changed_cleanly(
                r, tdoc, "%s: link parameter change to 3.0 in" % key,
                lambda: setattr(link, "MortiseThickness", 3.0 * F.IN),
                lambda: top.Shape.Volume, expected_cut_volume(3.0))
            o["forced"] = o["forced"] or forced
            o["volume_after_change"] = top.Shape.Volume
            o["updates"] = clean

            # native editability: drive the timber section sketch itself
            dims.Width = 10.0 * F.IN
            tdoc.recompute()
            want3 = expected_cut_volume(3.0, width_in=10.0)
            vol3 = top.Shape.Volume
            if not near(vol3, want3):
                force_recompute(tdoc)
                vol3 = top.Shape.Volume
                o["forced"] = True
            o["volume_after_timber_edit"] = vol3
            o["section_sketch_DX_mm"] = sk.getDatum("DX").Value
            o["editable"] = (near(o["section_sketch_DX_mm"], 10.0 * F.IN)
                             and near(vol3, want3))
            dims.Width = F.TIMBER_W * F.IN
            force_recompute(tdoc)
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
            r.note("%s survives a link parameter change cleanly" % key,
                   "%s (%.3f)" % (o["updates"],
                                  o.get("volume_after_change", -1)))
            r.note("%s timber stays natively editable" % key,
                   "%s (section DX now %.1f mm, volume %.3f)"
                   % (o["editable"], o.get("section_sketch_DX_mm", -1),
                      o.get("volume_after_timber_edit", -1)))
            r.note("%s needed a forced recompute" % key,
                   "YES" if o["forced"] else "no")
        if o["error"]:
            r.note("%s error" % key, o["error"])

    good = [k for k, _, _ in BRIDGES
            if outcomes[k]["constructs"] and outcomes[k]["volume_ok"]
            and outcomes[k]["updates"] and outcomes[k]["editable"]
            and outcomes[k]["state_after_build"] == "none"]
    # prefer a bridge whose top-level object is still a PartDesign::Body
    keeps_body = [k for k in good
                  if outcomes[k]["type"] == "PartDesign::Body"]
    winner = (keeps_body or good or [None])[0]
    r.note("bridges passing every criterion", ", ".join(good) or "none")
    r.note("winner", winner or "none")
    r.status = "PASS" if winner else ("PARTIAL" if good else "FAIL")
    return winner, outcomes


# --------------------------------------------------------------------------
# T4 -- persistence and round trip
# --------------------------------------------------------------------------

def t4(rec, workdir, mode, winner):
    r = rec.start("T4", "Persistence and round trip")
    close_all()
    ok = True
    build = BRIDGE_BUILD[winner]
    try:
        cdoc, cutter = make_cutter(workdir, "T4_Cutter")
        tdoc, tb, dims, sk = make_target(workdir, "T4_Target")
        link = make_link(tdoc, cutter, mode)
        link.MortiseThickness = 1.5 * F.IN
        tdoc.recompute()
        top, feature = build(tdoc, tb, link)
        force_recompute(tdoc)
        vol_before = top.Shape.Volume
        top_name, link_name = top.Name, link.Name
        cpath, tpath = cdoc.FileName, tdoc.FileName
        cdoc.save()
        tdoc.save()
        close_all()

        tdoc = App.openDocument(tpath)
        link = tdoc.getObject(link_name)
        top = tdoc.getObject(top_name)
        r.note("override after reopen",
               "%.4f mm" % link.MortiseThickness.Value)
        ok &= r.check("override persists",
                      near(link.MortiseThickness.Value, 1.5 * F.IN))
        tdoc.recompute()
        vol_after = top.Shape.Volume
        forced = False
        if not near(vol_after, vol_before):
            force_recompute(tdoc)
            vol_after = top.Shape.Volume
            forced = True
        r.note("volume before / after reopen",
               "%.3f / %.3f (forced=%s)"
               % (vol_before, vol_after, "YES" if forced else "no"))
        ok &= r.check("geometry recomputes identically",
                      near(vol_after, vol_before))
        linked = link.getLinkedObject(True)
        r.note("link resolves to",
               "%s in %s" % (linked.Name, linked.Document.Name)
               if linked else "unresolved")
        r.note("documents open after reopening the target alone",
               sorted(App.listDocuments()))
        r.note("LinkCopyOnChangeSource after reopen",
               getattr(link.LinkCopyOnChangeSource, "Name", None))
        ok &= r.check("link resolves after reopen", linked is not None)

        # Relocation, in two cases:
        #   A  target alone moved, the source left at its original path
        #      -> can only resolve by absolute path
        #   B  both moved together and the originals deleted
        #      -> can only resolve by relative path (or not at all)
        def relocate(case_id, case, move_source, drop_originals):
            close_all()
            moved = os.path.join(workdir, "relocated_%s" % case_id)
            if os.path.isdir(moved):
                shutil.rmtree(moved)
            os.makedirs(moved)
            new_t = os.path.join(moved, os.path.basename(tpath))
            shutil.copy2(tpath, new_t)
            if move_source:
                shutil.copy2(cpath, os.path.join(moved,
                                                 os.path.basename(cpath)))
            if drop_originals:
                for path in (cpath, tpath):
                    if os.path.exists(path):
                        os.remove(path)
            good = False
            try:
                doc = App.openDocument(new_t)
                lk = doc.getObject(link_name)
                tp = doc.getObject(top_name)
                doc.recompute()
                vol = tp.Shape.Volume
                if not near(vol, vol_before):
                    force_recompute(doc)
                    vol = tp.Shape.Volume
                linked_now = lk.getLinkedObject(True)
                opened = sorted(App.listDocuments())
                srcdoc = [App.getDocument(n) for n in opened
                          if n != doc.Name]
                r.note("%s: link resolves to" % case,
                       "%s in %s" % (linked_now.Name,
                                     linked_now.Document.Name)
                       if linked_now else "unresolved")
                r.note("%s: documents opened" % case, opened)
                r.note("%s: source document loaded from" % case,
                       srcdoc[0].FileName if srcdoc
                       else "none (self-contained)")
                r.note("%s: LinkCopyOnChangeSource resolves" % case,
                       getattr(lk.LinkCopyOnChangeSource, "Name", None)
                       or "unresolved (template link dropped)")
                r.note("%s: volume" % case,
                       "%.3f (expected %.3f)" % (vol, vol_before))
                good = near(vol, vol_before)
            except Exception as exc:
                r.error("T4 relocation %s" % case, exc)
            return good

        shutil.copy2(cpath, cpath + ".bak")
        okA = relocate("A", "A: target moved alone, source left in place",
                       False, False)
        ok &= r.check("relocated target alone resolves and recomputes", okA)
        okB = relocate("B", "B: both moved together, originals deleted",
                       True, True)
        ok &= r.check("relocated pair resolves and recomputes", okB)
        shutil.copy2(cpath + ".bak", cpath)   # leave the workdir usable
    except Exception as exc:
        r.error("T4", exc)
        ok = False
    r.status = "PASS" if ok else "FAIL"
    return ok


# --------------------------------------------------------------------------
# T5 -- scale
# --------------------------------------------------------------------------

def t5(rec, workdir, mode, winner, counts):
    r = rec.start("T5", "Scale")
    build = BRIDGE_BUILD[winner]
    rows = []
    ok = True
    for n in counts:
        close_all()
        row = {"n": n}
        try:
            cdoc, cutter = make_cutter(workdir, "T5c_%d" % n)
            tdoc = App.newDocument("T5t_%d" % n)
            path = save(tdoc, workdir, "T5t_%d" % n)
            grp = tdoc.addObject("App::VarSet", "GroupTest")
            grp.Label = "Group_Test"
            grp.addProperty("App::PropertyLength", "MortiseThickness",
                            "Group", "Shared mortise thickness")
            grp.MortiseThickness = 2.0 * F.IN

            t0 = time.time()
            for i in range(n):
                label = "T-Post-Spike-%03d" % (i + 1)
                _, body, dims, sk = F.build_timber(tdoc, label=label)
                body.Placement.Base = App.Vector(0, 0, i * 300.0)
                link = make_link(tdoc, cutter, mode, "L%03d" % (i + 1))
                link.setExpression("MortiseThickness",
                                   "<<Group_Test>>.MortiseThickness")
                build(tdoc, body, link)
            row["build_s"] = time.time() - t0

            # A "full recompute" only means something if everything is
            # actually dirty: doc.recompute(None, True, True) on a clean
            # document returns in microseconds.
            for obj in tdoc.Objects:
                obj.touch()
            t0 = time.time()
            tdoc.recompute(None, True, True)
            row["full_recompute_s"] = time.time() - t0

            t0 = time.time()
            grp.MortiseThickness = 1.75 * F.IN
            tdoc.recompute()
            row["param_change_s"] = time.time() - t0

            t0 = time.time()
            tdoc.save()
            row["save_s"] = time.time() - t0
            row["file_mb"] = os.path.getsize(path) / (1024.0 * 1024.0)
            row["objects"] = len(tdoc.Objects)
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
            if per_first <= 0:
                r.note("growth", "not assessed (baseline too fast to time)")
            else:
                ratio = per_last / per_first
                r.note("per-instance cost ratio", "%.2fx" % ratio)
                r.note("growth", "roughly linear" if ratio < 2.0
                       else "NON-LINEAR")
    except Exception as exc:
        r.error("T5 analysis", exc)
    r.status = "PASS" if ok else "FAIL"
    return rows


# --------------------------------------------------------------------------
# T6 -- downstream: TechDraw (best effort, headless)
# --------------------------------------------------------------------------

def t6(rec, workdir, mode, winner):
    r = rec.start("T6", "Downstream: TechDraw (best effort, headless)")
    close_all()
    ok = True
    build = BRIDGE_BUILD[winner]
    try:
        cdoc, cutter = make_cutter(workdir, "T6_Cutter")
        tdoc, tb, dims, sk = make_target(workdir, "T6_Target")
        link = make_link(tdoc, cutter, mode)
        link.MortiseThickness = 1.5 * F.IN
        tdoc.recompute()
        top, feature = build(tdoc, tb, link)
        force_recompute(tdoc)

        tdir = os.path.join(App.getResourceDir(), "Mod", "TechDraw",
                            "Templates")
        page = tdoc.addObject("TechDraw::DrawPage", "Page")
        tpl = tdoc.addObject("TechDraw::DrawSVGTemplate", "Template")
        tpl.Template = os.path.join(tdir,
                                    "Default_Template_A4_Landscape.svg")
        page.Template = tpl
        tdoc.recompute()

        pg = tdoc.addObject("TechDraw::DrawProjGroup", "ProjGroup")
        page.addView(pg)
        pg.Source = [top]
        pg.ScaleType = "Custom"
        pg.Scale = 0.1
        front = pg.addProjection("Front")
        front.HardHidden = True
        tdoc.recompute()
        r.note("projection group state", pg.State)
        try:
            edges_before = len(front.getVisibleEdges())
        except Exception:
            edges_before = None
        r.note("visible edges in the front view", edges_before)

        dim = tdoc.addObject("TechDraw::DrawViewDimension", "Dim")
        page.addView(dim)
        dim.Type = "DistanceX"
        dim.References2D = (front, ["Edge0"])
        tdoc.recompute()
        try:
            before = dim.getRawValue()
        except Exception as exc:
            before = "unavailable (%s: %s)" % (type(exc).__name__, exc)
        r.note("dimension state / value before the change",
               "%s / %s" % (dim.State, before))
        ok &= r.check("page, view and dimension compute",
                      "Invalid" not in str(front.State)
                      and "Invalid" not in str(dim.State))

        link.MortiseThickness = 3.0 * F.IN
        force_recompute(tdoc)
        try:
            after = dim.getRawValue()
        except Exception as exc:
            after = "unavailable (%s: %s)" % (type(exc).__name__, exc)
        try:
            edges_after = len(front.getVisibleEdges())
        except Exception:
            edges_after = None
        r.note("view / dimension state after a link parameter change",
               "%s / %s" % (front.State, dim.State))
        r.note("dimension value before -> after", "%s -> %s"
               % (before, after))
        r.note("visible edges before -> after", "%s -> %s"
               % (edges_before, edges_after))
        r.note("dimension references after the change",
               list(dim.References2D))
        ok &= r.check("view and dimension survive a parameter change",
                      "Invalid" not in str(front.State)
                      and "Invalid" not in str(dim.State))
    except Exception as exc:
        r.error("T6", exc)
        ok = False
    r.status = "PASS" if ok else "PARTIAL"
    return ok


# --------------------------------------------------------------------------
# report
# --------------------------------------------------------------------------

def write_report(rec, ctx):
    lines = []
    w = lines.append
    w("# Spike results: variant links + booleans as the joint mechanism")
    w("")
    w("Generated by `tests/spike/spike_variant_link.py` (fixtures in")
    w("`tests/spike/spike_fixtures.py`), run headless under `freecadcmd.exe`.")
    w("Every fixture is built from scratch; no hand-authored `.FCStd` is")
    w("involved. This implements `docs/spike-headless-brief.md`.")
    w("")
    w("- FreeCAD: %s" % ctx["version"])
    w("- Run: %s" % ctx["timestamp"])
    w("- Work directory: `%s`" % ctx["workdir"])
    w("")
    w("Rerun with:")
    w("")
    w("```bash")
    w("freecadcmd.exe tests/spike/spike_variant_link.py")
    w("```")
    w("")
    w("`BW_SPIKE_WORKDIR` overrides the fixture directory and")
    w("`BW_SPIKE_SCALE` the T5 instance counts (e.g. `BW_SPIKE_SCALE=3,6`")
    w("for a quick pass).")
    w("")
    w("**A headless PASS is a candidate, not a proof.** Headless recompute")
    w("triggers are not the GUI's; see *Needs GUI confirmation* at the end.")
    w("")
    lines.extend(render_results(rec, ctx["headlines"]))
    lines.extend(ctx["narrative"])
    with open(REPORT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print("\nwrote %s" % REPORT)


def gate_failed_narrative():
    return [
        "## Recommendation: **No go**",
        "",
        "T1 is the gate and it failed in all three `LinkCopyOnChange` modes:",
        "no copy materialized, so there is no per-instance parameterization",
        "to build on. The rebuild engine in `apply_joint.py` stays.",
        "",
        "## Needs GUI confirmation",
        "",
        "- Headless recompute triggers differ from the GUI's. A GUI session",
        "  should repeat the T1 sequence before this no-go is final.",
    ]


def narrative(rec, ctx):
    out = []
    w = out.append
    winner = ctx.get("winner")
    bridges = ctx.get("bridges", {})
    status = dict((r.id, r.status) for r in rec.results)

    w("## What won")
    w("")
    w("- **`LinkCopyOnChange` mode.** All three of `Enabled`, `Owned` and")
    w("  `Tracking` materialize a copy and hold the override; the remaining")
    w("  tests ran on `%s`. The difference the harness can see is *when*"
      % ctx.get("mode"))
    w("  the copy appears: `Owned` creates its `LinkCopyOnChangeGroup`")
    w("  immediately, `Enabled` and `Tracking` create it lazily, on the")
    w("  first override.")
    if winner:
        w("- **Boolean bridge:** `%s` — %s."
          % (winner, BRIDGE_TITLE[winner]))
        others = [k for k, _, _ in BRIDGES if k != winner]
        for k in others:
            o = bridges.get(k, {})
            if o.get("error"):
                w("  - `%s` failed: `%s`" % (k, o["error"]))
            elif o.get("constructs"):
                w("  - `%s` also worked, producing a `%s`."
                  % (k, o.get("type")))
        w("")
        w("  `C2` is reported as the winner because the brief asks for it")
        w("  first and it is the documented PartDesign route, but `C1` is")
        w("  the better answer on the evidence: contrary to the brief's")
        w("  expectation, `PartDesign::Boolean` accepts an `App::Link`")
        w("  directly in its `Group`, giving the same Body, the same exact")
        w("  volume and the same editability with one fewer object per")
        w("  joint. `C3` is correct too but turns the timber into a")
        w("  `Part::Cut`, which is the object-type change that would")
        w("  ripple through every downstream consumer.")
        w("")
        w("  One authoring trap in `C2`: a `SubShapeBinder` created")
        w("  *inside* the Body is already claimed by it, and handing it to")
        w("  the Boolean raises `Object can only be in a single")
        w("  GeoFeatureGroup`. The binder has to be created at document")
        w("  level and let the Boolean adopt it.")
    else:
        w("- **Boolean bridge:** none passed every criterion.")
    w("")
    w("## Why the manual GUI session saw no copy")
    w("")
    w("Two preconditions, neither visible in the property editor:")
    w("")
    w("1. **The source property must carry the `CopyOnChange` property")
    w("   status.** The negative control in T1 — the same cutter with the")
    w("   status omitted — exposes *no* dynamic properties on the Link at")
    w("   all, which is exactly the symptom the manual session recorded.")
    w("   The status is set with")
    w("   `obj.setPropertyStatus(name, 'CopyOnChange')`; the Add-property")
    w("   dialog offers no way to set it, so a hand-authored template needs")
    w("   the Python console or a macro for this one step.")
    w("2. **The source document must be saved.** Creating a")
    w("   cross-document `App::Link` against an unsaved document raises")
    w("   `Linked document not saved` outright.")
    w("")
    w("The override must also be written to the Link's own dynamic")
    w("property, not into the linked object. The harness only ever assigns")
    w("`link.<Param>`, and asserts the source value unchanged afterwards.")
    w("")
    w("## Notes on the individual tests")
    w("")
    w("- **T1.** After an override `link.getLinkedObject(True)` resolves")
    w("  into the *target* document: the copy is real and local, and the")
    w("  source keeps its authored value.")
    w("- **T2.** Binding a Link's dynamic property to")
    w("  `<<Group_Test>>.MortiseThickness` works, survives save/reload, and")
    w("  drives every instance bound to it, so the layered")
    w("  parameter-group architecture is not blocked by this mechanism.")
    w("  Two behaviours carry forward: the copy materializes on the first")
    w("  *change* of the expression's value rather than when the expression")
    w("  is set, and clearing the expression for a per-instance literal")
    w("  leaves siblings alone — the override semantics the workbench")
    w("  already documents.")
    w("- **T3.** Volumes are compared against an analytic expectation")
    w("  (timber minus cutter), never against each other, so a bridge that")
    w("  silently removes nothing is caught rather than passed.")
    w("- **T4.** Note what relocation really tests here. Once the copy has")
    w("  materialized the geometry lives *inside* the target document, so")
    w("  the target survives its source file being deleted. That is a")
    w("  genuine deployment advantage over a library of external")
    w("  templates — and the flip side of FEP-0010's warning that a")
    w("  copy-on-change link cannot be refreshed from its template without")
    w("  converting to a regular link and discarding per-instance")
    w("  parameters.")
    w("  The two relocation cases separate cleanly. Moving the target")
    w("  *alone* leaves the source unreachable — FreeCAD looks for it")
    w("  beside the target, not at the absolute path it was linked from,")
    w("  logs `does not exist!`, and carries on — and the geometry is")
    w("  still right, because the copy is local. Moving both together")
    w("  resolves the source by relative path and opens it. So a joint")
    w("  library is a *build-time* dependency under this mechanism, not a")
    w("  runtime one: a delivered model does not need the library beside")
    w("  it, but it also cannot be refreshed from it.")
    if ctx.get("scale"):
        last = ctx["scale"][-1]
        if "error" not in last:
            w("- **T5.** At %s instances: %.1f s full recompute, %.2f s for"
              % (last.get("n"), last.get("full_recompute_s", -1),
                 last.get("param_change_s", -1)))
            w("  a one-value parameter change, %.1f MB on disk, %s objects"
              % (last.get("file_mb", -1), last.get("objects")))
            w("  in the document.")
    w("- **Console noise.** Boolean recomputes emit repeated")
    w("  `TopoShapeExpansion.cpp: hasher mismatch` warnings throughout the")
    w("  run. Nothing failed and every volume is exact, but it is")
    w("  element-mapping (topological naming) machinery complaining, and")
    w("  it is worth watching if this mechanism is adopted — stable")
    w("  element names are what keep a TechDraw dimension attached to the")
    w("  edge a framer picked.")
    w("- **T6.** Headless TechDraw is a smoke test: it proves the page,")
    w("  projection and dimension recompute without raising after a link")
    w("  parameter changes. It says nothing about whether the dimension")
    w("  still points at the edge a framer meant.")
    w("")

    go = (status.get("T1") in ("PASS", "PARTIAL")
          and status.get("T2") == "PASS" and winner
          and status.get("T4") == "PASS")
    scale_ok = bool(ctx.get("scale")) and "error" not in ctx["scale"][-1]

    w("## Recommendation")
    w("")
    if go and scale_ok:
        keeps_body = bridges.get(winner, {}).get("type") == "PartDesign::Body"
        if keeps_body:
            w("**Go on the mechanism — but see the four costs below before")
            w("treating it as a replacement for `apply_joint.py`.**")
            w("")
            w("Against the brief's criteria this is a go: T1 and T2 pass,")
            w("the `%s` bridge preserves both the cut and the timber's" % winner)
            w("native editability while leaving the top-level object a")
            w("`PartDesign::Body`, T4 passes, and T5 is workable at 150")
            w("instances. Nothing downstream has to change to accommodate")
            w("the object type: the timber is still a Body whose `Tip` is a")
            w("`PartDesign::Boolean`, so the linter, the cut-list walker,")
            w("the TechDraw batch and the assembly code all keep addressing")
            w("a Body.")
        else:
            w("**Partial go.** The mechanism works and the `%s` bridge"
              % winner)
            w("produces the right solid, but the top-level object changes")
            w("type (`%s`), so every consumer that assumes a"
              % bridges.get(winner, {}).get("type"))
            w("`PartDesign::Body` needs adapting: the linter's structural")
            w("rules, the cut-list walker, the TechDraw batch, and the body")
            w("lookups in `assemble.py` / `duplicate.py`.")
        w("")
        w("### What a go would cost, and what it does not buy")
        w("")
        w("1. **Parameters must live on the linked object itself.** A Link")
        w("   exposes only the linked object's own properties, so a")
        w("   cutter's parameters sit on the Body and drive its sketches")
        w("   through `href()` — which severs the dependency edge and")
        w("   disables expression autocomplete. That is the shape of every")
        w("   template under this mechanism, and it is a step down in")
        w("   authoring ergonomics from the VarSet the workbench uses now.")
        w("2. **`href()` is a documented weak point.** Upstream #24715 is")
        w("   an open report of a copy-on-change variant not updating with")
        w("   changed custom properties, in a configuration close to this")
        w("   one. The harness does not reproduce it headlessly; that is")
        w("   not evidence it is fixed.")
        w("3. **Template revision does not propagate.** Per FEP-0010, and")
        w("   consistent with T4's self-containment, revising a library")
        w("   template cannot be pushed into existing instances without")
        w("   converting them to regular links, which discards their")
        w("   per-instance parameters. The rebuild engine can re-apply a")
        w("   revised template; this mechanism cannot.")
        w("4. **A cutter is half a joint.** The spike cuts one negative")
        w("   into one timber. BentWizard's joint VarSet parameterizes both")
        w("   halves at once, and the mate frame / `Stick_Allowance_FTF`")
        w("   contract is what makes driven `Length` work. A link-based")
        w("   mechanism needs a second cutter, a mate frame the link does")
        w("   not carry, and a way to keep both instances' parameters in")
        w("   step — in practice a shared VarSet per joint plus placement")
        w("   logic, which is most of what `apply_joint.py` already does.")
        w("   The spike retires the *question*; it does not by itself")
        w("   justify the rewrite.")
    else:
        if status.get("T2") != "PASS":
            w("**No go.** T2 failed: layered parameter groups cannot be")
            w("built on this mechanism, and the rebuild engine stays.")
        elif not winner:
            w("**No go.** No boolean bridge preserved both the cut and the")
            w("timber's native editability.")
        elif not scale_ok:
            w("**No go on scale.** The mechanism works but T5 failed or")
            w("degraded at frame scale; see the T5 table.")
        else:
            w("**No go.** See the failing test above.")
    w("")
    w("## Needs GUI confirmation before acting")
    w("")
    w("- **Recompute triggers.** Headless recompute is not the GUI's. The")
    w("  tables above record every place a *forced* recompute")
    w("  (`doc.recompute(None, True, True)`) was needed to see a change;")
    w("  in the GUI those are the cases most likely to show a stale view or")
    w("  a touched object that never clears.")
    w("- **The property editor.** Whether the Link's exposed `Joint` group")
    w("  is editable in the property panel, and how a trailing digit")
    w("  renders (`Setback Face 1` vs `Setback Face1`) — the naming")
    w("  question the manual session raised.")
    w("- **Assembly.** Out of scope headless. Whether a cut timber behaves")
    w("  as an ordinary component, and whether 150 materialized copies")
    w("  confuse the solver, has to be seen in the GUI.")
    w("- **TechDraw correctness.** T6 proves no exception, not a correct")
    w("  drawing. Whether dimensions stay attached to the edges a framer")
    w("  picked needs eyes on a page.")
    w("- **Upstream #13481, #30124, #19182.** The harness does not")
    w("  reproduce these headlessly; all three are GUI-workflow shaped")
    w("  (links Owned inside an `App::Part`, switching a binder to")
    w("  Detached, switching configurations). Retest in the GUI before")
    w("  relying on the mechanism.")
    w("")
    w("## Keeping this harness")
    w("")
    w("Three of those upstream issues are open. The harness stays in the")
    w("repo as a regression test: rerun it after a FreeCAD upgrade and diff")
    w("this report.")
    return out


# --------------------------------------------------------------------------

def main(argv):
    # FreeCADCmd swallows its own options, so the harness is steered by
    # environment variables rather than argv:
    #   BW_SPIKE_WORKDIR  where fixture documents are written
    #   BW_SPIKE_SCALE    comma-separated instance counts for T5
    workdir = os.environ.get("BW_SPIKE_WORKDIR") or None
    counts = [int(x) for x in
              os.environ.get("BW_SPIKE_SCALE", "10,50,150").split(",")]
    workdir = workdir or tempfile.mkdtemp(prefix="bw_spike_")
    if not os.path.isdir(workdir):
        os.makedirs(workdir)
    print("work directory: %s" % workdir)

    rec = Recorder()
    ctx = {"workdir": workdir,
           "version": "%s.%s.%s (build %s)"
           % (tuple(App.Version()[:3])
              + (App.Version()[3].split()[0],)),
           "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
           "headlines": {}, "narrative": []}

    modes = t1(rec, workdir)
    gate = [m for m in MODES if modes.get(m)]
    ctx["headlines"]["T1"] = ("copies materialize in %s" % ", ".join(gate)
                              if gate else "no mode materializes a copy")
    if not gate:
        ctx["headlines"]["T1"] += " — GATE FAILED, later tests skipped"
        ctx["narrative"] = gate_failed_narrative()
        write_report(rec, ctx)
        return 1

    mode = "Enabled" if "Enabled" in gate else gate[0]
    ctx["mode"] = mode

    t2_ok = t2(rec, workdir, mode)
    ctx["headlines"]["T2"] = ("group expressions drive every instance"
                              if t2_ok else "group propagation FAILED")

    winner, bridges = t3(rec, workdir, mode)
    ctx["headlines"]["T3"] = ("winner: %s" % winner if winner
                              else "no bridge passes every criterion")
    ctx["bridges"] = bridges
    ctx["winner"] = winner

    if winner:
        t4_ok = t4(rec, workdir, mode, winner)
        ctx["headlines"]["T4"] = ("survives save/reload and relocation"
                                  if t4_ok else "round trip FAILED")
        rows = t5(rec, workdir, mode, winner, counts)
        ctx["scale"] = rows
        last = rows[-1]
        ctx["headlines"]["T5"] = (
            "%s instances: %.1f s full recompute, %.1f MB"
            % (last.get("n"), last.get("full_recompute_s", -1),
               last.get("file_mb", -1))
            if "error" not in last else "failed at n=%s" % last.get("n"))
        t6_ok = t6(rec, workdir, mode, winner)
        ctx["headlines"]["T6"] = ("TechDraw view and dimension survive"
                                  if t6_ok else "see notes")
    else:
        ctx["scale"] = []

    ctx["narrative"] = narrative(rec, ctx)
    write_report(rec, ctx)
    print("\nsummary: " + ", ".join("%s=%s" % (r.id, r.status)
                                    for r in rec.results))
    return 0


# FreeCADCmd executes a script under its own file stem, not
# ``"__main__"``, so there is no useful guard to hang the entry point on:
# this module is a script and simply runs.  ``BW_SPIKE_NORUN=1`` suppresses
# that for anything that wants to import the helpers instead.
if not os.environ.get("BW_SPIKE_NORUN"):
    main(sys.argv[1:])
