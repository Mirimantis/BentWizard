"""Tests for the two-level structure assembly (assemble.py).

FreeCAD-dependent — run with the bundled interpreter; skips under plain
Python. Exercises the container rules (bent sub-assemblies, the parent
frame), the parity-corrected seating (the inverted end-B/face-2 bent of
the first GUI shakedown), the 10-step bay sequence, and the parametric
bay width.
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

TEMPLATE = REPO_ROOT / "library" / "Joint_HousedMT.FCStd"
LIBRARY_DIR = REPO_ROOT / "library"


@unittest.skipUnless(HAVE_FREECAD, "FreeCAD not importable — run with the bundled python")
class TwoLevelAssemblyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from freecad.bentwizard.apply_joint import TemplateSpec
        cls.spec = TemplateSpec(TEMPLATE)

    def setUp(self):
        self.doc = App.newDocument("AssembleTest")

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def timber(self, label, w="8 in", d="8 in", length="8 ft"):
        from freecad.bentwizard.timber import new_timber
        body, _dims = new_timber(self.doc, label, w, d, length)
        return body

    def joint(self, jid, post, beam, face=4, end="A"):
        from freecad.bentwizard.apply_joint import apply_joint
        return apply_joint(self.doc, self.spec, jid,
                           {"P0-1": post, "B0-1": beam},
                           placement={"P0-1": {"face": face},
                                      "B0-1": {"end": end}})

    def pi_bent(self, tag="1"):
        """post1 --endA--> beam <--endB-- post2 (the benttest shape:
        face 4 on the near post, face 2 on the far post)."""
        from freecad.bentwizard.assemble import assimilate_joint
        post1 = self.timber(f"P{tag}-1")
        post2 = self.timber(f"P{tag}-2")
        beam = self.timber(f"B{tag}-1", "6 in", "8 in", "10 ft")
        j1 = self.joint(f"{tag}a", post1, beam, face=4, end="A")
        j2 = self.joint(f"{tag}b", post2, beam, face=2, end="B")
        assimilate_joint(self.doc, j1)
        assimilate_joint(self.doc, j2)
        return post1, post2, beam, j1, j2

    # --- the shakedown regression -------------------------------------

    def test_pi_bent_seats_without_inversion(self):
        from freecad.bentwizard.assemble import (container_assembly,
                                                 joint_misfit)
        post1, post2, beam, j1, j2 = self.pi_bent()
        # one bent sub-assembly holds all three
        asm = container_assembly(post1)
        self.assertIsNotNone(asm)
        self.assertIs(container_assembly(beam), asm)
        self.assertIs(container_assembly(post2), asm)
        for vs in (j1, j2):
            mm, deg = joint_misfit(vs)
            self.assertLess(mm, 1e-6, vs.Label)
            self.assertLess(deg, 1e-6, vs.Label)
        # THE regression: the far post stood on its head (yaw 180),
        # clipping through its own back. Correct: upright, unrotated.
        self.assertTrue(post2.Placement.Rotation.isSame(App.Rotation(),
                                                        1e-9),
                        f"post2 rotated: {post2.Placement.Rotation}")
        # the pose derived numerically from scratch/benttest.FCStd:
        # beam tip at 3136.9, tenon 101.6, housing 12.7 -> post at
        # x = 3136.9 - 101.6 - 12.7 = 3022.6, upright at grade
        self.assertAlmostEqual(post2.Placement.Base.x, 3022.6, places=1)
        self.assertAlmostEqual(post2.Placement.Base.y, 0.0, places=4)
        self.assertAlmostEqual(post2.Placement.Base.z, 0.0, places=4)
        overlap = post2.Shape.common(beam.Shape).Volume
        self.assertLess(overlap / 25.4 ** 3, 1e-3,
                        "far post interpenetrates the beam")

    # --- container rules ----------------------------------------------

    def test_first_joint_creates_grounded_bent(self):
        from freecad.bentwizard.assemble import (assimilate_joint,
                                                 container_assembly,
                                                 find_fixed_joint,
                                                 grounded_joint)
        post = self.timber("P2-1")
        beam = self.timber("B2-1", "6 in", "8 in", "8 ft")
        vs = self.joint("2a", post, beam)
        result = assimilate_joint(self.doc, vs)
        asm = container_assembly(post)
        self.assertEqual(asm.TypeId, "Assembly::AssemblyObject")
        self.assertIs(container_assembly(beam), asm)
        # the anchor (mortise carrier) is the Principal timber, and the
        # result reports the creation so the GUI can announce it
        self.assertIs(grounded_joint(asm).ObjectToGround, post)
        self.assertIs(result.new_assembly, asm)
        self.assertIs(result.principal, post)
        self.assertIs(find_fixed_joint(self.doc, vs), result.joint)
        # references point at LCS datums by object reference
        self.assertIs(result.joint.Reference1[0], post)
        self.assertIn("LocalCoordinateSystem", result.joint.Reference1[1][0])

    def test_loose_timber_joins_the_other_bent(self):
        from freecad.bentwizard.assemble import (assimilate_joint,
                                                 container_assembly)
        post1, post2, beam, _j1, _j2 = self.pi_bent()
        asm = container_assembly(post1)
        tie = self.timber("T3-1", "6 in", "8 in", "12 ft")
        vs = self.joint("3a", post1, tie, face=3, end="A")
        assimilate_joint(self.doc, vs)
        self.assertIs(container_assembly(tie), asm)

    def test_preseat_moves_the_unconnected_side(self):
        # The Bay-1 shakedown bug: the tie beam lives in its own
        # assembly and is already connected to bent 1 through its A-end
        # joint. The B-end joint must bring the NEW bent to the tie —
        # the tie and bent 1 stay exactly where they are.
        from freecad.bentwizard.assemble import (assemble_timbers,
                                                 assimilate_joint,
                                                 container_assembly,
                                                 joint_misfit,
                                                 root_assembly)
        from freecad.bentwizard.duplicate import duplicate_bent
        post1, post2, beam, j1, j2 = self.pi_bent(tag="8")
        bent1 = container_assembly(post1)
        new_bodies, _joints, _sk = duplicate_bent(
            self.doc, {post1: "P8-11", post2: "P8-12", beam: "B8-11"},
            {j1.Label: "81", j2.Label: "82"}, LIBRARY_DIR,
            assembly_label="Bent-002", offset=App.Vector(0, 5000, 0))
        bent2 = next(o for o in self.doc.Objects if o.Label == "Bent-002")

        tie = self.timber("T8-1", "6 in", "8 in", "10 ft")
        bay, _s, _m = assemble_timbers(self.doc, [tie], label="Bay-1")
        ta = self.joint("8t1", post1, tie, face=3, end="A")
        assimilate_joint(self.doc, ta)      # cross: bent1 + Bay-1 -> frame
        frame = root_assembly(bent1)
        self.assertIsNot(frame, bent1)
        tie_g = App.Placement(tie.getGlobalPlacement())
        post1_g = App.Placement(post1.getGlobalPlacement())

        tb = self.joint("8t2", new_bodies[post1], tie, face=1, end="B")
        assimilate_joint(self.doc, tb)
        # the already-connected side never moved
        self.assertLess(
            (tie.getGlobalPlacement().Base - tie_g.Base).Length, 1e-6,
            "the tie was dragged off its seat")
        self.assertLess(
            (post1.getGlobalPlacement().Base - post1_g.Base).Length, 1e-6)
        # the new bent came to the tie (left its provisional offset)
        self.assertGreater(abs(bent2.Placement.Base.y - 5000), 1.0)
        for vs in (ta, tb):
            self.assertLess(joint_misfit(vs)[0], 1e-6, vs.Label)

    def test_remove_joint_removes_its_fixed_joint(self):
        from freecad.bentwizard.apply_joint import remove_joint
        from freecad.bentwizard.assemble import (assimilate_joint,
                                                 find_fixed_joint)
        post = self.timber("P4-1")
        beam = self.timber("B4-1", "6 in", "8 in", "8 ft")
        vs = self.joint("4a", post, beam)
        assimilate_joint(self.doc, vs)
        self.assertIsNotNone(find_fixed_joint(self.doc, vs))
        remove_joint(vs)
        self.assertFalse(any(getattr(o, "JointType", None) is not None
                             for o in self.doc.Objects))

    # --- the 10-step bay sequence -------------------------------------

    def test_bay_sequence_and_parametric_width(self):
        from freecad.bentwizard.assemble import (container_assembly,
                                                 grounded_joint,
                                                 joint_misfit,
                                                 root_assembly)
        from freecad.bentwizard.duplicate import duplicate_bent

        # steps 1: design and assemble Bent 1
        post1, post2, beam, j1, j2 = self.pi_bent(tag="5")
        bent1 = container_assembly(post1)

        # step 2: duplicate the bent into an offset Bent-002
        member_map = {post1: "P5-11", post2: "P5-12", beam: "B5-11"}
        new_bodies, new_joints, skipped = duplicate_bent(
            self.doc, member_map, {j1.Label: "51", j2.Label: "52"},
            LIBRARY_DIR, assembly_label="Bent-002",
            offset=App.Vector(0, 3000, 0))
        self.assertEqual(skipped, [])
        bent2 = next(o for o in self.doc.Objects
                     if o.Label == "Bent-002")
        provisional = App.Placement(bent2.Placement)
        self.assertAlmostEqual(provisional.Base.y, 3000, places=6)
        # copies stand at source-relative poses, offset as one unit
        src_g = post2.getGlobalPlacement()
        copy_g = new_bodies[post2].getGlobalPlacement()
        self.assertAlmostEqual(copy_g.Base.y - src_g.Base.y, 3000,
                               places=6)
        self.assertAlmostEqual(copy_g.Base.x, src_g.Base.x, places=6)
        for vs in new_joints:
            self.assertLess(joint_misfit(vs)[0], 1e-6, vs.Label)

        # steps 3-5: a tie beam from a Bent 1 post to a Bent 2 post.
        # Anchor faces along the bay axis: face 3 (y = Depth) on the
        # bent-1 post, face 1 (y = 0) on the bent-2 copy.
        from freecad.bentwizard.assemble import assimilate_joint
        tie = self.timber("T5-1", "6 in", "8 in", "10 ft")
        ta = self.joint("5t1", post1, tie, face=3, end="A")
        assimilate_joint(self.doc, ta)          # tie joins Bent 1
        self.assertIs(container_assembly(tie), bent1)
        tb = self.joint("5t2", new_bodies[post1], tie, face=1, end="B")
        assimilate_joint(self.doc, tb)          # cross-bent -> frame
        frame = root_assembly(bent1)
        self.assertIsNot(frame, bent1)
        self.assertIs(root_assembly(bent2), frame)
        # the OLDEST bent (holds the Principal Post) grounds the frame
        self.assertIs(grounded_joint(frame).ObjectToGround, bent1)
        # Bent 2 snapped from its provisional offset to the tie's pose
        for vs in (ta, tb):
            mm, deg = joint_misfit(vs)
            self.assertLess(mm, 1e-6, vs.Label)
            self.assertLess(deg, 1e-6, vs.Label)
        self.assertGreater(
            (bent2.Placement.Base - provisional.Base).Length, 1.0,
            "bent 2 never left its provisional offset")

        # parametric bay width: the tie's Length drives Bent 2
        y_before = bent2.Placement.Base.y
        dims = self.doc.getObjectsByLabel("TimberDims_T5-1")[0]
        dims.Length = dims.Length.Value + 200
        self.doc.recompute()
        self.assertAlmostEqual(bent2.Placement.Base.y - y_before, 200,
                               places=4,
                               msg="bay width did not follow tie Length")

    def test_output_lints_completely_clean(self):
        from freecad.bentwizard.linter import lint
        self.pi_bent(tag="6")
        with tempfile.TemporaryDirectory() as td:
            path = str(Path(td) / "assembled.FCStd")
            self.doc.saveAs(path)
            self.assertEqual([str(f) for f in lint(path)], [])


if __name__ == "__main__":
    unittest.main()
