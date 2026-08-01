"""Tests for the per-joint handle (joint_handle.py).

FreeCAD-dependent — run with the bundled interpreter; skips under plain
Python. The GUI half (the marker ViewProvider) is not exercised here:
these cover the App side, which is what has to survive without a GUI and
without the workbench.
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


@unittest.skipUnless(HAVE_FREECAD, "FreeCAD not importable — run with the bundled python")
class JointHandleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from freecad.bentwizard.apply_joint import TemplateSpec
        cls.spec = TemplateSpec(TEMPLATE)

    def setUp(self):
        self.doc = App.newDocument("HandleTest")

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def timber(self, label, w="8 in", d="8 in", length="8 ft"):
        from freecad.bentwizard.timber import new_timber
        body, _dims = new_timber(self.doc, label, w, d, length)
        return body

    def joint(self, jid, post, beam, face=4, end="A"):
        from freecad.bentwizard.apply_joint import apply_joint
        return apply_joint(self.doc, self.spec, jid,
                           {"T.Post.001": post, "T.AnchorBeam.001": beam},
                           placement={"T.Post.001": {"face": face},
                                      "T.AnchorBeam.001": {"end": end}})

    def pi_bent(self, tag="1"):
        from freecad.bentwizard.assemble import assimilate_joint
        post1 = self.timber(f"P{tag}-1")
        post2 = self.timber(f"P{tag}-2")
        beam = self.timber(f"B{tag}-1", "6 in", "8 in", "10 ft")
        j1 = self.joint(f"{tag}a", post1, beam, face=4, end="A")
        j2 = self.joint(f"{tag}b", post2, beam, face=2, end="B")
        assimilate_joint(self.doc, j1)
        assimilate_joint(self.doc, j2)
        return post1, post2, beam, j1, j2

    def groups(self):
        return {o.Label for o in self.doc.Objects
                if o.TypeId == "App::DocumentObjectGroup"}

    # --- creation ------------------------------------------------------

    def test_apply_joint_creates_a_handle_for_the_varset(self):
        from freecad.bentwizard.joint_handle import (find_handle,
                                                     handle_varset)
        post = self.timber("P1-1")
        beam = self.timber("B1-1", "6 in", "8 in", "8 ft")
        vs = self.joint("1a", post, beam)
        handle = find_handle(vs)
        self.assertIsNotNone(handle)
        self.assertEqual(handle.TypeId, "App::FeaturePython")
        self.assertEqual(handle.Label, "Handle_J-HousedMT-1a")
        self.assertIs(handle_varset(handle), vs)
        self.assertIs(handle.Joint, vs)

    def test_varset_nests_under_its_handle(self):
        """One node per joint: the handle holds its parameters, so the
        VarSet travels with it between bents. (The tree only DRAWS this
        when the view provider carries Gui::ViewProviderGroupExtension —
        the App-side Group alone left the VarSet at container level.)"""
        from freecad.bentwizard.joint_handle import find_handle
        _p1, _p2, _beam, j1, _j2 = self.pi_bent()
        handle = find_handle(j1)
        self.assertIn(j1, list(handle.Group))
        self.assertIs(j1.getParentGroup(), handle)

    def test_a_varset_dragged_beside_its_handle_stays_there(self):
        """Re-filing must not fight the user's tree arrangement."""
        from freecad.bentwizard.joint_handle import ensure_handle, find_handle
        _p1, _p2, _beam, j1, _j2 = self.pi_bent()
        handle = find_handle(j1)
        group = handle.getParentGroup()
        group.addObject(j1)                        # the user drags it out
        ensure_handle(j1)
        self.assertIs(j1.getParentGroup(), group)
        # the joint VarSet stays where the user put it; the companion
        # layout VarSet (when the template declares one) is a separate
        # member and legitimately stays nested under the handle
        self.assertNotIn(j1, list(handle.Group))

    def test_a_varset_that_drifted_out_of_the_folder_is_refiled(self):
        from freecad.bentwizard.joint_handle import ensure_handle, find_handle
        _p1, _p2, _beam, j1, _j2 = self.pi_bent()
        stray = self.doc.addObject("App::DocumentObjectGroup", "Elsewhere")
        stray.addObject(j1)
        ensure_handle(j1)
        self.assertIs(j1.getParentGroup(), find_handle(j1))

    def test_the_joint_link_is_structural_not_label_matched(self):
        """A renamed handle must still resolve — the project has been
        bitten twice by name-matched bindings."""
        from freecad.bentwizard.joint_handle import find_handle
        _p1, _p2, _beam, j1, _j2 = self.pi_bent()
        handle = find_handle(j1)
        handle.Label = "Whatever the user typed"
        self.assertIs(find_handle(j1), handle)

    def test_a_handle_without_the_joint_link_still_resolves(self):
        """Handles built before the Joint link keep working: the VarSet
        is found through the group, and the next ensure_handle adds the
        link."""
        from freecad.bentwizard.joint_handle import (ensure_handle,
                                                     find_handle,
                                                     handle_varset)
        _p1, _p2, _beam, j1, _j2 = self.pi_bent()
        handle = find_handle(j1)
        handle.removeProperty("Joint")
        self.assertIs(handle_varset(handle), j1)   # found via the group
        self.assertIs(find_handle(j1), handle)
        ensure_handle(j1)
        self.assertIs(handle.Joint, j1)
        self.assertIs(j1.getParentGroup(), handle)

    def test_handle_carries_no_app_proxy(self):
        """Tier 2: nothing to import when the workbench is absent. An
        App-level Proxy would make the object depend on this code."""
        from freecad.bentwizard.joint_handle import find_handle
        post = self.timber("P1-1")
        beam = self.timber("B1-1", "6 in", "8 in", "8 ft")
        handle = find_handle(self.joint("1a", post, beam))
        self.assertIsNone(getattr(handle, "Proxy", None))
        self.assertTrue(handle.hasExtension("App::GroupExtension"))

    def test_frame_points_at_the_anchor_landing_frame(self):
        from freecad.bentwizard.apply_joint import joint_role_frames
        from freecad.bentwizard.joint_handle import find_handle
        post = self.timber("P1-1")
        beam = self.timber("B1-1", "6 in", "8 in", "8 ft")
        vs = self.joint("1a", post, beam)
        frames = joint_role_frames(vs)
        # the anchor is the half that receives and never enters
        anchor = next(b for b, f in frames.items()
                      if f["landing"] and not f["mate"])
        self.assertIs(find_handle(vs).Frame, frames[anchor]["landing"])

    # --- tree home ------------------------------------------------------

    def test_handle_files_in_its_bents_group(self):
        from freecad.bentwizard.assemble import container_assembly
        from freecad.bentwizard.joint_handle import find_handle
        post1, _post2, _beam, j1, j2 = self.pi_bent()
        bent = container_assembly(post1)
        group = find_handle(j1).getParentGroup()
        self.assertEqual(group.Label, f"TimberJoints_{bent.Label}")
        self.assertIs(group.getParentGeoFeatureGroup(), bent)
        self.assertIs(find_handle(j2).getParentGroup(), group)
        for vs in (j1, j2):                       # VarSets ride along
            self.assertIs(vs.getParentGroup(), find_handle(vs))
        # the root group was left behind empty by nobody
        self.assertNotIn("TimberJoints", self.groups())

    def test_cross_bent_joint_files_in_the_frame(self):
        """A joint spanning two bents belongs to the frame — the same
        container rule its Fixed assembly joint follows."""
        from freecad.bentwizard.assemble import (assimilate_joint,
                                                 container_assembly,
                                                 find_fixed_joint)
        from freecad.bentwizard.joint_handle import find_handle
        post1, _p2, _b1, _j1, _j2 = self.pi_bent("1")
        post3, _p4, _b2, _j3, _j4 = self.pi_bent("2")
        tie = self.timber("TIE-1", "6 in", "8 in", "12 ft")
        ta = self.joint("3a", post1, tie, face=1, end="A")
        tb = self.joint("3b", post3, tie, face=3, end="B")
        assimilate_joint(self.doc, ta)
        assimilate_joint(self.doc, tb)
        for vs in (ta, tb):
            home = container_assembly(find_fixed_joint(self.doc, vs))
            group = find_handle(vs).getParentGroup()
            self.assertEqual(group.Label, f"TimberJoints_{home.Label}",
                             f"{vs.Label} handle filed away from its joint")
            self.assertIs(group.getParentGeoFeatureGroup(), home)

    def test_handle_follows_its_joint_into_a_new_container(self):
        """Assimilation moves joints between assemblies; the handle
        re-files rather than accumulating."""
        from freecad.bentwizard.assemble import (assimilate_joint,
                                                 container_assembly)
        from freecad.bentwizard.joint_handle import find_handle
        post = self.timber("P1-1")
        beam = self.timber("B1-1", "6 in", "8 in", "8 ft")
        vs = self.joint("1a", post, beam)
        self.assertEqual(find_handle(vs).getParentGroup().Label,
                         "TimberJoints")           # loose: root group
        assimilate_joint(self.doc, vs)
        bent = container_assembly(post)
        self.assertEqual(find_handle(vs).getParentGroup().Label,
                         f"TimberJoints_{bent.Label}")
        self.assertNotIn("TimberJoints", self.groups())
        handles = [o for o in self.doc.Objects
                   if o.Label.startswith("Handle_")]
        self.assertEqual(len(handles), 1)

    # --- removal and adoption -------------------------------------------

    def test_remove_joint_removes_the_handle(self):
        from freecad.bentwizard.apply_joint import remove_joint
        from freecad.bentwizard.joint_handle import find_handle
        post1, _post2, _beam, j1, _j2 = self.pi_bent()
        handle_name = find_handle(j1).Name
        remove_joint(j1)
        self.assertIsNone(self.doc.getObject(handle_name))
        self.assertEqual(
            [o for o in self.doc.Objects if o.Label.startswith("Handle_")],
            [o for o in self.doc.Objects if o.Label == "Handle_J-HousedMT-1b"])

    def test_adopt_handles_is_idempotent_and_restores(self):
        from freecad.bentwizard.joint_handle import adopt_handles, find_handle
        _p1, _p2, _beam, j1, j2 = self.pi_bent()
        self.assertEqual(adopt_handles(self.doc), 0)     # nothing owed
        # a pre-handle document: the joint exists, the handle does not
        handle = find_handle(j1)
        group = handle.getParentGroup()
        group.removeObject(handle)
        self.doc.removeObject(handle.Name)
        self.assertIsNone(find_handle(j1))
        self.assertEqual(adopt_handles(self.doc), 1)
        self.assertIsNotNone(find_handle(j1))
        self.assertIs(find_handle(j2).getParentGroup(),
                      find_handle(j1).getParentGroup())
        self.assertEqual(adopt_handles(self.doc), 0)

    def test_assemble_timbers_adopts_doc_wide(self):
        from freecad.bentwizard.assemble import assemble_timbers
        from freecad.bentwizard.joint_handle import find_handle
        post1, post2, beam, j1, j2 = self.pi_bent()
        for vs in (j1, j2):
            handle = find_handle(vs)
            handle.getParentGroup().removeObject(handle)
            self.doc.removeObject(handle.Name)
        _asm, _skipped, _misfits, adopted = assemble_timbers(
            self.doc, [post1, post2, beam])
        self.assertEqual(adopted, 2)
        self.assertIsNotNone(find_handle(j1))
        self.assertIsNotNone(find_handle(j2))

    def test_deleting_a_handle_keeps_the_varset(self):
        """The marker is not the joint: losing it leaves the joint's
        parameters behind in the bent's folder, not orphaned with it."""
        from freecad.bentwizard.joint_handle import find_handle, remove_handle
        _p1, _p2, _beam, j1, _j2 = self.pi_bent()
        group = find_handle(j1).getParentGroup()
        self.assertTrue(remove_handle(j1))
        self.assertIsNone(find_handle(j1))
        self.assertIsNotNone(self.doc.getObject(j1.Name))
        self.assertIs(j1.getParentGroup(), group)
        self.assertFalse(remove_handle(j1))

    # --- the document as a whole -----------------------------------------

    def test_handles_survive_a_save_and_reload(self):
        from freecad.bentwizard.assemble import joint_misfit
        from freecad.bentwizard.joint_handle import find_handle
        self.pi_bent()
        with tempfile.TemporaryDirectory() as td:
            path = str(Path(td) / "handles.FCStd")
            self.doc.saveAs(path)
            App.closeDocument(self.doc.Name)
            self.doc = App.openDocument(path)
            self.doc.recompute()
            self.assertEqual(
                [o.Label for o in self.doc.Objects if "Invalid" in o.State],
                [])
            for vs in self.doc.Objects:
                if not vs.Label.startswith("J-"):
                    continue
                handle = find_handle(vs)
                self.assertIsNotNone(handle, vs.Label)
                self.assertTrue(handle.hasExtension("App::GroupExtension"))
                self.assertIsNotNone(handle.Frame)
                self.assertLess(joint_misfit(vs)[0], 1e-6, vs.Label)

    def test_output_lints_completely_clean(self):
        """The acceptance bar: handles add no lint noise, strict or
        advisory, in an assembled document."""
        from freecad.bentwizard.linter import lint
        self.pi_bent()
        with tempfile.TemporaryDirectory() as td:
            path = str(Path(td) / "handles.FCStd")
            self.doc.saveAs(path)
            self.assertEqual([str(f) for f in lint(path)], [])


if __name__ == "__main__":
    unittest.main()
