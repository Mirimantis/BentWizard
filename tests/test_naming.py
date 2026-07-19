"""Tests for the naming helpers (freecad.bentwizard.naming).

Stdlib-only — runs under any Python. Pins the decided scheme: permanent
labels with a trailing serial segment; suggestion helpers only ever
touch that segment (the retired bent-number swap changed the FIRST
number it found, which mangled descriptive names — the regression these
tests guard).
"""

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
import _repo_path  # noqa: E402, F401 — this repo's code must win the import

from freecad.bentwizard import naming  # noqa: E402


class SplitSerialTest(unittest.TestCase):
    def test_trailing_segment_is_the_serial(self):
        self.assertEqual(naming.split_serial("T-Post-Level1-003"),
                         ("T-Post-Level1", "003"))
        self.assertEqual(naming.split_serial("T-TieBeam_decorative-007"),
                         ("T-TieBeam_decorative", "007"))

    def test_digit_inside_a_description_is_not_a_serial(self):
        # 'Level1' ends with a digit but is not an all-digit segment
        self.assertEqual(naming.split_serial("T-Post-Level1"),
                         ("T-Post-Level1", None))

    def test_no_serial_forms(self):
        self.assertEqual(naming.split_serial("T-Post"), ("T-Post", None))
        self.assertEqual(naming.split_serial("Post01"), ("Post01", None))
        self.assertEqual(naming.split_serial("007"), ("007", None))

    def test_legacy_member_id_splits_on_its_position(self):
        self.assertEqual(naming.split_serial("P2-1"), ("P2", "1"))

    def test_permissive_separators(self):
        # July 2026: dots, underscores, and spaces separate a serial too
        self.assertEqual(naming.split_serial("T-Post.Balcony.001"),
                         ("T-Post.Balcony", "001"))
        self.assertEqual(naming.split_serial("T_Post_004"),
                         ("T_Post", "004"))
        self.assertEqual(naming.split_serial("T Post 002"),
                         ("T Post", "002"))
        # a glued digit is still descriptive, whatever the separators
        self.assertEqual(naming.split_serial("T-Post.Level1"),
                         ("T-Post.Level1", None))


class NextSerialTest(unittest.TestCase):
    def test_starts_at_one(self):
        self.assertEqual(naming.next_serial([], "T-Post"), "T-Post-001")

    def test_counts_past_the_highest_existing(self):
        labels = ["T-Post-001", "T-Post-005", "T-Post-Level1-002"]
        self.assertEqual(naming.next_serial(labels, "T-Post"), "T-Post-006")
        # the Level1 family is separate
        self.assertEqual(naming.next_serial(labels, "T-Post-Level1"),
                         "T-Post-Level1-003")

    def test_taken_reserves_batch_suggestions(self):
        self.assertEqual(
            naming.next_serial(["T-Post-001"], "T-Post",
                               taken=["T-Post-002"]),
            "T-Post-003")

    def test_width_grows_past_999(self):
        self.assertEqual(naming.next_serial(["T-Post-999"], "T-Post"),
                         "T-Post-1000")


class SuccessorLabelTest(unittest.TestCase):
    def test_bumps_only_the_trailing_serial(self):
        labels = ["T-Post-Level1-003"]
        self.assertEqual(naming.successor_label(labels, "T-Post-Level1-003"),
                         "T-Post-Level1-004")

    def test_never_touches_interior_digits(self):
        # the old bent-number swap would have produced T-Post-Level2-...
        out = naming.successor_label(["T-Post-Level1-003"],
                                     "T-Post-Level1-003")
        self.assertTrue(out.startswith("T-Post-Level1-"), out)

    def test_appends_a_serial_when_missing(self):
        self.assertEqual(naming.successor_label([], "T-Post-Level1"),
                         "T-Post-Level1-001")

    def test_keeps_legacy_width(self):
        self.assertEqual(naming.successor_label(["P1-1", "P1-2"], "P1-1"),
                         "P1-3")

    def test_batch_taken(self):
        labels = ["T-Post-001", "T-Post-002"]
        first = naming.successor_label(labels, "T-Post-001")
        second = naming.successor_label(labels, "T-Post-002", taken=[first])
        self.assertEqual((first, second), ("T-Post-003", "T-Post-004"))

    def test_keeps_the_users_separator(self):
        # dotted family bumps with dots
        labels = ["T-Post.Balcony.001"]
        self.assertEqual(naming.successor_label(labels, "T-Post.Balcony.001"),
                         "T-Post.Balcony.002")
        # spaced family bumps with spaces
        self.assertEqual(naming.successor_label(["T Post 002"], "T Post 002"),
                         "T Post 003")

    def test_mixed_separator_families_share_serials(self):
        # 'T-Post.001' and 'T-Post-001' are one family: the scan counts
        # across separators so serials never collide, and an unspecified
        # separator adopts the family's own
        self.assertEqual(naming.next_serial(["T-Post.001"], "T-Post"),
                         "T-Post.002")

    def test_trailing_separator_names_the_separator(self):
        # 'T.Post.solarium.' means "append my serial with a dot" — the
        # separator is used, never doubled, and the existing family
        # counts (the shakedown bug: 'T.Post.solarium.-001')
        labels = ["T.Post.solarium.100"]
        self.assertEqual(naming.successor_label(labels, "T.Post.solarium."),
                         "T.Post.solarium.101")
        self.assertEqual(naming.next_serial([], "T.Post.solarium."),
                         "T.Post.solarium.001")

    def test_dot_is_the_default_separator(self):
        # no trailing separator, no family, no separator in the base:
        # the appended serial uses a dot
        self.assertEqual(naming.next_serial([], "Solarium"), "Solarium.001")
        # a separator already in the base wins over the default
        self.assertEqual(naming.next_serial([], "T-Post"), "T-Post-001")
        self.assertEqual(naming.next_serial([], "T.Post"), "T.Post.001")

    def test_bare_base_adopts_the_family_separator(self):
        # typing the base without serial or trailing separator still
        # lands in the family's style
        self.assertEqual(
            naming.successor_label(["T.Post.solarium.100"], "T.Post.solarium"),
            "T.Post.solarium.101")


class ReservedLabelCharsTest(unittest.TestCase):
    def test_clean_labels_pass(self):
        for label in ("T-Post-003", "T-Post.Balcony.001", "T Post (north)",
                      "T-Pfosten-Größe-004", "T-Post-#7-005", "T-Post-<x-006"):
            self.assertEqual(naming.reserved_in_label(label), "", label)

    def test_reserved_characters_reported(self):
        self.assertEqual(naming.reserved_in_label("T>Post"), ">")
        self.assertEqual(naming.reserved_in_label("T;Post\\x"), ";\\")
        self.assertEqual(naming.reserved_in_label("T-Post\na"), "\n")


class JointLabelTest(unittest.TestCase):
    def test_new_scheme_roundtrip(self):
        label = naming.joint_label("HousedMT", "001")
        self.assertEqual(label, "J-HousedMT-001")
        self.assertEqual(naming.parse_joint_label(label),
                         ("HousedMT", "001"))
        self.assertTrue(naming.is_joint_varset_label(label))

    def test_legacy_scheme_parses(self):
        self.assertEqual(naming.parse_joint_label("Joint_MT_B2a"),
                         ("MT", "B2a"))
        self.assertEqual(naming.parse_joint_label("Joint_Loft_DT_0a"),
                         ("Loft_DT", "0a"))
        self.assertTrue(naming.is_joint_varset_label("Joint_MT_B2a"))

    def test_non_joint_labels(self):
        self.assertIsNone(naming.parse_joint_label("TimberDims_T-Post-001"))
        self.assertIsNone(naming.parse_joint_label("J-nosegments"))
        self.assertFalse(naming.is_joint_varset_label("T-Post-001"))
        self.assertFalse(naming.is_joint_varset_label("Joints"))

    def test_kind_token_from_source(self):
        self.assertEqual(naming.kind_token_from_source("Joint_HousedMT"),
                         "HousedMT")
        self.assertEqual(naming.kind_token_from_source("J-ScarfJoint"),
                         "ScarfJoint")
        self.assertEqual(naming.kind_token_from_source("HousedMT"),
                         "HousedMT")


if __name__ == "__main__":
    unittest.main()
