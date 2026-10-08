"""TemplateSpec: what the shipped templates declare, read without FreeCAD."""

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
import _repo_path  # noqa: E402, F401

from freecad.bentwizard.template import JointError, TemplateSpec  # noqa: E402

LIBRARY = REPO_ROOT / "library"


class HousedMTSpec(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec = TemplateSpec(LIBRARY / "Joint_HousedMT.FCStd")

    def test_kind_and_varset(self):
        self.assertEqual(self.spec.kind, "HousedMT")
        self.assertEqual(self.spec.varset_label, "J-HousedMT-000")

    def test_roles_host_first(self):
        self.assertEqual(self.spec.roles, ["T-Post-000", "T-Girt-000"])
        self.assertEqual(self.spec.host_role, "T-Post-000")
        self.assertEqual(self.spec.datum_face[self.spec.host_datum_label], "YPos")
        self.assertEqual(self.spec.datum_face[self.spec.mate_datum_label], "EndB")

    def test_components(self):
        comps = self.spec.components
        self.assertEqual([c["label"] for c in comps],
                         ["Mortise.HousedMT.000", "Tenon.HousedMT.000"])
        self.assertEqual([c["role"] for c in comps], ["Cutter", "Adder"])
        self.assertEqual([c["timber_role"] for c in comps], ["T-Post-000", "T-Girt-000"])
        self.assertEqual([c["order"] for c in comps], [1, 2])
        self.assertFalse(self.spec.is_starter)
        self.assertEqual(len(self.spec.components_for("T-Post-000")), 1)

    def test_declared_range_is_read(self):
        """A template may still declare a range (`<Name>Min`/`Max`, group
        Ranges); the shipped ones no longer do, so inject one into a copy."""
        import re
        import tempfile
        import zipfile
        with zipfile.ZipFile(LIBRARY / "Joint_HousedMT.FCStd") as z:
            entries = {n: z.read(n) for n in z.namelist()}
        xml = entries["Document.xml"].decode("utf-8")
        block = re.search(r'<Property name="TenonWidth" .*?</Property>', xml, re.S).group(0)
        bound = (block.replace('name="TenonWidth"', 'name="TenonWidthMax"')
                 .replace('group="Joint"', 'group="Ranges"'))
        bound = re.sub(r'value="[^"]*"', 'value="203.2"', bound, count=1)
        entries["Document.xml"] = xml.replace(block, block + bound).encode("utf-8")
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "Joint_HousedMT.FCStd"
            with zipfile.ZipFile(path, "w") as z:
                for name, data in entries.items():
                    z.writestr(name, data)
            tw = TemplateSpec(path).parameter("TenonWidth")
        self.assertIsNone(tw["min"])
        self.assertAlmostEqual(tw["max"], 203.2)

    def test_parameters(self):
        names = [p["name"] for p in self.spec.parameters]
        self.assertEqual(sorted(names), ["HousingDepth", "MortiseFit", "PegCount",
                                         "TenonLength", "TenonThickness", "TenonWidth"])
        tl = self.spec.parameter("TenonLength")
        self.assertAlmostEqual(tl["default"], 4 * 25.4)
        # no declared range: a through tenon must not be capped (Adam,
        # 2026-10-07)
        self.assertIsNone(tl["min"])
        self.assertIsNone(tl["max"])
        self.assertTrue(tl["doc"])
        self.assertFalse(self.spec.parameter("PegCount")["numeric"] is False)
        for p in self.spec.parameters:
            self.assertTrue(p["doc"], f"{p['name']} lacks a tooltip")


class ButtSpec(unittest.TestCase):
    def test_starter(self):
        spec = TemplateSpec(LIBRARY / "Joint_Butt.FCStd")
        self.assertEqual(spec.kind, "Butt")
        self.assertTrue(spec.is_starter)
        self.assertEqual(spec.components, [])
        self.assertEqual([p["name"] for p in spec.parameters], ["PegCount"])


class BadTemplate(unittest.TestCase):
    def test_not_a_template(self):
        with self.assertRaises(Exception):
            TemplateSpec(REPO_ROOT / "does-not-exist.FCStd")


if __name__ == "__main__":
    unittest.main()
