"""Duplicate Timbers: copies match, stay independent, carry project
bindings and datums, re-apply their joints, and seat as a new bent."""

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


@unittest.skipUnless(HAVE_FREECAD, "FreeCAD not importable — run with the bundled python")
class DuplicateBentTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from freecad.bentwizard.template import TemplateSpec
        cls.spec = TemplateSpec(LIBRARY / "Joint_HousedMT.FCStd")

    def setUp(self):
        from freecad.bentwizard.apply import apply_joint
        from freecad.bentwizard.frame import place_on_apply
        from freecad.bentwizard.timber import new_timber
        self.doc = App.newDocument("DupTest")
        pv = self.doc.addObject("App::VarSet", "PV")
        pv.Label = "ProjectVars"
        pv.addProperty("App::PropertyLength", "GirtLine", "Layout", "girt line")
        pv.GirtLine = "48 in"
        pv.addProperty("App::PropertyLength", "Bay", "Layout", "bay")
        pv.Bay = "10 ft"
        self.pv = pv
        self.post1, _ = new_timber(self.doc, "T-Post-001", "8 in", "8 in", "8 ft")
        self.post2, _ = new_timber(self.doc, "T-Post-002", "8 in", "8 in", "8 ft")
        self.beam, _ = new_timber(self.doc, "T-Beam-001", "6 in", "8 in",
                                  "=<<ProjectVars>>.Bay")
        self.j1 = apply_joint(self.doc, self.spec, "001", {
            self.spec.host_role: {"body": self.post1, "face": "YPos",
                                  "station": "=<<ProjectVars>>.GirtLine"},
            self.spec.mate_role: {"body": self.beam, "face": "EndA"}},
            values={"TenonLength": "5 in"}).varset
        self.j2 = apply_joint(self.doc, self.spec, "002", {
            self.spec.host_role: {"body": self.post2, "face": "YNeg", "station": "48 in"},
            self.spec.mate_role: {"body": self.beam, "face": "EndB"}}).varset
        place_on_apply(self.doc, self.j1)
        place_on_apply(self.doc, self.j2)
        self.sources = [self.post1, self.post2, self.beam]

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def duplicate(self, bodies=None, **kw):
        from freecad.bentwizard.apply import bent_joints
        from freecad.bentwizard.duplicate import (duplicate_bent, suggest_joint_serials,
                                                  suggest_member_labels)
        bodies = bodies or self.sources
        inside, _ = bent_joints(self.doc, bodies)
        return duplicate_bent(
            self.doc, suggest_member_labels(self.doc, bodies),
            {j.Label: s for j, s in suggest_joint_serials(self.doc, inside).items()},
            LIBRARY, **kw)

    def test_copies_match_and_are_independent(self):
        from freecad.bentwizard import datums
        new_bodies, new_joints, skipped = self.duplicate()
        self.assertEqual(skipped, [])
        self.assertEqual([b.Label for b in new_bodies.values()],
                         ["T-Post-003", "T-Post-004", "T-Beam-002"])
        self.assertEqual([j.Label for j in new_joints], ["J-HousedMT-003", "J-HousedMT-004"])
        for src, copy in new_bodies.items():
            self.assertAlmostEqual(copy.Shape.Volume, src.Shape.Volume, places=3, msg=src.Label)
        # the copied joint kept its parameter state
        self.assertAlmostEqual(new_joints[0].TenonLength / IN, 5, places=9)
        # and the copied datum kept its project binding
        host = datums.datums_of_joint(new_joints[0])[0]
        self.assertIn("<<ProjectVars>>.GirtLine",
                      dict((p.lstrip("."), e) for p, e in host.ExpressionEngine)["Station"])
        # independence: editing the source moves nothing in the copy
        self.j1.TenonLength = "3 in"
        self.doc.recompute()
        self.assertAlmostEqual(new_joints[0].TenonLength / IN, 5, places=9)
        # the project binding is shared, not copied: Bay moves both beams
        self.pv.Bay = "12 ft"
        self.doc.recompute()
        from freecad.bentwizard import measure
        # source: tenon now 3 in at A (+ 1/2 in housing), 4 in at B; the copy
        # kept 5 in at A
        self.assertAlmostEqual(measure.order_length(self.beam) / IN, 144 + 3.5 + 4.5, places=3)
        self.assertAlmostEqual(measure.order_length(new_bodies[self.beam]) / IN,
                               144 + 5.5 + 4.5, places=3)

    def test_copies_seat_in_an_offset_bent_group(self):
        from freecad.bentwizard import datums, frame
        new_bodies, new_joints, _ = self.duplicate(group_label="Bent-002",
                                                   offset=App.Vector(120 * IN, 0, 0))
        copy1 = new_bodies[self.post1]
        bent2 = copy1.getParentGroup()
        self.assertEqual(bent2.Label, "Bent-002")
        self.assertIsNot(bent2, self.post1.getParentGroup())
        # a bent is tree organisation only — a Std Group, never an Assembly
        self.assertEqual(bent2.TypeId, "App::DocumentObjectGroup")
        self.assertEqual([o.Label for o in self.doc.Objects
                          if o.TypeId == "Assembly::AssemblyObject"], [])
        for vs in new_joints:
            self.assertLess(frame.joint_misfit(vs)[0], 1e-3, vs.Label)
        # the offset rides on the copies; the copy of the principal timber
        # roots them provisionally until a joint ties them to the frame
        self.assertAlmostEqual(datums.global_placement(copy1).Base.x / IN, 120, places=6)
        self.assertIsNone(frame.seat_driving(copy1))
        self.assertFalse(frame.is_anchored(copy1))
        self.assertIs(frame.anchored_timber(self.doc), self.post1)
        for vs in new_joints:
            self.assertIsNotNone(frame.places(vs), vs.Label)

    def test_duplicate_a_duplicate_and_the_original_again(self):
        """Adam's GUI round (2026-09-23): the second Duplicate Timbers in a
        document failed with 'cyclic reference to ...Placement'. The first
        copy's provisional root is neither anchored nor seated, and the
        bulk seating tried to seat it back from the timber it places."""
        from freecad.bentwizard import datums, frame, measure
        first, _j, _ = self.duplicate(group_label="Bent-002",
                                      offset=App.Vector(120 * IN, 0, 0))
        root = first[self.post1]
        before = {b.Name: App.Placement(datums.global_placement(b))
                  for b in first.values()}
        seats = {b.Name: frame.seat_driving(b) for b in first.values()}
        second, j2, _ = self.duplicate(list(first.values()), group_label="Bent-003",
                                       offset=App.Vector(120 * IN, 0, 0))
        third, j3, _ = self.duplicate(group_label="Bent-004",
                                      offset=App.Vector(360 * IN, 0, 0))
        # the first copy is untouched: same seats, same root, same place
        self.assertIsNone(frame.seat_driving(root))
        for b in first.values():
            self.assertIs(frame.seat_driving(b), seats[b.Name], b.Label)
            self.assertLess((datums.global_placement(b).Base
                             - before[b.Name].Base).Length, 1e-9, b.Label)
        self.assertAlmostEqual(
            datums.global_placement(second[root]).Base.x / IN, 240, places=6)
        self.assertAlmostEqual(
            datums.global_placement(third[self.post1]).Base.x / IN, 360, places=6)
        for vs in j2 + j3:
            self.assertIsNotNone(frame.places(vs), vs.Label)
            self.assertLess(frame.joint_misfit(vs)[0], 1e-3, vs.Label)
        for b in list(second.values()) + list(third.values()):
            self.assertTrue(measure.is_whole(b), b.Label)
        self.assertEqual(measure.unhealthy(self.doc), [])

    def test_partial_set_skips_boundary_joints(self):
        new_bodies, new_joints, skipped = self.duplicate([self.post1, self.beam])
        self.assertEqual(skipped, ["J-HousedMT-002"])
        self.assertEqual([j.Label for j in new_joints], ["J-HousedMT-003"])

    def test_output_lints_clean(self):
        from freecad.bentwizard.linter import lint
        self.duplicate(group_label="Bent-002")
        with tempfile.TemporaryDirectory() as td:
            path = str(Path(td) / "dup.FCStd")
            self.doc.saveAs(path)
            self.assertEqual([str(f) for f in lint(path)], [])


if __name__ == "__main__":
    unittest.main()
