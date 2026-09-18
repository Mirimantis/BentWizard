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

    def test_structural_not_label_matched(self):
        from freecad.bentwizard import joint_handle
        h = joint_handle.find_handle(self.vs)
        h.Label = "Whatever"
        self.assertIs(joint_handle.find_handle(self.vs), h)
        self.assertTrue(joint_handle.is_handle(h))

    def test_files_into_the_bent(self):
        from freecad.bentwizard import joint_handle
        from freecad.bentwizard.assemble import assimilate_joint, container_assembly
        assimilate_joint(self.doc, self.vs)
        h = joint_handle.find_handle(self.vs)
        group = h.getParentGroup()
        bent = container_assembly(self.post)
        self.assertEqual(group.Label, f"TimberJoints_{bent.Label}")
        self.assertIs(group.getParentGeoFeatureGroup(), bent)
        self.assertEqual([o for o in self.doc.Objects
                          if o.TypeId == "App::DocumentObjectGroup"
                          and o.Label == "TimberJoints"], [])

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
