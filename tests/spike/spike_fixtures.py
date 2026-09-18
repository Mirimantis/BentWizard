"""Fixture builders for the variant-link spike (see docs/spike-headless-brief.md).

Everything here is constructed from scratch so the harness never depends on a
hand-authored ``.FCStd``.  Nothing in this package is imported by production
code -- the spike is an evaluation only.
"""

import FreeCAD as App
import Part
import Sketcher
from FreeCAD import Vector

IN = 25.4  # mm per inch

#: The cutter's eight ``Joint``-group parameters, in inches.
CUTTER_PARAMS = [
    ("MortiseThickness", 2.0,  "Mortise thickness, from face 2"),
    ("MortiseWidth",     6.0,  "Mortise width, along face 1"),
    ("MortiseDepth",     4.25, "Mortise depth, into the landing face"),
    ("HousingDepth",     0.5,  "Housing depth, into the landing face"),
    ("HousingWidth",     8.0,  "Housing width, along face 2"),
    ("HousingHeight",    8.0,  "Housing height, along face 1"),
    ("SetbackFace1",     2.0,  "Mortise setback from face 1"),
    ("SetbackFace2",     1.0,  "Mortise setback from face 2"),
]

TIMBER_W = 8.0
TIMBER_H = 8.0
TIMBER_L = 96.0


def _origin_plane(body, name):
    for feat in body.Origin.OriginFeatures:
        if feat.Name.startswith(name) or getattr(feat, "Role", "") == name:
            return feat
    for feat in body.Origin.OriginFeatures:
        if feat.TypeId == "App::Plane" and name in feat.Name:
            return feat
    raise KeyError(name)


def _rect_sketch(body, name, plane, coords, exprs=None):
    """Axis-aligned, fully constrained rectangle on ``plane``.

    ``coords`` is ``(x0, y0, dx, dy)`` in mm; ``exprs`` maps the four named
    driving constraints (``X0``/``Y0``/``DX``/``DY``) to expression strings.
    """
    x0, y0, dx, dy = coords
    sk = body.newObject("Sketcher::SketchObject", name)
    sk.AttachmentSupport = [(plane, "")]
    sk.MapMode = "FlatFace"

    pts = [(x0, y0), (x0 + dx, y0), (x0 + dx, y0 + dy), (x0, y0 + dy)]
    for i in range(4):
        a, b = pts[i], pts[(i + 1) % 4]
        sk.addGeometry(Part.LineSegment(Vector(a[0], a[1], 0),
                                        Vector(b[0], b[1], 0)), False)
    for i in range(4):
        sk.addConstraint(Sketcher.Constraint(
            "Coincident", i, 2, (i + 1) % 4, 1))
    sk.addConstraint(Sketcher.Constraint("Horizontal", 0))
    sk.addConstraint(Sketcher.Constraint("Horizontal", 2))
    sk.addConstraint(Sketcher.Constraint("Vertical", 1))
    sk.addConstraint(Sketcher.Constraint("Vertical", 3))
    idx = {}
    idx["X0"] = sk.addConstraint(
        Sketcher.Constraint("DistanceX", -1, 1, 0, 1, x0))
    idx["Y0"] = sk.addConstraint(
        Sketcher.Constraint("DistanceY", -1, 1, 0, 1, y0))
    idx["DX"] = sk.addConstraint(
        Sketcher.Constraint("DistanceX", 0, 1, 0, 2, dx))
    idx["DY"] = sk.addConstraint(
        Sketcher.Constraint("DistanceY", 1, 1, 1, 2, dy))
    for key, i in idx.items():
        sk.renameConstraint(i, key)
    if exprs:
        for key, expr in exprs.items():
            sk.setExpression("Constraints.%s" % key, expr)
    return sk


def build_cutter(doc=None, label="Cutter_MT_Mortise", href=True,
                 copy_on_change=True, params_owner=None):
    """The removal solid: a housing pad plus a mortise prism pad.

    By default (round 1) the parameters live on the Body itself and drive
    the sketches through ``href()`` -- the dependency-severing form the
    manual session found to be the only one that works for a body's own
    properties, and the only one an ``App::Link`` can expose.

    Pass ``params_owner`` (round 2's A-bis structure) to put the parameters
    on a separate object -- a sibling VarSet -- instead.  The sketches then
    reference it by plain ``<<Label>>.Prop``, with no ``href()`` anywhere.
    """
    doc = doc or App.newDocument("Spike_Cutter")
    body = doc.addObject("PartDesign::Body", "Cutter")
    body.Label = label
    owner = params_owner if params_owner is not None else body
    for name, inches, tip in CUTTER_PARAMS:
        owner.addProperty("App::PropertyLength", name, "Joint", tip)
        setattr(owner, name, inches * IN)
        if copy_on_change and params_owner is None:
            owner.setPropertyStatus(name, "CopyOnChange")

    xy = _origin_plane(body, "XY_Plane")

    def ref(prop):
        token = "<<%s>>.%s" % (owner.Label, prop)
        # a body's own property can only reach its sketches through href();
        # a sibling VarSet needs no such thing
        return "href(%s)" % token if (href and params_owner is None)             else token

    housing_sk = _rect_sketch(
        body, "HousingSkt", xy,
        (0.0, 0.0, TIMBER_W * IN, TIMBER_H * IN),
        {"X0": "0", "Y0": "0",
         "DX": ref("HousingWidth"), "DY": ref("HousingHeight")})
    housing = body.newObject("PartDesign::Pad", "HousingPad")
    housing.Profile = housing_sk
    housing.setExpression("Length", ref("HousingDepth"))

    mortise_sk = _rect_sketch(
        body, "MortiseSkt", xy,
        (1.0 * IN, 2.0 * IN, 2.0 * IN, 6.0 * IN),
        {"X0": ref("SetbackFace2"), "Y0": ref("SetbackFace1"),
         "DX": ref("MortiseThickness"), "DY": ref("MortiseWidth")})
    mortise = body.newObject("PartDesign::Pad", "MortisePad")
    mortise.Profile = mortise_sk
    mortise.setExpression("Length", ref("MortiseDepth"))

    doc.recompute()
    return doc, body


def cutter_volume(params):
    """Analytic volume (mm^3) of the cutter for a dict of inch values."""
    p = dict(params)
    hw, hh, hd = p["HousingWidth"], p["HousingHeight"], p["HousingDepth"]
    mt, mw, md = p["MortiseThickness"], p["MortiseWidth"], p["MortiseDepth"]
    # Both pads start at z = 0; the mortise prism is interior to the housing
    # footprint, so the union double-counts the overlap slab.
    vol = hw * hh * hd + mt * mw * md - mt * mw * min(hd, md)
    return vol * IN ** 3


def default_params():
    return {name: inches for name, inches, _ in CUTTER_PARAMS}


def build_timber(doc=None, label="T-Post-Spike-001",
                 w=TIMBER_W, h=TIMBER_H, length=TIMBER_L):
    """A plain 8x8x96 timber Body with its Dims VarSet, corner on origin."""
    doc = doc or App.newDocument("Spike_Target")
    dims = doc.addObject("App::VarSet", "TDim")
    dims.Label = "TDim_%s" % label
    for name, inches, tip in (("Width", w, "Timber width"),
                              ("Depth", h, "Timber depth"),
                              ("Length", length, "Full finished stick")):
        dims.addProperty("App::PropertyLength", name, "Dims", tip)
        setattr(dims, name, inches * IN)

    body = doc.addObject("PartDesign::Body", "Timber")
    body.Label = label
    xy = _origin_plane(body, "XY_Plane")
    sk = _rect_sketch(
        body, "Section.Skt.%s" % label, xy, (0.0, 0.0, w * IN, h * IN),
        {"X0": "0", "Y0": "0",
         "DX": "<<%s>>.Width" % dims.Label,
         "DY": "<<%s>>.Depth" % dims.Label})
    pad = body.newObject("PartDesign::Pad", "Stick.%s" % label)
    pad.Profile = sk
    pad.setExpression("Length", "<<%s>>.Length" % dims.Label)
    doc.recompute()
    return doc, body, dims, sk


def timber_volume(w=TIMBER_W, h=TIMBER_H, length=TIMBER_L):
    return w * h * length * IN ** 3


def build_abis_template(doc=None, part_label="Joint_MT",
                        varset_label="JointParams",
                        body_label="Cutter"):
    """Round 2's A-bis template: an ``App::Part`` holding a parameter VarSet
    and the cutter Body as *siblings*.

    Round 1 had to set this shape aside because an ``App::Link`` exposes
    only the linked object's own properties and so cannot reach a child
    VarSet.  A deep copy has no such restriction, which is the whole point
    of round 2: the sketches reference ``<<JointParams>>.X`` directly, with
    no ``href()`` anywhere.
    """
    doc = doc or App.newDocument("Spike_R2_Template")
    part = doc.addObject("App::Part", "JointTemplate")
    part.Label = part_label
    params = doc.addObject("App::VarSet", "JointParams")
    params.Label = varset_label
    part.addObject(params)
    _, body = build_cutter(doc, label=body_label, params_owner=params)
    part.addObject(body)
    doc.recompute()
    return doc, part, params, body


def expressions(obj):
    """``{path: expression}`` for one object, or ``{}``."""
    try:
        return dict(obj.ExpressionEngine or [])
    except (AttributeError, TypeError):
        return {}


def all_expressions(objs):
    """``[(object_name, path, expression), ...]`` over a set of objects."""
    out = []
    for obj in objs:
        for path, expr in sorted(expressions(obj).items()):
            out.append((obj.Name, path, expr))
    return out


def build_nocontainer_template(doc=None, varset_label="JointParams",
                               body_label="Cutter"):
    """Round 2b's template: a ``JointParams`` VarSet and the cutter Body as
    plain document-root objects, with no ``App::Part`` container.

    The container was only ever round 1's requirement -- an ``App::Link``
    exposes only the linked object's own properties, so the VarSet had to
    be a sibling inside a Part.  ``copyObject`` follows dependency edges,
    so it needs nothing of the kind, and ``PartDesign::Boolean`` gets the
    Body it actually expects.  This is the Phase 0 pattern.
    """
    doc = doc or App.newDocument("Spike_R2b_Template")
    params = doc.addObject("App::VarSet", "JointParams")
    params.Label = varset_label
    _, body = build_cutter(doc, label=body_label, params_owner=params)
    doc.recompute()
    return doc, params, body


# --------------------------------------------------------------------------
# round 3: cutter + adder joint halves
# --------------------------------------------------------------------------

def _tri_sketch(body, name, plane, coords, exprs=None):
    """Right triangle with vertices ``(x0,y0)``, ``(x0+dx,y0)``,
    ``(x0+dx,y0+dy)``, fully constrained, with the same four named driving
    constraints as :func:`_rect_sketch`.

    Used for an angled shoulder cut: the angle rides on ``DY`` being an
    expression over ``DX``, so the template carries the angle rather than
    the apply step supplying a rotation.
    """
    x0, y0, dx, dy = coords
    sk = body.newObject("Sketcher::SketchObject", name)
    sk.AttachmentSupport = [(plane, "")]
    sk.MapMode = "FlatFace"

    pts = [(x0, y0), (x0 + dx, y0), (x0 + dx, y0 + dy)]
    for i in range(3):
        a, b = pts[i], pts[(i + 1) % 3]
        sk.addGeometry(Part.LineSegment(Vector(a[0], a[1], 0),
                                        Vector(b[0], b[1], 0)), False)
    for i in range(3):
        sk.addConstraint(Sketcher.Constraint(
            "Coincident", i, 2, (i + 1) % 3, 1))
    sk.addConstraint(Sketcher.Constraint("Horizontal", 0))
    sk.addConstraint(Sketcher.Constraint("Vertical", 1))
    idx = {"X0": sk.addConstraint(
               Sketcher.Constraint("DistanceX", -1, 1, 0, 1, x0)),
           "Y0": sk.addConstraint(
               Sketcher.Constraint("DistanceY", -1, 1, 0, 1, y0)),
           "DX": sk.addConstraint(
               Sketcher.Constraint("DistanceX", 0, 1, 0, 2, dx)),
           "DY": sk.addConstraint(
               Sketcher.Constraint("DistanceY", 1, 1, 1, 2, dy))}
    for key, i in idx.items():
        sk.renameConstraint(i, key)
    if exprs:
        for key, expr in exprs.items():
            sk.setExpression("Constraints.%s" % key, expr)
    return sk


#: The tenon adder's parameters, in inches.
TENON_PARAMS = [
    ("TenonThickness", 2.0, "Tenon thickness, from face 2"),
    ("TenonWidth",     6.0, "Tenon width, along face 1"),
    ("TenonLength",    4.0, "Tenon length, proud of the shoulder"),
    ("SetbackFace1",   1.0, "Tenon setback from face 1"),
    ("SetbackFace2",   3.0, "Tenon setback from face 2"),
]


def default_tenon_params():
    return dict((name, inches) for name, inches, _ in TENON_PARAMS)


def build_tenon_adder(doc=None, varset_label="TenonParams",
                      body_label="Tenon", embed_mm=0.0):
    """The additive half: a tenon prism to be fused onto a stick end.

    Modelled in its own frame with the shoulder plane at local ``z = 0``,
    so applying it means placing the Body at the timber's end face, minus
    ``Embed``. The pad runs ``TenonLength + Embed``, so the length proud
    of the shoulder is ``TenonLength`` whatever ``Embed`` is.

    ``Embed`` is signed and is the knob risk 1 turns: 0 puts the shoulder
    exactly coplanar with the end face, positive buries the adder in the
    stick, negative leaves a gap.
    """
    doc = doc or App.newDocument("Spike_R3_Tenon")
    params = doc.addObject("App::VarSet", "TenonParams")
    params.Label = varset_label
    for name, inches, tip in TENON_PARAMS:
        params.addProperty("App::PropertyLength", name, "Joint", tip)
        setattr(params, name, inches * IN)
    params.addProperty("App::PropertyDistance", "Embed", "Joint",
                       "How far the adder reaches into the stick past the "
                       "shoulder plane; 0 is exactly coplanar")
    params.Embed = embed_mm

    body = doc.addObject("PartDesign::Body", "Tenon")
    body.Label = body_label
    xy = _origin_plane(body, "XY_Plane")

    def ref(prop):
        return "<<%s>>.%s" % (varset_label, prop)

    sk = _rect_sketch(
        body, "TenonSkt", xy,
        (3.0 * IN, 1.0 * IN, 2.0 * IN, 6.0 * IN),
        {"X0": ref("SetbackFace2"), "Y0": ref("SetbackFace1"),
         "DX": ref("TenonThickness"), "DY": ref("TenonWidth")})
    pad = body.newObject("PartDesign::Pad", "TenonPad")
    pad.Profile = sk
    pad.setExpression("Length", "%s + %s" % (ref("TenonLength"),
                                             ref("Embed")))
    doc.recompute()
    return doc, params, body


def tenon_proud_volume(params):
    """Volume the adder contributes outside the stick (mm^3)."""
    p = dict(params)
    return p["TenonThickness"] * p["TenonWidth"] * p["TenonLength"] * IN ** 3


def build_shoulder_cutter(doc, params, body_label="Shoulder"):
    """The angled-shoulder cutter: a wedge whose rise is
    ``ShoulderRun * tan(ShoulderAngle)``, so the angle is a template
    parameter driving geometry rather than a placement supplied at apply
    time. Sketched on XZ and padded through the stick's depth.
    """
    body = doc.addObject("PartDesign::Body", "Shoulder")
    body.Label = body_label
    xz = _origin_plane(body, "XZ_Plane")

    def ref(prop):
        return "<<%s>>.%s" % (params.Label, prop)

    # On XZ the sketch's local y is the stick's z.  The wedge is the
    # triangle between the sawn line and the end face: local (0,0),
    # (Run,0), (Run,-Run*tan(angle)), placed with its apex on the end
    # face, so the long point stays at the design length and the short
    # point falls back by Run*tan(angle).
    #
    # ``ShoulderRun`` is deliberately oversized past the section: the
    # excess cuts air, and it keeps the cutter's side faces off the
    # stick's, which is the same discipline the island-pocket rule
    # applies to sketches.
    sk = _tri_sketch(
        body, "ShoulderSkt", xz,
        (0.0, 0.0, (TIMBER_W + 2.0) * IN,
         -(TIMBER_W + 2.0) * IN * 0.5773502691896257),
        {"X0": "0", "Y0": "0",
         "DX": ref("ShoulderRun"),
         "DY": "-%s * tan(%s)" % (ref("ShoulderRun"),
                                  ref("ShoulderAngle"))})
    pad = body.newObject("PartDesign::Pad", "ShoulderPad")
    pad.Profile = sk
    pad.setExpression("Length", ref("ShoulderDepth"))
    pad.SideType = 2                    # symmetric; see the API gotcha
    doc.recompute()
    return body


def build_brace_half(doc=None, varset_label="BraceParams"):
    """One joint half carrying **both** a cutter and an adder, driven by a
    single VarSet: the angled shoulder cut plus the tenon it leaves.
    """
    doc = doc or App.newDocument("Spike_R3_Brace")
    params = doc.addObject("App::VarSet", "BraceParams")
    params.Label = varset_label
    for name, kind, value, tip in (
            ("ShoulderRun", "App::PropertyLength", (TIMBER_W + 2.0) * IN,
             "Shoulder cut run across face 2, oversized past the section"),
            ("ShoulderAngle", "App::PropertyAngle", 30.0,
             "Shoulder angle off square, from the end face"),
            ("ShoulderDepth", "App::PropertyLength", (TIMBER_H + 2.0) * IN,
             "Depth of the shoulder cut through face 1, oversized"),
            ("TenonThickness", "App::PropertyLength", 2.0 * IN,
             "Tenon thickness, from face 2"),
            ("TenonWidth", "App::PropertyLength", 6.0 * IN,
             "Tenon width, along face 1"),
            ("TenonLength", "App::PropertyLength", 4.0 * IN,
             "Tenon length, proud of the shoulder"),
            ("SetbackFace1", "App::PropertyLength", 1.0 * IN,
             "Tenon setback from face 1"),
            ("SetbackFace2", "App::PropertyLength", 3.0 * IN,
             "Tenon setback from face 2")):
        params.addProperty(kind, name, "Joint", tip)
        setattr(params, name, value)

    cutter = build_shoulder_cutter(doc, params)

    adder = doc.addObject("PartDesign::Body", "BraceTenon")
    adder.Label = "BraceTenon"
    xy = _origin_plane(adder, "XY_Plane")

    def ref(prop):
        return "<<%s>>.%s" % (varset_label, prop)

    sk = _rect_sketch(
        adder, "BraceTenonSkt", xy,
        (3.0 * IN, 1.0 * IN, 2.0 * IN, 6.0 * IN),
        {"X0": ref("SetbackFace2"), "Y0": ref("SetbackFace1"),
         "DX": ref("TenonThickness"), "DY": ref("TenonWidth")})
    pad = adder.newObject("PartDesign::Pad", "BraceTenonPad")
    pad.Profile = sk
    pad.setExpression("Length", ref("TenonLength"))
    doc.recompute()
    return doc, params, cutter, adder


def build_subtractive_tenon_timber(doc=None, label="T-Sub-001",
                                   params=None):
    """The **current** model's tenon: an over-length stick with an island
    pocket cutting the waste away from around the tenon.

    The outer removal loop is deliberately oversized past the section, per
    the house rule -- a loop coincident with the section boundary is the
    known-bad form of finding #14 and would not be a fair comparison.
    """
    doc = doc or App.newDocument("Spike_R3_Subtractive")
    dims = doc.addObject("App::VarSet", "TDim")
    dims.Label = "TDim_%s" % label
    for name, inches, tip in (("Width", TIMBER_W, "Timber width"),
                              ("Depth", TIMBER_H, "Timber depth"),
                              ("Length", TIMBER_L, "Full finished stick")):
        dims.addProperty("App::PropertyLength", name, "Dims", tip)
        setattr(dims, name, inches * IN)

    if params is None:
        params = doc.addObject("App::VarSet", "TenonParams")
        params.Label = "TenonParams"
        for name, inches, tip in TENON_PARAMS:
            params.addProperty("App::PropertyLength", name, "Joint", tip)
            setattr(params, name, inches * IN)

    body = doc.addObject("PartDesign::Body", "Timber")
    body.Label = label
    xy = _origin_plane(body, "XY_Plane")
    section = _rect_sketch(
        body, "Section.Skt.%s" % label, xy,
        (0.0, 0.0, TIMBER_W * IN, TIMBER_H * IN),
        {"X0": "0", "Y0": "0",
         "DX": "<<%s>>.Width" % dims.Label,
         "DY": "<<%s>>.Depth" % dims.Label})
    pad = body.newObject("PartDesign::Pad", "Stick.%s" % label)
    pad.Profile = section
    # the stick is ordered long: design length plus the tenon
    pad.setExpression("Length", "<<%s>>.Length + <<%s>>.TenonLength"
                      % (dims.Label, params.Label))
    doc.recompute()

    waste = _island_sketch(body, "Waste.Skt", xy, params, dims)
    pocket = body.newObject("PartDesign::Pocket", "Waste")
    pocket.Profile = waste
    pocket.setExpression("Length", "<<%s>>.TenonLength" % params.Label)
    pocket.Reversed = True
    doc.recompute()
    return doc, body, dims, params, section


def _island_sketch(body, name, plane, params, dims, oversize_in=1.0):
    """Outer loop oversized past the section, inner loop the tenon: the
    house-style island pocket."""
    sk = body.newObject("Sketcher::SketchObject", name)
    sk.AttachmentSupport = [(plane, "")]
    sk.MapMode = "FlatFace"

    over = oversize_in * IN

    def rect(x0, y0, dx, dy):
        base = len(sk.Geometry)
        pts = [(x0, y0), (x0 + dx, y0), (x0 + dx, y0 + dy), (x0, y0 + dy)]
        for i in range(4):
            a, b = pts[i], pts[(i + 1) % 4]
            sk.addGeometry(Part.LineSegment(Vector(a[0], a[1], 0),
                                            Vector(b[0], b[1], 0)), False)
        for i in range(4):
            sk.addConstraint(Sketcher.Constraint(
                "Coincident", base + i, 2, base + (i + 1) % 4, 1))
        sk.addConstraint(Sketcher.Constraint("Horizontal", base + 0))
        sk.addConstraint(Sketcher.Constraint("Horizontal", base + 2))
        sk.addConstraint(Sketcher.Constraint("Vertical", base + 1))
        sk.addConstraint(Sketcher.Constraint("Vertical", base + 3))
        return base

    outer = rect(-over, -over,
                 TIMBER_W * IN + 2 * over, TIMBER_H * IN + 2 * over)
    inner = rect(3.0 * IN, 1.0 * IN, 2.0 * IN, 6.0 * IN)

    names = {}
    names["OuterX0"] = sk.addConstraint(Sketcher.Constraint(
        "DistanceX", -1, 1, outer, 1, -over))
    names["OuterY0"] = sk.addConstraint(Sketcher.Constraint(
        "DistanceY", -1, 1, outer, 1, -over))
    names["OuterDX"] = sk.addConstraint(Sketcher.Constraint(
        "DistanceX", outer, 1, outer, 2, TIMBER_W * IN + 2 * over))
    names["OuterDY"] = sk.addConstraint(Sketcher.Constraint(
        "DistanceY", outer + 1, 1, outer + 1, 2, TIMBER_H * IN + 2 * over))
    names["InnerX0"] = sk.addConstraint(Sketcher.Constraint(
        "DistanceX", -1, 1, inner, 1, 3.0 * IN))
    names["InnerY0"] = sk.addConstraint(Sketcher.Constraint(
        "DistanceY", -1, 1, inner, 1, 1.0 * IN))
    names["InnerDX"] = sk.addConstraint(Sketcher.Constraint(
        "DistanceX", inner, 1, inner, 2, 2.0 * IN))
    names["InnerDY"] = sk.addConstraint(Sketcher.Constraint(
        "DistanceY", inner + 1, 1, inner + 1, 2, 6.0 * IN))
    for key, i in names.items():
        sk.renameConstraint(i, key)

    dim = dims.Label
    par = params.Label
    sk.setExpression("Constraints.OuterX0", "-%fmm" % over)
    sk.setExpression("Constraints.OuterY0", "-%fmm" % over)
    sk.setExpression("Constraints.OuterDX",
                     "<<%s>>.Width + %fmm" % (dim, 2 * over))
    sk.setExpression("Constraints.OuterDY",
                     "<<%s>>.Depth + %fmm" % (dim, 2 * over))
    sk.setExpression("Constraints.InnerX0", "<<%s>>.SetbackFace2" % par)
    sk.setExpression("Constraints.InnerY0", "<<%s>>.SetbackFace1" % par)
    sk.setExpression("Constraints.InnerDX", "<<%s>>.TenonThickness" % par)
    sk.setExpression("Constraints.InnerDY", "<<%s>>.TenonWidth" % par)
    return sk


def local_shape(body):
    """``body``'s shape expressed in the body's own frame.

    A rotated timber's *global* bounding box is meaningless for a cut
    list, so every derived-length measurement resolves the frame first.
    """
    shape = body.Shape.copy()
    shape.Placement = body.Placement.inverse().multiply(shape.Placement)
    return shape


def derived_length(body):
    """Stick length read off the solid, in mm, in the body's own frame."""
    return local_shape(body).BoundBox.ZLength


def angled_end_points(body, tol=1e-6):
    """``(short_point_mm, long_point_mm)`` of a non-square end.

    Found from the one face whose normal is not axis-aligned -- the sawn
    face -- measured in the body's own frame.
    """
    shape = local_shape(body)
    for face in shape.Faces:
        normal = face.normalAt(0, 0)
        axis_aligned = min(abs(abs(normal.x) - 1.0),
                           abs(abs(normal.y) - 1.0),
                           abs(abs(normal.z) - 1.0))
        if axis_aligned > tol:
            box = face.BoundBox
            return box.ZMin, box.ZMax
    return None, None


def topology(shape):
    """The assertions a fusion must satisfy, as a dict."""
    return {"volume": shape.Volume,
            "solids": len(shape.Solids),
            "valid": bool(shape.isValid()),
            "closed": bool(shape.isClosed()),
            "faces": len(shape.Faces),
            "edges": len(shape.Edges),
            "vertexes": len(shape.Vertexes)}


def build_end_cutter(doc, params, body_label="EndCut"):
    """A half-space box used to saw an end off at an angle, for the
    derived-length tests. Its rotation is supplied at apply time."""
    body = doc.addObject("PartDesign::Body", "EndCutter")
    body.Label = body_label
    xy = _origin_plane(body, "XY_Plane")
    sk = _rect_sketch(body, "EndCutSkt", xy,
                      (-500.0, -500.0, 1000.0, 1000.0),
                      {"X0": "-500", "Y0": "-500",
                       "DX": "1000", "DY": "1000"})
    pad = body.newObject("PartDesign::Pad", "EndCutPad")
    pad.Profile = sk
    pad.Length = 500.0
    doc.recompute()
    return body
