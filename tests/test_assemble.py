"""The two-level structure assembly on datums: a pi bent seats, the bay
width follows the beam's LengthZ, a second bent joins under a frame,
Remove Joint takes the Fixed joint with it, and the grounded post never
moves."""

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
TEMPLATE = REPO_ROOT / "library" / "Joint_HousedMT.FCStd"


@unittest.skipUnless(HAVE_FREECAD, "FreeCAD not importable — run with the bundled python")
class TwoLevelAssemblyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from freecad.bentwizard.template import TemplateSpec
        cls.spec = TemplateSpec(TEMPLATE)

    def setUp(self):
        self.doc = App.newDocument("AssembleTest")

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def timber(self, label, w="8 in", d="8 in", length="8 ft"):
        from freecad.bentwizard.timber import new_timber
        body, _dims = new_timber(self.doc, label, w, d, length)
        return body

    def joint(self, serial, post, beam, face="YPos", end="EndA", station="48 in"):
        from freecad.bentwizard.apply import apply_joint
        return apply_joint(self.doc, self.spec, serial, {
            self.spec.host_role: {"body": post, "face": face, "station": station},
            self.spec.mate_role: {"body": beam, "face": end}}).varset

    def pi_bent(self, tag="1", assimilate=True):
        """post1 --end A--> beam <--end B-- post2: the beam's end A on
        post1's +Y face, its end B on post2's -Y face."""
        from freecad.bentwizard.assemble import assimilate_joint
        post1 = self.timber(f"T-Post-{tag}01")
        post2 = self.timber(f"T-Post-{tag}02")
        beam = self.timber(f"T-Beam-{tag}01", "6 in", "8 in", "10 ft")
        j1 = self.joint(f"{tag}01", post1, beam, face="YPos", end="EndA")
        j2 = self.joint(f"{tag}02", post2, beam, face="YNeg", end="EndB")
        if assimilate:
            assimilate_joint(self.doc, j1)
            assimilate_joint(self.doc, j2)
        return post1, post2, beam, j1, j2

    def test_pi_bent_seats(self):
        from freecad.bentwizard.assemble import (container_assembly, grounded_joint,
                                                 joint_misfit)
        post1, post2, beam, j1, j2 = self.pi_bent()
        asm = container_assembly(post1)
        self.assertIsNotNone(asm)
        self.assertIs(container_assembly(beam), asm)
        self.assertIs(container_assembly(post2), asm)
        for vs in (j1, j2):
            mm, deg = joint_misfit(vs)
            self.assertLess(mm, 1e-3, vs.Label)
            self.assertLess(deg, 0.01, vs.Label)
        self.assertIs(grounded_joint(asm).ObjectToGround, post1)
        self.assertEqual(post1.Placement.Rotation.Angle, 0)
        self.assertEqual(post1.Placement.Base.Length, 0)
        # post centrelines 120 in + two half posts apart, along post1's +Y
        self.assertAlmostEqual(post2.Placement.Base.y / IN, 120 + 8, places=6)
        self.assertAlmostEqual(post2.Placement.Base.x / IN, 0, places=6)
        self.assertLess(post1.Shape.common(beam.Shape).Volume, 1e-6)
        self.assertLess(post2.Shape.common(beam.Shape).Volume, 1e-6)

    def test_bay_width_follows_the_beam(self):
        from freecad.bentwizard.assemble import container_assembly, joint_misfit
        from freecad.bentwizard.timber import dims_varset
        post1, post2, beam, j1, j2 = self.pi_bent()
        asm = container_assembly(post1)
        dims_varset(beam).LengthZ = "12 ft"
        self.doc.recompute()
        asm.solve()          # headless: a recompute leaves the assembly Touched
        self.doc.recompute()
        self.assertAlmostEqual(post2.Placement.Base.y / IN, 144 + 8, places=6)
        for vs in (j1, j2):
            self.assertLess(joint_misfit(vs)[0], 1e-3)
        # a project variable drives it just the same
        pv = self.doc.addObject("App::VarSet", "PV")
        pv.Label = "ProjectVars"
        pv.addProperty("App::PropertyLength", "BayClear", "Layout", "clear span")
        pv.BayClear = "10 ft"
        dims_varset(beam).setExpression("LengthZ", "<<ProjectVars>>.BayClear")
        self.doc.recompute()
        asm.solve()
        self.doc.recompute()
        self.assertAlmostEqual(post2.Placement.Base.y / IN, 120 + 8, places=6)

    def test_remove_joint_removes_the_fixed_joint(self):
        from freecad.bentwizard.apply import remove_joint
        from freecad.bentwizard.assemble import find_fixed_joint
        post1, post2, beam, j1, j2 = self.pi_bent()
        self.assertIsNotNone(find_fixed_joint(self.doc, j2))
        remove_joint(j2)
        self.assertEqual([o.Label for o in self.doc.Objects
                          if getattr(o, "JointType", None) is not None
                          and "002" in o.Label], [])
        self.assertIsNotNone(find_fixed_joint(self.doc, j1))

    def test_reassimilation_replaces(self):
        from freecad.bentwizard.assemble import assimilate_joint, find_fixed_joints
        post1, post2, beam, j1, j2 = self.pi_bent()
        assimilate_joint(self.doc, j2)
        self.assertEqual(len(find_fixed_joints(self.doc, j2)), 1)

    def test_second_bent_joins_under_a_frame(self):
        from freecad.bentwizard.assemble import (assimilate_joint, container_assembly,
                                                 joint_misfit, root_assembly)
        post1, post2, beam, _j1, _j2 = self.pi_bent("1")
        post3, post4, beam2, _j3, _j4 = self.pi_bent("2")
        tie = self.timber("T-Tie-001", "6 in", "8 in", "12 ft")
        t1 = self.joint("301", post1, tie, face="XPos", end="EndA")
        t2 = self.joint("302", post3, tie, face="XNeg", end="EndB")
        assimilate_joint(self.doc, t1)
        assimilate_joint(self.doc, t2)
        bent1 = container_assembly(post1)
        bent2 = container_assembly(post3)
        self.assertIsNot(bent1, bent2)
        frame = root_assembly(bent1)
        self.assertIs(root_assembly(bent2), frame)
        self.assertIsNot(frame, bent1)
        for vs in (t1, t2):
            self.assertLess(joint_misfit(vs)[0], 1e-3, vs.Label)
        # bent 2 sits 144 + 8 in along +X of bent 1
        self.assertAlmostEqual(post3.getGlobalPlacement().Base.x / IN, 144 + 8, places=6)
        self.assertEqual(post1.getGlobalPlacement().Base.Length, 0)

    def test_assemble_timbers_bulk(self):
        from freecad.bentwizard.assemble import (assemble_timbers, container_assembly,
                                                 joint_misfit)
        post1, post2, beam, j1, j2 = self.pi_bent(assimilate=False)
        asm, skipped, misfits, _adopted = assemble_timbers(
            self.doc, [post1, post2, beam], label="Bent-A", grounded=post1)
        self.assertEqual(asm.Label, "Bent-A")
        self.assertEqual((skipped, misfits), ([], []))
        self.assertIs(container_assembly(beam), asm)
        self.assertLess(joint_misfit(j2)[0], 1e-3)

    def test_output_lints_clean(self):
        from freecad.bentwizard.linter import lint
        self.pi_bent()
        with tempfile.TemporaryDirectory() as td:
            path = str(Path(td) / "bent.FCStd")
            self.doc.saveAs(path)
            self.assertEqual([str(f) for f in lint(path)], [])


if __name__ == "__main__":
    unittest.main()
