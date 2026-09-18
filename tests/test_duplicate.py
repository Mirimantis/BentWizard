"""Duplicate Timbers: copies match, stay independent, carry project
bindings and datums, re-apply their joints, and assemble as a new bent."""

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
        from freecad.bentwizard.assemble import assimilate_joint
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
        assimilate_joint(self.doc, self.j1)
        assimilate_joint(self.doc, self.j2)
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

    def test_copies_assemble_into_an_offset_bent(self):
        from freecad.bentwizard.assemble import (container_assembly, joint_misfit,
                                                 root_assembly)
        new_bodies, new_joints, _ = self.duplicate(assembly_label="Bent-002",
                                                   offset=App.Vector(120 * IN, 0, 0))
        bent2 = container_assembly(new_bodies[self.post1])
        self.assertEqual(bent2.Label, "Bent-002")
        self.assertIsNot(bent2, container_assembly(self.post1))
        self.assertIs(root_assembly(bent2), bent2)     # no tie yet: two loose bents
        for vs in new_joints:
            self.assertLess(joint_misfit(vs)[0], 1e-3, vs.Label)
        self.assertAlmostEqual(new_bodies[self.post1].getGlobalPlacement().Base.x / IN,
                               120, places=6)

    def test_partial_set_skips_boundary_joints(self):
        new_bodies, new_joints, skipped = self.duplicate([self.post1, self.beam])
        self.assertEqual(skipped, ["J-HousedMT-002"])
        self.assertEqual([j.Label for j in new_joints], ["J-HousedMT-003"])

    def test_output_lints_clean(self):
        from freecad.bentwizard.linter import lint
        self.duplicate(assembly_label="Bent-002")
        with tempfile.TemporaryDirectory() as td:
            path = str(Path(td) / "dup.FCStd")
            self.doc.saveAs(path)
            self.assertEqual([str(f) for f in lint(path)], [])


if __name__ == "__main__":
    unittest.main()
