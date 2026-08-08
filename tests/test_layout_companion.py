"""Tests for the companion layout VarSet (roadmap: Parametric layout).

A joint template may declare a second, PURE-SOURCE VarSet holding the
length-consuming parameters plus the derived Stick_Allowance. The joint
VarSet consumes from it, never the reverse — that direction is the only
thing that lets a timber's Dims.Length sum the allowances without
closing a dependency cycle, because FreeCAD's dependency graph is
object-granular and the template already binds the joint to the
entering timber's Dims.

FreeCAD-dependent — run with the bundled interpreter.
"""

import sys
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
IN = 25.4


@unittest.skipUnless(HAVE_FREECAD,
                     "FreeCAD not importable — run with the bundled python")
class LayoutCompanionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from freecad.bentwizard.apply_joint import TemplateSpec
        cls.spec = TemplateSpec(TEMPLATE)

    def setUp(self):
        from freecad.bentwizard.timber import new_timber
        self.doc = App.newDocument("CompanionTest")
        self.post1, self.d1 = new_timber(self.doc, "T-Post-001",
                                         "8 in", "8 in", "10 ft")
        self.post2, self.d2 = new_timber(self.doc, "T-Post-002",
                                         "8 in", "8 in", "10 ft")
        self.tie, self.dt = new_timber(self.doc, "T-Tie-001",
                                       "6 in", "8 in", "12 ft")
        self.doc.recompute()

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def joint(self, serial, post, end, face, tenon):
        from freecad.bentwizard.apply_joint import apply_joint
        from freecad.bentwizard.assemble import assimilate_joint
        vs = apply_joint(
            self.doc, self.spec, serial,
            {"T.Post.001": post, "T.AnchorBeam.001": self.tie},
            values={"Tenon_Length": tenon, "Housing_Depth": "1 in",
                    "Joint_Station": "96 in"},
            placement={"T.Post.001": {"face": face},
                       "T.AnchorBeam.001": {"end": end}})
        assimilate_joint(self.doc, vs)
        self.doc.recompute()
        return vs

    def bent(self):
        """End A on post 1 (3in tenon), end B on post 2 (11in through)."""
        j1 = self.joint("001", self.post1, "A", 4, "3 in")
        j2 = self.joint("002", self.post2, "B", 2, "11 in")
        return j1, j2

    def inches(self, q):
        return (q.Value if hasattr(q, "Value") else float(q)) / IN

    def exprs(self, obj):
        return {p.lstrip("."): e for p, e in obj.ExpressionEngine}

    # -- template reading --------------------------------------------------

    def test_template_declares_a_companion(self):
        self.assertIsNotNone(self.spec.layout,
                             "library template lost its companion VarSet")
        merged = {(p["name"], p["varset"]) for p in self.spec.parameters}
        self.assertIn(("Stick_Allowance_OC", "layout"), merged)
        self.assertIn(("Tenon_Length", "layout"), merged)
        # the joint's copy still exists (its geometry reads it) but is
        # tagged consumed, so the dialog shows only the companion's row
        consumed = {p["name"] for p in self.spec.parameters
                    if p["varset"] == "joint" and p["consumed"]}
        self.assertEqual(consumed, {"Tenon_Length", "Housing_Depth"})

    def test_companion_resolves_structurally_after_a_rename(self):
        """Frame_Role's lesson: never bind by label."""
        from freecad.bentwizard.apply_joint import layout_varset
        j1, _j2 = self.bent()
        companion = layout_varset(j1)
        self.assertIsNotNone(companion)
        companion.Label = "renamed by the user"
        self.doc.recompute()
        self.assertIs(layout_varset(j1), companion)

    # -- the consuming direction ------------------------------------------

    def test_joint_consumes_from_its_own_companion(self):
        """Regression: `values` is keyed by NAME and both VarSets carry
        these names, so the companion's value used to land on the joint
        VarSet too and replace the binding — the allowance would then
        track an edit the actual cut ignored."""
        from freecad.bentwizard.apply_joint import layout_varset
        for vs in self.bent():
            companion = layout_varset(vs)
            for name in ("Tenon_Length", "Housing_Depth"):
                self.assertEqual(
                    self.exprs(vs).get(name),
                    f"<<{companion.Label}>>.{name}",
                    f"{vs.Label}.{name} does not consume from its companion")

    def test_dialog_values_land_on_the_companion(self):
        from freecad.bentwizard.apply_joint import layout_varset
        j1, j2 = self.bent()
        self.assertAlmostEqual(
            self.inches(layout_varset(j1).Tenon_Length), 3, places=6)
        self.assertAlmostEqual(
            self.inches(layout_varset(j2).Tenon_Length), 11, places=6)

    def test_editing_the_companion_moves_the_cut(self):
        """The parameter is authoritative on the companion: the geometry
        must follow an edit there."""
        from freecad.bentwizard.apply_joint import layout_varset
        j1, _j2 = self.bent()
        companion = layout_varset(j1)
        before = self.post1.Shape.Volume
        companion.setExpression("Housing_Depth", None)   # applied as an expr
        companion.Housing_Depth = "2 in"
        self.doc.recompute()
        self.assertNotAlmostEqual(self.post1.Shape.Volume, before, places=6,
                                  msg="the post's housing ignored the edit")

    # -- what it exists for ------------------------------------------------

    def test_allowance_values(self):
        from freecad.bentwizard.apply_joint import layout_varset
        j1, j2 = self.bent()
        # tenon + housing - post/2:  3+1-4 = 0   and   11+1-4 = +8
        self.assertAlmostEqual(
            self.inches(layout_varset(j1).Stick_Allowance_OC), 0, places=4)
        self.assertAlmostEqual(
            self.inches(layout_varset(j2).Stick_Allowance_OC), 8, places=4)

    def test_grid_drives_the_stick_with_no_cycle(self):
        from freecad.bentwizard.apply_joint import layout_varset
        j1, j2 = self.bent()
        c1, c2 = layout_varset(j1), layout_varset(j2)
        layout = self.doc.addObject("App::VarSet", "Layout")
        layout.Label = "Project_Main"
        layout.addProperty("App::PropertyLength", "Bay_Span_OC", "Grid",
                           "On-center distance between post grid lines.")
        layout.Bay_Span_OC = "136 in"
        self.doc.recompute()

        self.dt.setExpression(
            "Length",
            f"<<Project_Main>>.Bay_Span_OC"
            f" + <<{c1.Label}>>.Stick_Allowance_OC"
            f" + <<{c2.Label}>>.Stick_Allowance_OC")
        self.doc.recompute()
        self.assertAlmostEqual(self.inches(self.dt.Length), 144, places=3)

        layout.Bay_Span_OC = "16 ft"
        self.doc.recompute()
        self.assertAlmostEqual(self.inches(self.dt.Length), 200, places=3)

        # and a joinery edit re-cuts the stick without moving the grid —
        # the whole reason the allowance is authored in the template
        c2.setExpression("Tenon_Length", None)
        c2.Tenon_Length = "14 in"
        self.doc.recompute()
        self.assertAlmostEqual(self.inches(self.dt.Length), 203, places=3)

    def test_posts_fatten_without_moving_the_grid(self):
        from freecad.bentwizard.apply_joint import layout_varset
        j1, j2 = self.bent()
        c1 = layout_varset(j1)
        before = self.inches(c1.Stick_Allowance_OC)
        self.d1.Width = "10 in"
        self.doc.recompute()
        self.assertAlmostEqual(self.inches(c1.Stick_Allowance_OC),
                               before - 1, places=4,
                               msg="allowance did not follow the post section")

    # -- lifecycle ---------------------------------------------------------

    def test_companion_nests_in_the_handle(self):
        from freecad.bentwizard.apply_joint import layout_varset
        from freecad.bentwizard.joint_handle import find_handle
        j1, _j2 = self.bent()
        self.assertIs(layout_varset(j1).getParentGroup(), find_handle(j1))

    def test_remove_joint_takes_its_companion(self):
        from freecad.bentwizard.apply_joint import layout_varset, remove_joint
        j1, j2 = self.bent()
        doomed = layout_varset(j2).Name
        survivor = layout_varset(j1).Name
        remove_joint(j2)
        self.doc.recompute()
        self.assertIsNone(self.doc.getObject(doomed),
                          "the companion outlived its joint")
        self.assertIsNotNone(self.doc.getObject(survivor),
                             "removal took another joint's companion")

    def test_output_lints_clean(self):
        import tempfile
        from freecad.bentwizard.linter import lint
        self.bent()
        with tempfile.TemporaryDirectory() as td:
            path = str(Path(td) / "companion.FCStd")
            self.doc.saveAs(path)
            self.assertEqual([str(f) for f in lint(path)], [])


@unittest.skipUnless(HAVE_FREECAD,
                     "FreeCAD not importable — run with the bundled python")
class CompanionFaceSwapTest(unittest.TestCase):
    """Grid_Setback is half the ANCHOR timber's dimension along the joint
    normal, and that dimension changes with the face: FACES[n]['ddim'] is
    Width on faces 2/4 and Depth on 1/3. The companion's expressions were
    never face-corrected — _face_transform runs on landing-frame specs
    only and _fill rewrites labels alone — so on faces 1/3 the setback
    kept reading Width and on-center layout came out wrong by half the
    section difference, silently. Needs a NON-SQUARE post to detect.
    """

    @classmethod
    def setUpClass(cls):
        from freecad.bentwizard.apply_joint import TemplateSpec
        cls.spec = TemplateSpec(TEMPLATE)

    def setUp(self):
        from freecad.bentwizard.timber import new_timber
        self.doc = App.newDocument("FaceSwapTest")
        self.post, _ = new_timber(self.doc, "T-Post-001",
                                  "10 in", "8 in", "10 ft")
        self.tie, _ = new_timber(self.doc, "T-Tie-001",
                                 "6 in", "8 in", "12 ft")
        self.doc.recompute()

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def setback_on(self, face):
        from freecad.bentwizard.apply_joint import apply_joint, layout_varset
        vs = apply_joint(
            self.doc, self.spec, f"00{face}",
            {"T.Post.001": self.post, "T.AnchorBeam.001": self.tie},
            values={"Tenon_Length": "3 in", "Housing_Depth": "1 in",
                    "Joint_Station": "48 in"},
            placement={"T.Post.001": {"face": face},
                       "T.AnchorBeam.001": {"end": "A"}})
        self.doc.recompute()
        return layout_varset(vs).Grid_Setback.Value / IN

    def test_anchor_role_is_the_landing_only_timber(self):
        self.assertEqual(self.spec.anchor_role, "T.Post.001")

    def test_width_faces_use_half_the_width(self):
        for face in (2, 4):
            with self.subTest(face=face):
                self.assertAlmostEqual(self.setback_on(face), 5, places=6)

    def test_depth_faces_use_half_the_depth(self):
        for face in (1, 3):
            with self.subTest(face=face):
                self.assertAlmostEqual(self.setback_on(face), 4, places=6)


if __name__ == "__main__":
    unittest.main()
