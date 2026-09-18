"""Undo of a deletion leaves expression bindings dead (finding #15); the
repair observer re-arms them. Pinned on two plain boxes (a statement
about FreeCAD) and on Undo of Remove Timber Joint (what it buys us)."""

import sys
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

IN3 = 25.4 ** 3
TEMPLATE = REPO_ROOT / "library" / "Joint_HousedMT.FCStd"


@unittest.skipUnless(HAVE_FREECAD, "FreeCAD not importable — run with the bundled python")
class UndoRearmPrimitivesTest(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("UndoPrim")
        self.doc.UndoMode = 1

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def test_rearm_restores_the_dependency(self):
        from freecad.bentwizard.undo_repair import rearm
        driver = self.doc.addObject("Part::Box", "Driver")
        follower = self.doc.addObject("Part::Box", "Follower")
        follower.setExpression("Length", "Driver.Length * 2")
        self.doc.recompute()
        self.doc.openTransaction("delete")
        self.doc.removeObject(follower.Name)
        self.doc.commitTransaction()
        self.doc.undo()
        follower = self.doc.getObject("Follower")
        rearm([follower])
        driver.Length = 30
        self.doc.recompute()
        self.assertAlmostEqual(follower.Length.Value, 60)


@unittest.skipUnless(HAVE_FREECAD, "FreeCAD not importable — run with the bundled python")
class UndoRemoveJointTest(unittest.TestCase):
    def setUp(self):
        from freecad.bentwizard import undo_repair
        undo_repair.install()
        self.doc = App.newDocument("UndoJoint")
        self.doc.UndoMode = 1

    def tearDown(self):
        from freecad.bentwizard import undo_repair
        App.closeDocument(self.doc.Name)
        undo_repair.uninstall()

    def test_undo_remove_gives_back_a_live_joint(self):
        from freecad.bentwizard.apply import apply_joint, remove_joint
        from freecad.bentwizard.template import TemplateSpec
        from freecad.bentwizard.timber import new_timber
        spec = TemplateSpec(TEMPLATE)
        self.doc.openTransaction("timbers")
        post, _ = new_timber(self.doc, "T-Post-001", "8 in", "8 in", "8 ft")
        girt, _ = new_timber(self.doc, "T-Girt-001", "6 in", "8 in", "6 ft")
        self.doc.commitTransaction()
        self.doc.openTransaction("apply")
        vs = apply_joint(self.doc, spec, "001", {
            spec.host_role: {"body": post, "face": "YPos", "station": "48 in"},
            spec.mate_role: {"body": girt, "face": "EndB"}}).varset
        self.doc.commitTransaction()
        jointed = post.Shape.Volume
        self.doc.openTransaction("remove")
        remove_joint(vs)
        self.doc.commitTransaction()
        self.assertAlmostEqual(post.Shape.Volume / IN3, 8 * 8 * 96, places=6)
        self.doc.undo()
        self.doc.recompute()
        vs = self.doc.getObjectsByLabel("J-HousedMT-001")[0]
        post = self.doc.getObjectsByLabel("T-Post-001")[0]
        self.assertAlmostEqual(post.Shape.Volume, jointed, places=3)
        vs.HousingDepth = "1 in"
        self.doc.recompute()
        self.assertLess(post.Shape.Volume, jointed - 1)   # still parametric


if __name__ == "__main__":
    unittest.main()
