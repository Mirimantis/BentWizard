"""Ground-truth tests for the BentWizard linter.

The session-12 prototype (tests/fixtures/Joint_HouseMT_session_12.FCStd)
carries every known debt listed in the Phase 0 workflow document §7.
These tests pin the linter to that ground truth: each debt must be
caught. TimberTemplate.FCStd is the clean control — the pristine
template must produce no strict findings.

Debt 5's *value* (ProjectVars.FloorHeight left at the 54 in test value)
is not machine-decidable; the linter catches that debt at the object
level (naming + tooltip findings on ProjectVars/FloorHeight), and the
value itself remains a human review item.

Run with:  python -m unittest discover -s tests
(stdlib only — works with the bundled FreeCAD python or any Python 3.9+)
"""

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from freecad.bentwizard.linter import ADVISORY, STRICT, lint  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"
SESSION_12 = FIXTURES / "Joint_HouseMT_session_12.FCStd"
TEMPLATE = FIXTURES / "TimberTemplate.FCStd"
JOINT_TEMPLATE = FIXTURES / "Joint_HousedMT.FCStd"


class LinterFixtureTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.findings = lint(cls.FIXTURE)

    def matching(self, rule, obj=None, contains=None):
        out = []
        for f in self.findings:
            if f.rule != rule:
                continue
            if obj is not None and f.obj != obj:
                continue
            if contains is not None and contains not in f.message:
                continue
            out.append(f)
        return out

    def assertFinding(self, rule, obj=None, contains=None):
        hits = self.matching(rule, obj=obj, contains=contains)
        self.assertTrue(
            hits,
            f"expected a [{rule}] finding"
            + (f" on {obj}" if obj else "")
            + (f" mentioning {contains!r}" if contains else "")
            + f"; got: {[str(f) for f in self.findings if f.rule == rule]}")
        return hits


class SessionTwelveDebts(LinterFixtureTest):
    """Workflow document §7: every known debt must be caught."""

    FIXTURE = SESSION_12

    # Debt 1 — MT1 drives both beam ends and both posts.
    def test_mt1_spans_three_bodies(self):
        self.assertFinding("joint-varset-single-instance",
                           obj="VarSet002", contains="3 bodies")

    def test_mt1_drives_both_beam_ends(self):
        self.assertFinding("joint-varset-single-instance",
                           obj="VarSet002", contains="both ends")

    # Debt 2 — combined two-circle peg sketch on the beam.
    def test_combined_peg_sketch(self):
        self.assertFinding("multi-instance-sketch", obj="Sketch019")

    # Debt 3 — PegHole_MT1_sketch2 (Post2) references PostDims.
    def test_peghole_cross_timber_reference(self):
        self.assertFinding("cross-timber-dims-reference",
                           obj="Sketch018", contains="PostDims")

    # Debt 4 — Post2's hole feature unnamed (Hole001); tongue-sides
    # pocket never renamed (Pocket007).
    def test_unnamed_hole_feature(self):
        self.assertFinding("auto-generated-label", obj="Hole001")

    def test_unnamed_tongue_pocket(self):
        self.assertFinding("auto-generated-label", obj="Pocket007")

    # Debt 5 — ProjectVars.FloorHeight left at a test value. The value is
    # not lintable; the object is flagged for naming and tooltips.
    def test_projectvars_flagged(self):
        self.assertFinding("naming-convention", obj="VarSet006",
                           contains="Kind_Owner")
        self.assertFinding("naming-convention", obj="VarSet006",
                           contains="FloorHeight")

    # Debt 6 — all prototype VarSets predate the naming convention.
    def test_all_prototype_varsets_flagged(self):
        flagged = {f.obj for f in self.matching("naming-convention",
                                                contains="Kind_Owner")}
        expected = {"VarSet", "VarSet001", "VarSet002", "VarSet003",
                    "VarSet004", "VarSet005", "VarSet006"}
        self.assertTrue(expected <= flagged,
                        f"missing naming findings for {expected - flagged}")


class SessionTwelveBehavior(LinterFixtureTest):
    """Rule behavior beyond the §7 list, pinned against the same file."""

    FIXTURE = SESSION_12

    def test_symmetric_constraint_detected(self):
        # Socket_DT1 sketch still carries one Symmetric constraint.
        self.assertFinding("symmetry-constraint", obj="Sketch010")

    def test_mortise_width_at_caution_threshold(self):
        # TenonWidth = 6 in on an 8x8: exactly 75% — at the severing limit
        # (not over it), so advisory caution, not strict.
        self.assertFinding("caution-threshold", obj="Pocket001",
                           contains="TenonWidth")
        self.assertFinding("caution-threshold", obj="Pocket011",
                           contains="TenonWidth")
        self.assertFalse(self.matching("severing-limit"),
                         "75% is at the limit, not over it")

    def test_no_solid_face_references(self):
        # Assembly joints were built datum-to-datum per the workflow.
        self.assertFalse(self.matching("solid-face-reference"))

    def test_islands_strictly_interior(self):
        # Post-session-5 subtractive rework: island pockets are clean.
        self.assertFalse(self.matching("island-not-interior"))

    def test_own_dims_references_not_flagged(self):
        # A timber's own Dims bindings are legitimate.
        self.assertFalse(self.matching("cross-timber-dims-reference",
                                       obj="Sketch002"))

    def test_strict_findings_are_exactly_the_known_set(self):
        strict_objs = sorted(f.obj for f in self.findings
                             if f.severity == STRICT)
        self.assertEqual(strict_objs, [
            "Pocket004",              # Housing_DT1 length from JoistDims
            "Sketch003",              # Post housing width from BeamDims
            "Sketch009",              # DT housing width from JoistDims
            "Sketch010",              # DT socket position from JoistDims
            "Sketch014",              # Post2 housing width from BeamDims
            "Sketch018",              # debt 3: peg sketch from PostDims
            "Sketch019",              # debt 2: combined peg sketch
            "VarSet002",              # debt 1: MT1 spans 3 bodies
            "VarSet002",              # debt 1: MT1 drives both beam ends
        ])


class TimberTemplateControl(LinterFixtureTest):
    """The pristine template must be strict-clean."""

    FIXTURE = TEMPLATE

    def test_no_strict_findings(self):
        strict = [f for f in self.findings if f.severity == STRICT]
        self.assertEqual(strict, [])

    def test_advisories_still_reported(self):
        # Pre-convention names are advisory, never strict.
        self.assertTrue(self.matching("naming-convention"))
        self.assertTrue(all(f.severity == ADVISORY for f in self.findings))


class HousedMTTemplateControl(LinterFixtureTest):
    """The first library joint template (built Phase 1, sessions
    Part A–E) must lint completely clean — strict AND advisory. This is
    the library acceptance bar; if a linter change breaks this, either
    the rule is wrong or the template needs updating alongside it."""

    FIXTURE = JOINT_TEMPLATE

    def test_completely_clean(self):
        self.assertEqual([str(f) for f in self.findings], [])


if __name__ == "__main__":
    unittest.main()
