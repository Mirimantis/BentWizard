"""One-off migration of the library templates to the descriptive-first
feature label scheme (July 2026).

Run under the portable FreeCAD's headless interpreter:

    freecadcmd.exe scripts/migrate-naming.py

Feature labels move from '<TimberLabel>_<Feature>_<JointLabel>' to
'<Descriptive>[.<TypeTag>].<Abbrev>.<serial>' — see naming.py. Nothing in
the workbench reads a feature label (joint membership is structural and
no expression targets one), so this is a pure relabel: NO geometry, no
placement and no expression VALUE changes. Expressions that reference a
renamed VarSet by '<<Label>>' are rewritten by FreeCAD itself when the
Label is set — verified against 1.1.1 — so they are not touched here.

Alongside the relabel this adds the two Tier-2 markers the new scheme
needs: `Template_Abbrev` on the joint VarSet (the short kind token the
feature labels carry) and `Frame_Role` on each joint frame (what the
retired 'JointFrame'/'MateFrame' label substrings used to imply).

`Joint_HousedMT` additionally comes off the pre-July-2026 legacy scheme
entirely: `P0-1`/`B0-1` bodies, a `Joint_MT_0a` VarSet, no
TimberJointVars group and no Template_* metadata.

The script maps INTERNAL NAMES (which never change) to new labels, so it
is safe to re-run — and it fails loudly if a mapped name is missing or a
stale token survives, so a half-applied run cannot pass silently.
"""

import os
import sys

import FreeCAD as App

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from freecad.bentwizard import naming          # noqa: E402

LANDING = naming.FRAME_ROLE_LANDING
MATE = naming.FRAME_ROLE_MATE

FRAME_ROLE_TOOLTIP = (
    "This frame's role in the timber joint: 'Landing' (where the joint "
    "sits on this timber) or 'Mate' (the pose this timber takes when "
    "seated). Read by Preview, Assemble and Duplicate.")
ABBREV_TOOLTIP = (
    "Short kind token this template's feature labels carry "
    "(<Descriptive>[.<TypeTag>].<Abbrev>.<serial>). Keep it unique "
    "across the joint library.")
HANDED_TOOLTIP = (
    "True when the mirrored hand of this joint is geometrically "
    "distinct, so Apply-Joint offers a hand choice.")

# --- Joint_WedgedHalfDovetail --------------------------------------------
# Post half takes the socket; anchor beam carries the dovetail tail. The
# tail pocket was labelled 'HalfTailAngle' in the file while its sketch
# said 'TailSlope' — the build recipe calls it TailSlope, so the pair is
# reunited under that name.
WHD = {
    "labels": {
        "TimberDims": "TDim_T.Post.001",
        "SectionSketch": naming.section_sketch_label("T.Post.001"),
        "Stick": naming.stick_label("T.Post.001"),
        "TimberDims001": "TDim_T.AnchorBeam.001",
        "SectionSketch001": naming.section_sketch_label("T.AnchorBeam.001"),
        "Stick001": naming.stick_label("T.AnchorBeam.001"),
        "LCS": "Socket.Lcs.WHD.000",
        "Sketch": "Housing.Skt.WHD.000",
        "Pocket": "Housing.WHD.000",
        "Sketch001": "Mortise.Skt.WHD.000",
        "Pocket001": "Mortise.WHD.000",
        "LCS001": "Tail.Lcs.WHD.000",
        "Sketch002": "Cheeks.Skt.WHD.000",
        "Pocket002": "Cheeks.WHD.000",
        "Sketch003": "TailSlope.Skt.WHD.000",
        "Pocket003": "TailSlope.WHD.000",
        "LCS002": "Mate.Lcs.WHD.000",
    },
    "frame_roles": {"LCS": LANDING, "LCS001": LANDING, "LCS002": MATE},
    "joint_varset": "VarSet",
    "abbrev": "WHD",
    "stale_tokens": ["T.Post.001_", "T.AnchorBeam.001_", "JointFrame",
                     "MateFrame", "TimberDims_"],
}

# --- Joint_HousedMT -------------------------------------------------------
# Both halves carry a peg bore, so the descriptive names are qualified by
# which half they cut — the within-template uniqueness rule that replaces
# the timber prefix.
HMT = {
    "labels": {
        "VarSet": "TDim_T.Post.001",
        "Body": "T.Post.001",
        "Sketch": naming.section_sketch_label("T.Post.001"),
        "Pad": naming.stick_label("T.Post.001"),
        "VarSet001": "TDim_T.AnchorBeam.001",
        "Body001": "T.AnchorBeam.001",
        "Sketch001": naming.section_sketch_label("T.AnchorBeam.001"),
        "Pad001": naming.stick_label("T.AnchorBeam.001"),
        "VarSet002": "J-HousedMT-000",
        "LCS": "Mortise.Lcs.HMT.000",
        "Sketch002": "Housing.Skt.HMT.000",
        "Pocket": "Housing.HMT.000",
        "Sketch003": "Mortise.Skt.HMT.000",
        "Pocket001": "Mortise.HMT.000",
        "Sketch004": "MortisePegBore.Skt.HMT.000",
        "Pocket002": "MortisePegBore.HMT.000",
        "LCS001": "Tenon.Lcs.HMT.000",
        "Sketch005": "Tenon.Skt.HMT.000",
        "Pocket003": "Tenon.HMT.000",
        "DatumPlane": "ShoulderA.Dtm.HMT.000",
        "Sketch006": "TenonPegBore.Skt.HMT.000",
        "Hole": "TenonPegBore.HMT.000",
        "LCS002": "Mate.Lcs.HMT.000",
    },
    "frame_roles": {"LCS": LANDING, "LCS001": LANDING, "LCS002": MATE},
    "joint_varset": "VarSet002",
    "abbrev": "HMT",
    # this template predates Template_Handed; True is what TemplateSpec
    # already defaults to for it, so the hand option keeps working exactly
    # as it does today
    "handed": True,
    "needs_joints_group": True,
    "stale_tokens": ["P0-1", "B0-1", "MT_0a", "JointFrame", "MateFrame",
                     "TimberDims_"],
}

PLAN = [
    ("library/Joint_WedgedHalfDovetail.FCStd", WHD),
    ("library/Joint_HousedMT.FCStd", HMT),
]


def migrate(path, spec):
    doc = App.openDocument(path)
    by_name = {o.Name: o for o in doc.Objects}

    missing = sorted(set(spec["labels"]) - set(by_name))
    if missing:
        raise SystemExit(f"{path}: no such object(s): {', '.join(missing)}")

    for name, label in spec["labels"].items():
        by_name[name].Label = label

    for name, role in spec["frame_roles"].items():
        obj = by_name[name]
        if naming.FRAME_ROLE_PROP not in obj.PropertiesList:
            obj.addProperty("App::PropertyString", naming.FRAME_ROLE_PROP,
                            "TimberJoint", FRAME_ROLE_TOOLTIP)
        setattr(obj, naming.FRAME_ROLE_PROP, role)

    varset = by_name[spec["joint_varset"]]
    if naming.TEMPLATE_ABBREV not in varset.PropertiesList:
        varset.addProperty("App::PropertyString", naming.TEMPLATE_ABBREV,
                           naming.TEMPLATE_META_GROUP, ABBREV_TOOLTIP)
    setattr(varset, naming.TEMPLATE_ABBREV, spec["abbrev"])

    if "handed" in spec and "Template_Handed" not in varset.PropertiesList:
        varset.addProperty("App::PropertyBool", "Template_Handed",
                           naming.TEMPLATE_META_GROUP, HANDED_TOOLTIP)
        varset.Template_Handed = spec["handed"]

    if spec.get("needs_joints_group") and not [
            o for o in doc.Objects
            if o.TypeId == "App::DocumentObjectGroup"
            and o.Label == "TimberJointVars"]:
        group = doc.addObject("App::DocumentObjectGroup", "TimberJointVars")
        group.Label = "TimberJointVars"
        group.addObject(varset)

    doc.recompute()

    bad = [o.Name for o in doc.Objects
           if "Invalid" in o.State or "Error" in o.State]
    if bad:
        raise SystemExit(f"{path}: recompute failed for {', '.join(bad)}")

    # Nothing may still carry a token that only made sense in the template
    # (its own timber names, the legacy joint id, the retired frame words).
    for obj in doc.Objects:
        for token in spec["stale_tokens"]:
            if token in obj.Label:
                raise SystemExit(
                    f"{path}: {obj.Name} label {obj.Label!r} still carries "
                    f"the stale token {token!r}")

    doc.save()
    App.closeDocument(doc.Name)
    print(f"migrated {path}")


for rel, spec in PLAN:
    migrate(os.path.join(REPO, rel), spec)
