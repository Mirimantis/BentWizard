"""Tests for the New Timber core (freecad.bentwizard.timber).

FreeCAD-dependent — run with the bundled interpreter; skips under plain
Python.
"""

import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
import _repo_path  # noqa: E402 — this repo's code must win the import

try:
    import FreeCAD as App
    _repo_path.graft()
    HAVE_FREECAD = True
except ImportError:
    HAVE_FREECAD = False

IN3 = 25.4 ** 3


@unittest.skipUnless(HAVE_FREECAD, "FreeCAD not importable — run with the bundled python")
class NewTimberTest(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("TimberTest")

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def new(self, *args):
        from freecad.bentwizard.timber import new_timber
        return new_timber(self.doc, *args)

    def assertRejected(self, *args):
        from freecad.bentwizard.timber import TimberError
        with self.assertRaises(TimberError):
            self.new(*args)

    def test_creates_verified_stick(self):
        body, dims = self.new("T-Post-001", "10 in", "8 in", "16 ft")
        self.assertEqual(body.Label, "T-Post-001")
        self.assertEqual(dims.Label, "TDim_T-Post-001")
        self.assertAlmostEqual(body.Shape.Volume / IN3, 10 * 8 * 192, places=6)
        for prop in ("WidthX", "WidthY", "LengthZ", "PositionTag"):
            self.assertTrue(dims.getDocumentationOfProperty(prop).strip(),
                            f"{prop} missing tooltip")

    def test_section_is_centred_on_the_axis(self):
        body, _dims = self.new("T-Post-001", "6 in", "10 in", "8 ft")
        bb = body.Shape.BoundBox
        self.assertAlmostEqual(bb.XMin / 25.4, -3, places=9)
        self.assertAlmostEqual(bb.XMax / 25.4, 3, places=9)
        self.assertAlmostEqual(bb.YMin / 25.4, -5, places=9)
        self.assertAlmostEqual(bb.YMax / 25.4, 5, places=9)
        self.assertAlmostEqual(bb.ZMin, 0, places=9)
        self.assertAlmostEqual(bb.ZMax / 25.4, 96, places=9)

    def test_no_symmetric_constraint(self):
        # finding #13: centreline + half-widths, never Symmetric
        body, _dims = self.new("T-Post-001", "6 in", "10 in", "8 ft")
        sketch = next(o for o in body.Group if o.TypeId == "Sketcher::SketchObject")
        self.assertNotIn("Symmetric", [c.Type for c in sketch.Constraints])
        names = {c.Name for c in sketch.Constraints}
        self.assertTrue({"HalfWidthXPos", "HalfWidthXNeg",
                         "HalfWidthYPos", "HalfWidthYNeg"} <= names)

    def test_dims_varset_nested_in_body_and_resolved_structurally(self):
        from freecad.bentwizard.timber import dims_varset, timber_bodies
        body, dims = self.new("T-Post-001", "10 in", "8 in", "16 ft")
        self.assertIn(dims, list(body.Group))
        self.assertIs(dims_varset(body), dims)
        dims.Label = "Whatever"          # a renamed VarSet still resolves
        self.assertIs(dims_varset(body), dims)
        self.assertEqual(timber_bodies(self.doc), [body])

    def test_end_datums_come_with_the_timber(self):
        from freecad.bentwizard import datums
        body, _dims = self.new("T-Post-001", "6 in", "10 in", "8 ft")
        ends = {datums.face_of(d): d for d in datums.datums_of(body)}
        self.assertEqual(sorted(ends), ["EndA", "EndB"])
        self.assertEqual(ends["EndA"].Label, "D_T-Post-001_A")
        self.assertEqual(ends["EndB"].Label, "D_T-Post-001_B")
        self.assertAlmostEqual(ends["EndB"].Placement.Base.z / 25.4, 96, places=9)
        for d in ends.values():
            self.assertEqual(datums.verify_datum(d), [])

    def test_position_tag_is_display_only_data(self):
        _, dims = self.new("T-Post-001", "10 in", "8 in", "16 ft",
                           "Bent 2, north post")
        self.assertEqual(dims.PositionTag, "Bent 2, north post")
        _, bare = self.new("T-Post-002", "10 in", "8 in", "16 ft")
        self.assertEqual(bare.PositionTag, "")

    def test_parametric_follow_through(self):
        from freecad.bentwizard import datums
        body, dims = self.new("T-Post-001", "10 in", "8 in", "16 ft")
        dims.WidthX = "12 in"
        dims.LengthZ = "10 ft"
        self.doc.recompute()
        self.assertAlmostEqual(body.Shape.Volume / IN3, 12 * 8 * 120, places=6)
        self.assertAlmostEqual(body.Shape.BoundBox.XMin / 25.4, -6, places=9)
        b = datums.end_datum(body, "EndB")
        self.assertAlmostEqual(b.Placement.Base.z / 25.4, 120, places=9)

    def test_rejects_bad_input(self):
        self.assertRejected("", "8 in", "8 in", "8 ft")
        self.assertRejected("a>b", "8 in", "8 in", "8 ft")
        self.assertRejected("a;b", "8 in", "8 in", "8 ft")
        self.assertRejected("a\\b", "8 in", "8 in", "8 ft")
        self.assertRejected("T-Post-001", "0 in", "8 in", "8 ft")
        self.new("T-Post-001", "8 in", "8 in", "8 ft")
        self.assertRejected("T-Post-001", "8 in", "8 in", "8 ft")  # duplicate

    def test_custom_and_dotted_labels_bind_expressions(self):
        body, dims = self.new("Ridge Post (custom)", "8 in", "8 in", "8 ft")
        self.assertEqual(dims.Label, "TDim_Ridge Post (custom)")
        dims.WidthX = "10 in"
        self.doc.recompute()
        self.assertAlmostEqual(body.Shape.Volume / IN3, 10 * 8 * 96, places=6)
        body2, dims2 = self.new("T-Post.Balcony.001", "8 in", "8 in", "8 ft")
        dims2.LengthZ = "10 ft"
        self.doc.recompute()
        self.assertAlmostEqual(body2.Shape.Volume / IN3, 8 * 8 * 120, places=6)

    def test_expression_bound_dimension(self):
        group = self.doc.addObject("App::VarSet", "GroupVars")
        group.Label = "ProjectVars"
        group.addProperty("App::PropertyLength", "PostHeight", "Layout", "post")
        group.PostHeight = "10 ft"
        body, dims = self.new("T.Post.Balcony.001", "8 in", "8 in",
                              "=<<ProjectVars>>.PostHeight")
        self.assertAlmostEqual(body.Shape.Volume / IN3, 8 * 8 * 120, places=6)
        group.PostHeight = "12 ft"
        self.doc.recompute()
        self.assertAlmostEqual(body.Shape.Volume / IN3, 8 * 8 * 144, places=6)

    def test_bad_expression_rejected_without_debris(self):
        before = len(self.doc.Objects)
        self.assertRejected("T-Post-001", "8 in", "8 in", "=<<Nowhere>>.Nothing")
        self.assertRejected("T-Post-001", "8 in", "8 in", "=")
        group = self.doc.addObject("App::VarSet", "G")
        group.Label = "Group_Zero"
        group.addProperty("App::PropertyLength", "Zip", "d", "zero")
        self.assertRejected("T-Post-001", "8 in", "8 in", "=<<Group_Zero>>.Zip")
        self.assertEqual(len(self.doc.Objects), before + 1)  # just Group_Zero

    def test_output_lints_clean(self):
        from freecad.bentwizard.linter import lint
        self.new("T-Post-Level1-003", "10 in", "8 in", "16 ft")
        self.new("T-TieBeam_decorative-007", "6 in", "8 in", "12 ft")
        with tempfile.TemporaryDirectory() as td:
            path = str(Path(td) / "out.FCStd")
            self.doc.saveAs(path)
            self.assertEqual([str(f) for f in lint(path)], [])


if __name__ == "__main__":
    unittest.main()
