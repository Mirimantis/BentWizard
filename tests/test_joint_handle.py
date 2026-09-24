"""The per-joint handle: created by Apply, linked structurally to the
joint's VarSet and host datum, filed in its assembly's group."""

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

TEMPLATE = REPO_ROOT / "library" / "Joint_HousedMT.FCStd"


@unittest.skipUnless(HAVE_FREECAD, "FreeCAD not importable — run with the bundled python")
class JointHandleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from freecad.bentwizard.template import TemplateSpec
        cls.spec = TemplateSpec(TEMPLATE)

    def setUp(self):
        from freecad.bentwizard.apply import apply_joint
        from freecad.bentwizard.timber import new_timber
        self.doc = App.newDocument("HandleTest")
        self.post, _ = new_timber(self.doc, "T-Post-001", "8 in", "8 in", "8 ft")
        self.girt, _ = new_timber(self.doc, "T-Girt-001", "6 in", "8 in", "6 ft")
        self.vs = apply_joint(self.doc, self.spec, "001", {
            self.spec.host_role: {"body": self.post, "face": "YPos", "station": "48 in"},
            self.spec.mate_role: {"body": self.girt, "face": "EndB"}}).varset

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def test_handle_contract(self):
        from freecad.bentwizard import joint_handle
        from freecad.bentwizard.apply import joint_datums
        h = joint_handle.find_handle(self.vs)
        self.assertEqual(h.Label, "Handle_J-HousedMT-001")
        self.assertIs(h.Joint, self.vs)
        self.assertIs(h.Datum, joint_datums(self.vs)[0])
        self.assertIn(self.vs, h.Group)
        self.assertIsNone(getattr(h, "Proxy", None))
        self.assertEqual(h.getParentGroup().Label, "TimberJoints")

    def test_marker_sits_on_the_host_datum(self):
        """The marker's position (view_joint_handle draws it there) is the
        host datum's origin in the document — the post moved, filed in the
        frame's Std Groups, which carry no placement."""
        import warnings
        from freecad.bentwizard import joint_handle
        from freecad.bentwizard.frame import place_on_apply, project_varset
        place_on_apply(self.doc, self.vs)
        # the post is anchored: move it the way a framer does, by the origin
        project_varset(self.doc).FrameOrigin = App.Placement(
            App.Vector(300, -120, 40), App.Rotation(App.Vector(0, 0, 1), 35))
        self.doc.recompute()
        self.assertEqual(self.post.Placement.Base, App.Vector(300, -120, 40))
        h = joint_handle.find_handle(self.vs)
        host = joint_handle.anchor_datum(self.vs)
        want = self.post.Placement.multiply(host.Placement).Base
        with warnings.catch_warnings():
            warnings.simplefilter("error", DeprecationWarning)
            got = joint_handle.marker_position(h, host)
        self.assertLess((got - want).Length, 1e-9)

    def test_structural_not_label_matched(self):
        from freecad.bentwizard import joint_handle
        h = joint_handle.find_handle(self.vs)
        h.Label = "Whatever"
        self.assertIs(joint_handle.find_handle(self.vs), h)
        self.assertTrue(joint_handle.is_handle(h))

    def test_files_into_the_frame(self):
        from freecad.bentwizard import joint_handle
        from freecad.bentwizard.frame import containing_frame, place_on_apply
        place_on_apply(self.doc, self.vs)
        h = joint_handle.find_handle(self.vs)
        group = h.getParentGroup()
        frame = containing_frame(self.post)
        self.assertEqual(group.Label, f"TimberJoints_{frame.Label}")
        self.assertIs(group.getParentGroup(), frame)
        self.assertEqual([o for o in self.doc.Objects
                          if o.TypeId == "App::DocumentObjectGroup"
                          and o.Label == "TimberJoints"], [])

    def test_deleting_a_handle_is_harmless_and_seat_timbers_restores_it(self):
        """Workstream C (Adam, 2026-09-23: deletion stays allowed). A
        handle is disposable, the joint is not: what it holds moves out
        beside it — never loose at the document root, where the seat and
        accessors used to fall — the timbers stay seated, and Seat
        Timbers gives the joint a new handle holding all three again."""
        from freecad.bentwizard import datums, frame, joint_handle, measure
        frame.place_on_apply(self.doc, self.vs)
        seat = frame.seat_driving(self.girt)
        acc = datums.accessors_varset(self.vs)
        self.assertIsNotNone(seat)
        self.assertIsNot(acc, self.vs)
        group = joint_handle.find_handle(self.vs).getParentGroup()
        volume = self.post.Shape.Volume

        self.assertTrue(joint_handle.remove_handle(self.vs))
        self.doc.recompute()
        self.assertIsNone(joint_handle.find_handle(self.vs))
        for obj in (self.vs, acc, seat):
            self.assertIs(obj.getParentGroup(), group, obj.Label)
        self.assertIs(frame.seat_driving(self.girt), seat)
        self.assertLess(frame.joint_misfit(self.vs)[0], 1e-9)
        self.assertAlmostEqual(self.post.Shape.Volume, volume, places=6)
        self.assertTrue(measure.is_whole(self.post))
        self.assertTrue(measure.is_whole(self.girt))
        self.assertEqual(measure.unhealthy(self.doc), [])

        built = frame.rebuild_seats(self.doc, [self.post, self.girt])
        self.assertEqual(built.adopted, 1)
        self.assertEqual(built.seated, [])          # the existing seat is kept
        h = joint_handle.find_handle(self.vs)
        self.assertEqual({o.Name for o in h.Group}, {self.vs.Name, acc.Name, seat.Name})
        self.assertIs(h.getParentGroup(), group)
        self.assertIs(frame.seat_driving(self.girt), seat)
        self.assertEqual(measure.unhealthy(self.doc), [])

    def test_varset_dragged_beside_the_handle_stays(self):
        from freecad.bentwizard import joint_handle
        h = joint_handle.find_handle(self.vs)
        h.getParentGroup().addObject(self.vs)      # beside, not inside
        joint_handle.ensure_handle(self.vs)
        self.assertNotIn(self.vs, h.Group)
        self.assertIn(self.vs, h.getParentGroup().Group)

    def test_removed_with_the_joint_and_adopted(self):
        from freecad.bentwizard import joint_handle
        from freecad.bentwizard.apply import remove_joint
        h = joint_handle.find_handle(self.vs)
        self.doc.removeObject(h.Name)
        self.assertIsNone(joint_handle.find_handle(self.vs))
        self.assertEqual(joint_handle.adopt_handles(self.doc), 1)
        self.assertIsNotNone(joint_handle.find_handle(self.vs))
        remove_joint(self.vs)
        self.assertEqual([o for o in self.doc.Objects if joint_handle.is_handle(o)], [])


if __name__ == "__main__":
    unittest.main()
