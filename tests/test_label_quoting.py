"""Quotes in labels (sweep finding 18). FreeCAD stores `<<T-Girt 6'-001>>`
as `<<T-Girt 6\\'-001>>`, so every tool that finds a reference in stored
text must match the escaped form. Before the fix New Timber refused such a
label outright; a framer writes 8"x8" and 6' without thinking."""

import sys
import tempfile
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
IN3 = IN ** 3
LIBRARY = REPO_ROOT / "library"
POST = 'T-Post 8"x8"-001'
GIRT = "T-Girt 6'-001"


@unittest.skipUnless(HAVE_FREECAD, "FreeCAD not importable — run with the bundled python")
class QuotedLabelTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from freecad.bentwizard.template import TemplateSpec
        cls.spec = TemplateSpec(LIBRARY / "Joint_HousedMT.FCStd")

    def setUp(self):
        from freecad.bentwizard.apply import apply_joint
        from freecad.bentwizard.timber import new_timber
        self.doc = App.newDocument("QuoteTest")
        pv = self.doc.addObject("App::VarSet", "PV")
        pv.Label = "ProjectVars"
        pv.addProperty("App::PropertyLength", "GirtLine", "Layout", "girt line")
        pv.GirtLine = "48 in"
        self.post, self.post_dims = new_timber(self.doc, POST, "8 in", "8 in", "8 ft")
        self.girt, self.girt_dims = new_timber(self.doc, GIRT, "6 in", "8 in", "6 ft")
        # a parameter bound to the girt's own Dims: Duplicate must re-point it
        self.varset = apply_joint(self.doc, self.spec, "001", {
            self.spec.host_role: {"body": self.post, "face": "YPos",
                                  "station": "=<<ProjectVars>>.GirtLine"},
            self.spec.mate_role: {"body": self.girt, "face": "EndB"}},
            values={"TenonLength": f"=<<TDim_{GIRT}>>.WidthY / 2"}).varset

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def test_new_timber_resolves_its_dims(self):
        from freecad.bentwizard.timber import dims_varset
        self.assertIs(dims_varset(self.post), self.post_dims)
        self.assertIs(dims_varset(self.girt), self.girt_dims)
        self.assertEqual(self.post_dims.Label, f"TDim_{POST}")

    def test_apply_seat_and_lint(self):
        from freecad.bentwizard import datums, frame, measure, naming
        from freecad.bentwizard.apply import joint_components
        self.assertTrue(measure.is_whole(self.post))
        self.assertTrue(measure.is_whole(self.girt))
        self.assertLess(self.post.Shape.Volume / IN3, 8 * 8 * 96 - 1)
        self.assertAlmostEqual(self.varset.TenonLength.Value / IN, 4, places=6)
        self.assertTrue(joint_components(self.varset))
        host = datums.host_datum(self.varset)
        self.assertIs(datums.owner(host), self.post)
        # the fallback reads the accessor expression, a quoted label in it
        setattr(self.varset, naming.PROP_HOST_DATUM, "")
        self.assertIs(datums.host_datum(self.varset), host)

        seating = frame.place_on_apply(self.doc, self.varset)
        self.assertIs(seating.mover, self.girt)
        self.assertIsNotNone(frame.seat_driving(self.girt))
        self.assertIs(frame.anchor_timber(self.girt), self.post)
        mm, deg = frame.joint_misfit(self.varset)
        self.assertLess(mm, 1e-6)
        self.assertLess(deg, 1e-6)

        from freecad.bentwizard.linter import STRICT, lint
        with tempfile.TemporaryDirectory() as td:
            path = str(Path(td) / "q.FCStd")
            self.doc.saveAs(path)
            strict = [str(f) for f in lint(path) if f.severity == STRICT]
        self.assertEqual(strict, [])

    def test_duplicate_re_points_quoted_references(self):
        from freecad.bentwizard import measure, naming
        from freecad.bentwizard.duplicate import duplicate_bent
        from freecad.bentwizard.frame import place_on_apply
        place_on_apply(self.doc, self.varset)
        new_bodies, new_joints, _outside = duplicate_bent(
            self.doc, {self.post: 'T-Post 8"x8"-002', self.girt: "T-Girt 6'-002"},
            {self.varset.Label: "002"}, LIBRARY,
            offset=App.Vector(120 * IN, 0, 0))
        (joint,) = new_joints
        exprs = {p.lstrip("."): e for p, e in joint.ExpressionEngine}
        self.assertEqual(naming.referenced_labels(exprs["TenonLength"]),
                         {"TDim_T-Girt 6'-002"})
        for body in new_bodies.values():
            self.assertTrue(measure.is_whole(body), body.Label)

    def test_renamed_joint_and_seat_are_still_found(self):
        """Tool labels carry no quotes, but a framer may rename a joint or
        its seat; FreeCAD then rewrites every reference, escaped."""
        from freecad.bentwizard import frame, measure
        from freecad.bentwizard.apply import joint_components, remove_joint
        frame.place_on_apply(self.doc, self.varset)
        comps = set(c.Name for c in joint_components(self.varset))
        seat = frame.seat_driving(self.girt)
        self.varset.Label = "J-HousedMT 'north'-001"
        seat.Label = 'Seat "north"'
        self.doc.recompute()
        self.assertIs(frame.seat_driving(self.girt), seat)
        self.assertEqual({c.Name for c in joint_components(self.varset)}, comps)
        remove_joint(self.varset)
        self.doc.recompute()
        self.assertAlmostEqual(self.post.Shape.Volume / IN3, 8 * 8 * 96, places=6)
        self.assertTrue(measure.is_whole(self.post))

    def test_remove_restores_the_timber(self):
        from freecad.bentwizard import measure
        from freecad.bentwizard.apply import remove_joint
        remove_joint(self.varset)
        self.doc.recompute()
        self.assertAlmostEqual(self.post.Shape.Volume / IN3, 8 * 8 * 96, places=6)
        self.assertTrue(measure.is_whole(self.post))


if __name__ == "__main__":
    unittest.main()
