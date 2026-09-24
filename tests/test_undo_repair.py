"""Undo of a deletion leaves expression bindings dead (finding #15); the
repair observer re-arms them. Pinned on two plain boxes (a statement
about FreeCAD) and on Undo of Remove Timber Joint (what it buys us).

On 26.3 fine-grained recomputes HIDE the defect (sweep finding 20): with
the preference on, its default, undo gives back a live joint with or
without the repair. So the Remove tests force it OFF for their run, and
restore the user's setting after — otherwise they would pass with the
repair broken. The tripwire asserts the defect is still there without
the repair; when it fails, FreeCAD has fixed #15 and `undo_repair`
can be deleted."""

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
PREF_PATH = "User parameter:BaseApp/Preferences/General"
PREF = "FineGrainedRecompute"


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
        grp = App.ParamGet(PREF_PATH)
        self._pref = grp.GetBool(PREF, True) if PREF in grp.GetBools() else None
        grp.SetBool(PREF, False)            # the defect shows only with it off
        undo_repair.install()
        self.doc = App.newDocument("UndoJoint")
        self.doc.UndoMode = 1

    def tearDown(self):
        from freecad.bentwizard import undo_repair
        App.closeDocument(self.doc.Name)
        undo_repair.uninstall()
        grp = App.ParamGet(PREF_PATH)
        if self._pref is None:
            grp.RemBool(PREF)
        else:
            grp.SetBool(PREF, self._pref)

    def undo_remove(self, seat=False):
        """Apply (and seat), Remove, Undo — each its own transaction, as
        the commands do. Returns the restored (varset, post, girt) and the
        post's jointed volume."""
        from freecad.bentwizard.apply import apply_joint, remove_joint
        from freecad.bentwizard.frame import place_on_apply
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
        if seat:
            place_on_apply(self.doc, vs)
        self.doc.commitTransaction()
        jointed = post.Shape.Volume
        self.doc.openTransaction("remove")
        remove_joint(vs)
        self.doc.commitTransaction()
        self.assertAlmostEqual(post.Shape.Volume / IN3, 8 * 8 * 96, places=6)
        self.doc.undo()
        self.doc.recompute()
        return (self.doc.getObjectsByLabel("J-HousedMT-001")[0],
                self.doc.getObjectsByLabel("T-Post-001")[0],
                self.doc.getObjectsByLabel("T-Girt-001")[0], jointed)

    def test_undo_remove_gives_back_a_live_joint(self):
        vs, post, _girt, jointed = self.undo_remove()
        self.assertAlmostEqual(post.Shape.Volume, jointed, places=3)
        vs.HousingDepth = "1 in"
        self.doc.recompute()
        self.assertLess(post.Shape.Volume, jointed - 1)   # still parametric

    def test_undo_remove_gives_back_a_live_seat(self):
        """Workstream D: the seat is one more restored binding. Move the
        frame after the undo: the girt must follow its seat."""
        from freecad.bentwizard import frame
        vs, _post, girt, _jointed = self.undo_remove(seat=True)
        self.assertIsNotNone(frame.seat_driving(girt))
        frame.project_varset(self.doc).FrameOrigin = App.Placement(
            App.Vector(1000, 500, 0), App.Rotation(App.Vector(0, 0, 1), 30))
        self.doc.recompute()
        self.assertLess(frame.joint_misfit(vs)[0], 1e-6)

    def test_tripwire_the_defect_is_still_there(self):
        """Without the repair, the undone joint is a fossil. When this
        fails, FreeCAD has fixed finding #15: delete undo_repair."""
        from freecad.bentwizard import undo_repair
        undo_repair.uninstall()
        vs, post, _girt, jointed = self.undo_remove()
        vs.HousingDepth = "1 in"
        self.doc.recompute()
        self.assertAlmostEqual(
            post.Shape.Volume, jointed, places=3,
            msg="FreeCAD fixed finding #15 — delete undo_repair "
                "(see its module docstring)")


if __name__ == "__main__":
    unittest.main()
