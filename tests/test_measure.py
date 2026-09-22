"""Order length, end projection and the solid-count post-condition, read
off the finished solid in the timber's own frame."""

import math
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
import _repo_path  # noqa: E402

try:
    import FreeCAD as App
    _repo_path.graft()
    HAVE_FREECAD = True
except ImportError:
    HAVE_FREECAD = False

IN = 25.4


@unittest.skipUnless(HAVE_FREECAD, "FreeCAD not importable — run with the bundled python")
class MeasureTest(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("MeasureTest")
        from freecad.bentwizard.timber import new_timber
        self.body, self.dims = new_timber(self.doc, "T-Beam-001", "6 in", "8 in", "8 ft")
        # deliberately off the origin and rotated: a global box would lie
        self.body.Placement = App.Placement(App.Vector(1000, 500, 250),
                                            App.Rotation(App.Vector(0, 1, 0), 37))
        self.doc.recompute()

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def box(self, label, x, y, z, dx, dy, dz, rotation=None):
        """A Part::Box in the BODY's local frame, as a Boolean operand."""
        b = self.doc.addObject("Part::Box", label)
        b.Length, b.Width, b.Height = dx, dy, dz
        b.Placement = App.Placement(App.Vector(x, y, z), rotation or App.Rotation())
        return b

    def boolean(self, op, operand):
        from freecad.bentwizard import component
        bo = self.body.newObject("PartDesign::Boolean", op)
        bo.Group = [operand]
        bo.Type = op
        # the operand is in the BODY's local frame (see `box`), which is
        # the workbench's contract — so pin it the way every Boolean the
        # workbench creates is pinned, or 26.3 resolves it globally and
        # the adders land outside the moved stick
        component.set_legacy_placement(bo)
        self.doc.recompute()
        return bo

    def test_plain_stick(self):
        from freecad.bentwizard import measure
        self.assertAlmostEqual(measure.order_length(self.body) / IN, 96, places=9)
        self.assertEqual(measure.end_projection(self.body), (0.0, 0.0))
        self.assertAlmostEqual(measure.design_length(self.body) / IN, 96, places=9)
        self.assertTrue(measure.is_whole(self.body))
        self.assertLess(self.body.Shape.BoundBox.ZLength / IN, 96)   # the global box lies

    def test_tenon_past_end_b_and_a(self):
        from freecad.bentwizard import measure
        self.boolean("Fuse", self.box("TenonB", -1 * IN, -3 * IN, 95 * IN, 2 * IN, 6 * IN, 5 * IN))
        self.assertAlmostEqual(measure.order_length(self.body) / IN, 100, places=9)
        past_a, past_b = measure.end_projection(self.body)
        self.assertAlmostEqual(past_a / IN, 0, places=9)
        self.assertAlmostEqual(past_b / IN, 4, places=9)
        self.boolean("Fuse", self.box("TenonA", -1 * IN, -3 * IN, -3 * IN, 2 * IN, 6 * IN, 4 * IN))
        self.assertAlmostEqual(measure.order_length(self.body) / IN, 103, places=9)
        self.assertAlmostEqual(measure.end_projection(self.body)[0] / IN, 3, places=9)
        self.assertTrue(measure.is_whole(self.body))
        r = measure.report(self.body)
        self.assertEqual(r["solids"], 1)
        self.assertAlmostEqual(r["order_mm"] / IN, 103, places=9)

    def test_gap_is_caught_only_by_solid_count(self):
        from freecad.bentwizard import measure
        # an adder held 1 mm off the end: right volume, two solids
        self.boolean("Fuse", self.box("Loose", -1 * IN, -3 * IN, 96 * IN + 1, 2 * IN, 6 * IN, 4 * IN))
        self.assertEqual(measure.solid_count(self.body), 2)
        self.assertFalse(measure.is_whole(self.body))
        self.assertTrue(self.body.Shape.isValid())

    def test_angled_end_long_and_short_point(self):
        from freecad.bentwizard import measure
        # saw end B at 30 degrees: a half-space box rotated -30 about local
        # X, hinged at the BOTTOM edge (y = -WidthY/2) of the design end, so
        # the cut plane runs from z = 96 in there down to 96 - 8 tan30 at
        # the top edge
        cutter = self.box("Saw", 0, 0, 0, 1000, 1000, 500,
                          App.Rotation(App.Vector(1, 0, 0), -30))
        cutter.Placement.Base = App.Vector(-500, -4 * IN, 96 * IN)
        self.boolean("Cut", cutter)
        short, long = measure.angled_end_points(self.body)
        self.assertAlmostEqual(long / IN, 96, places=6)
        self.assertAlmostEqual(short / IN, 96 - 8 * math.tan(math.radians(30)), places=6)
        self.assertAlmostEqual(measure.order_length(self.body) / IN, 96, places=6)
        self.assertTrue(measure.is_whole(self.body))


if __name__ == "__main__":
    unittest.main()
