"""Tests for driving a timber's Length from a span (span.py).

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
class SpanTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from freecad.bentwizard.apply_joint import TemplateSpec
        cls.spec = TemplateSpec(TEMPLATE)

    def setUp(self):
        from freecad.bentwizard.timber import new_timber
        self.doc = App.newDocument("SpanTest")
        self.post1, self.d1 = new_timber(self.doc, "T-Post-001",
                                         "8 in", "8 in", "10 ft")
        self.post2, self.d2 = new_timber(self.doc, "T-Post-002",
                                         "8 in", "8 in", "10 ft")
        self.tie, self.dt = new_timber(self.doc, "T-Tie-001",
                                       "6 in", "8 in", "12 ft")
        self.doc.recompute()

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def bent(self):
        from freecad.bentwizard.apply_joint import apply_joint
        from freecad.bentwizard.assemble import assimilate_joint
        out = []
        for serial, post, end, face, tenon in (("001", self.post1, "A", 4, "3 in"),
                                               ("002", self.post2, "B", 2, "11 in")):
            vs = apply_joint(
                self.doc, self.spec, serial,
                {"T.Post.001": post, "T.AnchorBeam.001": self.tie},
                values={"Tenon_Length": tenon, "Housing_Depth": "1 in",
                        "Joint_Station": "96 in"},
                placement={"T.Post.001": {"face": face},
                           "T.AnchorBeam.001": {"end": end}})
            assimilate_joint(self.doc, vs)
            out.append(vs)
        self.doc.recompute()
        return out

    def inches(self, q):
        return (q.Value if hasattr(q, "Value") else float(q)) / IN

    def grid(self):
        """Solved on-center distance between the two posts."""
        xs = []
        for body, dims in ((self.post1, self.d1), (self.post2, self.d2)):
            c = body.getGlobalPlacement().multVec(
                App.Vector(dims.Width.Value / 2, dims.Depth.Value / 2, 0))
            xs.append(c.x / IN)
        return abs(xs[1] - xs[0])

    def span(self, value="136 in", name="Bay_Span_OC"):
        from freecad.bentwizard.span import ensure_span_property
        return ensure_span_property(self.doc, name, value)

    # -- which joints count ------------------------------------------------

    def test_only_entering_joints_contribute(self):
        """The entering half is the one whose stick the joinery eats. A
        post carrying a tie's mortise is not shortened by it."""
        from freecad.bentwizard.span import entering_joints
        self.bent()
        self.assertEqual(len(entering_joints(self.tie)), 2)
        self.assertEqual(entering_joints(self.post1), [])
        self.assertEqual(entering_joints(self.post2), [])

    def test_refuses_a_timber_with_no_allowances(self):
        from freecad.bentwizard.span import SpanError, drive_length
        self.bent()
        with self.assertRaises(SpanError):
            drive_length(self.post1, self.span())

    # -- the span property -------------------------------------------------

    def test_creates_a_project_varset_when_none_exists(self):
        from freecad.bentwizard.span import DEFAULT_SPAN_VARSET
        ref = self.span()
        self.assertEqual(ref, f"<<{DEFAULT_SPAN_VARSET}>>.Bay_Span_OC")
        holder = self.doc.getObjectsByLabel(DEFAULT_SPAN_VARSET)[0]
        self.assertAlmostEqual(self.inches(holder.Bay_Span_OC), 136, places=6)

    def test_existing_span_is_reused_not_overwritten(self):
        """Several bays share one span — that is the point of it."""
        self.span("136 in")
        self.span("999 in")           # same name, different value
        holder = self.doc.getObjectsByLabel("Project_Main")[0]
        self.assertAlmostEqual(self.inches(holder.Bay_Span_OC), 136, places=6)

    def test_rejects_an_unusable_property_name(self):
        from freecad.bentwizard.span import SpanError
        for bad in ("", "2Bay", "bay span", "bay-span"):
            with self.assertRaises(SpanError, msg=f"accepted {bad!r}"):
                self.span(name=bad)

    # -- driving -----------------------------------------------------------

    def test_drives_the_stick_from_the_grid(self):
        from freecad.bentwizard.span import drive_length, driving_span
        self.bent()
        length = drive_length(self.tie, self.span("136 in"))
        self.assertAlmostEqual(self.inches(length), 144, places=3)
        self.assertAlmostEqual(self.grid(), 136, places=3)
        self.assertEqual(driving_span(self.tie), ("<<Project_Main>>.Bay_Span_OC", "OC"))

    def test_editing_the_span_moves_the_bay(self):
        from freecad.bentwizard.span import drive_length
        self.bent()
        drive_length(self.tie, self.span("136 in"))
        holder = self.doc.getObjectsByLabel("Project_Main")[0]
        holder.Bay_Span_OC = "16 ft"
        self.doc.recompute()
        self.assertAlmostEqual(self.inches(self.dt.Length), 200, places=3)
        self.assertAlmostEqual(self.grid(), 192, places=3)

    def test_refuses_a_span_shorter_than_the_joinery(self):
        """And leaves the timber exactly as it found it."""
        from freecad.bentwizard.span import SpanError, drive_length
        self.bent()
        before = self.dt.Length.Value
        # the span term is any expression, not necessarily a VarSet ref;
        # a PropertyLength would clamp a negative away before we saw it
        with self.assertRaises(SpanError):
            drive_length(self.tie, "-200 in")
        self.doc.recompute()
        self.assertAlmostEqual(self.dt.Length.Value, before, places=6,
                               msg="a refused span left the timber changed")
        self.assertEqual(
            [p for p, _e in self.dt.ExpressionEngine
             if p.lstrip(".") == "Length"], [],
            "a refused span left an expression behind")

    def test_refuses_a_span_that_does_not_resolve(self):
        from freecad.bentwizard.span import SpanError, drive_length
        self.bent()
        with self.assertRaises(SpanError):
            drive_length(self.tie, "<<NoSuchVarSet>>.Nope")

    def test_freeze_keeps_the_length(self):
        from freecad.bentwizard.span import (drive_length, driving_span,
                                             freeze_length)
        self.bent()
        drive_length(self.tie, self.span("136 in"))
        self.assertTrue(freeze_length(self.tie))
        self.doc.recompute()
        self.assertAlmostEqual(self.inches(self.dt.Length), 144, places=3)
        self.assertIsNone(driving_span(self.tie))
        self.assertFalse(freeze_length(self.tie), "second freeze is a no-op")

    # -- removal -----------------------------------------------------------

    def test_removing_a_joint_freezes_its_term_only(self):
        """The stick must not shrink by the tenon it is losing and drag
        the far post with it, mid-delete: that one term freezes at its
        resolved value while the span keeps driving the rest."""
        from freecad.bentwizard.apply_joint import remove_joint
        from freecad.bentwizard.span import drive_length
        j1, j2 = self.bent()
        drive_length(self.tie, self.span("136 in"))
        self.assertAlmostEqual(self.inches(self.dt.Length), 144, places=3)

        remove_joint(j2)                       # the +8in through tenon
        self.doc.recompute()
        self.assertAlmostEqual(self.inches(self.dt.Length), 144, places=3,
                               msg="the stick moved when the joint went")

        # ...and the span still drives what is left
        holder = self.doc.getObjectsByLabel("Project_Main")[0]
        holder.Bay_Span_OC = "146 in"
        self.doc.recompute()
        self.assertAlmostEqual(self.inches(self.dt.Length), 154, places=3,
                               msg="the span stopped driving the survivor")

    def test_removing_both_joints_leaves_a_working_length(self):
        """Regression, units: end A's allowance is exactly ZERO here,
        and freezing it via UserString wrote a bare '0' with no unit
        under an imperial display schema — a unitless term in a length
        expression, so Length went Invalid. Frozen terms carry the raw
        internal value and an explicit unit instead."""
        from freecad.bentwizard.apply_joint import remove_joint
        from freecad.bentwizard.span import drive_length
        j1, j2 = self.bent()
        drive_length(self.tie, self.span("136 in"))
        for vs in (j2, j1):
            remove_joint(vs)
            self.doc.recompute()
        self.assertAlmostEqual(self.inches(self.dt.Length), 144, places=3)
        self.assertNotIn("Invalid", self.dt.State)

    # -- the two bases -----------------------------------------------------

    def test_clear_span_needs_no_knowledge_of_the_posts(self):
        """The half-post terms cancel: Length = FTF + sum(tenon+housing).
        Adam's original 12' example, arrived at from the other side."""
        from freecad.bentwizard.span import drive_length
        self.bent()
        ref = self.span("128 in", name="Bay_Dist_FTF")
        length = drive_length(self.tie, ref, "FTF")
        # 128 clear + (3+1) + (11+1) = 144
        self.assertAlmostEqual(self.inches(length), 144, places=3)
        self.assertAlmostEqual(self.grid(), 136, places=3)

    def test_the_two_bases_agree(self):
        """136 O.C. and 128 clear describe the same bay, so they must cut
        the same stick and solve to the same grid."""
        from freecad.bentwizard.span import drive_length
        self.bent()
        by_oc = drive_length(self.tie, self.span("136 in"), "OC").Value
        grid_oc = self.grid()
        by_ftf = drive_length(
            self.tie, self.span("128 in", name="Bay_Dist_FTF"), "FTF").Value
        self.assertAlmostEqual(by_ftf, by_oc, places=6)
        self.assertAlmostEqual(self.grid(), grid_oc, places=6)

    def test_basis_reads_back_from_the_expression(self):
        """Structural, never from the variable's name."""
        from freecad.bentwizard.span import drive_length, driving_span
        self.bent()
        drive_length(self.tie, self.span("128 in", name="Misleading_Dist_OC"),
                     "FTF")
        _ref, basis = driving_span(self.tie)
        self.assertEqual(basis, "FTF",
                         "basis was taken from the name, not the expression")

    def test_readout_converts_both_ways(self):
        from freecad.bentwizard.span import readout
        self.bent()
        oc = readout(self.tie, 136 * IN, "OC")
        self.assertAlmostEqual(oc["FTF"] / IN, 128, places=4)
        self.assertAlmostEqual(oc["Length"] / IN, 144, places=4)
        ftf = readout(self.tie, 128 * IN, "FTF")
        self.assertAlmostEqual(ftf["OC"] / IN, 136, places=4)
        self.assertAlmostEqual(ftf["Length"] / IN, 144, places=4)

    def test_clear_span_unavailable_with_one_end(self):
        """A timber with one end has no face-to-face distance to be
        between; on-center still works."""
        from freecad.bentwizard.apply_joint import apply_joint
        from freecad.bentwizard.assemble import assimilate_joint
        from freecad.bentwizard.span import (SpanError, available_bases,
                                             drive_length, readout)
        vs = apply_joint(
            self.doc, self.spec, "001",
            {"T.Post.001": self.post1, "T.AnchorBeam.001": self.tie},
            values={"Tenon_Length": "3 in", "Housing_Depth": "1 in",
                    "Joint_Station": "96 in"},
            placement={"T.Post.001": {"face": 4},
                       "T.AnchorBeam.001": {"end": "A"}})
        assimilate_joint(self.doc, vs)
        self.doc.recompute()

        self.assertEqual(available_bases(self.tie), ("OC",))
        with self.assertRaises(SpanError):
            drive_length(self.tie, self.span("136 in"), "FTF")
        # the O.C. readout still works, with no clear span to report
        self.assertIsNone(readout(self.tie, 136 * IN, "OC")["FTF"])

    def test_unknown_basis_is_refused(self):
        from freecad.bentwizard.span import SpanError, drive_length
        self.bent()
        with self.assertRaises(SpanError):
            drive_length(self.tie, self.span(), "sideways")

    def test_suggested_name_carries_the_basis(self):
        from freecad.bentwizard.span import suggested_name
        self.assertEqual(suggested_name("Bay", "OC"), "Bay_Dist_OC")
        self.assertEqual(suggested_name("Bay", "FTF"), "Bay_Dist_FTF")

    def test_removing_a_joint_freezes_the_clear_span_term_too(self):
        from freecad.bentwizard.apply_joint import remove_joint
        from freecad.bentwizard.span import drive_length
        _j1, j2 = self.bent()
        drive_length(self.tie,
                     self.span("128 in", name="Bay_Dist_FTF"), "FTF")
        remove_joint(j2)
        self.doc.recompute()
        self.assertAlmostEqual(self.inches(self.dt.Length), 144, places=3)
        self.assertNotIn("Invalid", self.dt.State)

    # -- orphaned distances ------------------------------------------------

    def test_a_shared_distance_is_never_removed(self):
        """Two bays on one distance is the whole point of it — stopping
        one must not delete the number the other still lives on."""
        from freecad.bentwizard.span import (SpanError, drive_length,
                                             freeze_length, references_to,
                                             remove_distance)
        from freecad.bentwizard.timber import new_timber
        self.bent()
        ref = self.span("136 in")
        drive_length(self.tie, ref)
        # a second timber bound to the same distance, the simple way
        other, dims = new_timber(self.doc, "T-Tie-002", "6 in", "8 in", "8 ft")
        dims.setExpression("Length", ref)
        self.doc.recompute()

        freeze_length(self.tie)
        self.doc.recompute()
        self.assertTrue(references_to(self.doc, ref),
                        "the other timber's use went unnoticed")
        with self.assertRaises(SpanError):
            remove_distance(self.doc, ref)
        holder = self.doc.getObjectsByLabel("Project_Main")[0]
        self.assertTrue(hasattr(holder, "Bay_Span_OC"))

    def test_an_orphaned_distance_can_be_removed(self):
        from freecad.bentwizard.span import (drive_length, freeze_length,
                                             references_to, remove_distance)
        self.bent()
        ref = self.span("136 in")
        drive_length(self.tie, ref)
        freeze_length(self.tie)
        self.doc.recompute()
        self.assertEqual(references_to(self.doc, ref), [])
        self.assertTrue(remove_distance(self.doc, ref))
        holder = self.doc.getObjectsByLabel("Project_Main")[0]
        self.assertFalse(hasattr(holder, "Bay_Span_OC"))

    def test_a_sibling_property_counts_as_a_use(self):
        """The holder's own expressions name a sibling BARE
        ('Bay_Span_OC * 2'), so a qualified-only scan would call this
        distance unused while its own VarSet still derives from it."""
        from freecad.bentwizard.span import (SpanError, references_to,
                                             remove_distance)
        ref = self.span("136 in")
        holder = self.doc.getObjectsByLabel("Project_Main")[0]
        holder.addProperty("App::PropertyLength", "Half_Bay", "Grid", "h")
        holder.setExpression("Half_Bay", "Bay_Span_OC / 2")
        self.doc.recompute()
        self.assertTrue(references_to(self.doc, ref))
        with self.assertRaises(SpanError):
            remove_distance(self.doc, ref)

    def test_a_similarly_named_property_is_not_a_use(self):
        """'Bay_Span_OC_Upper' must not make 'Bay_Span_OC' look used."""
        from freecad.bentwizard.span import references_to
        ref = self.span("136 in")
        holder = self.doc.getObjectsByLabel("Project_Main")[0]
        holder.addProperty("App::PropertyLength", "Bay_Span_OC_Upper",
                           "Grid", "u")
        holder.addProperty("App::PropertyLength", "Derived", "Grid", "d")
        holder.setExpression("Derived", "Bay_Span_OC_Upper * 2")
        self.doc.recompute()
        self.assertEqual(references_to(self.doc, ref), [])

    def test_switching_basis_orphans_the_old_distance(self):
        """Adam's step 5: drive on O.C., stop, drive on F.T.F. — the O.C.
        variable is left behind with nothing using it."""
        from freecad.bentwizard.span import (drive_length, references_to)
        self.bent()
        oc = self.span("136 in")
        drive_length(self.tie, oc)
        ftf = self.span("128 in", name="Bay_Dist_FTF")
        drive_length(self.tie, ftf, "FTF")
        self.doc.recompute()
        self.assertEqual(references_to(self.doc, oc), [])
        self.assertTrue(references_to(self.doc, ftf))

    def test_output_lints_clean(self):
        import tempfile
        from freecad.bentwizard.linter import lint
        from freecad.bentwizard.span import drive_length
        self.bent()
        drive_length(self.tie, self.span("136 in"))
        with tempfile.TemporaryDirectory() as td:
            path = str(Path(td) / "span.FCStd")
            self.doc.saveAs(path)
            self.assertEqual([str(f) for f in lint(path)], [])


if __name__ == "__main__":
    unittest.main()
