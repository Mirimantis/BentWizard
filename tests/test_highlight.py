"""The variable highlight's outline — the geometry, not the scene graph.

`view_highlight` keeps its `pivy.coin` imports inside the drawing
functions so the outline is reachable without a GUI. An outline that
does not sit on the timber it names is worse than none, so it is checked
against a real timber's solid.
"""

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
import _repo_path  # noqa: E402, F401

try:
    import FreeCAD as App
    _repo_path.graft()
    HAVE_FREECAD = True
except ImportError:
    HAVE_FREECAD = False


@unittest.skipUnless(HAVE_FREECAD, "FreeCAD not importable — run with the bundled python")
class HighlightOutline(unittest.TestCase):
    def test_twelve_edges_each_along_one_axis(self):
        from freecad.bentwizard.view_highlight import outline
        corners, edges = outline(152.4, 203.2, 2438.4)
        self.assertEqual(len(corners), 8)
        self.assertEqual(len({tuple(sorted(e)) for e in edges}), 12)
        lengths = sorted(
            sum(abs(a - b) for a, b in zip(corners[i], corners[j])) for i, j in edges)
        self.assertEqual(lengths, [152.4] * 4 + [203.2] * 4 + [2438.4] * 4)
        for i, j in edges:
            moved = [a != b for a, b in zip(corners[i], corners[j])]
            self.assertEqual(moved.count(True), 1)

    def test_name_clears_the_timber_however_it_is_turned(self):
        from freecad.bentwizard.view_highlight import label_frame
        for wx, wy, lz in ((152.4, 203.2, 2438.4), (304.8, 152.4, 914.4)):
            height, clearance, middle = label_frame(wx, wy, lz)
            # the letters' near edge is outside the section's corners
            self.assertGreater(clearance, (wx ** 2 + wy ** 2) ** 0.5 / 2)
            self.assertGreater(height, 0)
            self.assertTrue(lz / 2 < middle < lz)    # off the face marks at 1/2

    def test_outline_is_the_timbers_design_solid(self):
        from freecad.bentwizard.timber import new_timber
        from freecad.bentwizard.view_highlight import outline
        doc = App.newDocument("HighlightOutline")
        try:
            body, dims = new_timber(doc, "T-Beam-001", "6 in", "8 in", "10 ft")
            doc.recompute()
            corners, _edges = outline(float(dims.WidthX), float(dims.WidthY),
                                      float(dims.LengthZ))
            box = body.Shape.transformed(body.Placement.inverse().toMatrix()).BoundBox
            for axis, lo, hi in ((0, box.XMin, box.XMax), (1, box.YMin, box.YMax),
                                 (2, box.ZMin, box.ZMax)):
                self.assertAlmostEqual(min(c[axis] for c in corners), lo, places=6)
                self.assertAlmostEqual(max(c[axis] for c in corners), hi, places=6)
        finally:
            App.closeDocument(doc.Name)


if __name__ == "__main__":
    unittest.main()
