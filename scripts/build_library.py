"""Build the shipped joint templates from the workbench's own API.

    freecadcmd.exe scripts/build_library.py [out_dir]

Writes library/Joint_Butt.FCStd (the jointless starter: two timbers
with a paired datum each and an empty joint VarSet) and
library/Joint_HousedMT.FCStd (a housed, square-shouldered mortise and
tenon: a Cutter on the post's face datum, an Adder on the girt's
end-B datum), then runs the template bar on both. Reproducible: the
files are exactly what New Timber, Add Datum and the component helpers
produce, so the library is a test of the tool as much as a product.
"""

import FreeCAD as App  # noqa: E402  FIRST — see below
# On FreeCAD 26.3, `import FreeCAD` REMOVES from __main__'s globals any
# name imported before it that collides with one of FreeCAD's own
# modules — `Path` (pathlib) being the one that bit: bound at module
# level, then gone by the time a function used it, with no error. A
# script's FreeCAD import therefore comes before everything else.
# 1.1.3 does not do this.
import os  # noqa: E402
import sys  # noqa: E402
from pathlib import Path  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))
import _repo_path  # noqa: E402

_repo_path.graft()

from freecad.bentwizard import component, datums, naming  # noqa: E402
from freecad.bentwizard.timber import new_timber  # noqa: E402

IN = 25.4
HOST, MATE = "T-Post-000", "T-Girt-000"


def skeleton(doc, kind, handed=None):
    """Two timbers, host datum on the post's +Y face at 48 in, the
    girt's end B paired to it under J-<kind>-000, girt seated. `handed`
    (bool) declares the template's Handed flag; None leaves it
    undeclared, which keeps the mirror rule."""
    post, _ = new_timber(doc, HOST, "8 in", "8 in", "8 ft")
    girt, _ = new_timber(doc, MATE, "6 in", "8 in", "6 ft")
    host = datums.add_datum(post, "YPos", "48 in")
    mate = datums.end_datum(girt, "EndB")
    vs = doc.addObject("App::VarSet", "JointVS")
    vs.Label = naming.joint_label(kind, naming.TEMPLATE_SERIAL)
    if handed is not None:
        add_param(vs, naming.PROP_TEMPLATE_HANDED, "App::PropertyBool", handed,
                  "False: the joint looks the same from either side, so "
                  "Apply never mirrors it. True: it has a hand, and Apply "
                  "mirrors a component applied at a datum of the other "
                  "parity (the opposite face or end).",
                  naming.TEMPLATE_META_GROUP)
    # a template stays one object: its accessors live on its own joint
    # VarSet, and Apply expands them onto Accessors_<joint> as it copies
    datums.pair(host, mate, vs, separate=False)
    doc.recompute()
    girt.Placement = datums.seat_delta(host, mate).multiply(girt.Placement)
    doc.recompute()
    return post, girt, host, mate, vs


def add_param(vs, name, type_id, value, tooltip, group="Joint"):
    vs.addProperty(type_id, name, group, tooltip)
    setattr(vs, name, value)


def build_butt(doc):
    _post, _girt, _host, _mate, vs = skeleton(doc, "Butt", handed=False)
    add_param(vs, "PegCount", "App::PropertyInteger", 0,
              "Number of pegs (or bolts) at this connection — schedule "
              "data only, no geometry.")
    return vs


def build_housed_mt(doc):
    # centred tenon and housing: the same from either side
    post, girt, host, mate, vs = skeleton(doc, "HousedMT", handed=False)
    J = f"<<{vs.Label}>>"
    add_param(vs, "TenonThickness", "App::PropertyLength", 2 * IN,
              "Tenon (and mortise) thickness, measured across the host's "
              "face — along the datum's U axis.")
    add_param(vs, "TenonWidth", "App::PropertyLength", 6 * IN,
              "Tenon (and mortise) width, measured along the host timber "
              "— the datum's V axis. Leaves a shoulder each side of the "
              "girt's depth.")
    add_param(vs, "TenonLength", "App::PropertyLength", 4 * IN,
              "How far the tenon runs into the host past the housing "
              "floor.")
    add_param(vs, "HousingDepth", "App::PropertyLength", 0.5 * IN,
              "Depth of the housing cut into the host's face, which the "
              "girt's full section seats in. 0 for no housing.")
    add_param(vs, "MortiseFit", "App::PropertyLength", IN / 16,
              "Extra mortise depth beyond the tenon so the shoulder "
              "seats before the tenon tip bottoms out. No lateral "
              "allowance: cheeks are tight.")
    add_param(vs, "PegCount", "App::PropertyInteger", 1,
              "Number of pegs through the tenon — schedule data only, "
              "no geometry yet.")
    add_param(vs, "TenonLengthMin", "App::PropertyLength", 2 * IN,
              "Lower bound of the valid range for TenonLength (the "
              "registration sweep and the apply dialog use it).", "Ranges")
    add_param(vs, "TenonLengthMax", "App::PropertyLength", 6 * IN,
              "Upper bound of the valid range for TenonLength.", "Ranges")

    # Cutter on the post: the housing (the girt's whole section, HousingDepth
    # deep) and the mortise (TenonLength + HousingDepth + MortiseFit deep),
    # both grown in -Z from the face
    mortise = component.new_component(doc, naming.component_label(
        "Mortise", "HousedMT", "000"), naming.COMPONENT_CUTTER, 1, vs, host)
    component.add_prism(mortise, "Housing", J + ".MateWidthU", J + ".MateWidthV",
                        J + ".HousingDepth", direction=-1)
    component.add_prism(mortise, "MortisePrism", J + ".TenonThickness",
                        J + ".TenonWidth",
                        J + ".TenonLength + " + J + ".HousingDepth + " + J + ".MortiseFit",
                        direction=-1)
    # Adder on the girt's end B: the full section through the housing, then
    # the tenon, both grown in +Z past the design end
    D = f"<<{mate.Label}>>"
    tenon = component.new_component(doc, naming.component_label(
        "Tenon", "HousedMT", "000"), naming.COMPONENT_ADDER, 2, vs, mate)
    component.add_prism(tenon, "Shoulder", D + ".WidthU", D + ".WidthV",
                        J + ".HousingDepth", direction=+1)
    component.add_prism(tenon, "TenonPrism", J + ".TenonThickness", J + ".TenonWidth",
                        J + ".TenonLength + " + J + ".HousingDepth", direction=+1)
    doc.recompute()
    component.apply_boolean(post, mortise, naming.COMPONENT_CUTTER,
                            naming.boolean_label(naming.COMPONENT_CUTTER, mortise.Label))
    component.apply_boolean(girt, tenon, naming.COMPONENT_ADDER,
                            naming.boolean_label(naming.COMPONENT_ADDER, tenon.Label))
    doc.recompute()
    return vs


def build(out_dir):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for kind, builder in (("Butt", build_butt), ("HousedMT", build_housed_mt)):
        doc = App.newDocument("Template")
        builder(doc)
        doc.recompute()
        path = out_dir / f"Joint_{kind}.FCStd"
        doc.saveAs(str(path))
        App.closeDocument(doc.Name)
        written.append(path)
    return written


def main(argv):
    out_dir = Path(argv[0]) if argv else REPO / "library"
    from freecad.bentwizard import template_check
    bad = 0
    for path in build(out_dir):
        findings = template_check.check(path) + template_check.check_geometry(path)
        report = template_check.format_report(path, findings)
        print(report)
        bad += sum(1 for f in findings if f.severity == template_check.STRICT)
    return 1 if bad else 0


if __name__ == "__main__":
    code = main(sys.argv[1:])
    if "freecadcmd" in os.path.basename(sys.executable).lower() or not sys.stdout.isatty():
        pass
    sys.exit(code)
