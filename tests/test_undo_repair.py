"""Tests for the undo expression-rearm repair (finding #15).

FreeCAD-dependent — run with the bundled interpreter; skips under
plain Python. Pins both the upstream defect (so the day FreeCAD fixes
it, these tests say so) and the repair, on plain primitives and on a
real applied timber joint.
"""

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
import _repo_path  # noqa: E402 — this repo's code must win the import

try:
    import FreeCAD as App
    import Part  # noqa: F401 — registers Part::Box
    _repo_path.graft()
    HAVE_FREECAD = True
except ImportError:
    HAVE_FREECAD = False

TEMPLATE = REPO_ROOT / "library" / "Joint_HousedMT.FCStd"


@unittest.skipUnless(HAVE_FREECAD, "FreeCAD not importable — run with the bundled python")
class UndoRearmPrimitivesTest(unittest.TestCase):
    """The defect and the repair on two boxes — no BentWizard geometry,
    so a failure here is a statement about FreeCAD, not about us."""

    def setUp(self):
        from freecad.bentwizard import undo_repair
        undo_repair.uninstall()          # each test installs what it wants
        self.doc = App.newDocument("UndoRearm")
        self.a = self.doc.addObject("Part::Box", "BoxA")
        self.b = self.doc.addObject("Part::Box", "BoxB")
        self.b.setExpression("Height", "BoxA.Height")
        self.doc.recompute()
        self.doc.UndoMode = 1

    def tearDown(self):
        from freecad.bentwizard import undo_repair
        undo_repair.uninstall()
        App.closeDocument(self.doc.Name)

    def drives(self, value):
        """Does BoxA still drive BoxB's height through the expression?"""
        a, b = self.doc.getObject("BoxA"), self.doc.getObject("BoxB")
        a.Height = value
        self.doc.recompute()
        return b.Height.Value == value

    def delete_both(self):
        self.doc.openTransaction("del")
        self.doc.removeObject("BoxB")
        self.doc.removeObject("BoxA")
        self.doc.commitTransaction()

    def test_binding_is_live_before_any_undo(self):
        self.assertTrue(self.drives(25))

    def test_upstream_loses_the_binding_on_undo(self):
        # Not our behaviour to fix in place — the guard that tells us if
        # FreeCAD ever repairs this itself, at which point the observer
        # becomes dead weight and should go.
        self.delete_both()
        self.doc.undo()
        self.doc.recompute()
        a = self.doc.getObject("BoxA")
        b = self.doc.getObject("BoxB")
        self.assertEqual(b.ExpressionEngine, [("Height", "BoxA.Height")],
                         "expression text should survive undo")
        self.assertEqual([o.Name for o in a.InList], [],
                         "upstream bug gone? drop undo_repair if so")
        self.assertFalse(self.drives(40))

    def test_rearm_restores_the_binding(self):
        from freecad.bentwizard import undo_repair
        self.delete_both()
        self.doc.undo()
        self.doc.recompute()
        undo_repair.rearm(self.doc.Objects)
        self.doc.recompute()
        a = self.doc.getObject("BoxA")
        self.assertEqual([o.Name for o in a.InList], ["BoxB"])
        self.assertTrue(self.drives(55))

    def test_observer_repairs_undo_automatically(self):
        from freecad.bentwizard import undo_repair
        undo_repair.install()
        self.delete_both()
        self.doc.undo()
        self.doc.recompute()
        self.assertTrue(self.drives(60))

    def test_observer_repairs_redo_of_an_undone_delete(self):
        # undo the delete, then undo the *creation* and redo it back:
        # the redo re-creates objects the same way and needs the same
        # repair.
        from freecad.bentwizard import undo_repair
        undo_repair.install()
        self.delete_both()
        self.doc.undo()
        self.doc.recompute()
        self.doc.redo()                  # delete again
        self.doc.recompute()
        self.assertIsNone(self.doc.getObject("BoxA"))
        self.doc.undo()                  # and back once more
        self.doc.recompute()
        self.assertTrue(self.drives(65))

    def test_undo_that_restores_nothing_is_left_alone(self):
        # an undo of a plain property edit restores no objects: the
        # observer must not touch or recompute the document for it
        from freecad.bentwizard import undo_repair
        obs = undo_repair.install()
        self.doc.openTransaction("edit")
        self.a.Length = 42
        self.doc.commitTransaction()
        self.doc.undo()
        self.assertEqual(obs._created, {}, "nothing should be buffered")
        self.assertTrue(self.drives(70))

    def test_ordinary_creation_does_not_accumulate_in_the_buffer(self):
        from freecad.bentwizard import undo_repair
        obs = undo_repair.install()
        self.doc.openTransaction("add")
        self.doc.addObject("Part::Box", "BoxC")
        self.doc.commitTransaction()
        self.assertEqual(obs._created, {},
                         "a committed transaction clears the buffer")


@unittest.skipUnless(HAVE_FREECAD, "FreeCAD not importable — run with the bundled python")
class UndoRemoveJointTest(unittest.TestCase):
    """The real thing: undo of Remove Joint gives back a joint that
    still drives its timbers' geometry."""

    @classmethod
    def setUpClass(cls):
        from freecad.bentwizard.apply_joint import TemplateSpec
        cls.spec = TemplateSpec(TEMPLATE)

    def setUp(self):
        from freecad.bentwizard import undo_repair
        from freecad.bentwizard.apply_joint import apply_joint
        from freecad.bentwizard.assemble import assimilate_joint
        from freecad.bentwizard.timber import new_timber
        undo_repair.uninstall()
        self.doc = App.newDocument("UndoJoint")
        self.post, _ = new_timber(self.doc, "P3-1", "10 in", "8 in", "10 ft")
        self.beam, _ = new_timber(self.doc, "B3-1", "6 in", "8 in", "8 ft")
        self.varset = apply_joint(
            self.doc, self.spec, "B3a",
            {"T.Post.001": self.post, "T.AnchorBeam.001": self.beam})
        assimilate_joint(self.doc, self.varset)
        self.doc.recompute()
        self.names = (self.varset.Name, self.post.Name)
        self.doc.UndoMode = 1

    def tearDown(self):
        from freecad.bentwizard import undo_repair
        undo_repair.uninstall()
        App.closeDocument(self.doc.Name)

    def housing_drives_the_post(self):
        """Nudge Housing_Depth and see whether the post's cut follows.

        Nudges wherever the parameter is AUTHORITATIVE: templates that
        declare a companion layout VarSet hold the length-consuming
        parameters there, and the joint VarSet only consumes them, so
        writing to the joint's copy is overwritten on recompute.
        """
        from freecad.bentwizard.apply_joint import layout_varset
        joint = self.doc.getObject(self.names[0])
        vs = layout_varset(joint) or joint
        if not hasattr(vs, "Housing_Depth"):
            vs = joint
        post = self.doc.getObject(self.names[1])
        before = post.Shape.Volume
        quarter = App.Units.Quantity("0.25 in")
        vs.Housing_Depth = vs.Housing_Depth + quarter
        self.doc.recompute()
        moved = post.Shape.Volume != before
        vs.Housing_Depth = vs.Housing_Depth - quarter
        self.doc.recompute()
        self.assertAlmostEqual(post.Shape.Volume, before, places=6,
                               msg="nudge should be reversible")
        return moved

    def remove_in_a_transaction(self):
        from freecad.bentwizard.apply_joint import remove_joint
        self.doc.openTransaction("Remove Joint")
        remove_joint(self.varset)
        self.doc.commitTransaction()

    def test_joint_drives_geometry_before_removal(self):
        self.assertTrue(self.housing_drives_the_post())

    def test_undo_without_repair_returns_a_dead_joint(self):
        # documents the bug being fixed; the count/state checks are what
        # made it invisible in the first place
        count = len(self.doc.Objects)
        self.remove_in_a_transaction()
        self.doc.undo()
        self.doc.recompute()
        self.assertEqual(len(self.doc.Objects), count)
        self.assertEqual([o.Name for o in self.doc.Objects if not o.isValid()],
                         [], "every object claims to be fine")
        self.assertFalse(self.housing_drives_the_post())

    def test_undo_with_the_observer_returns_a_live_joint(self):
        from freecad.bentwizard import undo_repair
        undo_repair.install()
        count = len(self.doc.Objects)
        self.remove_in_a_transaction()
        self.doc.undo()
        self.doc.recompute()
        self.assertEqual(len(self.doc.Objects), count)
        self.assertTrue(self.housing_drives_the_post(),
                        "undone Remove Joint must give back a live joint")

    def test_restored_joint_is_still_structurally_whole(self):
        from freecad.bentwizard import joint_handle, undo_repair
        undo_repair.install()
        self.remove_in_a_transaction()
        self.doc.undo()
        self.doc.recompute()
        vs = self.doc.getObject(self.names[0])
        self.assertIsNotNone(vs)
        self.assertIsNotNone(joint_handle.find_handle(vs),
                             "the joint's handle comes back with it")
        bad = [o.Name for o in self.doc.Objects
               if not o.isValid() or "Invalid" in o.State]
        self.assertEqual(bad, [])


if __name__ == "__main__":
    unittest.main()
