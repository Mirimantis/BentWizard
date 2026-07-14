"""Tests for Apply-Joint (freecad.bentwizard.apply_joint).

FreeCAD-dependent — run with the bundled interpreter; skips under
plain Python. Applies the real library template to fresh timbers and
pins the result to analytic cut volumes and a completely clean lint.
"""

import math
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

TEMPLATE = REPO_ROOT / "library" / "Joint_HousedMT.FCStd"
IN3 = 25.4 ** 3


@unittest.skipUnless(HAVE_FREECAD, "FreeCAD not importable — run with the bundled python")
class ApplyJointTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from freecad.bentwizard.apply_joint import TemplateSpec
        cls.spec = TemplateSpec(TEMPLATE)

    def setUp(self):
        from freecad.bentwizard.timber import new_timber
        self.doc = App.newDocument("ApplyTest")
        self.post, _ = new_timber(self.doc, "P3-1", "10 in", "8 in", "10 ft")
        self.beam, _ = new_timber(self.doc, "B3-1", "6 in", "8 in", "8 ft")
        self.v0 = (self.post.Shape.Volume, self.beam.Shape.Volume)

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def apply(self, joint_id="B3a", **kw):
        from freecad.bentwizard.apply_joint import apply_joint
        return apply_joint(self.doc, self.spec,
                           joint_id, {"P0-1": self.post, "B0-1": self.beam},
                           **kw)

    def cuts(self):
        return ((self.v0[0] - self.post.Shape.Volume) / IN3,
                (self.v0[1] - self.beam.Shape.Volume) / IN3)

    def test_analytic_cut_volumes(self):
        # housing 6x8x0.5 + mortise 2x6x4.25 + 1"-dia bore through the
        # 8" post depth minus its passage through the 2" mortise void;
        # beam: 6x8x4 end slab minus the 2x6x4 tenon island, plus the
        # drawbore through the 2" tenon thickness.
        self.apply()
        post_cut, beam_cut = self.cuts()
        bore = math.pi * 0.25
        self.assertAlmostEqual(post_cut, 24 + 51 + bore * 8 - bore * 2, places=3)
        self.assertAlmostEqual(beam_cut, 144 + bore * 2, places=3)

    def test_renamed_body_binds_its_actual_dims_varset(self):
        # The live bug: body renamed after creation, its Dims VarSet
        # keeping the old label. The junction bindings must resolve the
        # ACTUAL VarSet structurally, and keep tracking it.
        self.beam.Label = "Beam Renamed"
        vs = self.apply()
        engine = {p.lstrip("."): e for p, e in vs.ExpressionEngine}
        self.assertIn("<<TimberDims_B3-1>>", engine["Housing_Width"])
        cut0, _ = self.cuts()
        self.doc.getObjectsByLabel("TimberDims_B3-1")[0].Width = "8 in"
        self.doc.recompute()
        cut1, _ = self.cuts()
        self.assertGreater(cut1, cut0)

    def test_junction_binding_tracks_mating_timber(self):
        self.apply()
        cut0, _ = self.cuts()
        dims = self.doc.getObjectsByLabel("TimberDims_B3-1")[0]
        dims.Width = "8 in"                     # widen the beam
        self.doc.recompute()
        cut1, _ = self.cuts()
        self.assertGreater(cut1, cut0)          # housing widened with it

    def test_station_override_places_joint(self):
        vs = self.apply(values={"Joint_Station": App.Units.Quantity("20 in")})
        self.assertAlmostEqual(vs.Joint_Station.Value, 508.0, places=6)
        post_cut, _ = self.cuts()
        self.assertGreater(post_cut, 70)        # cuts landed inside the stick

    def test_two_instances_coexist_and_ids_collide(self):
        from freecad.bentwizard.apply_joint import JointError
        self.apply("B3a", values={"Joint_Station": App.Units.Quantity("60 in")})
        self.apply("B3b", values={"Joint_Station": App.Units.Quantity("20 in")})
        with self.assertRaises(JointError):
            self.apply("B3a")

    def _end_slab(self, at_b):
        """Remaining beam volume (in^3) in the 4-in slab at one end."""
        import Part
        L = 96 * 25.4
        z0 = L - 4 * 25.4 if at_b else 0.0
        box = Part.makeBox(6 * 25.4, 8 * 25.4, 4 * 25.4,
                           App.Vector(0, 0, z0))
        return self.beam.Shape.common(box).Volume / IN3

    def test_end_b_tenon(self):
        import math
        self.apply(placement={"B0-1": {"end": "B"}})
        _, beam_cut = self.cuts()
        self.assertAlmostEqual(beam_cut, 144 + math.pi * 0.25 * 2, places=3)
        # end A untouched; end B slab = tenon minus its drawbore passage
        self.assertAlmostEqual(self._end_slab(False), 6 * 8 * 4, places=3)
        self.assertAlmostEqual(self._end_slab(True),
                               48 - math.pi * 0.25 * 2, places=3)

    def test_both_ends_of_one_beam(self):
        import math
        self.apply("B3a", values={"Joint_Station": App.Units.Quantity("60 in")})
        self.apply("B3b", values={"Joint_Station": App.Units.Quantity("20 in")},
                   placement={"B0-1": {"end": "B"}})
        _, beam_cut = self.cuts()
        self.assertAlmostEqual(beam_cut, 2 * (144 + math.pi * 0.25 * 2),
                               places=3)

    def test_end_b_output_lints_clean(self):
        from freecad.bentwizard.linter import lint
        self.apply(placement={"B0-1": {"end": "B"}})
        with tempfile.TemporaryDirectory() as td:
            path = str(Path(td) / "endb.FCStd")
            self.doc.saveAs(path)
            self.assertEqual([str(f) for f in lint(path)], [])

    def test_end_b_only_for_end_landing_roles(self):
        from freecad.bentwizard.apply_joint import JointError
        with self.assertRaises(JointError):
            self.apply(placement={"P0-1": {"end": "B"}})

    def _face_slabs(self):
        """Remaining post material (in^3) in a thin slab at each face."""
        import Part
        t = 0.4 * 25.4               # thinner than the 0.5 in housing
        W, D, L = 10 * 25.4, 8 * 25.4, 120 * 25.4
        boxes = {
            1: Part.makeBox(W, t, L, App.Vector(0, 0, 0)),
            2: Part.makeBox(t, D, L, App.Vector(0, 0, 0)),
            3: Part.makeBox(W, t, L, App.Vector(0, D - t, 0)),
            4: Part.makeBox(t, D, L, App.Vector(W - t, 0, 0)),
        }
        intact = {1: 10 * 0.4 * 120, 2: 8 * 0.4 * 120,
                  3: 10 * 0.4 * 120, 4: 8 * 0.4 * 120}
        return {f: intact[f] - self.post.Shape.common(b).Volume / IN3
                for f, b in boxes.items()}   # material LOST at each face

    def test_each_face_carries_the_joint(self):
        import math
        for face in (1, 2, 3, 4):
            with self.subTest(face=face):
                vs = self.apply(f"F{face}",
                                placement={"P0-1": {"face": face}})
                post_cut, _ = self.cuts()
                slabs = self._face_slabs()
                self._remove_joint(vs, f"MT_F{face}")   # before asserts
                # the peg bore crosses the across-face extent: the 10 in
                # Width on faces 1/3, the 8 in Depth on faces 2/4
                bore_len = 10 if face in (1, 3) else 8
                expected = (24 + 51 + math.pi * 0.25 * bore_len
                            - math.pi * 0.25 * 2)
                self.assertAlmostEqual(post_cut, expected, places=3)
                self.assertEqual(max(slabs, key=slabs.get), face,
                                 f"housing did not land on face {face}: {slabs}")

    def _remove_joint(self, varset, tag):
        self.doc.removeObject(varset.Name)
        for body in (self.post, self.beam):
            for o in reversed(list(body.Group)):   # dependents first
                if tag in o.Label:
                    self.doc.removeObject(o.Name)
        self.doc.recompute()

    def _mortise_probe(self, face):
        """Material (in^3) at the expected mortise void and at its
        across-face mirror, for an asymmetric Tenon_Setback_Face2."""
        import Part
        IN = 25.4
        span = (61.5 * IN, 66.5 * IN)            # inside the 6in-high mortise
        depth = {1: (1 * IN, 4 * IN), 2: (1 * IN, 4 * IN),
                 3: (4 * IN, 7 * IN), 4: (6 * IN, 9 * IN)}[face]
        # footprint is centered across the face ((extent - 6)/2 offset),
        # and the asymmetric 1 in setback puts the 2 in mortise 1..3 in
        # from the footprint's low-coordinate edge
        across_lo = {1: (3 * IN, 5 * IN), 3: (3 * IN, 5 * IN),
                     2: (2 * IN, 4 * IN), 4: (2 * IN, 4 * IN)}[face]
        across_hi = (self._across_extent(face) - across_lo[1],
                     self._across_extent(face) - across_lo[0])

        def box(depth_rng, across_rng):
            (d0, d1), (a0, a1) = depth_rng, across_rng
            if face in (2, 4):     # depth along X, across along Y
                return Part.makeBox(d1 - d0, a1 - a0, span[1] - span[0],
                                    App.Vector(d0, a0, span[0]))
            return Part.makeBox(a1 - a0, d1 - d0, span[1] - span[0],
                                App.Vector(a0, d0, span[0]))

        expected = self.post.Shape.common(box(depth, across_lo)).Volume / IN3
        mirror = self.post.Shape.common(box(depth, across_hi)).Volume / IN3
        return expected, mirror

    @staticmethod
    def _across_extent(face):
        return (10 * 25.4) if face in (1, 3) else (8 * 25.4)

    def test_asymmetric_mortise_lands_on_the_correct_side(self):
        # Symmetric defaults cannot detect mirror errors; skew the tenon
        # 1 in off the footprint edge and check the void is where square
        # rule says, on a flip_z face (2) and a swapped family face (3).
        for face in (2, 3):
            with self.subTest(face=face):
                vs = self.apply(
                    f"S{face}",
                    values={"Joint_Station": App.Units.Quantity("60 in"),
                            "Tenon_Setback_Face2": App.Units.Quantity("1 in")},
                    placement={"P0-1": {"face": face}})
                expected, mirror = self._mortise_probe(face)
                self.assertAlmostEqual(expected, 0.0, places=3,
                                       msg=f"face {face}: mortise void missing")
                self.assertGreater(mirror, 25,
                                   msg=f"face {face}: mortise mirrored")
                self._remove_joint(vs, f"MT_S{face}")

    def test_mirrored_hand_swaps_the_mortise_side(self):
        # §4.6 handed mate: same asymmetric setback, hand mirrored — the
        # void and material sides of the probe must swap relative to the
        # test above, on the template face and on a flip_z face.
        for face in (4, 2):
            with self.subTest(face=face):
                vs = self.apply(
                    f"H{face}",
                    values={"Joint_Station": App.Units.Quantity("60 in"),
                            "Tenon_Setback_Face2": App.Units.Quantity("1 in")},
                    placement={"P0-1": {"face": face, "hand": "mirrored"}})
                expected, mirror = self._mortise_probe(face)
                self._remove_joint(vs, f"MT_H{face}")
                self.assertGreater(expected, 25,
                                   msg=f"face {face}: mirrored hand cut the "
                                       f"template side")
                self.assertAlmostEqual(mirror, 0.0, places=3,
                                       msg=f"face {face}: mirrored mortise "
                                           f"void missing")

    def test_mirrored_hand_volume_and_lint(self):
        import math
        from freecad.bentwizard.linter import lint
        self.apply(placement={"P0-1": {"hand": "mirrored"}})
        post_cut, _ = self.cuts()
        self.assertAlmostEqual(
            post_cut, 24 + 51 + math.pi * 0.25 * 8 - math.pi * 0.25 * 2,
            places=3)
        with tempfile.TemporaryDirectory() as td:
            path = str(Path(td) / "hand.FCStd")
            self.doc.saveAs(path)
            self.assertEqual([str(f) for f in lint(path)], [])

    def test_hand_only_for_side_landing_roles(self):
        from freecad.bentwizard.apply_joint import JointError
        with self.assertRaises(JointError):
            self.apply(placement={"B0-1": {"hand": "mirrored"}})

    def test_face_only_for_side_landing_roles(self):
        from freecad.bentwizard.apply_joint import JointError
        with self.assertRaises(JointError):
            self.apply(placement={"B0-1": {"face": 2}})

    def test_face_output_lints_clean(self):
        from freecad.bentwizard.linter import lint
        self.apply(placement={"P0-1": {"face": 1}})
        with tempfile.TemporaryDirectory() as td:
            path = str(Path(td) / "face1.FCStd")
            self.doc.saveAs(path)
            self.assertEqual([str(f) for f in lint(path)], [])

    def test_oversized_defaults_refused_before_cutting(self):
        # Template defaults (6 in tenon height + 1 in setback) cannot
        # fit a 4 in deep beam: the pre-flight must refuse after the
        # junction bindings resolve, before any geometry is cut.
        from freecad.bentwizard.apply_joint import JointError, apply_joint
        from freecad.bentwizard.timber import new_timber
        small, _ = new_timber(self.doc, "B3-9", "6 in", "4 in", "8 ft")
        v_post = self.post.Shape.Volume
        with self.assertRaises(JointError) as ctx:
            apply_joint(self.doc, self.spec, "B9x",
                        {"P0-1": self.post, "B0-1": small})
        self.assertIn("does not fit", str(ctx.exception))
        self.doc.recompute()
        self.assertAlmostEqual(self.post.Shape.Volume, v_post, places=6)

    def test_remove_joint_restores_the_timbers(self):
        from freecad.bentwizard.apply_joint import remove_joint
        vs = self.apply()
        remove_joint(vs)
        self.assertEqual(self.cuts(), (0.0, 0.0))
        leftovers = [o.Label for o in self.doc.Objects
                     if "MT_B3a" in o.Label]
        self.assertEqual(leftovers, [])
        # the relinked tips must stay visible (the timber looked
        # deleted in the live run)
        self.assertTrue(self.post.Tip.Visibility)
        self.assertTrue(self.beam.Tip.Visibility)

    def test_bad_expression_value_refused(self):
        from freecad.bentwizard.apply_joint import JointError
        with self.assertRaises(JointError):
            self.apply(values={"Joint_Station": "<<Nowhere>>.Missing"})

    def test_remove_one_joint_leaves_the_other_untouched(self):
        # the live accident: cleaning up one joint by hand deleted parts
        # of another
        import math
        from freecad.bentwizard.apply_joint import remove_joint
        vs_a = self.apply("B3a", values={"Joint_Station":
                                         App.Units.Quantity("60 in")})
        self.apply("B3b", values={"Joint_Station":
                                  App.Units.Quantity("20 in")},
                   placement={"B0-1": {"end": "B"}})
        remove_joint(vs_a)
        post_cut, beam_cut = self.cuts()
        self.assertAlmostEqual(post_cut,
                               24 + 51 + math.pi * 0.25 * 8
                               - math.pi * 0.25 * 2, places=3)
        self.assertAlmostEqual(beam_cut, 144 + math.pi * 0.25 * 2, places=3)
        self.assertTrue(any("MT_B3b" in o.Label for o in self.doc.Objects))
        self.assertFalse(any("MT_B3a" in o.Label for o in self.doc.Objects))

    def test_expression_values_bind(self):
        # a string value is applied as an expression: bind Joint_Station
        # to a project-level VarSet at apply time
        proj = self.doc.addObject("App::VarSet", "ProjectVars")
        proj.Label = "Project_Main"
        proj.addProperty("App::PropertyLength", "Tie_Height", "Project", "t")
        proj.Tie_Height = "60 in"
        vs = self.apply(values={"Joint_Station": "<<Project_Main>>.Tie_Height"})
        self.assertAlmostEqual(vs.Joint_Station.Value, 60 * 25.4, places=6)
        proj.Tie_Height = "50 in"
        self.doc.recompute()
        self.assertAlmostEqual(vs.Joint_Station.Value, 50 * 25.4, places=6)

    def test_engagement_seats_the_mate_frame(self):
        # the seated pose must make the beam's mate frame coincide with
        # the post's landing frame, regardless of the beam's current pose
        from freecad.bentwizard.apply_joint import engagement_placement
        vs = self.apply()
        self.beam.Placement = App.Placement(
            App.Vector(123, -45, 67),
            App.Rotation(App.Vector(1, 2, 3), 37))     # arbitrary pose
        self.doc.recompute()
        mover, anchor, seated = engagement_placement(vs)
        self.assertIs(mover, self.beam)
        self.assertIs(anchor, self.post)
        mover.Placement = seated
        self.doc.recompute()
        landing = self.doc.getObjectsByLabel(
            "P3-1_JointFrame_MT_B3a")[0].getGlobalPlacement()
        mate = self.doc.getObjectsByLabel(
            "B3-1_MateFrame_MT_B3a")[0].getGlobalPlacement()
        self.assertLess(mate.Base.sub(landing.Base).Length, 1e-6)
        # axes coincide too (not just origins)
        for v in (App.Vector(1, 0, 0), App.Vector(0, 1, 0)):
            self.assertLess(
                mate.Rotation.multVec(v).sub(landing.Rotation.multVec(v)).Length,
                1e-6)

    def test_engagement_none_without_mate_frame(self):
        # a joint whose mate frame was removed (older joints) → no pose
        from freecad.bentwizard.apply_joint import engagement_placement
        vs = self.apply()
        mate = self.doc.getObjectsByLabel("B3-1_MateFrame_MT_B3a")[0]
        self.doc.removeObject(mate.Name)
        self.doc.recompute()
        self.assertIsNone(engagement_placement(vs))

    def test_preview_ghosts_secondary_seated_in_real_primary(self):
        from freecad.bentwizard.apply_joint import (create_preview,
                                                    find_preview,
                                                    remove_preview)
        vs = self.apply()
        post_pose = self.post.Placement.copy()
        beam_pose = self.beam.Placement.copy()
        group = create_preview(vs)
        self.assertIsNotNone(group)
        links = list(group.Group)
        # one ghost — the secondary (beam), the mate-frame carrier
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0].TypeId, "App::Link")
        self.assertIs(links[0].getLinkedObject(), self.beam)
        # placements never touched (finding #11)
        self.assertEqual(self.post.Placement.Base, post_pose.Base)
        self.assertEqual(self.beam.Placement.Base, beam_pose.Base)
        # real secondary hidden, primary stays visible
        self.assertFalse(self.beam.Visibility)
        self.assertTrue(self.post.Visibility)
        # clearing restores the secondary's visibility
        remove_preview(group)
        self.assertTrue(self.beam.Visibility)
        self.assertIsNone(find_preview(vs))

    def test_preview_idempotent(self):
        from freecad.bentwizard.apply_joint import create_preview, find_preview
        vs = self.apply()
        create_preview(vs)
        create_preview(vs)                          # replaces, not duplicates
        groups = [o for o in self.doc.Objects
                  if o.Label == f"Preview_{vs.Label}"]
        self.assertEqual(len(groups), 1)
        self.assertEqual(find_preview(vs), groups[0])
        self.assertFalse(self.beam.Visibility)      # still hidden, not double

    def test_preview_none_without_mate_frame(self):
        from freecad.bentwizard.apply_joint import create_preview
        vs = self.apply()
        mate = self.doc.getObjectsByLabel("B3-1_MateFrame_MT_B3a")[0]
        self.doc.removeObject(mate.Name)
        self.doc.recompute()
        self.assertIsNone(create_preview(vs))

    def test_placement_record_written(self):
        vs = self.apply(placement={"P0-1": {"face": 2, "hand": "mirrored"},
                                   "B0-1": {"end": "B"}})
        self.assertEqual(
            vs.Placement_Record,
            "P0-1 -> P3-1: face 2, hand mirrored; B0-1 -> B3-1: end B")

    def test_output_lints_completely_clean(self):
        from freecad.bentwizard.linter import lint
        self.apply()
        with tempfile.TemporaryDirectory() as td:
            path = str(Path(td) / "applied.FCStd")
            self.doc.saveAs(path)
            self.assertEqual([str(f) for f in lint(path)], [])


if __name__ == "__main__":
    unittest.main()
