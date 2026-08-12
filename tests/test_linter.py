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
import _repo_path  # noqa: E402, F401 — this repo's code must win the import

from freecad.bentwizard import naming  # noqa: E402
from freecad.bentwizard.fcstd import FcstdDocument, expression_refs  # noqa: E402
from freecad.bentwizard.linter import ADVISORY, STRICT, Model, lint  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"
LIBRARY = REPO_ROOT / "library"
SESSION_12 = FIXTURES / "Joint_HouseMT_session_12.FCStd"
TEMPLATE = FIXTURES / "TimberTemplate.FCStd"
# The library acceptance controls read library/ DIRECTLY. They used to
# read a fixture copy, which drifted: the copy predated the companion
# layout VarSet entirely, so the bar was being asserted against a
# template two conventions old. Every other test module already reads
# library/, and a duplicate that must be hand-refreshed is exactly the
# kind of thing that silently stops being refreshed.
JOINT_TEMPLATE = LIBRARY / "Joint_HousedMT.FCStd"
BUTT_TEMPLATE = LIBRARY / "Joint_Butt.FCStd"
WHD_TEMPLATE = LIBRARY / "Joint_WedgedHalfDovetail.FCStd"


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

    def test_dims_label_drift_flagged(self):
        # PostDims should be TDim_Post per the convention; the drifted
        # label is advisory (tools resolve structurally). Note the legacy
        # 'TimberDims_' prefix IS grandfathered — 'PostDims' carries
        # neither prefix, so it still reports.
        self.assertFinding("naming-convention", contains="TDim_Post")

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


class TemplateSkeletonCompleteness:
    """Every library template carries the same skeleton, and a lint of
    zero findings does NOT prove it is there.

    The linter is a correctness bar, not a completeness one: its frame
    rules only fire once frames exist, so a half-built template — two
    timbers and no frames at all — lints completely silent. That is a
    false green on the one test whose whole job is to say 'this template
    is fit to ship', and it matters most for Joint_Butt, which is the
    skeleton new templates are copied from.

    Mixed into every library control, so the assertions are proven
    against a template known to be complete rather than only against the
    one being authored. Failure messages name the build-doc part that
    creates the missing piece, so a red suite reads as a checklist.
    """

    # Two timbers, three frames: one Landing per role (the anchor's, and
    # the entering timber's end frame) plus the single Mate.
    EXPECTED_FRAMES = 3
    EXPECTED_LANDING = 2
    EXPECTED_MATE = 1

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.model = Model(FcstdDocument.from_file(cls.FIXTURE))

    # -- helpers ----------------------------------------------------------

    @property
    def frames(self):
        return [o for o in self.model.doc.objects.values()
                if o.is_type("Part::LocalCoordinateSystem")]

    def role_of(self, frame):
        return getattr(frame.prop(naming.FRAME_ROLE_PROP), "value", None)

    def frames_with_role(self, role):
        return [f for f in self.frames if self.role_of(f) == role]

    def varsets_of_kind(self, kind):
        return [vs for vs in self.model.varsets
                if self.model.kind.get(vs.name) == kind]

    # -- the skeleton -----------------------------------------------------

    def test_carries_two_timbers_each_with_dims(self):
        bodies = self.model.bodies
        self.assertEqual(
            len(bodies), 2,
            f"expected 2 timber bodies (the anchor and the entering "
            f"timber), got {[b.label for b in bodies]} — see Part A")
        missing = [b.label for b in bodies if b.name not in self.model.dims_of]
        self.assertEqual(
            missing, [],
            f"timber(s) with no Dims VarSet driving the base pad's "
            f"Length: {missing} — see Part A")

    def test_carries_joint_and_companion_varsets(self):
        joints = [vs for vs in self.model.varsets
                  if naming.parse_joint_label(vs.label)]
        self.assertEqual(
            len(joints), 1,
            f"expected exactly 1 joint VarSet labelled J-<Kind>-<serial>, "
            f"got {[vs.label for vs in self.model.varsets]} — see Part C")

        companions = [
            vs for vs in self.model.varsets
            if getattr(vs.prop(naming.VARSET_ROLE_PROP), "value", None)
            == naming.VARSET_ROLE_LAYOUT]
        self.assertEqual(
            len(companions), 1,
            f"expected exactly 1 companion layout VarSet carrying "
            f"{naming.VARSET_ROLE_PROP} = '{naming.VARSET_ROLE_LAYOUT}' "
            f"(resolved through the marker, never by label), got "
            f"{[vs.label for vs in companions]} — see Part B")

    def test_joint_varset_declares_its_abbrev(self):
        joints = [vs for vs in self.model.varsets
                  if naming.parse_joint_label(vs.label)]
        for vs in joints:
            abbrev = getattr(vs.prop(naming.TEMPLATE_ABBREV), "value", None)
            self.assertTrue(
                abbrev,
                f"{vs.label} declares no {naming.TEMPLATE_ABBREV} — "
                f"Apply-Joint rewrites exactly that suffix on every "
                f"feature label — see Part C")

    def test_carries_the_full_frame_set(self):
        self.assertEqual(
            len(self.frames), self.EXPECTED_FRAMES,
            f"expected {self.EXPECTED_FRAMES} joint frames, got "
            f"{[f.label for f in self.frames]} — see Parts D and E")

    def test_every_frame_declares_a_role(self):
        roleless = [f.label for f in self.frames
                    if self.role_of(f) not in naming.FRAME_ROLES]
        self.assertEqual(
            roleless, [],
            f"frame(s) with no valid {naming.FRAME_ROLE_PROP} property: "
            f"{roleless} — the role is Tier-2 data read by Preview, "
            f"Assemble and Duplicate, never a label substring — "
            f"see Parts D and E")

    def test_role_counts(self):
        landing = self.frames_with_role(naming.FRAME_ROLE_LANDING)
        mate = self.frames_with_role(naming.FRAME_ROLE_MATE)
        self.assertEqual(
            len(landing), self.EXPECTED_LANDING,
            f"expected {self.EXPECTED_LANDING} "
            f"'{naming.FRAME_ROLE_LANDING}' frames, one per role, got "
            f"{[f.label for f in landing]} — see Parts D and E")
        self.assertEqual(
            len(mate), self.EXPECTED_MATE,
            f"expected {self.EXPECTED_MATE} "
            f"'{naming.FRAME_ROLE_MATE}' frame — only the half that "
            f"enters carries one — got {[f.label for f in mate]} — "
            f"see Part E")

    def test_each_timber_owns_one_landing_frame(self):
        owners = {}
        for f in self.frames_with_role(naming.FRAME_ROLE_LANDING):
            body = self.model.owner.get(f.name)
            owners.setdefault(body.label if body else None, []).append(f.label)
        self.assertNotIn(
            None, owners,
            f"landing frame(s) outside any body: {owners.get(None)} — "
            f"activate the target body before creating a datum, or the "
            f"frame lands at the document root")
        self.assertEqual(
            sorted(owners), sorted(b.label for b in self.model.bodies),
            f"each timber gets exactly one landing frame; got {owners}")

    def test_mate_frame_is_driven_from_the_joint_varset(self):
        joints = {vs.name for vs in self.model.varsets
                  if naming.parse_joint_label(vs.label)}
        for frame in self.frames_with_role(naming.FRAME_ROLE_MATE):
            paths = {e.path: e.expression for e in frame.expressions}
            offset = ".AttachmentOffset.Base.z"
            self.assertIn(
                offset, paths,
                f"{frame.label} has no {offset} expression — the mate "
                f"frame's offset from the stick end IS the clear-span "
                f"allowance, and a typed literal would not follow an "
                f"author's edit — see Part E")
            refs = {t.name for t, _ in
                    expression_refs(paths[offset], self.model.doc)}
            self.assertTrue(
                refs & joints,
                f"{frame.label}{offset} does not reference the joint "
                f"VarSet ({paths[offset]!r}) — joint_members closes over "
                f"the literal <<J-Kind-serial>> token, which "
                f"<<Layout_J-Kind-serial>> does not contain, so a mate "
                f"frame reading the companion directly is not a joint "
                f"member — see Part E")


class HousedMTTemplateControl(TemplateSkeletonCompleteness, LinterFixtureTest):
    """The first library joint template (built Phase 1, sessions
    Part A–E) must lint completely clean — strict AND advisory. This is
    the library acceptance bar; if a linter change breaks this, either
    the rule is wrong or the template needs updating alongside it."""

    FIXTURE = JOINT_TEMPLATE

    def test_completely_clean(self):
        self.assertEqual([str(f) for f in self.findings], [])


@unittest.skipUnless(BUTT_TEMPLATE.exists(),
                     f"{BUTT_TEMPLATE.name} not built yet — see "
                     f"docs/butt-template-build.md")
class ButtTemplateControl(TemplateSkeletonCompleteness, LinterFixtureTest):
    """The jointless starter template. Same acceptance bar as any other
    library template — strict AND advisory clean — with no
    caution-threshold exemption, because it has no cuts to be cautious
    about. It is also the skeleton new templates are authored from, so
    anything it carries propagates: it must be silent, and it must be
    complete (see TemplateSkeletonCompleteness — a jointless template is
    exactly the case a lint-only bar cannot tell from a half-built one)."""

    FIXTURE = BUTT_TEMPLATE

    def test_completely_clean(self):
        self.assertEqual([str(f) for f in self.findings], [])

    def test_stays_jointless(self):
        """The defining property, and the one that would rot silently.

        Its value is that it carries the skeleton and nothing else; a
        pocket added here propagates into every template copied from it
        as exactly the phantom feature finding #12 warns about. Only the
        two base pads may be solid features.
        """
        solid = [o for o in self.model.doc.objects.values()
                 if o.type_id.startswith("PartDesign::")
                 and not o.is_type("PartDesign::Body")]
        pads = [o.label for o in solid if o.is_type("PartDesign::Pad")]
        joinery = [f"{o.label} ({o.type_id})" for o in solid
                   if not o.is_type("PartDesign::Pad")]
        self.assertEqual(
            joinery, [],
            f"the starter skeleton must carry no joinery geometry, "
            f"found: {joinery}")
        self.assertEqual(
            sorted(pads),
            sorted(f"Stick.{b.label}" for b in self.model.bodies),
            f"expected exactly the two stick pads, got {pads}")


class WedgedHalfDovetailTemplateControl(TemplateSkeletonCompleteness,
                                        LinterFixtureTest):
    """The Dutch anchor-beam joint, converted to frames-at-face and given
    its companion layout VarSet (August 2026).

    Its documented bar allows `caution-threshold` — it severs a real
    fraction of the post, deliberately — but nothing else. It carries
    the same three-frame skeleton as the other two, so the completeness
    assertions apply unchanged.
    """

    FIXTURE = WHD_TEMPLATE

    def test_no_strict_findings(self):
        strict = [str(f) for f in self.findings if f.severity == STRICT]
        self.assertEqual(strict, [])

    def test_only_caution_advisories(self):
        other = [str(f) for f in self.findings
                 if f.severity == ADVISORY and f.rule != "caution-threshold"]
        self.assertEqual(other, [])

    def test_publishes_its_allowance(self):
        """The point of the conversion: a timber entering this joint can
        drive its Length. Before the companion existed, Drive Length from
        Layout Distance refused outright.

        FTF is asserted structurally rather than by value — the template
        must publish an allowance consumed by the mate frame, and it is
        the frame placement that makes it true, not the arithmetic.
        """
        companion = [
            vs for vs in self.model.varsets
            if getattr(vs.prop(naming.VARSET_ROLE_PROP), "value", None)
            == naming.VARSET_ROLE_LAYOUT][0]
        for prop in ("Stick_Allowance_FTF", "Stick_Allowance_OC",
                     "Grid_Setback"):
            self.assertIsNotNone(
                companion.prop(prop),
                f"{companion.label} publishes no {prop}")
        # the layout triple must be one signed type: _OC goes negative
        # whenever the stick stops short of the grid line, and a Length
        # would clamp it to zero without complaint
        for prop in ("Stick_Allowance_FTF", "Stick_Allowance_OC",
                     "Grid_Setback"):
            self.assertEqual(
                companion.prop(prop).type_id, "App::PropertyDistance",
                f"{prop} must be App::PropertyDistance, not Length")


if __name__ == "__main__":
    unittest.main()
