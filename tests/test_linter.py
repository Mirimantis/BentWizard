"""The linter's rules, pinned against documents built for the purpose.

A clean rev-2 document (timbers, datums, a pairing, a component and its
Boolean) lints silent — strict AND advisory — and then one deliberate
violation per rule is introduced and must be the finding that fires.
FreeCAD builds the documents; the linter reads the saved files with no
FreeCAD at all.
"""

import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
import _repo_path  # noqa: E402

try:
    import FreeCAD as App
    import Part
    import Sketcher
    _repo_path.graft()
    HAVE_FREECAD = True
except ImportError:
    HAVE_FREECAD = False

IN = 25.4


@unittest.skipUnless(HAVE_FREECAD, "FreeCAD not importable — run with the bundled python")
class LinterRules(unittest.TestCase):
    def setUp(self):
        from freecad.bentwizard import datums
        from freecad.bentwizard.timber import new_timber
        self.doc = App.newDocument("LintTest")
        self.post, self.pdims = new_timber(self.doc, "T-Post-001", "6 in", "10 in", "8 ft")
        self.girt, self.gdims = new_timber(self.doc, "T-Girt-001", "4 in", "8 in", "6 ft")
        self.host = datums.add_datum(self.post, "YPos", "48 in")
        self.mate = datums.end_datum(self.girt, "EndB")
        self.vs = self.doc.addObject("App::VarSet", "JointVS")
        self.vs.Label = "J-Test-001"
        self.vs.addProperty("App::PropertyLength", "HousingDepth", "Joint", "housing depth")
        self.vs.HousingDepth = 0.5 * IN
        datums.pair(self.host, self.mate, self.vs)
        self.cutter = self.component("Housing.Test.001", "Cutter", 1)
        self.boolean = self.post.newObject("PartDesign::Boolean", "Cut")
        self.boolean.Label = "Cut.Housing.Test.001"
        self.boolean.Group = [self.cutter]
        self.boolean.Type = "Cut"
        self.doc.recompute()

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def component(self, label, role, order):
        """A cutter body: housing block sized from the joint VarSet's
        mate accessors, grown in -Z, placed on the host datum."""
        body = self.doc.addObject("PartDesign::Body", "Comp")
        body.Label = label
        body.addProperty("App::PropertyString", "ComponentRole", "Component", "role")
        body.ComponentRole = role
        body.addProperty("App::PropertyInteger", "ComponentOrder", "Component", "order")
        body.ComponentOrder = order
        sk = body.newObject("Sketcher::SketchObject", "HousingSkt")
        sk.AttachmentSupport = (body.Origin.OriginFeatures[3], [""])
        sk.MapMode = "FlatFace"
        w, h = 4 * IN, 8 * IN
        V = App.Vector
        pts = [V(-w / 2, -h / 2, 0), V(w / 2, -h / 2, 0), V(w / 2, h / 2, 0), V(-w / 2, h / 2, 0)]
        for i in range(4):
            sk.addGeometry(Part.LineSegment(pts[i], pts[(i + 1) % 4]), False)
        for i in range(4):
            sk.addConstraint(Sketcher.Constraint("Coincident", i, 2, (i + 1) % 4, 1))
        sk.addConstraint(Sketcher.Constraint("Horizontal", 0))
        sk.addConstraint(Sketcher.Constraint("Horizontal", 2))
        sk.addConstraint(Sketcher.Constraint("Vertical", 1))
        sk.addConstraint(Sketcher.Constraint("Vertical", 3))
        J = f"<<{self.vs.Label}>>"
        c = sk.addConstraint(Sketcher.Constraint("DistanceX", -1, 1, 1, 1, w / 2))
        sk.setExpression(f"Constraints[{c}]", J + ".MateWidthU / 2")
        c = sk.addConstraint(Sketcher.Constraint("DistanceX", 3, 1, -1, 1, w / 2))
        sk.setExpression(f"Constraints[{c}]", J + ".MateWidthU / 2")
        c = sk.addConstraint(Sketcher.Constraint("DistanceY", -1, 1, 2, 1, h / 2))
        sk.setExpression(f"Constraints[{c}]", J + ".MateWidthV / 2")
        c = sk.addConstraint(Sketcher.Constraint("DistanceY", 0, 1, -1, 1, h / 2))
        sk.setExpression(f"Constraints[{c}]", J + ".MateWidthV / 2")
        pad = body.newObject("PartDesign::Pad", "HousingPad")
        pad.Profile = sk
        pad.setExpression("Length", J + ".HousingDepth")
        pad.Reversed = True
        from freecad.bentwizard import datums
        body.setExpression("Placement", datums.placement_binding(self.vs, self.host))
        self.doc.recompute()
        return body

    def findings(self):
        from freecad.bentwizard.linter import lint
        self.doc.recompute()
        with tempfile.TemporaryDirectory() as td:
            path = str(Path(td) / "lint.FCStd")
            self.doc.saveAs(path)
            return lint(path)

    def rules(self, severity=None):
        return sorted({f.rule for f in self.findings()
                       if severity is None or f.severity == severity})

    # --- the control ------------------------------------------------------

    def test_clean_document_is_silent(self):
        self.assertEqual([str(f) for f in self.findings()], [])

    # --- strict rules -----------------------------------------------------

    def test_datum_not_attached(self):
        self.host.AttachmentSupport = [(self.post.Origin.OriginFeatures[4], "")]
        self.host.MapMode = "FlatFace"
        self.assertIn("datum-not-attached", self.rules("strict"))

    def test_datum_declaration_rotation_from_the_wrong_row(self):
        from freecad.bentwizard import facetable
        row = facetable.FACE_TABLE["YNeg"]
        self.host.Placement = App.Placement(
            self.host.Placement.Base, App.Rotation(App.Vector(*row.axis), row.angle))
        self.assertIn("datum-declaration", self.rules("strict"))

    def test_datum_declaration_station_unbound(self):
        self.host.setExpression(".Placement.Base.z", None)
        self.assertIn("datum-declaration", self.rules("strict"))

    def test_datum_declaration_accessor_rebound(self):
        self.host.setExpression("WidthU", f"<<{self.pdims.Label}>>.WidthY")
        self.assertIn("datum-declaration", self.rules("strict"))

    def test_datum_link_scope(self):
        self.host.addProperty("App::PropertyLink", "MateLink", "Datum", "no")
        self.assertIn("datum-link-scope", self.rules("strict"))

    def test_datum_pairing_mate_missing(self):
        self.mate.MateDatum = "Nowhere"
        self.assertIn("datum-pairing", self.rules("strict"))

    def test_datum_pairing_does_not_point_back(self):
        self.mate.MateDatum = ""
        self.assertIn("datum-pairing", self.rules("strict"))

    def test_datum_pairing_varset_reads_another_datum(self):
        from freecad.bentwizard import datums
        other = datums.add_datum(self.post, "XPos", "30 in")
        self.vs.setExpression("HostWidthU", f"<<{other.Label}>>.WidthU")
        self.assertIn("datum-pairing", self.rules("strict"))

    def test_component_declaration(self):
        self.cutter.ComponentRole = "Slicer"
        self.assertIn("component-declaration", self.rules("strict"))

    def test_component_placement_unbound(self):
        self.cutter.setExpression("Placement", None)
        self.assertIn("component-declaration", self.rules("strict"))

    def test_component_placement_direct(self):
        """A Body reading the datum's Placement directly is the defect
        behind 'Link(s) ... go out of the allowed scope' (Adam's second
        GUI round): strict on the body, advisory on a mirroring."""
        self.cutter.setExpression("Placement", f"<<{self.host.Label}>>.Placement")
        self.assertIn("component-placement-direct", self.rules("strict"))
        self.assertNotIn("component-declaration", self.rules("strict"))
        # through a mirroring: the same read is merely non-uniform
        self.cutter.setExpression("Placement", None)
        self.cutter.Placement = App.Placement()
        m = self.doc.addObject("Part::Mirroring", "Mirror")
        m.Label = "Mirror.Housing.Test.001"
        m.Source = self.cutter
        m.Normal = App.Vector(1, 0, 0)
        m.setExpression("Placement", f"<<{self.host.Label}>>.Placement")
        self.boolean.Group = [m]
        self.assertIn("component-placement-direct", self.rules("advisory"))
        self.assertNotIn("component-placement-direct", self.rules("strict"))

    def test_component_reference_scope_dims(self):
        pad = next(o for o in self.cutter.Group if o.TypeId == "PartDesign::Pad")
        pad.setExpression("Length", f"<<{self.gdims.Label}>>.WidthX / 4")
        self.assertIn("component-reference-scope", self.rules("strict"))

    def test_component_reference_scope_other_datum(self):
        sk = next(o for o in self.cutter.Group if o.TypeId == "Sketcher::SketchObject")
        sk.setExpression("Constraints[8]", f"<<{self.mate.Label}>>.WidthU / 2")
        self.assertIn("component-reference-scope", self.rules("strict"))

    def test_boolean_operand_count(self):
        extra = self.doc.addObject("Part::Box", "Extra")
        self.boolean.Group = [self.cutter, extra]
        self.assertIn("boolean-operand", self.rules("strict"))

    def test_solid_face_reference(self):
        sk = next(o for o in self.cutter.Group if o.TypeId == "Sketcher::SketchObject")
        sk.AttachmentSupport = [(self.post, "Face1")]
        self.assertIn("solid-face-reference", self.rules("strict"))

    def test_label_reserved_characters(self):
        self.vs.Label = "J-Te;st-001"
        self.assertIn("label-reserved-characters", self.rules("strict"))

    # --- advisory rules ---------------------------------------------------

    def test_property_naming(self):
        self.vs.addProperty("App::PropertyLength", "Tenon_Length", "Joint", "t")
        self.assertIn("property-naming", self.rules("advisory"))

    def test_missing_tooltip(self):
        self.vs.addProperty("App::PropertyLength", "TenonLength", "Joint", "")
        self.assertIn("missing-tooltip", self.rules("advisory"))

    def test_naming_conventions(self):
        self.cutter.Label = "Housing"
        self.host.Label = "Frame_Post"
        self.assertIn("naming-convention", self.rules("advisory"))

    def test_component_order(self):
        # an adder on the SAME timber ordered before the cutter
        adder = self.component("Tongue.Test.001", "Adder", 0)
        fuse = self.post.newObject("PartDesign::Boolean", "Fuse")
        fuse.Group = [adder]
        fuse.Type = "Fuse"
        self.doc.recompute()
        self.assertIn("component-order", self.rules("advisory"))

    def test_auto_generated_label(self):
        self.cutter.Label = "Body001"
        self.assertIn("auto-generated-label", self.rules("advisory"))


if __name__ == "__main__":
    unittest.main()
