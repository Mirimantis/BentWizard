"""The completeness half of the template bar.

The library controls in test_linter.py prove these rules stay silent on
templates known to be complete. This module proves the other direction —
that they actually fire — because a completeness check that never
reports anything is exactly the false green it exists to prevent.

Run with:  python -m unittest discover -s tests
(stdlib only)
"""

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
import _repo_path  # noqa: E402, F401

from freecad.bentwizard import template_check  # noqa: E402
from freecad.bentwizard.fcstd import Expression, FcstdDocument  # noqa: E402
from freecad.bentwizard.linter import ADVISORY, STRICT, Model  # noqa: E402

LIBRARY = REPO_ROOT / "library"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
SESSION_12 = FIXTURES / "Joint_HouseMT_session_12.FCStd"
TEMPLATE = FIXTURES / "TimberTemplate.FCStd"

LIBRARY_TEMPLATES = sorted(LIBRARY.glob("*.FCStd"))


class LibraryIsShippable(unittest.TestCase):
    """Every shipped template clears the whole bar — the linter's rules,
    the skeleton, the file-stem contract, and a real TemplateSpec load.

    Globbed rather than listed: a template added to library/ without
    being added to a test list is precisely the file nothing checks.
    """

    def test_every_library_template_is_clean(self):
        self.assertTrue(LIBRARY_TEMPLATES, "library/ holds no templates")
        for path in LIBRARY_TEMPLATES:
            with self.subTest(template=path.name):
                findings = template_check.check(path)
                self.assertEqual([str(f) for f in findings], [])


class RulesActuallyFire(unittest.TestCase):
    """The session-12 prototype is a project model, not a template: four
    timbers, two joints, no frames at all. It lints with known findings
    and would pass a frames-only bar silently."""

    @classmethod
    def setUpClass(cls):
        cls.model = Model(FcstdDocument.from_file(SESSION_12))
        cls.findings = template_check.skeleton_findings(cls.model)
        cls.rules = {f.rule for f in cls.findings}

    def test_reports_the_wrong_timber_count(self):
        self.assertIn("template-timbers", self.rules)

    def test_reports_the_missing_single_joint_varset(self):
        self.assertIn("template-joint-varset", self.rules)

    def test_reports_the_missing_frames(self):
        self.assertIn("template-frame-set", self.rules)

    def test_missing_frames_are_strict(self):
        frame = [f for f in self.findings if f.rule == "template-frame-set"]
        self.assertTrue(frame)
        self.assertTrue(all(f.severity == STRICT for f in frame))

    def test_missing_companion_is_only_advisory(self):
        # A template without one still applies; it just cannot drive a
        # timber's Length from a layout distance.
        companion = [f for f in self.findings
                     if f.rule == "template-layout-companion"]
        self.assertTrue(companion)
        self.assertTrue(all(f.severity == ADVISORY for f in companion))

    def test_apply_joint_refuses_to_load_it(self):
        loads = template_check.load_findings(SESSION_12)
        self.assertEqual([f.rule for f in loads], ["template-loads"])
        self.assertEqual(loads[0].severity, STRICT)


class HalfBuiltTemplateIsCaught(unittest.TestCase):
    """The case the linter cannot see: a pristine timber document with
    nothing wrong in it and nothing joint-shaped in it either. Its lint
    is strict-clean (TimberTemplateControl pins that), so only the
    skeleton rules can tell it from a finished template."""

    @classmethod
    def setUpClass(cls):
        cls.model = Model(FcstdDocument.from_file(TEMPLATE))
        cls.findings = template_check.skeleton_findings(cls.model)

    def test_is_not_mistaken_for_a_template(self):
        self.assertTrue(
            [f for f in self.findings if f.severity == STRICT],
            "a document with no joint at all must not pass the skeleton bar")

    def test_names_the_missing_frames(self):
        self.assertIn("template-frame-set", {f.rule for f in self.findings})


class CompanionIsNotAJointVarSet(unittest.TestCase):
    """The companion declares itself with VarSet_Role, so it is never
    guessed at.

    The structural fallback used to call it a JOINT VarSet as soon as
    any geometry referenced it directly, and the template then failed to
    load with a count no author could act on ('found 2') — while the
    actual defect (geometry bound to the companion is not part of the
    joint and never gets cloned) went unnamed.
    """

    def test_the_shipped_companions_are_not_joint_varsets(self):
        for path in LIBRARY_TEMPLATES:
            with self.subTest(template=path.name):
                model = Model(FcstdDocument.from_file(path))
                joints = [vs.label for vs in model.joint_varsets()]
                self.assertEqual(len(joints), 1, joints)
                self.assertFalse([l for l in joints
                                  if l.startswith("Layout_")])

    def test_a_companion_binding_is_named_as_the_real_defect(self):
        """Proven against a hand-built model rather than a library file:
        the rule has to fire on the mistake, and no shipped template
        makes it."""
        model = Model(FcstdDocument.from_file(LIBRARY / "Joint_HousedMT.FCStd"))
        companion = template_check._companions(model)[0]
        # a frame reading the companion and nothing else
        frame = template_check._frames(model)[0]
        engine = frame.properties["ExpressionEngine"]
        original = list(engine.expressions)
        try:
            engine.expressions[:] = [
                Expression(".AttachmentOffset.Base.y",
                           f"<<{companion.label}>>.Stick_Allowance_FTF")]
            findings = template_check.rule_geometry_reads_the_joint_varset(model)
            self.assertEqual([f.rule for f in findings],
                             ["template-companion-binding"])
            self.assertEqual(findings[0].severity, STRICT)
            self.assertIn(companion.label, findings[0].message)
        finally:
            engine.expressions[:] = original
        # and restored to the consumed copy on the joint VarSet, silent
        self.assertEqual(
            template_check.rule_geometry_reads_the_joint_varset(model), [])


class StemContract(unittest.TestCase):
    """The file stem is the user-visible joint kind; a VarSet saying
    something else is a surprise waiting in a cut list."""

    def test_mismatch_is_reported(self):
        path = LIBRARY / "Joint_HousedMT.FCStd"
        model = Model(FcstdDocument.from_file(path))
        findings = template_check.stem_findings("Joint_BraceMT.FCStd", model)
        self.assertEqual([f.rule for f in findings],
                         ["template-kind-matches-stem"])
        self.assertEqual(findings[0].severity, ADVISORY)

    def test_the_shipped_stems_match(self):
        for path in LIBRARY_TEMPLATES:
            with self.subTest(template=path.name):
                model = Model(FcstdDocument.from_file(path))
                self.assertEqual(template_check.stem_findings(path, model), [])


class ReportFormat(unittest.TestCase):
    def test_clean_says_so_out_loud(self):
        report = template_check.format_report("x.FCStd", [])
        self.assertIn("Clean", report)

    def test_findings_are_grouped_by_what_to_do(self):
        findings = template_check.check(SESSION_12)
        report = template_check.format_report(SESSION_12, findings)
        self.assertIn("MUST FIX", report)
        self.assertIn("SHOULD FIX", report)


if __name__ == "__main__":
    unittest.main()
