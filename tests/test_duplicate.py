"""Tests for Duplicate Bent (freecad.bentwizard.duplicate).

FreeCAD-dependent — run with the bundled interpreter. The core promise
under test is workflow §4.2's layer boundary: instance-layer VarSets
(Dims, joints) duplicate — each copy owns its joints and dims — while
group bindings are preserved to the SAME shared group VarSets. And the
finding #2 regression: no expression in a copy may still point at the
source's VarSets.
"""

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

LIBRARY = REPO_ROOT / "library"
IN3 = 25.4 ** 3


@unittest.skipUnless(HAVE_FREECAD, "FreeCAD not importable — run with the bundled python")
class DuplicateBentTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from freecad.bentwizard.apply_joint import TemplateSpec
        cls.spec = TemplateSpec(LIBRARY / "Joint_HousedMT.FCStd")

    def setUp(self):
        from freecad.bentwizard.timber import new_timber
        from freecad.bentwizard.apply_joint import apply_joint
        self.doc = App.newDocument("DupTest")
        self.p1, _ = new_timber(self.doc, "P1-1", "8 in", "8 in", "108 in")
        self.p2, _ = new_timber(self.doc, "P1-2", "8 in", "8 in", "108 in")
        self.tb, _ = new_timber(self.doc, "TB-1", "6 in", "8 in", "120 in")
        st = App.Units.Quantity("96 in")
        self.j1 = apply_joint(
            self.doc, self.spec, "1a", {"P0-1": self.p1, "B0-1": self.tb},
            values={"Joint_Station": st},
            placement={"P0-1": {"face": 4, "hand": "template"},
                       "B0-1": {"end": "A"}})
        self.j2 = apply_joint(
            self.doc, self.spec, "1b", {"P0-1": self.p2, "B0-1": self.tb},
            values={"Joint_Station": st},
            placement={"P0-1": {"face": 4, "hand": "mirrored"},
                       "B0-1": {"end": "B"}})

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def duplicate(self, member_map=None, joint_ids=None):
        from freecad.bentwizard.duplicate import duplicate_bent
        member_map = member_map or {self.p1: "P2-1", self.p2: "P2-2",
                                    self.tb: "TB-2"}
        joint_ids = joint_ids or {"Joint_MT_1a": "2a", "Joint_MT_1b": "2b"}
        return duplicate_bent(self.doc, member_map, joint_ids, LIBRARY)

    def test_copies_match_originals(self):
        new_bodies, new_joints, skipped = self.duplicate()
        self.assertEqual(skipped, [])
        self.assertEqual(len(new_joints), 2)
        for src, copy in new_bodies.items():
            self.assertAlmostEqual(copy.Shape.Volume, src.Shape.Volume,
                                   places=4, msg=copy.Label)
        # placements carried: 2b is mirrored/end B like 1b
        j2b = next(j for j in new_joints if j.Label == "Joint_MT_2b")
        self.assertIn("face 4, hand mirrored", j2b.Placement_Record)
        self.assertIn("end B", j2b.Placement_Record)
        self.assertIn("P2-2", j2b.Placement_Record)

    def test_copies_are_independent_of_source(self):
        # finding #2: no copy expression may still point at the source.
        # Resize the SOURCE beam: copies must not move; resize the COPY
        # beam: sources must not move.
        new_bodies, _, _ = self.duplicate()
        copy_volumes = {b.Label: b.Shape.Volume for b in new_bodies.values()}
        self.doc.getObjectsByLabel("TimberDims_TB-1")[0].Width = "7 in"
        self.doc.recompute()
        for b in new_bodies.values():
            self.assertAlmostEqual(b.Shape.Volume, copy_volumes[b.Label],
                                   places=4,
                                   msg=f"{b.Label} moved with the source")
        src_volumes = {b.Label: b.Shape.Volume for b in (self.p1, self.p2)}
        self.doc.getObjectsByLabel("TimberDims_TB-2")[0].Width = "8 in"
        self.doc.recompute()
        for b in (self.p1, self.p2):
            self.assertAlmostEqual(b.Shape.Volume, src_volumes[b.Label],
                                   places=4,
                                   msg=f"{b.Label} moved with the copy")

    def test_group_bindings_preserved_to_same_group(self):
        # §4.9: sharing IS the binding — the copy binds the SAME group
        # VarSet, so a group edit moves both bents together.
        proj = self.doc.addObject("App::VarSet", "Proj")
        proj.Label = "Project_Main"
        proj.addProperty("App::PropertyLength", "Tie_Height", "Project", "t")
        proj.Tie_Height = "96 in"
        self.j1.setExpression("Joint_Station", "<<Project_Main>>.Tie_Height")
        self.doc.recompute()
        _, new_joints, _ = self.duplicate()
        j2a = next(j for j in new_joints if j.Label == "Joint_MT_2a")
        exprs = {p.lstrip("."): e for p, e in j2a.ExpressionEngine}
        self.assertIn("<<Project_Main>>", exprs.get("Joint_Station", ""))
        proj.Tie_Height = "90 in"
        self.doc.recompute()
        self.assertAlmostEqual(j2a.Joint_Station.Value, 90 * 25.4, places=6)
        self.assertAlmostEqual(self.j1.Joint_Station.Value, 90 * 25.4,
                               places=6)

    def test_user_override_carries_to_copy(self):
        self.j1.Tenon_Width = "3 in"
        self.doc.recompute()
        _, new_joints, _ = self.duplicate()
        j2a = next(j for j in new_joints if j.Label == "Joint_MT_2a")
        self.assertAlmostEqual(j2a.Tenon_Width.Value, 3 * 25.4, places=6)

    def test_partial_set_skips_boundary_joints(self):
        new_bodies, new_joints, skipped = self.duplicate(
            member_map={self.p1: "P2-1", self.tb: "TB-2"},
            joint_ids={"Joint_MT_1a": "2a"})
        self.assertEqual([j.Label for j in new_joints], ["Joint_MT_2a"])
        self.assertEqual(skipped, ["Joint_MT_1b"])

    def test_output_lints_clean(self):
        from freecad.bentwizard.linter import lint
        self.duplicate()
        with tempfile.TemporaryDirectory() as td:
            path = str(Path(td) / "dup.FCStd")
            self.doc.saveAs(path)
            self.assertEqual([str(f) for f in lint(path)], [])


if __name__ == "__main__":
    unittest.main()
