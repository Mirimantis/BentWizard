"""Tests for Apply-Joint (freecad.bentwizard.apply_joint).

FreeCAD-dependent — run with the bundled interpreter; skips under
plain Python. Applies the real library template to fresh timbers and
pins the result to analytic cut volumes and a completely clean lint.
"""

import math
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

try:
    import FreeCAD as App
    import freecad
    _repo_pkg = str(REPO_ROOT / "freecad")
    if _repo_pkg not in freecad.__path__:
        freecad.__path__.append(_repo_pkg)
    HAVE_FREECAD = True
except ImportError:
    HAVE_FREECAD = False

TEMPLATE = REPO_ROOT / "library" / "Joint_HousedMT.FCStd"
IN3 = 25.4 ** 3


@unittest.skipUnless(HAVE_FREECAD, "FreeCAD not importable — run with the bundled python")
class ApplyJointTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from freecad.bentwizard.apply_joint import TemplateSpec
        cls.spec = TemplateSpec(TEMPLATE)

    def setUp(self):
        from freecad.bentwizard.timber import new_timber
        self.doc = App.newDocument("ApplyTest")
        self.post, _ = new_timber(self.doc, "P3-1", "10 in", "8 in", "10 ft")
        self.beam, _ = new_timber(self.doc, "B3-1", "6 in", "8 in", "8 ft")
        self.v0 = (self.post.Shape.Volume, self.beam.Shape.Volume)

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def apply(self, joint_id="B3a", **kw):
        from freecad.bentwizard.apply_joint import apply_joint
        return apply_joint(self.doc, self.spec,
                           joint_id, {"P0-1": self.post, "B0-1": self.beam},
                           **kw)

    def cuts(self):
        return ((self.v0[0] - self.post.Shape.Volume) / IN3,
                (self.v0[1] - self.beam.Shape.Volume) / IN3)

    def test_analytic_cut_volumes(self):
        # housing 6x8x0.5 + mortise 2x6x4.25 + 1"-dia bore through the
        # 8" post depth minus its passage through the 2" mortise void;
        # beam: 6x8x4 end slab minus the 2x6x4 tenon island, plus the
        # drawbore through the 2" tenon thickness.
        self.apply()
        post_cut, beam_cut = self.cuts()
        bore = math.pi * 0.25
        self.assertAlmostEqual(post_cut, 24 + 51 + bore * 8 - bore * 2, places=3)
        self.assertAlmostEqual(beam_cut, 144 + bore * 2, places=3)

    def test_junction_binding_tracks_mating_timber(self):
        self.apply()
        cut0, _ = self.cuts()
        dims = self.doc.getObjectsByLabel("TimberDims_B3-1")[0]
        dims.Width = "8 in"                     # widen the beam
        self.doc.recompute()
        cut1, _ = self.cuts()
        self.assertGreater(cut1, cut0)          # housing widened with it

    def test_station_override_places_joint(self):
        vs = self.apply(values={"Joint_Station": App.Units.Quantity("20 in")})
        self.assertAlmostEqual(vs.Joint_Station.Value, 508.0, places=6)
        post_cut, _ = self.cuts()
        self.assertGreater(post_cut, 70)        # cuts landed inside the stick

    def test_two_instances_coexist_and_ids_collide(self):
        from freecad.bentwizard.apply_joint import JointError
        self.apply("B3a", values={"Joint_Station": App.Units.Quantity("60 in")})
        self.apply("B3b", values={"Joint_Station": App.Units.Quantity("20 in")})
        with self.assertRaises(JointError):
            self.apply("B3a")

    def test_oversized_defaults_refused_before_cutting(self):
        # Template defaults (6 in tenon height + 1 in setback) cannot
        # fit a 4 in deep beam: the pre-flight must refuse after the
        # junction bindings resolve, before any geometry is cut.
        from freecad.bentwizard.apply_joint import JointError, apply_joint
        from freecad.bentwizard.timber import new_timber
        small, _ = new_timber(self.doc, "B3-9", "6 in", "4 in", "8 ft")
        v_post = self.post.Shape.Volume
        with self.assertRaises(JointError) as ctx:
            apply_joint(self.doc, self.spec, "B9x",
                        {"P0-1": self.post, "B0-1": small})
        self.assertIn("does not fit", str(ctx.exception))
        self.doc.recompute()
        self.assertAlmostEqual(self.post.Shape.Volume, v_post, places=6)

    def test_output_lints_completely_clean(self):
        from freecad.bentwizard.linter import lint
        self.apply()
        with tempfile.TemporaryDirectory() as td:
            path = str(Path(td) / "applied.FCStd")
            self.doc.saveAs(path)
            self.assertEqual([str(f) for f in lint(path)], [])


if __name__ == "__main__":
    unittest.main()
