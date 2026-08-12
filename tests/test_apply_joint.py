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
import _repo_path  # noqa: E402 — this repo's code must win the import

try:
    import FreeCAD as App
    _repo_path.graft()   # FreeCAD's init grafts the Mod copy; ours first
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
                           joint_id, {"T.Post.001": self.post, "T.AnchorBeam.001": self.beam},
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
        self.assertIn("<<TDim_B3-1>>", engine["Housing_Width"])
        cut0, _ = self.cuts()
        self.doc.getObjectsByLabel("TDim_B3-1")[0].Width = "8 in"
        self.doc.recompute()
        cut1, _ = self.cuts()
        self.assertGreater(cut1, cut0)

    def test_junction_binding_tracks_mating_timber(self):
        self.apply()
        cut0, _ = self.cuts()
        dims = self.doc.getObjectsByLabel("TDim_B3-1")[0]
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
        self.apply(placement={"T.AnchorBeam.001": {"end": "B"}})
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
                   placement={"T.AnchorBeam.001": {"end": "B"}})
        _, beam_cut = self.cuts()
        self.assertAlmostEqual(beam_cut, 2 * (144 + math.pi * 0.25 * 2),
                               places=3)

    def test_end_b_output_lints_clean(self):
        from freecad.bentwizard.linter import lint
        self.apply(placement={"T.AnchorBeam.001": {"end": "B"}})
        with tempfile.TemporaryDirectory() as td:
            path = str(Path(td) / "endb.FCStd")
            self.doc.saveAs(path)
            self.assertEqual([str(f) for f in lint(path)], [])

    def test_end_b_only_for_end_landing_roles(self):
        from freecad.bentwizard.apply_joint import JointError
        with self.assertRaises(JointError):
            self.apply(placement={"T.Post.001": {"end": "B"}})

    def test_datums_rebuilt_before_dependents(self):
        # Regression (wedged half-dovetail cheeks not cut): a sketch may
        # attach to a frame authored AFTER it (a mate frame added once
        # the cheeks were cut). The rebuilder must create every datum
        # before the sketches/features that hang off them, or the
        # attachment resolves to a body origin plane by name and the cut
        # lands at the origin. TemplateSpec hoists datums to the front of
        # each role stack; the MT beam authors its mate frame and a
        # shoulder datum after the tenon sketch, so it exercises this.
        def is_datum(s):
            return s["type_id"].startswith(
                ("Part::LocalCoordinateSystem", "Part::Datum"))
        for role, stack in self.spec.roles.items():
            kinds = [is_datum(s) for s in stack]
            last_datum = max((i for i, d in enumerate(kinds) if d),
                             default=-1)
            first_feature = next((i for i, d in enumerate(kinds) if not d),
                                 len(kinds))
            self.assertLess(last_datum, first_feature,
                            f"{role}: a datum follows a feature in the "
                            f"rebuild order — dependents would miss it")

    def test_template_metadata_defaults(self):
        # the shipped template declares Template_Handed True (hand stays
        # offered, as it was when the flag was absent) and no angle bounds
        self.assertTrue(self.spec.handed)
        self.assertIsNone(self.spec.angle_min)
        self.assertIsNone(self.spec.angle_max)

    def test_mate_flip_composes_authored_rotation(self):
        from freecad.bentwizard.apply_joint import mate_flip_rotation
        V = App.Vector

        def axes(rot):
            return [tuple(round(c, 9) for c in rot.multVec(V(*v)))
                    for v in ((1, 0, 0), (0, 1, 0), (0, 0, 1))]

        # identity mate frame (this template): the plain 180° about Y
        self.assertEqual(axes(mate_flip_rotation(App.Rotation())),
                         [(-1.0, 0.0, 0.0), (0.0, 1.0, 0.0),
                          (0.0, 0.0, -1.0)])
        # a mate frame authored turned 90° about Z (the housed
        # dovetail): the seated up-axis (mate X -> body +Y) must
        # survive the flip; right-composing would send it to -Y
        turned = mate_flip_rotation(App.Rotation(V(0, 0, 1), 90))
        self.assertEqual(axes(turned),
                         [(0.0, 1.0, 0.0), (1.0, 0.0, 0.0),
                          (0.0, 0.0, -1.0)])

    def _modified_template(self, mutate):
        """A TemplateSpec from a copy of the library template with
        `mutate(joint_varset)` applied — template metadata the shipped
        template does not carry."""
        from freecad.bentwizard import naming
        from freecad.bentwizard.apply_joint import TemplateSpec
        doc = App.openDocument(str(TEMPLATE))
        try:
            vs = next(o for o in doc.Objects
                      if o.TypeId == "App::VarSet"
                      and naming.is_joint_varset_label(o.Label))
            mutate(vs)
            with tempfile.TemporaryDirectory() as td:
                path = str(Path(td) / "modified.FCStd")
                doc.saveAs(path)
                return TemplateSpec(path)
        finally:
            App.closeDocument(doc.Name)

    def _nested_dims_template(self):
        """A TemplateSpec from a copy of the library template whose Dims
        VarSets are nested INSIDE their Bodies — what New Timber
        produces (§3 tree organization). The shipped template predates
        that convention and keeps them at document root, so only this
        arrangement exercises the body-member path."""
        from freecad.bentwizard.apply_joint import TemplateSpec
        doc = App.openDocument(str(TEMPLATE))
        try:
            for body in doc.Objects:
                if body.TypeId != "PartDesign::Body":
                    continue
                for o in doc.Objects:
                    if o.TypeId == "App::VarSet" \
                            and o.Label == f"TDim_{body.Label}":
                        body.addObject(o)
            doc.recompute()
            with tempfile.TemporaryDirectory() as td:
                path = str(Path(td) / "nested.FCStd")
                doc.saveAs(path)
                return TemplateSpec(path)
        finally:
            App.closeDocument(doc.Name)

    def test_body_nested_dims_varset_is_not_cloned(self):
        # Regression (caught on the wedged half-dovetail template): the
        # role stack must skip a body-nested Dims VarSet. Cloning it
        # dropped an empty near-duplicate Dims VarSet into every target
        # timber, which Remove Joint could not clean up.
        from freecad.bentwizard.apply_joint import apply_joint
        spec = self._nested_dims_template()
        for role, stack in spec.roles.items():
            self.assertNotIn("App::VarSet", [s["type_id"] for s in stack],
                             f"{role} stack still clones a VarSet")
        before = {o.Name for o in self.doc.Objects
                  if o.TypeId == "App::VarSet"}
        vs = apply_joint(self.doc, spec, "N1",
                         {"T.Post.001": self.post, "T.AnchorBeam.001": self.beam})
        added = [o for o in self.doc.Objects
                 if o.TypeId == "App::VarSet" and o.Name not in before]
        # the joint's own VarSet, plus its companion layout VarSet when
        # the template declares one — and nothing else, above all no
        # clone of the body-nested Dims VarSet
        from freecad.bentwizard.apply_joint import layout_varset
        expected = [o.Label for o in (layout_varset(vs), vs) if o is not None]
        self.assertEqual([o.Label for o in added], expected,
                         "apply added a VarSet besides the joint's own")
        # and the timbers' real Dims still drive them
        self.assertIsNotNone(self.doc.getObjectsByLabel("TDim_P3-1"))

    def test_template_metadata_is_name_keyed_not_group_keyed(self):
        # Regression: metadata was read from the property GROUP, so a
        # Template_Handed sitting in the 'Joint' group (where the first
        # hand-authored template put it) was silently ignored.
        def mutate(vs):
            # the template now ships Template_Handed in the 'Template'
            # group — drop it so the flag really is read from the 'Joint'
            # group this test is about
            vs.removeProperty("Template_Handed")
            vs.addProperty("App::PropertyBool", "Template_Handed",
                           "Joint", "test: symmetrical joint")
            vs.Template_Handed = False

        spec = self._modified_template(mutate)
        self.assertFalse(spec.handed)
        self.assertTrue(next(p["metadata"] for p in spec.parameters
                             if p["name"] == "Template_Handed"))

    def test_unhanded_template_rejects_mirrored_hand(self):
        from freecad.bentwizard.apply_joint import apply_joint, JointError

        def mutate(vs):
            # shipped as True by the template; this test needs the
            # symmetrical case
            vs.Template_Handed = False

        spec = self._modified_template(mutate)
        self.assertFalse(spec.handed)
        with self.assertRaises(JointError):
            apply_joint(self.doc, spec, "H1",
                        {"T.Post.001": self.post, "T.AnchorBeam.001": self.beam},
                        placement={"T.Post.001": {"hand": "mirrored"}})
        # the template hand still applies
        apply_joint(self.doc, spec, "H2",
                    {"T.Post.001": self.post, "T.AnchorBeam.001": self.beam})

    def test_angle_bounds_clamp_angle_parameters(self):
        from freecad.bentwizard.apply_joint import apply_joint, JointError

        def mutate(vs):
            vs.addProperty("App::PropertyAngle", "Test_Angle", "Joint",
                           "test: an angled-cut parameter")
            vs.Test_Angle = 45
            vs.addProperty("App::PropertyAngle", "Template_Angle_Min",
                           "Template", "test: smallest valid angle")
            vs.Template_Angle_Min = 30
            vs.addProperty("App::PropertyAngle", "Template_Angle_Max",
                           "Template", "test: largest valid angle")
            vs.Template_Angle_Max = 60

        spec = self._modified_template(mutate)
        self.assertEqual((spec.angle_min, spec.angle_max), (30.0, 60.0))
        # in range applies; out of range refused before cutting
        apply_joint(self.doc, spec, "A1",
                    {"T.Post.001": self.post, "T.AnchorBeam.001": self.beam})
        with self.assertRaises(JointError):
            apply_joint(self.doc, spec, "A2",
                        {"T.Post.001": self.post, "T.AnchorBeam.001": self.beam},
                        values={"Test_Angle": App.Units.Quantity("70 deg")})

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
                                placement={"T.Post.001": {"face": face}})
                post_cut, _ = self.cuts()
                slabs = self._face_slabs()
                self._remove_joint(vs)  # before asserts
                # the peg bore crosses the across-face extent: the 10 in
                # Width on faces 1/3, the 8 in Depth on faces 2/4
                bore_len = 10 if face in (1, 3) else 8
                expected = (24 + 51 + math.pi * 0.25 * bore_len
                            - math.pi * 0.25 * 2)
                self.assertAlmostEqual(post_cut, expected, places=3)
                self.assertEqual(max(slabs, key=slabs.get), face,
                                 f"housing did not land on face {face}: {slabs}")

    def _remove_joint(self, varset):
        # members carry the joint's suffix ('.HMT.F2') — ask naming for it
        # rather than spelling a label form here, so this helper cannot
        # silently strip nothing when the scheme changes (it did exactly
        # that during the descriptive-first rework, and the leftover cuts
        # surfaced as an invalid shape two subTests later)
        from freecad.bentwizard import naming
        suffix = naming.joint_suffix_for(
            varset.Label, getattr(varset, naming.TEMPLATE_ABBREV, None))
        self.doc.removeObject(varset.Name)
        removed = 0
        for body in (self.post, self.beam):
            for o in reversed(list(body.Group)):   # dependents first
                if o.Label.endswith(suffix):
                    self.doc.removeObject(o.Name)
                    removed += 1
        self.assertTrue(removed, f"no joint members matched {suffix!r}")
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
                    placement={"T.Post.001": {"face": face}})
                expected, mirror = self._mortise_probe(face)
                self.assertAlmostEqual(expected, 0.0, places=3,
                                       msg=f"face {face}: mortise void missing")
                self.assertGreater(mirror, 25,
                                   msg=f"face {face}: mortise mirrored")
                self._remove_joint(vs)

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
                    placement={"T.Post.001": {"face": face, "hand": "mirrored"}})
                expected, mirror = self._mortise_probe(face)
                self._remove_joint(vs)
                self.assertGreater(expected, 25,
                                   msg=f"face {face}: mirrored hand cut the "
                                       f"template side")
                self.assertAlmostEqual(mirror, 0.0, places=3,
                                       msg=f"face {face}: mirrored mortise "
                                           f"void missing")

    def test_mirrored_hand_volume_and_lint(self):
        import math
        from freecad.bentwizard.linter import lint
        self.apply(placement={"T.Post.001": {"hand": "mirrored"}})
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
            self.apply(placement={"T.AnchorBeam.001": {"hand": "mirrored"}})

    def test_face_only_for_side_landing_roles(self):
        from freecad.bentwizard.apply_joint import JointError
        with self.assertRaises(JointError):
            self.apply(placement={"T.AnchorBeam.001": {"face": 2}})

    def test_face_output_lints_clean(self):
        from freecad.bentwizard.linter import lint
        self.apply(placement={"T.Post.001": {"face": 1}})
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
                        {"T.Post.001": self.post, "T.AnchorBeam.001": small})
        self.assertIn("does not fit", str(ctx.exception))
        self.doc.recompute()
        self.assertAlmostEqual(self.post.Shape.Volume, v_post, places=6)

    def test_remove_joint_restores_the_timbers(self):
        from freecad.bentwizard.apply_joint import remove_joint
        vs = self.apply()
        remove_joint(vs)
        self.assertEqual(self.cuts(), (0.0, 0.0))
        leftovers = [o.Label for o in self.doc.Objects
                     if "J-HousedMT-B3a" in o.Label]
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
                   placement={"T.AnchorBeam.001": {"end": "B"}})
        remove_joint(vs_a)
        post_cut, beam_cut = self.cuts()
        self.assertAlmostEqual(post_cut,
                               24 + 51 + math.pi * 0.25 * 8
                               - math.pi * 0.25 * 2, places=3)
        self.assertAlmostEqual(beam_cut, 144 + math.pi * 0.25 * 2, places=3)
        self.assertTrue(any("J-HousedMT-B3b" in o.Label
                            for o in self.doc.Objects))
        self.assertFalse(any("J-HousedMT-B3a" in o.Label
                             for o in self.doc.Objects))

    def test_expression_values_bind(self):
        # an '='-prefixed string is applied as an expression: bind
        # Joint_Station to a project-level VarSet at apply time
        proj = self.doc.addObject("App::VarSet", "ProjectVars")
        proj.Label = "Project_Main"
        proj.addProperty("App::PropertyLength", "Tie_Height", "Project", "t")
        proj.Tie_Height = "60 in"
        vs = self.apply(values={"Joint_Station": "=<<Project_Main>>.Tie_Height"})
        self.assertAlmostEqual(vs.Joint_Station.Value, 60 * 25.4, places=6)
        proj.Tie_Height = "50 in"
        self.doc.recompute()
        self.assertAlmostEqual(vs.Joint_Station.Value, 50 * 25.4, places=6)

    def test_plain_string_value_is_a_literal_not_an_expression(self):
        """Regression: every string used to become an expression, so a
        plain '5 in' silently bound the property to the expression
        `5 in` — the right number, but unwritable ever after, which is
        exactly how it hid."""
        vs = self.apply(values={"Joint_Station": "5 in"})
        self.assertAlmostEqual(vs.Joint_Station.Value, 5 * 25.4, places=6)
        self.assertNotIn("Joint_Station",
                         [p.lstrip(".") for p, _e in vs.ExpressionEngine],
                         "a literal value left the property expression-bound")
        vs.Joint_Station = "7 in"          # and it must still be writable
        self.doc.recompute()
        self.assertAlmostEqual(vs.Joint_Station.Value, 7 * 25.4, places=6)

    def test_empty_expression_is_refused(self):
        from freecad.bentwizard.apply_joint import JointError
        with self.assertRaises(JointError):
            self.apply(values={"Joint_Station": "="})

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
            "Mortise.Lcs.HMT.B3a")[0].getGlobalPlacement()
        mate = self.doc.getObjectsByLabel(
            "Mate.Lcs.HMT.B3a")[0].getGlobalPlacement()
        self.assertLess(mate.Base.sub(landing.Base).Length, 1e-6)
        # axes coincide too (not just origins)
        for v in (App.Vector(1, 0, 0), App.Vector(0, 1, 0)):
            self.assertLess(
                mate.Rotation.multVec(v).sub(landing.Rotation.multVec(v)).Length,
                1e-6)

    def _seated_interference(self, vs):
        """Seat the mover per engagement and return (interference in^3,
        mover-extends-out-of-primary bool). Non-destructive."""
        from freecad.bentwizard.apply_joint import engagement_placement
        mover, anchor, seated = engagement_placement(vs)
        orig = mover.Placement
        mover.Placement = seated
        self.doc.recompute()
        inter = anchor.Shape.common(mover.Shape).Volume / IN3
        mb, ab = mover.Shape.BoundBox, anchor.Shape.BoundBox
        # the mover must reach out past the primary somewhere, not sit
        # entirely inside / driving through it
        extends_out = (mb.XMax > ab.XMax + 25 or mb.XMin < ab.XMin - 25 or
                       mb.YMax > ab.YMax + 25 or mb.YMin < ab.YMin - 25)
        mover.Placement = orig
        self.doc.recompute()
        return inter, extends_out

    def test_engagement_seats_without_interference_both_ends(self):
        # a seated joint has ~0 solid interference (tenon fills the
        # mortise void) AND the beam extends out of the post — not
        # driving through it. The End-B mate frame must reverse its
        # orientation or the beam seats backwards (live bent bug).
        for jid, end in (("A", "A"), ("B", "B")):
            with self.subTest(end=end):
                vs = self.apply(f"E{jid}", placement={"T.AnchorBeam.001": {"end": end}})
                inter, out = self._seated_interference(vs)
                self.assertLess(inter, 1.0,
                                f"end {end}: {inter:.1f} in^3 interference — "
                                f"beam driving through the post")
                self.assertTrue(out, f"end {end}: beam does not reach out")
                self._remove_joint(vs)

    def test_engagement_none_without_mate_frame(self):
        # a joint whose mate frame was removed (older joints) → no pose
        from freecad.bentwizard.apply_joint import engagement_placement
        vs = self.apply()
        mate = self.doc.getObjectsByLabel("Mate.Lcs.HMT.B3a")[0]
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

    def test_preview_seats_when_primary_body_moved(self):
        # the live bug: posts moved aside with the transform tool, then
        # previewed — the ghost must seat at the moved post, not at the
        # origin-relative spot
        from freecad.bentwizard.apply_joint import (create_preview,
                                                    engagement_placement)
        vs = self.apply()
        self.post.Placement = App.Placement(
            App.Vector(-2000, 500, 100), App.Rotation(App.Vector(0, 0, 1), 25))
        self.doc.recompute()
        group = create_preview(vs)
        link = group.Group[0]
        _, _, seated = engagement_placement(vs)
        self.assertLess(link.Placement.Base.sub(seated.Base).Length, 1e-6)

    def test_preview_follows_station_change_live(self):
        # the ghost is attached to the landing frame, so moving the joint
        # station moves the ghost with the mortise (live fit adjustment)
        from freecad.bentwizard.apply_joint import (create_preview,
                                                    engagement_placement)
        vs = self.apply(values={"Joint_Station": App.Units.Quantity("60 in")})
        group = create_preview(vs)
        link = group.Group[0]
        vs.Joint_Station = App.Units.Quantity("90 in")
        self.doc.recompute()
        _, _, seated = engagement_placement(vs)
        self.assertLess(link.Placement.Base.sub(seated.Base).Length, 1e-6)

    def test_remove_joint_clears_its_live_preview(self):
        # the live bug: removing a joint while its preview was up
        # orphaned the ghost and left the secondary hidden
        from freecad.bentwizard.apply_joint import (create_preview,
                                                    find_preview, remove_joint)
        vs = self.apply()
        create_preview(vs)
        self.assertFalse(self.beam.Visibility)
        remove_joint(vs)
        # ghost gone, secondary visible again, nothing orphaned
        self.assertTrue(self.beam.Visibility)
        self.assertEqual(
            [o for o in self.doc.Objects if o.Label.startswith("Preview_")],
            [])
        self.assertEqual(
            [o for o in self.doc.Objects if o.TypeId == "App::Link"], [])

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
        mate = self.doc.getObjectsByLabel("Mate.Lcs.HMT.B3a")[0]
        self.doc.removeObject(mate.Name)
        self.doc.recompute()
        self.assertIsNone(create_preview(vs))

    def test_placement_record_written(self):
        vs = self.apply(placement={"T.Post.001": {"face": 2, "hand": "mirrored"},
                                   "T.AnchorBeam.001": {"end": "B"}})
        self.assertEqual(
            vs.Placement_Record,
            "T.Post.001 -> P3-1: face 2, hand mirrored; T.AnchorBeam.001 -> B3-1: end B")

    def test_joint_label_and_tree_placement(self):
        # new scheme: J-<Kind>-<serial>, kind token from the template's
        # file stem; the VarSet and its handle park side by side in the
        # TimberJoints group (named apart from every Assembly's own
        # "Joints" group) until a bent claims them;
        # Position_Tag exists as empty display-only data
        from freecad.bentwizard.joint_handle import find_handle
        vs = self.apply("001")
        self.assertEqual(vs.Label, "J-HousedMT-001")
        handle = find_handle(vs)
        self.assertEqual(handle.Label, "Handle_J-HousedMT-001")
        self.assertIs(handle.Joint, vs)
        group = next(o for o in self.doc.Objects
                     if o.TypeId == "App::DocumentObjectGroup"
                     and o.Label == "TimberJoints")
        self.assertIn(handle, list(group.Group))
        self.assertIn(vs, list(group.Group))
        self.assertEqual(vs.Position_Tag, "")

    def test_legacy_joints_group_migrates(self):
        # a pre-rename document's "Joints" Std Group is renamed in
        # place, not duplicated
        legacy = self.doc.addObject("App::DocumentObjectGroup", "Joints")
        legacy.Label = "Joints"
        vs = self.apply("001")
        self.assertEqual(legacy.Label, "TimberJoints")
        self.assertIn(vs, list(legacy.Group))
        groups = [o for o in self.doc.Objects
                  if o.TypeId == "App::DocumentObjectGroup"]
        self.assertEqual(len(groups), 1)

    def test_legacy_varset_group_migrates(self):
        # ...as is a TimberJointVars group from before handles existed
        legacy = self.doc.addObject("App::DocumentObjectGroup", "TJV")
        legacy.Label = "TimberJointVars"
        self.apply("001")
        self.assertEqual(legacy.Label, "TimberJoints")
        groups = [o for o in self.doc.Objects
                  if o.TypeId == "App::DocumentObjectGroup"]
        self.assertEqual(len(groups), 1)

    def test_output_lints_completely_clean(self):
        from freecad.bentwizard.linter import lint
        self.apply()
        with tempfile.TemporaryDirectory() as td:
            path = str(Path(td) / "applied.FCStd")
            self.doc.saveAs(path)
            self.assertEqual([str(f) for f in lint(path)], [])

    def test_engagement_seats_correctly_on_every_face_and_end(self):
        # The authority on mate parity (the inverted end-B/face-2 bent
        # of the first GUI shakedown): for every post face x beam end,
        # the engagement pose must ACTUALLY seat the joint — tenon
        # inside the post, no interpenetration. Plain frame coincidence
        # mirrors the fit through the bearing plane on the flip_z
        # faces, which shows up here as cubic inches of overlap.
        from freecad.bentwizard.apply_joint import (apply_joint,
                                                    engagement_placement)
        from freecad.bentwizard.timber import new_timber
        for face in (1, 2, 3, 4):
            for end in ("A", "B"):
                with self.subTest(face=face, end=end):
                    post, _ = new_timber(self.doc, f"P9-{face}{end}",
                                         "10 in", "8 in", "10 ft")
                    beam, _ = new_timber(self.doc, f"B9-{face}{end}",
                                         "6 in", "8 in", "8 ft")
                    vs = apply_joint(
                        self.doc, self.spec, f"M{face}{end}",
                        {"T.Post.001": post, "T.AnchorBeam.001": beam},
                        placement={"T.Post.001": {"face": face},
                                   "T.AnchorBeam.001": {"end": end}})
                    mover, _anchor, seated = engagement_placement(vs)
                    self.assertIs(mover, beam)
                    beam.Placement = seated
                    self.doc.recompute()
                    # the only universally reliable seating invariants
                    # (through-tenons poke out the far side; some
                    # joints have no tenon at all): the halves TOUCH
                    # but share no interior volume. A wrong-direction
                    # seat interpenetrates; a correct one slots the
                    # solid into the void exactly.
                    overlap = post.Shape.common(beam.Shape).Volume
                    self.assertLess(overlap / 25.4 ** 3, 1e-3,
                                    "seated halves interpenetrate")
                    distance = post.Shape.distToShape(beam.Shape)[0]
                    self.assertLess(distance, 1e-6,
                                    "seated halves do not touch — "
                                    "joint not engaged")


LIBRARY = REPO_ROOT / "library"
WHD_TEMPLATE = LIBRARY / "Joint_WedgedHalfDovetail.FCStd"


@unittest.skipUnless(HAVE_FREECAD, "FreeCAD not importable — run with the bundled python")
class FramesAtFaceInvariant(unittest.TestCase):
    """A landing frame sits on the primary timber's face, so changing the
    housing must not move it.

    This is the whole point of frames-at-face, and until now nothing
    asserted it. Before the conversion the frame was authored at
    `Width - Housing_Depth`, so deepening the housing dragged the frame
    inward — and with it the clear-span allowance, the seat, and every
    neighbouring timber's position. Now the housing is an independently
    adjustable bearing feature: the frame holds on the face, the cuts
    that measure from the bearing plane follow, and the allowance grows
    by exactly the extra depth (a deeper housing means a deeper seat).

    Runs over every library template declaring a Housing_Depth, so a new
    template authored on the old convention fails here rather than in a
    bent six months later.
    """

    @staticmethod
    def _housed_companion(doc):
        """The template's companion layout VarSet, if it has a housing."""
        for o in doc.Objects:
            if (o.TypeId == "App::VarSet"
                    and getattr(o, "VarSet_Role", "") == "Layout"
                    and hasattr(o, "Housing_Depth")):
                return o
        return None

    @staticmethod
    def _landing_frame(doc):
        from freecad.bentwizard import naming
        for o in doc.Objects:
            if (o.TypeId == "Part::LocalCoordinateSystem"
                    and getattr(o, naming.FRAME_ROLE_PROP, None)
                    == naming.FRAME_ROLE_LANDING
                    and o.ExpressionEngine):
                return o                      # the anchor's; the entering
        return None                           # timber's end frame has none

    def test_deepening_the_housing_does_not_move_the_landing_frame(self):
        import FreeCAD
        checked = []
        for path in sorted(LIBRARY.glob("*.FCStd")):
            doc = FreeCAD.openDocument(str(path))
            try:
                companion = self._housed_companion(doc)
                if companion is None:
                    continue                  # jointless template, no housing
                frame = self._landing_frame(doc)
                self.assertIsNotNone(
                    frame, f"{path.stem}: no expression-driven landing frame")
                doc.recompute()
                before = FreeCAD.Vector(frame.Placement.Base)
                allowance = companion.Stick_Allowance_FTF.Value
                companion.Housing_Depth = companion.Housing_Depth.Value + 25.4
                doc.recompute()
                moved = (frame.Placement.Base - before).Length
                grew = companion.Stick_Allowance_FTF.Value - allowance
                self.assertLess(
                    moved, 1e-9,
                    f"{path.stem}: landing frame moved {moved:.4f} mm when "
                    f"the housing deepened — it is not on the face")
                self.assertAlmostEqual(
                    grew, 25.4, places=6,
                    msg=f"{path.stem}: allowance did not follow the housing")
                checked.append(path.stem)
            finally:
                FreeCAD.closeDocument(doc.Name)
        self.assertEqual(
            checked, ["Joint_HousedMT", "Joint_WedgedHalfDovetail"],
            f"expected both housed templates to be checked, got {checked}")

    def test_a_zero_depth_housing_still_recomputes(self):
        """A Mill Rule housing is an OPTIONAL bearing feature, so zero is
        a legitimate value rather than an edge case.

        It used to kill the template: a pocket whose Length is a single
        user parameter fails outright at zero ("cannot create a pocket
        with a total length of 0"), and the failure was worse than a
        stopped recompute — the housing froze at its last good depth
        while a driven Length carried on resizing the beam, so an H-bent
        went quietly inconsistent.

        The arrangement that survives: the sketch sits on the bearing
        plane (an explicit Housing_Depth term back from the frame, which
        is on the face) and the cut runs OUTWARD from there, padded past
        the face. The pad only ever cuts air, so the removed volume is
        exactly Housing_Depth at any depth including zero.
        """
        import FreeCAD
        checked = []
        for path in sorted(LIBRARY.glob("*.FCStd")):
            doc = FreeCAD.openDocument(str(path))
            try:
                companion = self._housed_companion(doc)
                if companion is None:
                    continue
                bodies = [o for o in doc.Objects
                          if o.TypeId == "PartDesign::Body"]
                companion.Housing_Depth = 0
                doc.recompute()
                broken = [o.Label for o in doc.Objects
                          if o.State and ("Invalid" in o.State
                                          or "Error" in o.State)]
                self.assertEqual(
                    broken, [],
                    f"{path.stem}: objects failed at Housing_Depth = 0: "
                    f"{broken}")
                for b in bodies:
                    self.assertTrue(
                        b.Shape.isValid(),
                        f"{path.stem}: {b.Label} invalid at zero housing")
                checked.append(path.stem)
            finally:
                FreeCAD.closeDocument(doc.Name)
        self.assertEqual(
            checked, ["Joint_HousedMT", "Joint_WedgedHalfDovetail"],
            f"expected both housed templates to be checked, got {checked}")


@unittest.skipUnless(HAVE_FREECAD, "FreeCAD not importable — run with the bundled python")
class WedgedHalfDovetailPlacementMatrix(unittest.TestCase):
    """The dovetail exercises two placement paths no other template does,
    and both were broken until August 2026 (found in GUI testing).

    It is the only template carrying an **angle constraint** (the
    dovetail slope) and the only one attaching frame-children to a
    frame's **XZ/YZ** planes rather than its XY. Joint_HousedMT and
    Joint_Butt cover neither, so this class is the regression guard for
    both fixes:

    - a mirrored sketch must negate its Angle constraints on an odd
      number of flipped axes, or the mirrored geometry contradicts the
      unflipped angle and the solver drops to -1 ('recompute failed for
      Mortise.Skt' on every flip_z face);
    - a frame-child's offset must be negated on whichever local
      component runs along the flipped frame axis, which is local *y*
      for an XZ/YZ attachment and only local z for XY.
    """

    @classmethod
    def setUpClass(cls):
        from freecad.bentwizard.apply_joint import TemplateSpec
        cls.spec = TemplateSpec(WHD_TEMPLATE)

    def setUp(self):
        self.doc = App.newDocument("WhdMatrix")

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def _apply(self, face, end):
        from freecad.bentwizard.apply_joint import apply_joint
        from freecad.bentwizard.timber import new_timber
        post, _ = new_timber(self.doc, f"P8-{face}{end}", "10 in", "8 in", "10 ft")
        beam, _ = new_timber(self.doc, f"B8-{face}{end}", "6 in", "8 in", "8 ft")
        v0 = (post.Shape.Volume, beam.Shape.Volume)
        vs = apply_joint(
            self.doc, self.spec, f"W{face}{end}",
            {"T.Post.001": post, "T.AnchorBeam.001": beam},
            placement={"T.Post.001": {"face": face},
                       "T.AnchorBeam.001": {"end": end}})
        self.doc.recompute()
        return vs, post, beam, v0

    def test_applies_on_every_face_and_end(self):
        """Every combination recomputes. Faces 2 and 3 raised
        'recompute failed for: Mortise.Skt' outright — the angle
        constraint — so this is the sharpest form of the regression."""
        for face in (1, 2, 3, 4):
            for end in ("A", "B"):
                with self.subTest(face=face, end=end):
                    _vs, post, beam, _v0 = self._apply(face, end)
                    for body in (post, beam):
                        self.assertNotIn(
                            "Invalid", " ".join(body.State),
                            f"{body.Label} invalid after apply")

    def test_beam_cut_is_the_same_whichever_face_and_end(self):
        """The beam's own joinery cannot depend on where it lands.

        Two distinct bugs showed up here. End B cut 352.000 in3 against
        end A's 362.586 — quietly wrong, and wrong before any of this
        work. Then decoupling the cheek sketch from the mate frame (so
        nothing hangs off a frame that moves) dropped it to 0.000: the
        offset ran along the frame's Z but sat on local *y*, which the
        end-B negation did not cover, so at end B the sketch landed at
        Length + Tenon_Length, outside the stick, and cut air.
        """
        cuts = {}
        for face in (1, 2, 3, 4):
            for end in ("A", "B"):
                _vs, _post, beam, v0 = self._apply(face, end)
                cuts[(face, end)] = round((v0[1] - beam.Shape.Volume) / IN3, 3)
        self.assertGreater(min(cuts.values()), 1.0,
                           f"a placement cut no joinery at all: {cuts}")
        self.assertEqual(len(set(cuts.values())), 1,
                         f"beam cut varies with placement: {cuts}")

    def test_post_cut_varies_only_with_the_face_dimension(self):
        """Faces 1/3 land on Depth, faces 2/4 on Width — the only
        legitimate reason the post's cut differs — and never with the
        beam's end."""
        cuts = {}
        for face in (1, 2, 3, 4):
            for end in ("A", "B"):
                _vs, post, _beam, v0 = self._apply(face, end)
                cuts[(face, end)] = round((v0[0] - post.Shape.Volume) / IN3, 3)
        for face in (1, 2, 3, 4):
            self.assertEqual(cuts[(face, "A")], cuts[(face, "B")],
                             f"face {face}: post cut depends on the beam's end")
        self.assertEqual(cuts[(1, "A")], cuts[(3, "A")], "faces 1 and 3 differ")
        self.assertEqual(cuts[(2, "A")], cuts[(4, "A")], "faces 2 and 4 differ")

    def test_engagement_seats_on_every_face_and_end(self):
        from freecad.bentwizard.apply_joint import engagement_placement
        for face in (1, 2, 3, 4):
            for end in ("A", "B"):
                with self.subTest(face=face, end=end):
                    vs, post, beam, _v0 = self._apply(face, end)
                    mover, _anchor, seated = engagement_placement(vs)
                    self.assertIs(mover, beam)
                    beam.Placement = seated
                    self.doc.recompute()
                    overlap = post.Shape.common(beam.Shape).Volume
                    self.assertLess(overlap / IN3, 1e-3,
                                    "seated halves interpenetrate")
                    self.assertLess(post.Shape.distToShape(beam.Shape)[0], 1e-6,
                                    "seated halves do not touch")


if __name__ == "__main__":
    unittest.main()
