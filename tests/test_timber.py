"""Tests for the New Timber core (freecad.bentwizard.timber).

These need the FreeCAD Python API — run the suite with the bundled
interpreter (FreeCAD_1.1.1-.../bin/python.exe); under a plain Python
they skip cleanly, keeping the rest of the suite stdlib-only.
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
    _repo_path.graft()   # FreeCAD's init grafts the Mod copy; ours first
    HAVE_FREECAD = True
except ImportError:
    HAVE_FREECAD = False


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
        self.assertEqual(dims.Label, "TimberDims_T-Post-001")
        self.assertAlmostEqual(body.Shape.Volume / 25.4 ** 3,
                               10 * 8 * 192, places=6)
        for prop in ("Width", "Depth", "Length", "Position_Tag"):
            self.assertTrue(dims.getDocumentationOfProperty(prop).strip(),
                            f"{prop} missing tooltip")

    def test_dims_varset_nested_in_body(self):
        # tree organization: the Dims VarSet is a child of its Body
        body, dims = self.new("T-Post-001", "10 in", "8 in", "16 ft")
        self.assertIn(dims, list(body.Group))

    def test_position_tag_is_display_only_data(self):
        _, dims = self.new("T-Post-001", "10 in", "8 in", "16 ft",
                           "Bent 2, north post")
        self.assertEqual(dims.Position_Tag, "Bent 2, north post")
        _, bare = self.new("T-Post-002", "10 in", "8 in", "16 ft")
        self.assertEqual(bare.Position_Tag, "")

    def test_parametric_follow_through(self):
        body, dims = self.new("T-Post-001", "10 in", "8 in", "16 ft")
        dims.Width = "12 in"
        self.doc.recompute()
        self.assertAlmostEqual(body.Shape.Volume / 25.4 ** 3,
                               12 * 8 * 192, places=6)

    def test_rejects_bad_input(self):
        self.assertRejected("", "8 in", "8 in", "8 ft")
        self.assertRejected("a<b", "8 in", "8 in", "8 ft")
        self.assertRejected("T-Post-001", "0 in", "8 in", "8 ft")
        self.new("T-Post-001", "8 in", "8 in", "8 ft")
        self.assertRejected("T-Post-001", "8 in", "8 in", "8 ft")  # duplicate

    def test_custom_label_binds_expressions(self):
        # Off-convention labels are allowed (advisory lint nudges later);
        # expressions must survive a label with spaces.
        body, dims = self.new("Ridge Post (custom)", "8 in", "8 in", "8 ft")
        self.assertEqual(dims.Label, "TimberDims_Ridge Post (custom)")
        dims.Width = "10 in"
        self.doc.recompute()
        self.assertAlmostEqual(body.Shape.Volume / 25.4 ** 3,
                               10 * 8 * 96, places=6)

    def test_output_lints_clean(self):
        from freecad.bentwizard.linter import lint
        self.new("T-Post-Level1-003", "10 in", "8 in", "16 ft")
        self.new("T-TieBeam_decorative-007", "6 in", "8 in", "12 ft")
        self.new("P2-1", "8 in", "8 in", "8 ft")       # legacy, still clean
        with tempfile.TemporaryDirectory() as td:
            path = str(Path(td) / "out.FCStd")
            self.doc.saveAs(path)
            self.assertEqual([str(f) for f in lint(path)], [])


if __name__ == "__main__":
    unittest.main()
