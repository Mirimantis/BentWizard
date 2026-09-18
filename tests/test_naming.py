"""Pure-Python naming helpers: serials, joint labels, datum and component
labels, the UpperCamelCase property rule. No FreeCAD needed."""

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
import _repo_path  # noqa: E402, F401

from freecad.bentwizard import naming  # noqa: E402


class SerialTest(unittest.TestCase):
    def test_split_serial(self):
        self.assertEqual(naming.split_serial("T-Post-Level1-003"), ("T-Post-Level1", "003"))
        self.assertEqual(naming.split_serial("T-Post.Balcony.001"), ("T-Post.Balcony", "001"))
        self.assertEqual(naming.split_serial("T-Post-Level1"), ("T-Post-Level1", None))
        self.assertEqual(naming.split_serial("P2-1"), ("P2", "1"))

    def test_next_serial_starts_at_one_and_counts_past_the_highest(self):
        self.assertEqual(naming.next_serial([], "T-Post"), "T-Post-001")
        self.assertEqual(naming.next_serial(["T-Post-001", "T-Post-007"], "T-Post"), "T-Post-008")
        self.assertEqual(naming.next_serial(["T.Post.002"], "T.Post"), "T.Post.003")
        self.assertEqual(naming.next_serial([], "T.Post.solarium."), "T.Post.solarium.001")
        self.assertEqual(naming.next_serial([], "D_T-Post-001_YPos", sep="_"),
                         "D_T-Post-001_YPos_001")

    def test_successor_bumps_only_the_trailing_serial(self):
        labels = ["T-Post-Level1-003"]
        self.assertEqual(naming.successor_label(labels, "T-Post-Level1-003"), "T-Post-Level1-004")
        self.assertEqual(naming.successor_label([], "T-Post-Level1"), "T-Post-Level1-001")


class ReservedCharsTest(unittest.TestCase):
    def test_reserved(self):
        self.assertEqual(naming.reserved_in_label("a>b;c\\d\n"), "\n;>\\")
        self.assertEqual(naming.reserved_in_label("T-Post.001 (Ünicode) #<"), "")


class JointLabelTest(unittest.TestCase):
    def test_round_trip(self):
        self.assertEqual(naming.joint_label("HousedMT", "001"), "J-HousedMT-001")
        self.assertEqual(naming.parse_joint_label("J-HousedMT-001"), ("HousedMT", "001"))
        self.assertTrue(naming.is_joint_varset_label("J-HousedMT-000"))
        self.assertFalse(naming.is_joint_varset_label("Joint_MT_0a"))
        self.assertFalse(naming.is_joint_varset_label("J-Butt.000"))
        self.assertIsNone(naming.parse_joint_label("TDim_T-Post-001"))

    def test_template_stem_is_the_kind(self):
        self.assertEqual(naming.template_kind_from_stem("Joint_HousedMT"), "HousedMT")
        self.assertEqual(naming.template_kind_from_stem("HousedMT"), "HousedMT")
        self.assertEqual(naming.template_stem("HousedMT"), "Joint_HousedMT")
        self.assertEqual(naming.template_stem("Joint_HousedMT"), "Joint_HousedMT")


class PropertyNameTest(unittest.TestCase):
    def test_camel_case(self):
        for good in ("TenonLength", "WidthX", "PegCount", "HousingDepth2"):
            self.assertTrue(naming.is_camel_case(good), good)
        for bad in ("Tenon_Length", "tenonLength", "Housing Depth", "_X", "2Wide"):
            self.assertFalse(naming.is_camel_case(bad), bad)

    def test_ranges_and_accessors(self):
        self.assertEqual(naming.range_base("TenonLengthMin"), ("TenonLength", "Min"))
        self.assertEqual(naming.range_base("TenonLengthMax"), ("TenonLength", "Max"))
        self.assertIsNone(naming.range_base("TenonLength"))
        self.assertTrue(naming.is_accessor_property("MateWidthU"))
        self.assertFalse(naming.is_accessor_property("WidthU"))
        self.assertTrue(naming.is_template_metadata("TemplateSource"))
        self.assertFalse(naming.is_template_metadata("TenonLength"))


class DatumLabelTest(unittest.TestCase):
    def test_labels(self):
        self.assertEqual(naming.datum_label("T-Post-001", "EndA"), "D_T-Post-001_A")
        self.assertEqual(naming.datum_label("T-Post-001", "EndB"), "D_T-Post-001_B")
        self.assertEqual(naming.datum_label("T-Post-001", "YPos", "002"), "D_T-Post-001_YPos_002")
        self.assertEqual(naming.object_name("D_T-Post-001_A"), "D_T_Post_001_A")
        self.assertEqual(naming.object_name("1st"), "_1st")


class FeatureLabelTest(unittest.TestCase):
    def test_base_features(self):
        self.assertEqual(naming.section_sketch_label("T-Post-001"), "Section.Skt.T-Post-001")
        self.assertEqual(naming.stick_label("T-Post-001"), "Stick.T-Post-001")
        self.assertEqual(naming.dims_label("T-Post-001"), "TDim_T-Post-001")
        self.assertEqual(naming.dims_owner("TDim_T-Post-001"), "T-Post-001")
        self.assertIsNone(naming.dims_owner("Whatever"))

    def test_component_labels(self):
        self.assertEqual(naming.component_label("Mortise", "HousedMT", "001"),
                         "Mortise.HousedMT.001")
        self.assertEqual(naming.parse_component_label("Mortise.HousedMT.001"),
                         ("Mortise", "HousedMT", "001"))
        self.assertEqual(naming.parse_component_label("Tenon.Shoulder.HousedMT.001"),
                         ("Tenon.Shoulder", "HousedMT", "001"))
        self.assertIsNone(naming.parse_component_label("Mortise"))
        self.assertEqual(naming.retag_component_label("Mortise.HousedMT.000", "HousedMT", "007"),
                         "Mortise.HousedMT.007")
        self.assertEqual(naming.retag_component_label("Mortise", "HousedMT", "007"),
                         "Mortise.HousedMT.007")
        self.assertEqual(naming.boolean_label("Cutter", "Mortise.HousedMT.001"),
                         "Cut.Mortise.HousedMT.001")
        self.assertEqual(naming.boolean_label("Adder", "Tenon.HousedMT.001"),
                         "Fuse.Tenon.HousedMT.001")
        self.assertEqual(naming.mirror_label("Tenon.HousedMT.001"), "Mirror.Tenon.HousedMT.001")


if __name__ == "__main__":
    unittest.main()
